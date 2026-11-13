"""interact.py v2: reusable character/object interaction + shot checks for scripted Blender shorts (R6 rigid limbs).
Units: metres in world space; STUD = 0.5 m. A limb = an empty (shoulder/hip pivot) with one mesh child hanging along -Z,
offset sideways by side*0.5 stud, 2 studs long, 1x1 stud thick (Roblox R6). All functions key animation directly.

CONTACT
  aim_limb(sc, pivot, side, frame, target)            solve shoulder X/Y/Z so a point on the rigid limb hits target
  key_aim(..., surface_from=centre)                    contact on a SURFACE: limb centre-line stands off by half the limb
                                                       thickness along the surface normal, so the limb touches, never sinks
  follow_prop(sc, pivot, side, prop, frames, local_offset)  prop-local anchor (follows rotation), anchor fixed on the limb
  point_limb(sc, pivot, side, frame, target)          aim the limb axis at a far target (minimum angle)
PROPS
  drop_object(obj, h0, velocity, support_rect, end)   slide, fall (g), tip, land on floor/earlier-landed objects, settle
  reset()                                              clear per-build state (call once per build)
VALIDATION / CLEANUP
  depenetrate(sc, pivot, props, frames, box_props)    after keying: smallest shoulder change clearing any prop;
                                                       registered contact frames keep their contact residual
  penetration_report(...)                              OBB SAT for box pairs + vertex containment for other meshes
CAMERA
  shot_visibility(sc, cam, frames, targets)            fraction of each target inside frame and unoccluded
  choose_camera(sc, candidates, frames, targets)       pick the candidate camera with the best worst-case visibility
"""
import math, json
import bpy
import numpy as np
from mathutils import Vector, Matrix, Euler, Quaternion

S = 0.5
D = math.radians
G = 9.81
LIMB_HALF = 0.5 * S          # half thickness of an R6 limb (m)
_LANDED = []                 # (land_frame, xmin, xmax, ymin, ymax, top_z)
CONTACTS = {}                # pivot name -> {frame: (target_world, along, side)}
REACH_LIMITS = {'rx': (-200, 40), 'ry': (-130, 130), 'rz': (-90, 90)}


def reset():
    _LANDED.clear(); CONTACTS.clear(); globals().get('LAST_POSE', {}).clear(); globals().get('_BB', {}).clear(); globals().get('_LV', {}).clear()   # geometry caches are per scene


def _key(o, path, f, v):
    setattr(o, path, v); o.keyframe_insert(data_path=path, frame=f)


def ensure_origin(obj):
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True); bpy.context.view_layer.objects.active = obj
    bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
    return obj


# ================================================================ limbs
def _pivot_frame(sc, pivot, frame):
    sc.frame_set(frame); bpy.context.view_layer.update()
    PW = pivot.parent.matrix_world.copy() if pivot.parent else Matrix.Identity(4)
    return PW, Matrix.Translation(pivot.location)


def solve_tip(parent_world, pivot_local, side, target_world, previous=None, limits=None, h=None):
    """Rigid-arm reach in metres; choose a limit-respecting XYZ pose along the free twist axis."""
    limits = REACH_LIMITS if limits is None else limits
    bounds = [limits[k] for k in ('rx', 'ry', 'rz')]
    assert all(math.isfinite(lo) and math.isfinite(hi) and lo <= hi for lo, hi in bounds), 'invalid reach limits'
    h = Vector((side * 0.5 * S, 0, -TIP * S)) if h is None else Vector(h)
    assert h.length > 0, 'hand vector must be nonzero'
    world = parent_world @ Matrix.Translation(pivot_local)
    target = Vector(target_world)
    assert all(math.isfinite(v) for v in target), 'target must be finite'
    prev = tuple(previous) if previous is not None else None
    if prev is not None and len(prev) == 2: prev += (0.0,)
    local = world.inverted() @ target
    direction = local.normalized() if local.length > 1e-10 else h.normalized()
    base = h.rotation_difference(direction)

    def delta(a, b): return abs((a - b + 180) % 360 - 180)

    def candidate(twist):
        q = Quaternion(direction, twist) @ base
        x, y, z = (math.degrees(a) for a in q.to_euler('XYZ'))
        choices = []
        # XYZ has two Euler branches; either may be the one inside the shoulder limits.
        for raw in ((x, y, z), (x + 180, 180 - y, z + 180)):
            angles = []
            for a, (lo, hi) in zip(raw, bounds):
                a += 360 * round(((lo + hi) / 2 - a) / 360)
                angles.append(a)
            clipped = tuple(max(lo, min(hi, a)) for a, (lo, hi) in zip(angles, bounds))
            violation = sum(abs(a - b) for a, b in zip(angles, clipped))
            score = sum(delta(a, b) for a, b in zip(clipped, prev)) if prev is not None else \
                abs(clipped[2]) + 0.001 * sum(delta(a, 0) for a in clipped[:2])
            choices.append(((violation, score), clipped))
        return min(choices)

    step = math.tau / 72
    twists = [i * step for i in range(72)]
    if prev is not None:
        relative = Euler(tuple(D(a) for a in prev), 'XYZ').to_quaternion() @ base.inverted()
        twists.append(2 * math.atan2(Vector(relative[1:]).dot(direction), relative.w))
    # Include exact zero-roll poses so old X/Y-only callers retain their natural solution.
    first = base @ Vector((1, 0, 0))
    c = direction.y * direction.dot(first)
    a, b = first.y - c, direction.cross(first).y
    r = math.hypot(a, b)
    if r > 1e-10 and abs(c) <= r:
        phase, arc = math.atan2(b, a), math.acos(max(-1, min(1, -c / r)))
        twists.extend((phase - arc, phase + arc))
    best, twist = min((candidate(t), t) for t in twists)
    for _ in range(17):
        best, twist = min((best, twist), (candidate(twist - step), twist - step),
                          (candidate(twist + step), twist + step))
        step *= 0.5
    angles = best[1]

    def residual(pose):
        return (world @ (Euler(tuple(D(a) for a in pose), 'XYZ').to_matrix() @ h) - target).length

    if best[0][0] > 1e-5:
        # No sampled twist fits: minimise the actual miss while staying inside every limit.
        error = residual(angles)
        for step in (20, 10, 5, 2, 1, 0.5, 0.1, 0.02):
            for _ in range(12):
                old = angles
                for i, (lo, hi) in enumerate(bounds):
                    for sign in (-1, 1):
                        trial = list(angles); trial[i] = max(lo, min(hi, trial[i] + sign * step))
                        e = residual(trial)
                        if e < error: angles, error = tuple(trial), e
                if angles == old: break
    error = residual(angles)
    return (*angles, error, error <= 0.01)


