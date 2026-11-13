"""l1_cam.py - LEVEL 1 CAMERA field checks (LEVEL1.md stage 3). build.py calls checks(sc, spec, log) after every build and stores
the result in report.json["L1"]["checks"]["cam.<name>"]; tools/level1.py judges it. Every check re-measures the FINAL scene (the
cameras as they will render, every 2nd frame), independent of what the camera search believed:
  faces        every shot whose focus is a character shows its readable face: face grid >= 0.5, head inside the frame, lens within
               ~72 deg of the face normal on >= 75 % of the showable frames, never lost for > 10 frames in a row (creator bug
               '0:18 camera', R259: 0.5 s of ceiling / floor + a cropped body), and camera.unread() of the build's own report is clean
  geometry     the lens is never inside furniture, outside the set walls, < 0.2 m from a body or pressed against geometry
  empty_frames no frame that is mostly ceiling (> 40 %), only floor / ceiling / sky (>= 92 %), or shows nothing of its character
  tilt         roll <= 3 deg, looking up <= 30 deg, down <= 55 deg (top-down allowed for angle 'top', a body on the ground, inserts)
  jump_cuts    no cut onto the SAME focus with < 30 deg view change and < 1.4x size change (+ the engine's own cut gate)
  mode         the scene's camera mode (short.schema.md 7b) is what is on screen: zero cuts, cut rhythm, OTS geometry, crash zoom...
"""
import math, os
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view as w2c
import camera, rig

STEP = 2
LIM = {'face_share': 0.75, 'face_run_frames': 10, 'roll': 3.0, 'up': 30.0, 'down': 55.0, 'ceiling': 0.4, 'flat': 0.92, 'body_m': 0.2, 'near': 0.15}


def _top(o):
    while o.parent is not None: o = o.parent
    return o


def _shots(sc, log):
    ms = sorted(sc.timeline_markers, key=lambda m: m.frame); n = log.get('frames', sc.frame_end + 1); meta = log.get('cam_shots', {})
    return [{**meta.get(m.camera.name, {}), 'name': m.camera.name, 'cam': m.camera, 'f0': m.frame, 'f1': (ms[i + 1].frame - 1) if i + 1 < len(ms) else n - 1}
            for i, m in enumerate(ms) if m.camera is not None]


def _scan(sc, sh, cast):
    """Per sampled frame of one shot: camera pose, every character's head (in frame, face grid, screen height), a 6x10 ray grid
    of what the frame shows, and where the lens stands."""
    cam = sh['cam']; roots = {_top(ch.root): nm for nm, ch in cast.items()}; hb = {nm: camera._hb(ch.head_mesh) for nm, ch in cast.items()}
    parts = [(nm, o) for nm, ch in cast.items() for o in (ch.torso, ch.head_mesh, *ch.arms, *ch.legs)]; out = []
    b = camera._cb(); obst = camera.ROOM.get('obstacles') or []
    for f in list(range(sh['f0'], sh['f1'] + 1, STEP)):
        sc.frame_set(f); bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
        M = cam.matrix_world; P = M.translation.copy(); R = M.to_3x3(); fwd = (R @ Vector((0, 0, -1))).normalized(); right = (R @ Vector((1, 0, 0))).normalized()
        row = {'f': f, 'P': P, 'fwd': fwd, 'down': -math.degrees(math.asin(max(-1, min(1, fwd.z)))), 'roll': abs(math.degrees(math.asin(max(-1, min(1, right.z))))), 'heads': {}}
        for nm, ch in cast.items():
            hm = ch.head_mesh; Mh = hm.matrix_world; ps = [w2c(sc, cam, Mh @ Vector(c)) for c in hm.bound_box]; c = w2c(sc, cam, Mh.translation)
            ys = [p.y for p in ps]; face = camera._face_frame(sc, cam, ch, dg, *hb[nm])
            nrm = (Mh.to_3x3() @ Vector((0, -1, 0))).normalized()
            row['heads'][nm] = {'in': c.z > 0 and 0.03 < c.x < 0.97 and min(ys) > -0.02 and max(ys) < 1.02, 'face': face, 'h': max(ys) - min(ys),
                                'cos': nrm.dot((P - Mh.translation).normalized()), 'lying': camera._lying(ch), 'd': (Mh.translation - P).length, 'pos': Mh.translation.copy()}
        g = {'char': 0, 'ceil': 0, 'floor': 0, 'miss': 0, 'near': 0}; who = {}
        fr = cam.data.view_frame(scene=sc)
        for i in range(6):
            for j in range(10):
                u, v = (i + 0.5) / 6, (j + 0.5) / 10
                d = (R @ fr[2].lerp(fr[1], u).lerp(fr[3].lerp(fr[0], u), v)).normalized()
                ok, loc, nor, _, obj, _ = sc.ray_cast(dg, P, d, distance=200)
                if not ok or obj is None: g['miss'] += 1; continue
                if camera._of_char(obj):
                    g['char'] += 1; k = roots.get(_top(obj)); who[k] = who.get(k, 0) + 1; continue
                nm = obj.name.lower()
                if (loc - P).length < 0.25: g['near'] += 1
                if 'ceiling' in nm or (nor.z < -0.7 and loc.z > 2.0): g['ceil'] += 1
                elif any(k in nm for k in ('floor', 'ground', 'road', 'sidewalk', 'grass')) or (nor.z > 0.7 and loc.z < 0.08): g['floor'] += 1
        row['grid'] = {k: x / 60.0 for k, x in g.items()}; row['who'] = {k: x / 60.0 for k, x in who.items()}
        near = min(((camera._bbox_dist(P, o), nm) for nm, o in parts), default=(9.0, None))
        row['where'] = ('inside furniture' if any(x0 < P.x < x1 and y0 < P.y < y1 and P.z < top for x0, x1, y0, y1, top in obst)
                        else 'outside the set' if b and not (b[0] - 0.02 < P.x < b[1] + 0.02 and b[2] - 0.02 < P.y < b[3] + 0.02)
                        else 'under the floor' if P.z < 0.05
                        else f'{near[0]:.2f} m from {near[1]}' if near[0] < LIM['body_m']
                        else 'lens against geometry' if row['grid']['near'] > LIM['near'] else None)
        out.append(row)
    return out


