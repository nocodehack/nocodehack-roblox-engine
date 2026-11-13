"""build.py - short.json -> Blender scene -> gates -> one-line report -> render tier.
Run:  blender -b --factory-startup --offline-mode --python-exit-code 1 -P build.py -- shorts/<name>/short.json [--tier draft|look|final|none]
        [--frames a b c ...] [--range a b] [--out DIR]
Times in the JSON are SECONDS; positions are STUDS (x right, y into the room, desk-relative for props with "on").
Field reference: short.schema.md."""
import shutil, random, bpy, sys, json, math, time, os, subprocess, zlib
from pathlib import Path
from mathutils import Vector, Euler, Matrix, Quaternion

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import claude_still as cs, interact as ia, lookat as la, grab as gr, locomotion as lo
import rig, faces, poses, sets, look, camera, assets, space, staging, affordances
import fight
from fight import FIGHT_KEYS, story_beat as fight_beat
import run as runm, release

S = cs.S
ARGS = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
def arg(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


TIER = None   # set from --tier in __main__ (draft builds take shortcuts)
END = 10 ** 6   # a hold 'until the scene end': resolved after the beats (a retime may lengthen the scene, R135 Codex #7)
OWN_TORSO_MAX = space.OWN_TORSO_MAX   # (space.py holds every arm allowance) was 0.12 here: m: an arm may cut its OWN torso this deep (rigid R6 arm corner on a forward reach; spec decision 1)


def F(t, fps):
    return int(round(float(t) * fps))


def yaw_to(src_xy, dst_xy):
    dx, dy = dst_xy[0] - src_xy[0], dst_xy[1] - src_xy[1]
    return math.degrees(math.atan2(dx, -dy))


def fcurves_of(obj):
    """F-curves of an object's action in Blender 5 (slotted actions: action.fcurves no longer exists)."""
    ad = obj.animation_data
    if not ad or not ad.action: return []
    if hasattr(ad.action, 'fcurves'): return list(ad.action.fcurves)
    from bpy_extras import anim_utils
    cb = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
    return list(cb.fcurves) if cb else []


def _rect_pts(cx, cy, yaw, hw, hd):
    c, s_ = math.cos(yaw), math.sin(yaw)
    return [(cx + c * x - s_ * y, cy + s_ * x + c * y) for x, y in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd))]


def _sat_depth(A, B):
    """Penetration depth (m) of two convex 2D polygons (0 = apart): separating-axis test, min overlap over all edge normals."""
    best = 9e9
    for P in (A, B):
        for i in range(len(P)):
            ex, ey = P[(i + 1) % len(P)][0] - P[i][0], P[(i + 1) % len(P)][1] - P[i][1]; L = math.hypot(ex, ey) or 1.0
            nx, ny = -ey / L, ex / L
            a = [nx * x + ny * y for x, y in A]; b = [nx * x + ny * y for x, y in B]
            ov = min(max(a), max(b)) - max(min(a), min(b))
            if ov <= 0: return 0.0
            best = min(best, ov)
    return best


def body_rect(ch, f, sc):
    """Oriented footprint of the R6 body (torso + legs, arms excluded): 2 x 1 studs around the root."""
    sc.frame_set(f); M = ch.root.matrix_world; p = M.translation; yaw = M.to_euler().z
    return _rect_pts(p.x, p.y, yaw, 1.0 * S, 0.5 * S)


def cheat(yaw, deg=25):
    """Film 'cheat to camera': a character facing another turns up to `deg` toward the camera side (-Y, yaw 0) so faces read in
    3/4 instead of profile (essential in narrow sets where no camera fits between them)."""
    d = (0 - yaw + math.pi) % (2 * math.pi) - math.pi
    return yaw + max(-math.radians(deg), min(math.radians(deg), d))


def seat_info(piv):
    """(centre xy m, seat height m, facing yaw rad) of a seat model read from its geometry: the seat is the flat at ~45 % of the
    height; the backrest = the side whose vertices rise above 60 % of the height; the sitter faces away from it."""
    vs = [o.matrix_world @ v.co for o in piv.children_recursive if o.type == 'MESH' for v in o.data.vertices]
    zt = max(v.z for v in vs); zb = min(v.z for v in vs); cx = sum(v.x for v in vs) / len(vs); cy = sum(v.y for v in vs) / len(vs)
    hi = [v for v in vs if v.z > zb + 0.6 * (zt - zb)]
    bx = sum(v.x for v in hi) / len(hi) - cx if hi else 0.0; by = sum(v.y for v in hi) / len(hi) - cy if hi else 1.0
    if math.hypot(bx, by) < 0.03: bx, by = 0.0, 1.0                    # no backrest (stool/bench): face -Y (camera)
    fx, fy = -bx, -by                                                    # face away from the back
    return (cx, cy), zb + 0.45 * (zt - zb), math.atan2(fx, -fy)


def plan_path(start, goal, obstacles, bounds, others=(), half=1.1 * S, cell=0.5 * S, forbid=None):
    """Grid A* (0.5-stud cells, 8-neighbour) from start to goal (metres xy) around solid footprints inflated by the character's
    half-width, inside the room bounds; then line-of-sight smoothing. Returns [start, ..., goal] (straight if already clear)."""
    import heapq
    if forbid is None: forbid = os.environ.get('ROUTE_FORBID', '1') == '1'   # A/B switch (R153 route-length check)
    def free(x, y):
        if math.hypot(x - goal[0], y - goal[1]) < 2.5 * half or math.hypot(x - start[0], y - start[1]) < 2.0 * half:
            # near the ends a route may enter a MARGIN (the approach parks close) but never the furniture itself
            body = 0.62   # m: R6 torso half-width 0.50 + 12 cm for sway/corner yaw (0.52 grazed a fridge on the last leg, R147 lunch; 0.30 cut chair corners, R137)
            # still a PREFERENCE near the ends: blocked cells cost 40x in A*, so a tight goal (desk stand point) stays reachable
            return not any(x0 - body < x < x1 + body and y0 - body < y < y1 + body for x0, x1, y0, y1, *_ in obstacles)
        m = 0.9   # m from walls: body half-width 0.5 + a stepping foot's reach 0.25 (corner step-turns) + 12 cm skirting (R133)
        if bounds and not (bounds[0] + m < x < bounds[1] - m and bounds[2] + m < y < bounds[3] - m): return False
        if any(x0 - half < x < x1 + half and y0 - half < y < y1 + half for x0, x1, y0, y1, *_ in obstacles): return False
        return all(math.hypot(x - ox, y - oy) > 2 * half for ox, oy in others)
    def solid(x, y):   # the root this close to a solid footprint puts the torso (half-depth 0.25 m) + a stepping foot inside it
        if math.hypot(x - start[0], y - start[1]) < 0.3 or math.hypot(x - goal[0], y - goal[1]) < 0.3: return False
        return any(x0 - 0.3 < x < x1 + 0.3 and y0 - 0.3 < y < y1 + 0.3 for x0, x1, y0, y1, *_ in obstacles)
    def wall(x, y):
        return bool(bounds) and not (bounds[0] + 0.3 * half < x < bounds[1] - 0.3 * half and bounds[2] + 0.3 * half < y < bounds[3] - 0.3 * half)
    def clear(a, b):
        n_ = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / (cell * 0.5)))
        return all(free(a[0] + (b[0] - a[0]) * k / n_, a[1] + (b[1] - a[1]) * k / n_) for k in range(1, n_))
    def room(x, y):   # m of room around a route point: 9 = free, else the distance to the nearest footprint / wall / character
        if free(x, y): return 9.0
        d = min((max(x0 - x, x - x1, y0 - y, y - y1) for x0, x1, y0, y1, *_ in obstacles), default=9.0)
        if bounds: d = min(d, x - bounds[0], bounds[1] - x, y - bounds[2], bounds[3] - y)
        return max(0.0, min([d] + [math.hypot(x - ox, y - oy) - half for ox, oy in others]))
    def no_worse(pr_, pts_, i, j):   # a shortcut through a MARGIN is fine when it has as much room as the grid path it replaces: a
        thr = min(pr_[i:j + 1])     # tight aisle came out as a 0.25 m staircase the walk keyer cannot walk (R228 librarian, 12 turns)
        if thr >= 9.0: return False   # an all-free stretch: clear() has already answered
        a, b = pts_[i], pts_[j]
        n_ = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / (cell * 0.5)))
        mid = ((a[0] + (b[0] - a[0]) * k / n_, a[1] + (b[1] - a[1]) * k / n_) for k in range(1, n_))
        return all(room(*m) >= thr - 1e-6 and not (forbid and solid(*m)) for m in mid)
    if clear(start, goal): return [start, goal]
    ox_, oy_ = start
    key = lambda x, y: (round((x - ox_) / cell), round((y - oy_) / cell))
    pos = lambda k: (ox_ + k[0] * cell, oy_ + k[1] * cell)
    g_k = key(*goal); s_k = (0, 0)
    openq = [(0.0, s_k)]; came = {s_k: None}; cost = {s_k: 0.0}
    while openq:
        _, k = heapq.heappop(openq)
        if k == g_k or (math.hypot(*(a - b for a, b in zip(pos(k), goal))) < cell and clear(pos(k), goal)): g_k = k; break
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not (dx or dy): continue
                nk = (k[0] + dx, k[1] + dy); p_ = pos(nk)
                if abs(nk[0]) > 400 or abs(nk[1]) > 400 or wall(*p_): continue
                if forbid and nk != g_k and solid(*p_): continue          # a body INSIDE furniture is forbidden (only margins are costly):
                # the 40x 'cost' let a sofa side-approach walk straight through the coffee table (R149 snack s03, Codex R146 #1)
                # margins are costly, not forbidden - and costlier the closer to the furniture, so a route keeps to the middle of an aisle
                c = cost[k] + math.hypot(dx, dy) * (1.0 if (free(*p_) or nk == g_k) else 40.0 + 80.0 * max(0.0, 1 - room(*p_) / half))
                if c < cost.get(nk, 1e9):
                    cost[nk] = c; came[nk] = k
                    heapq.heappush(openq, (c + math.hypot(p_[0] - goal[0], p_[1] - goal[1]) / cell, nk))
    if g_k not in came:
        if forbid:   # no route outside the furniture: the old costly-but-allowed search beats a straight line through everything
            print('ROUTE tight: no fully clear route, allowing costly cells', [round(v / S, 1) for v in start], '->', [round(v / S, 1) for v in goal])
            return plan_path(start, goal, obstacles, bounds, others, half, cell, forbid=False)
        print('ROUTE FAIL', [round(v / S, 1) for v in start], '->', [round(v / S, 1) for v in goal]); return [start, goal]
    pts = []; k = g_k
    while k is not None: pts.append(pos(k)); k = came[k]
    pts = [start] + pts[::-1][1:-1] + [goal]
    proom = [room(*q) for q in pts]
    out = [pts[0]]; i = 0                                # line-of-sight smoothing
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not (clear(pts[i], pts[j]) or no_worse(proom, pts, i, j)): j -= 1
        out.append(pts[j]); i = j
    return out


def floor_pocket(obstacles, bounds, cell=0.25, max_m2=4.0):
    """-> pocket(xy): is this spot in a small dead-end pocket of floor (under max_m2, cut off from the main floor by furniture a
    forward-walking body cannot pass)? Floor = grid cells at least 0.3 m (the route planner's 'solid' margin) from every footprint
    and wall. A start moved off furniture landed in such pockets (between two chairs, behind the teacher's desk) and every walk
    out of them was rejected (R228 teacher s02, librarian)."""
    if not bounds: return lambda xy: False
    nx, ny = int((bounds[1] - bounds[0]) / cell) + 1, int((bounds[3] - bounds[2]) / cell) + 1
    def ok(i, j):
        x, y = bounds[0] + i * cell, bounds[2] + j * cell
        return bounds[0] + 0.3 < x < bounds[1] - 0.3 and bounds[2] + 0.3 < y < bounds[3] - 0.3 and not any(
            o[0] - 0.3 < x < o[1] + 0.3 and o[2] - 0.3 < y < o[3] + 0.3 for o in obstacles if len(o) < 5 or o[4] >= 0.2)
    comp = {}; sizes = []
    for i in range(nx):
        for j in range(ny):
            if (i, j) in comp or not ok(i, j): continue
            k = len(sizes); todo = [(i, j)]; comp[(i, j)] = k; n_ = 0
            while todo:
                a, b = todo.pop(); n_ += 1
                for c in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
                    if 0 <= c[0] < nx and 0 <= c[1] < ny and c not in comp and ok(*c): comp[c] = k; todo.append(c)
            sizes.append(n_)
    if not sizes: return lambda xy: False
    main = max(range(len(sizes)), key=sizes.__getitem__)
    def pocket(xy):
        i, j = round((xy[0] - bounds[0]) / cell), round((xy[1] - bounds[2]) / cell)
        ks = {comp[c] for c in ((i + a, j + b) for a in (-1, 0, 1) for b in (-1, 0, 1)) if c in comp}
        return main not in ks and all(sizes[k] * cell * cell < max_m2 for k in ks)
    return pocket