def _aim(sc, pivot, side, frame, target, rx_rng, ry_rng, h=None, continuity=True):
    PW, T = _pivot_frame(sc, pivot, frame)
    previous = LAST_POSE.get(pivot.name, tuple(math.degrees(a) for a in pivot.rotation_euler)) if continuity else None
    limits = dict(REACH_LIMITS, rx=rx_rng, ry=ry_rng)
    return solve_tip(PW, T.translation, side, target, previous, limits, h)[:4]


def aim_limb(sc, pivot, side, frame, target_world, offset_studs=0.5, rx_rng=(-150, 20), ry_rng=(-70, 70), along=None, along_clamp=None, with_rz=False):
    """Returns (rx_deg, ry_deg, error_m, along_studs). The contact point slides along the rigid limb (0.6..1.9 studs)
    to match the target distance unless `along` is fixed (R6 limbs cannot bend)."""
    PW, T = _pivot_frame(sc, pivot, frame)
    tgt = Vector(target_world)
    d = (tgt - (PW @ T).translation).length / S
    a = along if along is not None else max(0.6, min(1.9, math.sqrt(max(d * d - offset_studs ** 2, 0.0))))
    if along_clamp: a = max(along_clamp[0], min(along_clamp[1], a))
    h = Vector((side * offset_studs * S, 0, -a * S))
    rx, ry, rz, e = _aim(sc, pivot, side, frame, tgt, rx_rng, ry_rng, h)
    return (rx, ry, rz, e, a) if with_rz else (rx, ry, e, a)


def _standoff(target, surface_from):
    n = Vector(target) - Vector(surface_from); n.z = 0
    return Vector(target) + (n.normalized() * LIMB_HALF if n.length > 1e-6 else Vector())


def key_aim(sc, pivot, side, frame, target_world, tol=0.03, label='', surface_from=None, along=None, along_clamp=None, **rng):
    """Key a contact. With surface_from (the prop centre), target_world is a point ON the prop surface and the limb
    centre-line is placed half a limb-thickness outside it, so the limb face touches the surface."""
    t = _standoff(target_world, surface_from) if surface_from is not None else Vector(target_world)
    rx, ry, rz, e, a = aim_limb(sc, pivot, side, frame, t, along=along, along_clamp=along_clamp, with_rz=True, **rng)
    print('AIM', label or pivot.name, frame, round(rx, 1), round(ry, 1), round(rz, 1), round(e, 3))
    assert e < tol, f'aim {label or pivot.name} f{frame}: error {e:.3f} m > {tol} (out of reach: move body/timing)'
    _key(pivot, 'rotation_euler', frame, (D(rx), D(ry), D(rz))); LAST_POSE[pivot.name] = (rx, ry, rz)
    CONTACTS.setdefault(pivot.name, {})[frame] = (t.copy(), a, side)
    return rx, ry, e, a


def point_limb(sc, pivot, side, frame, target_world, rx_rng=(-200, 20), ry_rng=(-90, 90)):
    """Aim the limb axis at a far target by minimum ANGLE (pointing), then key it."""
    PW, T = _pivot_frame(sc, pivot, frame)
    base = (PW @ T).translation; want = (Vector(target_world) - base).normalized()
    rx, ry, rz, _ = _aim(sc, pivot, side, frame, base + want * math.hypot(0.5, TIP) * S, rx_rng, ry_rng)
    _key(pivot, 'rotation_euler', frame, (D(rx), D(ry), D(rz))); LAST_POSE[pivot.name] = (rx, ry, rz)
    return rx, ry


def follow_prop(sc, pivot, side, prop, frames, local_offset_studs, tol=0.03, label='', surface=True, slide_per_frame=0.05):
    """Hold contact with a moving/rotating prop: the anchor is PROP-LOCAL (follows rotation) and the contact point
    is fixed on the limb after the first frame (no sliding along the arm)."""
    worst = 0.0; along = None; fl = list(frames); step = (fl[1] - fl[0]) if len(fl) > 1 else 1
    off = Vector(tuple(c * S for c in local_offset_studs))
    for f in fl:
        sc.frame_set(f); bpy.context.view_layer.update()
        target = prop.matrix_world @ off
        _, _, e, a = key_aim(sc, pivot, side, f, target, tol, label,
                             surface_from=prop.matrix_world.translation if surface else None,
                             along_clamp=None if along is None else (along - slide_per_frame * step, along + slide_per_frame * step))
        along = a
        worst = max(worst, e)
    return worst


# ================================================================ props
def _corners(obj):
    return [Vector(c) for c in obj.bound_box]


