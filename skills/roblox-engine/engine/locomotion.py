"""locomotion.py - standing R6 characters: build, walk (planted feet), idle breathing, sit down / stand up.

Units: world metres, STUD S = 0.5 m, angles in radians inside the code (degrees only in public args named *_deg),
frames are scene frames. Forward of a character is local -Y (as in claude_still.r6, whose seated legs point to -Y).
World heading: forward = (sin yaw, -cos yaw), so yaw = atan2(dx, -dy) for a travel direction (dx, dy).
Rigid R6 limbs: a leg is a 1x1x2-stud box hanging along -Z from a HIP pivot empty (L = 2 studs = 1.0 m).

Walk model (heel-toe roll, so no floor digging and no sliding):
 * 50/50 duty: exactly one foot is planted at any frame. A planted foot touches the floor with the bottom-edge midpoint of the
   sole at its REAR edge (heel) while the leg points forward, then the sole lies flat (leg vertical) and the FRONT edge (toe)
   becomes the fixed point while the leg points backward. That contact point is fixed in the world during the stance.
 * Root height follows from the planted contact (hip is exactly |D.z| above it), so the torso bobs by the leg geometry
   (about 13 cm at 30 deg). A smaller stride_deg gives a smaller bob.
 * The stance lasts n whole frames (n derived from speed and stride); stride is re-derived so n is an integer, hence the
   cycle (2 steps) is exactly 2n frames and loops pose-for-pose on a straight line. Speed is rescaled by <1/N so the walk
   ends exactly on the last path point. Real values are returned in the info dict.
 * Swing leg: quaternion slerp from the toe-off pose to the next heel-strike pose. A rigid leg cannot lift its foot, so the
   swing sole just skims the floor at mid swing (the minimum clearance is reported in info['swing_min_clear']).
Shortcuts: contact is the sole edge midpoint (the sole side corners can dip ~1-2 cm on tight curves); sit/stand do not model
the chair seat edge or back (thighs rest on seat_z; the legs overlap the torso base by half a stud, as in Roblox).
"""
import math, sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import bpy
from mathutils import Vector, Quaternion, Euler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_still as cs

S = cs.S
LEG = 2 * S            # leg length, m (hip pivot to sole)
SOLE_Y = 0.5 * S       # half sole depth along the leg's local Y, m
RHO = math.hypot(LEG, SOLE_Y)   # hip -> sole edge midpoint distance
DELTA = math.atan2(SOLE_Y, LEG)  # angle of that edge midpoint off the leg axis
HALF_W = 0.5 * S       # half leg width (local X), m
import os as _os
TURN_STEP_DEG = float(_os.environ.get('L1_TURN', 60.0))   # a walk's launch turn: degrees per planted step (35 made a 180 deg turn a 1.5 s six-step shuffle, L1 GAIT)


# ---------------------------------------------------------------- build
def make_r6_standing(name, loc, yaw_deg=0, shirt=None, pants=None, skin=None, hairm=None, face=None):
    """Standing R6 at loc=(x,y,z) metres of the FEET centre (root origin on the floor), heading yaw_deg.
    Returns SimpleNamespace(root, torso, head, hips=[left(-1), right(+1)], shoulders=[left, right], legs, arms).
    Hips are empties at the torso bottom (z = 2 studs) with a 1x1x2 leg box hanging along -Z; shoulders as in r6()."""
    skin = skin or cs.mat('Roblox yellow', (1.0, 0.78, 0.002), 0.8, 0.12)
    shirt = shirt or cs.mat('Shirt', (0.9, 0.9, 0.95))
    pants = pants or cs.mat('Blue pants', (0.04, 0.09, 0.32))
    hairm = hairm or cs.mat('Hair', (0.08, 0.05, 0.03))
    root = bpy.data.objects.new(name, None); bpy.context.collection.objects.link(root)
    root.location = loc; root.rotation_euler = (0, 0, math.radians(yaw_deg))
    torso = cs.box(name + ' torso', (0, 0, 3.0), (2, 1, 2), shirt, parent=root)
    hips, shoulders, legs, arms = [], [], [], []
    for side in (-1, 1):
        sh = cs.empty(name + ' shoulder', (side * 1.0, 0, 4.0), parent=root)
        arms.append(cs.box(name + ' arm', (side * 0.5, 0, -1.0), (1, 1, 2), skin, parent=sh)); shoulders.append(sh)
    for side in (-1, 1):
        hp = cs.empty(name + ' hip', (side * 0.5, 0, 2.0), parent=root)
        legs.append(cs.box(name + ' leg', (0, 0, -1.0), (1, 1, 2), pants, parent=hp)); hips.append(hp)
    head = cs.empty(name + ' head', (0, 0, 4.62), parent=root)
    hm = cs.cyl(name + ' head mesh', (0, 0, 0), 0.62, 1.24, skin, bevel=0.16, segs=4); hm.parent = head; hm.location = (0, 0, 0)
    cs.face_decal(name + ' face', 0.62, 1.24, face or cs.face_image('smile'), head)
    cs.hair(head, hairm, 0.62)
    for o in hips + shoulders: o.rotation_mode = 'XYZ'
    return SimpleNamespace(root=root, torso=torso, head=head, hips=hips, shoulders=shoulders, legs=legs, arms=arms)


# ---------------------------------------------------------------- path
def _rz(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s], [s, c]])


