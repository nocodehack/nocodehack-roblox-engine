"""l1_move.py - LEVEL 1 MOVEMENT field checks (LEVEL1.md section 1). build.py calls checks(sc, spec, log) after every build and
stores the result in report.json["L1"]. Each check: {'ok': bool, 'value': worst measured, 'limit': bound, 'where': first offender}.

GAIT (every walk/run span of log['walks']; arms measured against the chest, legs against the root; an arm that HOLDS a prop
or plays an authored pose/anim/talk of the story is not a gait arm). Each value is the worst span, judged on its own limit:
  gait.arm_swing    half range of an arm's forward angle over the stride frames (deg)       walk 6..34, run 15..70
  gait.zombie       a free arm raised past the gait range (walk 40, run 75 deg), or BOTH free arms > 18 deg forward at once
  gait.stiff_arm    frames a free arm stays frozen >= 12 deg off the hang while the legs step      <= 9
  gait.arm_out      a free arm's sideways angle (deg)                                       <= 22
  gait.leg_spread   angle between the two legs (deg): scissor legs                          walk <= 58 (stride <= 29 deg), run <= 120
  gait.leg_out      a leg's sideways angle (deg)                                            walk <= 14, run <= 30 (banked corners)
  gait.bob          root height range over the span (m)                                     walk <= 0.11, run <= 0.30
  gait.shuffle      longest stretch of stepping in place inside a walk (launch turn, fallback steps), s   <= 0.85
  gait.cam_loom     toward a close camera (< 4 m): head distance / nearest free hand or foot distance; a looming block
                    limb reads as a zombie reach                                             <= 1.45
crowd.overlap       deepest overlap between body parts of two different characters over the scene (m)   <= 0.03
throw.* (log['throws'], written by the throw beat):
  throw.arc     the flight is ballistic: horizontal speed constant, vertical acceleration = -g (relative error)   <= 0.03
  throw.hand    the flying prop inside any arm / torso / head, from 3 frames after the release to the frame before it arrives (m)  <= 0.02
  throw.catch   distance of the catcher's hand point from the prop at the catch and 4 frames later (m)            <= 0.03
  throw.end     an uncaught prop ends resting on a surface: height above it / still moving (m)                    <= 0.05
  throw.done    every throw beat of the story was keyed (no "not holding it" / unknown target)"""
import math
import os
import numpy as np
import bpy
from mathutils import Vector
import interact as ia, rig, space

S = ia.S
LIM = {'walk': {'swing': (6.0, 34.0), 'spread': 58.0, 'bob': 0.11, 'raise': 40.0, 'leg_out': 14.0},
       'run': {'swing': (15.0, 70.0), 'spread': 120.0, 'bob': 0.30, 'raise': 75.0, 'leg_out': 30.0}}
ZOMBIE_BOTH, ARM_OUT, LEG_OUT, LOOM, LOOM_DIST, OVERLAP = 18.0, 22.0, 14.0, 1.45, 4.0, 0.03
SHUFFLE_S, STIFF_FR = 0.85, 9.0


def _angles(ref, piv):
    """(forward, sideways) angle in degrees of a limb's axis in ref's frame: 0 = hanging, + = toward the front (-Y)."""
    d = ref.matrix_world.to_3x3().inverted() @ (piv.matrix_world.to_3x3() @ Vector((0, 0, -1)))
    d.normalize()
    return math.degrees(math.atan2(-d.y, -d.z)), math.degrees(math.asin(max(-1.0, min(1.0, d.x))))


def _tip(piv, side):
    return piv.matrix_world @ Vector((side * 0.5 * S, 0, -ia.TIP * S))