def drop_object(obj, h0, velocity, support_rect, end_frame, floor_z=0.0, fps=24, tip_max=1.4, tip_rate=4.0,
                settle=4, friction_s=0.15, yaw_kick_deg=15.0, base_yaw_deg=0.0, label=''):
    """Slide from h0 at velocity (m/s, xy) on its support; once the centre leaves support_rect=(xmin,xmax,ymin,ymax)
    it falls with g, tips about the axis perpendicular to motion, lands (exact lowest corner) on the floor or on objects
    that ALREADY landed by that frame, decelerates monotonically (friction) and settles flat over `settle` frames."""
    ensure_origin(obj)
    start = obj.location.copy(); sc3 = obj.matrix_world.to_3x3().to_scale()
    v = Vector((velocity[0], velocity[1], 0))
    axis = Vector((-v.y, v.x, 0)).normalized() if v.length > 1e-6 else Vector((0, 1, 0))
    def rot(angle, yaw): return (Quaternion(axis, angle) @ Quaternion((0, 0, 1), D(yaw))).to_matrix()
    def pts(R): return [R @ Vector((c.x * sc3.x, c.y * sc3.y, c.z * sc3.z)) for c in _corners(obj)]
    y0 = Euler((0, 0, D(base_yaw_deg)))
    _key(obj, 'location', 0, start); _key(obj, 'location', h0, start)
    _key(obj, 'rotation_euler', 0, y0); _key(obj, 'rotation_euler', h0, y0)
    xmin, xmax, ymin, ymax = support_rect
    t_off = None; landed = None; pos = start.copy(); angle = 0.0
    for f in range(h0 + 1, end_frame + 1):
        t = (f - h0) / fps
        yaw = base_yaw_deg + yaw_kick_deg * min(1.0, t * 8)
        if landed is None:
            xy = start + v * t
            if t_off is None and xmin <= xy.x <= xmax and ymin <= xy.y <= ymax:
                pos = Vector((xy.x, xy.y, start.z)); angle = 0.0
            else:
                if t_off is None: t_off = t
                tf = t - t_off
                pos = Vector((xy.x, xy.y, start.z - 0.5 * G * tf * tf)); angle = min(tip_max, tip_rate * tf)
                R = rot(angle, yaw)
                land_z = max([floor_z] + [top for (lf, a0, a1, b0, b1, top) in _LANDED
                                          if lf <= f and a0 <= pos.x <= a1 and b0 <= pos.y <= b1])
                if pos.z + min(p.z for p in pts(R)) < land_z:
                    landed = (f, angle, land_z, pos.copy())
        if landed is not None:
            lf, a0, land_z, p_land = landed
            k = min(1.0, (f - lf) / settle)
            angle = a0 * (1 - k)
            u = min((f - lf) / fps, friction_s)
            slide = v * (u - u * u / (2 * friction_s))          # monotonic deceleration to rest
            R = rot(angle, yaw)
            pos = Vector((p_land.x + slide.x, p_land.y + slide.y, land_z - min(p.z for p in pts(R)) + 0.001))
        _key(obj, 'location', f, pos)
        _key(obj, 'rotation_euler', f, rot(angle, yaw).to_euler())
    if landed is not None:
        P = [pos + p for p in pts(rot(0, yaw))]
        _LANDED.append((landed[0] + settle, min(p.x for p in P), max(p.x for p in P), min(p.y for p in P),
                        max(p.y for p in P), max(p.z for p in P)))
    print('DROP', label or obj.name, 'landed f%s' % landed[0] if landed else 'NOT LANDED')
    return landed


# ================================================================ geometry tests (numpy)
def limb_mesh(pivot):
    return next(c for c in pivot.children if c.type == 'MESH')


_LV = {}   # mesh data -> local vertices (n, 4) homogeneous; meshes here are rigid (objects move, vertices do not)


def world_pts(o):
    """World-space vertices of a rigid mesh object as (n, 3) numpy: cached local coords x matrix_world (one matmul).
    Replaces per-vertex Python loops that dominated build time (cleanup 945 of 1035 s with library hair, R148)."""
    me = o.data; k = (me.name, len(me.vertices))
    L = _LV.get(k)
    if L is None:
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co)
        L = np.hstack([co.reshape(-1, 3), np.ones((len(me.vertices), 1))]); _LV[k] = L
    return (L @ np.array(o.matrix_world).T)[:, :3]


_BB = {}   # mesh data -> local bound box corners (8, 3): rigid meshes; np.array(o.bound_box) per call was 1.3 M conversions = 25 s of a 200 s build


def _wbox(o):
    """World AABB (lo, hi) of an object's bound box corners."""
    k = (o.data.name, len(o.data.vertices)) if o.type == 'MESH' else None
    bb = _BB.get(k) if k else None
    if bb is None:
        bb = np.array(o.bound_box)
        if k: _BB[k] = bb
    M = np.array(o.matrix_world); c = bb @ M[:3, :3].T + M[:3, 3]
    return c.min(0), c.max(0)


def _static_boxes(objs):
    """{object: world AABB} for the objects that cannot move (no action on them or any parent: set pieces). Their box is
    computed once per call instead of once per frame (664 k _wbox calls in one 200 s build)."""
    out = {}
    for o in objs:
        q = o
        while q is not None and not (q.animation_data and q.animation_data.action): q = q.parent
        if q is None: out[o] = _wbox(o)
    return out


def _bounds_np(obj):
    co = np.array([v.co[:] for v in obj.data.vertices]); return co.min(0), co.max(0)


def _obb(M, lo, hi):
    """centre, unit axes (3x3, columns), half extents from a 4x4 world matrix and local AABB."""
    M = np.asarray(M); c_local = (lo + hi) / 2; half = (hi - lo) / 2
    A = M[:3, :3]; scale = np.linalg.norm(A, axis=0); axes = A / scale
    return M[:3, :3] @ c_local + M[:3, 3], axes, half * scale


