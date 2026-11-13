"""camera.py - shot grammar for 9:16 Roblox shorts (reference defaults: camera at head height, slight high angle, always pushing in).
shot(sc, name, f0, f1, kind, subjects, ...) builds a camera from the shot SIZE (frame height at the subject, widened so
several subjects fit the 9:16 WIDTH), scores 15 candidate angles, binds it with a marker, keys a push-in, optionally tracks.
Candidate score = worst target visibility + 0.25 mean visibility
                  - 6 x (screen area above 15%) for every occluder (other characters, the subjects' own arms)
                  - 1.0 if the camera is closer than 1.2 m to any character, - 2.0 if outside the room bounds
                  - 30-degree cut rule penalty against the previous camera."""
import math, os
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
import interact as ia

S = ia.S
# kind -> (frame height at the subject in metres, aim height in studs above the floor)
SIZES = {'close': (1.3, 4.62), 'medium': (2.7, 3.7), 'full': (4.2, 2.8), 'wide': (6.5, 2.8), 'insert': (0.9, None)}   # close: head ~60 % (reference)
LAST = {'cam': None}
HIST = {}   # shot name -> (azimuth, pitch) of its chosen camera, in shot order (variety rule)
RING_EXTRA = []
SAFE_KEYS = set()            # safe high-corner spots: always scored in stage 2 (they must not crowd out the regular finalists)              # extra azimuths for a retry (shot() fills it when the first choice is poor)
ROOM = {'bounds': None}      # (xmin, xmax, ymin, ymax) metres, set by build; 'cam' = where a CAMERA may stand (build widens it
                             # past an OPEN side of a set: the film camera stands outside the missing fourth wall)


def _cb():
    return ROOM.get('cam') or ROOM['bounds']


LOW_POSES = ('proud', 'cheer', 'angry', 'shock', 'fist_pump_R', 'hands_up', 'facepalm_R', 'facepalm_L', 'recoil', 'gloat')   # facepalm reads from below
STRONG = ('shock', 'scream', 'scared', 'cry', 'angry', 'laugh', 'evil', 'joy', 'sad', 'worry', 'facepalm', 'hands_head', 'cover_mouth')