def _busy_arms(spec, log, fps):
    """{(who, hand): [(f0, f1)]} frames where an arm is not a gait arm: it holds a prop (log['holds']) or the story gave the
    character a pose / anim / talk gesture / throw there."""
    out = {}
    for who, hand, _, f0, f1 in log.get('holds', []):
        out.setdefault((who, hand), []).append((f0 - 30, f1 + 8))   # the reach starts before the hold
    for b in spec.get('beats', []):
        if b.get('auto'): continue
        if any(k in b for k in ('pose', 'anim', 'talk', 'wiggle', 'throw', 'give', 'attack', 'block')):
            f = round(b['t'] * fps); dur = round((b.get('loop') or b.get('talk') or 1.0) * fps)
            for h in 'RL': out.setdefault((b['who'], h), []).append((f - 8, f + dur + 8))
    for sp in log.get('sit_spans', []):   # walking INTO a seat: the arms belong to the sit from the last steps on
        for h in 'RL': out.setdefault((sp[0], h), []).append((sp[1] - 12, sp[2] + 12))
    for t in log.get('throws', []):
        out.setdefault((t['who'], t['hand']), []).append((t['f_wind'], t['f_release'] + 16))
        if isinstance(t['to'], str):
            for h in 'RL': out.setdefault((t['to'], h), []).append((t['f_end'] - 14, t['f_end'] + 16))
    return out


def sample(sc, cast, n):
    """Per frame, per character: arm/leg angles, root, head, limb tips, part OBBs, camera position."""
    rows = []
    for f in range(n):
        sc.frame_set(f); bpy.context.view_layer.update()
        cam = sc.camera.matrix_world.translation.copy() if sc.camera else None
        row = {'cam': cam}
        for name, ch in cast.items():
            parts = [ch.torso, ch.head_mesh] + [next(o for o in p.children if o.type == 'MESH') for p in list(ch.shoulders) + list(ch.hips)]
            row[name] = {
                'arm': {h: _angles(ch.upper, ch.arm[h]) for h in 'RL'}, 'leg': {h: _angles(ch.root, ch.leg[h]) for h in 'RL'},
                'root': ch.root.matrix_world.translation.copy(), 'head': ch.head_mesh.matrix_world.translation.copy(),
                'hand': {h: _tip(ch.arm[h], rig.SIDE[h]) for h in 'RL'}, 'foot': {h: ch.leg[h].matrix_world @ Vector((0, 0, -2 * S)) for h in 'RL'},
                'low': min((o.matrix_world @ Vector(c)).z for o in parts for c in o.bound_box),
                'obb': [(o.name, ia._obb(o.matrix_world, *space.local_bounds(o))) for o in parts]}
        rows.append(row)
    return rows