def obb_depth(a, b):
    """Separating-axis test for two OBBs; returns penetration depth (m) along the axis of least overlap, 0 if apart."""
    ca, Aa, ha = a; cb, Ab, hb = b; T = cb - ca
    axes = np.concatenate((Aa.T, Ab.T))
    overlap = np.abs(axes @ Aa) @ ha + np.abs(axes @ Ab) @ hb - np.abs(axes @ T)
    if np.any(overlap <= 0): return 0.0
    depth = overlap.min()
    cross = np.cross(Aa.T[:, None, :], Ab.T[None, :, :]).reshape(-1, 3)
    norms = np.linalg.norm(cross, axis=1); valid = norms > 1e-6
    if valid.any():
        axes = cross[valid] / norms[valid, None]
        overlap = np.abs(axes @ Aa) @ ha + np.abs(axes @ Ab) @ hb - np.abs(axes @ T)
        if np.any(overlap <= 0): return 0.0
        depth = min(depth, overlap.min())
    return float(depth)


def _pts_depth(pts, M, lo, hi):
    M = np.asarray(M)
    if len(pts) > 64:
        centre = M[:3, :3] @ ((lo + hi) / 2) + M[:3, 3]
        half = np.abs(M[:3, :3]) @ ((hi - lo) / 2)
        lower, upper = centre - half - 1e-9, centre + half + 1e-9
        keep = ((pts[:, 0] >= lower[0]) & (pts[:, 0] <= upper[0]) &
                (pts[:, 1] >= lower[1]) & (pts[:, 1] <= upper[1]) &
                (pts[:, 2] >= lower[2]) & (pts[:, 2] <= upper[2]))
        pts = pts[keep]
        if not len(pts): return 0.0
    inv = np.linalg.inv(M); p = pts @ inv[:3, :3].T + inv[:3, 3]
    s = np.linalg.norm(np.asarray(M)[:3, :3], axis=0)
    inside = np.all((p > lo) & (p < hi), axis=1)
    if not inside.any(): return 0.0
    q = p[inside]; return float(np.max(np.min(np.concatenate([(q - lo) * s, (hi - q) * s], axis=1), axis=1)))


def _limb_depth(Mlimb, lo, hi, mesh_pts, box_obbs):
    d = _pts_depth(mesh_pts, Mlimb, lo, hi) if len(mesh_pts) else 0.0
    if box_obbs:
        la = _obb(Mlimb, lo, hi)
        for bo in box_obbs: d = max(d, obb_depth(la, bo))
    return d


# ================================================================ cleanup + validation
def depenetrate(sc, pivot, props, frames, box_props=(), tol=0.03, ctol=0.04, max_pass=4, search_deg=60, label='', allowances=None):
    """Wherever the limb sinks deeper than tol into a prop, key the smallest shoulder change that clears it.
    Frames with a registered contact (key_aim/follow_prop) must also keep the contact within ctol.
    allowances maps mesh names to the existing gate's permitted depths (e.g. own torso/hair)."""
    limb = limb_mesh(pivot); lo, hi = _bounds_np(limb); child = np.array(limb.matrix_local)
    contacts = CONTACTS.get(pivot.name, {}); fixed = []; failed = []; allowances = allowances or {}
    rings = [sorted([(dx, dy) for dx in range(-rad, rad + 1, 2) for dy in range(-rad, rad + 1, 2) if max(abs(dx), abs(dy)) == rad],
                    key=lambda d: d[0] ** 2 + d[1] ** 2) for rad in range(2, search_deg + 1, 2)]
    static = _static_boxes(props)
    for _ in range(max_pass):
        changed = 0
        for f in frames:
            sc.frame_set(f); bpy.context.view_layer.update()
            PW = np.array(pivot.parent.matrix_world); T = np.array(Matrix.Translation(pivot.location))
            sp = np.array(pivot.matrix_world.translation[:]); R_ = 1.4   # arm + hand + search swing: nothing farther can be touched
            near_ = [pr for pr in props for lo_, hi_ in [static.get(pr) or _wbox(pr)] if np.all(sp > lo_ - R_) and np.all(sp < hi_ + R_)]
            strict = [world_pts(pr) for pr in near_ if pr.name not in allowances]
            pts = np.concatenate(strict) if strict else np.zeros((0, 3))
            allowed = [(world_pts(pr), allowances[pr.name]) for pr in near_ if pr.name in allowances]
            boxes = [_obb(np.array(b.matrix_world), *_bounds_np(b)) for b in box_props]
            rz = pivot.rotation_euler.z
            def M_of(rx, ry, rz_=None): return PW @ T @ np.array(Euler((rx, ry, rz if rz_ is None else rz_)).to_matrix().to_4x4()) @ child
            def clear(M):
                if _limb_depth(M, lo, hi, pts, boxes) > tol: return False
                return all(_pts_depth(P, M, lo, hi) <= limit for P, limit in allowed)
            r0x, r0y = pivot.rotation_euler.x, pivot.rotation_euler.y
            if clear(M_of(r0x, r0y)): continue
            cpt = contacts.get(f)
            def contact_ok(rx, ry, rz_):
                if not cpt: return True
                tgt, a, side = cpt
                h = np.array([side * 0.5 * S, 0, -a * S, 1.0])
                return np.linalg.norm((PW @ T @ np.array(Euler((rx, ry, rz_)).to_matrix().to_4x4()) @ h)[:3] - np.array(tgt[:])) <= ctol
            best = None
            if cpt:
                # Twist about the reached hand vector: all three Euler axes may change while contact stays exact.
                base = pivot.rotation_euler.to_quaternion()
                axis = (base @ Vector((cpt[2] * .5 * S, 0, -cpt[1] * S))).normalized()
                for degrees in sorted(range(-180, 181, 2), key=abs):
                    angles = (Quaternion(axis, D(degrees)) @ base).to_euler('XYZ', pivot.rotation_euler)
                    if contact_ok(*angles) and clear(M_of(*angles)):
                        best = tuple(angles); break
            for rad, ring in zip(range(2, search_deg + 1, 2), rings):
                if best: break
                for dx, dy, dz in [(dx, dy, 0) for dx, dy in ring] + [(0, 0, -rad), (0, 0, rad)]:
                    rx, ry, rz_ = r0x + D(dx), r0y + D(dy), rz + D(dz)
                    if contact_ok(rx, ry, rz_) and clear(M_of(rx, ry, rz_)):
                        best = (rx, ry, rz_); break
                if best: break
            if best:
                _key(pivot, 'rotation_euler', f, best); fixed.append(f); changed += 1
            else:
                failed.append(f)
        print('DEPEN', label or pivot.name, 'pass fixed', changed)
        if not changed: break
    if failed: print('DEPEN could not clear', label or pivot.name, sorted(set(failed))[:20])
    return sorted(set(fixed))


