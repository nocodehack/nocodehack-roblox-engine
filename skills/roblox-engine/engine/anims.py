"""anims.py - Roblox's own R6 animations (assets/anims/<slug>/anim.json + meta.json) as an acting library.
  anims.convert(slug)  -> [(t_seconds, {chan: value}, {chan: (style, direction)})]  pure python (no bpy needed)
  anims.play(sc, ch, slug, f0, speed=1.0, loop_until=None, skip=())  keys it on a rig; returns the last frame used
Channels are poses.py's: R/L/legR/legL = (raise, out), head = (down, left, roll), body = (fwd, twist, lean), degrees.
Conversion: a Pose CFrame is the Motor6D Transform; the part's rotation in the parent frame is R = C0 * T * C0^-1 (standard R6
C0 rotations; C1 has the same rotation). Roblox (x right, y up, z back) -> rig-local (-x, z, y). Arms/legs hang along -Z, so
their direction gives (raise, out) with raise in [-90, 90] (arm overhead = out 180, like poses.LIB 'hands_up'); the rig has no
arm twist so roll about the limb axis is dropped. shortcut: Torso/root TRANSLATION and the arm twist are ignored, the torso
pivots at the hips (rig) not the torso centre (Roblox); upgrade if a clip needs bobbing hips."""
import json, math
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'assets' / 'anims'
# C0 rotations of the standard R6 Motor6Ds (rows), identical for C1
_RJ = ((-1, 0, 0), (0, 0, 1), (0, 1, 0))        # RootJoint and Neck
_RS = ((0, 0, 1), (0, 1, 0), (-1, 0, 0))        # Right Shoulder and Right Hip
_LS = ((0, 0, -1), (0, 1, 0), (1, 0, 0))        # Left Shoulder and Left Hip
JOINT = {'Right Arm': ('R', _RS), 'Left Arm': ('L', _LS), 'Right Leg': ('legR', _RS), 'Left Leg': ('legL', _LS),
         'Head': ('head', _RJ), 'Torso': ('body', _RJ)}
_P = ((-1, 0, 0), (0, 0, 1), (0, 1, 0))         # Roblox -> rig basis (proper rotation, det +1)
_I = ((1, 0, 0), (0, 1, 0), (0, 0, 1))


def _mm(a, b): return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))
def _t(a): return tuple(tuple(a[j][i] for j in range(3)) for i in range(3))


def _rotvec(v):
    th = math.sqrt(sum(c * c for c in v))
    if th < 1e-9: return _I
    x, y, z = (c / th for c in v); c, s = math.cos(th), math.sin(th); k = 1 - c
    return ((c + x * x * k, x * y * k - z * s, x * z * k + y * s), (y * x * k + z * s, c + y * y * k, y * z * k - x * s),
            (z * x * k - y * s, z * y * k + x * s, c + z * z * k))


def _rig_rot(T, c0):
    """Pose rotation vector -> rotation matrix of the part in the parent frame, in rig axes."""
    R = _mm(_mm(c0, _rotvec(T)), _t(c0))
    return _mm(_mm(_P, R), _t(_P))


def _limb(M, side, prev):
    """Limb direction -> (raise, out) CONTINUOUS with prev. The same direction has two decompositions, (r, o) and (180 - r, o + 180)
    (arm swung up through the front vs through the side); the one nearest prev is taken, angles unwrapped, so an arm raised overhead
    never flips mid-clip."""
    d = (-M[0][2], -M[1][2], -M[2][2])      # M @ (0, 0, -1)
    r = math.degrees(math.asin(max(-1.0, min(1.0, -d[1]))))
    if math.hypot(d[0], d[2]) < 1e-3: o = prev[1] if prev else 0.0   # limb straight forward/back: out undefined, hold it
    else:
        beta = math.degrees(math.atan2(-d[0], -d[2])); o = beta if side == 'R' else -beta
    cands = [(r, o), (180 - r, o + 180)]
    if prev: cands = [(_unwrap(a, prev[0]), _unwrap(b, prev[1])) for a, b in cands]
    return min(cands, key=lambda c: (c[0] - prev[0]) ** 2 + (c[1] - prev[1]) ** 2) if prev else cands[0]