class Path:
    """Polyline (metres, xy) with filleted corners (radius corner_r m); arc-length parametrised; extrapolates linearly."""
    def __init__(self, pts, corner_r=2.0):
        P = [np.asarray(p, float)[:2] for p in pts]
        P = [p for k, p in enumerate(P) if k == 0 or np.linalg.norm(p - P[k - 1]) > 1e-9]  # drop duplicate waypoints (zero-length segments gave NaN)
        assert len(P) >= 2, 'path needs at least 2 distinct points'
        out = [P[0]]
        for k in range(1, len(P) - 1):
            A, B, C = P[k - 1], P[k], P[k + 1]
            u1, u2 = (A - B) / np.linalg.norm(A - B), (C - B) / np.linalg.norm(C - B)
            phi = math.acos(np.clip(u1 @ u2, -1, 1))
            assert phi > 1e-2, 'path reverses 180 deg at point %d: add an intermediate waypoint' % k
            if phi > math.pi - 1e-3:
                out.append(B); continue
            t = corner_r / math.tan(phi / 2)
            assert t <= 0.5 * min(np.linalg.norm(A - B), np.linalg.norm(C - B)) + 1e-9, 'corner radius too big for segment %d' % k
            T1, T2 = B + u1 * t, B + u2 * t
            bis = (u1 + u2) / np.linalg.norm(u1 + u2); cen = B + bis * corner_r / math.sin(phi / 2)
            a1, a2 = math.atan2(*(T1 - cen)[::-1]), math.atan2(*(T2 - cen)[::-1])
            da = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
            for j in range(0, 61):
                a = a1 + da * j / 60; out.append(cen + corner_r * np.array([math.cos(a), math.sin(a)]))
        out.append(P[-1])
        P = np.array(out); seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
        self.P = P[np.concatenate([[True], seg > 1e-9])]
        self.cum = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(self.P, axis=0), axis=1))]); self.L = self.cum[-1]
        self.d0 = (self.P[1] - self.P[0]) / np.linalg.norm(self.P[1] - self.P[0])
        self.d1 = (self.P[-1] - self.P[-2]) / np.linalg.norm(self.P[-1] - self.P[-2])

    def pos(self, s):
        if s < 0: return self.P[0] + self.d0 * s
        if s > self.L: return self.P[-1] + self.d1 * (s - self.L)
        return np.array([np.interp(s, self.cum, self.P[:, 0]), np.interp(s, self.cum, self.P[:, 1])])

    def yaw(self, s):
        e = 0.03; d = self.pos(s + e) - self.pos(s - e)
        return math.atan2(d[0], -d[1])