def penetration_report(sc, limbs, props, frames, tol=0.03, path=None, box_props=()):
    """Per frame: OBB SAT depth for limb vs box props; vertex containment (prop points in limb box) for other meshes.
    Also the contact residual for registered contacts after all cleanup."""
    rows = []; worst = {}; static = _static_boxes([pr for pr in props if pr.type == 'MESH'])
    for f in frames:
        sc.frame_set(f); bpy.context.view_layer.update()
        for lb in limbs:
            M = np.array(lb.matrix_world); lo, hi = _bounds_np(lb); la = _obb(M, lo, hi)
            llo, lhi = _wbox(lb)
            for pr in props:
                if pr.type != 'MESH': continue
                if pr.name in box_props: d = obb_depth(la, _obb(np.array(pr.matrix_world), *_bounds_np(pr)))
                else:
                    plo, phi = static.get(pr) or _wbox(pr)
                    if np.any(plo > lhi + tol) or np.any(phi < llo - tol): continue   # boxes apart: no vertex can be inside
                    d = _pts_depth(world_pts(pr), M, lo, hi)
                if d > tol:
                    r = {'f': f, 'limb': lb.name, 'prop': pr.name, 'depth_m': d}; rows.append(r)
                    k = (lb.name, pr.name)
                    if k not in worst or d > worst[k]['depth_m']: worst[k] = r
    resid = []
    for pname, cs in CONTACTS.items():
        pv = bpy.data.objects[pname]
        for f, (tgt, a, side) in cs.items():
            sc.frame_set(f); bpy.context.view_layer.update()
            hp = pv.matrix_world @ Vector((side * 0.5 * S, 0, -a * S))
            resid.append({'pivot': pname, 'f': f, 'residual_m': (hp - tgt).length})
    bad_contacts = [r for r in resid if r['residual_m'] > 0.04]
    summary = sorted(worst.values(), key=lambda r: -r['depth_m'])
    rep = {'tol': tol, 'frames_checked': len(list(frames)), 'hits': len(rows), 'worst': summary, 'rows': rows,
           'contacts_checked': len(resid), 'contacts_broken': bad_contacts}
    if path: open(path, 'w').write(json.dumps(rep, indent=1))
    print('PENETRATION', len(rows), 'frame-hits; worst:', [(r['f'], r['limb'], r['prop'], round(r['depth_m'], 3)) for r in summary[:5]],
          '| contacts', len(resid), 'broken', len(bad_contacts))
    return rep


# ================================================================ camera
def _samples(tg):
    bb = [Vector(c) for c in tg.bound_box]; lo = Vector((min(c.x for c in bb), min(c.y for c in bb), min(c.z for c in bb)))
    hi = Vector((max(c.x for c in bb), max(c.y for c in bb), max(c.z for c in bb)))
    pts = []
    for fx in (0.0, 0.5, 1.0):
        for fy in (0.0, 0.5, 1.0):
            for fz in (0.0, 0.5, 1.0):
                pts.append(tg.matrix_world @ Vector((lo.x + (hi.x - lo.x) * fx, lo.y + (hi.y - lo.y) * fy, lo.z + (hi.z - lo.z) * fz)))
    return pts


def shot_visibility(sc, cam, frames, targets, samples=27):
    """Per frame and target: fraction of 27 bbox sample points inside the frame AND unoccluded (ray-cast; the target's
    own hierarchy does not occlude), plus the projected screen area fraction. Returns {name: (min_vis, mean_vis, min_area)}."""
    from bpy_extras.object_utils import world_to_camera_view
    out = {}
    for f in frames:
        sc.frame_set(f); bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
        cpos = cam.matrix_world.translation
        for tg in targets:
            pts = _samples(tg); ok = 0; xs = []; ys = []
            anc = tg.parent or tg
            def under(o):
                while o is not None:
                    if o == anc or o == tg: return True
                    o = o.parent
                return False
            for p in pts:
                v = world_to_camera_view(sc, cam, p)
                if v.z > 0: xs.append(min(1, max(0, v.x))); ys.append(min(1, max(0, v.y)))
                if not (0.02 <= v.x <= 0.98 and 0.02 <= v.y <= 0.98 and v.z > 0): continue
                d = p - cpos; hit, loc, _, _, obj, _ = sc.ray_cast(dg, cpos, d.normalized(), distance=d.length - 0.02)
                if not hit or under(obj): ok += 1
            area = (max(xs) - min(xs)) * (max(ys) - min(ys)) if xs else 0.0
            out.setdefault(tg.name, []).append((ok / len(pts), area))
    return {k: (min(v[0] for v in vals), sum(v[0] for v in vals) / len(vals), min(v[1] for v in vals)) for k, vals in out.items()}