def _euler_xyz(M):                                       # R = Rz Ry Rx (Blender XYZ)
    return (math.degrees(math.atan2(M[2][1], M[2][2])), math.degrees(math.asin(max(-1.0, min(1.0, -M[2][0])))),
            math.degrees(math.atan2(M[1][0], M[0][0])))


def _unwrap(v, prev):
    return v + 360 * round((prev - v) / 360)


def meta(slug): return json.loads((ROOT / slug / 'meta.json').read_text())
def slugs(): return sorted(p.name for p in ROOT.iterdir() if (p / 'anim.json').exists())


def convert(slug):
    """-> list of (t, {chan: value}, {chan: (EasingStyle, EasingDirection)}) with angles unwrapped over time."""
    kfs = json.loads((ROOT / slug / 'anim.json').read_text())['kf']
    out, last = [], {}
    for kf in kfs:
        vals, ease = {}, {}
        for name, (chan, c0) in JOINT.items():
            p = kf['p'].get(name) if isinstance(kf['p'], dict) else None
            if p is None: continue
            M = _rig_rot(p['r'], c0)
            if chan in ('R', 'L', 'legR', 'legL'):
                v = _limb(M, chan[-1], last.get(chan))
            else:
                x, y, z = _euler_xyz(M); v = (x, z, y)            # head (down, left, roll) / body (fwd, twist, lean)
            last[chan] = v; vals[chan] = v; ease[chan] = (p.get('e', 'Linear'), p.get('d', 'In'))
        out.append((kf['t'], vals, ease))
    return out


_INTERP = {'Linear': 'LINEAR', 'Constant': 'CONSTANT', 'Cubic': 'CUBIC', 'Elastic': 'ELASTIC', 'Bounce': 'BOUNCE'}
_EASE = {'In': 'EASE_IN', 'Out': 'EASE_OUT', 'InOut': 'EASE_IN_OUT'}


def _fcurves(o):
    a = o.animation_data.action
    return a.fcurves if hasattr(a, 'fcurves') else [fc for l in a.layers for s in l.strips for cb in s.channelbags for fc in cb.fcurves]


def _sole(leg):
    """Contact feature of a leg box, same rule as locomotion.foot_slide: the sole EDGE when its two lowest corners are level
    (<= 3 mm), else the lowest CORNER. -> (feature, world point)."""
    from mathutils import Vector
    cs = [leg.matrix_world @ Vector(c) for c in leg.bound_box]; o = sorted(range(8), key=lambda q: cs[q].z)
    ft = (min(o[0], o[1]), max(o[0], o[1])) if cs[o[1]].z - cs[o[0]].z <= 0.003 else (o[0],)
    return ft, sum((cs[q] for q in ft), Vector()) / len(ft)