def gait(rows, spec, log, fps):
    """One entry per gait check: the worst span as value / its own limit (walk and run spans have their own limits)."""
    W = {}   # check -> (ratio, value, limit, where)
    def up(k, v, lim, where):
        r = v / lim
        if k not in W or r > W[k][0]: W[k] = (r, round(v, 2), lim, where)
    for k in ('arm_swing', 'zombie', 'stiff_arm', 'arm_out', 'leg_spread', 'leg_out', 'bob', 'shuffle', 'cam_loom'): up(k, 0.0, 1.0, '')
    busy = _busy_arms(spec, log, fps)
    def free(who, h, f): return not any(a <= f <= b for a, b in busy.get((who, h), ()))
    for w in log.get('walks', []):
        who, f0, f1 = w['who'], max(0, w['f0']), min(len(rows) - 1, w['f1'])
        if f1 - f0 < 3 or who not in rows[0]: continue
        kind = 'run' if w.get('run') else 'walk'; L = LIM[kind]; tag = f"{who} {kind} f{f0}-{f1}"
        R = [rows[f][who] for f in range(f0, f1 + 1)]
        spd = [0.0] + [(R[k]['root'].xy - R[k - 1]['root'].xy).length * fps for k in range(1, len(R))]
        top = sorted(spd)[int(0.8 * (len(spd) - 1))]
        mv = {k for k in range(len(R)) if spd[k] > max(0.5 * top, 0.5 * S)}   # stride frames (not the planted start/stop steps and turns)
        zs = [r['root'].z for r in R]; up('bob', max(zs) - min(zs), L['bob'], tag)
        # SHUFFLE: the longest stretch of stepping without travelling (launch turn, fallback steps) inside the walk
        run_ = best = 0
        for k in range(len(R)):
            run_ = run_ + 1 if k not in mv else 0; best = max(best, run_)
        if top > 2.0 * S: up('shuffle', best / fps, SHUFFLE_S, f'{tag} ({best} frames in place)')
        for h in 'RL':
            fa = [(k, R[k]['arm'][h]) for k in range(len(R)) if free(who, h, f0 + k)]
            if not fa: continue
            st = [a[0] for k, a in fa if k in mv]
            if len(st) >= 8 and w.get('stride', True):
                amp = (max(st) - min(st)) / 2; up('arm_swing', amp, L['swing'][1], f'{tag} {h}')
                if amp < L['swing'][0]: up('arm_swing', 2 * L['swing'][1], L['swing'][1], f'{tag} {h} too still: {amp:.1f} deg')
            for k, a in fa:
                up('arm_out', abs(a[1]), ARM_OUT, f'{tag} {h} f{f0 + k}')
                up('zombie', abs(a[0]), L['raise'], f'{tag} {h} f{f0 + k} raised')
            # STIFF: a free arm held off the hang (>= 12 deg) without moving while the legs step for 10+ frames
            run_ = 0
            for i in range(1, len(fa)):
                (k0, a0), (k1, a1) = fa[i - 1], fa[i]
                legs = max(abs(R[k1]['leg'][s][0] - R[k0]['leg'][s][0]) for s in 'RL')
                still = k1 == k0 + 1 and abs(a1[0] - a0[0]) < 0.3 and abs(a1[1] - a0[1]) < 0.3 and math.hypot(*a1) >= 12.0
                run_ = run_ + 1 if still and (legs > 0.5 or run_) else 0
                up('stiff_arm', float(run_), STIFF_FR, f'{tag} {h} held at {a1[0]:.0f} deg, f{f0 + k1}')
        both = [f0 + k for k in range(len(R)) if free(who, 'R', f0 + k) and free(who, 'L', f0 + k)
                and min(R[k]['arm']['R'][0], R[k]['arm']['L'][0]) > ZOMBIE_BOTH]
        if both: up('zombie', L['raise'] * len(both) / 2.0, L['raise'], f'{tag} both arms forward f{both[0]}-{both[-1]} ({len(both)} frames)')
        for k, r in enumerate(R):
            up('leg_spread', abs(r['leg']['R'][0] - r['leg']['L'][0]), L['spread'], f'{tag} f{f0 + k}')
            up('leg_out', max(abs(r['leg'][h][1]) for h in 'RL'), L['leg_out'], f'{tag} f{f0 + k}')
            cam = rows[f0 + k]['cam']
            if cam is None or k not in mv: continue
            v = (r['root'].xy - R[k - 1]['root'].xy); to = (cam.xy - r['root'].xy); d = (cam - r['head']).length
            if d < LOOM_DIST and v.length > 1e-6 and to.length > 1e-6 and v.normalized().dot(to.normalized()) > 0.6:
                tips = [r['hand'][h] for h in 'RL' if free(who, h, f0 + k)] + [r['foot'][h] for h in 'RL']
                up('cam_loom', d / max(0.05, min((cam - t).length for t in tips)), LOOM, f'{tag} f{f0 + k} cam {d:.1f} m')
    return {'gait.' + k: {'ok': r <= 1.0001, 'value': v, 'limit': lim, 'where': where} for k, (r, v, lim, where) in W.items()}


def crowd(rows, log, fps):
    """Deepest overlap between body parts of two different characters (OBB separating axes), every frame. A handoff's two
    hands meet on the prop and a fight strike lands on the target: those are contacts, measured by their own gates."""
    names = [k for k in rows[0] if k != 'cam']; worst = (0.0, '')
    touch = set()   # frames where two characters are meant to touch
    for t in log.get('touch_spans', []): touch |= {(a, b, f) for a, b in ((t[0], t[1]), (t[1], t[0])) for f in range(t[2], t[3] + 1)}
    for t in log.get('fight', []):   # a landed strike (error_cm is the fight gate's own measure): attacker and target touch from the wind-up's end to the recoil
        f_ = round(t['t'] * fps); touch |= {(a, b, f) for a, b in ((t['who'], t['target']), (t['target'], t['who'])) for f in range(f_ - 6, f_ + 21)}
    for f, row in enumerate(rows):
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if (row[a]['root'].xy - row[b]['root'].xy).length > 2.6 or (a, b, f) in touch: continue
                for na, oa in row[a]['obb']:
                    for nb, ob in row[b]['obb']:
                        d = ia.obb_depth(oa, ob)
                        if d > worst[0]: worst = (d, f'{na} x {nb} f{f}')
    return {'crowd.overlap': {'ok': worst[0] <= OVERLAP, 'value': round(worst[0], 3), 'limit': OVERLAP, 'where': worst[1]}}