def _run(flags):
    best = cur = 0
    for x in flags:
        cur = cur + 1 if x else 0; best = max(best, cur)
    return best * STEP


def _readable(h):
    return None if h['face'] is None else bool(h['in'] and h['face'] >= 0.5 and h['cos'] >= 0.3)


def _faces(S, vis):
    bad = []; worst = 1.0
    for sh in S:
        foc = sh.get('focus')
        if not foc: continue
        rd = [_readable(r['heads'][foc]) for r in sh['rows']]; rd = [x for x in rd if x is not None]
        if not rd: continue
        share = sum(rd) / len(rd); run = _run([not x for x in rd]); worst = min(worst, share)
        why = [f'face on {share:.0%} of the frames'] if share < LIM['face_share'] else []
        if run > LIM['face_run_frames']: why.append(f'face lost {run} frames in a row')
        why += [x for x in camera.unread(sh['name'], vis.get(sh['name'], {}), eyes=False) if x not in ('face not shown', 'back of a head')]   # the first is measured per frame above;
        # the second is about ANOTHER subject of a wide (two people facing each other: one of them is always seen from behind)
        if why: bad.append(f"{sh['name']} f{sh['f0']}-{sh['f1']} {foc}: {', '.join(why)}")
        if why and os.environ.get('L1DEBUG'):
            print('L1CAM faces', sh['name'], [(r['f'], r['heads'][foc]['in'], r['heads'][foc]['face'], round(r['heads'][foc]['cos'], 2), round(r['heads'][foc]['h'], 2)) for r in sh['rows']][::3])
    return {'ok': not bad, 'value': bad[:4] or round(worst, 2), 'limit': f"face share >= {LIM['face_share']}, lost <= {LIM['face_run_frames']} frames, unread() clean"}


def _geometry(S):
    bad = [f"{sh['name']} f{r['f']}: {r['where']}" for sh in S for r in sh['rows'] if r['where']]
    return {'ok': not bad, 'value': [bad[0], f'{len(bad)} frames'] if bad else 0, 'limit': 'lens outside furniture / bodies / walls'}


def _empty(S):
    bad = []
    for sh in S:
        for r in sh['rows']:
            g = r['grid']; foc = sh.get('focus')
            why = ('ceiling %.0f%%' % (100 * g['ceil']) if g['ceil'] > LIM['ceiling']
                   else 'only floor / ceiling / sky' if g['ceil'] + g['floor'] + g['miss'] >= LIM['flat']
                   else 'nothing of its character in frame' if foc and r['who'].get(foc, 0) == 0 and not r['heads'][foc]['in'] and r['heads'][foc]['face'] is not None else None)
            if why: bad.append(f"{sh['name']} f{r['f']}: {why}")
    return {'ok': not bad, 'value': [bad[0], f'{len(bad)} frames'] if bad else 0, 'limit': f"ceiling <= {LIM['ceiling']}, flat < {LIM['flat']}, subject in frame"}