# ---------------------------------------------------------------- walk
def walk(sc, root, hips, shoulders, path_points, f_start, speed_studs_s=8, stride_deg=30, arm_ratio=0.9,
         corner_r=2.0, lead=6, floor_z=0.0, _hip_step_deg=25):
    """Bake a planted-foot walk. root: character root empty (origin on the floor); hips/shoulders: [left(-1), right(+1)]
    empties from make_r6_standing. path_points: world xy metres (corners filleted with corner_r m). speed in studs/s
    (1 stud = 0.5 m); stride_deg = nominal hip swing amplitude. lead = frames before f_start / after the end that blend
    from/to the neutral standing pose (0 disables). Keys root loc/yaw and hip/shoulder rotation EVERY frame.
    Cadence uses even stance lengths and ends at flat mid-stance; the returned speed accounts for that timing.
    The swing leg's hip pivot is lifted for 25 mm sole clearance, eased at toe-off and landing (info['swing_min_clear'] is
    the clearance BEFORE that lift). Returns info dict: f_start, f_end, n (frames per stance), speed_studs_s, stride_deg, bob_m, swing_min_clear (m, <0 = dig),
    contact[i] = (side, 'heel'|'toe') for i in 0..N (frame = f_start+i)."""
    fps = sc.render.fps / sc.render.fps_base
    pth = Path(path_points, corner_r)
    v = speed_studs_s * S
    w0_nom = RHO * math.sin(math.radians(stride_deg) - DELTA)
    n = 2 * max(1, round((w0_nom + SOLE_Y) * fps / v))
    # L1 GAIT (creator bug 'scissor legs'): the whole-frame cadence may round the stride UP (9.5 studs/s at 30 deg -> 33.5 deg,
    # legs 67 deg apart); a WALK whose stride would pass stride_deg + 2 takes the quicker cadence with the smaller stride (9.5 studs/s:
    # 22 deg; 8 studs/s keeps 28 deg, and tests/test_locomotion's 2-frame heel/toe rule with it). Runs (stride > 35) keep theirs.
    if not _os.environ.get('L1_NO2') and stride_deg <= 35 and n > 2 and (n - 2) * v / fps / 2 - SOLE_Y > 0.05 and \
            math.degrees(DELTA + math.asin(min(1.0, max(0.0, n * v / fps / 2 - SOLE_Y) / RHO))) > stride_deg + 2: n -= 2
    # Finish at flat mid-stance so the stop does not drag a loaded, tilted sole home.
    N = max(n // 2, math.ceil((pth.L / (v / fps) - n / 2) / n) * n + n // 2)
    D = pth.L / N
    w0 = n * D / 2 - SOLE_Y                                        # heel lands w0 ahead of the hip
    assert pth.L > 2 * SOLE_Y and 0 < w0 < RHO, 'stride/speed combination impossible for 1m legs (w0=%.3f)' % w0
    eff_stride = math.degrees(DELTA + math.asin(w0 / RHO))
    pos = lambda t: pth.pos(t * D)
    yawf = lambda t: pth.yaw(t * D)
    M = N // n + 1

    steps = {}  # m -> dict(side, hx, Hw, Tw, ts)
    for m in range(-1, M + 1):
        i0 = m * n; side = -1 if m % 2 == 0 else 1; hx = side * 0.5 * S
        heading = yawf(i0)
        Hw = pos(i0) + _rz(heading) @ np.array([hx, -w0])
        def ly(t, Hw=Hw, heading=heading, hx=hx):
            hip = pos(t) + _rz(yawf(t)) @ np.array([hx, 0])
            return (_rz(-heading) @ (Hw - hip))[1] - SOLE_Y
        lo, hi = float(i0), float(i0 + n)
        assert ly(lo) < 0 < ly(hi), 'flat-foot instant not inside stance'
        for _ in range(50):
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if ly(mid) < 0 else (lo, mid)
        ts = 0.5 * (lo + hi)
        Tw = Hw + _rz(heading) @ np.array([0, -2 * SOLE_Y])
        steps[m] = dict(side=side, hx=hx, Hw=Hw, Tw=Tw, ts=ts, heading=heading)

    def stance(m, t):  # leg quaternion + hip height above the contact for the planted foot of step m at frame t
        s = steps[m]; heel = t < s['ts']
        C, cy = (s['Hw'], SOLE_Y) if heel else (s['Tw'], -SOLE_Y)
        hip = pos(t) + _rz(yawf(t)) @ np.array([s['hx'], 0])
        dx, dy = _rz(-s['heading']) @ (C - hip)
        # Lateral roll loads a fixed sole corner; the heel/toe centres keep their landing heading.
        cx = -math.copysign(HALF_W, dx)
        height2 = RHO ** 2 - dy * dy
        dz2 = height2 + cx * cx - (dx + cx) ** 2
        assert height2 > 0 and dz2 > 0, 'foot beyond leg reach'
        dz = math.sqrt(dz2)
        height = math.sqrt(height2)
        ax = math.asin(dy / RHO) - math.atan2(cy, LEG)
        by = math.atan2(cx, height) - math.asin((dx + cx) / math.hypot(cx, height))
        e = Euler((ax, by, (s['heading'] - yawf(t) + math.pi) % (2 * math.pi) - math.pi), 'XYZ')
        q = e.to_quaternion()
        return q, dz, 'heel' if heel else 'toe'

    def g(u): return u - 0.1 * math.sin(2 * math.pi * u)

    eul = {-1: Euler((0, 0, 0)), 1: Euler((0, 0, 0))}
    contact, rows = [], []
    yaw_acc = root.rotation_euler.z; minclear = 1e9
    for i in range(N + 1):
        m, u = divmod(i, n); u /= n; sm = steps[m]['side']
        q_st, dz, kind = stance(m, i); contact.append((sm, kind))
        row = dict(i=i, z=floor_z + dz - LEG)
        for side in (-1, 1):
            if side == sm: q = q_st
            else:
                a, b = m * n, (m + 1) * n
                qa = Quaternion((0, 0, 1), yawf(a)) @ stance(m - 1, a)[0]
                qb = Quaternion((0, 0, 1), yawf(b)) @ stance(m + 1, b)[0]
                q = Quaternion((0, 0, 1), -yawf(i)) @ qa.slerp(qb, g(u))
            # lowest sole corner (4 corners, 0.25 m half width) vs floor; the hip is dz above the planted contact
            clear = dz + min((q @ Vector((cx, cy, -LEG))).z for cx in (SOLE_Y, -SOLE_Y) for cy in (SOLE_Y, -SOLE_Y))
            if side != sm: minclear = min(minclear, clear)
            ramp = min(1.0, u * n, (1 - u) * n)
            target = 0.025 * ramp * ramp * (3 - 2 * ramp) if side != sm else 0.0
            landing = min(1.0, (N - i) / 2)   # finish the swing before lowering into the floor contact band
            if side != sm: target *= landing * landing * (3 - 2 * landing)
            row['lift', side] = max(0.0, target - clear)
            e = q.to_euler('XYZ', eul[side])
            assert not rows or max(abs(a - b) for a, b in zip(e, eul[side])) < math.radians(_hip_step_deg), 'hip turn too sharp for continuous walk'
            eul[side] = e; row[side] = e.copy()
        p = pos(i); y = yawf(i)
        yaw_acc += (y - yaw_acc + math.pi) % (2 * math.pi) - math.pi
        row.update(x=p[0], y=p[1], yaw=yaw_acc); rows.append(row)

    hz0 = [h.location.z for h in hips]
    def neutral(f, r):
        root.location = (r['x'], r['y'], floor_z); root.rotation_euler = (0, 0, r['yaw'])
        root.keyframe_insert('location', frame=f); root.keyframe_insert('rotation_euler', frame=f)
        for o in hips + shoulders:
            o.rotation_euler = (0, 0, 0); o.keyframe_insert('rotation_euler', frame=f)
        for k, h in enumerate(hips): h.location.z = hz0[k]; h.keyframe_insert('location', frame=f)
    if lead: neutral(f_start - lead, rows[0])
    for r in rows:
        f = f_start + r['i']
        root.location = (r['x'], r['y'], r['z']); root.rotation_euler = (0, 0, r['yaw'])
        root.keyframe_insert('location', frame=f); root.keyframe_insert('rotation_euler', frame=f)
        for k, side in enumerate((-1, 1)):
            hips[k].rotation_euler = r[side]; hips[k].keyframe_insert('rotation_euler', frame=f)
            hips[k].location.z = hz0[k] + r['lift', side]; hips[k].keyframe_insert('location', frame=f)
            # each arm swings opposite to its own-side leg (= with the other leg); forward is negative X rotation
            shoulders[k].rotation_euler = (-arm_ratio * r[side].x, 0, 0); shoulders[k].keyframe_insert('rotation_euler', frame=f)
    if lead: neutral(f_start + N + lead, rows[-1])
    zs = [r['z'] for r in rows]
    return dict(f_start=f_start, f_end=f_start + N, n=n, N=N, speed_studs_s=D * fps / S, stride_deg=eff_stride,
                bob_m=max(zs) - min(zs), swing_min_clear=minclear, contact=contact, path=pth)


# ---------------------------------------------------------------- idle
def feet_now(ch):
    """[[sole centre xy (world, metres), sole heading (yaw rad)] for each leg] at the currently evaluated frame."""
    out = []
    for h in ch.hips:
        M = h.matrix_world; c = M @ Vector((0, 0, -LEG)); fw = M.to_3x3() @ Vector((0, -1, 0))
        out.append([Vector((c.x, c.y)), math.atan2(fw.x, -fw.y)])
    return out


def _leg_pose(dx, dy, rest_h=LEG):
    """Hip rotation (rx, ry) that puts the sole centre at (dx, dy) local offset from the hip (forward = -Y), and the vertical
    distance hip -> LOWEST sole corner at that pose (a tilted box leg stands on an edge/corner)."""
    a = math.asin(max(-0.99, min(0.99, dy / LEG)))
    b = math.asin(max(-0.99, min(0.99, -dx / (LEG * math.cos(a)))))
    R = Euler((a, b, 0.0)).to_matrix()
    low = min((R @ Vector((x, y, -LEG))).z for x in (-HALF_W, HALF_W) for y in (-SOLE_Y, SOLE_Y))
    return a, b, -low


def _step_count(distance, dyaw, step_m=0.5 * S, step_deg=35.0):
    return max(1, math.ceil(distance / step_m - 1e-9), math.ceil(abs(math.degrees(dyaw)) / step_deg - 1e-9))


def step_to(sc, ch, goal_xy, f_start, goal_yaw=None, step_m=0.5 * S, step_deg=35.0, frames_per_step=6, lift_m=0.025,
            feet_goal=None, key_last=True, key_first=True):
    """Planted steps from the current root pose to goal_xy (metres) and goal_yaw (radians, default: keep the heading):
    sideways, forward/back, diagonal, turning in place, or a step-and-turn. A planted foot stays fixed in the world (it may
    pivot on its sole centre); the stepping foot lands at its home spot under the next body pose; the root height comes
    from the planted soles' lowest corners; the swing foot arcs up and never dips below the floor. Keys every frame.
    Starts from where the feet ACTUALLY are (e.g. mid-stride at the end of a walk -> a stop step). feet_goal = optional
    [(xy, yaw), (xy, yaw)] for the last step instead of the home spots (e.g. a walk's first stride -> a start step);
    key_last=False leaves the end frame to the caller (the walk keys it).
    Returns the end frame. Replaces the glide shuffle and the root spin of in-place turns (both slid the feet)."""
    sc.frame_set(f_start); bpy.context.view_layer.update()
    r = ch.root; y0 = r.rotation_euler.z; p0 = Vector(r.location.xy); goal = Vector(goal_xy)
    e = r.matrix_world.to_euler()
    if abs(e.x) > 0.3 or abs(e.y) > 0.3 or any(abs(h.rotation_euler.x) > 1.0 for h in ch.hips):
        raise ValueError(f'step_to: {r.name} is not standing (seated/lying) at f{f_start}')   # Codex review #5
    floor = min(min((l.matrix_world @ Vector(c)).z for c in l.bound_box) for l in ch.legs)     # the support it stands on
    dyaw = 0.0 if goal_yaw is None else (goal_yaw - y0 + math.pi) % (2 * math.pi) - math.pi
    n = _step_count((goal - p0).length, dyaw, step_m, step_deg)
    hx = [h.location.x for h in ch.hips]; hz0 = [h.location.z for h in ch.hips]
    def home(k, pos, yaw):   # where leg k's sole centre sits under a body at (pos, yaw)
        return pos + Vector((math.cos(yaw), math.sin(yaw))) * hx[k]
    feet = feet_now(ch)                                      # world sole centre + sole heading, as evaluated now
    # atan2 headings must share the body's turn count before interpolating.
    for foot in feet: foot[1] = y0 + (foot[1] - y0 + math.pi) % (2 * math.pi) - math.pi
    y1_ = y0 + dyaw
    final = feet_goal or [(home(k, goal, y1_), y1_) for k in (0, 1)]
    final = [(xy, y1_ + (fy - y1_ + math.pi) % (2 * math.pi) - math.pi) for xy, fy in final]
    if (goal - p0).length < 1e-4 and abs(dyaw) < 1e-4 and all((feet[k][0] - Vector(final[k][0])).length < 0.01 for k in (0, 1)):
        return f_start
    sw = [None, None]; half = frames_per_step // 2

    def key(f, pos, yaw, swing_k=None, u=0.0):
        pose = []
        for k in (0, 1):
            fp, fy = feet[k]
            if swing_k == k:
                (a0, y_a), (a1, y_b) = sw[k]; fp = a0.lerp(a1, u); fy = y_a + (y_b - y_a) * u
            d = fp - home(k, pos, yaw)                       # sole offset from its hip, world
            c = fy - yaw                                     # the foot keeps its world heading: twist at the hip
            loc = Vector((math.cos(-yaw) * d.x - math.sin(-yaw) * d.y, math.sin(-yaw) * d.x + math.cos(-yaw) * d.y))
            h = Vector((math.cos(-c) * loc.x - math.sin(-c) * loc.y, math.sin(-c) * loc.x + math.cos(-c) * loc.y))
            ax, by, reach = _leg_pose(h.x, h.y); pose.append((ax, by, c, reach))
        root_z = floor + max(pose[k][3] for k in (0, 1) if k != swing_k) - LEG   # planted lowest corner on the support
        r.location = (pos.x, pos.y, root_z); r.rotation_euler.z = yaw
        r.keyframe_insert('location', frame=f); r.keyframe_insert('rotation_euler', frame=f)
        for k in (0, 1):
            hp = ch.hips[k]; hp.rotation_euler = pose[k][:3]; hp.keyframe_insert('rotation_euler', frame=f)
            lift = (pose[k][3] - LEG - (root_z - floor)) + max(lift_m * math.sin(math.pi * u), 0.004) if swing_k == k else 0.0   # the swing sole's LOWEST corner clears by lift_m (R133: 4 mm dragged)
            hp.location.z = hz0[k] + lift; hp.keyframe_insert('location', frame=f)

    f = f_start; pos, yaw = p0.copy(), y0
    if key_first: key(f, pos, yaw)
    for i in range(1, n + 1):
        p1, y1 = p0.lerp(goal, i / n), y0 + dyaw * i / n
        # lead with the leg that has further to go (the travel/turn side)
        tgt = [(Vector(final[k][0]), final[k][1]) if i == n else (home(k, p1, y1), y1) for k in (0, 1)]
        order = sorted((0, 1), key=lambda k: -(tgt[k][0] - feet[k][0]).length)
        for idx, k in enumerate(order):
            pm, ym = (pos.lerp(p1, 0.5), yaw + (y1 - yaw) * 0.5) if idx == 0 else (p1, y1)   # halfway, then all the way
            sw[k] = ((feet[k][0].copy(), feet[k][1]), tgt[k])
            for j in range(1, half):
                t = j / half; key(f + j, pos.lerp(pm, t), yaw + (ym - yaw) * t, swing_k=k, u=t)
            feet[k] = [tgt[k][0].copy(), tgt[k][1]]; pos, yaw = pm, ym; f += half
            if key_last or i < n or idx == 0: key(f, pos, yaw)          # landed: both feet planted
    return f


sidestep = step_to   # side-steps are step_to with a sideways goal


def _hold(ch, f):
    """Key the currently evaluated root + hips at frame f (so later keys cannot reach back before f)."""
    for o in [ch.root] + list(ch.hips):
        o.keyframe_insert('location', frame=f); o.keyframe_insert('rotation_euler', frame=f)


def clear_keys(objs, f0, f1=10 ** 9):
    """Remove every keyframe of these objects in [f0, f1] (an interrupted or re-planned move must not leave keys behind)."""
    import space
    for o in objs:
        for fc in space.fcurves_of(o):
            for i in reversed([i for i, k in enumerate(fc.keyframe_points) if f0 - 0.5 <= k.co.x <= f1 + 0.5]):
                fc.keyframe_points.remove(fc.keyframe_points[i])
            fc.update()


def walk_planted(sc, ch, path, f_start, speed_studs_s=8, stride_deg=30, corner_r=2.0, _hip_step_deg=25):
    """A walk with PLANTED start and stop: hold the standing pose at f_start, start steps that land the feet in
    the walk's first stride, the walk itself (no lead-in blend), then a stop step that brings the feet together. The old
    6-frame lead-in/out blended legs between stride and standing with the body still: a full foot length (50 cm) of slide
    at every walk start and stop. Raises AssertionError when the stride solver cannot walk the path."""
    sc.frame_set(f_start); bpy.context.view_layer.update(); _hold(ch, f_start)
    yaw = Path(path, corner_r).yaw(0)
    dyaw = (yaw - ch.root.rotation_euler.z + math.pi) % (2 * math.pi) - math.pi
    # Reserve the entire step-and-turn so its keys cannot overwrite the walk.
    f_walk = f_start + 6 * _step_count((Vector(path[0]) - ch.root.location.xy).length, dyaw)
    info = walk(sc, ch.root, ch.hips, ch.shoulders, path, f_walk, speed_studs_s=speed_studs_s, stride_deg=stride_deg,
                corner_r=corner_r, lead=0, _hip_step_deg=_hip_step_deg)
    sc.frame_set(f_walk); bpy.context.view_layer.update()
    goal_feet = [(xy.copy(), y) for xy, y in feet_now(ch)]; p1 = Vector(ch.root.location.xy); y1 = ch.root.rotation_euler.z
    step_to(sc, ch, tuple(p1), f_start, goal_yaw=y1, feet_goal=goal_feet, key_last=False)
    fe = info['f_end']
    info['f_end'] = step_to(sc, ch, path[-1], fe, key_first=False)
    info['f_walk_end'] = fe
    return info


def walk_path(sc, ch, path, f_start, speed_studs_s=8, stride_deg=30, corner_r=0.6, planted=None):
    """Walk a routed path. One continuous walk when the stride solver can (filleted corners); otherwise, per straight leg:
    a planted step-turn to face it, then a walk (or planted steps when the leg is shorter than 1.5 studs). The walk's
    6-frame lead-in always starts after the turn ends (its neutral key must not land inside the turn).
    planted(path, f, corner_r, stride_scale) -> info replaces walk_planted (build.py passes run.run_planted: a RUN gets the same
    retries and the same step-and-turn fallback). Returns the walk info dict (f_end always set; 'segmented' True for the fallback)."""
    if planted is None:
        planted = lambda path_, f_, cr_, k_: walk_planted(sc, ch, path_, f_, speed_studs_s=speed_studs_s, stride_deg=k_ * stride_deg,
                                                          **({} if cr_ is None else {'corner_r': cr_}))
    # the stride solver is picky about how a corner falls inside a stride: other fillet radii / stride lengths usually solve the
    # SAME route as one continuous walk; the per-leg fallback turns the 2-stud body in place at every waypoint (leg grazes, R228)
    for cr, sd in ((corner_r, 1.0), (0.6 * corner_r, 1.0), (corner_r, 0.85), (0.6 * corner_r, 0.85), (0.35 * corner_r, 1.0), (0.35 * corner_r, 0.85)):
        try:
            return planted(path, f_start, cr, sd)
        except AssertionError as e:
            err = e
    print('WALK FALLBACK', ch.root.name, str(err)[:60], 'path', [(round(p[0], 3), round(p[1], 3)) for p in path], 'corner_r', round(corner_r, 3))
    f = f_start
    legs = [(p, q) for p, q in zip(path, path[1:]) if math.hypot(q[0] - p[0], q[1] - p[1]) >= 1e-4]
    if LEGACY_FALLBACK:   # last-resort pass of build.walk_to: the pre-L1 per-leg fallback (35 deg turn steps, default step length) for scenes it solved
        for p, q in legs:
            f = step_to(sc, ch, p, f, goal_yaw=math.atan2(q[0] - p[0], -(q[1] - p[1])))
            try:
                if math.hypot(q[0] - p[0], q[1] - p[1]) < 1.5 * S: raise AssertionError('short')
                f = planted([p, q], f, None, 1.0)['f_end']
            except AssertionError:
                f = step_to(sc, ch, q, f)
        return {'f_start': f_start, 'f_end': f, 'segmented': True}
    for k, (p, q) in enumerate(legs):
        d = math.hypot(q[0] - p[0], q[1] - p[1])
        # L1 GAIT (creator bug R259 'weird walking': a 1.5-stud first leg + a 70 deg corner = 30 frames of 25 cm shuffle steps and
        # 35 deg turn steps before the real walk): a leg the stride solver refuses is ONE step-and-turn with stride-sized steps that
        # arrives already facing the next leg; the turn into a walked leg takes TURN_STEP_DEG per step.
        y_leg = math.atan2(q[0] - p[0], -(q[1] - p[1]))
        f1 = None
        try:
            if d < 1.5 * S: raise AssertionError('short')
            f1 = step_to(sc, ch, p, f, goal_yaw=y_leg, step_deg=TURN_STEP_DEG)
            f = planted([p, q], f1, None, 1.0)['f_end']
        except AssertionError:   # the stride solver refuses this leg (too short, odd speed): planted steps always work
            nxt = legs[k + 1] if k + 1 < len(legs) else None
            f = step_to(sc, ch, q, f if f1 is None else f1, goal_yaw=math.atan2(nxt[1][0] - nxt[0][0], -(nxt[1][1] - nxt[0][1])) if nxt else y_leg,
                        step_m=0.75 * S, step_deg=TURN_STEP_DEG)
    return {'f_start': f_start, 'f_end': f, 'segmented': True}


def _rest_on_floor(sc, ch, frames, floor_z=0.0):
    """Key the root height so the body's lowest corner never goes below the floor (a body tipping about its feet sinks half its
    thickness into the floor otherwise, R134 Zed 35 cm). Root x/y/rotation untouched."""
    parts = [ch.torso, ch.head_mesh] + list(ch.legs) + list(ch.arms)
    for f in frames:
        sc.frame_set(f); r = ch.root; r.location.z = floor_z; bpy.context.view_layer.update()
        low = min((o.matrix_world @ Vector(c)).z for o in parts for c in o.bound_box)
        r.location.z = floor_z + max(0.0, floor_z - low); r.keyframe_insert('location', frame=f)


def _pivot_on_edge(sc, ch, frames, back):
    """Key the root position so the body tips about its HEEL edge (back fall) or TOE edge (forward), which stays fixed on the
    floor; tipping about the sole centre scraped the contact edge along the floor (21 cm, R134)."""
    r = ch.root; sc.frame_set(frames[0]); bpy.context.view_layer.update()
    edge = Vector((0.0, SOLE_Y if back else -SOLE_Y, 0.0))                 # local: forward = -Y, so the heel edge is +Y
    anchor = r.matrix_world @ edge
    for f in frames:
        sc.frame_set(f); e = r.rotation_euler
        R = Euler((e.x, e.y, e.z)).to_matrix()
        p = anchor - R @ edge
        r.location = (p.x, p.y, p.z); r.keyframe_insert('location', frame=f)


FALL_KEYS = {}
LEGACY_FALLBACK = False


def fall(sc, ch, f, back=True):
    """Tip over (backward by default) about the heel/toe edge over ~10 frames with a small bounce; the body comes to rest ON
    the floor. Returns the frame it lies still."""
    r = ch.root; sgn = -1 if back else 1; sc.frame_set(f - 2)
    for df, deg in ((-2, 0), (5, 97), (7, 84), (9, 90)):
        r.rotation_euler.x = math.radians(sgn * deg); r.keyframe_insert('rotation_euler', frame=f + df)
    _pivot_on_edge(sc, ch, range(f - 2, f + 12), back)
    _rest_on_floor_add(sc, ch, range(f - 2, f + 12))
    keys = []   # the fall as keyed (root position + tilt): get_up plays it BACKWARDS (a get-up that re-derived its own pivot hovered 10-33 cm, L1 move 09)
    for fr in range(f - 2, f + 12):
        sc.frame_set(fr); keys.append((r.location.copy(), r.rotation_euler.x))
    FALL_KEYS[ch.name] = keys
    return f + 12


def get_up(sc, ch, f, back=True):
    """Reverse of fall (same side, same edge): lying -> standing over 13 frames. Returns the end frame."""
    r = ch.root; sgn = -1 if back else 1
    keys = FALL_KEYS.get(ch.name)
    if keys:   # reverse playback of this character's own fall: same contacts, ends exactly where it stood (z too)
        sc.frame_set(f); d = r.location - keys[-1][0]; d.z = 0.0   # lying spot moved since the fall: carry the whole motion along
        for df in range(14):
            loc, rx = keys[round((13 - df) * (len(keys) - 1) / 13)]
            sc.frame_set(f + df); r.location = loc + d; r.rotation_euler.x = rx
            r.keyframe_insert('location', frame=f + df); r.keyframe_insert('rotation_euler', frame=f + df)
        return f + 14
    sc.frame_set(f); edge = Vector((0.0, SOLE_Y if back else -SOLE_Y, 0.0))
    for df, deg in ((0, 90), (10, -8), (13, 0)):
        r.rotation_euler.x = math.radians(sgn * deg); r.keyframe_insert('rotation_euler', frame=f + df)
    _pivot_on_edge(sc, ch, range(f, f + 14), back)
    _rest_on_floor_add(sc, ch, range(f, f + 14))
    return f + 14


def _rest_on_floor_add(sc, ch, frames, floor_z=0.0):
    """Like _rest_on_floor but keeps the keyed root height and only ADDS the lift needed (a round head can sink a few cm)."""
    parts = [ch.torso, ch.head_mesh] + list(ch.legs) + list(ch.arms)
    for f in frames:
        sc.frame_set(f); bpy.context.view_layer.update()
        low = min((o.matrix_world @ Vector(c)).z for o in parts for c in o.bound_box)
        if low < floor_z:
            ch.root.location.z += floor_z - low; ch.root.keyframe_insert('location', frame=f)


def unwrap_yaw(root):
    """Make the root's heading curve continuous: each key is shifted by whole turns to lie within 180 deg of the previous
    key, so interpolation never goes the long way round (functions key absolute yaws: walk, sit; turns key unwrapped ones)."""
    import space
    for fc in space.fcurves_of(root):
        if fc.data_path != 'rotation_euler' or fc.array_index != 2: continue
        ks = sorted(fc.keyframe_points, key=lambda k: k.co.x); prev = None
        for k in ks:
            if prev is not None:
                d = round((k.co.y - prev) / (2 * math.pi)) * 2 * math.pi
                if d:
                    k.co.y -= d; k.handle_left.y -= d; k.handle_right.y -= d
            prev = k.co.y
        fc.update()


def foot_slide(sc, ch, frames, floor_z=0.0, contact_tol=0.012, move=0.03, cuts=()):
    """Foot slide measured on the FINAL curves, for any motion. Contact feature per leg and frame = the actual lowest
    support: the sole EDGE when its two lowest corners are level (<= 3 mm), else the single lowest CORNER. A grounded run =
    consecutive frames on the floor with the same feature. Per run:
      drag  = distance covered while the contact moves > `move` per frame for >= 3 frames in a row (a glide or a dragged foot;
              a swing foot crossing the floor or landing lasts <= 2 frames),
      drift = creep from where the contact settled (slow slides).
    Returns (worst_m, frame, leg_index). No 'slower foot' exemption (it hid a dragged foot, Codex review #9)."""
    runs = {0: [], 1: []}; worst = (0.0, None, None)

    def judge(k, run):
        nonlocal worst
        if len(run) < 2: return
        ps = [p for _, p in run]; st = [(ps[i] - ps[i - 1]).length for i in range(1, len(ps))]
        drag, i = 0.0, 0
        while i < len(st):
            if st[i] > move:
                j = i
                while j < len(st) and st[j] > move: j += 1
                if j - i >= 3: drag = max(drag, sum(st[i:j]))
                i = j
            else:
                i += 1
        o = 0
        while o < len(st) and st[o] > move: o += 1          # settle after a short landing
        drift = max([(ps[j] - ps[o]).length for j in range(o, len(ps))] or [0.0])
        d = max(drag, drift)
        if d > worst[0]: worst = (d, run[-1][0], k)

    cuts = set(cuts)
    for f in frames:
        sc.frame_set(f); bpy.context.view_layer.update()
        if f in cuts:   # a camera cut may carry an invisible cheat turn: contact runs restart there
            for k in (0, 1): judge(k, [(f_, p_) for f_, p_, _ in runs[k]]); runs[k] = []
        for k, leg in enumerate(ch.legs):
            cs = [leg.matrix_world @ Vector(c) for c in leg.bound_box]
            o = sorted(range(8), key=lambda q: cs[q].z)
            feat = (min(o[0], o[1]), max(o[0], o[1])) if cs[o[1]].z - cs[o[0]].z <= 0.003 else (o[0],)
            p = sum((cs[q] for q in feat), Vector()) / len(feat)
            if p.z - floor_z > contact_tol:
                judge(k, [(f_, p_) for f_, p_, _ in runs[k]]); runs[k] = []; continue
            if runs[k] and runs[k][-1][2] != feat:
                judge(k, [(f_, p_) for f_, p_, _ in runs[k]]); runs[k] = []
            runs[k].append((f, Vector((p.x, p.y)), feat))
    for k in (0, 1): judge(k, [(f, p) for f, p, _ in runs[k]])
    return worst

def idle(sc, ch, f_start, f_end, period_s=3.6, breath=0.012, sway_deg=1.5):
    """Breathing for [f_start, f_end]: torso height scales by `breath` (fraction, bottom fixed), shoulders and head rise with
    the chest, arms rock +-sway_deg about X. One key per frame; at f_start + k*period the pose repeats exactly."""
    fps = sc.render.fps / sc.render.fps_base
    base = dict(ts=ch.torso.location.z, sh=[o.location.z for o in ch.shoulders], hd=ch.head.location.z)
    for f in range(f_start, f_end + 1):
        ph = 2 * math.pi * (f - f_start) / (period_s * fps)
        a = math.sin(ph); b = breath * (0.5 - 0.5 * math.cos(ph))
        ch.torso.scale.z = 1 + b; ch.torso.location.z = base['ts'] + b * S   # half of the 1 m torso height: bottom stays put
        ch.head.location.z = base['hd'] + b * 2 * S
        for o, z0 in zip(ch.shoulders, base['sh']):
            o.location.z = z0 + b * 2 * S; o.rotation_euler.x = math.radians(sway_deg) * a
        for o in (ch.torso, ch.head): o.keyframe_insert('location', frame=f)
        ch.torso.keyframe_insert('scale', frame=f)
        for o in ch.shoulders: o.keyframe_insert('location', frame=f); o.keyframe_insert('rotation_euler', frame=f)


# ---------------------------------------------------------------- sit / stand
def _sm(x):
    x = min(max(x, 0.0), 1.0); return x * x * (3 - 2 * x)


def _sit_state(u, seat_xy, seat_z, yaw, back_studs, floor_z, hop_m=0.35 * S, entry_xy=None):
    """u=0 standing 'back_studs' in front of the seat (heading yaw), u=1 seated. Roblox-style HOP: the legs swing up while
    the body pops up and backs onto the seat, so the feet leave the floor at once (the old version dragged the sole edge
    along the floor as the legs rose: 49 cm foot slide, R127). Returns (xy, root_z, leg_angle_rad)."""
    fwd = np.array([math.sin(yaw), -math.cos(yaw)]); seat = np.asarray(seat_xy, float)
    appr = seat + fwd * back_studs * S if entry_xy is None else np.asarray(entry_xy, float)
    high = seat_z + SOLE_Y > floor_z + LEG
    xy = appr + (seat - appr) * _sm((u - (.35 if high else .1)) / (.55 if high else .7))
    th = math.radians(90) * _sm(u / 0.55)                                 # legs swing up fast ...
    d = float(np.dot(xy - seat, fwd))                                     # ... but the feet never reach further forward than
    if not high and LEG * math.sin(th) + SOLE_Y * math.cos(th) > LEG - d + 1e-9:
        th = max(0.0, math.asin(max(0.0, min(1.0, (LEG - d) / math.hypot(LEG, SOLE_Y)))) - math.atan2(SOLE_Y, LEG))
    # Clear a high mattress vertically before backing over its edge (reverse on standing).
    hip = (floor_z + LEG) + ((seat_z + SOLE_Y) - (floor_z + LEG)) * _sm(u / .4 if high else (u - .25) / .6)
    hop = hop_m * math.sin(math.pi * min(1.0, u / 0.8))
    a = -th   # lowest point of the rotated leg box must stay above the floor
    low = min(y * math.sin(a) + z * math.cos(a) for y in (-SOLE_Y, SOLE_Y) for z in (0, -LEG))
    return xy, max(hip + hop, floor_z - low + (0.004 if u > 0 else 0.0)) - LEG, th


def _key_sit(ch, f, xy, rz, yaw, th):
    ch.root.location = (xy[0], xy[1], rz); ch.root.rotation_euler = (0, 0, yaw)
    ch.root.keyframe_insert('location', frame=f); ch.root.keyframe_insert('rotation_euler', frame=f)
    for h in ch.hips: h.rotation_euler = (-th, 0, 0); h.keyframe_insert('rotation_euler', frame=f)


def sit_down(sc, ch, seat_xy, seat_z, yaw_deg, f_start, frames=14, back_studs=2.0, floor_z=0.0, entry_xy=None):
    """Sit on a seat whose top is at seat_z (m), sitter root ends at seat_xy facing yaw_deg: planted steps to the approach
    point (back_studs in front of the seat, facing yaw) if not already there, then a Roblox-style hop onto the seat.
    Seated: hips at seat_z + 0.25 m, thighs horizontal (leg rotation X = -90 deg). Returns the end frame."""
    assert seat_z >= floor_z
    yaw = math.radians(yaw_deg)
    appr, _, _ = _sit_state(0, seat_xy, seat_z, yaw, back_studs, floor_z, entry_xy=entry_xy)
    f0 = step_to(sc, ch, tuple(appr), f_start, goal_yaw=yaw)            # no-op when the planner already put us there
    sc.frame_set(f0); y0 = ch.root.rotation_euler.z
    for j in range(frames + 1):
        xy, rz, th = _sit_state(j / frames, seat_xy, seat_z, yaw, back_studs, floor_z, entry_xy=entry_xy)
        _key_sit(ch, f0 + j, xy, rz, y0, th)
    return f0 + frames


def stand_up(sc, ch, seat_xy, seat_z, yaw_deg, f_start, frames=24, back_studs=2.0, floor_z=0.0, entry_xy=None):
    """Reverse of the sit_down backing phase (same arguments): from seated to standing at the approach point, feet flat
    on floor_z at the end. Returns the end frame."""
    sc.frame_set(f_start); y0 = ch.root.rotation_euler.z
    for j in range(frames + 1):
        xy, rz, th = _sit_state(1 - j / frames, seat_xy, seat_z, math.radians(yaw_deg), back_studs, floor_z, entry_xy=entry_xy)
        _key_sit(ch, f_start + j, xy, rz, y0, th)
    return f_start + frames


def sit_clearance(world, ch, st, entry_xy, frame=0, exempt=(), seated_only=False):
    """Check both hop directions and the seated pose without writing animation keys."""
    import space
    world.sc.frame_set(frame)
    objs = [ch.root] + list(ch.hips)
    saved = [(o.location.copy(), o.rotation_euler.copy()) for o in objs]
    try:
        samples = [1] if seated_only else [1] + sorted({j / n for n in (14, 18) for j in range(n)})
        for u in samples:
            xy, rz, th = _sit_state(u, st['pos'], st['z'], st['yaw'], 0, 0, entry_xy=entry_xy)
            ch.root.location = (*xy, rz); ch.root.rotation_euler = (0, 0, st['yaw'])
            for h in ch.hips: h.rotation_euler = (-th, 0, 0)
            bpy.context.view_layer.update()
            for _, part, piece, depth in world._hits_now(ch, space.TOL, exempt):
                return space.Clearance(depth, piece, part)
            for _, part, piece, depth in world._hits_now(ch, space.TOL, ()):
                if part in ('torso', 'head'):
                    return space.Clearance(depth, piece, part)
            for other in (world.cast.values() if isinstance(world.cast, dict) else world.cast):
                if other is ch: continue
                depth, part, _ = world._actor_now(ch, other)
                if depth > space.TOL: return space.Clearance(depth, other.name, part)
        return space.Clearance()
    finally:
        for o, (loc, rot) in zip(objs, saved): o.location = loc; o.rotation_euler = rot
        bpy.context.view_layer.update(); world.invalidate()


"""USAGE
import sys; sys.path.insert(0, r'<engine folder>'); import locomotion as lo
ch = lo.make_r6_standing('Ann', (0, 0, 0))                      # root origin on the floor, heading yaw 0
info = lo.walk(sc, ch.root, ch.hips, ch.shoulders, [(0, 0), (8, 0), (8, 6)], f_start=1, speed_studs_s=8, stride_deg=30)
# info['f_end'] = last walk frame; legs/arms keyed every frame; info['contact'][i] = (side, 'heel'|'toe') planted at frame 1+i
t = info['f_end'] + 6                                           # lead-out frames blend back to neutral standing
lo.idle(sc, ch, t, t + 48)                                      # breathing loop (period 3.6 s)
e = lo.sit_down(sc, ch, seat_xy=(7, 6), seat_z=0.9, yaw_deg=90, f_start=t + 48, frames=30)
lo.stand_up(sc, ch, seat_xy=(7, 6), seat_z=0.9, yaw_deg=90, f_start=e + 24, frames=24)
"""