def ground(sc, ch, f0, f1, tol=0.012):
    """Planted-foot retarget for rigid R6 legs. Roblox clips swing the legs about a FIXED root, so soles slide and box corners
    dip under the floor. Per frame: lift the root so the lowest body part sits at the floor height the feet had at f0, then
    move it in x/y so the sole feature in contact stays exactly where it landed (re-anchored when the contact changes).
    The character may shuffle a little, like a real dancer. A swing foot skimming the floor (within tol) while it moves is a
    drag for the gate: it is lifted a few degrees. Keys root location and leg rotations on every frame of [f0, f1]."""
    import bpy
    root = ch.root; parts = [ch.torso, ch.head_mesh] + list(ch.legs) + list(ch.arms); pivs = [l.parent for l in ch.legs]
    low = lambda objs: min((o.matrix_world @ __import__('mathutils').Vector(c)).z for o in objs for c in o.bound_box)
    frames = range(int(f0), int(math.ceil(f1)) + 1)
    for f in frames:   # bake the legs to one key per frame: a lift keyed at f must not bend already-grounded frames
        sc.frame_set(f)
        for pv in pivs: pv.keyframe_insert('rotation_euler', frame=f)
    sc.frame_set(int(f0)); bpy.context.view_layer.update()
    floor = low(ch.legs); base = root.location.copy(); ox = oy = 0.0; anchor = None   # (leg index, feature, world point)
    land = [None, None]   # swing foot in the contact band: (feature, where it touched)
    prev = [None, None]   # last frame's (feature, point) of each foot in contact
    for f in frames:
        sc.frame_set(f); root.location = (base.x + ox, base.y + oy, base.z); bpy.context.view_layer.update()
        root.location.z = base.z + max(0.0, floor - low(parts)); bpy.context.view_layer.update()
        sole = [_sole(l) for l in ch.legs]; on = [k for k, (_, p) in enumerate(sole) if p.z - floor <= tol]
        if anchor and len(on) == 2 and sole[anchor[0]][1].z - sole[1 - anchor[0]][1].z > 0.001:
            o_ = 1 - anchor[0]   # both feet down: the weight is on the LOWER foot (only the other one can be lifted)
            land[anchor[0]] = (anchor[1], anchor[2].copy())   # the old anchor's creep counts from where it was PLANTED (blind5 Sam 3 cm)
            anchor = (o_, sole[o_][0], prev[o_][1].copy() if prev[o_] and prev[o_][0] == sole[o_][0] else sole[o_][1].copy())
        if anchor and anchor[0] in on and sole[anchor[0]][0] == anchor[1]:
            d = anchor[2] - sole[anchor[0]][1]; ox += d.x; oy += d.y
            root.location.x += d.x; root.location.y += d.y
        else:
            anchor = (on[0], sole[on[0]][0], sole[on[0]][1].copy()) if on else None
        bpy.context.view_layer.update()
        for k in on:
            if anchor and k == anchor[0]: continue
            ft, p = _sole(ch.legs[k])
            if land[k] is None or land[k][0] != ft: land[k] = (ft, p.copy()); continue
            if (p - land[k][1]).xy.length < 0.004: continue          # resting second foot: fine
            pv = pivs[k]; r0 = tuple(pv.rotation_euler)
            for d, ax, sg in sorted((d, ax, sg) for d in (2, 4, 6, 8, 10) for ax in (0, 1) for sg in (1, -1)):
                r = list(r0); r[ax] += sg * math.radians(d); pv.rotation_euler = r; bpy.context.view_layer.update()
                if _sole(ch.legs[k])[1].z - floor > tol + 0.002:
                    pv.keyframe_insert('rotation_euler', frame=f); land[k] = None; break
            else:   # no small lift clears it (a near-vertical box leg dips a corner when it rotates): hop the body <= 2.5 cm so
                pv.rotation_euler = r0; bpy.context.view_layer.update()   # neither foot drags for these frames (pose blends)
                hop = tol + 0.002 - min(_sole(l)[1].z for l in ch.legs) + floor
                if hop <= 0.025:
                    root.location.z += hop; bpy.context.view_layer.update(); anchor = None; land = [None, None]; break
        for k in range(2):
            if k not in on: land[k] = None
        bpy.context.view_layer.update()
        prev = [(lambda s_: s_ if s_[1].z - floor <= tol else None)(_sole(l)) for l in ch.legs]
        root.keyframe_insert('location', frame=f)


def _clear_arm(sc, ch, side, piv, pts, parts):
    """Roblox clips let arms pass through the head/hair/others. Per key: if the arm cuts any (mesh, allowance) in `parts` on the
    frames around the key, try 'out' offsets then a lower raise and keep the clearest. Edits pts in place; returns keys fixed."""
    import bpy, interact as ia, space, poses
    arm = next(o for o in piv.children if o.type == 'MESH'); lo, hi = space.local_bounds(arm); frs = [p[0] for p in pts]
    def over(a, b):
        w = 0.0
        for g in range(int(a), int(math.ceil(b)) + 1):
            sc.frame_set(g); bpy.context.view_layer.update(); M = arm.matrix_world
            w += sum(max(0.0, ia._pts_depth(ia.world_pts(o), M, lo, hi) - lim) for o, lim in parts)
        return w
    fixed = 0
    for j, (f, (r, ou), e) in enumerate(pts):
        a = (frs[j - 1] + f) / 2 if j else f; b = (f + frs[j + 1]) / 2 if j + 1 < len(frs) else f
        best = (over(a, b), (r, ou))
        if best[0] <= 1e-4: continue
        for v in [(r, ou + d) for d in (15, -15, 30, -30, 45, -45, 60, -60)] + [(r * s, ou) for s in (.85, .7, .5)]:
            piv.rotation_euler = poses.euler(ch, side, v); piv.keyframe_insert('rotation_euler', frame=f)
            w = over(a, b)
            if w < best[0]: best = (w, v)
            if w <= 1e-4: break
        piv.rotation_euler = poses.euler(ch, side, best[1]); piv.keyframe_insert('rotation_euler', frame=f)
        pts[j] = (f, best[1], e); fixed += best[1] != (r, ou)
    return fixed