def choose_camera(sc, cam, candidates, frames, targets, area_goal=None, area_cap=None, prev_cam=None, cut_frame=None, min_cut_deg=32.0):
    """Try (location, aim, lens) candidates; score = worst visibility + 0.25 * mean visibility
    + mean over area_goal {name: screen fraction} of min(1, area / goal). Keeps the best."""
    best = None; area_goal = area_goal or {}
    dprev = None
    if prev_cam is not None and cut_frame is not None:  # 30-degree rule against the previous shot at the cut
        sc.frame_set(cut_frame - 1); bpy.context.view_layer.update()
        dprev = (prev_cam.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()
    for pos, aim, lens in candidates:
        cam.location = Vector(pos); cam.rotation_euler = (Vector(aim) - Vector(pos)).to_track_quat('-Z', 'Y').to_euler(); cam.data.lens = lens
        vis = shot_visibility(sc, cam, frames, targets)
        score = min(v[0] for v in vis.values()) + 0.25 * min(v[1] for v in vis.values())
        if area_goal:
            score += sum(min(1.0, vis[n][2] / g) for n, g in area_goal.items() if n in vis) / len(area_goal)
        if dprev is not None:
            ang = math.degrees(math.acos(max(-1.0, min(1.0, (Vector(aim) - Vector(pos)).normalized().dot(dprev)))))
            if ang < min_cut_deg: score -= 0.6 + 0.8 * (min_cut_deg - ang) / min_cut_deg
        if area_cap:  # occluders (e.g. a foreground arm) may not dominate the frame
            for n, cap in area_cap.items():
                if n in vis: score -= 8.0 * max(0.0, vis[n][2] - cap)
        print('CAMCHOICE', [round(x / S, 2) for x in pos], lens, {k: (round(a, 2), round(b, 2), round(c, 3)) for k, (a, b, c) in vis.items()}, round(score, 3))
        if best is None or score > best[0]: best = (score, pos, aim, lens, vis)
    return best



# ================================================================ secondary motion + camera acting
def spring_follow(sc, driver, follower, frames, stiffness=0.22, damping=0.32, gain=0.9, clamp_deg=5.0, axes=(0, 1)):
    """Overlap/drag: follower (a pivot under the driver, e.g. hair) lags the driver's world angular velocity through a
    damped spring, keyed every frame. Use only on parts without contact constraints (hair, antenna, head accessories)."""
    base = follower.rotation_euler.copy(); r = [0.0, 0.0, 0.0]; v = [0.0, 0.0, 0.0]; prev = None
    lim = D(clamp_deg)
    for f in frames:
        sc.frame_set(f); bpy.context.view_layer.update()
        e = driver.matrix_world.to_euler()
        w = [0.0, 0.0, 0.0] if prev is None else [e[i] - prev[i] for i in range(3)]
        prev = e
        for i in axes:
            v[i] += -stiffness * r[i] - damping * v[i] - gain * w[i]
            r[i] = max(-lim, min(lim, r[i] + v[i]))
        _key(follower, 'rotation_euler', f, Euler((base.x + r[0], base.y + r[1], base.z + r[2])))


def auto_blinks(schedule, blink='blink', open_kind='smile', start=30, period=78, end=479, guard=6, skip=('o', 'sheepish')):
    """Insert 2-frame blinks into an expression schedule wherever `open_kind` is active and no change is within guard."""
    out = dict(schedule); changes = sorted(schedule)
    if not changes: return out
    def active(f): return schedule[max((k for k in changes if k <= f), default=changes[0])]
    f = start
    while f < end - 3:
        if active(f) == open_kind and active(f + 2) == open_kind and all(abs(f - c) > guard for c in changes):
            out[f] = blink; out[f + 2] = open_kind
        f += period + (11 if (f // period) % 2 else -7)
    return out


def cam_shake(sc, cam, frame, amp_m, n=6, roll_deg=1.2, seed=1):
    """Decaying hand-held hit on top of the camera's existing path (reads the evaluated path, then re-keys it)."""
    import random
    rnd = random.Random(seed); fr = list(range(frame, frame + n + 1))
    base = []
    for f in fr:
        sc.frame_set(f); bpy.context.view_layer.update(); base.append((cam.location.copy(), cam.rotation_euler.copy()))
    for i, f in enumerate(fr):
        k = (1 - i / n) ** 2 if i < n else 0.0
        off = Vector((rnd.uniform(-1, 1), rnd.uniform(-0.3, 0.3), rnd.uniform(-1, 1))) * amp_m * k
        loc, rot = base[i]
        _key(cam, 'location', f, loc + off)
        _key(cam, 'rotation_euler', f, Euler((rot.x, rot.y + D(roll_deg) * k * (1 if i % 2 else -1), rot.z)))


def punch_in(cam, f0, f1, lens_from, lens_to):
    cam.data.lens = lens_from; cam.data.keyframe_insert('lens', frame=f0)
    cam.data.lens = lens_to; cam.data.keyframe_insert('lens', frame=f1)


def cut_report(sc, subject, path=None):
    """30-degree / shot-size check across every marker cut: flags cuts with < 30 deg view change AND < 1.4x size change."""
    from bpy_extras.object_utils import world_to_camera_view
    ms = sorted(sc.timeline_markers, key=lambda m: m.frame); rows = []
    def info(cam, f):
        sc.frame_set(f); bpy.context.view_layer.update()
        d = (cam.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()
        pts = [world_to_camera_view(sc, cam, subject.matrix_world @ Vector(c)) for c in subject.bound_box]
        return d, max(p.y for p in pts) - min(p.y for p in pts)
    for a, b in zip(ms, ms[1:]):
        da, sa = info(a.camera, b.frame - 1); db, sb = info(b.camera, b.frame)
        ang = math.degrees(math.acos(max(-1, min(1, da.dot(db))))); ratio = max(sa, sb) / max(1e-6, min(sa, sb))
        rows.append({'cut': b.frame, 'from': a.name, 'to': b.name, 'angle_deg': round(ang, 1), 'size_ratio': round(ratio, 2),
                     'jump_cut': ang < 30 and ratio < 1.4})
    if path: open(path, 'w').write(json.dumps(rows, indent=1))
    print('CUTS', [(r['cut'], r['angle_deg'], r['size_ratio'], 'JUMP' if r['jump_cut'] else 'ok') for r in rows])
    return rows


# ================================================================ tip contact on a surface (v3: the hand touches, the arm never passes through)
LAST_POSE = {}
TIP = 1.9  # studs from the pivot along the limb to the hand point


def aim_tip(sc, pivot, side, frame, target_world, rx_rng=(-200, 40), ry_rng=(-130, 130), w_cont=0.0006, with_rz=False):
    """Tip-only aim; preserve the legacy (rx, ry, error) result unless with_rz requests all three angles.
    Continuity chooses the twist after matching the target direction, without trading away contact accuracy."""
    rx, ry, rz, e = _aim(sc, pivot, side, frame, target_world, rx_rng, ry_rng, continuity=bool(w_cont))
    return (rx, ry, rz, e) if with_rz else (rx, ry, e)


def reach_surface(sc, pivot, side, frame, center, radius, z_lo, z_hi, prefer=None, min_z=None, standoff=True, local_frame=None):
    """Pick the point on a cylinder surface where the HAND (limb tip, standing off half a limb thickness) lands exactly at
    arm's length; prefer the side facing the pivot and continuity. With local_frame (the prop's world matrix) the
    cylinder axis, centre and z range are in PROP-LOCAL coordinates, so the surface tilts/rotates with the prop."""
    PW, T = _pivot_frame(sc, pivot, frame)
    P = (PW @ T).translation; reach = math.hypot(TIP, 0.5) * S; r = radius + (LIMB_HALF if standoff else 0.0)
    M = local_frame if local_frame is not None else Matrix.Identity(4)
    c = Vector(center); cW = M @ c
    fl = M.inverted().to_3x3() @ (P - cW); fl.z = 0
    fl = fl.normalized() if fl.length > 1e-6 else Vector((0, -1, 0))
    best = None
    for ai in range(0, 360, 5):
        a = D(ai); n = Vector((math.cos(a), math.sin(a), 0))
        for k in range(7):
            zl = z_lo + (z_hi - z_lo) * k / 6
            qW = M @ Vector((c.x + n.x * r, c.y + n.y * r, zl))
            if min_z is not None and qW.z < min_z: continue
            score = abs((qW - P).length - reach) + 0.25 * S * (1 - n.dot(fl)) + (0.4 * (qW - prefer).length if prefer else 0)
            if best is None or score < best[0]: best = (score, qW)
    return best[1]


def key_tip(sc, pivot, side, frame, target_world, tol=0.03, label='', **rng):
    rx, ry, rz, e = aim_tip(sc, pivot, side, frame, target_world, with_rz=True, **rng)
    print('TIP', label or pivot.name, frame, round(rx, 1), round(ry, 1), round(rz, 1), round(e, 3))
    assert e < tol, f'tip {label or pivot.name} f{frame}: error {e:.3f} m > {tol} (unreachable: lean/move the body)'
    _key(pivot, 'rotation_euler', frame, (D(rx), D(ry), D(rz))); LAST_POSE[pivot.name] = (rx, ry, rz)
    CONTACTS.setdefault(pivot.name, {})[frame] = (Vector(target_world), TIP, side)
    return rx, ry, e


def touch(sc, pivot, side, frame, center, radius, z_lo, z_hi, tol=0.03, label='', prefer=None, min_z=None, standoff=True, local_frame=None, **rng):
    """One-call contact: choose the reachable surface point, then aim the hand there. Returns the point used."""
    q = reach_surface(sc, pivot, side, frame, center, radius, z_lo, z_hi, prefer=prefer, min_z=min_z, standoff=standoff, local_frame=local_frame)
    key_tip(sc, pivot, side, frame, q, tol, label, **rng)
    return q


def follow_surface(sc, pivot, side, prop, frames, local_center_studs, radius_studs, dz_lo_studs, dz_hi_studs, tol=0.03, label='', min_z=None, tilt=False):
    """Hold a moving/rotating prop with the HAND: each frame re-pick the reachable surface point near the last one."""
    prev = None; lc = Vector(tuple(c * S for c in local_center_studs))
    for f in frames:
        sc.frame_set(f); bpy.context.view_layer.update()
        if tilt:  # opt-in: surface tilts with the prop (tested worse on the cake catch: 175 vs 70 hits, overhead pose)
            prev = touch(sc, pivot, side, f, lc, radius_studs * S, lc.z + dz_lo_studs * S, lc.z + dz_hi_studs * S, tol, label,
                         prefer=prev, min_z=min_z, local_frame=prop.matrix_world.copy())
        else:
            c = prop.matrix_world @ lc
            prev = touch(sc, pivot, side, f, c, radius_studs * S, c.z + dz_lo_studs * S, c.z + dz_hi_studs * S, tol, label, prefer=prev, min_z=min_z)
    return prev


# ================================================================ clear-anchor hold (v4): contact AND whole-limb clearance together
def _arm_depth_for(pivot, side, PW, T, rx, ry, rz, pts):
    limb = limb_mesh(pivot); lo, hi = _bounds_np(limb); child = np.array(limb.matrix_local)
    M = np.array(PW) @ np.array(T) @ np.array(Euler((D(rx), D(ry), D(rz))).to_matrix().to_4x4()) @ child
    return _pts_depth(pts, M, lo, hi)


def _surface_candidates(P, cW, Mrot, c_local, r, z_lo, z_hi, reach, face_local, min_z=None, k=14):
    cands = []
    for ai in range(0, 360, 6):
        a = D(ai); n = Vector((math.cos(a), math.sin(a), 0))
        for j in range(7):
            zl = z_lo + (z_hi - z_lo) * j / 6
            qW = cW + Mrot @ Vector((n.x * r, n.y * r, zl - c_local.z))
            if min_z is not None and qW.z < min_z: continue
            cands.append((abs((qW - P).length - reach) + 0.25 * S * (1 - n.dot(face_local)), qW))
    cands.sort(key=lambda c: c[0]); return [q for _, q in cands[:k]]


def hold_clear(sc, pivot, side, prop, frames, local_center_studs, radius_studs, dz_lo_studs, dz_hi_studs, clear_objs,
               tol=0.03, clear_tol=0.03, label='', min_z=None):
    """Hold a moving prop with the HAND while the WHOLE limb stays out of `clear_objs`.
    The anchor is stored in PROP-LOCAL coordinates and reused while it stays reachable and clear; otherwise the best
    clear candidate on the surface (nearest the old anchor) is chosen. Reports frames with no clear solution."""
    lc = Vector(tuple(c * S for c in local_center_studs)); anchor_local = None; infeasible = []
    reach = math.hypot(TIP, 0.5) * S
    for f in frames:
        PW, T = _pivot_frame(sc, pivot, f)
        P = (PW @ T).translation; M = prop.matrix_world.copy(); cW = M @ lc
        pts = np.concatenate([np.array([(o.matrix_world @ v.co)[:] for v in o.data.vertices]) for o in clear_objs])
        def try_target(q):
            rx, ry, rz, e = aim_tip(sc, pivot, side, f, q, with_rz=True)
            return rx, ry, rz, e, _arm_depth_for(pivot, side, PW, T, rx, ry, rz, pts)
        chosen = None
        if anchor_local is not None:
            q = M @ anchor_local; rx, ry, rz, e, d = try_target(q)
            if e < tol and d <= clear_tol: chosen = (q, rx, ry, rz, e)
        if chosen is None:
            fl = M.inverted().to_3x3() @ (P - cW); fl.z = 0; fl = fl.normalized() if fl.length > 1e-6 else Vector((0, -1, 0))
            cands = _surface_candidates(P, cW, Matrix.Identity(3), lc, radius_studs * S + LIMB_HALF,
                                        lc.z + dz_lo_studs * S, lc.z + dz_hi_studs * S, reach, fl, min_z)
            if anchor_local is not None:
                old = M @ anchor_local; cands.sort(key=lambda q: (q - old).length)
            best_fallback = None
            for q in cands:
                rx, ry, rz, e, d = try_target(q)
                if e < tol and d <= clear_tol: chosen = (q, rx, ry, rz, e); break
                if e < tol and (best_fallback is None or d < best_fallback[5]): best_fallback = (q, rx, ry, rz, e, d)
            if chosen is None and best_fallback is not None:
                chosen = best_fallback[:5]; infeasible.append((f, round(best_fallback[5], 3)))
        if chosen is None:
            infeasible.append((f, 'unreachable')); continue
        q, rx, ry, rz, e = chosen
        anchor_local = M.inverted() @ q
        _key(pivot, 'rotation_euler', f, (D(rx), D(ry), D(rz))); LAST_POSE[pivot.name] = (rx, ry, rz)
        CONTACTS.setdefault(pivot.name, {})[f] = (q.copy(), TIP, side)
    print('HOLD', label or pivot.name, 'frames', len(list(frames)), 'infeasible', infeasible[:12])
    return infeasible


# ================================================================ camera tracking (v5)
def frame_targets(sc, cam, frames, targets, weights=None, lag=0.25, max_turn_deg=25.0, from_aim=None):
    """Re-aim a camera every frame toward the weighted centre of its key objects (objects or world points),
    with damped lag (0 = rigid, 1 = frozen) and a cap on total turn from the original aim, keeping the camera's
    position path. Keeps falling/moving story objects in frame without hand-typed pans."""
    weights = weights or [1.0] * len(targets)
    sc.frame_set(frames[0]); bpy.context.view_layer.update()
    base_dir = (cam.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()
    aim = None
    for f in frames:
        sc.frame_set(f); bpy.context.view_layer.update()
        pts = [(t.matrix_world.translation if hasattr(t, 'matrix_world') else Vector(t)) for t in targets]
        c = sum((p * w for p, w in zip(pts, weights)), Vector()) / sum(weights)
        aim = c if aim is None else aim.lerp(c, 1 - lag)
        d = (aim - cam.location).normalized()
        ang = math.degrees(math.acos(max(-1.0, min(1.0, d.dot(base_dir)))))
        if ang > max_turn_deg:
            d = base_dir.slerp(d, max_turn_deg / ang) if hasattr(base_dir, 'slerp') else (base_dir.lerp(d, max_turn_deg / ang)).normalized()
        _key(cam, 'rotation_euler', f, d.to_track_quat('-Z', 'Y').to_euler())