def _tilt(S):
    bad = []; mx = [0.0, 0.0, 0.0]
    for sh in S:
        for r in sh['rows']:
            foc = sh.get('focus'); topdown = sh.get('angle') == 'top' or sh.get('kind') == 'insert' or (foc and r['heads'][foc]['lying'])
            mx = [max(mx[0], r['roll']), max(mx[1], -r['down']), mx[2] if topdown else max(mx[2], r['down'])]
            why = (f"roll {r['roll']:.1f}" if r['roll'] > LIM['roll'] else f"looks up {-r['down']:.0f} deg" if -r['down'] > LIM['up']
                   else f"looks down {r['down']:.0f} deg" if r['down'] > LIM['down'] and not topdown else None)
            if why: bad.append(f"{sh['name']} f{r['f']}: {why}")
    return {'ok': not bad, 'value': [bad[0], f'{len(bad)} frames'] if bad else [round(x, 1) for x in mx], 'limit': f"roll {LIM['roll']}, up {LIM['up']}, down {LIM['down']} deg"}


def _size(sc, cam, obj, f):
    sc.frame_set(f); bpy.context.view_layer.update()
    ys = [w2c(sc, cam, obj.matrix_world @ Vector(c)).y for c in obj.bound_box]
    return (cam.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized(), max(ys) - min(ys)


def _jumps(sc, S, cast, log):
    bad = [f'engine gate f{c}' for c in log.get('jump_cuts', [])]
    for a, b in zip(S, S[1:]):
        foc = (b.get('on') or [None])[0]
        if foc is None or foc not in (a.get('on') or []): continue
        obj = cast[foc].head_mesh if foc in cast else bpy.data.objects.get(foc)
        if obj is None: continue
        da, sa = _size(sc, a['cam'], obj, b['f0'] - 1); db, sb = _size(sc, b['cam'], obj, b['f0'])
        ang = math.degrees(math.acos(max(-1, min(1, da.dot(db))))); k = max(sa, sb) / max(1e-6, min(sa, sb))
        if ang < 30 and k < 1.4: bad.append(f"f{b['f0']} {a['name']} -> {b['name']} on {foc}: {ang:.0f} deg, size x{k:.2f}")
    return {'ok': not bad, 'value': bad[:4] or 0, 'limit': 'same focus: >= 30 deg or >= 1.4x'}


def _smooth(rows):
    """(largest view turn in deg, largest position jolt in m) between consecutive samples: a cut or a teleport reads as a spike."""
    turn = max([math.degrees(math.acos(max(-1, min(1, a['fwd'].dot(b['fwd']))))) for a, b in zip(rows, rows[1:])] or [0.0])
    jolt = max([(a['P'] - 2 * b['P'] + c['P']).length for a, b, c in zip(rows, rows[1:], rows[2:])] or [0.0])
    return round(turn, 1), round(jolt, 2)


def _in(sh, nm):
    xs = [r['heads'][nm]['in'] for r in sh['rows'] if r['heads'][nm]['face'] is not None]
    return sum(xs) / len(xs) if xs else 1.0


def _face(sh, nm):
    xs = [_readable(r['heads'][nm]) for r in sh['rows']]; xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 1.0


def _mode(sc, spec, log, S, cast):
    cm = spec.get('camera') or {}; cm = {'mode': cm} if isinstance(cm, str) else cm
    mode = cm.get('mode'); fps = spec.get('fps', 24); n = log.get('frames', 1); names = [c['name'] for c in spec['cast']]
    if not mode: return {'ok': True, 'value': 'no camera mode set (default grammar)', 'limit': '-'}
    hero = cm['hero'] if cm.get('hero') in cast else names[0]
    v = {'cuts': len(S) - 1}; why = []
    def need(cond, text):
        if not cond: why.append(text)
    travel = lambda rows: sum((a['P'] - b['P']).length for a, b in zip(rows, rows[1:]))
    if mode in ('follow_oneshot', 'chase_track'):
        need(len(S) == 1, f'{len(S) - 1} cuts (one shot wanted)'); sh = S[0]; rows = sh['rows']; on = [x for x in sh.get('on', []) if x in cast]
        need(bool(sh.get('follow_cam')), 'no follow path found (a fixed camera pans)')
        v['turn_deg'], v['jolt_m'] = _smooth(rows); need(v['turn_deg'] <= 12 and v['jolt_m'] <= 0.3, 'camera not smooth (turn <= 12 deg, jolt <= 0.3 m per sample)')
        subj = sum((a['heads'][on[0]]['pos'] - b['heads'][on[0]]['pos']).length for a, b in zip(rows, rows[1:])) if on else 0.0
        v['travel_m'] = round(travel(rows), 1); v['subject_m'] = round(subj, 1)
        need(v['travel_m'] >= 0.5 * subj and subj >= 3.0, 'the camera does not travel with a moving subject (>= 3 m, camera >= half of it)')
        v['in_frame'] = round(min([_in(sh, x) for x in on] or [0.0]), 2); need(v['in_frame'] >= 0.95, 'a subject head leaves the frame')
        if mode == 'follow_oneshot':
            v['face'] = round(_face(sh, hero), 2); need(v['face'] >= 0.9, 'the hero face is lost (>= 0.9 wanted)'); need(sh.get('focus') == hero, 'focus is not the hero')
        else:
            ds = [r['heads'][on[0]]['d'] for r in rows] if on else [1.0]; v['dist_ratio'] = round(max(ds) / max(1e-6, min(ds)), 2)
            need(len(on) == 2, 'not a pair'); need(v['dist_ratio'] <= 1.8, 'the camera lets the runners go (distance ratio <= 1.8)')
    elif mode == 'story_cuts':
        ln = sorted((sh['f1'] - sh['f0'] + 1) / fps for sh in S); med = ln[len(ln) // 2]; v.update(median_s=round(med, 2), max_s=round(ln[-1], 2), min_s=round(ln[0], 2))
        need(len(S) >= 3 and 1.0 <= med <= 2.2 and ln[-1] <= 3.2 and ln[0] >= 0.5, 'cut rhythm: median 1.0-2.2 s, every shot 0.5-3.2 s')
    elif mode == 'static_wide':
        need(len(S) == 1, f'{len(S) - 1} cuts (one static shot wanted)'); sh = S[0]; rows = sh['rows']; on = [x for x in sh.get('on', []) if x in cast]
        v['drift_m'] = round(max((r['P'] - rows[0]['P']).length for r in rows), 3)
        v['turn_deg'] = round(max(math.degrees(math.acos(max(-1, min(1, r['fwd'].dot(rows[0]['fwd']))))) for r in rows), 2)
        need(v['drift_m'] <= 0.08 and v['turn_deg'] <= 1.5, 'the camera moves (drift <= 8 cm, turn <= 1.5 deg)')
        v['in_frame'] = round(min([_in(sh, x) for x in on] or [0.0]), 2); need(v['in_frame'] >= 0.97 and len(on) >= 2, 'an actor leaves the frame')
        v['faces'] = round(min([_face(sh, x) for x in on] or [0.0]), 2); need(v['faces'] >= 0.5, 'an actor is not staged to the camera (face >= 0.5 of the shot)')
        v['head_h'] = round(min(r['heads'][x]['h'] for r in rows for x in on), 3) if on else 0; need(v['head_h'] >= 0.04, 'actors too small (head >= 4 % of the frame)')
    elif mode == 'ots_dialogue':
        ots = []
        for sh in S:
            on = [x for x in sh.get('on', []) if x in cast]
            if len(on) != 2: continue
            r = sh['rows'][len(sh['rows']) // 2]; A, B = r['heads'][on[0]], r['heads'][on[1]]; share = sum(x['who'].get(on[1], 0) for x in sh['rows']) / len(sh['rows'])
            if B['d'] < A['d'] and B['cos'] < 0.2 and 0.02 <= share <= 0.4 and _face(sh, on[0]) >= 0.75:
                ln = A['pos'] - B['pos'] if on[0] < on[1] else B['pos'] - A['pos']; q = r['P'] - (A['pos'] + B['pos']) / 2
                ots.append((sh, on[0], ln.x * q.y - ln.y * q.x > 0, share))
        v.update(ots_shots=len(ots), focus=[o[1] for o in ots], shoulder=[round(o[3], 2) for o in ots],
                 time_share=round(sum(o[0]['f1'] - o[0]['f0'] + 1 for o in ots) / max(1, n), 2))
        need(len(ots) >= 2 and len({o[1] for o in ots}) == 2, 'no shot / reverse shot (two over-the-shoulder shots with swapped focus)')
        need(len({o[2] for o in ots}) <= 1, 'the cameras cross the line of action (180-degree rule)')
        need(v['time_share'] >= 0.5, 'less than half of the scene is over the shoulder')
    elif mode == 'topdown_reveal':
        rv = [sh for sh in S if sh.get('reveal')]; need(bool(rv), 'no reveal shot')
        if rv:
            sh = rv[0]; rows = sh['rows']; on = [x for x in sh.get('on', []) if x in cast]
            v['down_deg'] = round(sum(r['down'] for r in rows) / len(rows)); v['len_s'] = round((sh['f1'] - sh['f0'] + 1) / fps, 2)
            v['in_frame'] = round(min([_in(sh, x) for x in on] or [0.0]), 2)
            falls = [a for _, a, _, _ in log.get('fall_spans', [])]
            need(v['down_deg'] >= 55, 'not top-down (>= 55 deg down)'); need(v['len_s'] >= 0.8, 'reveal shorter than 0.8 s'); need(v['in_frame'] >= 0.9, 'the subject leaves the frame')
            need(not falls or sh['f0'] >= min(falls), 'the reveal starts before the fall'); need(len(S) >= 2, 'nothing before the reveal')
    elif mode == 'punch_in':
        ps = [sh for sh in S if sh.get('punch') is not None]; need(bool(ps), 'no punch-in shot')
        if ps:
            sh = ps[0]; who = sh['focus']; fp = int(round(sh['punch'] * fps)); a, b = max(sh['f0'], fp - 5), min(sh['f1'], fp + 6)
            _, ha = _size(sc, sh['cam'], cast[who].head_mesh, a); _, hb = _size(sc, sh['cam'], cast[who].head_mesh, b)
            v.update(who=who, zoom=round(hb / max(1e-6, ha), 2), head_after=round(hb, 2), frames=b - a)
            need(v['zoom'] >= 1.4, 'no punch-in (the head grows >= 1.4x around the punchline)'); need(hb >= 0.22, 'not a close-up after the punch (head >= 22 % of the frame)')
            need(_face(sh, who) >= 0.9, 'the punchline face is not readable')
    elif mode == 'two_shot_react':
        two = [sh for sh in S if len([x for x in sh.get('on', []) if x in cast]) == 2 and sh.get('kind') != 'close']
        good = [sh for sh in two if all(_in(sh, x) >= 0.9 and _face(sh, x) >= 0.5 for x in sh['on'][:2])]
        re_ = [i for i, sh in enumerate(S) if sh.get('react') and sh.get('kind') == 'close']
        v.update(two_shots=len(two), both_faces=len(good), reactions=len(re_), two_share=round(sum(sh['f1'] - sh['f0'] + 1 for sh in two) / max(1, n), 2))
        need(two and len(good) == len(two), 'a two-shot does not show both faces'); need(len(re_) >= 2, 'fewer than 2 reaction close-ups')
        need(all(any(0 <= j < len(S) and S[j] in two for j in (i - 1, i + 1)) for i in re_), 'a reaction is not cut from / back to the two-shot')
        need(v['two_share'] >= 0.3, 'the two-shot holds < 30 % of the scene')
    else: why.append(f'unknown mode {mode}')
    return {'ok': not why, 'value': {**v, **({'why': why} if why else {})}, 'limit': mode}


def checks(sc, spec, log):
    S = _shots(sc, log)
    fx = [(o, o.hide_get()) for o in bpy.data.objects if o.name.startswith('VFX')]
    for o, _ in fx: o.hide_set(True)   # per-view-layer hiding survives animated hide_viewport keys and frame changes
    try: return _checks(sc, spec, log, S)
    finally:
        for o, hidden in fx: o.hide_set(hidden)


def _checks(sc, spec, log, S):
    if not S: return {'mode': {'ok': not (spec.get('camera') or {}), 'value': 'no shots', 'limit': '-'}}
    cast = dict(rig.CAST)
    for sh in S:
        on = sh.get('on') or []; sh['focus'] = on[0] if on and on[0] in cast else None; sh['rows'] = _scan(sc, sh, cast)
    out = {'faces': _faces(S, log.get('visibility', {})), 'geometry': _geometry(S), 'empty_frames': _empty(S), 'tilt': _tilt(S),
           'jump_cuts': _jumps(sc, S, cast, log), 'mode': _mode(sc, spec, log, S, cast)}
    print('L1CAM', {k: (x['ok'], x['value']) for k, x in out.items()})
    return out