def grammar(shots, beats, cast, events, T_end, fps, spec, notes):
    """EDITOR PASS over the scene's shot list (authored shots + rhythm pieces), pure data. Authored shots keep their subject,
    size and time; the engine adds the grammar a writer leaves out (critic R195/R200/R206: 4.0 vs reference 8.0 - every homework
    shot was authored and <= 2.2 s, so the rhythm splitter, the only place grammar lived, ran once in 12 shots):
      1 ESTABLISHING: every scene (= location) opens on a high wide: an authored opening wide gets angle 'high', else a 0.9 s
        high wide of the cast is put before the first shot (build drops it again if no camera reads it).
      2 STORY-OBJECT INSERT: a prop that changes hands or is looked at (events = [(t, prop, 'grab' | 'look')]) gets its own ~0.8 s insert, cut
        INTO the shot that covers it; once per prop, two per scene.
      3 REACTION CLOSE-UP: a medium/full/wide shot >= 1.3 s in which someone it shows changes to a strong face -> the cut-in to
        a close on that face from the beat on.
      4 PITCH: fall -> top-down, on the ground -> high, power poses / angry-smug faces -> low, sad-scared faces -> high, then
        at least one shot in three gets low/high alternately (the filler never pitches next to a pitched shot).
    Every added piece carries '_alt' (the authored shot, other side): build falls back to it when no camera reads the piece.
    spec keys establish / inserts / reactions / pitch = false switch a rule off. Returns the new list."""
    F = lambda t: int(round(float(t) * fps))
    shots = [dict(x) for x in shots]
    end = lambda i: shots[i + 1]['t'] if i + 1 < len(shots) else T_end
    base = lambda sh: {k: v for k, v in sh.items() if k not in ('establish', '_alt', 'hold')}

    def cut_in(i, ta, tb, piece, mn=0.5):
        """Replace [ta, tb] of shot i by piece; a remainder shorter than mn is absorbed; the shot must survive on one side."""
        sh = shots[i]; t0, t1 = sh['t'], end(i); ta, tb = max(ta, t0), min(tb, t1)
        if ta - t0 < mn: ta = t0
        if t1 - tb < mn: tb = t1
        if tb - ta < mn or (ta == t0 and tb == t1): return False
        new = [sh] if ta > t0 else []
        new.append({**piece, 't': round(ta, 3), 'auto': True, '_alt': {**base(sh), 't': round(ta, 3), 'side': sh.get('side', 0) - 35, 'auto': True}})
        if tb < t1: new.append({**base(sh), 't': round(tb, 3), 'side': sh.get('side', 0) + 35, 'auto': True} if ta > t0 else {**sh, 't': round(tb, 3)})   # head absorbed: the tail IS the authored shot
        shots[i:i + 1] = new
        return True
    cover = lambda t: next((i for i in range(len(shots)) if shots[i]['t'] <= t < end(i)), None)

    if shots and spec.get('establish', True) and shots[0]['t'] < 0.05:
        s0 = shots[0]
        if s0.get('kind') == 'wide':
            if s0.get('angle') is None and not s0.get('track'): s0['angle'] = 'high'; s0['_soft'] = True; notes.append('establishing: the opening wide looks down (high)')
        elif cast and (end(0) >= 1.6 or (end(0) >= 0.8 and len(shots) > 1 and shots[1].get('auto'))):   # or the first rhythm piece becomes it
            shots[:1] = [{'t': 0.0, 'kind': 'wide', 'on': list(cast)[:3], 'lens': 24, 'angle': 'high', '_soft': True, 'auto': True, 'hold': True, 'establish': True},
                         {**s0, 't': 0.9}][:2 if end(0) >= 1.6 else 1]
    if spec.get('inserts', True):
        done = set()
        for t, prop, how in sorted(events):
            i = cover(t)
            if i is None or prop in done or len(done) >= 2: continue
            sh = shots[i]
            if sh.get('kind') == 'insert' or prop in sh.get('on', []) or sh.get('hold') or sh.get('establish'): continue
            ta, tb = (t - 0.7, t + 0.1) if how == 'grab' else (t - 0.2, t + 0.6)   # a hand contact: the reach BEFORE it (afterwards the hand covers the prop)
            if cut_in(i, ta, tb, {'kind': 'insert', 'on': [prop], 'lens': 50}):
                done.add(prop); notes.append(f't{t:.2f} story-object insert on {prop}')
    if spec.get('reactions', True):
        i = 0
        while i < len(shots):
            sh = shots[i]; t0, t1 = sh['t'], end(i); on = [x for x in sh.get('on', []) if x in cast]
            if sh.get('kind') in ('medium', 'full', 'wide') and on and t1 - t0 >= 1.3 and not (sh.get('hold') or sh.get('track') or sh.get('establish') or sh.get('fight')):   # a fight exchange stays a two-shot
                b = next((x for x in beats if x['who'] in on and t0 + 0.5 <= x['t'] <= t1 - 0.5 and any(w in str(x.get('face', '')) for w in STRONG)
                          and not any(k in x for k in ('walk', 'fall', 'knockback', 'jump', 'get_up', 'sit', 'stand', 'attack'))), None)
                if b is not None and cut_in(i, b['t'] - 0.1, t1, {'kind': 'close', 'on': [b['who']], 'lens': 50}):
                    notes.append(f"t{b['t']:.2f} reaction close-up on {b['who']} ({b.get('face')})")
                elif b is None and t1 - t0 >= 1.6:   # SOMEONE ELSE acts while the shot holds on its subject: cut to them (shot / reverse shot)
                    o = next((x for x in beats if x['who'] in cast and x['who'] not in on and t0 + 0.5 <= x['t'] <= t1 - 0.5
                              and ('talk' in x or ('pose' in x and 'face' in x))
                              and not any(k in x for k in ('walk', 'fall', 'knockback', 'jump', 'get_up', 'sit', 'stand', 'attack'))), None)
                    if o is not None and cut_in(i, o['t'] - 0.1, t1, {'kind': 'close' if sh.get('kind') == 'medium' else 'medium', 'on': [o['who']], 'lens': 50}):
                        notes.append(f"t{o['t']:.2f} cutaway to {o['who']} (acts off screen)")
            i += 1
    if spec.get('pitch', True):
        chars = []
        for i, sh in enumerate(shots):
            who = (sh.get('on') or list(cast)[:1])[:1]
            if sh.get('kind') == 'insert' or not who or who[0] not in cast: continue
            chars.append(i)
            if sh.get('angle') is not None: continue
            sh['_soft'] = True   # an engine-chosen pitch may fall back to eye level (camera._shot rounds)
            f0, f1 = F(sh['t']), F(end(i)) - 1
            fc = [str(x.get('face', '')) for x in beats if x['who'] == who[0] and f0 - 6 <= F(x['t']) <= f1]
            falls = [x for x in beats if x['who'] in sh.get('on', who) and 'fall' in x and f0 - 6 <= F(x['t']) <= f1]   # not knockbacks: a 9-stud flight needs the side view
            fb = [x for x in beats if x['who'] == who[0] and f0 - 6 <= F(x['t']) <= f1 and isinstance(x.get('pose'), str)]
            fall_b = [x for x in beats if x['who'] == who[0] and ('fall' in x or 'knockback' in x or x.get('get_up')) and F(x['t']) <= f1]
            if falls and sh.get('kind') != 'close' and not sh.get('track'): sh['angle'] = 'top'          # the fall itself: from above
            elif fall_b and (fall_b[-1].get('fall') or 'knockback' in fall_b[-1] or F(fall_b[-1]['t']) >= f0): sh['angle'] = 'high'   # on the ground: look down
            elif any(x['pose'] in LOW_POSES for x in fb): sh['angle'] = 'low'
            elif any(x['pose'] in ('sad', 'cower', 'slump') for x in fb): sh['angle'] = 'high'
            elif sh.get('track') or len([x for x in sh.get('on', []) if x in cast]) > 1: pass                 # faces drive singles only
            elif any(w in c for c in fc for w in ('angry', 'evil', 'smug', 'scream')): sh['angle'] = 'low'    # power / threat: from below
            elif any(w in c for c in fc for w in ('sad', 'worry', 'scared', 'cry')): sh['angle'] = 'high'     # small: from above
        nxt = 'low' if sum(shots[i].get('angle') == 'low' for i in chars) <= sum(shots[i].get('angle') in ('high', 'top') for i in chars) else 'high'
        body = [i for i in chars if not (i == 0 and shots[i].get('kind') == 'wide')]   # the establishing wide is not a story pitch
        need = -(-len(body) // 3) - sum(shots[i].get('angle') is not None for i in body)   # reference: 14 of 32 frames clearly low/high
        for i in body:
            if need <= 0: break
            sh = shots[i]
            if sh.get('angle') is not None or sh.get('track'): continue
            if any(0 <= j < len(shots) and shots[j].get('angle') is not None for j in (i - 1, i + 1)): continue
            sh['angle'] = nxt; nxt = 'high' if nxt == 'low' else 'low'; need -= 1
    return shots


MODES = ('story_cuts', 'follow_oneshot', 'ots_dialogue', 'static_wide', 'topdown_reveal', 'punch_in', 'chase_track', 'two_shot_react', 'pov')
AXIS = {}   # ots_dialogue: frozenset(pair names) -> world side of the line of action the first OTS camera stood on (180-degree rule)


def _foe(b, beats, cast):
    """The other fighter of a fight beat (attack / flurry / blocked, beam, knockback, dodge), else None."""
    who = b.get('who'); other = None
    if 'attack' in b: other = b['attack'].get('target') if isinstance(b['attack'], dict) else b.get('target')
    elif isinstance(b.get('knockback'), dict): other = b['knockback'].get('from')
    elif isinstance(b.get('beam'), dict): other = b['beam'].get('to') if isinstance(b['beam'].get('to'), str) else None
    elif 'dodge' in b:
        attack = min((x for x in beats if 'attack' in x and (x['attack'].get('target') if isinstance(x['attack'], dict) else x.get('target')) == who),
                     key=lambda x: abs(x['t'] - b['t']), default=None)
        other = attack['who'] if attack else next((x for x in cast if x != who), None) if len(cast) == 2 else None
    return other if who in cast and other in cast and other != who else None


STEER = ('profile', 'side', 'front', 'angle', 'ots', 'track', 'move', 'frame')   # authored camera steering: the fight rule keeps out


def fight_shot(sh, beats, cast, t1, dist=None, notes=None):
    """FIGHT COVERAGE = the side-on two-shot (cam2). Fighters face each other: a camera in front of the focus face stands behind
    the other fighter's back, so a fight is filmed ACROSS the fighters' line from the audience side (shot key profile: faces in
    profile, report-only).
      - an automatic piece on a fighter near a fight beat -> profile two-shot of both; kind 'full' when dist(a, b) <= 5 studs,
        else 'wide' (dist = callable(name, name) -> studs, None = unknown = wide)
      - an AUTHORED shot of exactly the two fighters whose span holds a fight beat between them (attack / flurry / blocked / beam /
        knockback / dodge; a beam or flurry counts for its whole length) -> the same side-on view, its size, lens and time kept.
        Any authored steering key (profile, side, front, angle, ots, track, move, frame) wins: the shot is left alone.
    Authored singles and close-ups are never changed."""
    if sh.get('fight') or sh.get('kind') == 'insert' or sh.get('establish') or sh.get('top_fall'): return sh
    on = [x for x in sh.get('on') or [] if x in cast]; focus = (sh.get('on') or [None])[0]
    if not sh.get('auto'):
        if len(on) != 2 or len(sh.get('on', [])) != 2 or any(k in sh for k in STEER): return sh
        for b in beats:
            a_ = b.get('attack') if isinstance(b.get('attack'), dict) else b.get('beam') if isinstance(b.get('beam'), dict) else {}
            if _foe(b, beats, cast) and {b['who'], _foe(b, beats, cast)} == set(on) and b['t'] < t1 and b['t'] + float(a_.get('s', 0.3)) > sh['t']:
                if notes is not None: notes.append(f"shot at {sh['t']}s: {on[0]} and {on[1]} fight in it -> filmed from the side (both in profile); write profile: false to keep the front view")
                return {**sh, 'profile': True, 'keep_two': True, 'fight': True, '_fight_auto': True}
        return sh
    for b in sorted(beats, key=lambda b: abs(b['t'] - sh['t'])):
        if not sh['t'] - 1.0 <= b['t'] <= t1 + 0.6: continue
        who = b.get('who'); other = _foe(b, beats, cast)
        if other and focus in (who, other):
            pair = [focus, other if focus == who else who]
            out = {**sh, 'kind': 'full' if dist is not None and dist(*pair) <= 5.0 else 'wide', 'on': pair, 'keep_two': True, 'fight': True, 'lens': 35, 'profile': True}
            out.pop('side', None)
            if out.get('_soft'): out.pop('angle', None)
            return out
    return sh


def arrival(samples, kind='full'):
    """DASH-IN inside a fight two-shot: samples = [(t, distance between the fighters in studs)]. Returns the time at which the
    gap has closed (85 % of the way) when the frame the pair needs shrinks >= 1.5x over the shot (so the cut onto the tighter
    two-shot is a real size change, never a jump cut) and both pieces last >= 0.6 s; else None."""
    if len(samples) < 3: return None
    need = lambda d: max(SIZES[kind][0], (d * S + 3.0 * S) * 16 / 9)
    d0, d1 = max(d for _, d in samples[:2]), samples[-1][1]
    if d0 - d1 < 3.0 or need(d0) < 1.5 * need(d1): return None
    ta = next(t for t, d in samples if d <= d1 + 0.15 * (d0 - d1))
    return round(ta, 3) if ta - samples[0][0] >= 0.6 and samples[-1][0] - ta >= 0.6 else None


def fall_top(shots, T_end, t_land, bodies, notes):
    """LANDING SHOT (cam2): once a knocked-back / fallen body has LANDED (t_land, measured by build on the final motion - never
    before: an early top shot showed empty ground for 0.5 s) the cut goes to a TRUE straight-down view of the whole body + its
    crater ('angle': 'top', 'frame': 'auto' = camera._shot fits the frame to the bodies' bounds), held 1.0-2.0 s.
    Pure data; returns the new shot list. Left alone: a 'hold' shot (never cut), a shot that is already a top view, a follow
    shot, a scene with < 1.0 s left. If the next cut comes < 1.0 s after the landing that cut moves later (note)."""
    ta = round(t_land + 0.08, 3); shots = [dict(x) for x in shots]
    i = next((k for k in range(len(shots)) if shots[k]['t'] <= ta < (shots[k + 1]['t'] if k + 1 < len(shots) else T_end)), None)
    if i is None or T_end - ta < 1.0: return shots
    cur = shots[i]
    if cur.get('hold') or cur.get('angle') == 'top' or cur.get('move') == 'follow' or cur.get('establish'): return shots
    nxt = shots[i + 1]['t'] if i + 1 < len(shots) else T_end
    tb = (nxt if nxt - ta <= 2.0 else ta + 1.4) if nxt - ta >= 1.0 else ta + 1.0
    late = [x for x in shots if ta < x['t'] < tb - 1e-6]   # cuts the 1.0 s hold runs over
    after = [x for x in shots if x['t'] > tb - 1e-6]; end2 = after[0]['t'] if after else T_end
    if late and (len(late) > 1 or late[0].get('angle') == 'top' or end2 - tb < 0.6):
        notes.append(f"t{t_land:.2f} {bodies[0]} lands: no room for the top-down landing shot (the next cut comes {nxt - ta:.1f}s later)"); return shots
    base = {k: v for k, v in cur.items() if k not in ('establish', '_alt', 'shake')}
    piece = {'t': ta, 'kind': 'wide', 'on': list(bodies), 'angle': 'top', 'frame': 'auto', 'move': 'still', 'hold': True, 'keep_two': True, 'lens': 35,
             'auto': True, 'top_fall': True, '_alt': {**base, 't': ta, 'auto': True}}
    head = shots[:i + 1] if ta - cur['t'] >= 0.5 else shots[:i]
    if not head: return shots   # the scene starts < 0.5 s before the landing: no cut
    mid = []
    if late: mid = [{**late[0], 't': round(tb, 3)}]; notes.append(f"shot at {late[0]['t']}s starts {tb - late[0]['t']:.2f}s later: the top-down landing shot of {bodies[0]} holds 1.0s")
    elif tb < nxt - 1e-6 and nxt - tb >= 0.6: mid = [{**base, 't': round(tb, 3), 'auto': True}]
    notes.append(f"t{ta:.2f} {' + '.join(bodies)} landed -> top-down shot of the whole body" + (' (both bodies)' if len(bodies) > 1 else ''))
    return head + [piece] + mid + after


def fit_top(pts, dirv, margin=1.25):
    """Frame of a straight-down camera whose screen-up runs along dirv (horizontal unit vector): (frame HEIGHT in metres that
    holds every world point of pts in a 9:16 frame with a margin, centre of the points)."""
    c = Vector(((min(p.x for p in pts) + max(p.x for p in pts)) / 2, (min(p.y for p in pts) + max(p.y for p in pts)) / 2, min(p.z for p in pts)))
    lat = Vector((-dirv.y, dirv.x, 0))
    ev = 2 * max(abs((p - c).dot(dirv)) for p in pts); eh = 2 * max(abs((p - c).dot(lat)) for p in pts)
    return margin * max(ev, eh * 16 / 9), c


CRATER = {}   # character name -> radius (m) of the crater its landing leaves (build fills it: the crater VFX is made AFTER the cameras)


def body_points(sc, chars, f):
    """World bbox corners at frame f of every mesh of the characters + their crater (CRATER radius around the torso; crater
    decals already in the scene count too). The crater ring is taken 1/1.25 smaller: fit_top's body margin would leave air
    around a crater, whose rim may touch the frame edge."""
    sc.frame_set(f); bpy.context.view_layer.update(); pts = []
    for ch in chars:
        r = ch.root
        while r.parent is not None: r = r.parent
        mine = [o for o in [r] + list(r.children_recursive) if o.type == 'MESH' and not o.hide_render]
        pts += [o.matrix_world @ Vector(c) for o in mine for c in o.bound_box]
        tc = ch.torso.matrix_world.translation
        if CRATER.get(ch.name): pts += [Vector((tc.x + CRATER[ch.name] / 1.25 * math.cos(a_ * math.pi / 8), tc.y + CRATER[ch.name] / 1.25 * math.sin(a_ * math.pi / 8), 0.0)) for a_ in range(16)]
        for o in bpy.data.objects:
            if o.name.startswith('VFX crater') and o.type == 'MESH' and not o.hide_render and (o.matrix_world.translation - tc).xy.length < 3.0:
                pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
    return pts


def landed(sc, ch, f_from, f_max):
    """The frame a falling body has LANDED: it lies within 30 cm of where it comes to rest (rest = the torso moves < 2 cm per
    2 frames for 8 frames; the last settling of the curl is not waited for). None if it never rests lying."""
    pos = {}
    for f in range(f_from, f_max + 1, 2):
        sc.frame_set(f); pos[f] = (ch.torso.matrix_world.translation.copy(), _lying(ch))
    for f in range(f_from, f_max - 7, 2):
        if pos[f][1] and all((pos[k][0] - pos[k - 2][0]).length < 0.02 for k in range(f + 2, f + 9, 2)):
            while f - 2 >= f_from and pos[f - 2][1] and (pos[f - 2][0] - pos[f][0]).length < 0.3 and (pos[f - 2][0] - pos[f][0]).length >= 1e-4: f -= 2
            return f
    return None


WORDS = {' face': "{}'s face is hidden or turned away from every camera position", ' head mesh': "{}'s head is hidden from every camera position"}


def plain(low, unr=()):
    """Gate keys ('S03 wide:Goku face') and unread() reasons in a writer's words (report notes)."""
    out = []
    for x in low:
        k = x.split(':', 1)[-1]
        out.append(next((w.format(k[:-len(suf)]) for suf, w in WORDS.items() if k.endswith(suf)), f"{k} is hidden from every camera position"))
    return '; '.join(out + list(unr)) or 'it does not read'


def _splice(shots, T_end, ta, tb, piece, mn=0.6):
    """piece replaces [ta, tb) of the shot list (pure data): a head shorter than mn is absorbed, the interrupted shot resumes at
    tb when >= mn s of it remain (else the piece runs on to the next cut)."""
    prev = [x for x in shots if x['t'] <= ta + 1e-6]
    if prev and ta - prev[-1]['t'] < mn: ta = prev[-1]['t']
    res = ([x for x in shots if x['t'] <= tb + 1e-6] or [None])[-1]
    nxt = min([x['t'] for x in shots if x['t'] > tb + 1e-6] or [T_end])
    out = [x for x in shots if x['t'] < ta - 1e-6] + [{**piece, 't': round(ta, 3)}]
    if res is not None and nxt - tb >= mn: out.append({**{k: v for k, v in res.items() if k != 'establish'}, 't': round(tb, 3)})
    return out + [x for x in shots if x['t'] > tb + 1e-6]


def mode_shots(cm, shots, beats, cast, T_end, notes):
    """CAMERA MODE (short.schema.md 7b; LEVEL1.md stage 3): the reel style of a scene -> (shot list, scene switches). Pure data.
    cm = the story/scene key "camera": {"mode", "hero", "with", "on", "at", "kind", "side", "lens"}. story_cuts (default) returns
    the authored shots unchanged; every other mode writes the shots its style needs (authored shots are kept where the style has
    room for them) and switches off the editor rules that would cut into it."""
    mode = cm.get('mode', 'story_cuts'); shots = [dict(x) for x in shots]
    if mode not in MODES: notes.append(f"camera mode '{mode}' unknown -> story_cuts"); mode = 'story_cuts'
    if mode == 'story_cuts' or not cast: return shots, {}
    hero = cm['hero'] if cm.get('hero') in cast else cast[0]
    oth = [c for c in cast if c != hero]; mate = cm['with'] if cm.get('with') in cast else (oth[0] if oth else None)
    OFF = {'establish': False, 'inserts': False, 'reactions': False, 'pitch': False, 'ecu': False}
    opt = {k: cm[k] for k in ('side', 'lens') if k in cm}
    strong = lambda b: b.get('who') in cast and any(w in str(b.get('face', '')) for w in STRONG)
    bs = sorted(beats, key=lambda b: b['t'])
    if mode == 'pov':   # first person from cm['who'] (default hero): see pov_shot; the others look into the lens (build.py)
        who = cm['who'] if cm.get('who') in cast else hero
        return [{'t': 0.0, 'kind': 'medium', 'on': [who], 'pov': who, 'hold': True, 'move': 'still', 'lens': cm.get('lens', 28)}], OFF
    if mode == 'follow_oneshot':
        return [{'t': 0.0, 'kind': cm.get('kind', 'medium'), 'on': [hero], 'hold': True, 'move': 'follow', **opt}], OFF
    if mode == 'chase_track':
        return [{'t': 0.0, 'kind': cm.get('kind', 'full'), 'on': [hero] + ([mate] if mate else []), 'hold': True, 'move': 'follow', 'keep_two': True,
                 'side': 40, **opt}], OFF
    if mode == 'static_wide':
        return [{'t': 0.0, 'kind': 'wide', 'on': list(cm.get('on') or cast[:4]), 'hold': True, 'move': 'still', 'keep_two': True, 'front': True, 'lens': 35, **opt}], OFF
    if mode == 'ots_dialogue':
        if shots:
            for x in shots:
                if len([c for c in x.get('on', []) if c in cast]) == 2 and x.get('kind', 'medium') in ('medium', 'close'): x.setdefault('ots', True)
        else:
            last = None
            for b in bs:
                who = b.get('who')
                if 'talk' not in b or who not in cast or who == last or len(cast) < 2: continue
                t = max(0.0, b['t'] - 0.15) if shots else 0.0
                if (shots and t - shots[-1]['t'] < 1.0) or T_end - t < 0.8: continue
                pa = b['look'] if b.get('look') in cast and b.get('look') != who else (last or next(c for c in ([mate, hero] + cast) if c and c != who))
                shots.append({'t': round(t, 3), 'kind': cm.get('kind', 'medium'), 'on': [who, pa], 'ots': True, 'hold': True, 'keep_two': True}); last = who
            if not shots and mate: shots = [{'t': 0.0, 'kind': 'medium', 'on': [hero, mate], 'ots': True, 'hold': True, 'keep_two': True}]
        return shots, OFF
    if mode == 'topdown_reveal':
        fb = next((b for b in bs if b.get('who') in cast and ('fall' in b or 'knockback' in b)), None)
        at = float(cm['at']) if 'at' in cm else (fb['t'] + 0.45 if fb else 0.6 * T_end)   # after the tip-over: the mess lies there
        at = min(at, T_end - 0.8); who = fb['who'] if fb else hero
        on = list(cm.get('on') or [who])   # the body on the ground is the subject: bystanders are seen from above (hair), never its co-subjects
        shots = [x for x in (shots or [{'t': 0.0, 'kind': 'medium', 'on': [hero]}]) if x['t'] < at - 0.5] or [{'t': 0.0, 'kind': 'medium', 'on': [hero]}]
        shots.append({'t': round(at, 3), 'kind': cm.get('kind', 'wide'), 'on': on, 'angle': 'top', 'hold': True, 'move': 'pull', 'keep_two': True,
                      'lens': 24, 'reveal': True, **opt})
        return shots, {'ecu': False}
    if mode == 'punch_in':
        p = (min(bs, key=lambda b: abs(b['t'] - float(cm['at']))) if 'at' in cm and bs else
             next((b for b in reversed(bs) if strong(b) and b['t'] <= T_end - 0.6 and (b['who'] == cm['hero'] if cm.get('hero') in cast else 0.5 * T_end <= b['t'])), None))
        if p is None or p.get('who') not in cast: notes.append('camera punch_in: no punchline beat (a strong face in the second half)'); return shots, {}
        shots = shots or [{'t': 0.0, 'kind': 'medium', 'on': [hero]}]
        shots = _splice(shots, T_end, p['t'] - 1.0, min(T_end, p['t'] + 1.4), {'kind': 'close', 'on': [p['who']], 'hold': True, 'move': 'still', 'punch': p['t'], 'lens': 50})
        notes.append(f"camera punch_in: crash zoom on {p['who']} at t{p['t']:.2f}")
        return shots, {'ecu': False}
    # two_shot_react: the two-shot is the master, every strong face gets its close-up and the cut returns to the two-shot
    if not mate: return shots, {}
    shots = [{'t': 0.0, 'kind': cm.get('kind', 'medium'), 'on': [hero, mate], 'hold': True, 'keep_two': True, 'front': True, **opt}]; free = 1.0
    for b in bs:
        if not strong(b) or b['t'] - 0.1 < free or b['t'] + 1.1 > T_end or any(k in b for k in ('walk', 'fall', 'knockback', 'jump')): continue
        shots = _splice(shots, T_end, b['t'] - 0.1, b['t'] + 1.1, {'kind': 'close', 'on': [b['who']], 'hold': True, 'react': True, 'lens': 50})
        free = b['t'] + 1.1 + 0.7
    return shots, OFF


def pov_shot(sc, name, f0, f1, ch, lens=28):
    """POV camera: at `ch`'s eye height, 0.4 m in front of the face, looking where the head looks, slight handheld drift
    (keys every 3 frames). Returns (camera, {}): nothing is gated."""
    import random, zlib
    rnd = random.Random(zlib.crc32(name.encode()) & 0xffff); ph = [rnd.uniform(0, 6.28) for _ in range(5)]
    cd = bpy.data.cameras.new(name); cd.sensor_fit = 'VERTICAL'; cd.sensor_height = 36; cd.clip_end = 200; cd.clip_start = 0.05; cd.lens = lens
    cam = bpy.data.objects.new(name, cd); bpy.context.collection.objects.link(cam)
    for f in sorted(set(list(range(f0, f1 + 1, 3)) + [f1])):
        sc.frame_set(f)
        eye = ch.head_mesh.matrix_world.translation.copy(); fwd = ch.head.matrix_world.to_3x3() @ Vector((0, -1, 0)); fwd.z = 0
        fwd = fwd.normalized() if fwd.length > 1e-6 else Vector((0, -1, 0)); t = f / 24.0
        P = eye + fwd * 0.4 + Vector((math.sin(t * 4.2 + ph[0]), math.sin(t * 3.1 + ph[1]), math.sin(t * 3.7 + ph[2]))) * 0.012
        cam.location = P; cam.keyframe_insert('location', frame=f)
        rot = (fwd * 5 + Vector((0, 0, -0.1))).to_track_quat('-Z', 'Y').to_euler()
        rot.x += math.radians(0.4) * math.sin(t * 2.9 + ph[3]); rot.z += math.radians(0.4) * math.sin(t * 2.3 + ph[4])
        cam.rotation_euler = rot; cam.keyframe_insert('rotation_euler', frame=f)
    _compat(cam)
    sc.timeline_markers.new(name, frame=f0).camera = cam
    cam['on'] = ch.name; cam['follow'] = False; LAST['cut'] = None; LAST['cam'] = cam
    return cam, {}


def vis_low(c, v):
    """The visibility gate for one shot c (name) with report v: list of 'shot:key' below threshold (build.gates uses it too).
    Focus face 0.6 in close-ups else 0.5; targets 0.35 in close-ups else 0.5; a head mesh whose face is measured is a sanity
    check only (0.2 when the face reads >= 0.8, else 0.3); keys ending '~' are reported, never gated."""
    def thr(k):
        if ' close' in c and k.endswith(' head mesh') and v.get(k.replace(' head mesh', ' face'), 0) >= 0.6:   # face passes its own close gate
            return 0.0   # close-up whose face reads: the skull is mostly library hair (snack S07: head 0.11, face 1.0 on the sheet)
        if ' close' in c: return 0.6 if k.endswith(' face') else 0.35
        if k.endswith(' head mesh') and (k.replace(' head mesh', ' face') in v or k.replace(' head mesh', ' face~') in v):
            return 0.2 if v.get(k.replace(' head mesh', ' face'), 0) >= 0.8 else 0.3
        return 0.5
    return [f'{c}:{k}' for k, x in v.items() if not k.endswith('~') and x < thr(k)]


def slab(v_):
    """A shot report whose frame is filled by ONE near surface (fg~ > 10 %), by furniture in front of the subject (fgb~ > 30 %)
    or by the void behind an open-sided set (bg~ > 12 %): homework R206 frame 3, factory R212b frames 6 and 12. A preference
    in the camera search (every round is tried before such a shot is accepted) and the drop rule for automatic establishing wides."""
    return v_.get('fg~', 0.0) > 0.1 or v_.get('fgb~', 0.0) > 0.3 or v_.get('bg~', 0.0) > 0.12 or v_.get('other~', 0.0) > 0.25   # other~: ANOTHER actor's body across a single (cam2)


def unread(c, v_, eyes=True):
    """R240 FACE READABILITY of shot c (name) with report v_, on the final trajectory: the reasons the subject does not read
    (critic R240: faces hidden or cropped in ~10 of 16 frames). head cropped = focus head + hair inside the frame on < 90 % of
    the frames; face turned away = the lens is > 60 deg off the face normal (profile, chin from below: the face grid passes
    those); eyes hidden = both eyes under the fringe; limb fills the frame = body~ (arms / legs / torsos, not the subject's
    head) > 50 % of a close-up or a medium (a low angle in a small room = a torso tower) or > 15 % of a prop shot; back of a head = a wide/full that shows another subject from behind;
    subject hidden = a wide/full in which another subject's head is < 40 % visible; prop half hidden = a prop shot < 75 %.
    NOT a gate: a strong selection rule - camera._shot searches a repair round (eye level, face-on, 1.3x wider) and keeps the
    least-flawed passing camera; build drops an automatic piece that stays unreadable (eyes=False there: a fringe is hair)."""
    g = lambda suf, dflt: next((x for k, x in v_.items() if k.endswith(suf)), dflt)
    char = any(k.endswith((' face', ' face~')) for k in v_); out = []
    if g(' framed~', 1.0) < 0.9: out.append('head cropped')
    if g(' safe~', 1.0) < 1.0: out.append('face leaves the frame or sits in the caption zone')   # cam2: on ANY frame of the moved camera
    if v_.get('other~', 0.0) > 0.25: out.append("another actor's body covers the frame")
    if char and not any(k.endswith(' face') for k in v_) and g(' face~', 1.0) < 0.5 and g(' front~', None) is None and len([k for k in v_ if k.endswith(' face~')]) == 1:
        out.append('face not shown')   # a moving single in a wide/full (face report-only): its back for the whole shot (creator bug '0:18 camera')
    if g(' front~', 1.0) < 0.5: out.append('face turned away')
    if eyes and g(' eyes~', 1.0) < 0.5: out.append('eyes hidden')
    if v_.get('body~', 0.0) > (0.5 if char else 0.15): out.append('limb fills the frame')
    if not char and min([x for k, x in v_.items() if not k.endswith('~')] or [1.0]) < 0.75: out.append('prop half hidden')
    if (' wide' in c or ' full' in c) and any(k.endswith(' face') for k in v_) and any(k.endswith(' face~') and x < 0.3 for k, x in v_.items()):
        out.append('back of a head')
    if (' wide' in c or ' full' in c) and any(k.endswith(' head mesh~') and x < 0.4 for k, x in v_.items()): out.append('subject hidden')
    return out


def _anchor(subjects):
    pts, fac = [], Vector((0, 0, 0))
    for s in subjects:
        if hasattr(s, 'head_mesh'):
            pts.append(s.head_mesh.matrix_world.translation.copy())
            if len(subjects) == 1:   # one character: shoot the FACE (head turned by looks), not the body direction
                hf = s.head.matrix_world.to_3x3() @ Vector((0, -1, 0)); hf.z = 0
                fac += hf.normalized() if hf.length > 1e-6 else Vector((0, -1, 0))
            else:
                y = s.root.matrix_world.to_euler().z
                fac += Vector((math.sin(y), -math.cos(y), 0))
        else:
            pts.append(s.matrix_world.translation.copy())
    c = sum(pts, Vector()) / len(pts)
    if fac.length < 0.4 and len(pts) >= 2:          # facing each other: shoot across their line, from the front (-Y)
        d = (pts[-1] - pts[0]); n = Vector((-d.y, d.x, 0)).normalized()
        fac = n if n.y < 0 else -n
    if fac.length < 1e-6: fac = Vector((0, -1, 0))
    return c, fac.normalized(), pts


MC = {}   # frame -> {object: matrix_world copy}: the scene is evaluated ONCE per frame per _choose, not per candidate (R157
          # profile: cheap() 25 s + _area() 24 s of a 182 s build were frame_set calls repeated for every candidate)


def _mat(obj, f):
    m = MC.get(f)
    return m[obj] if m is not None and obj in m else obj.matrix_world


def _area(sc, cam, obj, frames):
    """Max over frames of the clamped screen-bbox area of obj (cheap, no ray casts)."""
    best = 0.0
    for f in frames:
        if f not in MC: sc.frame_set(f)
        M_ = _mat(obj, f)
        ps = [world_to_camera_view(sc, cam, M_ @ Vector(c)) for c in obj.bound_box]
        ps = [p for p in ps if p.z > 0]
        if not ps: continue
        xs = [min(1, max(0, p.x)) for p in ps]; ys = [min(1, max(0, p.y)) for p in ps]
        best = max(best, (max(xs) - min(xs)) * (max(ys) - min(ys)))
    return best


def _union_area(sc, cam, objs, frames):
    """Max over frames of the clamped screen-bbox area of ALL objs together (a whole foreground person: torso + head + arms +
    hair; per-part areas read 14 % + 15 % for a back that filled 40 % of the frame, homework S03)."""
    best = 0.0
    for f in frames:
        if f not in MC: sc.frame_set(f)
        ps = [world_to_camera_view(sc, cam, _mat(o, f) @ Vector(c)) for o in objs for c in o.bound_box]
        ps = [p for p in ps if p.z > 0]
        if not ps: continue
        xs = [min(1, max(0, p.x)) for p in ps]; ys = [min(1, max(0, p.y)) for p in ps]
        best = max(best, (max(xs) - min(xs)) * (max(ys) - min(ys)))
    return best


def _hb(ob):
    return (Vector(min(c[i] for c in ob.bound_box) for i in range(3)), Vector(max(c[i] for c in ob.bound_box) for i in range(3)))


EYES_W = [0.0]     # > 0 in close-ups: ranking weight of the eyes being visible under the character's own hair
FACE_OPT = [False]   # focus face report-only for this shot (moving subject in a wide/full)
UNSHOW_D = [0.8]   # a set piece this close in front of the face = no camera of this SIZE fits there (close 0.8 m, others 1.5 m: Nico
                   # facing a store shelf ~1.2 m away in a WIDE, R178)


def _of_char(o):
    """True if o (or any parent) belongs to a character (body part, head, hair, face decal)."""
    while o is not None:
        if o.name.startswith(('hair lib', 'face')) or any(o.name.startswith(cn) or o.name == cn.strip() for cn in CAST_NAMES): return True
        o = o.parent
    return False


def _lying(ch):
    return abs((ch.torso.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized().z) < 0.6


def _face_frame(sc, cam, ch, dg, lo_, hi_):
    """One frame (already evaluated): fraction of a 3x3 grid on the FRONT of the face in frame and unoccluded."""
    hm = ch.head_mesh; M = hm.matrix_world; P = cam.matrix_world.translation; ok = n = 0
    fwd = (M.to_3x3() @ Vector((0, -1, 0))).normalized()
    b_ = ROOM.get('bounds')
    if b_ and not (b_[0] < M.translation.x < b_[1] and b_[2] < M.translation.y < b_[3]): return None   # LEFT THE SET (ran out the door):
    # unshowable from inside the room, not 'hidden' (blind3 bedroom Ben, R179)
    if fwd.z < -0.6 and _lying(ch): return None   # a face-down fall is unshowable; a standing actor bowing still needs a camera
    c0 = M @ Vector(((lo_.x + hi_.x) / 2, lo_.y, (lo_.z + hi_.z) / 2))   # face INTO furniture (reaching into a fridge): no camera fits
    hit0, hl0, _, _, ob0, _ = sc.ray_cast(dg, c0 + fwd * 0.02, fwd, distance=UNSHOW_D[0])  # between the face and it -> unshowable (R158 snack)
    if hit0 and not _of_char(ob0) and any(x0 - 0.05 < hl0.x < x1 + 0.05 and y0 - 0.05 < hl0.y < y1 + 0.05 and hl0.z < top + 0.1
                                          for x0, x1, y0, y1, top in ROOM.get('obstacles') or []):
        return None   # only a registered SOLID SET PIECE counts (never own hair, bodies, or a held prop in front of the face)

    for a in (-0.3, 0.0, 0.3):
        for b in (-0.36, -0.14, 0.1):     # mouth row .. eye row (Roblox faces sit low on the head)
            loc = Vector(((lo_.x + hi_.x) / 2 + a * (hi_.x - lo_.x), lo_.y, (lo_.z + hi_.z) / 2 + b * (hi_.z - lo_.z)))
            w = M @ loc; n += 1
            if fwd.dot((P - w).normalized()) < 0.1: continue           # facing away from the lens
            v = world_to_camera_view(sc, cam, w)
            if not (0.02 <= v.x <= 0.98 and 0.02 <= v.y <= 0.98 and v.z > 0): continue
            d = w - P; hit, _, _, _, obj, _ = sc.ray_cast(dg, P, d.normalized(), distance=d.length - 0.03)
            if not hit or obj is hm or (obj.parent is not None and obj.parent in (ch.head, ch.hair_pivot)) or obj.name.startswith(('face', ch.name + ' face')):   # own hair = parent check; ANOTHER's hair blocks (big lib hair, R119)
                ok += 1
    return ok / n


def _face_agg(per, q):
    per = [x for x in per if x is not None]   # face-down frames are skipped; a shot that is ALL face-down reads 1.0 (report-only)
    if q is None or not per: return min(per) if per else 1.0
    qv = sorted(per)[int(q * (len(per) - 1))]   # quantile: value reached on (1-q) of the frames (walks turn away for a moment)
    # REVEAL: the face turns INTO view in the first 40 % of the shot and stays readable (>= 0.6) to the end (a character
    # starting with its back to the lens and turning round; no camera sees a face before it turns: snack/chase s02, R143)
    k = next((i for i in range(len(per)) if min(per[i:]) >= 0.6), None)
    if k is not None and k <= 0.4 * (len(per) - 1): return max(qv, min(per[k:]))
    return qv


def face_vis(sc, cam, ch, frames, q=None):
    """Min over frames (or the q-quantile + reveal rule) of the visible fraction of the FRONT of the face (the head's own
    hierarchy - hair, decals - does not count). Arms or props across the face drop it; the back of the head reads 0."""
    lo_, hi_ = _hb(ch.head_mesh); per = []
    for f in frames:
        sc.frame_set(f); per.append(_face_frame(sc, cam, ch, bpy.context.evaluated_depsgraph_get(), lo_, hi_))
    return _face_agg(per, q)


def _framed(sc, cam, ch):
    """One frame (already evaluated): is the head WITH its hair inside the frame (x 0.04-0.96, y 0.05-0.95)? (reference R3: a face
    is all in or deliberately out, never cut by the frame edge; the 3x3 face grid passes with a third of the face cropped.)"""
    for o in [ch.head_mesh] + [h for h in ch.hair_pivot.children_recursive if h.type == 'MESH']:
        for c in o.bound_box:
            v = world_to_camera_view(sc, cam, o.matrix_world @ Vector(c))
            if not (0.05 <= v.y <= 0.95 and v.z > 0): return False   # top / bottom only: the bbox corners of the head mesh and of big library
            # hair are ~1.8x wider than the visible head (R240: on the true 9:16 frame they left the sides of every close-up; the
            # sides are judged by the face grid and the eyes)
    return True


CAPTION_Y = 0.38   # captions sit ~22-30 % from the bottom of the 9:16 frame: a face centre stays above 38 %


def _safe(sc, cam, ch):
    """One frame (already evaluated): the head mesh is inside the frame and the FACE centre is inside it AND above the caption
    zone (cam2: a close-up chosen on frame 0 lost the face under the caption after its push-in + a pose change)."""
    hm = ch.head_mesh; lo_, hi_ = _hb(hm)
    v = world_to_camera_view(sc, cam, hm.matrix_world @ Vector(((lo_.x + hi_.x) / 2, lo_.y, (lo_.z + hi_.z) / 2)))
    ys = [world_to_camera_view(sc, cam, hm.matrix_world @ Vector(c)).y for c in hm.bound_box]
    f_ = sc.get('frame'); cap = 0.05 if f_ and f_[0] > f_[1] else CAPTION_Y   # B1: landscape frames have no Shorts caption zone
    return bool(v.z > 0 and 0.1 <= v.x <= 0.9 and cap <= v.y <= 0.95 and min(ys) >= 0.0 and max(ys) <= 1.02)


def _eyes_frame(sc, cam, ch, dg):
    """One frame (already evaluated): fraction of the two EYES in frame and unoccluded, the character's OWN HAIR counted as an
    occluder (the face grid ignores own hair by design: an emo fringe over both eyes read face 1.0, critic R206 frames 15-16).
    shortcut: eye positions of the procedural decal (u 0.32/0.68, v 0.62 on the 120-degree strip); library faces may differ."""
    hm = ch.head_mesh; M = hm.matrix_world; P = cam.matrix_world.translation; lo_, hi_ = _hb(hm); ok = 0
    cx, cy, r = (lo_.x + hi_.x) / 2, (lo_.y + hi_.y) / 2, (hi_.x - lo_.x) / 2
    for sg in (-1, 1):
        loc = Vector((cx + sg * 0.37 * r, cy - 0.94 * r, (lo_.z + hi_.z) / 2 + 0.108 * (hi_.z - lo_.z)))
        w = M @ loc; n_ = (M.to_3x3() @ Vector((sg * 0.37, -0.93, 0))).normalized()
        if n_.dot((P - w).normalized()) < 0.1: continue                 # eye turned away from the lens
        v = world_to_camera_view(sc, cam, w)
        if not (0.02 <= v.x <= 0.98 and 0.02 <= v.y <= 0.98 and v.z > 0): continue
        d = w - P; hit, _, _, _, obj, _ = sc.ray_cast(dg, P, d.normalized(), distance=d.length - 0.03)
        if not hit or obj is hm or obj.name.startswith(('face', ch.name + ' face')): ok += 1
    return ok / 2


def eyes_vis(sc, cam, ch, frames):
    """Mean over frames of the visible fraction of the eyes (own hair blocks). Report + ranking term, not a gate."""
    tot = 0.0
    for f in frames:
        sc.frame_set(f); bpy.context.view_layer.update(); tot += _eyes_frame(sc, cam, ch, bpy.context.evaluated_depsgraph_get())
    return tot / max(1, len(frames))


def fg_void(sc, cam, f, subj_dist):
    """(void, block, bg): fractions of a 6x10 ray grid over the frame that end on NON-character set geometry (floors/walls excluded)
    void = in the lens's face: nearer than 35 % of the subject distance (max 1.2 m). A desk edge / chair back this close is an
           unlit out-of-focus slab (critic R206 frame 3: the bottom quarter pure black, camera low behind a desk).
    block = anywhere in front of the subject (< 75 % of its distance): foreground furniture is a frame element up to ~30 % of
           the frame (reference R4), beyond that it is the subject of the shot.
    bg = rays that hit NOTHING, counted only in an open-sided room (ROOM['cam'] set): the lens looks out of the missing wall
           into the flat world colour (factory Short R212b frame 6).
    body = rays that end on a character but not on a subject's head/hair/face (BODY['heads']): arms, legs, torsos."""
    sc.frame_set(f); bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
    M = cam.matrix_world; P = M.translation; fr = cam.data.view_frame(scene=sc); lim = min(1.2, 0.35 * subj_dist); n = nb = nv = nl = no = 0; open_ = bool(ROOM.get('cam'))
    for i in range(6):
        for j in range(10):
            u, v = (i + 0.5) / 6, (j + 0.5) / 10
            d = (M.to_3x3() @ fr[2].lerp(fr[1], u).lerp(fr[3].lerp(fr[0], u), v)).normalized()
            ok, loc, _, _, obj, _ = sc.ray_cast(dg, P, d, distance=120)
            if not ok: nv += open_; continue
            if obj is None: continue
            if _of_char(obj):   # body = character geometry that is not a subject's head / hair / face (R240: limbs filling inserts)
                o = obj
                while o is not None and o not in BODY['heads']: o = o.parent
                nl += o is None
                while obj.parent is not None: obj = obj.parent
                no += bool(BODY.get('mine')) and obj not in BODY['mine']   # other~: a character that is not a subject of this shot
            elif (loc - P).length <= 0.75 * subj_dist and not any(obj.name.startswith(k) or k in obj.name for k in PLAIN):   # a floor is not a void
                nb += 1; n += (loc - P).length < lim
    return n / 60.0, nb / 60.0, nv / 60.0, nl / 60.0, no / 60.0


def _target_frame(sc, cam, tg, dg):
    """One frame (already evaluated): fraction of the 27 bbox samples of tg in frame and unoccluded (ia.shot_visibility).
    (R213 tried counting the holding arm as part of a held prop: the gate passed, the pictures were sleeves - reverted.)"""
    cpos = cam.matrix_world.translation; ok = 0; anc = tg.parent or tg
    def under(o):
        while o is not None:
            if o == anc or o == tg: return True
            o = o.parent
        return False
    pts = ia._samples(tg)
    for p in pts:
        v = world_to_camera_view(sc, cam, p)
        if not (0.02 <= v.x <= 0.98 and 0.02 <= v.y <= 0.98 and v.z > 0): continue
        d = p - cpos; hit, _, _, _, obj, _ = sc.ray_cast(dg, cpos, d.normalized(), distance=d.length - 0.02)
        if not hit or under(obj): ok += 1
    return ok / len(pts)


def measure(sc, cam, frames, targets, until, chars, q=0.25):
    """vis_gate + face_vis in ONE pass: each frame is evaluated once for every target and face (they each re-evaluated the
    whole scene per frame per target: the camera validation dominated build time, R148). Same numbers, same rules.
    Returns ({target: (value,)}, [face value per char])."""
    tfr = {}
    for t in targets:
        fr = [f for f in frames if not until or t.name not in until or f <= until[t.name]] or [frames[0]]
        key = until[t.name] - 4 if until and t.name in until else frames[-1]
        tfr[t.name] = (set(fr), key)
    allf = sorted(set(frames) | {k for _, k in tfr.values()} | {f for s_, _ in tfr.values() for f in s_})
    hb = [_hb(ch.head_mesh) for ch in chars]
    tper = {t.name: [] for t in targets}; tkey = {}; fper = [[] for _ in chars]; fs = set(frames); FRAMED[:] = []; FRONT[:] = []; SAFE[:] = []
    for f in allf:
        sc.frame_set(f); bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
        for t in targets:
            s_, key = tfr[t.name]
            b_ = ROOM.get('bounds'); tp = t.matrix_world.translation
            if b_ and t.name.endswith('head mesh') and not (b_[0] < tp.x < b_[1] and b_[2] < tp.y < b_[3]): continue   # left the set
            if f in s_ or f == key:
                v_ = _target_frame(sc, cam, t, dg)
                if f in s_: tper[t.name].append(v_)
                if f == key: tkey[t.name] = v_
        if f in fs:
            for i, ch in enumerate(chars): fper[i].append(_face_frame(sc, cam, ch, dg, *hb[i]))
            if chars:
                FRAMED.append(_framed(sc, cam, chars[0])); SAFE.append(_safe(sc, cam, chars[0])); M_ = chars[0].head_mesh.matrix_world
                FRONT.append((M_.to_3x3() @ Vector((0, -1, 0))).normalized().dot((cam.matrix_world.translation - M_.translation).normalized()))
    tv = {}
    for t in targets:
        per = sorted(tper[t.name]) or [tkey.get(t.name, 0.0)]
        tv[t.name] = (min(per[int(q * (len(per) - 1))], tkey.get(t.name, 1.0)),)
    return tv, [_face_agg(p_, q) for p_ in fper]


PLAIN = ('wall', 'floor', 'ceiling', 'ground', 'skirting', 'road', 'sidewalk', 'Back wall', 'Left wall', 'Front wall', 'Right window wall')


def _richness(sc, cam, f, subj_dist=None):
    """Fraction of a 6x10 ray grid over the frame that lands on set dressing (anything but plain walls/floor/ceiling or
    characters) -> busy reference-like backgrounds score higher."""
    sc.frame_set(f); bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
    M = cam.matrix_world; P = M.translation; fr = cam.data.view_frame(scene=sc)
    hit_n = tot = 0
    for i in range(6):
        for j in range(10):
            u, v = (i + 0.5) / 6, (j + 0.5) / 10
            q = fr[2].lerp(fr[1], u).lerp(fr[3].lerp(fr[0], u), v)    # bottom-left..top-right interpolation (order irrelevant)
            d = (M.to_3x3() @ q).normalized()
            ok, loc, _, _, obj, _ = sc.ray_cast(dg, P, d, distance=60)
            tot += 1
            if ok and obj is not None:
                n = obj.name
                if subj_dist and (loc - P).length < 0.75 * subj_dist and not any(n.startswith(c) for c in CAST_NAMES)                         and not n.startswith(('hair', 'face')) and 0.15 < u < 0.85:
                    FG[0] += 1; continue                   # foreground blocker (pole, tree, prop) between lens and subject
                if any(n.startswith(k) or k in n for k in PLAIN): continue
                if any(n.startswith(c) for c in CAST_NAMES) or n.startswith(('hair', 'face', 'Hair', 'Face')): continue
                hit_n += 1
    return hit_n / max(tot, 1)


CAST_NAMES = []
BODY = {'heads': set(), 'thr': 9.0, 'mine': set()}   # per shot: head/hair parents of the subject characters; body~ share above which the frame is "a limb"
FRONT = []    # per dense frame of the last measure(): cosine between the focus face normal and the direction to the lens
FRAMED = []   # per dense frame of the last measure(): focus head + hair fully in frame
SAFE = []     # per dense frame of the last measure(): focus head in frame, face centre above the caption zone (_safe)
FG = [0]


def _move_camera(sc, cam, P, A, f0, f1, move, kind, people, name, focus=None):
    """reference: the camera is never still. push = dolly in (close 22 %, insert 28 %), pull = dolly out (wide/full 14 %),
    arc = orbit the aim 12 deg (medium; direction away from walls/people), track = follow (frame_targets) + slight dolly.
    Every move gets a gentle handheld drift (+-1.2 cm, +-0.25 deg, ~1.5 s period). Keys every 3 frames, eased (smoothstep).
    A move whose end would leave the room or come within 1.0 m of anyone is shortened, then falls back to a small push."""
    import random
    import zlib
    n = max(1, f1 - f0); rnd = random.Random(zlib.crc32(name.encode()) & 0xffff)   # stable seed: hash() is randomized per process (builds were not reproducible)
    def safe(q):
        b = _cb()
        if b and not (b[0] + 0.2 < q.x < b[1] - 0.2 and b[2] + 0.2 < q.y < b[3] - 0.2): return False
        if any(x0 - 0.15 < q.x < x1 + 0.15 and y0 - 0.15 < q.y < y1 + 0.15 and q.z < top + 0.1 for x0, x1, y0, y1, top in ROOM.get('obstacles') or []): return False   # the move's END inside furniture (L1 cam 08 park, new set seed)
        for f in (f0, (f0 + f1) // 2, f1):
            sc.frame_set(f)
            if any(_bbox_dist(q, p) < 1.0 for p in people): return False
        return True
    push_amt = [0.28 if kind == 'insert' else 0.12 if kind == 'close' else 0.22]   # close: 22 % ended with the (taller library) hair cropped and the head filling the frame (critic R151)
    def path(u):
        if move == 'push': return P + (A - P) * (push_amt[0] * u)
        if move == 'pull': return P - (A - P) * (0.14 * u)
        if move == 'track': return P + (A - P) * (0.08 * u)
        v = P - A; ang = math.radians(arc_sign[0] * 12 * u)                # arc around the vertical axis through the aim
        return A + Vector((v.x * math.cos(ang) - v.y * math.sin(ang), v.x * math.sin(ang) + v.y * math.cos(ang), v.z))
    arc_sign = [1]
    if move == 'arc':
        arc_sign[0] = 1 if safe(path(1.0)) else -1
        if not safe(path(1.0)): move = 'push'
    if focus is not None and move in ('arc', 'push', 'pull'):   # the move must END with the focus face still readable
        def face_end(q):
            cam.location = q; cam.rotation_euler = (A - q).to_track_quat('-Z', 'Y').to_euler(); bpy.context.view_layer.update()
            return face_vis(sc, cam, focus, [(f0 + f1) // 2, f1])
        start = face_end(P); tries = []
        if move == 'arc': tries = [('arc', arc_sign[0]), ('arc', -arc_sign[0]), ('push', 1), ('still', 1)]
        else: tries = [(move, 1), ('push', 1), ('still', 1)]
        for mv_, sg in tries:
            move = mv_; arc_sign[0] = sg
            if move == 'still': break
            q_end = path(1.0)
            if safe(q_end) and face_end(q_end) >= min(0.6, start - 0.05): break
    if move in ('push', 'pull') and not safe(path(1.0)):   # fall back to a SMALL push (and really use that small amount)
        if safe(P + (A - P) * 0.1): move = 'push'; push_amt[0] = 0.1
        else: move = 'still'
    ph = [rnd.uniform(0, 6.28) for _ in range(5)]
    for f in list(range(f0, f1 + 1, 3)) + ([f1] if (f1 - f0) % 3 else []):
        u = (f - f0) / n; u = u * u * (3 - 2 * u)
        q = P if move == 'still' else path(u)
        t = f / 24.0; dr = Vector((math.sin(t * 4.2 + ph[0]), math.sin(t * 3.1 + ph[1]), math.sin(t * 3.7 + ph[2]))) * 0.012
        cam.location = q + dr; cam.keyframe_insert('location', frame=f)
        rot = (A - q).to_track_quat('-Z', 'Y').to_euler()
        rot.x += math.radians(0.25) * math.sin(t * 2.9 + ph[3]); rot.z += math.radians(0.25) * math.sin(t * 2.3 + ph[4])
        cam.rotation_euler = rot; cam.keyframe_insert('rotation_euler', frame=f)
    print('MOVE', name, move)


def _compat(cam):
    """Make the keyed camera rotation continuous. to_track_quat().to_euler() returns, for some aims, the OTHER Euler triple of the
    same orientation (or one a full turn away); the interpolation between such keys tumbles the camera for a few frames (roll 87
    deg over f52-62 of f_a_determined s03: the creator's rotated '0:18' frame, R259). Every key becomes the triple nearest to the
    key before it."""
    import space
    from mathutils import Euler
    fcs = {fc.array_index: fc for fc in space.fcurves_of(cam) if fc.data_path == 'rotation_euler'}
    if len(fcs) < 3: return
    ks = [{int(round(k.co.x)): k for k in fcs[i].keyframe_points} for i in range(3)]; prev = None
    for f in sorted(set(ks[0]) & set(ks[1]) & set(ks[2])):
        e = Euler([ks[i][f].co.y for i in range(3)])
        if prev is not None:
            e2 = e.to_quaternion().to_euler('XYZ', prev)
            for i in range(3):
                d = e2[i] - ks[i][f].co.y; k = ks[i][f]; k.co.y += d; k.handle_left.y += d; k.handle_right.y += d
            e = e2
        prev = e
    for fc in fcs.values(): fc.update()


def _bbox_dist(pw, obj, M=None):
    """Distance from world point pw to the object's bounding box surface (0 inside)."""
    M = obj.matrix_world if M is None else M; q = M.inverted() @ pw
    lo_ = [min(c[i] for c in obj.bound_box) for i in range(3)]; hi_ = [max(c[i] for c in obj.bound_box) for i in range(3)]
    cl = Vector(tuple(max(lo_[i], min(hi_[i], q[i])) for i in range(3)))
    return (M @ cl - pw).length


def _vis(sc, cam, frames, targets, until):
    """shot_visibility, but a target listed in `until` (name -> frame) is only judged on frames up to that frame."""
    if not until: return ia.shot_visibility(sc, cam, frames, targets)
    out = ia.shot_visibility(sc, cam, frames, [t for t in targets if t.name not in until])
    for t in targets:
        if t.name in until:
            fr = [f for f in frames if f <= until[t.name]] or [frames[0]]
            out.update(ia.shot_visibility(sc, cam, sorted(set(fr + [until[t.name]])), [t]))
    return out


def _vis_tracked(sc, cam, frames, targets, until):
    """_vis for a camera that will TRACK its targets: it is re-aimed at their centre on every frame (a static candidate of a
    0.9 m insert frame saw a hand-over travelling 1 m as 'never in frame': every candidate read 0.0, homework give)."""
    pos = cam.location.copy(); per = {t.name: [] for t in targets}
    for f in frames:
        sc.frame_set(f); bpy.context.view_layer.update()
        look = sum((t.matrix_world.translation for t in targets), Vector()) / len(targets)
        cam.rotation_euler = (look - pos).to_track_quat('-Z', 'Y').to_euler(); bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        for t in targets:
            if not (until and t.name in until and f > until[t.name]) or not per[t.name]: per[t.name].append(_target_frame(sc, cam, t, dg))
    return {k: (min(v), sum(v) / len(v)) for k, v in per.items()}


def vis_gate(sc, cam, frames, targets, until=None, q=0.25):
    """Gate visibility of each target on the moved camera: the value reached on (1-q) of the frames (same rule as face_vis:
    a body passing in front for a moment is film, not a hidden prop), but never above its value on the KEY frame (a grabbed
    prop at its grab frame, else the shot's last frame) - the moment that matters must read. {name: (value,)}"""
    out = {}
    for t in targets:
        fr = [f for f in frames if not until or t.name not in until or f <= until[t.name]] or [frames[0]]
        key = until[t.name] - 4 if until and t.name in until else frames[-1]   # until = grab frame + 2 (build): judge the reach 2 frames before contact (at contact the hand covers the prop by design)
        per = sorted(ia.shot_visibility(sc, cam, [f], [t])[t.name][0] for f in sorted(set(fr)))
        kv = ia.shot_visibility(sc, cam, [key], [t])[t.name][0]
        out[t.name] = (min(per[int(q * (len(per) - 1))], kv),)
    return out


def _hero_h(sc, cam, hero):
    pts = [world_to_camera_view(sc, cam, hero.matrix_world @ Vector(c)) for c in hero.bound_box]
    return max(p.y for p in pts) - min(p.y for p in pts)


def _choose(sc, cam, cands, frames, targets, occluders, people, prev, faces=(), subj_torsos=(), face_chars=(), hero=None, track=False, push_k=0.0, vis_until=None, o_own=None, near_min=1.2, same=False):
    cam.animation_data_clear()   # a retry scores static candidates, not the previous candidate's keyed trajectory
    dprev = None
    if prev is not None:
        sc.frame_set(frames[0] - 1); bpy.context.view_layer.update()
        dprev = (prev.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()
    dense_fr = sorted(set(list(range(frames[0], frames[-1] + 1, 4)) + [frames[-1]]))
    MC.clear()
    hair_of = lambda ch_: [h for h in ch_.hair_pivot.children_recursive if h.type == 'MESH']
    objs_ = set(people) | set(occluders) | set(subj_torsos) | {h for ch_ in face_chars[1:] for h in hair_of(ch_)}
    for f in sorted(set(range(frames[0], frames[-1] + 1, 2)) | set(frames)):
        sc.frame_set(f); MC[f] = {o: o.matrix_world.copy() for o in objs_}
    jump_ref = None
    if prev is not None and hero is not None:
        sc.frame_set(frames[0] - 1); bpy.context.view_layer.update()
        jump_ref = ((prev.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized(), _hero_h(sc, prev, hero))
    def cheap(pos, aim, lens, grow):   # stage 1: no ray casts
        sc_ = 0.0; near = 9.0; span = max(1, frames[-1] - frames[0]); jump = False
        for f in range(frames[0], frames[-1] + 1, 2):   # dense (a runner passes between samples) + follows the push-in dolly
            cp = pos + (aim - pos) * push_k * (f - frames[0]) / span
            near = min([near] + [_bbox_dist(cp, p, MC[f][p]) for p in people])
        if near < near_min: sc_ -= 3.0 + 6.0 * (near_min - near)     # nobody (no arm, no head) within 1.2 m of the lens (insert on a held prop: 0.6)
        sc_ -= 0.25 * (grow - 1.0)                         # wider than the shot size asks = small characters + empty ceiling
        if faces:                                            # faces toward the lens (dot of face forward with dir to camera)
            dots = [fw.dot((pos - hp).normalized()) for hp, fw in faces]
            sc_ -= 0.4 * sum(max(0.0, 0.35 - d) for d in dots) / len(dots) + (0.6 if max(dots) < 0.2 else 0.0)
            sc_ += 0.9 * max(0.0, dots[0])                   # stage-1 proxy for the focus face term
        b = _cb()
        if b and not (b[0] < pos.x < b[1] and b[2] < pos.y < b[3]): sc_ -= 2.0
        if jump_ref is not None:   # same rule as interact.cut_report: < 30 deg AND < 1.4x hero size change = jump cut
            cam.location = pos; cam.data.lens = lens
            dprev_, hprev = jump_ref; sc.frame_set(frames[0]); look = aim
            if track:   # a tracking camera re-aims at its targets: judge the cut by where it really looks at the cut frame
                look = sum((t.matrix_world.translation for t in targets), Vector()) / len(targets)
            cam.rotation_euler = (look - pos).to_track_quat('-Z', 'Y').to_euler(); bpy.context.view_layer.update()
            ang = math.degrees(math.acos(max(-1.0, min(1.0, (look - pos).normalized().dot(dprev_)))))
            hh = _hero_h(sc, cam, hero)
            if ang < 35 and max(hh, hprev) / max(1e-6, min(hh, hprev)) < 1.6: sc_ -= 3.0; jump = True   # margin over the 30/1.4 gate
            elif same and ang < 30: sc_ -= 2.0   # R240 near-duplicate pieces: the SAME subject again = a new angle, not only a new size
        d_ = (aim - pos).normalized(); az_, pt_ = math.degrees(math.atan2(d_.x, d_.y)), math.degrees(math.asin(max(-1.0, min(1.0, d_.z))))
        if any(abs((az_ - a0 + 180) % 360 - 180) < 25 and abs(pt_ - p0) < 10 for a0, p0 in list(HIST.values())[-3:]):
            sc_ -= 2.0   # reference rule: never the same camera spot within 3 shots (Fable camera review R1; critic R195/R200)
        return sc_, near, jump
    seen, uniq = set(), []
    for c in cands:   # wall clamps collapse candidates onto the same spot: score each spot once
        key = (round(c[0].x, 1), round(c[0].y, 1), round(c[0].z, 1), round(c[2]))
        if key not in seen: seen.add(key); uniq.append(c)
    key_ = lambda c: (round(c[0].x, 1), round(c[0].y, 1), round(c[0].z, 1), round(c[2]))
    regular = [c for c in uniq if key_(c) not in SAFE_KEYS]; safe = [c for c in uniq if key_(c) in SAFE_KEYS]
    stage1 = sorted(((cheap(*c), c) for c in regular), key=lambda t: -t[0][0])[:12] + [(cheap(*c), c) for c in safe]
    ranked, hidden = [], []; grow_k = 1.0 / (1.0 - push_k) ** 2   # a foreground block grows with the push-in (static 0.29 -> 0.43 at the end: homework v3 frame 7)
    for (s1, near, jump), (pos, aim, lens, grow) in stage1:   # stage 2: ray casts only for the 12 most promising spots
        cam.location = pos; cam.rotation_euler = (aim - pos).to_track_quat('-Z', 'Y').to_euler(); cam.data.lens = lens
        bpy.context.view_layer.update()
        vis = _vis_tracked(sc, cam, frames, targets, vis_until) if track and not face_chars else _vis(sc, cam, frames, targets, vis_until)
        score = s1 + min(v[0] for v in vis.values()) + 0.25 * min(v[1] for v in vis.values())
        occ = {o.name: _area(sc, cam, o, frames) for o in occluders}
        o_own = o_own or {}
        score -= sum(6.0 * max(0.0, a - (0.15 if o_own.get(k) else 0.08)) for k, a in occ.items())   # other people: 8 %, own arms 15 %
        groups = {}   # FOREGROUND PERSON rule (reference R4): a non-subject character nearer the lens than the subject is judged as ONE
        for o in occluders:   # block (union of its parts): a frame element up to 20 %, never a wall (> 30 %)
            if o_own.get(o.name): continue
            r_ = o
            while r_.parent is not None: r_ = r_.parent
            groups.setdefault(r_, []).append(o)
        for g_ in groups.values():
            if (_mat(g_[0], frames[len(frames) // 2]).translation - pos).length < 0.9 * (aim - pos).length:
                blk = _union_area(sc, cam, g_, frames[::2]) * grow_k
                score -= 8.0 * max(0.0, blk - 0.20) + (3.0 if blk > 0.30 else 0.0)
        if subj_torsos:   # several subjects: a foreground subject must not fill the frame (over-the-shoulder max ~35%)
            ta = [_area(sc, cam, t, frames[::2]) for t in subj_torsos]
            score -= sum(4.0 * max(0.0, a - 0.35) for a in ta)
            for ch_, a in zip(face_chars[1:], ta[1:]):   # OTS partner: a big body block WITHOUT its head reads as a wall
                hv = vis.get(ch_.head_mesh.name, (1.0,))[0]
                if hv < 0.3 and a > 0.08: score -= 1.5
                # OTS BLOCK RULE (reference R4/R8; critic R200: the partner's back fills a third of frames 4-6, 8): the partner seen
                # from BEHIND counts with head + hair, is a frame element up to 20 % of the frame and never a wall (> 30 %)
                to_lens = (ch_.head.matrix_world.to_3x3() @ Vector((0, -1, 0))).dot((pos - ch_.head_mesh.matrix_world.translation).normalized())
                if to_lens < 0.1:
                    blk = grow_k * _union_area(sc, cam, [ch_.torso, ch_.head_mesh, *ch_.arms] + hair_of(ch_), frames[::2])   # one block (per-part areas passed a back filling half the frame: homework v2 frame 7)
                    score -= 8.0 * max(0.0, blk - 0.20) + (3.0 if blk > 0.30 else 0.0)
        FG[0] = 0
        score += 0.35 * _richness(sc, cam, frames[len(frames) // 2], (aim - pos).length)
        score -= 0.2 * FG[0]                                  # each centre ray blocked in front of the subject (R195: a chair filled the lower third)
        fv = [face_vis(sc, cam, ch, dense_fr, q=0.25) for ch in face_chars]   # same rule as the gate
        if fv: score += 1.8 * fv[0] + 0.4 * (sum(fv[1:]) / len(fv[1:]) if len(fv) > 1 else fv[0])   # on[0] = the focus face
        if faces: score -= 0.9 * max(0.0, faces[0][1].dot((pos - faces[0][0]).normalized()))  # undo the stage-1 proxy
        ey = eyes_vis(sc, cam, face_chars[0], frames[::2]) if EYES_W[0] and face_chars else None
        if ey is not None: score += EYES_W[0] * ey             # close-up: the eyes must show under the fringe (critic R206)
        void, blk_, bg_, body_, oth_ = fg_void(sc, cam, frames[len(frames) // 2], (aim - pos).length)
        score -= 6.0 * max(0.0, body_ - BODY['thr'])            # a limb / torso fills the frame (R240 frames 7-8, 11-12)
        if len(face_chars) == 1: score -= 8.0 * max(0.0, oth_ - 0.25) + (2.0 if oth_ > 0.25 else 0.0)   # cam2: another actor's arm / body as a slab across a single
        score -= 8.0 * void + (2.0 if void > 0.12 else 0.0)    # a slab in the lens's face (desk edge, chair back): never a frame element
        score -= 4.0 * max(0.0, blk_ - 0.3)                    # furniture in front of the subject beyond 30 % of the frame
        score -= 10.0 * max(0.0, bg_ - 0.05)                   # looking out of the open side of the set into the void
        if os.environ.get('CAMDEBUG'):
            print('CAND', cam.name, 'pos', [round(v / S, 1) for v in pos], 'L', round(lens), 'score', round(score, 2), 'vis', {k[:8]: round(v[0], 2) for k, v in vis.items()},
                  'fv', [round(x, 2) for x in fv] if face_chars else None, 'near', round(near, 2), 'grow', round(grow, 2),
                  'eyes', None if ey is None else round(ey, 2), 'void', round(void, 2), 'block', round(blk_, 2), 'bg', round(bg_, 2), 'body', round(body_, 2), 'el', round(math.degrees(math.asin(max(-1, min(1, (pos - aim).normalized().z))))))
        # Keep readable faces in the finalists even when a body/slab preference gives them a lower score.
        bucket = hidden if fv and not FACE_OPT[0] and vis_low(cam.name, {face_chars[0].name + ' face': round(fv[0], 2)}) else ranked
        bucket.append((score, pos, aim, lens, vis, occ, jump))
    MC.clear()
    return sorted(ranked, key=lambda r: -r[0]) + sorted(hidden, key=lambda r: -r[0])   # _shot validates the FINAL trajectory


def shot(sc, name, f0, f1, kind='medium', subjects=(), *a, **k):
    """Choose a camera; if the best score is poor (< 0.5) retry once with a wider ring (+-60..150) and keep the better one."""
    import time as _t
    RING_EXTRA[:] = []; SAFE_KEYS.clear(); prev0 = LAST.get('cam'); t0_ = _t.time()
    r_ = sc.render   # R240 ROOT CAUSE of cropped faces: look.tier() sets 540x960 only at render time, so every camera was chosen and
    fw_, fh_ = sc.get('frame', (1080, 1920))   # B1: a story 'frame' (e.g. 16:9) is measured at its own aspect
    if r_.resolution_x * fh_ != r_.resolution_y * fw_:   # gated on Blender's default 1920x1080 frame: world_to_camera_view / view_frame
        r_.resolution_x, r_.resolution_y = fw_ // 2, fh_ // 2    # were 3.16x too WIDE (a head cut by the 9:16 edge read 'framed 1.0', a torso
        print('CAMERA frame set to 9:16 for the measures (was', 'landscape/default)')   # filling half the picture read 17 %)
    cam, v = _shot(sc, name, f0, f1, kind, subjects, *a, **k)
    print('SHOT TIME', name, round(_t.time() - t0_, 1), 's', f1 - f0 + 1, 'frames')
    if False and LAST.get('score', 9) < 0.5:   # retry experiment (02:50) disabled 03:46: regressed benches
        s1, cam1, v1 = LAST['score'], cam, v
        LAST['cam'] = prev0                         # the retry is judged against the PREVIOUS shot (jump-cut rule)
        RING_EXTRA[:] = [60, 75, 90, 105, 120, 135, 150, -60, -75, -90, -105, -120, -135, -150]
        cam2, v2 = _shot(sc, name + 'b', f0, f1, kind, subjects, *a, **k)
        RING_EXTRA[:] = []
        fk_ = next((k for k in v1 if k.endswith(' face') and not k.endswith('~')), None)
        if LAST['score'] > s1 + 0.2 and (fk_ is None or v2.get(fk_, 0) >= min(0.6, v1.get(fk_, 0))):   # never trade the focus face away
            print('SHOT RETRY better', round(s1, 2), '->', round(LAST['score'], 2))
            for m in list(sc.timeline_markers):
                if m.camera is cam1: sc.timeline_markers.remove(m)
            bpy.data.objects.remove(cam1, do_unlink=True); cam2.name = name
            return cam2, v2
        for m in list(sc.timeline_markers):
            if m.camera is cam2: sc.timeline_markers.remove(m)
        bpy.data.objects.remove(cam2, do_unlink=True); LAST['cam'] = cam1; LAST['score'] = s1
    return cam, v


def _shot(sc, name, f0, f1, kind='medium', subjects=(), side=0.0, lens=50, push=None, must_see=(), height=None, track=False,
         prev=None, cast=(), vis_until=None, angle=None, motion=None, ecu=False, soft=False, ots_first=False, punch=None, front=False, profile=False, frame=None):
    """side: degrees around the subject (+ = to the subject's left). push: fraction of the distance travelled toward the aim
    over the shot (default reference 0.4%/frame, capped 18%). cast = all characters (occluders). Returns (camera, visibility)."""
    sc.frame_set((f0 + f1) // 2); bpy.context.view_layer.update()
    c, fac, pts = _anchor(subjects)
    path = []; per = [[] for _ in subjects]            # subject heads over the shot: moving subjects must stay framed
    for f in sorted(set(list(range(f0, f1 + 1, 3)) + [f1])):    # every 3 frames: a 0.4 s jump must not fall between samples
        sc.frame_set(f)
        for i_, s_ in enumerate(subjects):
            q_ = (s_.head_mesh if hasattr(s_, 'head_mesh') else s_).matrix_world.translation.copy(); per[i_].append(q_); path.append(q_)
    sc.frame_set(f0)
    moving = any((q - p_[0]).length > 1.0 * S for p_ in per for q in p_)   # displacement PER subject (not between subjects)
    if moving:
        c = sum(path, Vector()) / len(path); pts = path
    H0, aim_z = SIZES[kind]
    UNSHOW_D[0] = 0.8 if kind in ('close', 'insert') else 1.5
    FACE_OPT[0] = False   # set below once 'moving' is known
    EYES_W[0] = {'close': 1.5, 'medium': 0.8}.get(kind, 0.0) if len(subjects) == 1 and hasattr(subjects[0], 'head_mesh') else 0.0   # medium: blind6_park, every fringe over the eyes
    if kind == 'close' and len(subjects) == 1 and hasattr(subjects[0], 'head_mesh'):   # big library hair (Vegeta's spikes) must
        ch0 = subjects[0]                                                               # fit: frame = 1.45 x (head + hair) height
        zs = [(o.matrix_world @ Vector(c)).z for o in [ch0.head_mesh] + [h for h in ch0.hair_pivot.children_recursive if h.type == 'MESH']
              for c in o.bound_box]
        zb_ = min((ch0.head_mesh.matrix_world @ Vector(c)).z for c in ch0.head_mesh.bound_box)   # hair hanging BELOW the chin is not
        H0 = max(H0, 1.45 * (max(zs) - zb_))   # head height: long hair made every close a medium (blind5_living Mia: frame 1.9 m, head 32 %)
        if ecu: H0, lens = 1.1, 60   # EXTREME close-up: the head fills ~60 % of the frame height (0.8 m / 85 mm cropped the face to a hair-covered slab, critic R206)
    holder = None
    if kind == 'insert' and len(subjects) == 1 and not hasattr(subjects[0], 'head_mesh') and cast:   # held prop: the character whose hand is nearest
        sc.frame_set((f0 + f1) // 2); pp_ = subjects[0].matrix_world.translation
        holder = min(cast, key=lambda c_: min((a_.matrix_world.translation - pp_).length for a_ in c_.arms))
        if min((a_.matrix_world.translation - pp_).length for a_ in holder.arms) > 1.2: holder = None
    if kind == 'insert' and holder is None and not hasattr(subjects[0], 'head_mesh'):   # a RESTING prop fills at most ~45 % of the frame
        ms_ = [o for s_ in subjects for o in ([s_] if s_.type == 'MESH' else [x for x in s_.children_recursive if x.type == 'MESH'])]   # (a 0.5 m box filled all of a 0.9 m frame after the push-in)
        if ms_:
            pp_ = [o.matrix_world @ Vector(c_) for o in ms_ for c_ in o.bound_box]
            H0 = max(H0, 2.2 * max(max(q[i_] for q in pp_) - min(q[i_] for q in pp_) for i_ in range(3)))
    if holder is not None: H0 = 1.4   # a prop IN A HAND: hand + prop + a bit of body (0.9 m lost a moving hand-over off the frame edge and read as a grey sleeve)
    top_fit = body_points(sc, [s_ for s_ in subjects if hasattr(s_, 'head_mesh')], f1) if frame == 'auto' else None   # cam2 landing shot: the frame is fitted to the whole lying body (bodies) + crater
    if frame and frame != 'auto': H0 = float(frame)   # shot key 'frame': frame HEIGHT in metres (e.g. a top-down that must show a whole lying body + its crater)
    aim = Vector((c.x, c.y, (aim_z * S) if aim_z and kind != 'close' else c.z))
    if kind in ('close', 'insert') and len(subjects) == 1 and hasattr(subjects[0], 'head_mesh'):   # aim at the FACE, not the hair
        hm = subjects[0].head_mesh; lo_ = Vector(min(v[i] for v in hm.bound_box) for i in range(3)); hi_ = Vector(max(v[i] for v in hm.bound_box) for i in range(3))
        aim = hm.matrix_world @ Vector(((lo_.x + hi_.x) / 2, lo_.y, lo_.z + 0.42 * (hi_.z - lo_.z)))
        if kind == 'close' and not ecu: aim.z = max(aim.z, max(zs) - 0.38 * H0)
        if kind == 'close' and not ecu: aim.z = min(aim.z, (hm.matrix_world @ ((lo_ + hi_) / 2)).z + 0.07 * H0)   # cam2: ... but never so far that the FACE drops into the caption zone (Vegeta's spikes: face at 30 % on every static close); the hair top is cropped instead   # R240 tall hair: aimed at the face, the hair top left the
        # frame after the push-in on every candidate ('head cropped' 42 of 68 tried cameras, blind6_park s02): raise the aim just enough
    if kind in ('full', 'wide'):
        aim.z = min(p.z for p in pts) - (4.62 - aim_z) * S
        if (sc.get('frame') or (1, 2))[0] > (sc.get('frame') or (1, 2))[1]: aim.z = (min(p.z for p in pts) + max(p.z for p in pts)) / 2   # B1 landscape: centre the bodies (the 9:16 low aim left half the frame as floor)
    cands = []
    multi = len(pts) > 1 and not (moving and kind == 'insert' and len(subjects) == 1)   # a moving prop: insert size, tracked (homework give: 'grow' 5.0)
    if moving and kind in ('close', 'insert'): track = True    # a jumping/turning head must not leave a close-up
    # a WIDE/FULL shot of a MOVING character (runs out, chase): the action reads from the body; face report-only, head still gated
    # (reference shows backs in exits/chases; blind3 bedroom Ben ran out the door, R182). Ranking still prefers face-visible angles.
    FACE_OPT[0] = moving and kind in ('wide', 'full') and len(subjects) == 1 or bool(profile) or bool(top_fit)   # shot key 'profile': an authored side-on fight two-shot, faces in profile (report-only)
    span_k = 1.0                                       # whole path fits (0.6 lost fast runners off the frame edge)
    sc.frame_set(f1)   # judge at the END of the shot (a fall that starts inside it counts)
    lying = len(subjects) == 1 and hasattr(subjects[0], 'head') and _lying(subjects[0])
    if lying:   # ... and already at the MIDDLE: a fall in the last frames of a shot is filmed upright (a top-down chosen for the END
        sc.frame_set((f0 + f1) // 2)   # showed 0.5 s of hair top + floor before the fall: creator bug '0:18 camera', R259)
        lying = _lying(subjects[0])
    if top_fit: lying = False   # its own straight-down ring below, not the 78 / 60 deg lying round
    if angle == 'top' and soft and not lying and len(subjects) == 1 and hasattr(subjects[0], 'head'): angle = 'high'   # same bug: the engine's top-down is for a body on the ground
    if motion == 'follow': track = True   # only its fallback (a fixed camera that pans) uses it
    sc.frame_set(f0)
    ring = tuple(range(0, 360, 30)) if lying else ((-105, -90, -75, -60, -45, -30, -15, 0, 15, 30, 45, 60, 75, 90, 105) if multi else (-75, -60, -45, -30, -15, 0, 15, 30, 45, 60, 75))
    if front: ring = (-30, -15, 0, 15, 30)   # camera modes two_shot_react / static_wide: the cast plays to the lens, the lens stays in front of it
    ring = ring + tuple(RING_EXTRA)
    if profile and multi and len(pts) >= 2:   # authored side-on fight two-shot: the lens looks ACROSS the fighters' line, from the audience side (-Y)
        ln_ = pts[1] - pts[0]; n_ = Vector((-ln_.y, ln_.x, 0))
        if n_.length > 1e-4:
            n_.normalize(); fac = -n_ if n_.y > 0 else n_; side = 0.0; ring = (0, -10, 10, -20, 20)
    if top_fit: side = 0.0; ring = tuple(range(0, 360, 30))   # every azimuth: the one that fits the body tightest and has no rock pillar under the lens wins
    # SPEAKER IN PROFILE (cam2): a single on a character whose face is sideways to the audience (talking to someone beside him: the
    # spot in front of his face is behind the listener's back) is shot 3/4 FRONT from the audience side (-Y), 5-75 deg off the
    # face, never from the far side or behind (what the writers did by hand with side: -50). An authored side / front wins.
    if (len(subjects) == 1 and hasattr(subjects[0], 'head_mesh') and not side and not front and not profile and not lying and not moving
            and not top_fit and kind in ('close', 'medium') and abs(fac.x) > 0.6 and not RING_EXTRA):
        side = 50.0 if (fac.x * math.sin(math.radians(50)) + fac.y * math.cos(math.radians(50))) < (-fac.x * math.sin(math.radians(50)) + fac.y * math.cos(math.radians(50))) else -50.0
        ring = (0, -15, 15, -30, 25, -45); print('SHOT 3/4', name, 'face sideways to the audience -> side', side)

    def gen_cands(ring, lms, mild=False, angle=angle, hk=1.0):
      cands = []
      for dside in ring:   # lying focus (face to the sky/floor): any azimuth can work, try the full ring
        a = math.radians(side + dside)
        dirv = Vector((fac.x * math.cos(a) - fac.y * math.sin(a), fac.x * math.sin(a) + fac.y * math.cos(a), 0))
        H = H0 * hk
        if multi:
            # 9:16: only the spread ACROSS the view must fit the width -> staging in depth keeps the frame tight
            lat = Vector((-dirv.y, dirv.x, 0))
            spread = max(abs((p - q).dot(lat)) for p in pts for q in pts)
            H = max(H, (span_k * spread + 3.0 * S) * 16 / 9)
        aim_ = aim
        if top_fit: H, aim_ = fit_top(top_fit, -dirv); aim_.z += 0.3   # looking down, screen-up points away from the camera's side
        for lm in lms:   # inserts (retry ring): longer lenses = same framing from further back, over low occluders
            L = lens * lm; d = H * L / 36.0
            # PITCH MUST READ (reference R2; critic R206 'one angle family: eye-level'): low = from the GROUND looking up, high = clearly
            # down, top = top-down (falls). mild = the pre-R213 values: the fallback round when the extreme pitch reads nothing
            wf = kind in ('wide', 'full')
            mild = mild or (soft and angle == 'low' and kind == 'medium')   # R240 frames 1-3: an engine-chosen ground-level low on a 9:16 medium = a torso tower, the face a chin at the top edge
            if mild: pm = {'low': -5 if kind == 'close' else (-18 if wf else -12), 'high': 8 if kind == 'close' else (34 if wf else 24), 'top': 8 if kind == 'close' else (34 if wf else 24)}
            else: pm = {'low': -16 if kind == 'close' else (-14 if wf else -22), 'high': 14 if kind == 'close' else (40 if wf else 32), 'top': 86 if frame else 68}   # an authored `frame` top view is a TRUE straight-down (whole lying body + crater)
            pitch = pm.get(angle, 6 if lm != 1.25 or multi else 14)
            if height is not None: pos = aim_ + dirv * d + Vector((0, 0, height * S - aim_.z))
            elif pitch > 45: pos = aim_ + (dirv * math.cos(math.radians(pitch)) + Vector((0, 0, math.sin(math.radians(pitch))))) * d   # top-down: on a sphere
            else: pos = aim_ + dirv * d + Vector((0, 0, d * math.tan(math.radians(pitch))))
            pos.z = max(pos.z, 0.3 if angle == 'low' and not mild else 0.9)   # low = ground level (lens 30 cm up); else never below knee height
            b = _cb()
            if b:   # inside a room: dolly in along the view ray until 0.25 m inside the walls, open the lens to keep the frame
                m = 0.25; k = 1.0
                for i, (lo_, hi_) in enumerate(((b[0], b[1]), (b[2], b[3]))):
                    v = pos[i] - aim_[i]
                    if pos[i] > hi_ - m and v > 1e-6: k = min(k, (hi_ - m - aim_[i]) / v)
                    if pos[i] < lo_ + m and v < -1e-6: k = min(k, (lo_ + m - aim_[i]) / v)
                if k < 1.0:
                    if L * k < 16: continue            # would need wider than 16 mm: skip this angle
                    pos = aim_ + (pos - aim_) * k; L = L * k
            for _ in range(12):   # never INSIDE furniture (lockers, bookcases, counters): dolly in until clear
                hit = any(x0 - 0.15 < pos.x < x1 + 0.15 and y0 - 0.15 < pos.y < y1 + 0.15 and pos.z < top + 0.1
                          for x0, x1, y0, y1, top in ROOM.get('obstacles') or [])
                if not hit: break
                pos = aim_ + (pos - aim_) * 0.88; L *= 0.88
            else:
                continue
            if L < 14: continue
            cands.append((pos, aim_.copy(), L, H / H0))
      return cands
    is_insert = kind == 'insert'
    cands = gen_cands(ring, (1.0, 0.8, 1.25)); ots = []
    if EYES_W[0] and angle != 'low' and not lying:   # UNDER THE FRINGE: a close-up may also look up at the face (wins only on the eyes term)
        cands += gen_cands((-30, 0, 30), (1.0,), angle='low')
    # OVER-THE-SHOULDER candidates (dialogue grammar): two characters facing each other within ~4.5 m -> camera behind the
    # SECOND subject's shoulder (left and right), framing the FOCUS face, the partner's shoulder in the foreground. Scored and
    # validated like every candidate (the OTS partner rule already allows a foreground body up to 35 %).
    chs_ = [x for x in subjects if hasattr(x, 'head_mesh')]
    if kind in ('medium', 'close') and len(chs_) == 2:
        sc.frame_set((f0 + f1) // 2); bpy.context.view_layer.update()
        A_, B_ = chs_[0].head_mesh.matrix_world.translation.copy(), chs_[1].head_mesh.matrix_world.translation.copy()
        fa = (chs_[0].head.matrix_world.to_3x3() @ Vector((0, -1, 0))); fb = (chs_[1].head.matrix_world.to_3x3() @ Vector((0, -1, 0)))
        ab = (B_ - A_); ab.z = 0
        if 0.8 < ab.length < 4.5 and fa.dot(ab.normalized()) > 0.3 and fb.dot(-ab.normalized()) > 0.3:   # facing each other
            back = ab.normalized(); lat = Vector((-back.y, back.x, 0))
            for sg in (1, -1):
                for k_, s_ in ((1.0, 0.5), (1.4, 0.5)) + (((1.2, 0.8), (1.2, 1.0), (1.5, 0.9)) if ots_first else ()):   # further behind the partner, longer lens: a shoulder edge, not a back (was 0.55 / 0.9 m)
                    # ots_dialogue mode, true 9:16 frame: 0.5 m to the side put the partner's head across half of the narrow frame (L1 cam 03
                    # sheet); 0.8-1.0 m leaves it the outer quarter
                    q = B_ + back * k_ + lat * sg * s_ + Vector((0, 0, 0.12))
                    tgt = A_ - Vector((0, 0, 0.05)); L_ = 36.0 * (q - tgt).length / max(0.9, SIZES[kind][0] * 0.8)
                    if 18 <= L_ <= 85: ots.append((q, tgt, L_, 1.0))
    pair_ = frozenset(x.name for x in chs_)
    if ots_first and ots and pair_ in AXIS:   # 180-DEGREE RULE: every OTS camera of a dialogue stays on one side of the line of action
        mid_ = (A_ + B_) / 2; ots = [o for o in ots if (o[0] - mid_).dot(AXIS[pair_]) > 0] or ots
    if not angle: cands += ots   # a shot with a PITCH (low/high/top) shows it: eye-level OTS spots only in its mild fallback round
    # SAFE candidates: high room corners (or a high ring outdoors) aimed at the subjects, lens fitted to the shot size. In a crowded
    # set (desks + 3 people) every close spot can be blocked; a high corner always reads and only wins when nothing closer does.
    b = ROOM['bounds']; hz = 7.0 * S
    spots = ([(b[0] + 0.35, b[2] + 0.35), (b[1] - 0.35, b[2] + 0.35), (b[0] + 0.35, b[3] - 0.35), (b[1] - 0.35, b[3] - 0.35)]
             if b and (b[1] - b[0]) < 30 else [(aim.x + 7 * math.cos(a_), aim.y + 7 * math.sin(a_)) for a_ in (3.9, 4.7, 5.5)])
    for sx, sy in []:   # safe-corner experiment disabled 03:46 (regressed benches); spots kept for later   # never for close-ups/inserts (steep look down at a face)
        pos = Vector((sx, sy, max(hz, aim.z + 1.2))); d = (aim - pos).length
        L = max(16.0, min(120.0, 36.0 * d / max(H0, 1.0)))
        cands.append((pos, aim.copy(), L, 1.0 + 0.15)); SAFE_KEYS.add((round(pos.x, 1), round(pos.y, 1), round(pos.z, 1), round(L)))
    cd = bpy.data.cameras.new(name); cd.sensor_fit = 'VERTICAL'; cd.sensor_height = 36; cd.clip_end = 200
    cam = bpy.data.objects.new(name, cd); bpy.context.collection.objects.link(cam)
    subj_chars = [s for s in subjects if hasattr(s, 'head_mesh')]
    CAST_NAMES[:] = [ch.name + ' ' for ch in cast]
    BODY['heads'] = {o for ch in subj_chars for o in (ch.head, ch.hair_pivot, ch.head_mesh)}
    top_of = lambda o: o if o.parent is None else top_of(o.parent)
    BODY['mine'] = {top_of(ch.root) for ch in subj_chars}
    BODY['thr'] = 0.15 if not subj_chars else ((0.5 if kind in ('close', 'medium') else 9.0) if len(subj_chars) == 1 else 9.0)
    on_key = ','.join(getattr(s_, 'name', '?') for s_ in subjects)
    targets = list(must_see) or [s.head_mesh for s in subj_chars] + [s for s in subjects if not hasattr(s, 'head_mesh')]
    targets = [m for t in targets for m in ([t] if t.type == 'MESH' else [o for o in t.children_recursive if o.type == 'MESH'][:2])]
    occluders = [o for ch in cast if ch not in subj_chars for o in (ch.torso, ch.head_mesh, *ch.arms, *[h for h in ch.hair_pivot.children if h.type == 'MESH' and h.name.startswith('hair lib')])] + [a for ch in subj_chars for a in ch.arms]
    people = [o for ch in cast for o in (ch.torso, ch.head_mesh, *ch.arms)]   # nearest SURFACE of any body part
    frames = sorted({f0, f0 + (f1 - f0) // 4, (f0 + f1) // 2, f0 + 3 * (f1 - f0) // 4, f1})
    push_k = 0.0 if moving else (min(0.18, 0.004 * (f1 - f0)) if push is None else push)   # no dolly toward a moving subject
    sc.frame_set((f0 + f1) // 2); bpy.context.view_layer.update()
    faces = []   # (head position, 3D face direction): lying characters face the sky, so the proxy must be 3D
    for ch in subj_chars:
        hf = (ch.head.matrix_world.to_3x3() @ Vector((0, -1, 0))).normalized()
        faces.append((ch.head_mesh.matrix_world.translation.copy(), hf))
    prev_ = prev if prev is not None else LAST['cam']
    same = prev_ is not None and prev_.get('on') == on_key   # same subject(s) as the previous shot: the cut must change the angle
    def choose(cs):
        return _choose(sc, cam, cs, frames, targets, occluders, people, prev_, faces,
                       [ch.torso for ch in subj_chars] if len(subj_chars) > 1 else (), subj_chars, cast[0].head_mesh if cast else None, track, push_k, vis_until,
                       {a.name: True for ch in subj_chars for a in ch.arms}, near_min=0.6 if kind == 'insert' and not subj_chars else 1.2, same=same)
    hold_face = kind == 'close' and len(subj_chars) == 1 and len(subjects) == 1 and not ecu   # cam2: a close-up holds the face on EVERY frame
    dense = sorted(set(list(range(f0, f1 + 1, 1 if hold_face else 3)) + [f1]))
    side_heads = {ch.head_mesh.name for ch in subj_chars[1:]}          # non-focus heads: reported with '~', not gated (OTS)
    def frame_measures(fv, sd_):
        """Report-only '~' numbers of the MOVED camera (a push-in dollies onto a desk edge): slab / void, body share, face-on."""
        one_ = len(subj_chars) == 1 and len(subjects) == 1   # a single: another actor's arm sweeping past the lens is looked for on 7 frames (showcase s02: Goku's arm across Krillin's close for its first 6 frames, missed by f0 / mid / f1)
        fg_ = [fg_void(sc, cam, f_, sd_) for f_ in (sorted({f0, min(f1, f0 + 3), min(f1, f0 + 6), f0 + (f1 - f0) // 4, (f0 + f1) // 2, f0 + 3 * (f1 - f0) // 4, f1}) if one_ and BODY['thr'] < 9 else (f0, (f0 + f1) // 2, f1) if BODY['thr'] < 9 else (f0, f1))]
        ends_ = (fg_[0], fg_[-1])
        fv['fg~'] = round(max(x[0] for x in ends_), 2); fv['fgb~'] = round(max(x[1] for x in ends_), 2)
        if ROOM.get('cam'): fv['bg~'] = round(max(x[2] for x in ends_), 2)
        if BODY['thr'] < 9: fv['body~'] = round(max(x[3] for x in fg_), 2)
        if one_: fv['other~'] = round(max(x[4] for x in fg_), 2)
        if top_fit or (angle == 'top' and frame): fv['fg~'] = max(fv['fg~'], fv['fgb~'])   # straight down: ANY set geometry between the lens and the body (a rock pillar top) is a slab
        if subj_chars and FRONT and not FACE_OPT[0] and not lying: fv[subj_chars[0].name + ' front~'] = round(sum(FRONT) / len(FRONT), 2)
    still_ = set()   # candidates whose camera move lost a target the static camera shows: held still (handheld drift only)
    def apply(r):
        """Key the real shot (move + tracking) from candidate r and measure what the gate will measure: the FINAL trajectory."""
        P, A = r[1], r[2]
        def key(tr):
            cam.animation_data_clear(); cd.animation_data_clear(); cd.lens = r[3]
            cam.location = P; cam.rotation_euler = (A - P).to_track_quat('-Z', 'Y').to_euler()
            mv = ('track' if motion == 'follow' else motion) if motion else ('track' if tr else ('push' if kind in ('close', 'insert') else 'arc' if kind == 'medium' else 'pull'))
            if id(r[1]) in still_: mv = 'still'
            _move_camera(sc, cam, P, A, f0, f1, mv, kind, people, name, subj_chars[0] if subj_chars else None)
            if tr: ia.frame_targets(sc, cam, list(range(f0, f1 + 1)), targets, lag=0.3, max_turn_deg=18)
            if punch is not None:   # CRASH ZOOM (camera mode punch_in): 1.8x wider until the punchline, the full close 4 frames later
                for f_, l_ in ((f0, r[3] / 1.8), (punch - 2, r[3] / 1.8), (punch + 2, r[3])): cd.lens = l_; cd.keyframe_insert('lens', frame=f_)
            _compat(cam)
            return measure(sc, cam, dense, targets, vis_until, subj_chars)
        tv, fl = key(track)
        if not track and not motion and moving and len(subj_chars) == 1 and kind in ('full', 'wide') and FRAMED and sum(FRAMED) / len(FRAMED) < 0.9:
            # a FIXED full/wide whose walker's head leaves the frame (framed for where he ends up, on the floor: his head was cut
            # by the top edge for the 0.5 s before the fall, f_a_determined s03 S04, R259) pans with him when that keeps the head in
            fr0 = sum(FRAMED) / len(FRAMED); tv2, fl2 = key(True)
            if sum(FRAMED) / len(FRAMED) > fr0 + 0.05 and min(x[0] for x in tv2.values()) >= min(x[0] for x in tv.values()) - 0.05: tv, fl = tv2, fl2
            else: tv, fl = key(False)
        if hold_face and not motion and punch is None and SAFE and not all(SAFE):
            # cam2 A CLOSE-UP HOLDS THE FACE ON EVERY FRAME: the push-in / a pose change took the face out of the frame or under the
            # caption zone -> no push (still), then a camera that re-aims at the head (pan), then both; first variant that holds wins
            st0 = id(r[1]) in still_; opts = [(track, st0)]; got = [sum(SAFE)]
            for tr_, st_ in [o_ for o_ in ((track, True), (True, st0), (True, True)) if o_ != (track, st0)]:
                (still_.add if st_ else still_.discard)(id(r[1])); tv, fl = key(tr_); opts.append((tr_, st_)); got.append(sum(SAFE))
                if all(SAFE): break
            else:
                tr_, st_ = opts[got.index(max(got))]; (still_.add if st_ else still_.discard)(id(r[1])); tv, fl = key(tr_)
            print('HOLD FACE', name, 'variants tried (pan, still)', opts, 'frames held', got, 'of', len(dense))
        fv = {ch.name + (' face' if i == 0 and not FACE_OPT[0] else ' face~'): round(fl[i], 2) for i, ch in enumerate(subj_chars)}
        if subj_chars and kind in ('close', 'medium') and not ecu and FRAMED: fv[subj_chars[0].name + ' framed~'] = round(sum(FRAMED) / len(FRAMED), 2)
        if subj_chars and len(subjects) == 1 and kind in ('close', 'medium') and not ecu and SAFE and not lying: fv[subj_chars[0].name + ' safe~'] = int(100 * sum(SAFE) / len(SAFE)) / 100   # floor: 1.0 = every frame
        if EYES_W[0]: fv[subj_chars[0].name + ' eyes~'] = round(eyes_vis(sc, cam, subj_chars[0], dense[::2]), 2)
        frame_measures(fv, (A - P).length)
        return {**{(k + '~' if k in side_heads else k): round(v[0], 2) for k, v in tv.items()}, **fv}
    def nice(v_):   # preferences among PASSING candidates (never gates): head + hair in frame, eyes not under hair, no slab in the lens's face
        return not [x for x in unread(name, v_) if x not in ('back of a head', 'subject hidden') + (('face not shown',) if top_fit else ())] and not slab(v_)   # those two: repair round only
    def flaw(v_):   # how much of the picture is lost: slab / void share, plus hidden eyes and a cropped head (a slab-free top-of-the-hair
        g = lambda suf, dflt: next((x for k, x in v_.items() if k.endswith(suf)), dflt)   # close replaced a readable one: factory f_dad s01)
        return ((2.0 * v_.get('fg~', 0.0) + max(0.0, v_.get('fgb~', 0.0) - 0.3) + v_.get('bg~', 0.0)) if slab(v_) else 0.0)             + 0.5 * (1.0 - g(' eyes~', 1.0)) + (0.3 if g(' framed~', 1.0) < 0.9 else 0.0) \
            + (1.0 - g(' front~', 1.0) if g(' front~', 1.0) < 0.5 else 0.0) + (0.5 + v_.get('body~', 0.0) if 'limb fills the frame' in unread(name, v_) else 0.0) \
            + (0.4 if 'back of a head' in unread(name, v_) else 0.0) + (0.6 if 'subject hidden' in unread(name, v_) else 0.0) \
            + (0.5 if 'prop half hidden' in unread(name, v_) else 0.0) + (0.8 if 'face not shown' in unread(name, v_) and not top_fit else 0.0)             + 1.5 * (1.0 - g(' safe~', 1.0)) + (0.3 + v_.get('other~', 0.0) if v_.get('other~', 0.0) > 0.25 else 0.0)
    def worth(v):   # fallback order when nothing passes: focus face first, then the worst gated target
        g = [x for k, x in v.items() if not k.endswith('~')]
        return (v.get(subj_chars[0].name + ' face', 1.0) if subj_chars else 1.0, min(g) if g else 1.0)
    # The chooser scores static candidates; the gate judges the moved camera. Validate the top candidates in rank order on
    # their FINAL trajectory (move, tracking) and take the first that passes; jump-cut candidates only if nothing else passes.
    # If none passes: a second ring (full 360, longer lenses for inserts: a prop at knee height is seen over a leg from further
    # back, R135 Codex #12), validated the same way. Else the best fallback.
    def lead_path(dside, lm=1.0):
        """LEAD TRACK (reference walk-and-talk): the camera travels AHEAD of a walking/running subject at the shot-size distance,
        dside deg off its smoothed facing, so the face reads the whole walk (a fixed camera that only pans shows the back
        of the head once the walker passes it). None if any key leaves the room, enters furniture or comes < 1 m of anyone."""
        ch = subj_chars[0] if subj_chars else holder; fr = list(range(f0, f1 + 1, 2)) + ([f1] if (f1 - f0) % 2 else [])
        focus = subj_chars[0].head_mesh if subj_chars else subjects[0]   # a held prop: follow the PROP, face from its holder
        hp, fw = {}, {}
        for f in range(f0 - 8, f1 + 9):
            sc.frame_set(f); M = ch.head.matrix_world
            hp[f] = focus.matrix_world.translation.copy(); v_ = M.to_3x3() @ Vector((0, -1, 0)); v_.z = 0
            fw[f] = v_.normalized() if v_.length > 1e-6 else Vector((0, -1, 0))
        H = H0 if holder is not None else SIZES[kind][0]; L = lens * lm; d = H * L / 36.0; a = math.radians(dside); out = []
        for f in fr:
            ks = [k for k in range(f - 8, f + 9)]
            c_ = sum((hp[k] for k in ks), Vector()) / len(ks); w = sum((fw[k] for k in ks), Vector())
            w = w.normalized() if w.length > 1e-6 else fw[f]
            dv = Vector((w.x * math.cos(a) - w.y * math.sin(a), w.x * math.sin(a) + w.y * math.cos(a), 0))
            aim_ = Vector((c_.x, c_.y, c_.z if kind in ('close', 'insert') else (SIZES[kind][1] or 3.7) * S))
            q = aim_ + dv * d + Vector((0, 0, d * math.tan(math.radians(6))))
            q.z = max(q.z, 0.9)
            b = _cb()
            if b:   # the camera stops at the wall and the walker comes toward it (a dolly cannot leave the room)
                q.x = min(max(q.x, b[0] + 0.25), b[1] - 0.25); q.y = min(max(q.y, b[2] + 0.25), b[3] - 0.25)
            if any(x0 - 0.15 < q.x < x1 + 0.15 and y0 - 0.15 < q.y < y1 + 0.15 and q.z < top + 0.1 for x0, x1, y0, y1, top in ROOM.get('obstacles') or []):
                print('LEAD', name, dside, 'rejected: furniture f', f); return None
            sc.frame_set(f)
            if any(_bbox_dist(q, o) < (0.45 if kind == 'insert' else 1.0) for o in people):   # an insert sits close to the hands
                print('LEAD', name, dside, 'rejected: < 1 m of a body f', f); return None
            out.append((f, q, aim_, L))
        return out
    def apply_lead(keys):
        cam.animation_data_clear(); cd.animation_data_clear(); cd.lens = keys[0][3] if len(keys[0]) > 3 else lens
        for f, q, aim_, _L in keys:
            cam.location = q; cam.keyframe_insert('location', frame=f)
            cam.rotation_euler = (aim_ - q).to_track_quat('-Z', 'Y').to_euler(); cam.keyframe_insert('rotation_euler', frame=f)
        import locomotion as lo_
        lo_.unwrap_yaw(cam); _compat(cam)   # no 360 spin between keys; aim = smoothed head, so no frame_targets (its turn cap is for fixed cameras)
        tv, fl = measure(sc, cam, dense, targets, vis_until, subj_chars)
        fv = {ch.name + (' face' if i == 0 and not FACE_OPT[0] else ' face~'): round(fl[i], 2) for i, ch in enumerate(subj_chars)}
        frame_measures(fv, (keys[0][2] - keys[0][1]).length)   # same slab/void numbers as apply(): a lead camera without them looked
        # flawless and replaced a passing shot (blind3_bedroom s02 jump cut, R231)
        if motion == 'follow' and subj_chars:
            ch = subj_chars[0]; hb = _hb(ch.head_mesh); readable = []; run = lost = 0
            for f in range(f0, f1 + 1, 2):
                sc.frame_set(f); bpy.context.view_layer.update()
                face = _face_frame(sc, cam, ch, bpy.context.evaluated_depsgraph_get(), *hb)
                if face is None: continue
                M = ch.head_mesh.matrix_world
                front = (M.to_3x3() @ Vector((0, -1, 0))).normalized().dot((cam.matrix_world.translation - M.translation).normalized())
                c = world_to_camera_view(sc, cam, M.translation)
                ys = [world_to_camera_view(sc, cam, M @ Vector(p)).y for p in ch.head_mesh.bound_box]
                ok = face >= 0.5 and front >= 0.3 and c.z > 0 and 0.03 < c.x < 0.97 and min(ys) > -0.02 and max(ys) < 1.02
                readable.append(ok); run = 0 if ok else run + 2; lost = max(lost, run)
            fv['follow_face~'] = sum(readable) / len(readable) if readable else 1.0; fv['follow_lost~'] = lost
        return {**{(k + '~' if k in side_heads else k): round(v[0], 2) for k, v in tv.items()}, **fv}
    # any shot whose ONE character moves may lead-track (a walk with a prop and no 'track' flag lost the face: snack s02 S06, R149)
    can_lead = moving and not motion and ((len(subj_chars) == 1 and kind in ('close', 'medium', 'full', 'wide')) or (holder is not None and track))
    if os.environ.get('CAMDEBUG') and is_insert and not subj_chars:   # what lies ABOVE the prop (a prop under the ground mesh reads 0.0 everywhere)
        for t_ in targets:
            zs_ = [(t_.matrix_world @ Vector(c_)).z for c_ in t_.bound_box]; p_ = t_.matrix_world @ (sum((Vector(c_) for c_ in t_.bound_box), Vector()) / 8)
            h_ = sc.ray_cast(bpy.context.evaluated_depsgraph_get(), p_ + Vector((0, 0, 3)), Vector((0, 0, -1)), distance=6)
            print('INSERT TARGET', t_.name, 'z', round(min(zs_), 3), round(max(zs_), 3), 'first hit from above', h_[4].name if h_[0] else None, round(h_[1].z, 3) if h_[0] else None, 'hidden', t_.hide_viewport, t_.hide_render)
    def follow_path(dside):
        """FOLLOW (camera modes follow_oneshot / chase_track): ONE travelling camera for the whole shot, a virtual operator. Every
        2nd frame it wants to stand dside deg off the subject's smoothed facing (one character) or travel direction (a pair), at
        the shot-size distance. Blocked spots are replaced by nearby clear ones, favouring the requested side; a solo camera
        stays within 60 degrees of the face and follows its height. Smooth the offsets, then validate body clearance and the
        final face visibility before accepting a path."""
        fr = list(range(f0, f1 + 1, 2)) + ([f1] if (f1 - f0) % 2 else []); hp, fw = {}, {}; one = len(subj_chars) == 1; W = 6 if one else 10
        for f in range(f0 - W, f1 + W + 1):
            sc.frame_set(f); hs = [c_.head_mesh.matrix_world.translation.copy() for c_ in subj_chars]
            hp[f] = sum(hs, Vector()) / len(hs); v_ = subj_chars[0].head.matrix_world.to_3x3() @ Vector((0, -1, 0)); v_.z = 0
            fw[f] = (v_.normalized() if v_.length > 1e-6 else Vector((0, -1, 0)), hs)
        sm = lambda f, w: sum((hp[k] for k in range(f - w, f + w + 1)), Vector()) / (2 * w + 1)
        ws = []; w = fw[f0][0]
        if not one:   # a pair: start from where it first RUNS (a start facing the other way swung the camera round for 2.5 s)
            w = next((t_.normalized() for t_ in ((hp[f + W] - hp[f - W]) * Vector((1, 1, 0)) for f in fr) if t_.length > 0.6), w)
        for f in fr:   # reference direction: the face (one) / where the pair runs; turns at most 9 deg per key (108 deg/s)
            if one: t_ = sum((fw[k][0] for k in range(f - W, f + W + 1)), Vector())
            else: t_ = hp[f + W] - hp[f - W]; t_.z = 0; t_ = t_ if t_.length > 0.6 else Vector((0, 0, 0))
            if t_.length > 1e-6:
                da = math.atan2(w.x * t_.y - w.y * t_.x, w.dot(t_)) if ws or not one else 0.0; da = max(-0.157, min(0.157, da))
                w = Vector((w.x * math.cos(da) - w.y * math.sin(da), w.x * math.sin(da) + w.y * math.cos(da), 0)) if ws or not one else t_.normalized()
            ws.append(w.copy())
        rot = lambda w_, deg: Vector((w_.x * math.cos(math.radians(deg)) - w_.y * math.sin(math.radians(deg)), w_.x * math.sin(math.radians(deg)) + w_.y * math.cos(math.radians(deg)), 0))
        H = SIZES[kind][0]; L = lens
        if not one:   # the pair must fit the 9:16 width from this side
            H = max(H, max((max(abs((p_ - q_).dot(Vector((-rot(w_, dside).y, rot(w_, dside).x, 0)))) for p_ in fw[f][1] for q_ in fw[f][1]) + 2.0 * S) * 16 / 9 for f, w_ in zip(fr, ws)))
        d = H * L / 36.0; b = _cb(); obst = ROOM.get('obstacles') or []
        cam.animation_data_clear(); cd.animation_data_clear(); cd.lens = L
        top_ = lambda o: o if o.parent is None else top_(o.parent)
        mine = {top_(c_.root) for c_ in subj_chars}
        def clear(q, los=None):
            if b and not (b[0] + 0.3 < q.x < b[1] - 0.3 and b[2] + 0.3 < q.y < b[3] - 0.3): return False
            if any(x0 - 0.2 < q.x < x1 + 0.2 and y0 - 0.2 < q.y < y1 + 0.2 and q.z < top + 0.1 for x0, x1, y0, y1, top in obst): return False
            if any(_bbox_dist(q, o) < (0.9 if los is not None else 0.25) for o in people): return False
            if los is not None:
                dv_ = los - q; hit, _, _, _, ob_, _ = sc.ray_cast(bpy.context.evaluated_depsgraph_get(), q, dv_.normalized(), distance=dv_.length - 0.05)
                if hit and top_(ob_) not in mine: return False
                if one:
                    ch = subj_chars[0]; M = ch.head_mesh.matrix_world
                    if (M.to_3x3() @ Vector((0, -1, 0))).normalized().dot((q - M.translation).normalized()) < 0.45: return False
                    cam.location = q; cam.rotation_euler = (los - q).to_track_quat('-Z', 'Y').to_euler(); bpy.context.view_layer.update()
                    face = _face_frame(sc, cam, ch, bpy.context.evaluated_depsgraph_get(), *_hb(ch.head_mesh))
                    if face is not None and face < 0.5: return False
            return True
        raw = []; aims = []; az0 = dside
        for f, w_ in zip(fr, ws):
            sc.frame_set(f); bpy.context.view_layer.update(); c_ = sm(f, 4)
            aim_ = Vector((c_.x, c_.y, c_.z if kind in ('close', 'insert') else (SIZES[kind][1] or 3.7) * S))
            if one and kind not in ('close', 'insert'): aim_.z += c_.z - hp[f0].z   # follow the head through jumps and crouches too
            azs = range(-60, 61, 15) if one else range(int(dside) - 105, int(dside) + 106, 15)
            opts = sorted(((abs(az - az0) + 1.1 * abs(az - dside) + (60 if one else 400) * abs(1 - dk), az, dk) for az in azs for dk in ((1.0, 1.25, 1.5, 0.8, 0.62) if one else (1.0, 0.8, 0.62))))   # return toward the face after an obstacle; a pair keeps room for both runners
            for _, az, dk in opts:
                q = aim_ + rot(w_, az) * d * dk; q.z = max(aim_.z + d * dk * math.tan(math.radians(8)), 0.9)
                if clear(q, subj_chars[0].head_mesh.matrix_world.translation): raw.append(q - aim_); aims.append(aim_); az0 = az; break
            else:
                print('FOLLOW', name, dside, 'rejected: no clear spot f', f); return None
        out = []
        radius = 3 if one else 4
        for _ in range(2):   # smooth the offset so obstacle avoidance eases in without lagging behind a runner
            # The OFFSET from the aim is smoothed, not the position: a smoothed position ran 2 m ahead of a runner at the start of the shot
            raw = [sum(raw[max(0, i - radius):i + radius + 1], Vector()) / len(raw[max(0, i - radius):i + radius + 1]) for i in range(len(raw))]
        for i, f in enumerate(fr):
            q = aims[i] + raw[i]; sc.frame_set(f)
            if not clear(q): print('FOLLOW', name, dside, 'rejected: smoothed path blocked f', f); return None
            out.append((f, q, aims[i], L))
        return out
    tried = []; best = None; v = None
    pre = []   # mode candidates validated BEFORE the regular rounds: the follow paths / the over-the-shoulder spots; least-flawed passing one wins
    if motion == 'follow' and subj_chars:
        FACE_OPT[0] = False   # a follow shot never loses the face: gated
        for ds in ((side, side - 25, side + 25, side - 45, side + 45) if len(subj_chars) == 1 else (side, -side, 0.7 * side, -0.7 * side)):
            k_ = follow_path(ds)
            if k_: pre.append((0.0, k_[0][1], k_[0][2], lens, {}, {}, False, k_))
    elif ots_first and ots: pre = choose(ots)[:6]
    for r in pre:
        v_ = apply_lead(r[7]) if len(r) > 7 else apply(r); tried.append((r, v_))
        if os.environ.get('CAMDEBUG'): print('TRIED', name, 'pre', [round(x / S, 1) for x in r[1]], v_, 'low', vis_low(name, v_), 'unread', unread(name, v_))
    ok_ = [t for t in tried if not vis_low(name, t[1]) and not t[0][6]
           and (motion != 'follow' or (t[1].get('follow_face~', 0) >= (0.9 if len(subj_chars) == 1 else 0.75) and t[1].get('follow_lost~', 99) <= 10))]
    if ok_:
        best, v = min(ok_, key=lambda t: flaw(t[1]))
        if tried[-1][0] is not best: v = apply_lead(best[7]) if len(best) > 7 else apply(best)
        print('SHOT MODE', name, 'follow path' if len(best) > 7 else 'over the shoulder', 'candidate', [t[0] for t in tried].index(best) + 1, 'of', len(tried))
    rounds = [lambda: choose(cands)]
    if profile and multi:   # cam2: the shot before it is the same side-on set-up (two fight shots in a row): every pure profile is a jump cut ->
        rounds.append(lambda: choose(gen_cands((-35, 35, -50, 50), (1.0, 0.8, 1.25))))   # still from the audience side, 35-50 deg round the pair
    n_pitch = 1   # rounds that may still improve on a merely-passing pitched candidate (below)
    if angle:
        if soft:   # engine-chosen pitch: desks block the ground-level view -> look DOWN over them instead (and vice versa)
            rounds.append(lambda: choose(gen_cands(ring, (1.0, 0.8, 1.25), angle='low' if angle == 'high' else 'high'))); n_pitch += 1
        rounds.append(lambda: choose(gen_cands(ring, (1.0, 0.8, 1.25), mild=True) + ots)); n_pitch += 1   # the pitch reads nothing here: the mild pitch
        if soft: rounds.append(lambda: choose(gen_cands(ring, (1.0, 0.8, 1.25), angle=None) + ots)); n_pitch += 1   # ... or eye level
    if lying and kind != 'insert':   # on the FLOOR (fall, knockback): look DOWN at them first (reference top-downs; an eye-level close
        def lying_round():           # on a face-down body reads its own spread arm: blind3_kitchen s02 head 0.26)
            out = []; dd = H0 * lens / 36.0; b_ = _cb()
            for el in (78, 60):
                for az in range(0, 360, 45):
                    a_ = math.radians(az); e_ = math.radians(el)
                    q = aim + Vector((math.cos(a_) * math.cos(e_), math.sin(a_) * math.cos(e_), math.sin(e_))) * dd
                    if b_ and not (b_[0] + 0.25 < q.x < b_[1] - 0.25 and b_[2] + 0.25 < q.y < b_[3] - 0.25): continue
                    if any(x0 - 0.15 < q.x < x1 + 0.15 and y0 - 0.15 < q.y < y1 + 0.15 and q.z < top + 0.1 for x0, x1, y0, y1, top in ROOM.get('obstacles') or []): continue
                    out.append((q, aim.copy(), lens, 1.0))
            return choose(out) if out else []
        rounds.insert(0, lying_round)
    if kind in ('insert', 'close') and not subj_chars and holder is None:   # a prop RESTING on furniture: look DOWN at it from above,
        def top_round():                                          # stationary (a low grazing push read 0.26; from above 0.56, R152 #7)
            out = []; H = H0; L = lens * 1.3; d = H * L / 36.0; b = _cb()
            for el, dk in ((35, 1.0), (35, 0.75), (50, 1.0), (50, 0.75), (65, 1.0)):   # Codex measured 35 deg / 1.5 m = 0.56 (R152 #7)
                for az in range(0, 360, 45):
                    a_ = math.radians(az); e_ = math.radians(el)
                    q = aim + Vector((math.cos(a_) * math.cos(e_), math.sin(a_) * math.cos(e_), math.sin(e_))) * d * dk
                    if b and not (b[0] + 0.2 < q.x < b[1] - 0.2 and b[2] + 0.2 < q.y < b[3] - 0.2): continue
                    if any(x0 - 0.15 < q.x < x1 + 0.15 and y0 - 0.15 < q.y < y1 + 0.15 and q.z < top + 0.1 for x0, x1, y0, y1, top in ROOM.get('obstacles') or []): continue
                    sc.frame_set(f0)
                    if any(_bbox_dist(q, o) < 0.6 for o in people): continue
                    out.append((0.0, q, aim.copy(), L, {}, {}, False, [(f0, q, aim.copy(), L), (f1, q, aim.copy(), L)]))
            return out
        rounds_extra = [top_round]
    else:
        rounds_extra = []
    if kind == 'insert' and holder is not None:   # a prop IN A HAND: also from above the hands (bodies block the level ring)
        def held_round():
            out = []; dd = H0 * lens * 1.3 / 36.0; b_ = _cb()
            for el in (40, 60):
                for az in range(0, 360, 45):
                    a_ = math.radians(az); e_ = math.radians(el)
                    q = aim + Vector((math.cos(a_) * math.cos(e_), math.sin(a_) * math.cos(e_), math.sin(e_))) * dd
                    if b_ and not (b_[0] + 0.2 < q.x < b_[1] - 0.2 and b_[2] + 0.2 < q.y < b_[3] - 0.2): continue
                    out.append((q, aim.copy(), lens * 1.3, 1.0))
            return choose(out) if out else []
        rounds.append(held_round)
    if can_lead:   # lead candidates: (score, P0, A0, lens, vis, occ, jump, keys) - P0/A0 = first key (jump-cut check uses the cut frame)
        def lead_jump(q, aim_):   # same jump-cut rule as _choose's stage 1, at the cut frame (a lead skipped it: homework f370, R152 #8)
            if prev_ is None or not cast: return False
            hero_ = cast[0].head_mesh
            sc.frame_set(f0 - 1); bpy.context.view_layer.update()
            dprev = (prev_.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized(); hprev = _hero_h(sc, prev_, hero_)
            sc.frame_set(f0); cam.animation_data_clear(); cam.location = q; cam.rotation_euler = (aim_ - q).to_track_quat('-Z', 'Y').to_euler()
            bpy.context.view_layer.update(); hh = _hero_h(sc, cam, hero_)
            ang = math.degrees(math.acos(max(-1.0, min(1.0, (aim_ - q).normalized().dot(dprev)))))
            return ang < 35 and max(hh, hprev) / max(1e-6, min(hh, hprev)) < 1.6
        def lead_round():
            out = []
            for lm_ in ((1.0,) if holder is None else (1.0, 1.6, 2.2)):   # inserts: longer lens = same framing from further back
                for ds in ((0, -25, 25, -45, 45) if holder is None else (0, -30, 30, -60, 60, -90, 90)):
                    k_ = lead_path(ds, lm_)
                    if k_: out.append((0.0, k_[0][1], k_[0][2], lens * lm_, {}, {}, lead_jump(k_[0][1], k_[0][2]), k_))
            return out
        rounds.append(lead_round)
    print('LEAD', name, 'can_lead', can_lead, 'moving', moving, 'track', track, 'kind', kind, 'motion', motion)
    rounds += rounds_extra
    rounds.append(lambda: choose(gen_cands(tuple(range(0, 360, 30)), (1.0, 1.6, 2.2) if is_insert else (1.0, 0.8, 1.25))))
    if kind != 'insert':   # LAST RESORT: a HIGH camera looking down over shelves/desk rows (store aisle hid Nico from every
        def high_round():   # eye-level angle, R177). Only reached when nothing else passes; validated by the same rule.
            out = []; b_ = _cb(); Hh = SIZES[kind][0]
            for az in range(0, 360, 30):
                for el in (35, 50):
                    a_ = math.radians(side + az); e_ = math.radians(el); dd = Hh * lens / 36.0
                    dirv = Vector((fac.x * math.cos(a_) - fac.y * math.sin(a_), fac.x * math.sin(a_) + fac.y * math.cos(a_), 0))
                    q = aim + dirv * dd * math.cos(e_) + Vector((0, 0, dd * math.sin(e_)))
                    if b_ and not (b_[0] + 0.25 < q.x < b_[1] - 0.25 and b_[2] + 0.25 < q.y < b_[3] - 0.25): continue
                    if any(x0 - 0.15 < q.x < x1 + 0.15 and y0 - 0.15 < q.y < y1 + 0.15 and q.z < top + 0.1 for x0, x1, y0, y1, top in ROOM.get('obstacles') or []): continue
                    out.append((q, aim.copy(), lens, 1.0))
            return choose(out) if out else []
        rounds.append(high_round)
    def real_jump():
        if prev_ is None or not cast: return False
        hero_ = cast[0].head_mesh
        sc.frame_set(f0 - 1); bpy.context.view_layer.update()
        dp_ = (prev_.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized(); hp_ = _hero_h(sc, prev_, hero_)
        sc.frame_set(f0); bpy.context.view_layer.update()
        dn_ = (cam.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized(); hn_ = _hero_h(sc, cam, hero_)
        return math.degrees(math.acos(max(-1.0, min(1.0, dp_.dot(dn_))))) < 30 and max(hp_, hn_) / max(1e-6, min(hp_, hn_)) < 1.4
    pend = None; n_lying = 1 if lying and kind != 'insert' else 0
    # R240 REPAIR ROUND: a camera passes the gates but the subject does not READ (unread(): head cropped, face in profile or from
    # under the chin, eyes under the fringe, a wide on the back of a head) -> one more round from the FRONT of the face at eye
    # level, at the shot size and 1.3x wider; the least-flawed passing camera of all rounds is kept. A prop shot whose frame is
    # mostly a limb searches on up to its look-down round. One extra round only where the picture is flawed (build time).
    i_rep = -1
    if subj_chars and not lying and angle != 'top' and not FACE_OPT[0]:
        def repair_round():
            if pend is None or not unread(name, pend[1], eyes=False): return []   # eyes under a fringe: round 1 already looked up at them
            if len(subj_chars) > 1: return choose(gen_cands(tuple(range(0, 360, 30)), (1.0,)))
            rg = (-40, -20, 0, 20, 40)
            return choose(gen_cands(rg, (1.0,), angle=None) + gen_cands(rg, (1.0,), angle=None, hk=1.3))
        i_rep = n_lying + n_pitch; rounds.insert(i_rep, repair_round)
    elif rounds_extra and not subj_chars: i_rep = rounds.index(rounds_extra[0])
    hf_ = [f_[1].copy() for f_ in faces]
    for h_ in hf_: h_.z = 0
    can_face = all(a_.dot(b_) > -0.8 * a_.length * b_.length for a_ in hf_ for b_ in hf_)   # faces looking opposite ways: no lens sees both
    skip_to = 0
    for ri, rd in enumerate(rounds if best is None else []):
        if ri < skip_to: continue
        ranked = rd(); loose = None
        lim_ = 3 if soft and angle and n_lying < ri < n_lying + n_pitch - 1 else (4 if ri == i_rep and subj_chars else 6)   # the in-between pitch rounds: top 3 (build time)
        for r in sorted(ranked[:lim_], key=lambda r: r[6]):   # stable: rank order, jump-cut candidates last
            v_ = apply_lead(r[7]) if len(r) > 7 else apply(r)
            if len(r) <= 7 and not motion and not track and r[4] and min(x[0] for x in r[4].values()) >= 0.5                     and any(not k.endswith(' face') for k in (x.split(':', 1)[1] for x in vis_low(name, v_))):
                still_.add(id(r[1])); v2_ = apply(r)   # R240 (true 9:16 frame): the arc / dolly swung a near prop out of the narrow frame
                if len(vis_low(name, v2_)) < len(vis_low(name, v_)): v_ = v2_
                else: still_.discard(id(r[1]))
            if not r[6] and real_jump(): r = r[:6] + (True,) + r[7:]   # the gate's own rule on the FINAL camera (a lead track passed its
            tried.append((r, v_))                                       # first-key estimate and cut 11 deg / x1.05: blind6_white_bedroom s02)
            if os.environ.get('CAMDEBUG'): print('TRIED', name, 'round', ri, 'pos', [round(x / S, 1) for x in r[1]], 'L', round(r[3]), v_, 'low', vis_low(name, v_), 'unread', unread(name, v_), 'jump', r[6])
            if not vis_low(name, v_) and not r[6]:
                # HEADROOM preference: among the passing candidates of this round, the first whose focus head + hair stays inside
                # the frame on >= 90 % of the frames (critic R200: faces cut by the frame edge); else the first passing one
                if nice(v_) and (pend is None or flaw(v_) < flaw(pend[1]) - 0.02):
                    if {'back of a head', 'subject hidden'} & set(unread(name, v_)) and ri < i_rep and can_face: pend = (r, v_); skip_to = i_rep; break   # straight to the repair round
                    best, v = r, v_; break
                if loose is None or flaw(v_) < flaw(loose[1]) - 0.02: loose = (r, v_)
        if best is None and loose is not None and (pend is None or flaw(loose[1]) < flaw(pend[1]) - 0.02): pend = loose
        # a PITCHED shot whose candidates pass the gates but not the preferences (desk filling the frame from the ground, eyes
        # under the fringe from above) tries its milder rounds before settling for the first passing one
        if best is None and pend is not None and not (angle and ri + 1 < n_lying + n_pitch) and not (slab(pend[1]) and ri + 1 < len(rounds)) \
                and not (ri < i_rep and unread(name, pend[1], eyes=False)):
            best = pend[0]; v = pend[1] if tried[-1][0] is best else (apply_lead(best[7]) if len(best) > 7 else apply(best))
        if best is not None: break
    if best is None:
        r, v_ = max(tried, key=lambda t: (worth(t[1]), not t[0][6], t[0][0]))
        best = r; v = v_ if tried[-1][0] is r else (apply_lead(r[7]) if len(r) > 7 else apply(r))

        print('SHOT VALIDATE none passes', name, 'kept', {k: x for k, x in v.items()})
    elif len(tried) > 1:
        print('SHOT VALIDATE', name, 'candidate', len(tried), 'passes (rank 1 failed:', vis_low(name, tried[0][1]), ')')
    if len(best) > 7: print('SHOT LEAD', name, 'lead track', len(best[7]), 'keys')
    P, A = best[1], best[2]
    fvis = {k: x for k, x in v.items() if ' face' in k}
    m = sc.timeline_markers.new(name, frame=f0); m.camera = cam
    cam['on'] = on_key; LAST['cut'] = None
    cam['follow'] = bool(len(best) > 7 and motion == 'follow')
    if ots_first and len(chs_) == 2 and any(best[1] is o[0] for o in ots):   # the shot IS over the shoulder: remember its side of the line
        mid_ = (A_ + B_) / 2; ln_ = B_ - A_; ln_.z = 0; ln_.normalize(); sd_ = best[1] - mid_; sd_.z = 0; sd_ -= ln_ * sd_.dot(ln_)
        if sd_.length > 1e-6: AXIS.setdefault(pair_, sd_.normalized())
        cam['ots'] = True
    if prev_ is not None and targets:   # R240 near-duplicate check: what this cut changes for the shot's own subject
        foc_ = subj_chars[0].head_mesh if subj_chars else targets[0]
        sc.frame_set(f0 - 1); bpy.context.view_layer.update()
        dp_ = (prev_.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized(); hp_ = _hero_h(sc, prev_, foc_)
        sc.frame_set(f0); bpy.context.view_layer.update()
        dn_ = (cam.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized(); hn_ = _hero_h(sc, cam, foc_)
        LAST['cut'] = (same, math.degrees(math.acos(max(-1.0, min(1.0, dp_.dot(dn_))))), max(hp_, hn_) / max(1e-6, min(hp_, hn_)))
        print('CUT', name, 'same subject' if same else 'new subject', 'angle', round(LAST['cut'][1]), 'size x', round(LAST['cut'][2], 2), 'unread', unread(name, v))
    LAST['cam'] = cam; LAST['score'] = best[0]
    d_ = (best[2] - best[1]).normalized(); HIST.pop(name, None)
    HIST[name] = (math.degrees(math.atan2(d_.x, d_.y)), math.degrees(math.asin(max(-1.0, min(1.0, d_.z)))))
    print('SHOT', name, 'score', round(best[0], 2), 'lens', round(best[3]), 'el', round(-HIST[name][1]), 'pos studs', [round(x / S, 1) for x in P],
          'vis', {k: x for k, x in v.items() if ' face' not in k}, 'occ>10%', {k: round(a, 2) for k, a in best[5].items() if a > 0.1})
    print('FACES', name, fvis)
    print('READ', name, unread(name, v) or 'ok')
    return cam, v