def throws(sc, cast, log, n, fps):
    """arc: every free-flight frame pair obeys gravity and a constant horizontal speed; hand: the flying prop is never inside
    an arm, torso or head (thrower's releasing arm: after the 2 frames it needs to leave the hand; the hit target: the hit
    frame itself); catch: the catcher's hand point is on the prop at the catch and 4 frames later; end: a prop that was not
    caught rests on a surface (not in the air) at the scene end."""
    out = {}; W = {'arc': (0.0, ''), 'hand': (0.0, ''), 'catch': (0.0, ''), 'end': (0.0, '')}
    def up(k, v, where):
        if v > W[k][0]: W[k] = (round(v, 3), where)
    for t in log.get('throws', []):
        pr = bpy.data.objects[t['prop']]; ms = [o for o in pr.children_recursive if o.type == 'MESH']
        f0, f1 = t['f_release'], min(t['f_end'], n - 1); tag = f"{t['who']} -> {t['to']} {t['prop']} f{f0}-{f1}"
        P = []
        for f in range(f0, f1 + 1):
            sc.frame_set(f); bpy.context.view_layer.update(); P.append(pr.matrix_world.translation.copy())
            if f0 + 2 < f < f1:
                pts = np.concatenate([ia.world_pts(o) for o in ms])
                for name, ch in cast.items():
                    for part in [ch.torso, ch.head_mesh] + [ia.limb_mesh(pv) for pv in ch.arms_piv]:
                        # a held prop sits ON the hand point, so it enters the catching arm's end block on the last 2 frames
                        if t['kind'] == 'catch' and name == t['to'] and part is ia.limb_mesh(ch.arm[t['catch_hand']]) and f >= f1 - 2: continue
                        d = ia._pts_depth(pts, part.matrix_world, *space.local_bounds(part))
                        up('hand', float(d), f'{tag}: in {part.name} f{f}')
        if len(P) < 5: up('arc', 9.0, f'{tag}: flight of {len(P) - 1} frames'); continue
        st = [b - a for a, b in zip(P[1:], P[2:])]   # P[0] = in the hand
        mean = sum((v.xy for v in st), Vector((0, 0))) / len(st)
        up('arc', max((v.xy - mean).length for v in st) / max(mean.length, 1e-6), f'{tag}: horizontal speed not constant')
        acc = [(b.z - a.z) * fps * fps for a, b in zip(st, st[1:])]
        up('arc', max(abs(a + 9.81) for a in acc) / 9.81, f'{tag}: vertical acceleration {min(acc):.1f}..{max(acc):.1f} m/s2')
        if max(p.z for p in P) < max(P[0].z, P[-1].z) - 1e-4 and t['kind'] == 'catch': up('arc', 1.0, f'{tag}: no rise')
        if t['kind'] == 'catch':
            ch = cast[t['to']]; pv = ch.arm[t['catch_hand']]
            for f in (f1, min(n - 1, f1 + 4)):
                sc.frame_set(f); bpy.context.view_layer.update()
                tip = np.array(_tip(pv, rig.SIDE[t['catch_hand']]))
                pts = np.concatenate([ia.world_pts(o) for o in ms]); lo, hi = pts.min(0), pts.max(0)
                gap = float(np.linalg.norm(np.maximum(0, np.maximum(lo - tip, tip - hi))))   # hand point to the prop's box
                up('catch', gap, f'{tag}: hand {gap * 100:.1f} cm from the prop f{f}')
        else:
            # judged where it has come to rest: the scene end, or the frame before somebody picks it up again
            fe = min([n - 1] + [h[3] - 1 for h in log.get('holds', []) if h[2] == t['prop'] and h[3] > f1])
            sc.frame_set(fe); bpy.context.view_layer.update()
            base = min((o.matrix_world @ Vector(c)).z for o in ms for c in o.bound_box); p = pr.matrix_world.translation.copy()
            sc.frame_set(fe - 1); bpy.context.view_layer.update()
            moving = (pr.matrix_world.translation - p).length
            o = Vector((p.x, p.y, base + 0.03)); air = base; dg = bpy.context.evaluated_depsgraph_get()
            for _ in range(8):   # the first surface under the prop that is not the prop itself
                hit, loc, _n, _i, ob, _m = sc.ray_cast(dg, o, Vector((0, 0, -1)), distance=6.0)
                if not hit: break
                if ob.original in ms or ob in ms: o = loc - Vector((0, 0, 0.002)); continue
                air = min(air, max(0.0, base - loc.z)); break
            if os.environ.get('L1_WHO'): print('THROWZ', t['kind'], f1, fe, [(ff, round((sc.frame_set(ff) or 1) and pr.matrix_world.translation.z, 2)) for ff in range(f1, fe + 1, 5)])
            if os.environ.get('L1_WHO'):
                for ff in (f0, fe):
                    sc.frame_set(ff); bpy.context.view_layer.update()
                    print('THROWGEO', ff, 'origin z %.3f' % pr.matrix_world.translation.z, [(o.name, round(min((o.matrix_world @ Vector(c)).z for c in o.bound_box), 3), round(max((o.matrix_world @ Vector(c)).z for c in o.bound_box), 3), tuple(round(v, 2) for v in o.location), o.parent.name if o.parent else None) for o in ms])
                sc.frame_set(fe); bpy.context.view_layer.update()
            if os.environ.get('L1_WHO'): print('THROWEND', t['prop'], tuple(round(v, 2) for v in p), round(base, 3), round(air, 3), [o.name for o in ms][:2])
            up('end', max(air, moving), f'{tag}: ends {air:.2f} m above a surface, moving {moving:.3f} m/frame (f{fe})')
    if log.get('throws'):
        out['throw.arc'] = {'ok': W['arc'][0] <= 0.03, 'value': W['arc'][0], 'limit': 0.03, 'where': W['arc'][1]}
        out['throw.hand'] = {'ok': W['hand'][0] <= 0.02, 'value': W['hand'][0], 'limit': 0.02, 'where': W['hand'][1]}
        if any(t['kind'] == 'catch' for t in log['throws']):
            out['throw.catch'] = {'ok': W['catch'][0] <= 0.03, 'value': W['catch'][0], 'limit': 0.03, 'where': W['catch'][1]}
        if any(t['kind'] != 'catch' for t in log['throws']):
            out['throw.end'] = {'ok': W['end'][0] <= 0.05, 'value': W['end'][0], 'limit': 0.05, 'where': W['end'][1]}
    return out


