"""affordances.py - what an object OFFERS a character, read from its geometry (motion foundation Task 4).
seat(piece): seat surface centre/height/facing; seat_entry(world, ch, piece): where to stand before sitting (clear, with room
to turn). Grips and hinges are added where they are first used (hands Task 6, doors Wave 2). Units: metres."""
import math
from mathutils import Vector
import staging
import bpy

S = staging.S
import os
SEATDEBUG = os.environ.get('SEATDEBUG') == '1'   # prints every seat candidate and why it was rejected


def _verts(piece):
    return [o.matrix_world @ v.co for o in piece.children_recursive if o.type == 'MESH' for v in o.data.vertices]


def seat(piece, _redirected=False):
    """{'pos': (x, y), 'z': seat surface height, 'yaw': facing (rad, forward = (sin, -cos))}.
    Seat height = the largest upward-facing surface between 25 % and 65 % of the model height (a 45 %-of-height guess put
    seats inside cushions or under them); facing = away from the backrest (vertices above 60 %)."""
    vs = _verts(piece)
    if not vs: raise ValueError(f'{piece.name}: no mesh')
    width = max(v.x for v in vs) - min(v.x for v in vs)
    depth = max(v.y for v in vs) - min(v.y for v in vs)
    if min(width, depth) < .6 and piece.parent:
        # Imported bed boundary panels and sofa backrests (thinner than an R6 lap, 0.6 m) can be named seats;
        # use the adjacent cushion/mattress, not the panel.
        nearby = []
        px = (max(v.x for v in vs) + min(v.x for v in vs)) / 2; py = (max(v.y for v in vs) + min(v.y for v in vs)) / 2
        for sibling in piece.parent.children:
            if sibling is piece or sibling.name.rsplit('_', 1)[0] != piece.name.rsplit('_', 1)[0]: continue
            sv = _verts(sibling)
            if not sv: continue
            x0, x1 = min(v.x for v in sv), max(v.x for v in sv)
            y0, y1 = min(v.y for v in sv), max(v.y for v in sv)
            if min(x1 - x0, y1 - y0) < .6: continue
            if x0 - .3 <= px <= x1 + .3 and y0 - .3 <= py <= y1 + .3:
                nearby.append(((x1 - x0) * (y1 - y0), max(v.z for v in sv), sibling))
        nearby = [q for q in nearby if q[0] > .25]
        if nearby:
            # A sofa stacks base + cushion: the seat is the TOP surface (the base under the cushion read as a seat).
            return seat(max(nearby, key=lambda q: q[1])[2])
    zt, zb = max(v.z for v in vs), min(v.z for v in vs); H = zt - zb
    areas = {}
    for o in piece.children_recursive:
        if o.type != 'MESH': continue
        M = o.matrix_world; R = M.to_3x3().normalized(); sx, sy = M.to_scale().x, M.to_scale().y
        for p in o.data.polygons:
            if (R @ p.normal).z < 0.9: continue
            z = sum((M @ o.data.vertices[i].co).z for i in p.vertices) / len(p.vertices)
            if zb + 0.25 * H <= z <= (zt if min(width, depth) > 1.65 else zb + 0.65 * H):
                k = round(z, 2); areas[k] = areas.get(k, 0.0) + p.area * sx * sy
    if not areas and piece.parent and not _redirected:
        # No sittable surface at all (an imported DESK flagged as a seat, classroom_crank seat_22): sit on the nearest piece of
        # the same set that has one (the desk's own chair), never in mid air.
        px, py = (max(v.x for v in vs) + min(v.x for v in vs)) / 2, (max(v.y for v in vs) + min(v.y for v in vs)) / 2
        best = None
        for sibling in piece.parent.children:
            if sibling is piece or sibling.name.rsplit('_', 1)[0] != piece.name.rsplit('_', 1)[0]: continue
            sv = _verts(sibling)
            if not sv: continue
            d = math.hypot((max(v.x for v in sv) + min(v.x for v in sv)) / 2 - px, (max(v.y for v in sv) + min(v.y for v in sv)) / 2 - py)
            if d > 2.0 or (best and d >= best[0]): continue
            try: st = seat(sibling, _redirected=True)
            except ValueError: continue
            if st.get('has_surface'): best = (d, st)
        if best: return best[1]
    z = max(areas, key=areas.get) if areas else zb + 0.45 * H
    seat_v = [v for v in vs if abs(v.z - z) < 0.03] or vs
    cx = sum(v.x for v in seat_v) / len(seat_v); cy = sum(v.y for v in seat_v) / len(seat_v)
    hi = [v for v in vs if v.z > zb + 0.6 * H and v.z > z + 0.1]
    bx = sum(v.x for v in hi) / len(hi) - cx if hi else 0.0; by = sum(v.y for v in hi) / len(hi) - cy if hi else 1.0
    if math.hypot(bx, by) < 0.03: bx, by = 0.0, 1.0          # no backrest (stool/bench): face -Y (the camera side)
    axis = piece.matrix_world.to_euler().z; c, s = math.cos(axis), math.sin(axis)
    edge_v = vs if min(width, depth) > 1.65 else seat_v
    xs = [c * v.x + s * v.y for v in edge_v]; ys = [-s * v.x + c * v.y for v in edge_v]
    return {'piece': piece, 'pos': (cx, cy), 'z': z, 'yaw': math.atan2(-bx, by), 'has_surface': bool(areas),
            'surface': (min(xs), max(xs), min(ys), max(ys)), 'axis': axis}