def play(sc, ch, slug, f0, speed=1.0, loop_until=None, skip=(), blend=3, clear=None):
    """Key animation `slug` on rig `ch`: its t=0 lands at frame f0+blend (the pose before f0 is kept at f0 and blends in over
    `blend` frames); one pass takes duration/speed seconds. loop_until = last frame: the clip repeats until it (the last frame
    is the last key at or before it). Roblox easing -> Blender interpolation (the style of the pose you ARRIVE at drives the
    segment into it). `skip` = channels not to touch, e.g. ('legR', 'legL') while walking. clear = [(mesh, allowance m)] the
    arms must not cut (keys searched clear after keying). Legs keyed -> ground() plants the feet. Returns the last frame keyed."""
    import poses
    fps = sc.render.fps / sc.render.fps_base
    data = convert(slug); dur = data[-1][0]
    objs = poses._objs(ch); skip = set(skip)
    legs_amp = max([abs(x) for _, v, _ in data for c in ('legR', 'legL') if c in v for x in v[c] if abs(x) < 170] or [0])
    if legs_amp < 8: skip |= {'legR', 'legL'}   # a weight shift (wave/point <= 6 deg): rigid legs can only slide it
    chans = [c for c in objs if c not in skip and any(c in v for _, v, _ in data)]
    per = {c: [] for c in chans}      # chan -> [(frame, value, (style, direction))]
    base = f0 + blend; k = 0
    while True:
        cut = False
        for i, (t, vals, ease) in enumerate(data):
            if k and i == 0: continue
            f = base + (k * dur + t) / speed * fps
            if loop_until is not None and f > loop_until + 1e-6: cut = True; break
            for c in chans:
                if c in vals: per[c].append((f, vals[c], ease[c]))
        k += 1
        if cut or loop_until is None: break
    end = f0
    for c in chans:
        pts = per[c]
        if not pts: continue
        o = objs[c]; sc.frame_set(int(f0))
        o.rotation_euler = tuple(o.rotation_euler); o.keyframe_insert('rotation_euler', frame=f0)
        for f, v, _ in pts:
            o.rotation_euler = poses.euler(ch, c, v); o.keyframe_insert('rotation_euler', frame=f)
        end = max(end, pts[-1][0])
    for c in chans:   # arms after ALL channels are keyed (the head/body pose decides what the arm cuts)
        if clear and c in ('R', 'L') and per[c]: _clear_arm(sc, ch, c, objs[c], per[c], clear)
    for c in chans:
        pts = per[c]
        if not pts: continue
        o = objs[c]
        arrive = {round(pts[j - 1][0], 3): pts[j][2] for j in range(1, len(pts))}   # segment that STARTS at pts[j-1]
        for fc in _fcurves(o):
            if fc.data_path != 'rotation_euler': continue
            for kp in fc.keyframe_points:
                st, di = arrive.get(round(kp.co.x, 3), ('Linear', 'In'))
                kp.interpolation = _INTERP.get(st, 'LINEAR')
                if kp.interpolation not in ('LINEAR', 'CONSTANT'): kp.easing = _EASE.get(di, 'EASE_IN_OUT')
    if {'legR', 'legL'} & set(chans): ground(sc, ch, f0, end)
    return end