def checks(sc, spec, log):
    fps = sc.render.fps / sc.render.fps_base
    n = int(log.get('frames') or sc.frame_end + 1)
    cast = {c['name']: rig.CAST[c['name']] for c in spec['cast'] if c['name'] in rig.CAST}
    rows = sample(sc, cast, n)
    out = gait(rows, spec, log, fps)
    out.update(crowd(rows, log, fps))
    out.update(throws(sc, cast, log, n, fps))
    n_thr = sum(1 for b in spec.get('beats', []) if 'throw' in b)
    if n_thr != len(log.get('throws', [])):
        out['throw.done'] = {'ok': False, 'value': f"{len(log.get('throws', []))} of {n_thr} throw beats keyed", 'limit': 'all'}
    import os
    if os.environ.get('L1_WHO'):   # root height, lowest foot point and xy of one character over the whole scene (a pop / float outside the walk spans)
        for f in range(n):
            r_ = rows[f][os.environ['L1_WHO']]
            print('L1ROOT', f, '%.3f %.3f %.2f %.2f' % (r_['root'].z, min(r_['foot'][h].z for h in 'RL'), r_['root'].x, r_['root'].y), 'low %.3f' % r_['low'])
    if os.environ.get('L1_DUMP'):   # per-frame gait numbers of every walk span (debugging a flagged walk)
        for w in log.get('walks', []):
            for f in range(max(0, w['f0']), min(n - 1, w['f1']) + 1):
                r = rows[f][w['who']]; c = rows[f]['cam']
                print('L1DUMP', w['who'], f, 'armR %6.1f %6.1f armL %6.1f %6.1f legR %6.1f %6.1f legL %6.1f %6.1f z %.3f camd %.2f xy %.2f %.2f' % (
                    *r['arm']['R'], *r['arm']['L'], *r['leg']['R'], *r['leg']['L'], r['root'].z, (c - r['head']).length if c else -1, r['root'].x, r['root'].y))
    return out