def seat_entry(world, ch, piece, st=None, frame=0):
    """Choose a usable surface edge and checked entry/hop. Update st with the selected anchor and facing.
    Fixed-back chairs keep their facing, can enter sideways, and can be pulled away from a desk by at most 0.8 m."""
    import locomotion as lo, assets
    st = st or seat(piece)
    piece = st.get('piece', piece)
    rect = st['surface']; wide = max(rect[1] - rect[0], rect[3] - rect[2]) > 1.65

    def search(base):
        candidates = [base]
        if not wide:
            candidates += [{**base, 'pos': (base['pos'][0] + math.sin(base['yaw']) * d,
                                           base['pos'][1] - math.cos(base['yaw']) * d)} for d in (.1, .2, .3)]
        if wide:
            candidates = []
            x0, x1, y0, y1 = base['surface']; a = base['axis']; c, s = math.cos(a), math.sin(a)
            # Long edges first; the anchor sits just inside the edge, facing out of the surface.
            edges = [(x1 - x0, (0, -1), ((x0 + x1) / 2, y0 + .18)),
                     (x1 - x0, (0, 1), ((x0 + x1) / 2, y1 - .18)),
                     (y1 - y0, (-1, 0), (x0 + .18, (y0 + y1) / 2)),
                     (y1 - y0, (1, 0), (x1 - .18, (y0 + y1) / 2))]
            for length, (fx, fy), (x, y) in sorted(edges, key=lambda e: -e[0]):
                if length < 2 * S: continue
                for off in (0, -.4, .4):
                    if abs(off) + S > length / 2: continue
                    px, py = x - fy * off, y + fx * off
                    candidates.append({**base, 'pos': (c * px - s * py, s * px + c * py),
                                       'yaw': math.atan2(c * fx - s * fy, -(s * fx + c * fy))})
        for target in candidates:
            if wide:
                # A curved mattress has no single flat top; sit on its upper surface, ignoring separate pillows.
                heights = [v.z for v in _verts(piece)
                           if abs(v.x - target['pos'][0]) <= S and abs(v.y - target['pos'][1]) <= S]
                for obj in piece.children_recursive:
                    if obj.type != 'MESH': continue
                    inv = obj.matrix_world.inverted()
                    for dx, dy in ((x, y) for x in (-S, 0, S) for y in (-S, 0, S)):
                        origin = Vector((target['pos'][0] + dx, target['pos'][1] + dy, 100))
                        hit, point, _, _ = obj.ray_cast(inv @ origin, inv.to_3x3() @ Vector((0, 0, -1)))
                        if hit: heights.append((obj.matrix_world @ point).z)
                if heights: target['z'] = max(heights) + .025   # imported visual shells can sit 1.5 cm above their collision mesh
            sc_ = lo.sit_clearance(world, ch, target, target['pos'], frame, exempt={piece.name}, seated_only=True)
            if SEATDEBUG: print('SEATDEBUG', piece.name, 'target', [round(v / S, 1) for v in target['pos']], 'z', round(target['z'], 2), 'yaw', round(math.degrees(target['yaw'])), 'seated depth', round(sc_.depth_m, 3), sc_.blocker, sc_.part)
            if sc_.depth_m: continue
            (sx, sy), yaw = target['pos'], target['yaw']; fx, fy = math.sin(yaw), -math.cos(yaw)
            entries = [(sx + fx * k * .05, sy + fy * k * .05) for k in
                       range(round(staging.d('seat_approach_max') / .05), round(staging.d('seat_approach_min') / .05) - 1, -1)]
            if not wide:
                entries += [(sx + sign * math.cos(yaw) * d + fx * .15,
                             sy + sign * math.sin(yaw) * d + fy * .15)
                            for d in (.8, 1.0, 1.2, 1.4, 1.6) for sign in (1, -1)]
            for p in entries:
                if world.query(ch, p, yaw, frame).depth_m: continue
                turn = world.sweep(ch, [(p, yaw + math.pi / 2), (p, yaw), (p, yaw - math.pi / 2)], frame)
                if lo.sit_clearance(world, ch, target, p, frame, exempt={piece.name}).depth_m: continue
                ent = {'xy': p, 'back_studs': math.hypot(p[0] - sx, p[1] - sy) / S, 'turn': turn}
                # The footprint walker cannot enter a tight 3D-clear gap: finish from the aisle with checked planted steps.
                def in_footprint(v):
                    return any(x0 - 1.1 * S < v[0] < x1 + 1.1 * S and y0 - 1.1 * S < v[1] < y1 + 1.1 * S
                               for x0, x1, y0, y1, top in assets.obstacles() if top > .2)
                if turn.depth_m == 0 and not in_footprint(p):
                    st.update(target); return ent
                for d in (.4, .8, 1.2):
                    for sign in (1, -1):
                        v = (p[0] + sign * math.cos(yaw) * d, p[1] + sign * math.sin(yaw) * d)
                        if in_footprint(v): continue
                        turn = world.sweep(ch, [(v, yaw + math.pi / 2), (v, yaw), (v, yaw - math.pi / 2)], frame)
                        if turn.depth_m or world.sweep(ch, [(v, yaw), (p, yaw)], frame).depth_m: continue
                        st.update(target)
                        return {**ent, 'via': v, 'turn': turn, 'sidestep_m': d}
        return None

    ent = search(st)
    if ent: return ent
    if not wide:
        original = piece.matrix_world.copy(); yaw = st['yaw']
        registered = next((q for q in assets.PLACED if q['pivot'] is piece), None)
        old_rect = registered['rect'] if registered else None
        try:
            for k in range(1, 9):
                # Facing points toward the desk; pull the chair back along that same axis.
                dx, dy = -math.sin(yaw) * k * .1, math.cos(yaw) * k * .1
                M = original.copy(); M.translation += Vector((dx, dy, 0)); piece.matrix_world = M
                bpy.context.view_layer.update()
                if registered:
                    x0, x1, y0, y1 = old_rect; registered['rect'] = (x0 + dx, x1 + dx, y0 + dy, y1 + dy)
                world.__init__(world.sc, world.cast, world.props)
                ent = search(seat(piece))
                if ent: return {**ent, 'pullout_m': k * .1}
        finally:
            if ent is None:
                piece.matrix_world = original; bpy.context.view_layer.update()
                if registered: registered['rect'] = old_rect
                world.__init__(world.sc, world.cast, world.props)
    raise ValueError(f'{piece.name}: no clear seat edge, entry, turn and sit/stand transition')