def tight_spans(route, obstacles, step=0.05):
    """Split a route into [(points, sideways)]: `sideways` where the body walking FORWARD (1.0 m across the path) would overlap a
    furniture footprint but the body turned side-on (0.5 m across) would not - an aisle to side-step through, like a person
    between a chair and a wall. Each sideways stretch is grown to the nearest spots with room to turn the body."""
    solid = [o for o in obstacles if len(o) < 5 or o[4] >= 0.2]   # space.World steps over anything lower (rugs, curbs)
    def hit(x, y, yaw, hw, hd):
        B = None
        for o in solid:
            if not (o[0] - 0.7 < x < o[1] + 0.7 and o[2] - 0.7 < y < o[3] + 0.7): continue
            B = B or _rect_pts(x, y, yaw, hw, hd)
            if _sat_depth(B, [(o[0], o[2]), (o[1], o[2]), (o[1], o[3]), (o[0], o[3])]) > 0: return True
        return False
    sam = []   # (arc length, x, y, forward-blocked-but-sideways-free, room to turn, heading)
    s0 = 0.0
    for a, b in zip(route, route[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 1e-6: continue
        yaw = math.atan2(b[0] - a[0], -(b[1] - a[1])); n_ = max(1, math.ceil(L / step))
        for k in range(n_ + 1):
            x, y = a[0] + (b[0] - a[0]) * k / n_, a[1] + (b[1] - a[1]) * k / n_
            fwd = hit(x, y, yaw, 0.53, 0.25)
            nx, ny = math.cos(yaw), math.sin(yaw)   # side-on fits somewhere within 0.3 m to either side (aisle() centres it later)
            sam.append((s0 + L * k / n_, x, y, fwd and any(not hit(x + nx * d, y + ny * d, yaw + math.pi / 2, 0.5, 0.25) for d in (0, .1, -.1, .2, -.2, .3, -.3)),
                        not fwd and not hit(x, y, yaw + math.pi / 4, 0.53, 0.28) and not hit(x, y, yaw - math.pi / 4, 0.53, 0.28), yaw))
        s0 += L
    if not any(t[3] for t in sam): return [(list(route), False)]
    spans = []; i = 0   # [first sample with room to turn, last one, first pinched sample, last pinched sample]
    while i < len(sam):
        if not sam[i][3]: i += 1; continue
        j = i
        while j + 1 < len(sam) and (sam[j + 1][3] or any(t[3] for t in sam[j + 1:j + 13])): j += 1   # pinches < 0.6 m apart: one stretch
        a_ = i
        while a_ > 0 and not sam[a_][4] and sam[i][0] - sam[a_][0] < 1.0: a_ -= 1     # back to a spot with room to turn side-on
        b_ = j
        while b_ < len(sam) - 1 and not sam[b_][4] and sam[b_][0] - sam[j][0] < 1.0: b_ += 1
        if spans and a_ <= spans[-1][1]: spans[-1][1] = b_; spans[-1][3] = j
        else: spans.append([a_, b_, i, j])
        i = b_ + 1
    cum = [0.0]
    for a, b in zip(route, route[1:]): cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    def aisle(i, j):   # heading of the pinched stretch, and its samples moved to the MIDDLE of the aisle: a 0.5 m body in a
        # 0.63 m gap must be centred to 5 cm and the route grid is 0.25 m. Measured with the side-on body's whole 1 m length, 1 cm
        # at a time to each side; 0.35 m off a single near side.
        dx, dy = sam[j][1] - sam[i][1], sam[j][2] - sam[i][2]
        ya = math.atan2(dx, -dy) if math.hypot(dx, dy) > 0.3 else sam[i][5]
        q_ = round(ya / (math.pi / 2)) * math.pi / 2   # footprints are axis-aligned rects, so their aisles are too
        if abs(ya - q_) < 0.45: ya = q_
        nx, ny = math.cos(ya), math.sin(ya); pts = []
        def gap(x, y, sg):   # m from the body's long axis to the first footprint on side sg (None beyond 0.7): 5 cm, then 1 cm steps
            q = next((q for q in range(5, 75, 5) if hit(x + sg * nx * q * 0.01, y + sg * ny * q * 0.01, ya + math.pi / 2, 0.5, 0.005)), None)
            return q and next(q_ * 0.01 for q_ in range(q - 4, q + 1) if hit(x + sg * nx * q_ * 0.01, y + sg * ny * q_ * 0.01, ya + math.pi / 2, 0.5, 0.005))
        for k in sorted(set(list(range(i, j, 3)) + [j])):
            x, y = sam[k][1], sam[k][2]
            l_, r_ = gap(x, y, 1), gap(x, y, -1)
            d = (l_ - r_) / 2 if l_ and r_ else -max(0.0, 0.35 - l_) if l_ else max(0.0, 0.35 - r_) if r_ else 0.0
            pts.append((x + nx * d, y + ny * d))
        return (nx, ny), pts
    def onto(p_, c_, n_):   # p_ moved sideways (along the aisle normal n_) onto the aisle line through c_: the body lines up with
        d = (c_[0] - p_[0]) * n_[0] + (c_[1] - p_[1]) * n_[1]   # the aisle BEFORE it moves into it (a diagonal entry clipped the
        return (p_[0] + n_[0] * d, p_[1] + n_[1] * d)           # chair corner with the body's leading end)
    def cut(sa, sb):   # the route between two arc lengths
        pts = [next((t[1], t[2]) for t in sam if t[0] >= sa - 1e-9)]
        pts += [p_ for p_, c_ in zip(route, cum) if sa + 0.05 < c_ < sb - 0.05]
        pts.append(next((t[1], t[2]) for t in reversed(sam) if t[0] <= sb + 1e-9))
        return pts
    def thin(pts):   # drop points within 1 cm of the line between their neighbours (fewer, longer side-step legs)
        if len(pts) < 3: return pts
        (ax, ay), (bx, by) = pts[0], pts[-1]; L = math.hypot(bx - ax, by - ay) or 1e-9
        d = [abs((bx - ax) * (ay - y) - (ax - x) * (by - ay)) / L for x, y in pts[1:-1]]
        k = max(range(len(d)), key=d.__getitem__) + 1
        return [pts[0], pts[-1]] if d[k - 1] < 0.01 else thin(pts[:k + 1])[:-1] + thin(pts[k:])
    out = []; s_prev = 0.0
    for a_, b_, i, j in spans:
        if sam[a_][0] - s_prev > 0.3: out.append((cut(s_prev, sam[a_][0]), False))    # a shorter forward stub joins the side-step
        else: a_ = next(k for k, t in enumerate(sam) if t[0] >= s_prev - 1e-9)
        s_end = sam[b_][0] if cum[-1] - sam[b_][0] > 0.3 else cum[-1]
        n_, mid = aisle(i, j); ent, ext = cut(sam[a_][0], s_end)[0], cut(sam[a_][0], s_end)[-1]
        pts = [ent, onto(ent, mid[0], n_)] + mid + [onto(ext, mid[-1], n_), ext]
        keep = [pts[0]]   # no baby steps: points under 12 cm from the last kept one go (the exit itself always stays)
        for q in pts[1:-1]:
            if math.dist(q, keep[-1]) > 0.12 and math.dist(q, pts[-1]) > 0.12: keep.append(q)
        pts = thin(keep + [pts[-1]]) if math.dist(keep[-1], pts[-1]) > 0.02 else thin(keep)
        out.append((pts if len(pts) > 1 else [ent, ext], True)); s_prev = s_end
    if cum[-1] - s_prev > 1e-6: out.append((cut(s_prev, cum[-1]), False))
    return out


def hold_in_hand(piv, side, pr):
    """Roblox tool grip: the held prop sits just PAST the hand end along the arm (not centred inside the arm block)."""
    bpy.context.view_layer.update()
    tip = piv.matrix_world @ gr._hand_local(side, None)
    down = (piv.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()          # along the arm toward the hand
    c_, r_, top_ = prop_cyl(pr); base_z = pr.matrix_world.translation.z; half = max(r_, (top_ - base_z) / 2)
    ctr = tip   # R94 placement (forward/past-the-hand offsets regressed handoffs; revisit with handoff tests)
    pr.location = (ctr.x, ctr.y, ctr.z - (top_ - base_z) / 2)


def give_stops(world, ch, start, target, frame, st, speed, fps):
    """Rank clear handoff routes before paying for at most two keyed walks."""
    candidates = []
    bounds = st.get('bounds')
    others = [tuple(c.root.matrix_world.translation.xy) for c in world.cast.values() if c is not ch]
    for deg in range(0, 360, 30):
        for radius in (staging.d('walk_up_stop'), staging.d('walk_up_stop') + .4 * S):
            p = (target[0] + radius * math.cos(math.radians(deg)), target[1] + radius * math.sin(math.radians(deg)))
            if bounds and not (bounds[0] + .6 < p[0] < bounds[1] - .6 and bounds[2] + .6 < p[1] < bounds[3] - .6): continue
            if any(q['solid'] and any(q['rect'][0] < p[0] + (target[0] - p[0]) * t < q['rect'][1] and
                                     q['rect'][2] < p[1] + (target[1] - p[1]) * t < q['rect'][3]
                                     for t in (i / 10 for i in range(1, 10))) for q in assets.PLACED): continue
            facing = math.atan2(target[0] - p[0], -(target[1] - p[1]))
            if world.query(ch, p, facing, frame).depth_m: continue
            route = plan_path(start, p, st.get('obstacles', []), bounds, others, half=.7)
            seconds = sum(math.dist(a, b) for a, b in zip(route, route[1:])) / (speed * S) + .25 * (len(route) - 2) + .75
            poses_ = [(start, ch.root.rotation_euler.z)]
            for a, b in zip(route, route[1:]):
                yaw = math.atan2(b[0] - a[0], -(b[1] - a[1]))
                poses_ += [(a, yaw), (b, yaw)]
            poses_.append((p, facing))
            if world.sweep(ch, poses_, frame=frame).depth_m: continue
            if world.query(ch, p, facing, frame + F(seconds, fps)).depth_m: continue
            candidates.append((seconds > 6, seconds, route))
    return [route for _, _, route in sorted(candidates)[:2]]


def hold_window(grabs, pr, f0, f1):
    """Reaching contact precedes acquisition; only a transfer has a departing-hand contact tail."""
    handed = any(pp is pr and a0 in (f1, f1 + 1) for _, _, pp, a0, _ in grabs)
    return f0 - 6, f1 + (6 if handed else 0)


def drop_prop(sc, pr, f_rel, n, fps, log):
    """Released prop falls straight down (g) onto the highest support under it (set piece top or floor), turns upright on the way,
    one small bounce, then rests. Keys location/rotation from f_rel+1."""
    sc.frame_set(f_rel); bpy.context.view_layer.update()
    p0 = pr.matrix_world.translation.copy(); r0 = pr.rotation_euler.copy()
    base = min((o.matrix_world @ Vector(cc)).z for o in pr.children_recursive if o.type == 'MESH' for cc in o.bound_box) - p0.z
    land = max([0.0] + [q['top'] for q in assets.PLACED if q['solid'] and q['rect'][0] < p0.x < q['rect'][1]
                        and q['rect'][2] < p0.y < q['rect'][3] and q['top'] < p0.z + base + 0.01])
    h = max(0.0, p0.z + base - land); g = 9.81
    t1 = math.sqrt(2 * h / g) if h > 0.01 else 0.0; t2 = 2 * math.sqrt(2 * 0.12 * h / g)   # fall, then a bounce of 12 % height
    f_end = min(n - 1, f_rel + int((t1 + t2) * fps) + 3)
    for f in range(f_rel + 1, f_end + 1):
        t = (f - f_rel) / fps
        if t <= t1: z = p0.z - 0.5 * g * t * t
        elif t <= t1 + t2: tb = t - t1; z = (p0.z - h) + (math.sqrt(2 * g * 0.12 * h) * tb - 0.5 * g * tb * tb)
        else: z = p0.z - h
        k = min(1.0, t / max(t1, 1e-3))
        pr.location = (p0.x, p0.y, max(z, p0.z - h)); pr.rotation_euler = (r0.x * (1 - k), r0.y * (1 - k), r0.z)
        pr.keyframe_insert('location', frame=f); pr.keyframe_insert('rotation_euler', frame=f)
    log.setdefault('notes', []).append(f'{pr.name} released f{f_rel}, dropped {h:.2f} m')


def grab_geom(pr):
    """How a hand grabs this prop: (centre xy, radius, z_lo, z_hi, standoff). Flat props (< 0.3 m tall: cookie, phone, book) are
    grabbed from ON TOP near the middle (reads as a grab); taller ones on the rim/side just under the top."""
    c, rad, top = prop_cyl(pr)
    base_z = min((o.matrix_world @ Vector(cc)).z for o in pr.children_recursive if o.type == 'MESH' for cc in o.bound_box)
    if top - base_z < 0.3: return c, rad * 0.35, top + 0.18, top + 0.26, False   # arm block is 1 stud thick: its lower edge ~0.2 m under the hand point
    return c, rad, top - 0.12, top + 0.03, True


def prop_cyl(pr):
    """(centre xy, rim radius, top z) of a prop from its mesh bounds, world metres."""
    pts = [o.matrix_world @ Vector(c) for o in pr.children_recursive if o.type == 'MESH' for c in o.bound_box]
    c0 = pr.matrix_world.translation
    return (c0.x, c0.y), max(math.hypot(p.x - c0.x, p.y - c0.y) for p in pts), max(p.z for p in pts)


def approach_spot(ch, hand, c, rad, z, obstacles, others, bounds, start_xy, zr=None, accept=None):
    """Where to stand (xy, yaw rad) so the rigid R6 arm `hand` lands on a rim (centre c, radius rad, height z) at arm's length,
    the body footprint stays clear of desk rects / other characters / walls, nearest to start_xy. None if nowhere fits."""
    bpy.context.view_layer.update()
    L0 = ch.root.matrix_world.inverted() @ ch.arm[hand].matrix_world.translation      # shoulder pivot in root space (m)
    Hp = Vector((0, 0, 2.0 * S))                                                        # upper-body pivot (hips)
    reach = math.hypot(ia.TIP, 0.5) * S; r = rad + ia.LIMB_HALF
    best = None
    zr = zr or (z, z)
    # lean forward from the hips: reach across tables (rotation +X tips the top toward -Y); 45-70 deg = bend DOWN to a low or
    # floor prop (a ground ball sits 1.3 m under the shoulder at 30 deg: unreachable, R146 Codex #2). Upright first.
    for lean in (0, 10, 20, 30, 45, 60, 70):
        if best is not None and lean > 30 and best[3] <= 30: break                       # a shallow lean already works
        th = math.radians(lean); v = L0 - Hp
        L = Hp + Vector((v.x, v.y * math.cos(th) - v.z * math.sin(th), v.y * math.sin(th) + v.z * math.cos(th)))
        candidates = [] if accept is not None else None
        best = _spot_search(L, c, r, zr, reach, obstacles, others, bounds, start_xy, lean, best, candidates)
        if accept is not None:
            seen, coarse, fine = set(), [], []
            for candidate in sorted(candidates):
                _, xy, yaw, _ = candidate
                cell = (round(xy[0] / .25), round(xy[1] / .25), round(yaw / math.radians(30)))
                (fine if cell in seen else coarse).append(candidate); seen.add(cell)
            for _, xy, yaw, bend in coarse + fine:
                if accept(xy, yaw, bend): return xy, yaw, bend
            best = None
        if best is not None and lean == 0: break                                         # no lean needed
    if best is None:
        near = [tuple(round(v / S, 1) for v in o[:4]) for o in obstacles if o[0] - 3 < c[0] < o[1] + 3 and o[2] - 3 < c[1] < o[3] + 3]
        print('APPROACH FAIL', ch.name, 'target studs', round(c[0] / S, 1), round(c[1] / S, 1), 'rad', round(rad / S, 2), 'z', round(z / S, 2),
              'reasons', dict(REJ), 'near obstacles (studs)', near)
    return None if best is None else (best[1], best[2], best[3])


REJ = {}


def _spot_search(L, c, r, zr, reach, obstacles, others, bounds, start_xy, lean, best, candidates=None):
    for ai in range(0, 360, 10):
        a = math.radians(ai)
        for k in range(4, 41):
            d = k * 0.1 * S
            x, y = c[0] + d * math.cos(a), c[1] + d * math.sin(a)
            base = math.atan2(c[0] - x, -(c[1] - y))                  # yaw that faces the prop (forward = local -Y)
            for off in range(-60, 61, 10):
                yaw = base + math.radians(off); cy, sy = math.cos(yaw), math.sin(yaw)
                px, py = x + cy * L.x - sy * L.y, y + sy * L.x + cy * L.y
                # rim at arm's length for SOME height of the contact band zr (not only its midpoint); the 3-axis shoulder
                # (interact.solve_tip) reaches level and sideways targets, so the old 2-axis 'level' veto is gone (R146 Codex #1)
                hmin = abs(math.hypot(px - c[0], py - c[1]) - r)
                dz_lo = 0.0 if zr[0] <= L.z <= zr[1] else min(abs(L.z - zr[0]), abs(L.z - zr[1])); dz_hi = max(abs(L.z - zr[0]), abs(L.z - zr[1]))
                # 2 cm: STRICTER than interact.touch's 3 cm (4 cm here let 3.2-3.9 cm misses through once the level veto was gone, R149)
                if not (math.hypot(hmin, dz_lo) - 0.02 <= reach <= math.hypot(hmin, dz_hi) + 0.02): REJ['reach'] = REJ.get('reach', 0) + 1; continue
                fx, fy = sy, -cy                                          # forward vector
                if (c[0] - px) * fx + (c[1] - py) * fy <= 0: REJ['behind'] = REJ.get('behind', 0) + 1; continue
                ok = True
                for u in (-2.0, -1.0, 0.0, 1.0, 2.0):                    # footprint 4 x 1.2 studs (arms included)
                    for v in (-0.6, 0.0, 0.6):
                        qx, qy = x + (cy * u - sy * v) * S, y + (sy * u + cy * v) * S
                        if bounds and not (bounds[0] + 0.1 < qx < bounds[1] - 0.1 and bounds[2] + 0.1 < qy < bounds[3] - 0.1): ok = False
                        if any(x0 - 0.04 < qx < x1 + 0.04 and y0 - 0.04 < qy < y1 + 0.04 for x0, x1, y0, y1, _ in obstacles): ok = False
                        if any(math.hypot(qx - ox, qy - oy) < 1.2 * S for ox, oy in others): ok = False
                if ok and lean:   # the LEANING upper body sweeps forward (head ~1.5 m up the body): it must clear the others too
                    # (Zed's 60 deg bend to a ground ball put his head 49 cm into Lia's torso, R147 park); furniture may be leaned over
                    for fd in (0.5, 1.0, 1.5):
                        reachf = fd * math.sin(math.radians(lean)); qx, qy = x + sy * reachf, y - cy * reachf
                        if any(math.hypot(qx - ox, qy - oy) < 1.0 * S for ox, oy in others): ok = False
                if not ok: REJ['blocked'] = REJ.get('blocked', 0) + 1; continue
                score = math.hypot(x - start_xy[0], y - start_xy[1]) + 0.2 * abs(off) / 60 + 0.03 * lean
                if candidates is not None: candidates.append((score, (x, y), yaw, lean))
                if best is None or score < best[0]: best = (score, (x, y), yaw, lean)
    return best


HELD_PROPS = set()
THROWS = []   # throw beats: {'prop', 'f_rel', 'f_end', 'kind': catch|land|hit_char|hit_prop, ...}; the flight is keyed by bake_props


def land_top(x, y, below_z):
    """Height (m) of the highest solid set-piece top under (x, y) that lies below below_z; the floor (0) when there is none."""
    return max([0.0] + [q['top'] for q in assets.PLACED if q['solid'] and q['rect'][0] < x < q['rect'][1]
                        and q['rect'][2] < y < q['rect'][3] and q['top'] < below_z + 0.01])


def throw_bake(sc, th, n, fps, log):
    """Key a thrown prop from the release (its pose in the thrower's hand at th['f_rel'], already baked) to its end:
    catch = exactly into the catcher's hand at f_end (the catcher's hold is baked from there); land = onto the floor / piece
    top at the target, one bounce; hit_char = to the target's chest, drops in front of them; hit_prop = to the target prop,
    which is knocked off its support and tips over, the thrown prop drops under the hit."""
    pr = th['prop']; f0, f1 = th['f_rel'], min(th['f_end'], n - 1)
    ms = [o for o in pr.children_recursive if o.type == 'MESH']
    sc.frame_set(f0); bpy.context.view_layer.update()
    p0 = pr.matrix_world.translation.copy()
    zs = [(o.matrix_world @ Vector(c)).z for o in ms for c in o.bound_box]; base, half = min(zs) - p0.z, (max(zs) - min(zs)) / 2
    if th['kind'] != 'catch':   # it comes to rest UPRIGHT (release.fall eases the tilt out): measure the bottom in that pose - a held (tilted) ball's bounds
        rot0 = pr.rotation_euler.copy(); pr.rotation_euler = (0.0, 0.0, rot0.z); bpy.context.view_layer.update()   # hovered it 0.4 m above the floor
        zs = [(o.matrix_world @ Vector(c)).z for o in ms for c in o.bound_box]; base, half = min(zs) - p0.z, (max(zs) - min(zs)) / 2
        pr.rotation_euler = rot0
    sc.frame_set(f1); bpy.context.view_layer.update()
    if th['kind'] == 'catch':
        piv, side = th['catcher']; tip = piv.matrix_world @ gr._hand_local(side, None)
        p1 = Vector((tip.x, tip.y, tip.z - base - half))          # the prop's middle on the hand point (hold_in_hand)
        release.arc(pr, f0, f1, p0, p1, fps)
        return
    if th['kind'] == 'hit_char':
        tor = th['target'].torso.matrix_world.translation; d = (p0.xy - tor.xy).normalized()
        p1 = Vector((tor.x + d.x * (0.27 + th['rad']), tor.y + d.y * (0.27 + th['rad']), tor.z - base - half))
    elif th['kind'] == 'hit_prop':
        tp = th['target']; tms = [o for o in tp.children_recursive if o.type == 'MESH']
        pts = [o.matrix_world @ Vector(c) for o in tms for c in o.bound_box]; c = sum(pts, Vector()) / len(pts)
        d = (p0.xy - c.xy).normalized(); trad = max((q.xy - c.xy).length for q in pts) * 0.7
        p1 = Vector((c.x + d.x * (trad + th['rad']), c.y + d.y * (trad + th['rad']), c.z - base - half))
    else:
        x, y = th['xy']; p1 = Vector((x, y, land_top(x, y, p0.z + 5.0) - base))
    v = release.arc(pr, f0, f1, p0, p1, fps)
    if th['kind'] == 'land':
        on_piece = p1.z + base > 0.02   # shortcut: a prop landing on a piece top stays put (no roll off its edge)
        v2 = Vector((0, 0, -0.35 * v.z)) if on_piece else Vector((0.35 * v.x, 0.35 * v.y, -0.4 * v.z))
        release.fall(pr, f1, p1, v2, p1.z, n - 1, fps)
        return
    # an impact: the thrown prop loses its speed, pops back a little and drops under the hit
    back = Vector((-0.12 * v.x, -0.12 * v.y, 0.8))
    release.fall(pr, f1, p1, back, land_top(p1.x, p1.y, p1.z + base) - base, n - 1, fps)
    if th['kind'] == 'hit_prop':
        tp = th['target']; tp.animation_data_clear(); tp.location, tp.rotation_euler = th['rest'][0].copy(), th['rest'][1].copy()
        bpy.context.view_layer.update()
        t0 = tp.location.copy(); push = Vector((0.45 * v.x, 0.45 * v.y, 1.2))
        tb = min((o.matrix_world @ Vector(c)).z for o in tp.children_recursive if o.type == 'MESH' for c in o.bound_box) - t0.z
        tp.keyframe_insert('location', frame=f1); tp.keyframe_insert('rotation_euler', frame=f1)
        Tf = (push.z + (push.z ** 2 + 2 * 9.81 * max(0.0, t0.z)) ** 0.5) / 9.81   # flight time to the floor
        lx, ly = t0.x + push.x * Tf, t0.y + push.y * Tf
        z_rest = land_top(lx, ly, t0.z + tb + 0.02) - tb
        fe, _ = release.fall(tp, f1, t0, push, z_rest, n - 1, fps, upright=False)
        # it tips over as it goes (about the horizontal axis across the throw direction) and stays lying
        ax = math.atan2(v.y, v.x); k = fe - f1
        for i in range(1, k + 1):
            u = min(1.0, i / max(1, k - 1)); a = math.radians(90) * u
            tp.rotation_euler = (th['rest'][1].x + a * math.sin(ax) * -1, th['rest'][1].y + a * math.cos(ax), th['rest'][1].z)
            tp.keyframe_insert('rotation_euler', frame=f1 + i)
CONTACT_POSES = {   # pose -> (hand(s), face-local target: x across (+ = char's left), z from head centre (+ up), in head half-sizes)
    'facepalm_R': (('R',), -0.5, 0.35), 'facepalm_L': (('L',), 0.5, 0.35),
    'think_R': (('R',), 0.05, -0.55), 'think_L': (('L',), -0.05, -0.55),
    'cover_mouth_R': (('R',), -0.35, -0.3), 'cover_mouth_L': (('L',), 0.35, -0.3),
    'hands_head': (('R', 'L'), None, 0.55),
}


def clear_keys(objs, f0, f1):
    """Remove every keyframe of these objects in [f0, f1] (undo a move that failed its clearance check)."""
    for o in objs:
        for fc in space.fcurves_of(o):
            idx = [i for i, k in enumerate(fc.keyframe_points) if f0 - 0.5 <= k.co.x <= f1 + 0.5]
            for i in reversed(idx): fc.keyframe_points.remove(fc.keyframe_points[i])   # by index, last first (held refs go stale)
            fc.update()


def motion_trial(sc, world, ch, key, f0, hold_until, spans=(), commit=True):
    """Accept a keyed move only when its whole motion and stopped hold clear; otherwise restore all actions."""
    objs = [ch.root] + list(ch.root.children_recursive)
    saved = [(o, o.animation_data.action if o.animation_data else None, o.location.copy(), o.rotation_euler.copy(), o.scale.copy()) for o in objs]
    contacts = {k: dict(v) for k, v in ia.CONTACTS.items()}; last_pose = dict(ia.LAST_POSE)
    accepted = False
    try:
        for o, action, *_ in saved:
            if action is not None: o.animation_data.action = action.copy()
        end = key(); world.invalidate()
        seat = lambda fr: {sp[3] for sp in spans if sp[0] == ch.name and sp[1] <= fr <= sp[2]}
        first, stop = max(0, f0), max(end, hold_until)
        # Reject occupied stops cheaply; keep the first 24 frames first for the walk's launch/goal fallback choice.
        lead_end = min(stop + 1, first + 24)
        samples = list(dict.fromkeys(fr for fr in (stop, end) if lead_end <= fr <= stop))
        hit = world.motion_hit(ch, range(first, lead_end), seat)
        if hit is None: hit = world.motion_hit(ch, samples, seat)
        if hit is None: hit = world.motion_hit(ch, (fr for fr in range(lead_end, stop + 1) if fr not in samples), seat)
        if hit and os.environ.get('WALK_DEBUG'): sc.frame_set(hit[0]); print('HITPOSE', hit[:3], [round(v, 2) for v in ch.root.matrix_world.translation[:2]], round(math.degrees(ch.root.matrix_world.to_euler().z)), {c_.name: [round(v, 2) for v in c_.root.matrix_world.translation[:2]] for c_ in world.cast.values() if c_ is not ch}, 'heads', {c_.name: [round(v, 2) for v in c_.head_mesh.matrix_world.translation] + [round(math.degrees(v)) for v in c_.root.matrix_world.to_euler()] for c_ in world.cast.values()})
        accepted = hit is None
        return (end if accepted else None), hit
    except (AssertionError, ValueError) as e:
        return None, (f0, ch.name, str(e), 0.0)
    finally:
        for o, action, loc, rot, scale in saved:
            trial = o.animation_data.action if o.animation_data else None
            if not accepted or not commit:
                if o.animation_data: o.animation_data.action = action
                o.location, o.rotation_euler, o.scale = loc, rot, scale
                if trial is not None and trial is not action and trial.users == 0: bpy.data.actions.remove(trial)
            elif action is not None and action.users == 0:
                bpy.data.actions.remove(action)
        if not accepted or not commit:
            ia.CONTACTS.clear(); ia.CONTACTS.update(contacts)
            ia.LAST_POSE.clear(); ia.LAST_POSE.update(last_pose)
        sc.frame_set(f0); world.invalidate()


def keyed_trial(sc, objs, key, bad):
    """The arm twin of motion_trial: key() -> bad() (0 = accept). Anything else restores every action, contact and solver
    memory of `objs` exactly. Returns bad()'s value, or None when key() could not reach (AssertionError)."""
    saved = [(o, o.animation_data.action if o.animation_data else None, o.rotation_euler.copy()) for o in objs]
    contacts = {k: dict(v) for k, v in ia.CONTACTS.items()}; last_pose = dict(ia.LAST_POSE)
    for o, action, _ in saved:
        if action is not None: o.animation_data.action = action.copy()
    res = None
    try:
        key(); res = bad()
    except AssertionError:
        res = None
    for o, action, rot in saved:
        trial = o.animation_data.action if o.animation_data else None
        if res == 0:
            if action is not None and action.users == 0: bpy.data.actions.remove(action)
            continue
        if o.animation_data: o.animation_data.action = action
        o.rotation_euler = rot
        if trial is not None and trial is not action and trial.users == 0: bpy.data.actions.remove(trial)
    if res != 0:
        ia.CONTACTS.clear(); ia.CONTACTS.update(contacts); ia.LAST_POSE.clear(); ia.LAST_POSE.update(last_pose)
    return res


def checked_gazes(sc, cast, props, frames, key, spans=()):
    """Key final looks together (key returns their actor names); restore heads that invalidate body clearance."""
    saved = {name: (ch.head.animation_data.action if ch.head.animation_data else None, ch.head.rotation_euler.copy())
             for name, ch in cast.items()}
    rejected = set(); complete = False
    def restore(name):
        head = cast[name].head; action, rotation = saved[name]
        trial = head.animation_data.action if head.animation_data else None
        if head.animation_data: head.animation_data.action = action
        head.rotation_euler = rotation
        if trial is not None and trial is not action and trial.users == 0: bpy.data.actions.remove(trial)
    try:
        for name, ch in cast.items():
            if saved[name][0] is not None: ch.head.animation_data.action = saved[name][0].copy()
        changed = key(); world = space.World(sc, cast, props)
        seat = lambda who, fr: {sp[3] for sp in spans if sp[0] == who and sp[1] <= fr <= sp[2]}
        while True:
            hits = world.scene_hits(frames, exempt_fn=seat)
            blocked = {name for name in changed if any(a == f'{name} head' or b == f'{name} head' for _, a, b, _ in hits)} - rejected
            if not blocked: break
            for name in blocked: restore(name)
            rejected |= blocked; world.invalidate()
        complete = True
        return sorted(rejected)
    finally:
        for name, (action, _) in saved.items():
            if not complete: restore(name)
            elif name not in rejected and action is not None and action.users == 0: bpy.data.actions.remove(action)
        sc.frame_set(sc.frame_current); bpy.context.view_layer.update()


def grab_candidate(sc, world, ch, pr, hand, f, lean=0, stance=None, lift=True, spans=()):
    """Trial the contact, body and reaching/lifting arm together; stance previews leave no keys or contacts."""
    piv = ch.arm[hand]; side = rig.SIDE[hand]; preview = stance is not None; single = preview and not lift
    import numpy as np
    blocked_contact = False
    def key():
        nonlocal blocked_contact
        sc.frame_set(f if single else f - 5)
        if stance is not None:
            xy, yaw = stance; ch.root.location.x, ch.root.location.y = xy; ch.root.rotation_euler.z = yaw
            lo._hold(ch, f if single else f - 5)
        up = ch.upper
        if lean:
            if not single: up.keyframe_insert('rotation_euler', index=0, frame=f - 5)
            up.rotation_euler.x = math.radians(lean); up.keyframe_insert('rotation_euler', index=0, frame=f)
        sc.frame_set(f); bpy.context.view_layer.update()
        gc, rad, zl, zh, so = grab_geom(pr)
        ia.touch(sc, piv, side, f, Vector((gc[0], gc[1], (zl + zh) / 2)), rad, zl, zh, label='grab ' + pr.name, standoff=so)
        arm = next(o for o in piv.children if o.type == 'MESH')
        bpy.context.view_layer.update()
        hit = world.limb_hits(arm, arm.matrix_world.copy(), f, owner=ch, own_torso_max=OWN_TORSO_MAX)
        blocked_contact = bool(hit.depth_m)
        if blocked_contact: raise ValueError(f'reaching arm f{f}: {hit}')
        grip = (piv.matrix_world @ Matrix.Translation(gr._hand_local(side, None))).inverted() @ pr.matrix_world
        points = np.concatenate([ia.world_pts(o) for o in pr.children_recursive if o.type == 'MESH'])
        local = np.column_stack((points, np.ones(len(points)))) @ np.array(pr.matrix_world.inverted()).T
        end = f if single else f + 16
        if not single:
            if lean:
                up.rotation_euler.x = math.radians(lean); up.keyframe_insert('rotation_euler', index=0, frame=f + 11)
                up.rotation_euler.x = 0.; up.keyframe_insert('rotation_euler', index=0, frame=f + 16)
            if lift:
                poses.beat(sc, ch, {hand: (carry_raise, carry_out)}, f + 7, move=6,
                           skip=tuple(c for c in ('R', 'L', 'legR', 'legL', 'head', 'body') if c != hand))
        for fr in range(f if single else f - 5, end + 1):
            sc.frame_set(fr); bpy.context.view_layer.update()
            hit = world.limb_hits(arm, arm.matrix_world.copy(), fr, owner=ch, own_torso_max=OWN_TORSO_MAX)
            if hit.depth_m: raise ValueError(f'reaching arm f{fr}: {hit}')
            if fr >= f:
                carried = piv.matrix_world @ Matrix.Translation(gr._hand_local(side, None)) @ grip
                future = (local @ np.array(carried).T)[:, :3]
                for other in (world.cast.values() if isinstance(world.cast, dict) else world.cast):
                    if other is ch: continue
                    for limb in other.arms:
                        if ia._pts_depth(future, limb.matrix_world, *space.local_bounds(limb)) > 0.02:
                            raise ValueError(f'held prop {pr.name} crosses {limb.name} f{fr}')
        return end
    carry = poses.LIB['carry_' + hand][hand]
    for carry_raise, carry_out in (carry, (65, 4), (80, 4), (95, 4), (48, 30), (65, 30), (48, -25)):
        end, hit = motion_trial(sc, world, ch, key, f if single else f - 5, f, spans, commit=not preview)
        if end is not None or blocked_contact or not lift: return end, hit
    return None, hit


def try_moves(sc, world, ch, variants, f0, f1, objs, spans=()):
    """Key the first variant whose body stays clear of the world over [f0, f1] (keyed -> checked -> undone if it hits).
    spans = log['sit_spans']: a sitter's OWN seat is exempt during the sit, exactly as in the final gate (a seated
    hands_head 'hit' Leo's own chair, R142). Returns (variant index, hits of the last try)."""
    hits = []
    seat = lambda fr: {sp[3] for sp in spans if sp[0] == ch.name and sp[1] <= fr <= sp[2]}
    for i, key in enumerate(variants):
        key(); world.invalidate()
        hits = [h for fr in range(f0, f1 + 1) for h in world.body_hits(ch, fr, exempt=seat(fr))]
        if not hits: return i, []
        if i < len(variants) - 1: clear_keys(objs, f0 - 3, f1)
    return len(variants) - 1, hits


def clipping_twist(sc, ch, piv, side, f, tgt, others=(), head_lim=0.04):
    """Same hand point, other twist: the exact 3-axis solutions for one target form a 1-D family; key the one whose rigid arm
    cuts its own torso/head least (continuity alone picked 12.9 cm where 9.97 existed, R135 Codex #5) AND does not enter another
    character (torso/head/hair, allowance 1 cm: Leo's panic arm sat 20.6 cm in Hale's head, R141 Codex #2).
    Returns (angles in degrees, metres OVER the allowances); does not key the shoulder."""
    import numpy as np
    sc.frame_set(f); bpy.context.view_layer.update()
    PW, T = ia._pivot_frame(sc, piv, f)
    arm = next(o for o in piv.children if o.type == 'MESH')
    alo, ahi = space.local_bounds(arm)   # the GATE's measure: the body's own vertices inside the rigid arm box
    own = [(ch.torso, OWN_TORSO_MAX - 0.01), (ch.head_mesh, head_lim)] + [(h, space.OWN_HAIR_MAX - 0.01) for h in ch.hair_pivot.children_recursive if h.type == 'MESH']
    own += [(o_, 0.01) for oc in others for o_ in [oc.torso, oc.head_mesh] + [h for h in oc.hair_pivot.children_recursive if h.type == 'MESH']]
    pts = [(ia.world_pts(o), lim) for o, lim in own]
    def over(ang):
        M = PW @ T @ Euler(tuple(math.radians(a) for a in ang)).to_matrix().to_4x4() @ arm.matrix_local
        return [(ia._pts_depth(P, M, alo, ahi), lim) for P, lim in pts]
    def cut(ang):   # first: how far OVER each allowance (torso 12 / head 5 / hair 10 cm, others 1 cm); then the plain depth as tie-break
        ds = over(ang)
        return sum(10.0 * max(0.0, d - lim) for d, lim in ds) + 0.1 * sum(d for d, _ in ds)
    cur = tuple(math.degrees(a) for a in piv.rotation_euler)
    rx, ry, rz, _, ok = ia.solve_tip(PW, piv.location, side, tgt, cur)
    best = (cut((rx, ry, rz)), (rx, ry, rz)) if ok else (math.inf, cur)
    if ok:
        base = Euler(tuple(math.radians(a) for a in best[1])).to_quaternion()
        axis = (base @ gr._hand_local(side, None)).normalized()
        # Rotating about the reached hand vector spans every twist without solving the same contact hundreds of times.
        for degrees in range(-180, 181, 5):
            angles = tuple(math.degrees(a) for a in (Quaternion(axis, math.radians(degrees)) @ base).to_euler('XYZ', piv.rotation_euler))
            c_ = cut(angles)
            if c_ < best[0] - .005: best = c_, angles
    return best[1], sum(max(0.0, d - lim) for d, lim in over(best[1]))


def least_clipping_twist(sc, ch, piv, side, f, tgt, others=(), head_lim=0.04):
    angles, over = clipping_twist(sc, ch, piv, side, f, tgt, others, head_lim)
    piv.rotation_euler = tuple(math.radians(a) for a in angles); piv.keyframe_insert('rotation_euler', frame=f)
    ia.LAST_POSE[piv.name] = angles
    return over


def held_geometry(sc, grabs):
    """Prop vertices in their driving shoulder's space, including the offset inherited at a transfer."""
    import numpy as np
    clouds, previous = [], {}
    for piv, side, pr, f0, f1 in sorted(grabs, key=lambda g: g[3]):
        if pr in previous:
            old, local, end = previous[pr]
            sc.frame_set(end); bpy.context.view_layer.update()
            points = local @ np.array(old.matrix_world).T
        else:
            sc.frame_set(f0); bpy.context.view_layer.update()
            points = np.concatenate([ia.world_pts(o) for o in pr.children_recursive if o.type == 'MESH'])
            if f0 == 0 and pr.name in HELD_PROPS:
                tip = piv.matrix_world @ gr._hand_local(side, None)
                _, _, top = prop_cyl(pr)
                centre = Vector((tip.x, tip.y, tip.z - (top - pr.matrix_world.translation.z) / 2))
                points += np.array(centre - pr.matrix_world.translation)
            points = np.column_stack((points, np.ones(len(points))))
        sc.frame_set(f0); bpy.context.view_layer.update()
        local = points @ np.array(piv.matrix_world.inverted()).T
        clouds.append((piv, f0, f1, local))
        previous[pr] = piv, local, f1
    return clouds


def clear_gesture(sc, ch, pose, t, mv, others, skip=(), grabs=()):
    """A big arm gesture (raise/out >= 60 deg: fist pump, cheer, wave) must not pass through its own head/hair or another
    character (strict 2 cm; own torso 12 cm as the gate). Check every anticipation/overshoot/settle frame, searching both
    sides of 'out' and lowering overhead elevation. Only a clear variant is accepted. Returns notes.
    'Clear' is judged per frame against what the UN-GESTURED arm already cuts there (a neighbour's hair lying on the shoulder
    at rest: homework s02, Lia's ponytail 16.7 cm in Max's hanging arm vetoed every variant, so his cheer came out one-armed
    since R158): a gesture may not ADD penetration on any frame (5 cm of slack while it leaves an overlap it started in), it is
    not blamed for the start pose."""
    import numpy as np
    vals = poses.full(pose); notes = []
    for side in 'RL':
        if side in skip: continue
        raise_, out_ = vals[side]
        if max(abs(raise_), abs(out_)) < 60: continue
        piv = ch.arm[side]; arm = next(o for o in piv.children if o.type == 'MESH'); alo, ahi = space.local_bounds(arm)
        parts = [(ch.torso, OWN_TORSO_MAX), (ch.head_mesh, space.ARM_TOL)] + [(h, space.OWN_HAIR_MAX) for h in ch.hair_pivot.children_recursive if h.type == 'MESH']
        parts += [(o_, 0.02) for oc in others for o_ in [oc.torso, oc.head_mesh] + [h for h in oc.hair_pivot.children_recursive if h.type == 'MESH']]
        def over():   # metres over the limits, per frame
            ws = []
            clouds = held_geometry(sc, grabs)
            for fr in range(max(0, t - mv - 2), t + 5):
                sc.frame_set(fr); bpy.context.view_layer.update(); M = arm.matrix_world; w = 0.0
                for o, lim in parts:
                    P = ia.world_pts(o)
                    w += max(0.0, ia._pts_depth(P, M, alo, ahi) - lim)
                for driver, f0, f1, local in clouds:
                    if not f0 <= fr <= f1: continue
                    points = (local @ np.array(driver.matrix_world).T)[:, :3]
                    if driver not in ch.arms_piv:
                        w += max(0.0, ia._pts_depth(points, M, alo, ahi) - .02)
                    elif driver is piv:
                        for oc in others:
                            for limb in oc.arms + [oc.torso, oc.head_mesh]:
                                w += max(0.0, ia._pts_depth(points, limb.matrix_world, *space.local_bounds(limb)) - .02)
                ws.append(w)
            return ws
        o0 = over()
        if max(o0) <= 1e-4: continue
        sc.frame_set(t - mv - 2); start_pose = piv.rotation_euler.copy()
        only = tuple(c for c in ('R', 'L', 'legR', 'legL', 'head', 'body') if c != side)
        clear_keys([piv], t - mv - 2, t + 4)   # the arm as it was, held through the window = what the gesture is compared with
        for fr in (t - mv - 2, t + 4): piv.rotation_euler = start_pose; piv.keyframe_insert('rotation_euler', frame=fr)
        base = over(); slack = 0.05 if base[0] > 1e-4 else 0.0   # an arm that STARTS inside something may graze 5 cm deeper for a frame on its way out (any move does, lowering it too)
        adds = lambda ws: sum(max(0.0, a_ - b_ - slack) for a_, b_ in zip(ws, base))
        if adds(o0) <= 1e-4:   # nothing added by the gesture itself: key it again as it was (anticipation + overshoot)
            clear_keys([piv], t - mv - 2, t + 4)
            piv.rotation_euler = start_pose; piv.keyframe_insert('rotation_euler', frame=t - mv - 2)
            poses.beat(sc, ch, {side: (raise_, out_)}, t, move=mv, skip=only)
            notes.append(f"{ch.name} {pose} {side}: kept ({sum(base) * 100:.1f} cm over is there before the gesture)"); continue
        variants = [(raise_, out_)] + [(raise_, out_ + delta) for delta in (15, -15, 30, -30, -45, -60)]
        variants += [(raise_ * scale, min(out_, cap)) for cap in (100, 90, 75) for scale in (.85, .7, .5)]
        if any(driver is piv and f0 <= t <= f1 for driver, _, _, f0, f1 in grabs):
            variants.append(poses.LIB['carry_' + side][side])
        variants.append((0, 3))
        for r_, o_ in variants:
            clear_keys([piv], t - mv - 2, t + 4)
            piv.rotation_euler = start_pose; piv.keyframe_insert('rotation_euler', frame=t - mv - 2)
            poses.beat(sc, ch, {side: (r_, o_)}, t, move=mv, antic=0, over=0, skip=only)
            w = adds(over())
            if w <= 1e-4: break
        if w > 1e-4:
            notes.append(f"{ch.name} {pose} {side}: rejected, no clear anticipation/settle ({w * 100:.1f} cm over)")
        else:
            notes.append(f"{ch.name} {pose} {side}: {adds(o0) * 100:.1f} cm over -> raise {r_:.0f} out {o_:.0f} (clear)")
    return notes


def contact_pose(sc, ch, pose, f, log, others=()):
    """Hand ON the face/head for a rigid R6 arm: the target lies on the line out of the face point along the face normal, at
    exactly arm's length from the shoulder (the hand covers the face, never enters it); keyed + registered as a contact."""
    hands, ax, az = CONTACT_POSES[pose]
    sc.frame_set(f); bpy.context.view_layer.update()
    hm = ch.head_mesh; M = hm.matrix_world
    lo_ = Vector(min(c[i] for c in hm.bound_box) for i in range(3)); hi_ = Vector(max(c[i] for c in hm.bound_box) for i in range(3))
    ctr = (lo_ + hi_) / 2; half = (hi_ - lo_) / 2; reach = math.hypot(ia.TIP, 0.5) * S   # hand point is 0.5 stud off the arm axis
    total_ov = 0.0
    for hand in hands:
        side = rig.SIDE[hand]; piv = ch.arm[hand]
        P = (piv.matrix_world @ Vector((side * 0.5 * S, 0, 0))) if False else piv.matrix_world.translation
        if ax is None:   # hands on the sides of the head (panic). Outward directions tried in order: straight out to the side,
            # then swept toward the front: the hand stays on the head side, the rigid arm swings away from a neighbour (R141 #2)
            loc = Vector((ctr.x + side * half.x * 1.05, ctr.y, ctr.z + az * half.z))   # each hand on ITS side (was mirrored: arms crossed through the head, 23.6 cm)
            nrms = [M.to_3x3() @ Vector(v_) for v_ in ((side, 0, 0.3), (side, -1, 0.3), (side, -3, 0.3))]
        else:
            loc = Vector((ctr.x + ax * half.x, lo_.y, ctr.z + az * half.z))   # on the face: straight on, then from the hand's side
            nrms = [M.to_3x3() @ Vector(v_) for v_ in ((0, -1, 0), (side * 0.5, -1, 0), (side * 1.0, -1, 0))]
        c = M @ loc; tried_ = []; best_c = None
        for nrm in nrms:
            nrm.normalize()
            # |c + d*nrm - P| = reach  ->  d^2 + 2 d (nrm.(c-P)) + |c-P|^2 - reach^2 = 0, take the smallest d >= limb half
            w = c - P; bq = nrm.dot(w); cq = w.length_squared - reach * reach; disc = bq * bq - cq
            if disc < 0: tried_.append('face out of reach'); continue
            ds = [d for d in (-bq - math.sqrt(disc), -bq + math.sqrt(disc)) if d >= (2.1 if 'mouth' in pose else 1.5) * ia.LIMB_HALF]
            if not ds: tried_.append('hand would sit inside the head'); continue
            try:
                tgt = c + min(ds) * nrm
                ia.key_tip(sc, piv, side, f, tgt, tol=0.04, label=f'{ch.name} {pose}',
                           rx_rng=(-200, 40), ry_rng=(-130, 130))   # across-the-body reach (normal aims stop at +-80)
                ov = least_clipping_twist(sc, ch, piv, side, f, tgt, others)
            except AssertionError as e:
                tried_.append(str(e)[:60]); continue
            tried_.append(round(ov, 3))
            if best_c is None or ov < best_c[0]: best_c = (ov, tgt)
            if ov <= 1e-4: break
        if best_c is not None and isinstance(tried_[-1], float) and best_c[0] < tried_[-1] - 1e-4:   # the LAST direction was keyed, not the best
            ia.key_tip(sc, piv, side, f, best_c[1], tol=0.04, label=f'{ch.name} {pose}', rx_rng=(-200, 40), ry_rng=(-130, 130))
            tried_.append(round(least_clipping_twist(sc, ch, piv, side, f, best_c[1], others), 3))
        if not any(isinstance(x, float) for x in tried_):
            log.setdefault('notes', []).append(f'f{f} {ch.name} {pose}: {tried_[-1] if tried_ else "no target"}, kept the pose angles'); continue
        if tried_[-1] != 0.0 and not (isinstance(tried_[-1], float) and tried_[-1] <= 1e-4):
            log.setdefault('notes', []).append(f'f{f} {ch.name} {pose} {hand}: no clear twist in {len(nrms)} hand directions {tried_} (best kept)')
        elif len(tried_) > 1:
            log.setdefault('notes', []).append(f'f{f} {ch.name} {pose} {hand}: hand direction {len(tried_)} of {len(nrms)} {tried_}')
        log.setdefault('contact_frames', []).append([ch.name, f, pose])
        total_ov += next((x for x in reversed(tried_) if isinstance(x, float)), 0.0)
    return total_ov


def crowd_spots(n, area, bounds, avoid, obstacles, rnd, clear=2.2, gap=1.3):
    """Pure python (metres). n extras' (x, y): inside bounds (0.9 m off the walls), region by area (back = far third in +y, sides = outer
    thirds in x, all), >= clear from every `avoid` point (the authored cast's samples), >= gap from each other, outside solid obstacle
    rects (x0, x1, y0, y1, top) + 0.4 m. May return fewer than n when the room is full."""
    x0, x1, y0, y1 = bounds; w, h = x1 - x0, y1 - y0; out = []
    def region(x, y): return area == 'all' or (area == 'back' and y > y0 + 0.62 * h) or (area == 'sides' and abs(x - (x0 + x1) / 2) > 0.34 * w)
    for _ in range(60 * max(n, 1)):
        if len(out) >= n: break
        x, y = rnd.uniform(x0 + 0.9, x1 - 0.9), rnd.uniform(y0 + 0.9, y1 - 0.9)
        if not region(x, y) or any(math.hypot(x - a, y - b) < clear for a, b in avoid) or any(math.hypot(x - a, y - b) < gap for a, b in out): continue
        if any(ox0 - 0.4 < x < ox1 + 0.4 and oy0 - 0.4 < y < oy1 + 0.4 for ox0, ox1, oy0, oy1, _t in obstacles or []): continue
        out.append((x, y))
    return out


def make_crowd(sc, spec, cast, n, log):
    """Scene key crowd {"n", "area", "act"}: background extras built AFTER the gates and cameras (no path, camera or gate sees them), built-in
    parts and random built-in looks, idle breathing or an existing anim (cheer / applaud / haha), facing the cast. Not kept in rig.CAST."""
    import random, anims
    cw = spec['crowd']; rnd = random.Random(zlib.crc32((spec.get('title', '') + 'crowd').encode()))
    avoid = []
    for ch in cast.values():
        for fr in range(0, n, 6):
            sc.frame_set(fr); p = ch.root.matrix_world.translation; avoid.append((p.x, p.y))
    blk = []
    for m in [m for m in sc.timeline_markers if m.camera]:
        sc.frame_set(m.frame + 6); blk.append((m.camera.matrix_world.translation.copy(), [c.head_mesh.matrix_world.translation.copy() for c in cast.values()]))
    bd = camera.ROOM.get('bounds') or (min(a for a, b in avoid) - 6, max(a for a, b in avoid) + 6, min(b for a, b in avoid) - 6, max(b for a, b in avoid) + 6)
    want = int(cw.get('n', 8)); spots = crowd_spots(want * 3, cw.get('area', 'all'), bd, avoid, camera.ROOM.get('obstacles'), rnd)
    def blocks(x, y):   # between a camera and a cast head (within 12 deg, nearer than the head + 0.5 m)
        for P, heads in blk:
            dq = Vector((x, y, 1.0)) - P
            for hd in heads:
                dh = hd - P
                if dq.length < dh.length + 0.5 and dq.angle(dh) < math.radians(12): return True
        return False
    spots = [q for q in spots if not blocks(*q)][:want]
    cx, cy = sum(a for a, b in avoid) / len(avoid), sum(b for a, b in avoid) / len(avoid)
    shirts = ['#C4281C', '#2E9C9A', '#E8A33D', '#4A5FC1', '#7A4FA0', '#3B8F4A', '#D8D8D8', '#E26D9C']; pants = ['#1B2A35', '#3A3A4A', '#5A4A32', '#2B3F6B']
    skins = ['#F5CD30', '#E0AC69', '#C68642', '#8D5524', '#F1C27D']; hairs = ['#5A3A22', '#2A2A2E', '#E8A33D', '#7A1212', '#8A8A90']
    styles = ('spiky', 'short', 'long', 'ponytail', 'bun'); fk = ('smile', 'grin', 'joy', 'neutral', 'laugh'); fps = sc.render.fps
    act = cw.get('act', 'mixed'); clips = [x for x in ('cheer', 'applaud', 'haha') if x in anims.slugs()]
    for k, (x, y) in enumerate(spots):
        yaw = math.degrees(math.atan2(cx - x, -(cy - y))) + rnd.uniform(-25, 25)
        ch = rig.make(f'Extra {k + 1:02d}', (x / S, y / S), yaw, rnd.choice(shirts), rnd.choice(pants), rnd.choice(skins), rnd.choice(hairs), rnd.choice(fk), rnd.choice(styles))
        rig.CAST.pop(ch.name, None); poses.breathe(sc, ch, n, phase=rnd.uniform(0, 6))
        if clips and act != 'idle' and (act == 'cheer' or rnd.random() < 0.5):
            try: anims.play(sc, ch, rnd.choice(clips), rnd.randint(0, fps), speed=rnd.uniform(0.9, 1.1), loop_until=n - 1, skip=('legR', 'legL'))
            except Exception as e: log.setdefault('notes', []).append(f'crowd extra {k + 1}: anim skipped ({str(e)[:60]})')
    log.setdefault('notes', []).append(f"crowd: {len(spots)} of {want} extras placed ({cw.get('area', 'all')})")


def build(spec, log):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    T0_ = time.time(); TT_ = {}   # stage timers -> log['timing'] (speed work, R147)
    ia.reset(); assets.reset(); HELD_PROPS.clear(); THROWS.clear(); rig.CAST.clear(); faces._LIB.clear(); sets.M.clear(); __import__('rooms').M.clear(); camera.LAST['cam'] = None
    sc = bpy.context.scene
    fps = spec.get('fps', 24); sc.render.fps = fps
    if spec.get('frame'):   # B1 opt-in output size, e.g. [1920, 1080] (16:9); default 1080x1920. Cameras are measured at half size
        sc['frame'] = [int(v) for v in spec['frame']]; sc.render.resolution_x, sc.render.resolution_y = sc['frame'][0] // 2, sc['frame'][1] // 2
    n = F(spec['seconds'], fps); sc.frame_start, sc.frame_end = 0, n - 1
    cm0_ = spec.get('camera') or {}   # camera mode pov: the others look into the lens (= the pov character's head) unless they have their own look/turn
    if isinstance(cm0_, dict) and cm0_.get('mode') == 'pov' and cm0_.get('who') in [c['name'] for c in spec['cast']]:
        spec['beats'] = list(spec.get('beats', [])) + [{'t': 0.1, 'who': c['name'], 'look': cm0_['who']} for c in spec['cast']
                                                       if c['name'] != cm0_['who'] and not any(b['who'] == c['name'] and b['t'] <= 0.5 and ('look' in b or 'turn' in b) for b in spec.get('beats', []))]
    st = sets.build(spec.get('set', {'preset': 'classroom'}))
    camera.ROOM['bounds'] = st.get('bounds')
    camera.ROOM['obstacles'] = None   # filled after the set is built (below)
    camera.ROOM['cam'] = None
    bd_ = st.get('bounds')
    if bd_:   # OPEN SIDES: an imported set with a missing fourth wall is a film set - the camera may stand up to 5 m outside that
        # side (blind3_bedroom: Nina 1 m from the open front, facing it, 'hidden' from every camera kept inside the walls)
        bpy.context.view_layer.update(); dg_ = bpy.context.evaluated_depsgraph_get()
        cx_, cy_ = (bd_[0] + bd_[1]) / 2, (bd_[2] + bd_[3]) / 2; hx_, hy_ = (bd_[1] - bd_[0]) / 2, (bd_[3] - bd_[2]) / 2
        open_ = []
        for dx_, dy_, half_, lat_ in ((-1, 0, hx_, hy_), (1, 0, hx_, hy_), (0, -1, hy_, hx_), (0, 1, hy_, hx_)):
            # rays from 1 m OUTSIDE the side straight in: a wall stands within 0.4 m of the boundary, furniture does not
            hits_ = sum(1 for k_ in (-0.8, -0.4, 0.0, 0.4, 0.8) for z_ in (0.6, 1.5, 2.4)
                        if sc.ray_cast(dg_, Vector((cx_ + dx_ * (half_ + 1.0) - dy_ * k_ * lat_, cy_ + dy_ * (half_ + 1.0) + dx_ * k_ * lat_, z_)),
                                       Vector((-dx_, -dy_, 0)), distance=1.4)[0])
            open_.append(hits_ <= 3)
        if any(open_) and not all(open_):   # all open = outdoors (unchanged); none open = a closed room (unchanged)
            camera.ROOM['cam'] = tuple(v_ + e_ for v_, e_ in zip(bd_, (-5.0 * open_[0], 5.0 * open_[1], -5.0 * open_[2], 5.0 * open_[3])))
            log.setdefault('notes', []).append(f"set open on {[n_ for n_, o_ in zip(('-x', '+x', '-y', '+y'), open_) if o_]}: cameras may stand outside it")
    look_key = spec.get('look', 'soft_window' if 'info' not in st else 'auto')
    set_spec = (st.get('info') or {}).get('spec') or {}
    if ':' not in look_key and not set_spec.get('mood') and not os.environ.get('LOOK_MOOD') and set_spec.get('time', 'day') == 'day':
        # AUTO MOOD from the scene's emotions (critic R195: every scene the same mid-key light, reference shifts mood per scene)
        words = ' '.join(str(b.get(k, '')) for b in spec.get('beats', []) for k in ('face', 'pose', 'anim')).lower()
        words += ' attack' * sum(1 for b in spec.get('beats', []) if 'attack' in b or 'transform' in b)
        tally = {m: sum(words.count(w) for w in ws) for m, ws in (
            ('dramatic', ('angry', 'shock', 'scream', 'evil', 'furious', 'rage', 'attack')),
            ('cool', ('sad', 'cry', 'worry', 'scared', 'cower')),
            ('warm', ('joy', 'happy', 'laugh', 'cheer', 'love', 'grin', 'smile', 'dance')))}
        best_ = max(tally, key=tally.get)
        if tally[best_] >= 2 and sorted(tally.values())[-2] < tally[best_]:
            look_key += ':' + best_; log.setdefault('notes', []).append(f"auto mood {best_} {tally}")
    look.apply(sc, look_key, st.get('info'))
    for c in spec['cast']:   # unknown cast face / hair style: fall back instead of crashing
        if c.get('face', 'smile') not in faces.KINDS: log.setdefault('errors', []).append(f"{c['name']} unknown face '{c['face']}'"); c['face'] = 'smile'
        if c.get('face_family') not in (None, *__import__('acting').FAMILIES): log.setdefault('errors', []).append(f"{c['name']} unknown face_family '{c['face_family']}'")
    import acting   # ONE FACE FAMILY per character for the whole Short (LEVEL 1 faces; story.py writes the story-wide 'face_family')
    log['face_family'] = acting.decide_families(spec['cast'], spec.get('beats', []), faces.library())
    for c in spec['cast']: c['face'] = acting.to_family(c.get('face', 'smile'), log['face_family'][c['name']], faces.library(), c.get('face_map'))
    for c in spec['cast']:
        faces.set_marks(c['name'], c.get('face_marks'))
        hs = c.get('hair_style', 'spiky')
        if '+' in hs:
            if all(rig.hair_dir(x if x.startswith('lib:') else 'lib:' + x) for x in hs.split('+')): continue
        if hs not in rig.HAIR_STYLES and not hs.startswith('lib:') and rig.hair_dir('lib:' + hs): c['hair_style'] = hs = 'lib:' + hs   # library tag without 'lib:'
        if hs not in rig.HAIR_STYLES and not (hs.startswith('lib:') and rig.hair_dir(hs)): log.setdefault('errors', []).append(f"{c['name']} unknown hair_style '{c['hair_style']}'"); c['hair_style'] = 'spiky'
    for n_ in faces.NOTES: log.setdefault('errors', []).append(n_)
    cast = {c['name']: rig.make(c['name'], tuple(c.get('at', (0, 0))), c.get('yaw', 0), c.get('shirt', '#C4281C'), c.get('pants', '#1B2A35'),
                                c.get('skin', '#F5CD30'), c.get('hair', '#5A3A22'), c.get('face', 'smile'), c.get('hair_style', 'spiky'),
                                dict(c['outfit']) if c.get('outfit') else None)
            for c in spec['cast']}
    for ch_ in cast.values():   # CASTING check: a library hair whose fringe hides an eye (messy_bun1/2 on Lia, R147) reads as
        # an emo/moody face in every close-up; own hair is (rightly) not an occluder in face_vis, so say it here, once
        sc.frame_set(0); bpy.context.view_layer.update(); dg_ = bpy.context.evaluated_depsgraph_get(); hm_ = ch_.head_mesh; M_ = hm_.matrix_world
        lo_ = Vector(min(c[i] for c in hm_.bound_box) for i in range(3)); hi_ = Vector(max(c[i] for c in hm_.bound_box) for i in range(3))
        fwd_ = (M_.to_3x3() @ Vector((0, -1, 0))).normalized(); hid_ = []
        for side_, ax_ in (('R', 0.22), ('L', -0.22)):   # eye row of the Roblox face decal, both eyes
            eye = M_ @ Vector(((lo_.x + hi_.x) / 2 + ax_ * (hi_.x - lo_.x), lo_.y, (lo_.z + hi_.z) / 2 - 0.1 * (hi_.z - lo_.z)))
            o_ = eye + fwd_ * 1.5 + Vector((0, 0, 0.15)); d_ = eye - o_
            hit_, _, _, _, ob_, _ = sc.ray_cast(dg_, o_, d_.normalized(), distance=d_.length - 0.02)
            if hit_ and ob_.parent is not None and ob_.parent in (ch_.hair_pivot,) or (hit_ and ob_.name.startswith('hair lib') and ob_ in ch_.hair_pivot.children_recursive):
                hid_.append(side_)
        if hid_: log.setdefault('notes', []).append(f"CASTING {ch_.name}: hair covers the {'/'.join(hid_)} eye(s) from the front - pick an open-face hair (assets/hair/sheet.jpg)")
    placed_ = []; START_GAP = 3.5   # studs between two characters' start spots (centre to centre)
    pocket_ = None
    w0 = space.World(sc, cast)   # START SPOTS: exact 3D vs the set and the other characters, with room to TURN (the 2D
    for ch in cast.values():     # footprint version missed a chair moved by the bench respacing: R134 Lia leg f8)
        sc.frame_set(0); bpy.context.view_layer.update()
        p0 = tuple(ch.root.location.xy); yaw0 = ch.root.rotation_euler.z
        bd_ = st.get('bounds')   # a START outside the set (blind4_cafe: Leo 0.25 m behind the kitchen wall -> no camera sees him and
        if bd_ and 'info' in st:   # his walk in crosses the sink) is pulled 0.6 m inside the walls before the clear-spot search
            pin_ = (min(max(p0[0], bd_[0] + 0.6), bd_[1] - 0.6), min(max(p0[1], bd_[2] + 0.6), bd_[3] - 0.6))
            if pin_ != p0:
                log.setdefault('notes', []).append(f"{ch.name} start {p0[0] / S:.1f}, {p0[1] / S:.1f} is outside the set -> pulled inside")
                ch.root.location.x, ch.root.location.y = pin_; p0 = pin_; w0.invalidate()
        def stride_room(q):   # a START needs room for a first STEP too: >= 6 of 8 directions clear 0.35 m away (a start
            # moved flush against a counter made every first stride graze it and the walk was rejected: blind2_store Dana, R162)
            k_ = sum(w0.query(ch, (q[0] + 0.35 * math.cos(a_), q[1] + 0.35 * math.sin(a_)), yaw0, 0).depth_m == 0
                     for a_ in [i_ * math.pi / 4 for i_ in range(8)])
            return k_ >= 6
        try:
            spot, moved = w0.nearest_clear(ch, p0, yaw0, frame=0, turn_from=yaw0 + math.pi / 2)
            if bd_ and 'info' in st and not (bd_[0] + 0.3 < spot[0] < bd_[1] - 0.3 and bd_[2] + 0.3 < spot[1] < bd_[3] - 0.3):
                in_ = lambda q: bd_[0] + 0.3 < q[0] < bd_[1] - 0.3 and bd_[2] + 0.3 < q[1] < bd_[3] - 0.3   # the nearest clear spot
                ring_ = [(p0[0] + r_ * math.cos(a_), p0[1] + r_ * math.sin(a_)) for r_ in [0.125 * k_ for k_ in range(1, 33)]   # INSIDE the walls
                         for a_ in [i_ * math.pi / 12 for i_ in range(24)]]
                spot = next(q for q in ring_ if in_(q) and w0.query(ch, q, yaw0, 0).depth_m == 0); moved = math.dist(spot, p0)
            if moved > 0.01:   # we choose the spot anyway: never a dead-end pocket between furniture (R228: every walk out rejected)
                if pocket_ is None:
                    obs_ = list(st.get('obstacles', [])); pocket_ = floor_pocket(obs_ + w0.unlisted_footprints(obs_, bd_), bd_)
                if pocket_(spot):
                    ring_ = [(p0[0] + r_ * math.cos(a_), p0[1] + r_ * math.sin(a_)) for r_ in [0.25 * k_ for k_ in range(1, 25)]
                             for a_ in [i_ * math.pi / 8 for i_ in range(16)]]
                    q = next((q for q in ring_ if not pocket_(q) and w0.query(ch, q, yaw0, 0).depth_m == 0 and stride_room(q)), None)
                    if q is not None:
                        log.setdefault('notes', []).append(f"{ch.name} start: nearest clear spot is a dead-end pocket between furniture -> open floor")
                        spot = q; moved = math.dist(q, p0)
            if not stride_room(spot):
                for r_ in (0.25, 0.5, 0.75, 1.0):   # step away from whatever crowds the spot
                    alts_ = [(spot[0] + r_ * math.cos(a_), spot[1] + r_ * math.sin(a_)) for a_ in [i_ * math.pi / 4 for i_ in range(8)]]
                    alts_ = [q for q in alts_ if w0.query(ch, q, yaw0, 0).depth_m == 0 and stride_room(q)]
                    if alts_:
                        q = min(alts_, key=lambda q: math.dist(q, p0)); moved = math.dist(q, p0); spot = q; break
        except (ValueError, StopIteration) as e:
            spot, moved = p0, 0.0; log.setdefault('errors', []).append(f"{ch.name} start: {e or 'no clear spot inside the set'}")
        for o_ in placed_:   # R218 ACTOR SPACING: boxes 2 studs apart pass the 3D check, then acting leans (hold_out/reach,
            q_ = o_.root.location.xy; d_ = math.dist(spot, q_)   # lean_in) put the heads together (factory p7 tug-of-war, 16 cm)
            if d_ < START_GAP * S - 1e-6:   # 3 studs left heads meeting on a turn + lean with big hair (p9 gym, R243 -> 4)
                ux, uy = ((spot[0] - q_.x) / d_, (spot[1] - q_.y) / d_) if d_ > 1e-3 else (1.0, 0.0)
                for ax, ay in ((ux, uy), (-uy, ux), (uy, -ux)):   # straight back, then either side
                    cand_ = (q_.x + ax * START_GAP * S, q_.y + ay * START_GAP * S)
                    if w0.query(ch, cand_, yaw0, 0).depth_m == 0:
                        moved = math.dist(cand_, p0); spot = cand_
                        log.setdefault('notes', []).append(f"{ch.name} start {d_ / S:.1f} studs from {o_.name} -> spaced to {START_GAP:g}")
                        break
        placed_.append(ch)
        if moved:
            ch.root.location.x, ch.root.location.y = spot; w0.invalidate()
            log.setdefault('notes', []).append(f"{ch.name} start was not clear -> moved {moved / S:.1f} studs")
        ch.root.keyframe_insert('location', frame=0); ch.root.keyframe_insert('rotation_euler', frame=0)   # later beats' first keys must not reach back to f0
    for i, ch in enumerate(cast.values()):   # idle life: breathing on every frame, each character on its own phase
        if spec.get('breathe', True): poses.breathe(sc, ch, n + 10 * fps, phase=i * 2.1)   # +10 s margin for retiming
    props = {}
    for p in spec.get('props', []):
        if p.get('on'):    # 'desk:i' (classroom) or the name of any placed set piece ('coffee table', 'counter', ...)
            if p['on'].startswith('desk') and 'info' not in st:
                i = int(p['on'].split(':')[1]) if ':' in p['on'] else 0
                x0, x1, y0, y1, top = st['supports'][i]
            else:
                x0, x1, y0, y1, top = assets.support(p['on'])
            at = ((x0 + x1) / 2 + p.get('at', [0, 0])[0] * S, (y0 + y1) / 2 + p.get('at', [0, 0])[1] * S, top)
        else:
            a = p.get('at', [0, 0]); at = (a[0] * S, a[1] * S, p.get('z', 0) * S)
        try: props[p['name']] = sets.prop(p.get('kind', 'box'), p['name'], at, p.get('rot', 0))
        except KeyError:   # unknown model name (factory p7 'cylinder'): a box stands in, the story still builds
            log.setdefault('notes', []).append(f"prop {p['name']}: unknown kind '{p.get('kind')}' -> box")
            props[p['name']] = sets.prop('box', p['name'], at, p.get('rot', 0))
    bpy.context.view_layer.update()
    for p in spec.get('props', []):   # R217 a prop placed by `at` UNDER a set surface (banana at z 0 inside a 0.44 m park slab: every insert
        if p.get('on') or p.get('held_by'): continue   # camera read it 0.0, probe p7 s02) rests ON that surface: nothing spawns buried
        pr_ = props[p['name']]; ms_ = [o for o in [pr_] + list(pr_.children_recursive) if o.type == 'MESH']
        if not ms_: continue
        pts_ = [o.matrix_world @ Vector(c) for o in ms_ for c in o.bound_box]; base_ = min(q.z for q in pts_); c_ = sum(pts_, Vector()) / len(pts_)
        hit_, loc_, _, _, ob_, _ = sc.ray_cast(bpy.context.evaluated_depsgraph_get(), Vector((c_.x, c_.y, base_ + 1.5)), Vector((0, 0, -1)), distance=1.5)
        if hit_ and ob_ not in ms_ and loc_.z > base_ + 0.02:
            pr_.location.z += loc_.z - base_; bpy.context.view_layer.update()
            log.setdefault('notes', []).append(f"prop {p['name']} was under {ob_.name}: lifted {loc_.z - base_:.2f} m onto it")

    held = []   # props that start in a hand: {'held_by': 'Max', 'hand': 'R'} -> carry pose at f0, prop placed in the hand, grabbed
    for p in spec.get('props', []):
        if p.get('held_by'):
            ch, hand = cast[p['held_by']], p.get('hand', 'R'); pr = props[p['name']]
            poses.beat(sc, ch, 'carry_' + hand, 0, move=1)
            sc.frame_set(0); bpy.context.view_layer.update()
            tip = ch.arm[hand].matrix_world @ gr._hand_local(rig.SIDE[hand], None)
            c, rad, top = prop_cyl(pr); pr.location = (tip.x, tip.y, tip.z - (top - pr.matrix_world.translation.z) / 2)
            fu = F(p['until'], fps) if 'until' in p else n - 1
            held.append((ch.arm[hand], rig.SIDE[hand], pr, 0, END if fu >= n - 1 - F(0.5, fps) else fu))
            HELD_PROPS.add(pr.name)

    def target_of(name):
        if name in cast: return cast[name].head_mesh
        if name in props: return props[name]
        piece = next((q['pivot'] for q in assets.PLACED if q['name'] == name), None)
        if piece is not None: return piece
        raise KeyError(f'unknown look/aim target {name}')

    settle = {}   # who -> frame their last walk/turn has settled (grabs wait for it)
    lean_for = {}  # who -> forward lean (deg) the approach planned for the next grab
    seated, fallen, seat_back = {}, {}, {}
    vfx_jobs = []   # fight VFX closures, baked after the shots

    def hold_until(ch, f, end):
        nxt = next((F(x['t'], fps) - x.get('move', 4) - 2 for x in beats
                    if x['who'] == ch.name and F(x['t'], fps) > f and any(k in x for k in ('walk', 'turn', 'sit', 'stand', 'jump', 'fall', 'give', 'grab', 'pose'))), None)
        return max(end, nxt if nxt is not None else max(n - 1, max(settle.values(), default=0)))

    def actor_overlap(ch, frames, tol=0.03):
        """First frame where a body part of ch (torso, head, arms, legs as boxes, exact SAT) is deeper than tol inside a part of
        another character AND deeper than the two already were at frames[0] (two who start shoulder to shoulder are not this
        move's fault). Returns (frame, name, other part, depth m) or None."""
        parts = lambda c: [c.torso, c.head_mesh] + list(c.arms) + list(c.legs)
        obb = lambda o: ia._obb(o.matrix_world, *space.local_bounds(o))
        base = {}
        for i_, fr in enumerate(frames):
            sc.frame_set(fr); p = ch.root.matrix_world.translation; mine = None
            for o in cast.values():
                if o is ch or (o.root.matrix_world.translation - p).length > 2.4: continue
                mine = mine or [obb(a) for a in parts(ch)]
                d, nm = max((ia.obb_depth(a, obb(b_)), b_.name) for a in mine for b_ in parts(o))
                if i_ == 0: base[o.name] = d
                elif d > max(tol, base.get(o.name, 0.0) + 0.02): return (fr, ch.name, nm, d)
        return None

    def walk_to(ch, who, wl, f, b, beats):
        """Walk along wl (points in studs, or a prop/character NAME as a goal). A prop goal ends on the clear spot where the hand
        reaches it (approach_spot); a character goal stops staging walk_up_stop short (clear of their body at arrival, waiting if they still move), facing them. Returns the settled frame or None."""
        f = max(f, settle.get(who, 0))
        sc.frame_set(f); bpy.context.view_layer.update()
        p0 = ch.root.matrix_world.translation; path = [(p0.x, p0.y)]; yaw_end = None
        # routes see what the gate measures: the registered footprints + every other collidable mesh inside the room
        obs_r = list(st.get('obstacles', [])) + world.unlisted_footprints(st.get('obstacles', []), st.get('bounds'))
        spans_of = {}
        def spans_for(route):
            k_ = tuple(route)
            if k_ not in spans_of: spans_of[k_] = tight_spans(route, obs_r)
            return spans_of[k_]
        for el in wl:
            if isinstance(el, str) and el in props:
                hand = b.get('hand') or next((x['grab'].get('hand', 'R') for x in beats if x['who'] == who and x['t'] >= b['t']
                                              and isinstance(x.get('grab'), dict) and x['grab']['prop'] == el), 'R')
                c, rad_g, zl, zh, so = grab_geom(props[el])
                rad = rad_g if so else rad_g - ia.LIMB_HALF; top = (zl + zh) / 2     # approach_spot adds the limb half itself
                others = [tuple(o.root.matrix_world.translation)[:2] for o in cast.values() if o is not ch]
                eta_ = f + int(math.hypot(c[0] - path[-1][0], c[1] - path[-1][1]) / (b.get('speed', 9.5) * S) * fps) + 8
                sc.frame_set(eta_)   # where the others STAND when this walker arrives (earlier beats are keyed: Lia walked up next to Zed)
                others += [tuple(o.root.matrix_world.translation)[:2] for o in cast.values() if o is not ch]
                sc.frame_set(f)
                def accept_spot(xy, yaw, lean):
                    end, _ = grab_candidate(sc, world, ch, props[el], hand, eta_, lean, (xy, yaw))
                    return end is not None
                spot = approach_spot(ch, hand, c, rad, top, st.get('obstacles', st['supports']), others, st.get('bounds'), path[-1], (zl, zh), accept_spot)
                if spot is None:   # unreachable on its support: slide the prop toward the support edge nearest the walker (an animator
                    pr = props[el]; c0 = pr.location.copy()   # would just dress it closer); stays on the support, logged as a note
                    sup = next((o for o in st.get('obstacles', st['supports']) if o[0] < c0.x < o[1] and o[2] < c0.y < o[3] and abs(o[4] - c0.z) < 0.08), None)
                    dx, dy = path[-1][0] - c0.x, path[-1][1] - c0.y; dl = math.hypot(dx, dy) or 1.0
                    for k in range(1, 11):
                        nx, ny = c0.x + dx / dl * 0.4 * S * k, c0.y + dy / dl * 0.4 * S * k
                        if sup and not (sup[0] + 0.3 * S < nx < sup[1] - 0.3 * S and sup[2] + 0.3 * S < ny < sup[3] - 0.3 * S): break
                        pr.location.x, pr.location.y = nx, ny; bpy.context.view_layer.update()
                        c, rad_g, zl, zh, so = grab_geom(pr); rad = rad_g if so else rad_g - ia.LIMB_HALF; top = (zl + zh) / 2
                        spot = approach_spot(ch, hand, c, rad, top, st.get('obstacles', st['supports']), others, st.get('bounds'), path[-1], (zl, zh), accept_spot)
                        if spot is not None:
                            log.setdefault('notes', []).append(f"{el} moved {0.4 * k:.1f} studs toward the edge (out of reach on its support)"); break
                    if spot is None: pr.location = c0
                if spot is None:
                    log.setdefault('errors', []).append(f"t{b['t']} {who} walk {el}: no clear spot within reach"); return None
                sp_ = tuple(spot[0]); y_in = math.atan2(sp_[0] - path[-1][0], -(sp_[1] - path[-1][1]))
                if world.sweep(ch, [(sp_, y_in), (sp_, spot[1])], frame=f).depth_m > 0:   # arrival TURN sweeps furniture (R135 cookie
                    try:                                                                     # table, 157 hits): nearest spot whose turn
                        sp_, mv_ = world.nearest_clear(ch, sp_, spot[1], frame=f, turn_from=y_in, max_r=0.75)   # is clear
                        if not accept_spot(sp_, spot[1], spot[2]): sp_ = tuple(spot[0])
                        log.setdefault('notes', []).append(f"t{b['t']} {who} walk {el}: stop moved {mv_ / S:.1f} studs so the turn is clear")
                    except ValueError:
                        log.setdefault('notes', []).append(f"t{b['t']} {who} walk {el}: preview found no turn spot; checking keyed alternatives")
                path.append(sp_); yaw_end = spot[1]; lean_for[who] = spot[2]
            elif isinstance(el, str) and any(q['name'] == el for q in assets.PLACED):   # a set piece: stop 1.5 studs in front, face it
                q = next(q for q in assets.PLACED if q['name'] == el); x0, x1, y0, y1 = q['rect']; px, py = path[-1]
                cx_, cy_ = (x0 + x1) / 2, (y0 + y1) / 2; m_ = staging.d('piece_stop_gap') + staging.d('body_half_depth')
                gx = min(max(px, x0 - m_), x1 + m_); gy = min(max(py, y0 - m_), y1 + m_)
                if x0 - m_ < gx < x1 + m_ and y0 - m_ < gy < y1 + m_:   # walker is beside it: push out along the nearest side
                    d_ = {'l': gx - (x0 - m_), 'r': (x1 + m_) - gx, 'b': gy - (y0 - m_), 't': (y1 + m_) - gy}; k_ = min(d_, key=d_.get)
                    gx, gy = {'l': (x0 - m_, gy), 'r': (x1 + m_, gy), 'b': (gx, y0 - m_), 't': (gx, y1 + m_)}[k_]
                world.invalidate()   # the stop may lie inside ANOTHER piece (a sofa made of 3 models: the spot in front of its back
                if world.query(ch, (gx, gy), math.atan2(cx_ - gx, -(cy_ - gy)), f).depth_m > 0:   # rest is inside its seat, R228)
                    try:
                        (gx, gy), mv_ = world.nearest_clear(ch, (gx, gy), math.atan2(cx_ - gx, -(cy_ - gy)), frame=f, max_r=2.5)
                        log.setdefault('notes', []).append(f"t{b['t']} {who} walk to {el}: stop is inside furniture -> {mv_ / S:.1f} studs to a clear spot")
                    except ValueError as e:
                        log.setdefault('notes', []).append(f"t{b['t']} {who} walk to {el}: preview found no clear stance ({e})")
                path.append((gx, gy)); yaw_end = math.atan2(cx_ - gx, -(cy_ - gy))
            elif isinstance(el, str) and el in cast:   # aim where they will BE on arrival (they may be moving: sitting, walking)
                px, py = path[-1]; q = cast[el].root.matrix_world.translation
                eta = f + int(math.hypot(q.x - px, q.y - py) / (b.get('speed', 9.5) * S) * fps) + 8
                if settle.get(el, 0) > eta:   # the target is still on the move: aim at where it STOPS and wait to set off,
                    late = settle[el] - eta   # so the two never converge on a moving spot (R131 Max met walking Lia head-on)
                    f += late; eta += late
                    log.setdefault('notes', []).append(f"t{b['t']} {who} waits {late / fps:.1f}s for {el} to settle before walking up")
                sc.frame_set(eta); q = cast[el].root.matrix_world.translation.copy(); tyaw = cast[el].root.matrix_world.to_euler().z; sc.frame_set(f)
                d = math.hypot(q.x - px, q.y - py)
                # L1 CROWD: walking up to someone's SIDE, the last strides swing a hand into their hanging arm (3 studs: 7 cm for a
                # walk, 17 cm for a run's 60 deg swing): stop up to 0.8 stud (run: 1.5) farther the more side-on the approach is
                side_on_ = abs((q.x - px) * math.cos(tyaw) + (q.y - py) * math.sin(tyaw)) / d if d > 1e-6 else 0.0
                stop_d_ = staging.d('walk_up_stop') + (side_on_ * (0.75 if b.get('run') or b.get('speed', 9.5) >= 10 else 0.4) if spec.get('strict_crowd') else 0.0)
                k = max(0.0, (d - stop_d_) / d) if d > 1e-6 else 0.0
                end = (px + (q.x - px) * k, py + (q.y - py) * k)
                world.invalidate()   # the target may have been keyed since: check the stop spot against its pose AT ARRIVAL
                def stop_ok(e_):     # clear at arrival INCLUDING the turn from the arrival heading to facing them (R134 Hale)
                    y_in = math.atan2(e_[0] - px, -(e_[1] - py)); y_face = math.atan2(q.x - e_[0], -(q.y - e_[1]))
                    return world.sweep(ch, [(e_, y_in), (e_, y_face)], frame=eta).depth_m == 0
                if el in seated:     # walk up BESIDE a seated person (the aisle), never into the knee space in front of the seat
                    lat = Vector((math.cos(tyaw), math.sin(tyaw)))
                    sides = [(q.x + sg * lat.x * dd_, q.y + sg * lat.y * dd_) for dd_ in (staging.d('walk_up_stop'), staging.d('walk_up_stop') + 0.4) for sg in (1, -1)]
                    ent_s = seat_back.get(el) or {}   # keep their STAND-UP spot free (blind6_classroom: Leo parked on Ava's entry,
                    keep = [e for e in (ent_s.get('xy'), ent_s.get('via')) if e   # she stood up through his torso) - only when
                            and any(x['who'] == el and x.get('stand') and x['t'] > b['t'] for x in beats)]   # they stand later
                    sides = sorted([c_ for c_ in sides if stop_ok(c_)],   # PREFER spots off their entry (a filter broke phone s02 +
                                   key=lambda c_: (any(math.hypot(c_[0] - e[0], c_[1] - e[1]) <= 0.9 for e in keep),   # schoolyard
                                                   math.hypot(c_[0] - px, c_[1] - py)))                                 # s01, R209)
                    if sides: end = sides[0]; log.setdefault('notes', []).append(f"t{b['t']} {who} walks up beside seated {el}")
                if not stop_ok(end):
                    try:
                        end, _ = world.nearest_clear(ch, end, math.atan2(q.x - end[0], -(q.y - end[1])), frame=eta,
                                                     turn_from=math.atan2(end[0] - px, -(end[1] - py)))
                    except ValueError as e:
                        log.setdefault('notes', []).append(f"t{b['t']} {who} walk to {el}: preview {e}")
                yaw_end = cheat(math.atan2(q.x - end[0], -(q.y - end[1])))
                path.append(end)
            else:   # a numeric point: the STANCE there must be clear at arrival (furniture, walls, the others as they will
                # be then); a route could end inside a fridge / bench (R146 Codex #1-2: 70 + 219 part-frame hits) -> nearest clear spot
                px, py = path[-1]; e_ = (el[0] * S, el[1] * S); bd = st.get('bounds')
                if bd: e_ = (min(max(e_[0], bd[0] + 0.35), bd[1] - 0.35), min(max(e_[1], bd[2] + 0.35), bd[3] - 0.35))
                eta = f + int(math.hypot(e_[0] - px, e_[1] - py) / (b.get('speed', 9.5) * S) * fps) + 8
                y_in = math.atan2(e_[0] - px, -(e_[1] - py)) if math.hypot(e_[0] - px, e_[1] - py) > 1e-6 else ch.root.rotation_euler.z
                world.invalidate()   # ... and as they END UP: one still on its way to this same spot arrives after `eta` (R228 store)
                for _ in range(3):   # a moved goal changes the arrival heading (a leaning pose is not symmetric): check again
                    rt_ = plan_path((px, py), e_, obs_r, bd)   # ... at the heading the ROUTE arrives with (R228: side-on into a wall)
                    y_rt = math.atan2(e_[0] - rt_[-2][0], -(e_[1] - rt_[-2][1])) if len(rt_) > 2 else y_in
                    e_was = e_
                    eta2 = max([eta] + [settle.get(o_, 0) for o_ in cast if o_ != who])
                    for fr_ in ((eta2, eta, eta2) if eta2 > eta else (eta,)):   # a spot found for one moment must hold at the other
                        if world.sweep(ch, [(e_, y_rt), (e_, y_in)], frame=fr_).depth_m == 0: continue
                        try:
                            e2, mv_ = world.nearest_clear(ch, e_, y_in, frame=fr_, turn_from=y_rt if len(rt_) > 2 else None, max_r=2.0)
                            if bd and not (bd[0] + 0.3 < e2[0] < bd[1] - 0.3 and bd[2] + 0.3 < e2[1] < bd[3] - 0.3): raise ValueError('outside the room')
                            log.setdefault('notes', []).append(f"t{b['t']} {who} walk to {el}: blocked there at arrival -> {mv_ / S:.1f} studs to a clear spot")
                            e_ = tuple(e2)
                        except ValueError as e:
                            log.setdefault('notes', []).append(f"t{b['t']} {who} walk to {el}: preview found no clear stance ({e})"); break
                    if e_ == e_was: break
                path.append(e_); yaw_end = None
        # other characters over the next ~3 s (they may be moving too: sitting down, walking). L1 CROWD: a MOVING other counts only
        # where it is while this walker is near (within 3 m of the walker's own progress at that moment); every sampled position
        # of a crossing walker was an obstacle, i.e. a wall across the room whose only gap was beyond their stop: the detour ran
        # into them there (L1_move_01: Cy walked around the end of Ana's lane into her arm, 60 cm)
        others_xy = []   # other characters over the next ~3 s (they may be moving too: sitting down, walking)
        for fo in range(f, f + F(3.0, fps), 6):
            sc.frame_set(fo); others_xy += [tuple(o.root.matrix_world.translation)[:2] for o in cast.values() if o is not ch]
        sc.frame_set(f)
        routed = [path[0]]
        for a, b_ in zip(path, path[1:]):    # every leg goes AROUND furniture / walls / other characters
            routed += plan_path(routed[-1], b_, obs_r, st.get('bounds'), others_xy)[1:]
        if len(routed) > len(path): log.setdefault('notes', []).append(f"t{b['t']} {who} walk routed around obstacles ({len(routed) - 2} turns)")
        if os.environ.get('WALK_DEBUG'): print('WALKDBG_T', round(time.time() % 10000, 1)); print('WALKDBG', json.dumps({'t': b['t'], 'who': who, 'path': path, 'routed': routed, 'obstacles': [list(o) for o in obs_r], 'bounds': st.get('bounds'), 'others': others_xy, 'placed': [(q['name'], [round(v, 2) for v in q['rect']], round(q['top'], 2), q['solid']) for q in assets.PLACED]}))
        origin, goal = routed[0], routed[-1]
        info = {}; last = None
        # a hit during the first stride is a LAUNCH problem (step aside first) - the first stride comes after the planted turn to
        # face the route (6 frames per 35 deg): a 180 deg turn made every launch hit look like a goal problem (R228 store Sam)
        d_y = abs((math.atan2(routed[1][0] - origin[0], -(routed[1][1] - origin[1])) - ch.root.rotation_euler.z + math.pi) % (2 * math.pi) - math.pi) if len(routed) > 1 and math.dist(origin, routed[1]) > 1e-6 else 0.0
        turn_fr = 6 * math.ceil(math.degrees(d_y) / lo.TURN_STEP_DEG) if d_y > math.radians(30) else 0
        def key_walk(route, start, launch=None, side=False, face=None):
            nonlocal info
            sc.frame_set(f); lo._hold(ch, f)
            sc.frame_set(start); lo._hold(ch, start)
            # L1 GAIT: an arm left in a stance/listener pose stayed FROZEN there through the planted launch turn and steps
            # (creator bug R259 'weird walking': 1.4 s of shuffle-turn with one arm 26 deg forward). A free arm drops toward
            # hanging as the first step starts; the stride's own swing takes over from there. Holding arms keep their pose.
            for pv_ in ch.arms_piv:
                if os.environ.get('L1_NOREL') or any(g_[0] is pv_ and g_[3] - 8 <= start <= g_[4] for g_ in grabs): continue
                e0_ = pv_.rotation_euler.copy(); fr0_ = max(f, start - 8); pv_.keyframe_insert('rotation_euler', frame=fr0_)   # let go DURING the launch turn, so the span opens with the arm down
                s_ = 'R' if pv_ is ch.arm['R'] else 'L'; r_ = poses.euler(ch, s_, poses.LIB['idle'].get(s_, (0, 0)))   # (0.3 x a raised pose is still raised)
                pv_.rotation_euler = [0.25 * e0_[i_] + 0.75 * r_[i_] if abs(e0_[i_] - r_[i_]) < 0.6 else r_[i_] for i_ in range(3)]
                pv_.keyframe_insert('rotation_euler', frame=start)
            if launch is not None: start = lo.step_to(sc, ch, launch, start)
            plen = sum(math.dist(p_, q) for p_, q in zip(route, route[1:]))
            fe = start; info = {}
            if plen < 1.5 * S:
                fe = lo.step_to(sc, ch, route[-1], start)
            elif math.dist(route[0], route[-1]) > 0.1 * S:
                sc.frame_set(start); y_cur = ch.root.rotation_euler.z
                y_path = math.atan2(route[1][0] - route[0][0], -(route[1][1] - route[0][1]))
                if not side and abs((y_path - y_cur + math.pi) % (2 * math.pi) - math.pi) > math.radians(30):
                    start = lo.step_to(sc, ch, route[0], start, goal_yaw=y_path, step_deg=lo.TURN_STEP_DEG)   # 180 deg = 3 steps, not 6
                spd = b.get('speed', 9.5)   # reference characters move briskly
                def go(rt, f0_):
                    if b.get('run') or spd >= 10:   # RUN: flight phase, no planted-foot constraint (walk() skates at running speed)
                        # through lo.walk_path: the same retries, and the L1 step-and-turn fallback instead of run.py's 35 deg shuffle turns
                        return lo.walk_path(sc, ch, rt, f0_, corner_r=min(0.8, 0.45 * min(math.dist(p_, q) for p_, q in zip(rt, rt[1:]))),
                                            planted=lambda path_, f_, cr_, k_: runm.run_planted(sc, ch, path_, f_, speed_studs_s=max(spd, 10), amp_deg=48 * k_,
                                                                                                corner_r=2.0 if cr_ is None else cr_))
                    return lo.walk_path(sc, ch, rt, f0_, speed_studs_s=spd, stride_deg=b.get('stride', 30),
                                        corner_r=min(0.6, 0.45 * min(math.dist(p_, q) for p_, q in zip(rt, rt[1:]))))
                if not side: info = go(route, start)
                else:   # tight aisles side-on with planted side-steps, the open stretches as a normal walk / run
                    fs_ = start; drift = 0.0
                    spans_ = spans_for(route)
                    for pts_, sideways in spans_:
                        if sideways:
                            a_, b_ = max(zip(pts_, pts_[1:]), key=lambda s_: math.dist(*s_))   # side-on to the longest leg, the
                            y_al = math.atan2(b_[0] - a_[0], -(b_[1] - a_[1]))                  # face kept toward the camera (-Y);
                            sc.frame_set(fs_); y_now = ch.root.rotation_euler.z
                            y_to = (yaw_end if face is None else face) if pts_ is spans_[-1][0] else None   # the last stretch faces
                            if y_to is None: y_to = y_now                                       # the way the walk ENDS (no turn
                            y_sd = max((y_al + math.pi / 2, y_al - math.pi / 2),                # inside the aisle: R228 sofa gap);
                                       key=lambda y_: (round(math.cos(y_ - y_to), 1), math.cos(y_)))   # others: the least turn
                            fs_ = lo.step_to(sc, ch, pts_[0], fs_, goal_yaw=y_now + (y_sd - y_now + math.pi) % (2 * math.pi) - math.pi)
                            for q_ in pts_[1:]: fs_ = lo.step_to(sc, ch, q_, fs_, step_m=0.4)
                        elif sum(math.dist(p_, q) for p_, q in zip(pts_, pts_[1:])) < 1.5 * S:
                            sc.frame_set(fs_); y_now = ch.root.rotation_euler.z; y_go = math.atan2(pts_[-1][0] - pts_[0][0], -(pts_[-1][1] - pts_[0][1]))
                            fs_ = lo.step_to(sc, ch, pts_[0], fs_, goal_yaw=y_now + (y_go - y_now + math.pi) % (2 * math.pi) - math.pi)
                            fs_ = lo.step_to(sc, ch, pts_[-1], fs_)
                        else:
                            i_ = go(pts_, fs_); fs_ = i_['f_end']; drift = max(drift, i_.get('max_plant_drift', 0))
                    info = {'f_end': fs_, 'max_plant_drift': drift, 'segmented': True}
                fe = info['f_end']
                if not (b.get('run') or spd >= 10):
                    up = ch.upper
                    for fw in range(start, fe + 1):
                        sc.frame_set(fw); a_ = ch.shoulders[0].rotation_euler.x
                        up.rotation_euler.z = 0.25 * a_; up.rotation_euler.y = 0.08 * a_
                        up.keyframe_insert('rotation_euler', frame=fw)
                    sc.frame_set(fe + 6); up.rotation_euler.z = 0; up.rotation_euler.y = 0; up.keyframe_insert('rotation_euler', frame=fe + 6)
            if yaw_end is not None:
                sc.frame_set(fe); fe = lo.step_to(sc, ch, tuple(ch.root.location.xy), fe, goal_yaw=yaw_end if face is None else face, step_deg=lo.TURN_STEP_DEG)
            if isinstance(wl[-1], str) and wl[-1] in props:
                sc.frame_set(fe + 6); bpy.context.view_layer.update()
                end, hit = grab_candidate(sc, world, ch, props[wl[-1]], hand, fe + 6, lean_for.get(who, 0),
                                          (tuple(ch.root.location.xy), ch.root.rotation_euler.z))
                if end is None: raise ValueError(f'contact at actual arrival: {hit}')
            info['f_end'] = fe; info['f_start'] = start
            h_ = actor_overlap(ch, range(f, fe + 7))   # L1 CROWD: a walker's arms/legs through another character (the body
            if h_ and not soft_ov[0]:                   # check sees torsos; a swinging arm crossed a bystander's arm 60 cm)
                ov_[0] = h_; raise ValueError(f'overlaps {h_[2]} f{h_[0]} {h_[3] * 100:.0f} cm')
            return fe + 6

        def candidates():
            # shortcut: waits <= 1 s and nearby offsets <= 1 m; extend this search for tighter traffic.
            for delay in (0, F(0.5, fps), F(1.0, fps)):
                yield routed, f + delay, None
            # A wait cannot clear a permanently occupied stop or a stride launched into furniture.
            for radius in (0.25, 0.5, 1.0):
                for deg in range(0, 360, 45):
                    d = (radius * math.cos(math.radians(deg)), radius * math.sin(math.radians(deg)))
                    launch = last is not None and last[0] < f + 24 + turn_fr
                    p = origin if launch else goal
                    alt = (p[0] + d[0], p[1] + d[1]); bd = st.get('bounds')
                    if bd and not (bd[0] + .3 < alt[0] < bd[1] - .3 and bd[2] + .3 < alt[1] < bd[3] - .3): continue
                    # PRE-SCREEN (speed): one body query at the alternate spot when it matters (arrival for a stop, start for a
                    # launch) before keying a whole trial walk (29 keyed trials made blind_park s01 take 1360 s, R160)
                    fr_q = f if launch else min(n - 1, f + int(math.dist(origin, alt) / (b.get('speed', 9.5) * S) * fps) + 8)
                    y_q = math.atan2(goal[0] - origin[0], -(goal[1] - origin[1])) if math.dist(origin, goal) > 1e-6 else ch.root.rotation_euler.z
                    if world.query(ch, alt, y_q, fr_q).depth_m > 0: continue
                    route = plan_path(alt if launch else origin, goal if launch else alt, obs_r, bd, others_xy)
                    yield route, f, alt if launch else None
            delta = Vector(goal) - Vector(origin)
            if delta.length > .01:
                lat = Vector((-delta.y, delta.x)).normalized()
                for sign in (1, -1):
                    mid = tuple((Vector(origin) + Vector(goal)) / 2 + sign * 1.5 * lat)
                    route = plan_path(origin, mid, obs_r, st.get('bounds'), others_xy)
                    route += plan_path(mid, goal, obs_r, st.get('bounds'), others_xy)[1:]
                    yield route, f, None
        bases = []   # plain trials that got past their launch (the hit came later): the routes worth stopping short on
        def trials():   # every candidate as keyed today; when it has a tight aisle, also with the aisle side-stepped
            for i, (route, start, launch) in enumerate(candidates()):
                yield i, route, start, launch, False, None, None
                if start == f and any(sd_ for _, sd_ in spans_for(route)):
                    yield i, route, start, launch, True, None, 'side-steps the tight part'
            if isinstance(wl[-1], str) and wl[-1] in props: return   # a grab needs its exact spot
            for base, lnch in (bases or [(routed, None)]):   # goal not reachable: stop as near as it gets, on the routes whose
                cum = [0.0]                                    # LAUNCH worked (a shorter walk re-phases the strides, so several)
                for p_, q in zip(base, base[1:]): cum.append(cum[-1] + math.dist(p_, q))
                for back in (0.25, 0.5, 1.0, 1.5, 2.5, 4.0):
                    if cum[-1] - back < 0.5: break
                    k_ = max(k for k, c_ in enumerate(cum) if c_ < cum[-1] - back); t_ = (cum[-1] - back - cum[k_]) / (cum[k_ + 1] - cum[k_])
                    cutp = (base[k_][0] + (base[k_ + 1][0] - base[k_][0]) * t_, base[k_][1] + (base[k_ + 1][1] - base[k_][1]) * t_)
                    short = [p_ for p_ in base[:k_ + 1] if math.dist(p_, cutp) > 0.05] + [cutp]
                    if len(short) < 2: break
                    face = math.atan2(goal[0] - cutp[0], -(goal[1] - cutp[1])) if yaw_end is not None else None
                    for sd_ in (False, True):
                        if sd_ and not any(s_ for _, s_ in spans_for(short)): continue
                        yield 0, short, f, lnch, sd_, face, f'stops {back / S:.1f} studs short (the goal is not reachable)'
        ov_ = [None]; soft_ov = [False]
        for pass_ in ((0, 1, 2) if spec.get('strict_crowd') else (1, 2)):   # (story key strict_crowd: only L1 stories and the showcase; the rest keep the old routes) pass 0 refuses a route whose limbs go through another character (L1 CROWD); pass 1 keeps the old behaviour (those
            soft_ov[0] = pass_ > 0; lo.LEGACY_FALLBACK = pass_ == 2   # pass 2: and the old fallback. (stories walked through each other's arms and were accepted) so no existing scene starts failing
            for i, route, start, launch, side, face, why in trials():
                ov_[0] = None
                fe, last_ = motion_trial(sc, world, ch, lambda: key_walk(route, start, launch, side, face), f,
                                         hold_until(ch, f, f), log.get('sit_spans', []))
                if fe is None and ov_[0]: last_ = ov_[0]   # the overlap's own frame decides launch vs goal alternates
                if os.environ.get('WALK_DEBUG'): print('WALKTRY', round(time.time() % 10000, 1), who, i, 'side' if side else 'fwd', why, [(round(x_, 2), round(y_, 2)) for x_, y_ in route], '->', fe, last_, 'spans', [(len(p_), s_) for p_, s_ in spans_for(route)] if side else '')
                if why is None or last is None: last = last_   # the launch/goal choice of candidates() reads the plain trials only
                if fe is None and why is None and start == f and last_[0] >= f + 24 + turn_fr and len(bases) < 3: bases.append((route, launch))
                if fe is not None:
                    if i: log.setdefault('notes', []).append(f"t{b['t']} {who} walk accepted alternate {i} (wait {(start - f) / fps:.2f}s)")
                    if why: log.setdefault('notes', []).append(f"t{b['t']} {who} walk {why}")
                    break
            else:
                continue
            break
        else:
            lo.LEGACY_FALLBACK = False
            log.setdefault('errors', []).append(f"t{b['t']} {who} walk rejected: {last}")
            return None
        lo.LEGACY_FALLBACK = False
        log.setdefault('walks', []).append({'who': who, 'f0': info['f_start'], 'f1': info['f_end'], 'slide_cm': round(100 * info.get('max_plant_drift', 0), 2),
                                            'run': bool(b.get('run') or b.get('speed', 9.5) >= 10), 'stride': 'n' in info and not info.get('segmented')})
        # walking characters look where they go: head back to forward at the walk start, and AT the goal on arrival
        gaze.append((ch, '__forward__', f + 4, 4, False))
        goal = next((el for el in reversed(wl) if isinstance(el, str)), None)
        if goal is not None: gaze.append((ch, goal, fe + 6, 5, False))
        settle[who] = fe
        return fe

    SHIFT_AT = {}   # authored start t -> seconds already pushed by an action starting then (concurrent delays OVERLAP)
    def retime_after(b, late, why):
        """An action finished its approach `late` frames after its authored time: push every LATER beat and shot back by
        that much and lengthen the scene (the story's rhythm is kept; nothing is squeezed or skipped). Returns the new n.
        Beats by other actors at the SAME time stay parallel, and a concurrent action's delay counts only beyond what an
        earlier concurrent one already pushed (two sits at t0.2 ran in series: a 9 s scene became 42 s, R152 Codex #3)."""
        t_b = b.get('_t0', b['t']); done = SHIFT_AT.get(t_b, 0.0)
        dl = late / fps - done
        if dl <= 1e-6: return n
        SHIFT_AT[t_b] = done + dl; i0 = next(i for i, x in enumerate(beats) if x is b)
        for x in beats[i0 + 1:]:
            if x['t'] > b['t'] + 1e-6 or (x['who'] == b['who'] and x['t'] >= b['t']):
                x.setdefault('_t0', x['t']); x['t'] = round(x['t'] + dl, 3)
        for sh in spec.get('shots', []):
            if sh['t'] > b['t'] + 1e-6: sh['t'] = round(sh['t'] + dl, 3)
            elif sh['t'] > b['t'] - 1e-6: sh['t'] = round(sh['t'] + max(0.0, dl - 0.6), 3)   # shot of the action: 0.6 s lead
        spec['seconds'] = round(spec['seconds'] + dl, 3); n_ = F(spec['seconds'], fps); sc.frame_end = n_ - 1
        log.setdefault('notes', []).append(f"t{b['t']} {b['who']} {why} retimed +{dl:.2f}s (approach)")
        return n_

    def safe_turn(ch_, f0_, yaw_, why, goal=None):
        """Planted turn in place to yaw_ starting at f0_; if the turn would sweep furniture/bodies, step to the nearest spot
        (<= 1 m) where the WHOLE turn is clear, as part of the same step-turn (R137 cookie: Max turned his legs into the table)."""
        sc.frame_set(f0_); bpy.context.view_layer.update(); world.invalidate()
        pos_ = tuple(ch_.root.location.xy); y0_ = ch_.root.rotation_euler.z
        if goal is not None: pos_ = tuple(goal)
        if world.sweep(ch_, [(pos_, y0_), (pos_, yaw_)], frame=f0_).depth_m > 0:
            try:
                pos_, mv_ = world.nearest_clear(ch_, pos_, yaw_, frame=f0_, turn_from=y0_, max_r=1.0)
                log.setdefault('notes', []).append(f"{ch_.name} {why}: steps {mv_ / S:.1f} studs to turn clear")
            except ValueError:
                log.setdefault('notes', []).append(f"{ch_.name} {why}: preview found no turn spot; checking keyed alternatives")
        def key(pos, delay):
            sc.frame_set(f0_); lo._hold(ch_, f0_)
            start = f0_ + delay; sc.frame_set(start); lo._hold(ch_, start)
            if (Vector(pos) - ch_.root.location.xy).length > 0.01:
                start = lo.step_to(sc, ch_, pos, start)
            return lo.step_to(sc, ch_, pos, start, goal_yaw=yaw_)
        candidates = [(pos_, delay) for delay in (0, F(.5, fps), F(1, fps))]
        candidates += [((pos_[0] + radius * math.cos(math.radians(deg)), pos_[1] + radius * math.sin(math.radians(deg))), 0)
                       for radius in (.25, .5, 1.) for deg in range(0, 360, 45)]
        for pos, delay in candidates:
            end, hit = motion_trial(sc, world, ch_, lambda: key(pos, delay), f0_, hold_until(ch_, f0_, f0_), log.get('sit_spans', []))
            if end is not None:
                settle[ch_.name] = end
                return end
        log.setdefault('errors', []).append(f"{ch_.name} {why} rejected: {hit}")
        return f0_

    # ---------------- THE ARM RULE: one function for the final gate AND the arm planners (give, face-touch poses) ----------------
    hair = {c_.name: [o for o in c_.hair_pivot.children_recursive if o.type == 'MESH'] for c_ in cast.values()}
    prop_meshes = [o for p in props.values() for o in p.children_recursive if o.type == 'MESH']
    desks = st['desk_tops']
    def near_set(ch, frames):   # every solid set piece within 2.5 m of the character's path over these frames
        frames = list(frames); pts = []
        for f in sorted(set(frames[::6]) | {frames[0], frames[-1]}):
            sc.frame_set(f); pts.append(ch.root.matrix_world.translation.copy())
        out = []
        for q in assets.PLACED:
            if not q['solid']: continue
            x0, x1, y0, y1 = q['rect']
            if any(x0 - 2.5 < p.x < x1 + 2.5 and y0 - 2.5 < p.y < y1 + 2.5 for p in pts):
                out += [o for o in q['pivot'].children_recursive if o.type == 'MESH']
        return out
    def arm_rows(ch, frames, final=True, margin=0.0):
        """(rows the arm gate counts, allowance notes) for `ch` over `frames`: arms vs props, the other bodies, own head/torso/
        hair and nearby set pieces, every frame, minus the agreed R6 allowances (space.py). final=False = a planner asking
        BEFORE the props are baked: props in anyone's hand around these frames are skipped (their keys do not exist yet).
        Everything else is the gate itself. margin (m) tightens every own-body allowance for planners: the final bake moves a
        pinned arm by millimetres, and a handoff accepted at 9.5-10.0 cm of own hair came back 11.8 cm (lunch s02)."""
        frames = list(frames)
        others = [o for c in cast.values() if c is not ch for o in (c.head_mesh, c.torso)]
        mine = [(pr, f0, f1) for piv, side, pr, f0, f1 in grabs if piv in ch.arms_piv]          # props this character holds
        if final: skip = {o for pr, _, _ in mine for o in pr.children_recursive if o.type == 'MESH'}
        else: skip = {o for _, _, pr, f0, f1 in grabs if f0 - 6 <= frames[-1] and f1 + 6 >= frames[0] for o in pr.children_recursive if o.type == 'MESH'}
        meshes = [m for m in prop_meshes if m not in skip] + others + [ch.head_mesh, ch.torso] + hair[ch.name] + near_set(ch, frames)
        reps = [ia.penetration_report(sc, ch.arms, meshes + desks, frames, tol=space.ARM_TOL, box_props=[d.name for d in desks])]
        for pr in ({pr for pr, _, _ in mine} if final else ()):
            windows = [hold_window(grabs, pr, f0, f1) for pp, f0, f1 in mine if pp is pr]
            out = [f for f in frames if not any(a <= f <= z for a, z in windows)]
            if out: reps.append(ia.penetration_report(sc, ch.arms, [o for o in pr.children_recursive if o.type == 'MESH'], out, tol=space.ARM_TOL))
        cf = {f for who, f0, ps in log.get('contact_frames', []) if who == ch.name for f in range(f0 - 2, f0 + 40)}   # face-touch pose frames
        own = {ch.head_mesh.name} | {o.name for o in hair[ch.name]}   # rigid R6 arm to mouth/face must cut the head corner
        def allowed(r):
            if r['f'] in cf and r['prop'] == ch.head_mesh.name and r['depth_m'] <= space.FACE_HEAD_MAX - margin: return 'face-touch head graze (<= 5 cm)'   # 3-axis arm: measured <= 4 cm
            if r['f'] in cf and r['prop'] in own and r['depth_m'] <= space.FACE_HAIR_MAX - margin: return 'face-touch hand in hair (<= 10 cm)'   # was 12-18 cm
            if r['prop'] == ch.torso.name and r['depth_m'] <= OWN_TORSO_MAX - margin: return 'own-torso arm corner'   # agreed R6 rule
            if r['prop'] in own and r['prop'] != ch.head_mesh.name and r['depth_m'] <= space.OWN_HAIR_MAX - margin: return 'own hair accessory brush (<= 10 cm)'
            return None
        # A DROPPED prop starts where the hand held it (centred in the hand block by the hold placement) and needs ~7 frames of
        # free fall to leave it (measured, backyard s02: 22 cm at f+1 .. 3.6 cm at f+7). For the arm that released it, the frames
        # after the release stay part of the hold while the prop is LEAVING: every frame farther from the hand point than the
        # frame before, 8 frames at most. An arm that follows the prop, or a prop that comes back, counts as before.
        leaving = set()
        for piv, side, pr, f0, f1 in (grabs if final else ()):
            if piv not in ch.arms_piv or f1 >= frames[-1] or hold_window(grabs, pr, f0, f1)[1] != f1: continue
            lm_ = ia.limb_mesh(piv).name; d_prev = -1.0
            for fr_ in range(f1, min(f1 + 8, frames[-1]) + 1):
                sc.frame_set(fr_); d_ = (pr.matrix_world.translation - piv.matrix_world @ gr._hand_local(side, None)).length
                if d_ <= d_prev: break
                d_prev = d_; leaving |= {(fr_, lm_, o.name) for o in pr.children_recursive if o.type == 'MESH'}
        bad, why = [], set()
        for rep_ in reps:
            for r in rep_['rows']:
                w_ = 'released prop leaving the hand (<= 8 frames)' if (r['f'], r['limb'], r['prop']) in leaving else allowed(r)
                if w_: why.add(w_)
                else: bad.append(r)
        return bad, sorted(why)

    def arm_plan_bad(ch, frames, core, margin=0.02):
        """What the final arm gate will say about arms keyed just now, in metres (0 = clean): the SAME cleanup the build runs
        later (depenetrate, same meshes and allowances, contacts pinned) and then arm_rows. `core` = the contact frames, asked
        first (cheap reject: cleanup is pinned there). Call inside keyed_trial: a rejected trial restores the cleanup keys too."""
        frames = list(frames); out = 0.0
        for fr_ in (list(core), frames):
            held_ = {o for _, _, pr, f0, f1 in grabs if f0 - 6 <= fr_[-1] and f1 + 6 >= fr_[0] for o in pr.children_recursive if o.type == 'MESH'}
            meshes = [m for m in prop_meshes if m not in held_] + [o for c in cast.values() if c is not ch for o in (c.head_mesh, c.torso)]
            meshes += [ch.head_mesh, ch.torso] + hair[ch.name] + near_set(ch, fr_)
            allow_ = {ch.torso.name: OWN_TORSO_MAX, **{h.name: space.OWN_HAIR_MAX for h in hair[ch.name]}}
            for s_ in 'RL': ia.depenetrate(sc, ch.arm[s_], meshes, fr_, box_props=desks, tol=space.ARM_TOL, label=f'plan {ch.name} {s_}', allowances=allow_)
            out = max((r_['depth_m'] for r_ in arm_rows(ch, fr_, final=False, margin=margin)[0]), default=0.0)
            if out: break
        return out

    # ---------------- beats (in time order) ----------------
    world = space.World(sc, cast, props)   # ONE body-in-space model for every planner (static set pieces)
    face_sched = {c: {0: spec_c.get('face', 'smile')} for c, spec_c in ((c['name'], c) for c in spec['cast'])}
    flap_fr = {c['name']: set() for c in spec['cast']}   # frames holding talk flaps: they follow the face of their moment (rebased below)
    grabs, gaze = list(held), []
    beats = sorted(spec.get('beats', []), key=lambda b: (b['t'], 'down' not in b))   # a character that starts down is down before anything else at that t
    def known_(x):   # R226 story input the scene cannot resolve is dropped with a note, never a crash (factory p8 'grab Coach')
        return isinstance(x, str) and (x in cast or x in props or any(q['name'] == x for q in assets.PLACED))
    for b_ in list(beats):
        if b_.get('who') not in cast:
            log.setdefault('notes', []).append(f"t{b_.get('t')} beat for '{b_.get('who')}' who is not in this scene -> skipped"); beats.remove(b_); continue
        for k_ in ('grab', 'give'):   # (throw reports its own errors)
            v_ = b_.get(k_)
            if isinstance(v_, dict) and (v_.get('prop') not in props or (k_ == 'give' and v_.get('to') not in cast)):
                log.setdefault('notes', []).append(f"t{b_['t']} {b_['who']} {k_} {v_}: not a prop/person in this scene -> dropped"); b_.pop(k_)
        for k_ in ('look', 'turn'):
            v_ = b_.get(k_)
            if isinstance(v_, str) and not known_(v_):
                log.setdefault('notes', []).append(f"t{b_['t']} {b_['who']} {k_} '{v_}': unknown target -> dropped"); b_.pop(k_)
    # AUTO EXPRESSION: a pose with no face picks a matching Roblox library face (critic: 'the same frown in 7 of 16 frames');
    # the writer's own face always wins
    POSE_FACE = {'shock': 'emo:shock', 'hands_up': 'emo:shock', 'cheer': 'emo:joy', 'fist_pump_R': 'emo:joy', 'cower': 'emo:scared',
                 'hands_head': 'emo:scared', 'think_R': 'emo:confused', 'think_L': 'emo:confused', 'facepalm_R': 'emo:disgust',
                 'facepalm_L': 'emo:disgust', 'taunt': 'smug', 'proud': 'smug', 'angry': 'angry', 'sad': 'sad', 'arms_crossed': 'emo:smug',
                 'cover_mouth_R': 'emo:laugh', 'cover_mouth_L': 'emo:laugh', 'wave': 'emo:happy', 'recoil': 'emo:shock', 'gloat': 'smug',
                 'slump': 'sad', 'curious': 'emo:confused'}
    for b_ in beats:
        if isinstance(b_.get('pose'), str) and 'face' not in b_ and b_['pose'] in POSE_FACE and POSE_FACE[b_['pose']] in faces.KINDS:
            b_['face'] = POSE_FACE[b_['pose']]; log.setdefault('notes', []).append(f"t{b_['t']} {b_['who']} {b_['pose']}: auto face {b_['face']}")
    import acting   # AUTOMATIC ACTING LAYER: listener reactions, emotion silhouettes, idle life as ordinary (checked) beats
    beats = acting.inject(spec, beats, log, valid_face=lambda k_: k_ in faces.KINDS)
    beats = acting.face_pass(spec, beats, log, faces.library())   # EXPRESSION RANGE: an exact face ('_lib') per face beat and talk line
    face_seq = {c_['name']: [(0, c_.get('face', 'smile'))] for c_ in spec['cast']}   # the expressions each character really plays (report)
    together = {}   # id(walk beat) -> goal moved beside a partner (walk together)
    for b in beats:
        world.invalidate()   # earlier beats keyed animation: no stale planning poses
        ch = cast[b['who']]; f = F(b['t'], fps); mv = b.get('move', 4)
        if b.get('auto') and ('anim' in b or 'pose' in b) and (settle.get(b['who'], 0) > f - 2 or b['who'] in fallen
                                                               or any(pv in ch.arms_piv and a0 <= f <= a1 and ('R' if pv is ch.arm['R'] else 'L') not in tuple(b.get('_skip', ())) + tuple(b.get('anim_skip', ())) for pv, _, _, a0, a1 in grabs)):
            continue   # automatic acting never interrupts a move still running, a body on the floor or an arm holding a prop (a beat that skips that arm may play)
        if 'walk' in b:
            wl = b['walk'] if isinstance(b['walk'], list) else [b['walk']]
            if len(wl) == 2 and all(isinstance(v, (int, float)) for v in wl): wl = [wl]   # a single point written flat (factory p7)
            sc.frame_set(f); bpy.context.view_layer.update()
            partners = sorted(beats[:beats.index(b)], key=lambda x: (cast[x['who']].root.matrix_world.translation - ch.root.matrix_world.translation).length)
            for x in partners:   # WALK TOGETHER: nearest earlier partner, so three walkers do not request the same offset stop.
                xl = x.get('walk') if isinstance(x.get('walk'), list) else [x.get('walk')]   # stop BESIDE them, on my side of
                if (x['who'] == b['who'] or not xl or not isinstance(xl[-1], (list, tuple)) or not wl   # their path (blind2_street:
                        or not isinstance(wl[-1], (list, tuple)) or abs(x['t'] - b['t']) > 0.5               # goals 1.4 studs apart,
                        or math.hypot(wl[-1][0] - xl[-1][0], wl[-1][1] - xl[-1][1]) >= 4.5): continue        # heads met 7.5 cm)
                xl = xl[:-1] + [together.get(id(x), xl[-1])]   # a partner already moved beside someone: line up on THAT spot
                sc.frame_set(f); p0 = cast[x['who']].root.matrix_world.translation / S; me = ch.root.matrix_world.translation / S
                dx, dy = xl[-1][0] - p0.x, xl[-1][1] - p0.y; L_ = math.hypot(dx, dy) or 1.0
                side = 1 if dx * (me.y - p0.y) - dy * (me.x - p0.x) > 0 else -1
                wl = wl[:-1] + [[xl[-1][0] - side * dy / L_ * 4.5, xl[-1][1] + side * dx / L_ * 4.5]]   # R6 + arms = 4 studs wide
                together[id(b)] = wl[-1]
                log.setdefault('notes', []).append(f"t{b['t']} {b['who']} walks with {x['who']}: stops beside them at {wl[-1][0]:.1f}, {wl[-1][1]:.1f}")
                break
            walk_to(ch, b['who'], wl, f, b, beats)
        if 'sit' in b:   # sit on a named seat piece: route to its front, then locomotion.sit_down
            piece = next((q['pivot'] for q in assets.PLACED if q['name'] == b['sit']), None); ent = None
            if piece is None:   # 'chair' / 'bench' / 'sofa' -> the nearest piece whose name starts with that word
                me = ch.root.matrix_world.translation
                cands = [q for q in assets.PLACED if q['name'].lower().startswith(b['sit'].lower())]
                if cands:
                    piece = min(cands, key=lambda q: math.hypot((q['rect'][0] + q['rect'][1]) / 2 - me.x, (q['rect'][2] + q['rect'][3]) / 2 - me.y))['pivot']
            if piece is None:   # the set has no such seat (blind4_cafe: 'kitchen_set_seat', a set with 0 seats): the character stays
                # standing and the story plays on; the note names what CAN be sat on (was a hard error = the whole scene failed)
                seats_ = sorted({q['name'] for q in assets.PLACED if any(w_ in q['name'].lower() for w_ in ('seat', 'chair', 'bench', 'sofa', 'stool', 'bed', 'couch'))})
                log.setdefault('notes', []).append(f"t{b['t']} {b['who']} sit: no piece '{b['sit']}' in this set -> stays standing (seats here: {', '.join(seats_[:8]) or 'none'})")
            else:
                st_ = affordances.seat(piece); (sx, sy), sz, syaw = st_['pos'], st_['z'], st_['yaw']
                piece = st_['piece']
                log.setdefault('seat_pieces', []).append(piece.name)
                try:
                    ent = affordances.seat_entry(world, ch, piece, st_, frame=f)
                except ValueError as e:
                    log.setdefault('errors', []).append(f"t{b['t']} {b['who']} sit: {e}"); ent = None
            if piece is not None and ent is not None:
                (sx, sy), sz, syaw = st_['pos'], st_['z'], st_['yaw']
                if ent.get('pullout_m'):
                    if 'obstacles' in st: st['obstacles'][:] = assets.obstacles()
                    log.setdefault('notes', []).append(f"{piece.name} pulled out {ent['pullout_m']:.2f} m for entry and knees")
                back = ent['back_studs']; here = tuple(ch.root.matrix_world.translation.xy)
                first_ = not any(x['who'] == b['who'] and x['t'] < b['t'] for x in beats)
                tgt0 = ent['via'] if 'via' in ent else ent['xy']
                if first_ and b['t'] <= 1.0 and math.hypot(here[0] - tgt0[0], here[1] - tgt0[1]) > 2.0 * S:
                    # 'sits at t0.2' = the writer means she is AT her seat: a cross-room approach (classroom 13 m, homework 14 s)
                    # stalled every later beat via the retime. Pre-stage at the entry from frame 0 (logged).
                    d0_ = math.hypot(here[0] - tgt0[0], here[1] - tgt0[1]) / S
                    r_ = ch.root; r_.location.x, r_.location.y = tgt0[0], tgt0[1]; r_.rotation_euler.z = syaw
                    for fr_ in (0, f): r_.keyframe_insert('location', frame=fr_); r_.keyframe_insert('rotation_euler', frame=fr_)
                    world.invalidate(); here = tuple(tgt0)
                    log.setdefault('notes', []).append(f"t{b['t']} {b['who']} pre-staged at {piece.name} (sit at scene start, was {d0_:.0f} studs away)")
                if 'via' in ent:   # no room to turn in front of the seat (desk rows): aisle spot beside it, turn there, side-step in
                    fe_ = walk_to(ch, b['who'], [(ent['via'][0] / S, ent['via'][1] / S)], f, b, beats) or f
                    fe_ = lo.step_to(sc, ch, ent['via'], fe_, goal_yaw=syaw)
                    fe_ = lo.step_to(sc, ch, ent['xy'], fe_ + 1)
                    log.setdefault('notes', []).append(f"{b['who']} sits via the aisle: side-step {ent['sidestep_m'] / S:.1f} studs")
                else:
                    far = math.hypot(here[0] - ent['xy'][0], here[1] - ent['xy'][1]) > 0.5 * S
                    fe_ = (walk_to(ch, b['who'], [(ent['xy'][0] / S, ent['xy'][1] / S)], f, b, beats) or f) if far else f
                    fe_ = lo.step_to(sc, ch, ent['xy'], fe_, goal_yaw=syaw)
                f_sit = lo.sit_down(sc, ch, (sx, sy), sz, math.degrees(syaw), fe_, back_studs=back, entry_xy=ent['xy'])
                seated[b['who']] = ((sx, sy), sz, math.degrees(syaw)); settle[b['who']] = f_sit; seat_back[b['who']] = ent
                hits_ = [h for fr in range(fe_, f_sit + 1) for h in world.body_hits(ch, fr, exempt={piece.name})]
                if hits_: log.setdefault('errors', []).append(f"{b['who']} sit transition hits {hits_[0][2]}")
                log.setdefault('sit_spans', []).append([b['who'], fe_, n + 999, next((q['name'] for q in assets.PLACED if q['pivot'] is piece), piece.name)])   # whole sitting motion (legs rise forward)
                late_ = f_sit - (f + F(1.0, fps))   # 'sit' = walk there + sit; a long approach (around a coffee table) must not
                if late_ > 0: n = retime_after(b, late_, 'sit')   # leave the next beats acting mid-walk or the scene ending first (R150)
                for hand_ in 'RL':   # holding something? lift that arm to carry height once seated (lap = under the desk)
                    if any(pv is ch.arm[hand_] and a0 <= f_sit <= a1 for pv, sd, pp, a0, a1 in grabs):
                        poses.beat(sc, ch, {hand_: poses.LIB['carry_' + hand_][hand_]}, f_sit + 5, move=5,
                                   skip=tuple(c for c in ('R', 'L', 'legR', 'legL', 'head', 'body') if c != hand_))
        if b.get('stand') and b['who'] in seated:
            (sx, sy), sz, sy_deg = seated.pop(b['who'])
            ent_ = seat_back[b['who']]; start_ = max(f, settle.get(b['who'], 0))
            settle[b['who']] = lo.stand_up(sc, ch, (sx, sy), sz, sy_deg, start_, frames=18,
                                             back_studs=ent_['back_studs'], entry_xy=ent_['xy'])
            own_ = {sp[3] for sp in log.get('sit_spans', []) if sp[0] == b['who'] and sp[1] <= start_ <= sp[2]}
            hits_ = [h for fr in range(start_, settle[b['who']] + 1) for h in world.body_hits(ch, fr, exempt=own_)]
            if hits_: log.setdefault('errors', []).append(f"{b['who']} stand transition hits {hits_[0][2]}")
            for sp_ in log.get('sit_spans', []):
                if sp_[0] == b['who'] and sp_[2] > n: sp_[2] = settle[b['who']]
        if 'fall' in b or b.get('get_up'):   # tip over backward from the feet (rotation about the character's side axis) / reverse
            r = ch.root; f_ = max(f, settle.get(b['who'], 0)); sc.frame_set(f_ - 2)
            if 'fall' in b:
                back = -1 if b.get('fall') != 'forward' else 1
                origin_ = tuple(r.location.xy); yaw_ = r.rotation_euler.z
                # Trials include planted restaging steps; restore every animated object so rejected trials leave no keys.
                objs_ = [ch.root] + list(ch.root.children_recursive)
                saved_ = [(o, o.animation_data.action if o.animation_data else None, o.location.copy(), o.rotation_euler.copy()) for o in objs_]
                def restore_fall_trial():
                    for o_, action_, loc_, rot_ in saved_:
                        trial_ = o_.animation_data.action if o_.animation_data else None
                        if o_.animation_data: o_.animation_data.action = action_
                        if trial_ is not None and trial_ is not action_ and trial_.users == 0: bpy.data.actions.remove(trial_)
                        o_.location = loc_; o_.rotation_euler = rot_
                    sc.frame_set(f_ - 2); world.invalidate()
                def fall_trial(side_, xy_):
                    restore_fall_trial()
                    for o_, action_, _, _ in saved_:
                        if action_ is not None: o_.animation_data.action = action_.copy()
                    start_ = lo.step_to(sc, ch, xy_, f_ - 2) + 2 if xy_ != origin_ else f_
                    poses.beat(sc, ch, {'R': (20, 70), 'L': (20, 70), 'legR': (10, 8), 'legL': (-6, 8), 'head': (-10, 0, 0)}, start_ + 5, move=3)
                    lo.fall(sc, ch, start_, back=side_ == -1); world.invalidate()
                    # furniture AND the other actors at the same frames (body_hits = furniture only: Tom restaged 0.5 m and fell
                    # onto Maya's feet, whose later jump was then rejected, blind3_kitchen s02, REPEAT since R164), then the
                    # spread fall arms through THE ARM GATE (22.4 cm in Maya's head)
                    mh_ = world.motion_hit(ch, range(f_ - 2, start_ + 13))
                    if mh_: hits_ = [mh_]
                    else:   # arms: after the build's own cleanup (a bare arm_rows rejected a fall beside a crate that cleanup clears: gym s02)
                        bad_ = arm_plan_bad(ch, range(f_ - 2, start_ + 13), range(start_ + 9, start_ + 13), margin=0.0)   # no pinned contact: the final cleanup is this cleanup
                        hits_ = [(start_, 'arm', 'the arm gate', bad_)] if bad_ else []
                    return start_, hits_
                start_, hits = fall_trial(back, origin_)
                moved_ = 0.0
                if hits:
                    for radius_ in (.25, .5, .75):
                        for deg_ in range(0, 360, 45):
                            xy_ = (origin_[0] + radius_ * math.cos(math.radians(deg_)), origin_[1] + radius_ * math.sin(math.radians(deg_)))
                            # Check the standing approach before keying and checking the complete steps + fall.
                            restore_fall_trial()
                            if world.sweep(ch, [(origin_, yaw_), (xy_, yaw_)], frame=f_ - 2).depth_m: continue
                            start_, hits = fall_trial(back, xy_)
                            if not hits: moved_ = radius_; break
                        if not hits: break
                if hits:
                    back = -back; start_, hits = fall_trial(back, origin_)
                    log.setdefault('notes', []).append(f"t{b['t']} {b['who']} falls the other way (the asked side is blocked)")
                if moved_:
                    log.setdefault('notes', []).append(f"t{b['t']} {b['who']} restages {moved_:.2f} m to keep the requested fall direction")
                    n = retime_after(b, start_ - f_, 'fall restage')
                if hits: log.setdefault('errors', []).append(f"t{b['t']} {b['who']} fall hits {hits[0][2]} both ways")
                log.setdefault('fall_spans', []).append([b['who'], start_, n + 999, 'forward' if back == 1 else 'backward'])
                settle[b['who']] = start_ + 12; fallen[b['who']] = back
            elif b['who'] in fallen:
                back = fallen.pop(b['who'])
                curled_ = b['who'] in log.get('curled', {})
                if curled_:   # lying curled on its side (knockback pose / down): roll onto the back, then the ordinary get-up
                    log['curled'].pop(b['who']); settle[b['who']] = fight.get_up_curled(sc, ch, f_)
                    for sp_ in log.get('fall_spans', []):
                        if sp_[0] == b['who'] and sp_[2] > n: sp_[2] = f_
                else:
                    poses.beat(sc, ch, {**poses.LIB['idle'], 'legR': (0, 0), 'legL': (0, 0)}, f_ + 10, move=6)   # explicit: straighten the fall legs
                    settle[b['who']] = lo.get_up(sc, ch, f_, back=back == -1)   # resting on the floor throughout (also after knockbacks)
                    for sp_ in log.get('fall_spans', []):
                        if sp_[0] == b['who'] and sp_[2] > n: sp_[2] = f_
        if 'give' in b:   # hand a held prop to another character: both hands meet between them, the prop changes hands
            gv = b['give']; pr = props[gv['prop']]; taker = cast[gv['to']]
            gi = next((k for k, (pv, sd, pp, a0, a1) in enumerate(grabs) if pp is pr and pv in ch.arms_piv and a0 <= f <= a1), None)
            if gi is None: log.setdefault('errors', []).append(f"t{b['t']} {b['who']} give {gv['prop']}: not holding it")
            else:
                f_ = max(f, settle.get(b['who'], 0), settle.get(gv['to'], 0))
                sc.frame_set(f_); bpy.context.view_layer.update()
                a = ch.root.matrix_world.translation; c_ = taker.root.matrix_world.translation
                if b['who'] in seated and (a - c_).length > 2 * math.hypot(ia.TIP, 0.5) * S + 0.5 * S:   # seated rows apart: no arm
                    (sx, sy), sz, sy_deg = seated.pop(b['who']); ent_ = seat_back[b['who']]   # reaches -> stand up, walk over (R186)
                    f_ = lo.stand_up(sc, ch, (sx, sy), sz, sy_deg, f_, frames=18, back_studs=ent_['back_studs'], entry_xy=ent_['xy'])
                    settle[b['who']] = f_
                    for sp_ in log.get('sit_spans', []):
                        if sp_[0] == b['who'] and sp_[2] > n: sp_[2] = f_
                    log.setdefault('notes', []).append(f"t{b['t']} {b['who']} stands up to give {gv['prop']} ({(a - c_).length / S:.1f} studs, out of reach)")
                    sc.frame_set(f_); bpy.context.view_layer.update(); a = ch.root.matrix_world.translation
                if (a - c_).length > staging.d('give_trigger') and b['who'] not in seated:   # too far: a STANDING giver walks up first
                    fe_ = walk_to(ch, b['who'], [gv['to']], f_, b, beats); f_ = (fe_ or f_) + 2
                    sc.frame_set(f_); bpy.context.view_layer.update(); a = ch.root.matrix_world.translation
                if (a - c_).length > staging.d('give_trigger') + 0.5 * S and b['who'] not in seated:   # walk-up ended across a counter or
                    sc.frame_set(f_); bpy.context.view_layer.update(); world.invalidate()
                    routes_ = give_stops(world, ch, tuple(a.xy), tuple(c_.xy), f_, st, b.get('speed', 9.5), fps)
                    failures_ = []
                    for route_ in routes_:
                        errors_ = len(log.get('errors', []))
                        fe_ = walk_to(ch, b['who'], [[p_[0] / S, p_[1] / S] for p_ in route_[1:]], f_, b, beats)
                        if fe_:
                            log.setdefault('notes', []).append(f"t{b['t']} {b['who']} re-approaches {gv['to']} around the furniture")
                            f_ = fe_ + 2; sc.frame_set(f_); bpy.context.view_layer.update(); a = ch.root.matrix_world.translation; break
                        failures_ += log.get('errors', [])[errors_:]
                        del log.get('errors', [])[errors_:]
                    else:
                        log.setdefault('errors', []).extend(failures_[-1:] or [f"t{b['t']} give {gv['prop']}: no clear re-approach route"])
                sc.frame_set(f_)   # a standing giver turns to face the taker with planted steps (seated: arms only)
                if b['who'] not in seated and b['who'] not in fallen:
                    f_ = safe_turn(ch, f_, math.atan2(c_.x - a.x, -(c_.y - a.y)), 'giver turn')
                if f_ > f + 2: n = retime_after(b, f_ - f, f"give {gv['prop']}")   # the walk-up ran long: later beats wait
                sc.frame_set(f_); bpy.context.view_layer.update()
                gpv, gsd = grabs[gi][0], grabs[gi][1]
                rch = math.hypot(ia.TIP, 0.5) * S; P1 = gpv.matrix_world.translation.copy()
                if gv['to'] not in seated and gv['to'] not in fallen:   # a STANDING taker faces the giver too (planted steps):
                    sc.frame_set(f_); bpy.context.view_layer.update()  # a walk-up heading 'cheated' toward the camera made the
                    tq = taker.root.matrix_world.translation; gq = ch.root.matrix_world.translation   # taker reach across its own chest
                    f_t = safe_turn(taker, max(f_ - 8, settle.get(gv['to'], 0)), math.atan2(gq.x - tq.x, -(gq.y - tq.y)), 'taker turn')
                    if f_t > f_: f_ = f_t
                mover = taker   # Recheck reach after clear-stop and turn adjustments for standing pairs too.
                if mover is not None and gv['to'] not in seated and gv['to'] not in fallen:   # comfortable handoff needs the nearest
                    sc.frame_set(f_); bpy.context.view_layer.update()                          # shoulders ~3.6 studs apart (closer: the
                    gps = [gpv.matrix_world.translation.copy()]                               # only common points are far off to the (the HOLDING arm, Codex #11)
                    tq = mover.root.matrix_world.translation.copy()                           # side, up or down - R134/R135 loop)
                    dd_now = min((mover.arm[h_].matrix_world.translation - g_).length for h_ in 'RL' for g_ in gps)
                    want = staging.d('handoff_shoulders')
                    if abs(dd_now - want) > 0.25 * S:
                        g_ = min(gps, key=lambda g: (g - tq).length); dirv = Vector((tq.x - g_.x, tq.y - g_.y)); dirv.normalize()
                        goal_ = (tq.x + dirv.x * (want - dd_now), tq.y + dirv.y * (want - dd_now)); yaw_ = math.atan2(-dirv.x, dirv.y)
                        try:
                            goal_, _ = world.nearest_clear(mover, goal_, yaw_, frame=f_)
                            f_ = safe_turn(mover, f_, yaw_, 'handoff restage', goal=goal_) + 1
                            log.setdefault('notes', []).append(f"{mover.name} steps to handoff distance ({dd_now / S:.1f} -> {want / S:.1f} studs)")
                        except ValueError as e:
                            log.setdefault('errors', []).append(f"t{b['t']} give: {mover.name} cannot reach handoff distance ({e})")
                if f_ > f + 2: n = retime_after(b, f_ - f, f"give {gv['prop']}")
                for who_, other_ in ((gv['to'], ch), (b['who'], taker)):   # a SEATED party twists its upper body toward the other
                    if who_ not in seated: continue                        # (a seated taker otherwise reaches back across her chest)
                    pc = cast[who_]; sc.frame_set(f_); bpy.context.view_layer.update()
                    fw = pc.root.matrix_world.to_3x3() @ Vector((0, -1, 0)); to_ = other_.root.matrix_world.translation - pc.root.matrix_world.translation
                    tw = math.atan2(fw.x * to_.y - fw.y * to_.x, fw.x * to_.x + fw.y * to_.y)
                    tw = max(-math.radians(45), min(math.radians(45), tw)); up_ = pc.upper; z0_ = up_.rotation_euler.z
                    for fr_, z_ in ((f_ - 8, z0_), (f_ - 1, z0_ + tw), (f_ + 10, z0_ + tw), (f_ + 22, z0_)):
                        up_.rotation_euler.z = z_; up_.keyframe_insert('rotation_euler', frame=fr_)
                    log.setdefault('notes', []).append(f"{who_} twists {math.degrees(tw):.0f} deg toward {other_.name} for the handoff")
                bpy.context.view_layer.update()
                sc.frame_set(f_); bpy.context.view_layer.update(); P1 = gpv.matrix_world.translation.copy()   # AFTER the twist/steps (was ~38 cm stale)
                # MEETING POINT: candidates around the circle where both rigid arms reach exactly; each candidate is solved for
                # BOTH arms with the 3-axis solver and both arm boxes are checked against the scene and the other bodies (the
                # old 'lowest point' sent a seated taker's hand down beside her chair: 2.3 cm, R133). Prefer a natural height.
                def ring(P2):
                    dd = (P2 - P1).length; mid = (P1 + P2) / 2
                    if dd >= 2 * rch: return [mid]
                    u = (P2 - P1).normalized(); e1 = u.orthogonal().normalized(); e2 = u.cross(e1)
                    r_ = math.sqrt(max(0.0, rch * rch - (dd / 2) ** 2))
                    return [mid + (e1 * math.cos(math.radians(k)) + e2 * math.sin(math.radians(k))) * r_ for k in range(0, 360, 20)]
                def arm_at(pc, pv, sd, fr, tgt):
                    PW_, T_ = ia._pivot_frame(sc, pv, fr)
                    rx_, ry_, rz_, res_, ok_ = ia.solve_tip(PW_, pv.location, sd, tgt, ia.LAST_POSE.get(pv.name))
                    if ok_:
                        (rx_, ry_, rz_), _ = clipping_twist(sc, pc, pv, sd, fr, tgt,
                                                           [o for o in cast.values() if o is not pc], head_lim=.01)
                    mesh = next(o for o in pv.children if o.type == 'MESH')
                    return ok_, PW_ @ T_ @ Euler((math.radians(rx_), math.radians(ry_), math.radians(rz_))).to_matrix().to_4x4() @ mesh.matrix_local, mesh
                chest = (P1.z + taker.upper.matrix_world.translation.z + 1.6 * S) / 2   # between the giver's shoulder and the taker's chest
                def meet_cands():
                    nonlocal P1
                    sc.frame_set(f_); bpy.context.view_layer.update(); P1 = gpv.matrix_world.translation.copy()
                    cands_ = []
                    for hs in ([gv['hand']] if gv.get('hand') else 'RL'):
                        pv2, sd2 = taker.arm[hs], rig.SIDE[hs]; P2_ = pv2.matrix_world.translation.copy()
                        for Mc in ring(P2_):
                            ok1, M1, m1 = arm_at(ch, gpv, gsd, f_, Mc); ok2, M2, m2 = arm_at(taker, pv2, sd2, f_ + 1, Mc)
                            if not (ok1 and ok2): continue
                            c1 = world.limb_hits(m1, M1, f_, owner=ch); c2 = world.limb_hits(m2, M2, f_ + 1, owner=taker)
                            clash = c1.depth_m + c2.depth_m
                            cands_.append((clash * 100 + abs(Mc.z - chest) + 0.3 * (Mc - (P1 + P2_) / 2).length, hs, Mc))
                    cands_.sort(key=lambda c_: c_[0])
                    return cands_
                def key_give(th, M):
                    tpv, tsd = taker.arm[th], rig.SIDE[th]
                    # Present after the approach: this target must not pull the prop through the receiver during the turn.
                    sc.frame_set(f_ - 12); gpv.keyframe_insert('rotation_euler', frame=f_ - 12)
                    ia.key_tip(sc, gpv, gsd, f_, M, tol=0.03, label='give', rx_rng=(-200, 40), ry_rng=(-130, 130))
                    # same meeting point, least-clipping twist for BOTH arms (own torso/head + every other body): continuity
                    # alone keyed Hale's take 14.3 cm into his own torso and Leo's give 7.9 cm into his head (R141 Codex #2.1/2.2)
                    least_clipping_twist(sc, ch, gpv, gsd, f_, M, [o for o in cast.values() if o is not ch], head_lim=0.01)   # no face-touch allowance in a handoff
                    sc.frame_set(f_ - 12); tpv.keyframe_insert('rotation_euler', frame=f_ - 12)   # receive before the prop reaches the resting arm
                    ia.key_tip(sc, tpv, tsd, f_ + 1, M, tol=0.03, label='take', rx_rng=(-200, 40), ry_rng=(-130, 130))
                    least_clipping_twist(sc, taker, tpv, tsd, f_ + 1, M, [o for o in cast.values() if o is not taker], head_lim=0.01)
                    poses.beat(sc, taker, {th: poses.LIB['carry_' + th][th]}, f_ + 9, move=6,
                               skip=tuple(x for x in ('R', 'L', 'legR', 'legL', 'head', 'body') if x != th))
                    poses.beat(sc, ch, {'R': (0, 3), 'L': (0, 3)}, f_ + 7, move=5, skip=('legR', 'legL', 'head', 'body'))   # the giver's hand is OUT by the end of the 6-frame transfer tail (was f+9: 6.6 cm in the lunch box lid one frame after it, lunch s02)
                def give_bad():   # what THE ARM GATE will say about this keyed handoff (reach, contact, release), both characters
                    return max(arm_plan_bad(c_, range(f_ - 12, f_ + 14), range(f_ - 1, f_ + 3)) for c_ in (ch, taker))
                # A meeting point is ACCEPTED only when the keyed arms pass the arm gate itself (the old planner keyed its best
                # estimate "for the gate to judge": park 18.2, backyard 14.1, lunch 11.8 cm in own hair, 5 rounds R158-R199)
                arms_ = list(ch.arms_piv) + list(taker.arms_piv); pick_ = None; tried_g = []
                yaw0_ = ch.root.rotation_euler.z; f0_g = f_
                # No clean point facing the taker squarely (a right-to-right pass sends the rigid arm across the giver's own chest:
                # park s01, 14 points, 14-17 cm in her torso) -> the standing giver turns the HOLDING shoulder toward the taker
                for off_ in (0, 20, -20, 40, -40):
                    if off_:
                        if b['who'] in seated or b['who'] in fallen: break
                        f_ = safe_turn(ch, f_, yaw0_ + math.radians(off_), 'giver shoulder turn') + 1
                    for _, th_, M_ in meet_cands()[:14]:
                        bad_ = keyed_trial(sc, arms_, lambda: key_give(th_, M_), give_bad)
                        if bad_ == 0: pick_ = (th_, M_); break
                        if bad_ is not None: tried_g.append((bad_, th_, M_, f_))
                    if pick_ is not None:
                        if off_: log.setdefault('notes', []).append(f"t{b['t']} {b['who']} turns the holding shoulder {off_} deg for a clean handoff")
                        break
                if pick_ is None and gv['to'] in seated and gv['to'] not in fallen:   # R222 no clean handoff to a SEATED taker (a
                    (tx_, ty_), tz_, tyd_ = seated.pop(gv['to']); te_ = seat_back[gv['to']]   # chest-high bed: the raised arm went
                    f_ = lo.stand_up(sc, taker, (tx_, ty_), tz_, tyd_, f_, frames=18, back_studs=te_['back_studs'],   # through her own
                                     entry_xy=te_['xy']) + 2                                                          # hair) -> the
                    settle[gv['to']] = f_                                                                             # taker stands
                    for sp_ in log.get('sit_spans', []):                                                              # up to receive
                        if sp_[0] == gv['to'] and sp_[2] > n: sp_[2] = f_
                    log.setdefault('notes', []).append(f"t{b['t']} {gv['to']} stands up to receive {gv['prop']} (no clean seated handoff)")
                    for _, th_, M_ in meet_cands()[:14]:
                        bad_ = keyed_trial(sc, arms_, lambda: key_give(th_, M_), give_bad)
                        if bad_ == 0: pick_ = (th_, M_); tried_g = []; break
                        if bad_ is not None: tried_g.append((bad_, th_, M_, f_))
                if f_ > f0_g: n = retime_after(b, f_ - f, f"give {gv['prop']}")
                if pick_ is None and tried_g:   # none is clean: keep the least-bad one, the gate will report it (never silent)
                    bad_, th_, M_, fb_ = min(tried_g, key=lambda t_: (t_[3] != f_, t_[0])); pick_ = (th_, M_)
                    try: key_give(th_, M_)
                    except AssertionError: pick_ = None   # reachable only from an earlier stance (blind3_classroom s01 crashed here)
                    log.setdefault('notes', []).append(f"t{b['t']} give {gv['prop']}: no meeting point passes the arm gate ({len(tried_g)} keyed, least {bad_ * 100:.1f} cm)")
                elif pick_ is not None and tried_g:
                    log.setdefault('notes', []).append(f"t{b['t']} give {gv['prop']}: meeting point {len(tried_g) + 1} passes the arm gate (first clipped {tried_g[0][0] * 100:.1f} cm)")
                if pick_ is None:
                    log.setdefault('errors', []).append(f"t{b['t']} give {gv['prop']}: no meeting point both arms reach")
                else:
                    th = pick_[0]; tpv, tsd = taker.arm[th], rig.SIDE[th]
                    pv, sd, pp, a0, a1 = grabs[gi]; grabs[gi] = (pv, sd, pp, a0, f_)
                    grabs.append((tpv, tsd, pr, f_ + 1, END))
                    settle[gv['to']] = f_ + 9
                    log.setdefault('touch_spans', []).append([b['who'], gv['to'], f_ - 14, f_ + 9])   # L1 crowd check: both hands are on the prop here (their own arm gate judges it)
        if 'throw' in b:   # THROW a held prop: {"prop", "to": character | [x, y] | piece | prop, "catch": true|false, "hand", "style", "react", "miss"}
            tw = b['throw'] if isinstance(b['throw'], dict) else {}; pr = props.get(tw.get('prop')); to = tw.get('to'); who = b['who']
            gi = next((k for k, (pv, sd, pp, a0, a1) in enumerate(grabs) if pp is pr and pv in ch.arms_piv and a0 <= f <= a1), None)
            piece_ = next((q for q in assets.PLACED if q['name'] == to), None) if isinstance(to, str) else None
            if pr is None or gi is None: log.setdefault('errors', []).append(f"t{b['t']} {who} throw {tw.get('prop')}: not holding it")
            elif not (isinstance(to, (list, tuple)) or to in cast or to in props or piece_): log.setdefault('errors', []).append(f"t{b['t']} {who} throw: unknown target {to!r}")
            elif who in fallen: log.setdefault('errors', []).append(f"t{b['t']} {who} throw: lying on the floor")
            else:
                pv, sd, _, a0, _ = grabs[gi]; h = 'R' if pv is ch.arm['R'] else 'L'
                taker = cast[to] if isinstance(to, str) and to in cast else None
                kind = ('catch' if tw.get('catch', True) and not tw.get('miss') else 'land' if tw.get('miss') else 'hit_char') if taker else 'hit_prop' if to in props else 'land'
                th = None
                if kind == 'catch':   # the catching hand: asked, else a free one (right first)
                    free_ = [s_ for s_ in 'RL' if not any(g_[0] is taker.arm[s_] and g_[4] >= f for g_ in grabs)]
                    th = tw.get('catch_hand') if tw.get('catch_hand') in free_ else (free_[0] if free_ else None)
                    if th is None or to in fallen:
                        log.setdefault('notes', []).append(f"t{b['t']} {to} cannot catch {tw['prop']} (hands full / on the floor) -> it hits them"); kind = 'hit_char'
                f_ = max(f, settle.get(who, 0), a0 + 8, settle.get(to, 0) if taker else 0)
                sc.frame_set(f_); bpy.context.view_layer.update()
                a = ch.root.matrix_world.translation.copy()
                if taker: c_ = taker.root.matrix_world.translation.copy(); txy = (c_.x, c_.y)
                elif to in props: c_ = props[to].matrix_world.translation; txy = (c_.x, c_.y)
                elif piece_: x0, x1, y0, y1, _top = assets.support(to); txy = ((x0 + x1) / 2, (y0 + y1) / 2)
                else: txy = (to[0] * S, to[1] * S)
                if kind == 'land' and taker:   # a MISS: past the catcher's reaching hand, onto the floor behind them
                    u_ = (Vector(txy) - a.xy).normalized(); d_m = max(1.0, (Vector(txy) - a.xy).length)   # the line to the landing spot must clear the catcher's body (torso half 0.5 m + ball) where it passes them
                    lat_ = Vector((-u_.y, u_.x)) * (max(1.1 * S, 1.0 * (d_m + 2.6 * S) / d_m) * (1 if tw.get('miss') != 'L' else -1))
                    txy = tuple(Vector(txy) + u_ * 2.6 * S + lat_)
                    bd_ = st.get('bounds')
                    if bd_: txy = (min(max(txy[0], bd_[0] + 0.4), bd_[1] - 0.4), min(max(txy[1], bd_[2] + 0.4), bd_[3] - 0.4))
                if who not in seated:   # face the target (planted turn), the catcher faces the thrower
                    f_ = safe_turn(ch, f_, math.atan2(txy[0] - a.x, -(txy[1] - a.y)), 'throw turn')
                ft_ = f_
                if taker and kind != 'hit_char' and to not in seated and to not in fallen:
                    ft_ = safe_turn(taker, max(f, settle.get(to, 0)), math.atan2(a.x - c_.x, -(a.y - c_.y)), 'catch turn')
                dist = math.hypot(txy[0] - a.x, txy[1] - a.y)
                nf = max(9, round(min(1.3, max(0.42, dist / 6.5)) * fps))   # flight frames: ~6.5 m/s, 0.42..1.3 s
                fr = max(f_ + 8, ft_ + 8 - nf); fc = fr + nf                # wind-up 8 frames, release at fr, arrival at fc
                if fr - 8 > f: n = retime_after(b, fr - 8 - f, f"throw {tw['prop']}")
                if fc + 16 > n - 1:   # the scene must not end with the prop in the air
                    spec['seconds'] = round((fc + 18) / fps, 3); n = F(spec['seconds'], fps); sc.frame_end = n - 1
                    log.setdefault('notes', []).append(f"t{b['t']} throw {tw['prop']}: scene lengthened to {spec['seconds']}s for the flight")
                over_ = tw.get('style', 'over' if kind in ('hit_char', 'hit_prop') or dist > 7.0 else 'under') == 'over'
                def arm_keys(c_h, piv_, rows_):   # exact shoulder keys (frame, (raise, out)); None = the pose it has there
                    for fr_, v_ in rows_:
                        sc.frame_set(fr_)
                        if v_ is not None: piv_.rotation_euler = poses.euler(c_h[0], c_h[1], v_)
                        piv_.keyframe_insert('rotation_euler', frame=fr_)
                rest_ = poses.LIB['idle'].get(h, (0, 0))
                # release at the arm's swing: wind back (under) / up (over), the prop leaves the hand at fr, follow-through, relax
                arm_keys((ch, h), pv, [(fr - 8, None), (fr - 3, (185, 6) if over_ else (-42, 10)), (fr, (128, 4) if over_ else (52, 6)),
                                       (fr + 3, (45, 2) if over_ else (112, 4)), (fr + 13, rest_)])   # under: the follow-through trails the ball (98 deg at fr+3 swept through it)
                grabs[gi] = (pv, sd, pr, a0, fr)
                c0_, rad_, top0_ = prop_cyl(pr)
                rec = {'prop': pr, 'f_rel': fr, 'f_end': fc, 'kind': kind, 'rad': min(rad_, 0.3)}
                if kind == 'catch':
                    tpv = taker.arm[th]; rec['catcher'] = (tpv, rig.SIDE[th])
                    carry_ = poses.LIB['carry_' + th][th]
                    arm_keys((taker, th), tpv, [(fc - 9, None), (fc - 1, (74, 6)), (fc, (72, 6)), (fc + 3, (58, 6)), (fc + 10, carry_)])
                    grabs.append((tpv, rig.SIDE[th], pr, fc, END)); settle[to] = max(settle.get(to, 0), fc + 10)
                elif kind == 'land':
                    rec['xy'] = txy
                    if taker and to not in seated and to not in fallen:   # the missed catch: a late reach beside the flight
                        s_m = 'R' if not any(g_[0] is taker.arm['R'] and g_[4] >= f for g_ in grabs) else 'L'
                        if not any(g_[0] is taker.arm[s_m] and g_[4] >= f for g_ in grabs):
                            arm_keys((taker, s_m), taker.arm[s_m], [(fc - 12, None), (fc - 5, (80, 12)), (fc + 2, (95, 4)), (fc + 14, poses.LIB['idle'].get(s_m, (0, 0)))])
                            settle[to] = max(settle.get(to, 0), fc + 14)
                else:
                    rec['target'] = taker if kind == 'hit_char' else props[to]
                    if kind == 'hit_prop': rec['rest'] = (props[to].location.copy(), props[to].rotation_euler.copy())
                    elif not any(x['who'] == to and abs(x['t'] - fc / fps) < 0.3 and any(k_ in x for k_ in ('pose', 'fall', 'knockback', 'anim')) for x in beats):
                        # the hit character REACTS (an ordinary beat, so every planner and gate sees it): recoil, or "react": "fall"
                        rb_ = {'t': round(fc / fps + 0.02, 3), 'who': to, 'face': 'scream' if tw.get('react') == 'fall' else 'o', '_throw_react': True}
                        rb_.update({'fall': 'back'} if tw.get('react') == 'fall' else {'pose': 'recoil', 'move': 2})
                        i_ = next((k for k, x in enumerate(beats) if x['t'] > rb_['t']), len(beats))
                        beats.insert(max(i_, beats.index(b) + 1), rb_)
                THROWS.append(rec)
                log.setdefault('throws', []).append({'who': who, 'hand': h, 'prop': pr.name, 'to': to if isinstance(to, str) else list(to), 'kind': kind,
                                                     'f_wind': fr - 8, 'f_release': fr, 'f_end': fc, 'catch_hand': th, 'style': 'over' if over_ else 'under'})
                settle[who] = fr + 13
                gaze.append((ch, to, fr - 6, 4, False)) if isinstance(to, str) else None
                if kind == 'catch': gaze.append((taker, tw['prop'], fc - 8, 4, True))
        if 'turn' in b:
            sc.frame_set(f - mv); bpy.context.view_layer.update()
            r = ch.root; p0 = r.matrix_world.translation
            tgt = b['turn']
            if isinstance(tgt, (list, tuple)): yaw = yaw_to((p0.x, p0.y), (tgt[0] * S, tgt[1] * S))   # turn toward a point (studs)
            else: yaw = math.radians(tgt if isinstance(tgt, (int, float)) else yaw_to((p0.x, p0.y), tuple(target_of(tgt).matrix_world.translation)[:2]))
            if isinstance(tgt, str) and tgt in cast: yaw = cheat(yaw)
            if b['who'] in seated or b['who'] in fallen:   # seated/lying: turn the upper body/head only is handled by look
                log.setdefault('notes', []).append(f"t{b['t']} {b['who']} turn ignored while seated/lying")
            else:   # planted stepped turn that FINISHES at t (Codex review #7); busy -> starts later and the scene re-times
                dur = 6 * max(1, math.ceil(abs(math.degrees((yaw - r.rotation_euler.z + math.pi) % (2 * math.pi) - math.pi)) / 35 - 1e-9))
                f0_ = max(f - dur, settle.get(b['who'], 0))
                fe_t = safe_turn(ch, f0_, yaw, 'turn')
                if fe_t > f + 2: n = retime_after(b, fe_t - f, 'turn')
                settle[b['who']] = fe_t
        if 'jump' in b:
            fj = max(f, settle.get(b['who'], 0) + 6)   # jump samples its standing base six frames before takeoff
            if fj > f: n = retime_after(b, fj - f, 'jump')
            f = fj
            if 'pose' in b: b['_pose_frame'] = f
        if isinstance(b.get('pose'), str) and b['pose'] not in poses.LIB:   # R242 unknown name from a writer: nearest pose + a
            import difflib                                                     # NOTE (a gate error failed fresh p9 'smug')
            alias_ = {'smug': 'gloat', 'happy': 'cheer', 'scared': 'cower', 'surprised': 'shock', 'thinking': 'think_R', 'point': 'point_R',
                      'wave': 'wave_R', 'facepalm': 'facepalm_R', 'think': 'think_R', 'excited': 'cheer', 'confused': 'curious', 'proud': 'proud'}
            near_ = alias_.get(b['pose']) or next(iter(difflib.get_close_matches(b['pose'], list(poses.LIB), 1, 0.6)), None)
            log.setdefault('notes', []).append(f"t{b['t']} {b['who']} unknown pose '{b['pose']}' -> {near_ or 'dropped'}")
            if near_ in poses.LIB: b['pose'] = near_
            else: b.pop('pose')
        if b.get('face') and b['face'] not in faces.KINDS:   # same for faces: the library emotion tag if there is one, else neutral
            emo_ = 'emo:' + str(b['face']).split(':')[-1]
            log.setdefault('notes', []).append(f"t{b['t']} {b['who']} unknown face '{b['face']}' -> {emo_ if emo_ in faces.KINDS else 'neutral'}")
            b['face'] = emo_ if emo_ in faces.KINDS else 'neutral'
        if 'pose' in b:   # a pose's body LEAN can tip the torso into furniture (R138 cookie table): keyed, checked, else no lean
            sk_ = (('head',) if 'look' in b else ()) + tuple(b.get('_skip', ()))
            if any(sp[0] == b['who'] and sp[1] <= f <= sp[2] for sp in log.get('sit_spans', [])):
                sk_ += ('legR', 'legL')   # SEATED: the seat owns the legs (a seated 'shock' kicked them into the coffee table, R149)
            plain_ = tuple(s_ for s_ in 'RL' if any(g_[0] is ch.arm[s_] and g_[3] - 8 <= f + 8 and g_[4] + 12 >= f - mv - 2 for g_ in grabs))   # an arm with a prop (or just rid of it): no rebound
            pose_ = b['pose']   # an arm that LETS GO of a prop during the move stays under the horizontal (out <= 75, the v1 shock): a crate
            for s_ in 'RL':     # dropped from an arm flung overhead falls through that arm (blind4_gym s02, 8.6 cm)
                if any(g_[0] is ch.arm[s_] and f - mv - 2 <= g_[4] <= f + 8 for g_ in grabs) and poses.full(pose_)[s_][1] > 75:
                    pose_ = {**(poses.LIB[pose_] if isinstance(pose_, str) else pose_), s_: (poses.full(pose_)[s_][0], 75)}
            iv_, hits_ = try_moves(sc, world, ch, [lambda: poses.beat(sc, ch, pose_, f, move=mv, skip=sk_, plain=plain_),
                                                   lambda: poses.beat(sc, ch, pose_, f, move=mv, skip=sk_ + ('body',), plain=plain_)],
                                   f - mv - 2, f + 6, [ch.upper], spans=log.get('sit_spans', []))
            if iv_ == 1 and not hits_: log.setdefault('notes', []).append(f"t{b['t']} {b['who']} {b['pose']}: no body lean (furniture)")
            if hits_: log.setdefault('errors', []).append(f"t{b['t']} {b['who']} pose {b['pose']} hits {hits_[0][2]}")
            if not (isinstance(b['pose'], str) and b['pose'] in CONTACT_POSES):
                for nt_ in clear_gesture(sc, ch, pose_, f, mv, [o for o in cast.values() if o is not ch], sk_, grabs):
                    log.setdefault('notes', []).append(f"t{b['t']} gesture {nt_.replace(str(pose_), str(b['pose']))}")   # planner note: the arm gate judges the keyed result
                    # (its strict 2 cm own-hair rule flagged a cheer the gate passes with 0 hits: homework s02, R158)
            if isinstance(b['pose'], str) and b['pose'] in CONTACT_POSES:
                others_ = [o for o in cast.values() if o is not ch]
                ov_ = contact_pose(sc, ch, b['pose'], f, log, others_)
                mir = b['pose'][:-1] + {'R': 'L', 'L': 'R'}.get(b['pose'][-1], '') if b['pose'][-2:] in ('_R', '_L') else None
                if ov_ > 1e-4 and mir in CONTACT_POSES:   # one-hand face pose still clips (own long hair, a neighbour): other hand
                    poses.beat(sc, ch, mir, f, move=mv, skip=sk_ + ('body',))
                    ov2 = contact_pose(sc, ch, mir, f, log, others_)
                    if ov2 < ov_ - 1e-4: log.setdefault('notes', []).append(f"t{b['t']} {b['who']} {b['pose']} -> {mir} (clear by {(ov_ - ov2) * 100:.1f} cm)")
                    else:
                        poses.beat(sc, ch, b['pose'], f, move=mv, skip=sk_ + ('body',)); contact_pose(sc, ch, b['pose'], f, log, others_)
                # THE ARM GATE on the keyed face-touch: a hand that still cuts a body (a neighbour beside the head, long hair) lets
                # go of the face and becomes a free gesture searched clear by clear_gesture, down to arm-at-rest (classroom s02:
                # Omar's left hand was keyed 12.3 cm into himself with Holt 2 studs away, "no clear twist", for the gate to fail)
                arm_plan_bad(ch, range(f - mv - 2, f + 7), range(f, f + 3), margin=0.0)   # the build's own cleanup first, then the gate's rows
                rows_ = arm_rows(ch, range(f - mv - 2, f + 7), final=False)[0]   # no planner margin: nothing re-pins this arm later (the 2 cm margin is for handoffs; here it dropped homework's facepalm at 10.6 cm of own torso, allowed 12)
                if os.environ.get('GIVEDEBUG'): print('CONTACTDEBUG', b['who'], b['pose'], f, sorted({(r_['f'], r_['limb'], r_['prop'], round(r_['depth_m'], 3)) for r_ in rows_}, key=lambda x: -x[3])[:6])
                for hand_ in 'RL':
                    piv_ = ch.arm[hand_]
                    if f not in ia.CONTACTS.get(piv_.name, {}) or not any(r_['limb'] == ia.limb_mesh(piv_).name for r_ in rows_): continue
                    worst_ = max(r_['depth_m'] for r_ in rows_ if r_['limb'] == ia.limb_mesh(piv_).name)
                    ia.CONTACTS[piv_.name].pop(f); clear_keys([piv_], f - mv, f + 6)
                    only_ = tuple(c_ for c_ in ('R', 'L', 'legR', 'legL', 'head', 'body') if c_ != hand_)
                    poses.beat(sc, ch, {hand_: poses.full(b['pose'])[hand_]}, f, move=mv, skip=only_)
                    nts_ = clear_gesture(sc, ch, b['pose'], f, mv, others_, tuple(c_ for c_ in 'RL' if c_ != hand_), grabs)
                    log.setdefault('notes', []).append(f"t{b['t']} {b['who']} {b['pose']} {hand_}: face-touch clips {worst_ * 100:.1f} cm at the arm gate -> free gesture ({'; '.join(nts_) or 'pose angles clear'})")
        if 'jump' in b:   # the leg tuck can hit nearby furniture (R135 bench): tucked, else straight legs, else report
            hj = b['jump'] if isinstance(b['jump'], (int, float)) else 0.9
            for tuck in (1.0, 0.0):
                end, hit = motion_trial(sc, world, ch, lambda: poses.jump(sc, ch, f, height=hj, tuck=tuck),
                                        f - 6, f + 12, log.get('sit_spans', []))
                if end is not None:
                    settle[b['who']] = end
                    log.setdefault('jump_spans', []).append([b['who'], f, end])
                    break
            else: log.setdefault('errors', []).append(f"t{b['t']} {b['who']} jump rejected: {hit}")
        if any(k in b for k in FIGHT_KEYS):
            fight_beat(sc, b, ch, f, fps, cast, face_sched, fallen, settle, vfx_jobs, log)
        if 'wiggle' in b:
            poses.wiggle(sc, ch, b['wiggle'], f, f + F(b.get('wiggle_s', 0.8), fps))
        if 'anim' in b:   # Roblox R6 animation library (anims.py): {"anim": "dance2", "loop": 2.0 (seconds, repeats), "anim_speed": 1.0, "anim_skip": ["legR"]}
            import anims
            if b['anim'] not in anims.slugs(): log.setdefault('errors', []).append(f"t{b['t']} {b['who']} unknown anim '{b['anim']}' (valid: {', '.join(anims.slugs())})")
            else:
                seated_ = any(sp[0] == b['who'] and sp[1] <= f <= sp[2] for sp in log.get('sit_spans', []))
                hair_ = lambda c_: [h for h in c_.hair_pivot.children_recursive if h.type == 'MESH']
                clear_ = [(ch.torso, OWN_TORSO_MAX), (ch.head_mesh, 0.02)] + [(h, 0.02) for h in hair_(ch)]
                clear_ += [(o_, 0.02) for oc in cast.values() if oc is not ch for o_ in [oc.torso, oc.head_mesh] + hair_(oc)]
                # A clip with leg motion shifts the ROOT (planted-foot retarget): keyed, checked against furniture and actors, and
                # undone like every other move (was the only unchecked beat: Leo's laugh shuffled him into the kitchen island,
                # blind4_cafe s02); blocked -> the same clip on our own legs (no root motion), else reported
                for extra_ in ((), ('legR', 'legL')):
                    def key_anim():
                        e_ = int(anims.play(sc, ch, b['anim'], f, speed=b.get('anim_speed', 1.0), loop_until=f + F(b['loop'], fps) if b.get('loop') else None,
                                            skip=tuple(b.get('anim_skip', ())) + (('legR', 'legL') if seated_ else ()) + extra_, clear=clear_)) + 1
                        bad_ = arm_plan_bad(ch, range(f, e_ + 1), range(f, f + 2), margin=0.0) if b.get('auto') else 0   # AUTOMATIC clips must be clean at plan time; a story's own clip is judged by the final gate as before (this check rejected blind5_living s02's laugh at 13.9 cm that the final cleanup clears)
                        if bad_: raise ValueError(f'arms clip {bad_ * 100:.1f} cm')
                        return e_
                    end_a, hit_a = motion_trial(sc, world, ch, key_anim, f, f, log.get('sit_spans', []))
                    if end_a is not None:
                        if extra_: log.setdefault('notes', []).append(f"t{b['t']} {b['who']} anim {b['anim']}: upper body only (its steps hit {hit_0[2]})")
                        settle[b['who']] = max(settle.get(b['who'], 0), end_a); break
                    hit_0 = hit_a
                else: log.setdefault('notes' if b.get('auto') else 'errors', []).append(f"t{b['t']} {b['who']} anim {b['anim']} rejected: {hit_a}")
        if 'face' in b or '_lib' in b:
            face_sched[b['who']][max(0, f - 2)] = b.get('_lib') or b['face']; face_seq[b['who']].append((f, b.get('_lib') or b['face']))
            flap_fr[b['who']].discard(max(0, f - 2))
            if b.get('_req'): log.setdefault('face_req', []).append([round(f / fps, 3), b['who'], b['_req']])   # written emotion at its real (retimed) time
        if 'talk' in b:   # dialogue: mouth flaps (open twin of the current expression) every 3-5 frames, optional hand gestures
            sch = face_sched[b['who']]; base = sch[max(k for k in sch if k <= f)] if any(k <= f for k in sch) else 'smile'
            base = base[:-5] if base.endswith('_talk') else base
            if base in faces.TALKABLE:
                rng_t = random.Random(f); ft = f; open_ = True; f_end_t = f + F(b['talk'], fps)
                while ft < f_end_t:
                    sch[ft] = base + '_talk' if open_ else base; flap_fr[b['who']].add(ft); open_ = not open_; ft += rng_t.choice((3, 4, 4, 5))
                sch[f_end_t] = base; flap_fr[b['who']].add(f_end_t)
            if b.get('gesture', True):
                # TALK GESTURES v2 (critic R195: 'one repeated talk gesture, arm slabs'): each line plays its own run of gestures
                # from poses.TALK, picked by the line's mood (face + say) and seeded per speaker + line, on an uneven rhythm.
                # Compact set when seated or with a body / solid set piece inside arm's reach; an arm that carries a prop keeps
                # carrying; the lean is checked against the world like a pose beat (keyed -> checked -> no lean).
                f_end_g = f + F(b['talk'], fps); sc.frame_set(f); here_ = ch.root.matrix_world.translation.copy()
                tight_ = any(sp[0] == b['who'] and sp[1] <= f_end_g and sp[2] >= f for sp in log.get('sit_spans', [])) \
                    or any((o_.root.matrix_world.translation - here_).length < 3.5 * S for o_ in cast.values() if o_ is not ch) \
                    or any(q_['solid'] and q_['rect'][0] - 1.3 < here_.x < q_['rect'][1] + 1.3 and q_['rect'][2] - 1.3 < here_.y < q_['rect'][3] + 1.3 for q_ in assets.PLACED)
                carry_ = tuple(s_ for s_ in 'RL' if any(g_[0] is ch.arm[s_] and g_[3] <= f_end_g and g_[4] >= f - 6 for g_ in grabs))
                line_ = sum(1 for x in beats if x.get('talk') and x['who'] == b['who'] and x['t'] < b['t'])
                rng_g = random.Random(f"{b['who']}{line_}g"); hits_g = []; tg = f
                while tg < f_end_g - 6: hits_g.append(tg); tg += rng_g.choice((F(0.7, fps), F(0.9, fps), F(1.1, fps)))
                # a pose or clip of the speaker's own (this beat's, or one landing inside the line) IS the gesture for its first 1.5 s:
                # no talk gesture on top (was: a cheer + talk beat showed the cheer for 4 frames, then talk_a)
                own_g = [F(x['t'], fps) for x in beats if x['who'] == b['who'] and ('pose' in x or 'anim' in x)]
                hits_g = [tg for tg in hits_g if not any(fp_ - 8 <= tg + 4 <= fp_ + F(1.5, fps) for fp_ in own_g)]
                others_g = [o_ for o_ in cast.values() if o_ is not ch]
                for tg, (gname_, gp_) in zip(hits_g, poses.talk_gestures(poses.talk_mood(b.get('face') or base, b.get('say')), len(hits_g), f"{b['who']}{line_}", compact=tight_)):
                    sk_g = ('head',) + carry_
                    try_moves(sc, world, ch, [lambda: poses.beat(sc, ch, gp_, tg + 4, move=4, skip=sk_g),
                                              lambda: poses.beat(sc, ch, gp_, tg + 4, move=4, skip=sk_g + ('body',))],
                              tg - 3, tg + 9, [ch.upper], spans=log.get('sit_spans', []))
                    for nt_ in clear_gesture(sc, ch, gp_, tg + 4, 4, others_g, sk_g, grabs):
                        log.setdefault('notes', []).append(f"t{b['t']} talk gesture {nt_.replace(str(gp_), gname_)}")
        if 'look' in b and b['who'] not in log.get('curled', {}):   # a body lying curled keeps its head down until get_up
            gaze.append((ch, b['look'], f, mv, b.get('track', False)))
        if 'grab' in b:
            g = b['grab']; hand = g.get('hand', 'R'); side = rig.SIDE[hand]; piv = ch.arm[hand]
            pr = props[g['prop']]
            sc.frame_set(f); bpy.context.view_layer.update()
            c, rad, top = prop_cyl(pr)
            fg = max(f, settle.get(b['who'], 0))
            for attempt in (0, 1):
                lean = lean_for.pop(b['who'], 0)
                nxt = next((x for x in beats if x['who'] == b['who'] and x['t'] > b['t'] and 'pose' in x), None)
                lift = nxt is None or F(nxt['t'] - b['t'], fps) > F(.5, fps)
                end, hit = grab_candidate(sc, world, ch, pr, hand, fg, lean, lift=lift, spans=log.get('sit_spans', []))
                if end is not None:
                    if fg > f:   # RETIME: the grab waited for the approach -> push every later beat/shot back, lengthen the scene
                        if 'until' in g: g['until'] = round(g['until'] + (fg - f) / fps, 3)
                        n = retime_after(b, fg - f, f"grab {g['prop']}")
                    fu = F(g['until'], fps) if 'until' in g else n - 1
                    if fu >= n - 1 - F(0.5, fps): fu = END   # releasing in the last 0.5 s = keep holding (no mid-air prop at the end)
                    grabs.append((piv, side, pr, fg, fu))
                    settle[b['who']] = end
                    break
                else:
                    if attempt == 0:   # out of reach: walk to the nearest clear spot first, grab on arrival
                        fe = walk_to(ch, b['who'], [g['prop']], fg, {'t': b['t'], 'hand': hand, 'speed': b.get('speed', 8)}, beats)
                        if fe is not None: fg = fe; continue
                    log.setdefault('errors', []).append(f"t{b['t']} {b['who']} grab {g['prop']} rejected: {hit}")
                    break
    # relaxed holds: a raised arm held > 1.2 s eases ~22 % toward rest (reference holds breathe; frozen raised arms read robotic)
    held_arms = [(piv, f0_, f1_) for piv, side, pr, f0_, f1_ in grabs]
    for who, ch in cast.items():
        pb = [x for x in beats if x['who'] == who and 'pose' in x]
        for i, x in enumerate(pb):
            if isinstance(x['pose'], str) and x['pose'] in CONTACT_POSES: continue
            t0_ = x.get('_pose_frame', F(x['t'], fps)); t1_ = pb[i + 1].get('_pose_frame', F(pb[i + 1]['t'], fps)) - 7 if i + 1 < len(pb) else n - 1
            if t1_ - t0_ < F(1.2, fps): continue
            vals = poses.full(x['pose'])
            for side in 'RL':
                raise_, out_ = vals[side]
                if max(abs(raise_), abs(out_)) < 30: continue
                piv = ch.arm[side]
                if any(p_ is piv and f0_ <= t1_ and f1_ >= t0_ for p_, f0_, f1_ in held_arms): continue
                a, b_ = t0_ + F(0.8, fps), min(t1_, t0_ + F(1.3, fps))
                sc.frame_set(a); v0 = piv.rotation_euler.copy(); piv.keyframe_insert('rotation_euler', frame=a)
                piv.rotation_euler = (v0.x * 0.78, v0.y * 0.78, v0.z); piv.keyframe_insert('rotation_euler', frame=b_)
    for ch in cast.values(): lo.unwrap_yaw(ch.root)
    # Gaze changes the head's collision box: validate the final looks before arm cleanup and cameras.
    # LISTENERS: when someone talks, every other character with nothing of their own in that window turns its head to the
    # speaker (reaction acting; reference listeners always look at the talker). Explicit looks / actions are never overridden.
    for tb in [x for x in beats if x.get('talk') and x['who'] in cast]:
        ft0 = F(tb['t'], fps); ft1 = ft0 + F(tb['talk'], fps)
        for lname, lch in cast.items():
            if lname == tb['who']: continue
            busy_ = any(x['who'] == lname and ft0 - 12 <= F(x['t'], fps) <= ft1 + 6 and any(k_ in x for k_ in ('look', 'walk', 'run', 'grab', 'give', 'fall', 'jump', 'talk') + FIGHT_KEYS)
                        for x in beats)
            if busy_ or any(g_[0] is lch and ft0 - 12 <= g_[2] <= ft1 for g_ in gaze): continue
            sc.frame_set(ft0 + 3); e_ = lch.root.matrix_world.to_euler()
            if abs(e_.x) > 0.3 or abs(e_.y) > 0.3: continue   # LYING (after a fall/knockback): no head turn into the floor (school s02 Zed, R180)
            gaze.append((lch, tb['who'], ft0 + 3, 6, False))
    gaze.sort(key=lambda g: g[2])
    def key_gazes():
        tilts = {}
        for i, (ch, tgt, f, mv, track) in enumerate(gaze):
            nxt = next((g[2] for g in gaze[i + 1:] if g[0] is ch), n - 1)
            sc.frame_set(f - mv); ch.head.keyframe_insert('rotation_euler', frame=f - mv)
            if tgt == '__forward__':
                ch.head.rotation_euler = (0, 0, 0); ch.head.keyframe_insert('rotation_euler', frame=f); continue
            tobj = target_of(tgt)
            if tgt in cast and not track:
                sc.frame_set(f); e_ = bpy.data.objects.new(f'gaze cheat {ch.name} {f}', None); bpy.context.collection.objects.link(e_)
                e_.location = tobj.matrix_world.translation + Vector((0, -0.9, 0)); tobj = e_
            if track: la.look_track(sc, ch.head, tobj, range(f, nxt), lead=2, hold=6, lag_frames=2, max_pitch=25)
            else:
                la.look_at(sc, ch.head, tobj, f, max_pitch=25)
                # HEAD TILT (acting v2: a level head on every look read as a robot): each look cocks the head 5-9 deg, the
                # other way than the look before. Not while a hand is on the face (the contact was solved on the level head).
                sc.frame_set(f); e_ = ch.root.matrix_world.to_euler()   # ... and not on a body that falls or lies (school s02: the tilted head went 4 cm under the floor)
                down_ = abs(e_.x) > 0.3 or abs(e_.y) > 0.3 or any(sp_[0] == ch.name and sp_[1] - 12 <= nxt and f <= sp_[2] for sp_ in log.get('fall_spans', []))
                if not down_ and not any(c_[0] == ch.name and f - 12 <= c_[1] <= nxt for c_ in log.get('contact_frames', [])):
                    k_ = tilts[ch.name] = tilts.get(ch.name, len(ch.name)) + 1
                    ch.head.rotation_euler.y += math.radians((5 + 2 * (k_ % 3)) * (1 if k_ % 2 else -1)); ch.head.keyframe_insert('rotation_euler', frame=f)
        return {ch.name for ch, *_ in gaze}
    if gaze:
        for name in checked_gazes(sc, cast, props, range(n), key_gazes, log.get('sit_spans', [])):
            log.setdefault('notes', []).append(f'{name}: kept pre-gaze head motion (the requested look conflicted with a body)')
    for name, sched in face_sched.items():   # FAST CHANGES WHILE TALKING (L1 face 02): a flap key takes the expression of its moment
        cur_ = None                            # (a face beat inside a line used to be overwritten by the flaps of the line's first face)
        for f_ in sorted(sched):
            if f_ in flap_fr.get(name, ()) and cur_: sched[f_] = cur_ + ('_talk' if sched[f_].endswith('_talk') else '')
            elif not sched[f_].endswith(('_talk', '_shut')) and sched[f_] != 'blink': cur_ = sched[f_]
    for name, sched in face_sched.items():   # every key (beats, talk flaps, fight reactions, fallbacks) drawn in the character's family
        fam_ = log['face_family'][name]; fm_ = next((c_.get('face_map') for c_ in spec['cast'] if c_['name'] == name), None)
        face_seq[name] = [(f_, acting.to_family(k_, fam_, faces.library(), fm_)) for f_, k_ in face_seq[name]]
        face_sched[name] = faces.blinks(name, {f_: acting.to_family(k_, fam_, faces.library(), fm_) for f_, k_ in sched.items()}, end=n - 4)
    for ch in cast.values():
        ia.spring_follow(sc, ch.head, ch.hair_pivot, range(0, n))

    grabs = [(pv, sd, pp, a0, n - 1 if a1 >= END else a1) for pv, sd, pp, a0, a1 in grabs]   # 'until the end' = the FINAL end
    log['holds'] = [[ch_.name, h_, pp.name, a0, a1] for pv, sd, pp, a0, a1 in grabs for ch_ in cast.values() for h_ in 'RL' if ch_.arm[h_] is pv]   # L1 checks: who holds what when
    TT_['beats'] = round(time.time() - T0_, 1)
    # ---------------- clean-up + gates ----------------
    desks = st['desk_tops']
    # PRELIM bake so depenetration sees where held props really travel (grab.py's rule is the reverse; we do both passes)
    _rest0 = {id(pr): (pr.location.copy(), pr.rotation_euler.copy()) for _, _, pr, _, _ in grabs}
    _contacts0 = {k: dict(v) for k, v in ia.CONTACTS.items()}   # prelim bake must not pin the holding arms for depenetration
    pen = {'hits': 0, 'worst': []}
    near = {ch.name: near_set(ch, range(0, n)) for ch in cast.values()}
    def depen_all():
        # shortcut: first-acquisition order handles one-way transfers; use a coupled solve for cyclic handoffs.
        order = sorted(cast.values(), key=lambda ch: min((f0 for piv, _, _, f0, _ in grabs if piv in ch.arms_piv), default=END))
        for ch in order:
            others = [o for c in cast.values() if c is not ch for o in (c.head_mesh, c.torso)]
            own_held = {o for piv, side, pr, f0, f1 in grabs if piv in ch.arms_piv for o in pr.children_recursive if o.type == 'MESH'}
            meshes = [m for m in prop_meshes if m not in own_held] + others + [ch.head_mesh, ch.torso] + hair[ch.name] + near[ch.name]
            allowances = {ch.torso.name: OWN_TORSO_MAX, **{h.name: space.OWN_HAIR_MAX for h in hair[ch.name]}}
            for s in 'RL':
                ia.depenetrate(sc, ch.arm[s], meshes, range(0, n), box_props=desks, tol=0.02, label=f'{ch.name} {s}', allowances=allowances)
            for pr_h in {pr for pv, _, pr, _, _ in grabs if pv in ch.arms_piv}:
                windows = [hold_window(grabs, pr, f0, f1) for pv, _, pr, f0, f1 in grabs if pr is pr_h and pv in ch.arms_piv]
                outside = [f for f in range(0, n) if not any(a <= f <= z + 8 for a, z in windows)]   # +8: a dropped prop is LEAVING the hand (arm_rows); cleanup must not yank the arm after it
                if outside:
                    pm = [o for o in pr_h.children_recursive if o.type == 'MESH']
                    for s in 'RL':
                        ia.depenetrate(sc, ch.arm[s], pm + meshes, outside, box_props=desks, tol=0.02, label=f'{ch.name} {s} vs {pr_h.name}', allowances=allowances)
            if own_held:
                contacts = {k: dict(v) for k, v in ia.CONTACTS.items()}
                for k, pr in grabbed.items():
                    pr.animation_data_clear(); pr.location, pr.rotation_euler = rest[k]
                bake_props()
                ia.CONTACTS.clear(); ia.CONTACTS.update(contacts)
    def bake_props():
        for piv, side, pr, f0, f1 in grabs:
            if pr.name in HELD_PROPS and f0 == 0:   # starts in the hand: put it in the CURRENT hand at f0
                sc.frame_set(f0); bpy.context.view_layer.update()
                hold_in_hand(piv, side, pr)
            gr.grab(sc, piv, side, pr, f0, f1)
            th_ = next((t_ for t_ in THROWS if t_['prop'] is pr and t_['f_rel'] == f1), None)
            if th_ is not None: throw_bake(sc, th_, n, fps, log)
            elif f1 < n - 1 and hold_window(grabs, pr, f0, f1)[1] == f1:
                drop_prop(sc, pr, f1, n, fps, log)
    grabbed = {id(pr): pr for _, _, pr, _, _ in grabs}
    rest = _rest0
    bake_props()   # cleanup and the final bake must see the same ordinary-release trajectory
    ia.CONTACTS.clear(); ia.CONTACTS.update(_contacts0)
    passes = 1 if TIER == 'draft' else 2   # drafts: one pass (2x faster builds); look/final: the full double pass
    for it_ in range(passes):   # depenetrate -> FINAL bake; the 2nd pass sees where props travel on the corrected arms
        depen_all()
        for k, pr in grabbed.items():
            pr.animation_data_clear(); pr.location, pr.rotation_euler = rest[k]
        if it_ < passes - 1:
            _c = {k: dict(v) for k, v in ia.CONTACTS.items()}
            bake_props(); ia.CONTACTS.clear(); ia.CONTACTS.update(_c)   # do not pin holding arms for the 2nd depenetration
        else:
            bake_props()
    for ch in cast.values():   # THE ARM GATE (arm_rows: the same function the planners asked)
        bad_, why_ = arm_rows(ch, range(0, n))
        pen['hits'] += len(bad_); pen['worst'] += bad_   # worst over the COUNTED rows (a pair's worst row could be an allowed one hiding a counted one)
        for why in why_: log.setdefault('notes', []).append(f'{ch.name}: {why} allowed (rigid R6 limit)')
    pen['worst'].sort(key=lambda r: -r['depth_m'])
    def root_busy(ch_, f0, f1):
        """The character moves or is tilted during [f0-6, f1+6] (walks, any planted steps/turns, falls, lying, getting up):
        a per-shot cheat turn must not touch its root then (R135 Codex #2: a cheat spun a lying body, 27 cm)."""
        pts = []
        for fr in range(max(0, f0 - 6), f1 + 7, 2):
            sc.frame_set(fr); M_ = ch_.root.matrix_world; e_ = M_.to_euler()
            if abs(e_.x) > 0.3 or abs(e_.y) > 0.3: return True
            pts.append((M_.translation.xy.copy(), e_.z))
        return any((p_[0] - pts[0][0]).length > 0.02 or abs(p_[1] - pts[0][1]) > 0.02 for p_ in pts)

    TT_['cleanup'] = round(time.time() - T0_ - sum(TT_.values()), 1)
    # ---------------- shots ----------------
    shafts_ = [o for o in bpy.data.objects if o.name.startswith('VFX lightshaft') and not o.hide_viewport]
    for o in shafts_: o.hide_viewport = True   # light beams are not occluders: camera visibility rays hit them (faces 'hidden', R153)
    camera.ROOM['obstacles'] = [(*q['rect'], q['top']) for q in assets.PLACED if q['solid']]
    vis = {}
    cm_ = spec.get('camera') or {}; cm_ = {'mode': cm_} if isinstance(cm_, str) else cm_   # CAMERA MODE (schema 7b): the scene's reel style
    shots, sw_ = camera.mode_shots(cm_, sorted(spec.get('shots', []), key=lambda s: s['t']), beats, list(cast), n / fps, log.setdefault('notes', []))
    spec = {**sw_, **spec}; log['camera_mode'] = cm_.get('mode', 'story_cuts'); camera.AXIS.clear()   # authored scene switches win over the mode's
    if spec.get('fights', True):   # cam2 FIGHTS FROM THE SIDE: an authored two-shot of two fighters in an exchange gets the side-on view
        shots = [camera.fight_shot(x, beats, list(cast), shots[k_ + 1]['t'] if k_ + 1 < len(shots) else n / fps, notes=log.setdefault('notes', [])) for k_, x in enumerate(shots)]
    # reference rhythm: a shot longer than 2.4 s (unless 'hold' or tracking a move <= 3.2 s) is split into ~2 s pieces that alternate size
    # on the focus character (medium <-> close, wide <-> medium, full <-> close); sizes differ >= 1.4x so no jump cut
    ALT = {'wide': 'medium', 'full': 'close', 'medium': 'close', 'close': 'medium', 'insert': 'medium'}
    T_end = n / fps; out_sh = []
    # ESTABLISHING WIDE (reference R6: one per location): a scene of >= 2 characters with no wide/full shot opens on a 0.9 s wide of
    # the cast before its first authored shot; dropped again if no camera reads it (logged either way)
    # (R213: the establishing wide moved to camera.grammar, below the rhythm split: it now opens EVERY scene)
    # ECU on the PUNCHLINE (reference R7): the last strong-emotion beat of the scene's second half gets ONE extreme close-up
    STRONG_ = ('shock', 'scream', 'scared', 'cry', 'angry', 'laugh', 'evil', 'joy', 'facepalm', 'hands_head', 'cover_mouth')
    punch_ = next((x for x in reversed(beats) if x['who'] in cast and x['t'] >= 0.5 * T_end and x['t'] <= T_end - 0.6
                   and any(w_ in str(x.get('face', '')) + str(x.get('pose', '')) for w_ in STRONG_)), None) if spec.get('ecu', True) else None
    looked_ = set()   # props that already got their story-object insert
    for i, sh in enumerate(shots):
        t1 = shots[i + 1]['t'] if i + 1 < len(shots) else T_end; dur = t1 - sh['t']
        if sh.get('hold') or sh.get('fight') or dur <= 2.2 or (sh.get('track') and dur <= 3.0):   # a fight two-shot is cut by the fight rules (arrival, landing), not by the rhythm   # reference measured: median 1.5 s, p75 2.0 s (101 cuts)
            out_sh.append(sh); continue
        k = math.ceil(dur / 1.6); step = dur / k
        for j in range(k):
            if j % 2 == 0:   # repeats of the authored shot MOVE the camera (critic R195: frames 2-7 = one held front-on shot)
                out_sh.append({**sh, 't': round(sh['t'] + j * step, 3), 'side': sh.get('side', 0) + (0, 35, -35, 25, -25, 50, -50)[(j // 2) % 7]})
            else:
                focus = sh.get('on', [])[:1]; t0p = sh['t'] + j * step
                g_in = [pr for piv, side, pr, fg_, f1_ in grabs if focus and focus[0] in cast and piv in cast[focus[0]].arms_piv
                        and F(t0p, fps) - 6 <= fg_ <= F(t0p + step, fps)]
                alt_ = {**{k_: v_ for k_, v_ in sh.items() if k_ != 'establish'}, 't': round(t0p, 3), 'side': sh.get('side', 0) - 35, 'auto': True}   # the authored shot, other side
                # STORY-OBJECT insert (reference R6): the focus LOOKS at a prop in this piece and nobody is holding it -> the prop gets
                # its own shot, once (an insert no camera reads falls back to the piece it replaced: '_alt')
                l_in = [x['look'] for x in beats if focus and x['who'] == focus[0] and x.get('look') in props and x['look'] not in looked_
                        and F(t0p, fps) - 6 <= F(x['t'], fps) <= F(t0p + step, fps)
                        and not any(pp is props[x['look']] and a0 <= F(t0p + step, fps) and a1 >= F(t0p, fps) for _, _, pp, a0, a1 in grabs)]
                if g_in:   # the focus grabs something in this piece: INSERT on the prop (reference grab close-up), not the back of a head
                    pname = next(k for k, v in props.items() if v is g_in[0])
                    out_sh.append({'t': round(t0p, 3), 'kind': 'insert', 'on': [pname], 'lens': 50, 'auto': True, '_alt': alt_})   # R240: a reaching arm filled it
                elif l_in:
                    looked_.add(l_in[0]); out_sh.append({'t': round(t0p, 3), 'kind': 'insert', 'on': [l_in[0]], 'lens': 50, 'auto': True, '_alt': alt_})
                    log.setdefault('notes', []).append(f"t{t0p:.2f} story-object insert on {l_in[0]} ({focus[0]} looks at it)")
                else:
                    # REACTION cut (reference shot/reverse-shot): if ANOTHER character acts in this piece (talk, pose, face change, look,
                    # grab, give...), cut to them instead of re-cutting the same focus (critic R151: 'repetitive cuts to the same
                    # character'); otherwise the size alternation on the focus as before
                    f_a, f_b = F(t0p, fps) - 4, F(t0p + step, fps)
                    acts = [x['who'] for x in beats if x['who'] in cast and (not focus or x['who'] != focus[0]) and not x.get('stance')
                            and (f_a <= F(x['t'], fps) <= f_b or ('talk' in x and F(x['t'], fps) < f_a and F(x['t'] + float(x['talk'] or 0), fps) >= f_a + 16))   # R240: still TALKING in this piece = cut to the speaker   # a stance change is not a reaction (hallway s02: cut from the laughing speaker to the back of Max's hair)
                            and any(k_ in x for k_ in ('talk', 'pose', 'face', 'look', 'grab', 'give', 'jump', 'fall', 'sit', 'stand'))]
                    if acts and camera.ROOM.get('bounds'):   # R240 f16: never cut to someone who has left the set (a dark dot in the doorway)
                        sc.frame_set(F(t0p + step / 2, fps)); b_ = camera.ROOM['bounds']
                        acts = [w_ for w_ in acts if b_[0] < cast[w_].root.matrix_world.translation.x < b_[1] and b_[2] < cast[w_].root.matrix_world.translation.y < b_[3]]
                    if acts and j % 4 == 1:
                        out_sh.append({'t': round(t0p, 3), 'kind': 'medium' if sh.get('kind') in ('wide', 'full') else ALT.get(sh.get('kind', 'medium'), 'close'),
                                       'on': [acts[0]], 'lens': 50, 'auto': True, '_alt': alt_})
                        log.setdefault('notes', []).append(f"t{t0p:.2f} reaction cut to {acts[0]}")
                    else:
                        walk_ = focus and any(w_['who'] == focus[0] and w_['f0'] <= F(t0p + step, fps) and w_['f1'] >= F(t0p, fps) for w_ in log.get('walks', []))
                        piece_ = {'t': round(t0p, 3), 'kind': ('full' if sh.get('kind') == 'medium' else 'medium') if walk_ and ALT.get(sh.get('kind', 'medium'), 'close') == 'close' else ALT.get(sh.get('kind', 'medium'), 'close'),   # R240 frames 7-8: a static close on a runner = a chest
                                  'on': focus if focus and focus[0] in cast else sh.get('on', []), 'lens': 50, 'auto': True,
                                  'side': sh.get('side', 0) + (-40, 40, -60, 60)[(j // 2) % 4], '_alt': alt_}   # other side + pitch cycle (Fable R2)
                        if sh.get('angle') is None and ('low', None, 'high', None)[(j // 2) % 4]: piece_['angle'] = ('low', None, 'high', None)[(j // 2) % 4]; piece_['_soft'] = True   # engine-chosen: may fall back (R240)
                        out_sh.append(piece_)
        log.setdefault('notes', []).append(f"shot at {sh['t']}s ({dur:.1f}s) split into {k} for rhythm")
    # EDITOR PASS (camera.grammar): establishing wide, story-object inserts, reaction close-ups, pitch - also on authored shots
    ev_ = [(a0 / fps, next(k_ for k_, v_ in props.items() if v_ is pp), 'grab') for _, _, pp, a0, _ in grabs if a0 > 6 and any(v_ is pp for v_ in props.values())
           and not any(p2 is pp and b0 < a0 - 2 <= b1 for _, _, p2, b0, b1 in grabs)]   # not a hand-over: a prop already in a hand never reads at insert size (cloud v3: 14 of 15 fell back)
    ev_ += [(x['t'], x['look'], 'look') for x in beats if isinstance(x.get('look'), str) and x['look'] in props
            and not any(pp is props[x['look']] and a0 <= F(x['t'], fps) + 12 and a1 >= F(x['t'], fps) - 6 for _, _, pp, a0, a1 in grabs)]
    shots = camera.grammar(out_sh, beats, list(cast), ev_, T_end, fps, spec, log.setdefault('notes', []))
    if not shots:   # a quiet scene (narrator line + faces only) gives the grammar nothing to cut on: hold one wide on the cast
        shots = [{'t': 0.0, 'kind': 'wide', 'on': list(cast)[:3]}]; log.setdefault('notes', []).append('no shots planned -> one wide on the cast')
    if punch_ is not None:   # the close on the punchline character that covers the beat (authored or a rhythm piece) becomes the ECU
        for j_, x in enumerate(shots):
            t1_ = shots[j_ + 1]['t'] if j_ + 1 < len(shots) else T_end
            if x.get('kind') == 'close' and x.get('on', [None])[:1] == [punch_['who']] and len(x.get('on', [])) == 1 and x['t'] - 0.3 <= punch_['t'] < t1_ and t1_ - x['t'] <= 2.4:
                x['ecu'] = True; log.setdefault('notes', []).append(f"ECU on {punch_['who']} at {x['t']}s (punchline beat t{punch_['t']})"); break
    # CUT ON THE FALL (creator bug '0:18 camera', R259: a piece that held a walker and his fall was filmed top-down for its END -
    # 0.5 s of hair top and floor before he fell): a fall that starts inside a shot on the faller moves the cut onto the fall
    # (6 frames in: cut on action). Before it the shot is an upright one, after it the camera looks down at the body. A tail
    # under 0.5 s stays in the upright shot (camera._shot judges 'lying' at the middle AND the end); 'hold' shots are never cut.
    for who_, a_, _z, _d in log.get('fall_spans', []):
        c_ = a_ + 6; fe_ = lambda k: (F(shots[k + 1]['t'], fps) if k + 1 < len(shots) else n) - 1
        j_ = next((k for k, x in enumerate(shots) if F(x['t'], fps) < c_ <= fe_(k)), None)
        if j_ is None or shots[j_].get('hold') or (shots[j_].get('on') or list(cast)[:1])[0] != who_ or fe_(j_) - c_ + 1 < 12: continue
        x = shots[j_]
        if c_ - F(x['t'], fps) >= 12:
            shots.insert(j_ + 1, {**{k: v for k, v in x.items() if k != 'establish'}, 't': round(c_ / fps, 3), 'auto': True})
            log.setdefault('notes', []).append(f"shot at {x['t']}s cut on {who_}'s fall (f{c_})")
        elif j_ > 0 and not shots[j_ - 1].get('hold'):
            log.setdefault('notes', []).append(f"cut at {x['t']}s moved onto {who_}'s fall (f{c_})"); x['t'] = round(c_ / fps, 3)
    # cam2 LANDING SHOT: a knocked-back / fallen body that has landed (measured on the final motion) and stays down >= 1 s gets a
    # straight-down view of the whole body + crater (other bodies lying within 8 studs join the frame). Scene switch: falls.
    camera.CRATER.clear(); camera.CRATER.update({w_: fight.CURL_CRATER for w_ in log.get('curled', {})})   # the crater VFX is built after the cameras
    for who_, a_, _z, _d in sorted(log.get('fall_spans', []), key=lambda x_: x_[1]) if spec.get('falls', True) else []:
        if who_ not in cast or a_ <= 0: continue   # a body lying from the scene start (down) joins another body's landing shot, it gets none of its own
        fl_ = camera.landed(sc, cast[who_], a_, n - 1)
        if fl_ is None or fl_ + 26 > n - 1: continue
        sc.frame_set(fl_ + 26)
        if not camera._lying(cast[who_]): continue   # up again within a second: not a landing to hold on
        near_ = [nm_ for nm_, c_ in cast.items() if nm_ != who_ and camera._lying(c_) and (c_.torso.matrix_world.translation - cast[who_].torso.matrix_world.translation).length < 8 * S]
        shots = camera.fall_top(shots, T_end, fl_ / fps, [who_] + near_, log.setdefault('notes', []))
    def dist_(a_, b_, fr_=None):   # studs between two characters (fight two-shot size), at a frame or the frame set last
        if fr_ is not None: sc.frame_set(fr_)
        return (cast[a_].root.matrix_world.translation - cast[b_].root.matrix_world.translation).length / S
    def unshoot_(c_):
        for m_ in list(sc.timeline_markers):
            if m_.camera is c_: sc.timeline_markers.remove(m_)
        camera.HIST.pop(c_.name, None); bpy.data.objects.remove(c_, do_unlink=True)
    i = 0; cams_ = []; cheated_ = set()   # cams_[k] = the camera of shots[k] (R240 merge of near-duplicate pieces)
    while i < len(shots):   # index loop: a failing shot can be cut at a head turn and re-shot (below)
        s = shots[i]
        f0 = F(s['t'], fps); f1 = (F(shots[i + 1]['t'], fps) - 1) if i + 1 < len(shots) else n - 1
        sc.frame_set((f0 + f1) // 2)
        s = shots[i] = camera.fight_shot(s, beats, list(cast), (f1 + 1) / fps, dist=dist_) if spec.get('fights', True) else s
        if s.get('fight') and s.get('profile') and not s.get('hold') and not s.get('_arr') and len(s.get('on', [])) >= 2 and all(x in cast for x in s['on'][:2]):
            s['_arr'] = True   # DASH-IN: the gap closes a lot inside the shot -> cut onto a tighter two-shot at the arrival
            smp_ = [(fr_ / fps, dist_(s['on'][0], s['on'][1], fr_)) for fr_ in range(f0, f1 + 1, 3)]
            ta_ = camera.arrival(smp_, s.get('kind', 'full'))
            if ta_ is not None:
                shots.insert(i + 1, {**{k_: v_ for k_, v_ in s.items() if k_ != '_fight_auto'}, 't': ta_, 'auto': True, 'kind': 'full' if smp_[-1][1] <= 5.0 else s.get('kind', 'full')})
                log.setdefault('notes', []).append(f"fight shot at {s['t']}s: {s['on'][0]} and {s['on'][1]} close from {smp_[0][1]:.0f} to {smp_[-1][1]:.0f} studs -> cut to a tighter two-shot at the arrival (t{ta_:.2f})")
                continue
        on_ = list(s.get('on', list(cast)[:1]))
        if len(on_) == 1 and on_[0] in cast:   # a fighter striking in this shot: the target joins as co-subject (in frame, not an occluder, face optional) (R123)
            tg = next(((bb['attack'].get('target') if isinstance(bb['attack'], dict) else bb.get('target'))
                       for bb in beats if bb['who'] == on_[0] and 'attack' in bb and f0 - 14 <= F(bb['t'], fps) <= f1 + 2), None)
            if tg in cast: s['on'] = on_ + [tg]
        subj = [cast[x] if x in cast else target_of(x) for x in s.get('on', list(cast)[:1])]
        chs_ = [x for x in subj if hasattr(x, 'head_mesh')]
        if len(chs_) >= 2 and not s.get('keep_two'):   # too far apart for one 9:16 frame -> a single on the focus (editor's choice)
            sc.frame_set((f0 + f1) // 2)
            if (chs_[0].root.matrix_world.translation - chs_[1].root.matrix_world.translation).length > 8 * S:
                subj = [x for x in subj if x is chs_[0] or not hasattr(x, 'head_mesh')]
                log.setdefault('notes', []).append(f"shot at {s['t']}s: two-shot too wide (> 8 studs apart) -> single on {chs_[0].name}")
        # props grabbed inside this shot: they must read UP TO the grab frame (afterwards the hand covers them by design)
        until = {m.name: fg_ + 2 for piv, side, pr, fg_, f1_ in grabs if f0 <= fg_ <= f1 and pr in subj
                 for m in pr.children_recursive if m.type == 'MESH'}
        # angle from emotion (reference): power/shock beats of the focus character -> low angle, small/sad beats -> high angle
        ang = s.get('angle')   # authored, or chosen by camera.grammar (R213: the emotion rule moved there)
        prev_cam = camera.LAST.get('cam')
        if s.get('pov') in cast: cam, v = camera.pov_shot(sc, f'S{i + 1:02d} {s.get("kind", "medium")}', f0, f1, cast[s['pov']], s.get('lens', 28), [v for k, v in cast.items() if k != s['pov']])   # camera mode pov
        else: cam, v = camera.shot(sc, f'S{i + 1:02d} {s.get("kind", "medium")}', f0, f1, s.get('kind', 'medium'), subj, s.get('side', 0), s.get('lens', 50),
                             s.get('push'), track=s.get('track', False), cast=list(cast.values()), vis_until=until, angle=ang,
                             motion=s.get('move'), ecu=s.get('ecu', False), soft=s.get('_soft', False), ots_first=s.get('ots', False), front=s.get('front', False), profile=s.get('profile', False), frame=s.get('frame'),
                             punch=F(s['punch'], fps) if s.get('punch') is not None else None)
        why_ = lambda: f"S{i + 1:02d} ({s.get('kind', 'medium')} on {' + '.join(s.get('on', list(cast)[:1]))} at {s['t']}s): {camera.plain(camera.vis_low(cam.name, v))}"   # item 6: plain words for writers
        side_on_ = True
        if s.get('_fight_auto'):   # is the camera really side-on? (every profile spot a jump cut / hidden -> a later round found some other angle)
            sc.frame_set((f0 + f1) // 2); ln_ = (subj[1].root.matrix_world.translation - subj[0].root.matrix_world.translation).xy
            dv_ = (cam.matrix_world.to_3x3() @ Vector((0, 0, -1))).xy
            side_on_ = ln_.length < 1e-4 or dv_.length < 1e-4 or abs(dv_.normalized().dot(ln_.normalized())) < 0.77
        if s.get('_fight_auto') and not side_on_ and i > 0 and len(cams_) == i and shots[i - 1].get('fight') and shots[i - 1].get('profile') and not shots[i - 1].get('hold') \
                and set(shots[i - 1].get('on', [])) == set(s.get('on', [])):
            # the shot before it is the SAME side-on two-shot of the same pair at the same size: a cut between them is a jump cut, so
            # there is no cut - the shot before runs on over both spans (and may be cut at a dash-in arrival)
            log.setdefault('notes', []).append(f"shot at {s['t']}s: the same side-on two-shot of {' + '.join(s['on'])} as the shot before it (a cut between them would be a jump cut) -> one shot from {shots[i - 1]['t']}s")
            for c_ in (cam, cams_.pop()): vis.pop(c_.name, None); log.get('cam_shots', {}).pop(c_.name, None); unshoot_(c_)
            camera.LAST['cam'] = cams_[-1] if cams_ else None
            if s.get('shake'): shots[i - 1]['shake'] = list(shots[i - 1].get('shake', [])) + list(s['shake'])
            shots[i - 1].pop('_arr', None); shots.pop(i); i -= 1
            continue
        if s.get('_fight_auto') and (camera.vis_low(cam.name, v) or not side_on_):   # the side-on view the engine chose hides a fighter: the authored front two-shot is shot instead
            log.setdefault('notes', []).append(f"{why_() if camera.vis_low(cam.name, v) else 'S%02d (two-shot at %ss): no clear camera position' % (i + 1, s['t'])} from the side -> shot from the front as written")
            unshoot_(cam); camera.LAST['cam'] = prev_cam
            shots[i] = {**{k_: v_ for k_, v_ in s.items() if k_ not in ('fight', '_fight_auto', '_arr')}, 'profile': False}
            continue
        if s.get('top_fall') and not camera.vis_low(cam.name, v) and camera.slab(v):   # set geometry under the lens from every azimuth
            log.setdefault('notes', []).append(f"S{i + 1:02d}: the top-down landing shot of {s['on'][0]} has a set piece between the lens and the body from every side -> not used")
            unshoot_(cam); camera.LAST['cam'] = prev_cam; shots[i] = s['_alt']
            continue
        if s.get('establish') and (camera.vis_low(cam.name, v) or camera.slab(v)):   # an AUTOMATIC shot nobody asked for must read (and not show a slab / the void), else it is dropped
            bad_ = camera.vis_low(cam.name, v) or [f"{k} {x}" for k, x in v.items() if k in ('fg~', 'fgb~', 'bg~')]
            for m_ in list(sc.timeline_markers):
                if m_.camera is cam: sc.timeline_markers.remove(m_)
            bpy.data.objects.remove(cam, do_unlink=True); camera.LAST['cam'] = prev_cam; camera.HIST.pop(f'S{i + 1:02d} {s.get("kind", "medium")}', None)
            log.setdefault('notes', []).append(f"S{i + 1:02d}: automatic establishing wide unreadable {bad_[:2]} -> dropped")
            shots.pop(i); shots[i]['t'] = 0.0
            continue
        if camera.vis_low(cam.name, v) and s.get('kind') in ('wide', 'full') and len(subj) == 1 and hasattr(subj[0], 'head_mesh'):
            bad_ = camera.vis_low(cam.name, v)
            for m_ in list(sc.timeline_markers):
                if m_.camera is cam: sc.timeline_markers.remove(m_)
            bpy.data.objects.remove(cam, do_unlink=True); camera.LAST['cam'] = prev_cam
            cam, v = camera.shot(sc, f'S{i + 1:02d} medium', f0, f1, 'medium', subj, s.get('side', 0), 50,
                                 None, track=s.get('track', False), cast=list(cast.values()), angle=ang)
            log.setdefault('notes', []).append(f"S{i + 1:02d} ({s['kind']} on {subj[0].name} at {s['t']}s): {camera.plain(bad_[:2])} at this size -> shot as a medium on {subj[0].name}")
        if camera.vis_low(cam.name, v) and len(subj) == 1 and not hasattr(subj[0], 'head_mesh'):   # any PROP-ONLY shot (a split insert became a 'medium' on the phone, R175)
            # editor's fallback: no camera reads this insert (a small prop swinging between two walkers, phone s01/s02) ->
            # re-cut as a MEDIUM on the character holding it (prop in hand, face readable); logged, never silent
            hold_ = next((c_ for c_ in cast.values() for pv, sd, pp, a0, a1 in grabs
                          if pp is subj[0] and pv in c_.arms_piv and a0 <= f1 and (a1 >= END or a1 >= f0)), None)
            if hold_ is not None:
                for m_ in list(sc.timeline_markers):
                    if m_.camera is cam: sc.timeline_markers.remove(m_)
                bad_ = camera.vis_low(cam.name, v); bpy.data.objects.remove(cam, do_unlink=True); camera.LAST['cam'] = prev_cam
                cam, v = camera.shot(sc, f'S{i + 1:02d} medium', f0, f1, 'medium', [hold_], 0, 50, None, track=s.get('track', False),
                                     cast=list(cast.values()), angle=ang)
                subj = [hold_]
                log.setdefault('notes', []).append(f"S{i + 1:02d}: insert on {subj_name_ if (subj_name_ := s.get('on', ['?'])[0]) else '?'} ({camera.plain(bad_[:2])}) -> shot as a medium on {hold_.name}, who holds it")
        if camera.vis_low(cam.name, v) and s.get('keep_two') and not s.get('fight') and len(chs_) >= 2:   # the two-shot shows only one of them from every
            for m_ in list(sc.timeline_markers):                                     # angle (blind2_store: Nico in an aisle behind
                if m_.camera is cam: sc.timeline_markers.remove(m_)                  # shelves, head 0.11) -> visibility beats keep_two:
            bad_ = camera.vis_low(cam.name, v); bpy.data.objects.remove(cam, do_unlink=True); camera.LAST['cam'] = prev_cam
            subj = [x for x in subj if x is chs_[0] or not hasattr(x, 'head_mesh')]   # a single on the focus, logged
            cam, v = camera.shot(sc, f'S{i + 1:02d} {s.get("kind", "medium")}', f0, f1, s.get('kind', 'medium'), subj, s.get('side', 0), s.get('lens', 50),
                                 s.get('push'), track=s.get('track', False), cast=list(cast.values()), vis_until=until, angle=ang, motion=s.get('move'))
            log.setdefault('notes', []).append(f"S{i + 1:02d} (two-shot at {s['t']}s): {camera.plain(bad_[:2])} -> shot as a single on {chs_[0].name}")
        if not camera.vis_low(cam.name, v) and camera.slab(v) and len([x for x in subj if hasattr(x, 'head_mesh')]) >= 2 and not s.get('keep_two'):
            # R219 a two-shot whose every camera shows a SLAB (the bed top across the lower half, factory R212b f12) or the void behind
            # the set: try a single on the focus; kept only if it passes the gates without a slab, else the two-shot is shot again
            def reshoot_(sub_):
                for m_ in list(sc.timeline_markers):
                    if m_.camera is camera.LAST.get('cam'): sc.timeline_markers.remove(m_)
                bpy.data.objects.remove(camera.LAST['cam'], do_unlink=True); camera.LAST['cam'] = prev_cam
                return camera.shot(sc, f'S{i + 1:02d} {s.get("kind", "medium")}', f0, f1, s.get('kind', 'medium'), sub_, s.get('side', 0), s.get('lens', 50),
                                   s.get('push'), track=s.get('track', False), cast=list(cast.values()), vis_until=until, angle=ang, motion=s.get('move'), soft=s.get('_soft', False))
            two_ = subj; one_ = [x for x in subj if x is chs_[0] or not hasattr(x, 'head_mesh')]
            cam, v1_ = reshoot_(one_)
            if camera.vis_low(cam.name, v1_) or camera.slab(v1_): cam, v = reshoot_(two_)
            else:
                v = v1_; subj = one_; log.setdefault('notes', []).append(f"S{i + 1:02d}: two-shot shows a slab/void from every camera -> single on {chs_[0].name}")
        fk = subj[0].name + ' face' if subj and hasattr(subj[0], 'head_mesh') else None
        if fk and s.get('kind') == 'close' and len(subj) == 1 and not s.get('ecu') and not s.get('_alt') and not s.get('_med') and v.get(subj[0].name + ' safe~', 1.0) < 1.0:
            # cam2 A CLOSE-UP HOLDS THE FACE ON EVERY FRAME: still not (after no push / re-aim in camera._shot) -> a medium, kept when
            # it holds the face on more frames and passes the gates; else the close-up is shot again
            s['_med'] = True; c0_ = v[subj[0].name + ' safe~']; unshoot_(cam); camera.LAST['cam'] = prev_cam
            cam, v = camera.shot(sc, f'S{i + 1:02d} medium', f0, f1, 'medium', subj, s.get('side', 0), s.get('lens', 50), s.get('push'), track=s.get('track', False),
                                 cast=list(cast.values()), vis_until=until, angle=ang, soft=s.get('_soft', False), front=s.get('front', False))
            if camera.vis_low(cam.name, v) or v.get(subj[0].name + ' safe~', 1.0) <= c0_:
                unshoot_(cam); camera.LAST['cam'] = prev_cam
                continue   # the close-up again ('_med' set: no second try)
            log.setdefault('notes', []).append(f"S{i + 1:02d} (close on {subj[0].name} at {s['t']}s): the face leaves the frame or drops into the caption zone on {100 - int(100 * c0_)} % of the frames (the character moves) -> shot as a medium")
        if fk and camera.vis_low(cam.name, v) and not s.get('_cut') and f1 - f0 >= 24:
            # CUT AT THE HEAD TURN (editor's rule): the shot fails its face check and the focus head swings > 60 deg between
            # 25 % and 75 % of it -> end this shot at the turn and give the turn its own piece (next size: no jump cut); both are
            # re-shot. Only after a FAILED check (a pre-camera cut split a passing reveal, R159).
            ch_ = subj[0]
            def yaw_at(fr):
                sc.frame_set(fr); v_ = ch_.head.matrix_world.to_3x3() @ Vector((0, -1, 0)); return math.atan2(v_.x, -v_.y)
            cut = None   # a FAST swing: > 50 deg within 8 frames (Max swung left ~45 then right 92 deg: a start-relative test missed it)
            for fr in range(f0 + (f1 - f0) // 4, f0 + 3 * (f1 - f0) // 4 + 1, 2):
                if abs((yaw_at(fr + 8) - yaw_at(fr) + math.pi) % (2 * math.pi) - math.pi) > math.radians(50): cut = fr + 4; break
            if cut is not None:
                for m_ in list(sc.timeline_markers):
                    if m_.camera is cam: sc.timeline_markers.remove(m_)
                bpy.data.objects.remove(cam, do_unlink=True); camera.LAST['cam'] = prev_cam
                s['_cut'] = True
                k_ = ALT.get(s.get('kind', 'medium'), 'close')   # a CLOSE piece frames the face: held props drop out of its targets (snack S07 apple)
                shots.insert(i + 1, {**s, 't': round(cut / fps, 3), 'kind': k_, 'auto': True, '_cut': True,
                                     'on': [x for x in s.get('on', []) if x in cast] or s.get('on', []) if k_ == 'close' else s.get('on', [])})
                log.setdefault('notes', []).append(f"{s.get('kind', 'medium')} shot at {s['t']}s cut at {ch_.name}'s head turn f{cut}")
                continue   # re-shoot shot i with its new (shorter) end
        # R240: ... or whose subject does not READ from any camera (a limb fills the insert, the face only in profile / from under the chin)
        g_ = lambda suf: min([y for k_, y in v.items() if k_.endswith(suf)] or [1.0])   # clearly unreadable only (the search itself is stricter)
        unr_ = [x for x in camera.unread(cam.name, v, eyes=False) if x == 'limb fills the frame' or x == 'face turned away' or x.startswith(('face leaves', 'another actor'))
                or (x == 'head cropped' and g_(' framed~') < 0.5)]
        cut_ = camera.LAST.get('cut')
        if (cut_ and cut_[0] and (unr_ or (cut_[1] < 30 and cut_[2] < 1.4)) and s.get('auto') and not s.get('establish') and not s.get('_cut')
                and i > 0 and len(cams_) == i and (i - 1) not in cheated_ and not shots[i - 1].get('_cut')):
            # R240 NEAR-DUPLICATE PIECE: an automatic piece on the SAME subject as the shot before it that changes neither the angle
            # (>= 30 deg) nor the size (>= 1.4x), or that reads only from the angle the shot before it already has (every readable
            # camera is a jump cut), is not a cut: the piece is dropped and the shot before it is re-shot over both spans
            for c_ in (cam, cams_.pop()):
                vis.pop(c_.name, None); camera.HIST.pop(c_.name, None)
                for m_ in list(sc.timeline_markers):
                    if m_.camera is c_: sc.timeline_markers.remove(m_)
                bpy.data.objects.remove(c_, do_unlink=True)
            camera.LAST['cam'] = cams_[-1] if cams_ else None
            log.setdefault('notes', []).append(f"S{i + 1:02d}: automatic piece repeats S{i:02d} (same subject, {cut_[1]:.0f} deg, size x{cut_[2]:.2f}{', ' + unr_[0] if unr_ else ''}) -> not split")
            shots.pop(i); i -= 1
            continue
        if (camera.vis_low(cam.name, v) or unr_) and s.get('_alt'):   # an AUTOMATIC piece (rhythm alternation, reaction cut, story insert) that no
            bad_ = camera.vis_low(cam.name, v) or unr_        # camera reads, after every rescue above: the cut goes back to what it
            for m_ in list(sc.timeline_markers):              # replaced (the authored shot continues from another side). The editor
                if m_.camera is cam: sc.timeline_markers.remove(m_)   # never forces a cut the set cannot show (blind2_store S08 close)
            bpy.data.objects.remove(cam, do_unlink=True); camera.LAST['cam'] = prev_cam; camera.HIST.pop(cam_name_ := f'S{i + 1:02d} {s.get("kind", "medium")}', None)
            log.setdefault('notes', []).append(f"{cam_name_} (engine's own cut at {s['t']}s): {camera.plain([x for x in bad_ if ':' in x][:2], [x for x in bad_ if ':' not in x][:2])} -> back to the authored shot")
            shots[i] = s['_alt']
            continue
        if fk and v.get(fk, 1.0) < 0.5:   # PER-SHOT CHEAT: turn the focus up to 40 deg toward this camera, keyed on the cuts (invisible)
            ch_ = subj[0]; busy = any(pv in ch_.arms_piv and a0 <= f1 and a1 >= f0 for pv, sd, pp, a0, a1 in grabs)                 or any(w['who'] == ch_.name and w['f0'] <= f1 and w['f1'] >= f0 - 1 for w in log.get('walks', [])) or ch_.name in seated or root_busy(ch_, f0, f1)
            if not busy:
                cheated_.add(i)
                r = ch_.root; sc.frame_set(f0); z_old = r.rotation_euler.z; cp_ = cam.matrix_world.translation; rp = r.matrix_world.translation
                want = math.atan2(cp_.x - rp.x, -(cp_.y - rp.y)); dz_ = (want - z_old + math.pi) % (2 * math.pi) - math.pi
                z_new = z_old + max(-math.radians(40), min(math.radians(40), dz_))
                for fr_, zz in ((f0 - 1, z_old), (f0, z_new), (f1, z_new), (f1 + 1, z_old)):   # Z only (keep fall/get-up X keys)
                    r.rotation_euler.z = zz; r.keyframe_insert('rotation_euler', index=2, frame=fr_)
                for fc in fcurves_of(r):   # snap ON the cuts (Blender 5: fcurves live in the slot's channelbag)
                    if fc.data_path == 'rotation_euler' and fc.array_index == 2:
                        for kp in fc.keyframe_points:
                            if kp.co.x in (f0 - 1, f0, f1, f1 + 1): kp.interpolation = 'CONSTANT'
                v[fk] = round(camera.face_vis(sc, cam, ch_, sorted(set(list(range(f0, f1 + 1, 3)) + [f1])), q=0.25), 2)
                log.setdefault('notes', []).append(f"{cam.name}: cheated {ch_.name} {math.degrees(z_new - z_old):.0f} deg to camera (face {v[fk]})")
        if subj and hasattr(subj[0], 'head_mesh'):   # focus lying FACE-DOWN in this shot: its face cannot read, report only
            if any(who_ == subj[0].name and direction_ == 'forward' and a_ <= f0 and f1 < z_
                   for who_, a_, z_, direction_ in log.get('fall_spans', [])):
                v = {(k + '~' if k == subj[0].name + ' face' else k): x for k, x in v.items()}
        if not s.get('auto') and (camera.vis_low(cam.name, v) or [x for x in unr_ if x != 'head cropped']):   # (head cropped: the hair bbox is wider than the hair, too noisy to tell a writer)   # item 6: an authored shot the engine could not make read is SAID, in plain words
            log.setdefault('notes', []).append(f"{cam.name} at {s['t']}s on {' + '.join(getattr(x, 'name', '?') for x in subj)}: kept as written, but {camera.plain(camera.vis_low(cam.name, v), [x for x in unr_ if x != 'head cropped'])}")
        vis[cam.name] = v
        log.setdefault('cam_shots', {})[cam.name] = {'kind': cam.name.split(' ', 1)[-1], 'on': [getattr(x, 'name', '?') for x in subj], 'angle': ang, 'auto': bool(s.get('auto')),   # for l1_cam.py
                                                     **{k: s[k] for k in ('ots', 'react', 'punch', 'reveal', 'move') if k in s}, 'ots_cam': bool(cam.get('ots')), 'follow_cam': bool(cam.get('follow'))}
        for t in s.get('shake', []):
            ia.cam_shake(sc, cam, F(t, fps), s.get('shake_amp', 0.05), seed=F(t, fps))
        cams_.append(cam); i += 1
    for o in shafts_: o.hide_viewport = False   # back for the render
    TT_['shots'] = round(time.time() - T0_ - sum(TT_.values()), 1)
    # PHYSICAL GATES on the FINAL animation (after the shots: per-shot cheats rotate roots on the cuts, Codex review #11)
    cut_frames = {m.frame for m in sc.timeline_markers}
    # WHOLE-BODY gate (space.py): torso/head/legs vs the scene's REAL meshes (exact triangles, > 2 cm) and vs other bodies,
    # EVERY frame; a seat is exempt only for its own sitter during the sit. Replaces the 2D footprint (every 2nd frame, 10 cm,
    # global seat + lying exemptions, classroom desks never registered).
    sit_spans = log.get('sit_spans', [])
    seat_of = lambda who, f: {sp[3] for sp in sit_spans if sp[0] == who and sp[1] <= f <= sp[2]}
    body_hits = space.World(sc, cast, props).scene_hits(range(0, n), exempt_fn=seat_of)
    if body_hits:
        worst_ = max(body_hits, key=lambda h: h[3])
        log['body_hits'] = len(body_hits); log['body_worst'] = worst_
        log.setdefault('errors', []).append(f"body through {worst_[2]} ({worst_[1]} f{worst_[0]} >{worst_[3] * 100:.0f}cm, {len(body_hits)} part-frame hits)")
    # FOOT SLIDE measured on the final curves (walk, run, shuffle, turns): the old value was a defaulted 0
    for sp_ in ([] if os.environ.get('ENGINE_NO_FALL_SETTLE') == '1' else log.get('fall_spans', [])):   # (env = evidence only: the pre-R214 bug) R214 FLOOR SETTLE after every arm pass: the fall rested ON the floor, then the arm
        lo._rest_on_floor_add(sc, cast[sp_[0]], range(max(0, sp_[1] - 2), min(sp_[2], n) + 1))   # cleanup re-keyed a face-down
    log['foot_slide'] = {}   # fall's arms 29 cm into the floor (factory mom story, t_fall_kitchen s02)
    for ch in cast.values():
        d_, f_, k_ = lo.foot_slide(sc, ch, range(0, n), cuts=cut_frames)
        log['foot_slide'][ch.name] = round(d_ * 100, 1)
        if d_ > 0.02: log.setdefault('errors', []).append(f"foot slide {ch.name} {d_ * 100:.1f}cm f{f_}")
        if os.environ.get('SLIDEDEBUG'):   # per-frame root + lowest corner of each leg (x, y, z cm)
            for fr in range(*map(int, os.environ['SLIDEDEBUG'].split(','))):
                sc.frame_set(fr); print('SLIDEDBG', ch.name, fr, [round(v * 100, 1) for v in ch.root.location], [round(math.degrees(v)) for h in ch.hips for v in h.rotation_euler] + [round(h.location.z * 100, 1) for h in ch.hips], [[round(v * 100, 1) for v in min((l.matrix_world @ Vector(c) for c in l.bound_box), key=lambda q: q.z)] for l in ch.legs])
    for ch in cast.values():   # FLOOR gate, no exemptions (a seat exemption hid feet 11 cm under the floor, R135 Codex #10)
        parts_ = [ch.torso, ch.head_mesh] + list(ch.legs) + list(ch.arms); worst_ = (0.0, None)
        for fr in range(0, n, 2):
            sc.frame_set(fr); low_ = min((o.matrix_world @ Vector(c)).z for o in parts_ for c in o.bound_box)
            if -low_ > worst_[0]: worst_ = (-low_, fr)
        if worst_[0] > 0.02: log.setdefault('errors', []).append(f"below floor {ch.name} {worst_[0] * 100:.0f}cm f{worst_[1]}")
        if worst_[0] > 0.02 and os.environ.get('ACTDEBUG'):
            sc.frame_set(worst_[1]); print('FLOORDEBUG', [(o.name, round(min((o.matrix_world @ Vector(c)).z for c in o.bound_box), 3)) for o in parts_], [(o.name, [round(math.degrees(v)) for v in o.rotation_euler]) for o in (ch.arm['R'], ch.arm['L'], ch.head, ch.upper)])

    # fight VFX: baked AFTER the cameras are chosen (auras/beams must not steer framing) and after all motion is final
    mk = sorted(sc.timeline_markers, key=lambda m: m.frame)
    cam_at = lambda fr: next((m.camera for m in reversed(mk) if m.frame <= fr), mk[0].camera if mk else None)
    for job in vfx_jobs:
        try:
            for o in job(): o.name = 'VFX ' + o.name
        except (ValueError, AssertionError, KeyError) as e:
            log.setdefault('errors', []).append(f'vfx: {str(e)[:80]}')
    for fr in log.get('impact_frames', []):   # every hit shakes the camera that shows it
        if cam_at(fr): ia.cam_shake(sc, cam_at(fr), fr, 0.06, seed=fr)
    # FACE ACCENTS ON THE CUTS (after the shots: it needs the final cut list): a close-up lands on a changed face, a blink / mouth
    # pop follows every cut onto a character and no on-screen face holds still for > ~1.4 s (acting.face_accents)
    spans_ = {c_: [] for c_ in cast}; closes_ = {c_: [] for c_ in cast}
    for j_, s_ in enumerate(shots):
        a_ = F(s_['t'], fps); z_ = (F(shots[j_ + 1]['t'], fps) - 1) if j_ + 1 < len(shots) else n - 1
        for c_ in [x for x in s_.get('on', list(cast)[:1]) if x in cast][:1 if s_.get('kind') == 'close' else 9]:
            if z_ > a_: spans_[c_].append((a_, min(z_, n - 5)))
            if z_ > a_ and s_.get('kind') == 'close': closes_[c_].append((a_, z_))
    log['faces'] = {}
    for c_ in cast:
        before_ = acting.face_hold(face_sched[c_], spans_[c_])
        if spec.get('auto_faces', True) and spec.get('auto_acting', True):
            for f_, k_ in sorted(acting.face_accents(face_sched[c_], spans_[c_], closes_[c_], faces.library(), fam=log['face_family'][c_]).items()):
                if k_ in faces.KINDS: faces.set(c_, k_, f_); face_sched[c_][f_] = k_
        d_, r_ = acting.face_runs(face_seq[c_])
        log['faces'][c_] = {'distinct': d_, 'max_run': r_, 'hold_max_s': round(acting.face_hold(face_sched[c_], spans_[c_]) / fps, 2),
                            'hold_before_s': round(before_ / fps, 2), 'seq': [k_ for _, k_ in face_seq[c_]], 'closes': closes_[c_]}
    if spec.get('crowd'): make_crowd(sc, spec, cast, n, log)   # after gates + cameras: extras are never gated
    sc.camera = sc.timeline_markers[0].camera if len(sc.timeline_markers) else None
    TT_['gates_vfx'] = round(time.time() - T0_ - sum(TT_.values()), 1); log['timing'] = TT_; print('TIMING', TT_)
    hero = cast[spec['cast'][0]['name']]
    cuts = ia.cut_report(sc, hero.head_mesh) if len(shots) > 1 else []
    log.update({'pen_hits': pen['hits'], 'pen_worst_cm': round(100 * pen['worst'][0]['depth_m'], 1) if pen['worst'] else 0.0,
                'pen_where': [(r['f'], r['limb'], r['prop']) for r in pen['worst'][:3]],
                'jump_cuts': [c['cut'] for c in cuts if c['jump_cut']], 'visibility': vis, 'frames': n})
    return sc


def gates(log):
    bad = list(log.get('errors', []))
    if log['pen_worst_cm'] > 2.0: bad.append(f"depth {log['pen_worst_cm']}cm")
    for w in log.get('walks', []):
        pass   # slide: measured per character in log['foot_slide'] (errors list), see the WHOLE-BODY gate block
    if log['jump_cuts']: bad.append(f"jump cuts {log['jump_cuts']}")
    low = [x for c, v in log['visibility'].items() for x in camera.vis_low(c, v)]   # one rule for the chooser and the gate
    if low: bad.append(f'hidden {low[:3]}')
    return bad


def render(sc, tier, out, frames):
    look.tier(sc, tier)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time(); k = 0
    fr = list(frames)
    if tier in look.LOCAL:   # mid / preview: per frame like farm_hq, skipping frames already on disk (a stop keeps the work)
        key = f"{tier} {zlib.crc32(b''.join(p.read_bytes() for p in [Path(ARGS[0])] + sorted(Path(__file__).resolve().parent.glob('*.py')))):08x}"
        todo = look.todo_frames(out, fr, key)
        print(f'RENDER {tier}: {len(fr) - len(todo)} of {len(fr)} frames already on disk', flush=True)
        for f in todo:
            sc.frame_set(f); sc.render.filepath = str(out / f'{f:04d}.png'); bpy.ops.render.render(write_still=True); k += 1
            print(f'{tier.upper()} frame {f} done {time.time() - t0:.0f}s', flush=True)
        return k, time.time() - t0
    if len(fr) > 1 and fr == list(range(fr[0], fr[-1] + 1)) and '--resume' not in ARGS:   # one animation render: no per-frame re-sync
        sc.frame_start, sc.frame_end = fr[0], fr[-1]; sc.render.filepath = str(out) + '/'; sc.render.use_file_extension = True
        bpy.ops.render.render(animation=True)
        return len(fr), time.time() - t0
    for f in frames:
        p = out / f'{f:04d}.png'
        if p.exists() and '--resume' in ARGS: continue
        sc.frame_set(f); sc.render.filepath = str(p); bpy.ops.render.render(write_still=True); k += 1
    return k, time.time() - t0


if __name__ == '__main__':
    jpath = Path(ARGS[0]).resolve(); spec = json.loads(jpath.read_text(encoding='utf-8'))
    sdir = jpath.parent; tier = arg('--tier', 'draft'); log = {'short': spec.get('title', sdir.name), 'tier': tier}
    TIER = tier
    t0 = time.time()
    if os.environ.get('BUILD_PROFILE'):   # speed work: cProfile the build, top 30 by cumulative time -> build/profile.txt
        import cProfile, pstats, io
        pr_ = cProfile.Profile(); pr_.enable(); sc = build(spec, log); pr_.disable()
        s_ = io.StringIO(); pstats.Stats(pr_, stream=s_).sort_stats('tottime').print_stats(30); (sdir / 'build').mkdir(exist_ok=True)
        (sdir / 'build' / 'profile.txt').write_text(s_.getvalue(), encoding='utf-8')
    else:
        sc = build(spec, log)
    log['build_s'] = round(time.time() - t0, 1)
    import importlib   # LEVEL 1 field checks (LEVEL1.md): each field owner writes l1_<field>.py with checks(sc, spec, log) ->
    l1_ = {}           # {name: {'ok': bool, 'value': ..., 'limit': ...}}; stored in report.json["L1"], judged by tools/level1.py
    for f_ in ('move', 'face', 'cam', 'acc'):
        try: mod_ = importlib.import_module('l1_' + f_)
        except ModuleNotFoundError: continue
        try: l1_.update({f'{f_}.{k}': v for k, v in (mod_.checks(sc, spec, log) or {}).items()})
        except Exception as e: l1_[f'{f_}.crash'] = {'ok': False, 'value': f'{type(e).__name__}: {e}'[:300]}
    if l1_: log['L1'] = {'ok': all(v.get('ok') for v in l1_.values()), 'checks': l1_}
    (sdir / 'build').mkdir(exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(sdir / 'build' / 'scene.blend'))
    bad = gates(log); log['gates'] = bad or 'PASS'
    if tier != 'none':
        if '--frames' in ARGS: fr = [int(x) for x in ARGS[ARGS.index('--frames') + 1:] if x.isdigit()]
        elif '--range' in ARGS: a, b = int(arg('--range')), int(ARGS[ARGS.index('--range') + 2]); fr = range(a, b + 1)
        else: fr = range(sc.frame_start, sc.frame_end + 1)
        sheet_only = bad and tier == 'draft' and '--full' not in ARGS and '--frames' not in ARGS and '--range' not in ARGS
        if sheet_only:   # failing draft: render just the 16 sheet frames (what gets reviewed); the full video waits for PASS
            n_ = sc.frame_end + 1; fr = [round(i * (n_ - 1) / 15) for i in range(16)]
        out = Path(arg('--out', str(sdir / 'out' / tier)))
        if '--frames' not in ARGS and '--range' not in ARGS and '--resume' not in ARGS and tier not in look.LOCAL and out.exists():
            shutil.rmtree(out)   # fresh full render (no shell rm -rf: it can trigger a permission prompt overnight)
        k, dt = render(sc, tier, out, fr); log['render'] = {'frames': k, 's': round(dt, 1), 's_per_frame': round(dt / max(k, 1), 2)}
        if sheet_only:
            for i, f_ in enumerate(fr): shutil.copy2(out / f'{f_:04d}.png', out / f'sheet_{i:02d}.png')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(out / 'sheet_%02d.png'), '-vf', 'scale=180:-2,tile=8x2', '-frames:v', '1', str(sdir / f'{tier}_sheet.jpg')])
            (sdir / f'{tier}.mp4').unlink(missing_ok=True); log['video'] = 'sheet only (gates failed; --full renders the video)'
        elif '--frames' not in ARGS and '--range' not in ARGS:
            mp4 = sdir / f'{tier}.mp4'; src, vf, t_up = out, [], time.time()
            if tier in look.LOCAL:   # 540x960 -> 1080x1920: Lanczos as the farm does, or Real-ESRGAN x2 when asked and installed
                src, vf = look.upscale(out, sdir / 'out' / f'{tier}_x2', look.frame_size(sc))
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', str(sc.render.fps), '-start_number', '0', '-i', str(src / '%04d.png'), *vf,
                            '-c:v', 'libx264', '-crf', '16' if tier in look.LOCAL else '20', '-pix_fmt', 'yuv420p', str(mp4)])
            if tier in look.LOCAL: log['assemble_s'] = round(time.time() - t_up, 1)
            step = max(1, len(fr) // 16)
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(mp4), '-vf', f"select='not(mod(n\\,{step}))',scale=180:-2,tile=8x2", '-frames:v', '1', str(sdir / f'{tier}_sheet.jpg')])
            log['video'] = str(mp4)
    (sdir / 'report.json').write_text(json.dumps(log, indent=1))
    # video trace: keep every round's sheet/stills + report under trace/ with a timestamp (never overwritten)
    stamp = time.strftime('%Y%m%d-%H%M%S'); tdir = Path(__file__).resolve().parent / 'trace'; tdir.mkdir(exist_ok=True)
    tag = f'{stamp}_{sdir.name}_{tier}'
    for src in [sdir / f'{tier}_sheet.jpg'] if '--frames' not in ARGS else []:
        if src.exists(): shutil.copy2(src, tdir / f'{tag}_sheet.jpg')
    if '--frames' in ARGS:
        try:
            subprocess.run([sys.executable if False else 'python', str(Path(__file__).resolve().parent / 'tools' / 'stills_sheet.py'), str(out), str(tdir / f'{tag}_stills.jpg')], check=False)
        except Exception as e: print('trace stills failed', e)
    shutil.copy2(sdir / 'report.json', tdir / f'{tag}_report.json'); shutil.copy2(jpath, tdir / f'{tag}_short.json')
    w = log.get('walks', [])
    print('REPORT', 'PASS' if not bad else 'FAIL ' + '; '.join(bad), f"| hits {log['pen_hits']} worst {log['pen_worst_cm']}cm",
          f"| slide {max(log.get('foot_slide', {}).values(), default=0)}cm | cuts {'OK' if not log['jump_cuts'] else log['jump_cuts']}",
          f"| build {log['build_s']}s", f"| render {log.get('render', {}).get('s', 0)}s", f"| {log.get('video', '')}")
