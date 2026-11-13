"""space.py - ONE body-in-space model for every movement (motion foundation, Task 1-2).
Obstacles = the scene's real meshes (Kenney pieces, room walls, procedural classroom desks...) minus characters, props,
floor-like surfaces and non-solid decor. Body parts (torso, head, legs) are boxes from the rig's own meshes.
Body-vs-furniture uses EXACT triangle overlap (BVH) against part boxes shrunk by the tolerance, so "legs under a desk top"
is clear while "legs through the desk" is a hit (box/footprint tests cannot tell them apart). Body-vs-body uses OBB depth.
Arms are checked by interact.penetration_report (unchanged). Units: metres."""
import math
import bpy
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

FLOORLIKE = ('ground', 'floor', 'road', 'sidewalk', 'path', 'rug', 'lane', 'ceiling', 'grass', 'flower', 'mark', 'skirting', 'carpet')
VFX = ('VFX', 'Impact', 'Beam', 'Aura', 'Dust', 'Speed', 'Sparkle', 'Exclamation', 'Charge')
BOX_FACES = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
TOL = 0.02   # m: penetration allowed before a hit (creator rule: 2 cm, every frame)
# THE ARM RULE's allowances (m), ONE place: the final gate (build.arm_rows) and every planner read these. Depth = the other
# mesh's vertices inside the rigid arm box (interact._pts_depth). Planners may be stricter, never looser.
ARM_TOL = 0.02          # arm vs anything else
OWN_TORSO_MAX = 0.12    # an arm may cut its OWN torso this deep (rigid R6 arm corner on a forward reach)
OWN_HAIR_MAX = 0.10     # own hair accessory brush
FACE_HEAD_MAX = 0.05    # face-touch pose frames: hand on own head
FACE_HAIR_MAX = 0.10    # face-touch pose frames: hand in own hair
_BOUNDS = {}


def fcurves_of(obj):
    """F-curves of an object's action in Blender 5 (slotted actions)."""
    ad = obj.animation_data
    if not ad or not ad.action: return []
    if hasattr(ad.action, 'fcurves'): return list(ad.action.fcurves)
    from bpy_extras import anim_utils
    cb = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
    return list(cb.fcurves) if cb else []


def local_bounds(obj):
    """Local AABB (lo, hi) of a mesh object's vertices (cached per mesh datablock identity + vertex count: a name-keyed
    cache survived scene resets with a differently sized mesh of the same name, Codex review #3)."""
    vs = obj.data.vertices   # memory addresses are reused after a reset: key on the geometry too
    k = (obj.data.as_pointer(), len(vs), tuple(vs[0].co) if len(vs) else (), tuple(vs[len(vs) - 1].co) if len(vs) else ())
    if k not in _BOUNDS:
        co = np.array([v.co[:] for v in obj.data.vertices]); _BOUNDS[k] = (co.min(0), co.max(0))
    return _BOUNDS[k]


def part_meshes(ch):
    """Body parts checked against the world: (label, mesh object). Arms are excluded (penetration_report owns them)."""
    out = [('torso', ch.torso), ('head', ch.head_mesh)]
    out += [(f'leg{k}', o) for k, o in enumerate(ch.legs)]
    return out


def _corners(M, lo, hi, shrink=0.0):
    lo = np.asarray(lo) + shrink; hi = np.asarray(hi) - shrink
    hi = np.maximum(hi, lo)
    loc = [(x, y, z) for z in (lo[2], hi[2]) for (x, y) in ((lo[0], lo[1]), (hi[0], lo[1]), (hi[0], hi[1]), (lo[0], hi[1]))]
    return [M @ Vector(c) for c in loc]


def _part_box(obj, shrink, M=None):
    """World corners of the part's box (at world matrix M, default its current one), shrunk by `shrink` metres (scale-aware)."""
    M = obj.matrix_world if M is None else M; lo, hi = local_bounds(obj)
    s = np.linalg.norm(np.asarray(M.to_3x3()), axis=0); sh = shrink / np.maximum(s, 1e-9)
    lo_ = np.asarray(lo) + sh; hi_ = np.maximum(np.asarray(hi) - sh, lo_)
    return _corners(M, lo_, hi_)


def _inside(bvh, p, max_d=50.0):
    """Is point p inside the closed mesh of `bvh`? The nearest surface normal points away from an inside point; a second
    vote by ray parity along +Z keeps open meshes (a desk top slab) from claiming the space below them."""
    hit = bvh.find_nearest(p, max_d)
    if hit[0] is None or (p - hit[0]).dot(hit[1]) >= 0: return False
    n, q = 0, p.copy()
    for _ in range(64):
        loc, nrm, _, _ = bvh.ray_cast(q, Vector((0, 0, 1)), max_d)
        if loc is None: break
        n += 1; q = loc + Vector((0, 0, 1e-4))
    return n % 2 == 1


def _obb(obj, M=None):
    import interact
    lo, hi = local_bounds(obj); return interact._obb(np.array(obj.matrix_world if M is None else M), lo, hi)


class Clearance:
    def __init__(self, depth_m=0.0, blocker=None, part=None):
        self.depth_m, self.blocker, self.part = depth_m, blocker, part

    def __repr__(self):
        return f'Clearance({self.depth_m:.3f} m, {self.blocker}, {self.part})'


class World:
    """Obstacles of the current scene. cast: dict name -> character namespace; props: dict/list of prop roots."""

    def __init__(self, sc, cast, props=()):
        self.sc = sc; self.cast = cast; self.props = props
        skip = set()
        for ch in (cast.values() if isinstance(cast, dict) else cast):
            skip |= {o.name for o in ch.root.children_recursive} | {ch.root.name}
        for p in (props.values() if isinstance(props, dict) else props):
            skip |= {o.name for o in p.children_recursive} | {p.name}
        nonsolid, owner = set(), {}
        try:
            import assets
            for q in assets.PLACED:
                kids = [o.name for o in q['pivot'].children_recursive]
                for n in kids: owner[n] = q['name']
                if not q['solid']: nonsolid |= set(kids)
        except Exception:
            pass
        self.obs = []   # (piece name, BVHTree world, aabb lo, aabb hi, names of the object + its parents)
        sc.frame_set(sc.frame_current); bpy.context.view_layer.update()
        for o in sc.objects:
            if o.type != 'MESH' or o.name in skip or o.name in nonsolid or o.hide_render: continue
            if not o.data.polygons: continue
            if o.name.startswith(VFX): continue
            M = o.matrix_world; vs = [M @ v.co for v in o.data.vertices]
            arr = np.array([v[:] for v in vs])
            # walkable surfaces: a floor-ish name AND flat (a name alone dropped solid floor LAMPS, Codex review #4)
            if arr[:, 2].max() - arr[:, 2].min() < 0.15 and any(w in o.name.lower() for w in FLOORLIKE): continue
            # a LOW STEP on the floor (curb 0.18 m, mat, rug edge): stepped over/onto like Roblox, not walked into (a 2 cm curb
            # graze rejected whole walks, R158 blind2_street). Anything taller (coffee tables, benches, bases + poles) stays solid.
            if arr[:, 2].max() < 0.2 and arr[:, 2].min() > -0.05: continue
            anc, q = {o.name}, o.parent
            while q is not None: anc.add(q.name); q = q.parent
            self.obs.append((owner.get(o.name, o.name), BVHTree.FromPolygons(vs, [p.vertices[:] for p in o.data.polygons]),
                             arr.min(0), arr.max(0), anc))
        self._lo = np.array([o[2] for o in self.obs]).reshape(-1, 3); self._hi = np.array([o[3] for o in self.obs]).reshape(-1, 3)
        self._rel = {}   # (character, frame) -> part matrices relative to the root (a rigid root move needs no depsgraph)
        self._head_bvh = {}   # rigid head/hair geometry in local space; only the eight limb corners need transforming

    def unlisted_footprints(self, listed, bounds=None, cell=0.125, top=2.5):
        """Footprint rects (x0, x1, y0, y1, top z) of the collidable meshes NO rect in `listed` covers: the gate hits every real
        mesh, the route planner only knew the registered pieces (an imported coffee table's top was 'visual': routes walked
        between its 4 legs and every walk was rejected, R228). Rays straight down on a `cell` grid over each free-standing mesh
        (walls and other meshes touching the room bounds stay the bounds' job). Cached per world."""
        key = (len(listed), bounds and tuple(bounds))
        if getattr(self, '_unlisted', (None,))[0] == key: return self._unlisted[1]
        out = []
        for name, bvh, lo, hi, _ in self.obs:
            if hi[2] < 0.2 or lo[2] > top: continue
            if bounds and not (lo[0] > bounds[0] + 0.3 and hi[0] < bounds[1] - 0.3 and lo[1] > bounds[2] + 0.3 and hi[1] < bounds[3] - 0.3): continue
            if any(o[0] - 0.1 <= lo[0] and hi[0] <= o[1] + 0.1 and o[2] - 0.1 <= lo[1] and hi[1] <= o[3] + 0.1 for o in listed): continue
            prev = {}   # (x0, x1) -> rect being grown row by row
            y = lo[1] + cell / 2
            while y < hi[1] + cell / 2:
                runs = []; x = lo[0] + cell / 2
                while x < hi[0] + cell / 2:
                    h = bvh.ray_cast(Vector((x, y, top)), Vector((0, 0, -1)))[0]
                    if h is not None and h.z > 0.2 and not any(o[0] - 0.1 < x < o[1] + 0.1 and o[2] - 0.1 < y < o[3] + 0.1 for o in listed):
                        if runs and abs(runs[-1][1] - (x - cell / 2)) < 1e-6: runs[-1][1] = x + cell / 2; runs[-1][2] = max(runs[-1][2], h.z)
                        else: runs.append([x - cell / 2, x + cell / 2, h.z])
                    x += cell
                cur = {}
                for x0, x1, z in runs:
                    k = (round(x0, 4), round(x1, 4)); r = prev.get(k)
                    if r is None: r = [x0, x1, y - cell / 2, y + cell / 2, z]; out.append(r)
                    else: r[3] = y + cell / 2; r[4] = max(r[4], z)
                    cur[k] = r
                prev = cur; y += cell
        self._unlisted = (key, [tuple(float(v) for v in r) for r in out])
        return self._unlisted[1]

    def body_hits(self, ch, frame, tol=TOL, exempt=()):
        """[(frame, part, piece, depth_bucket_m)] for torso/head/legs vs obstacles at `frame` (penetration > tol)."""
        self.sc.frame_set(frame); bpy.context.view_layer.update()
        return [(frame, l, p, d) for _, l, p, d in self._hits_now(ch, tol, exempt)]

    def _depth(self, obj, bvh, tol, M=None, transform=None):
        """Penetration bucket: the largest shrink (2/5/10/20/40 cm) that still overlaps."""
        d = tol
        for s in (0.05, 0.10, 0.20, 0.40):
            corners = _part_box(obj, s, M)
            if transform is not None: corners = [transform @ p for p in corners]
            if BVHTree.FromPolygons(corners, BOX_FACES).overlap(bvh): d = s
            else: break
        return d

    def actor_depth(self, a, b, frame):
        """(depth_m, part_a, part_b): worst OBB overlap between two characters' torso/head/legs at `frame`."""
        self.sc.frame_set(frame); bpy.context.view_layer.update()
        return self._actor_now(a, b)

    def scene_hits(self, frames, tol=TOL, exempt_fn=lambda who, f: ()):
        """Every frame, every character: body vs obstacles + body vs body. -> list of (frame, who, blocker, depth_m)."""
        chs = list(self.cast.values()) if isinstance(self.cast, dict) else list(self.cast)
        out = []
        for f in frames:
            for i, ch in enumerate(chs):
                for fr, part, piece, d in self.body_hits(ch, f, tol, exempt_fn(ch.name, f)):
                    out.append((fr, f'{ch.name} {part}', piece, d))
                for other in chs[i + 1:]:
                    d, pa, pb = self.actor_depth(ch, other, f)
                    if d > tol: out.append((f, f'{ch.name} {pa}', f'{other.name} {pb}', round(d, 3)))
        return out

    def invalidate(self):
        """Forget cached evaluated poses (call after keying animation; the beat loop calls it every beat, Codex review #2)."""
        self._rel.clear()

    def motion_hit(self, ch, frames, exempt_fn=lambda f: ()):
        """First conflict on the evaluated trajectory, including other actors at the SAME frame."""
        for f in frames:
            hits = self.body_hits(ch, f, exempt=exempt_fn(f))
            if hits: return hits[0]
            for other in (self.cast.values() if isinstance(self.cast, dict) else self.cast):
                if other is ch: continue
                d, part, opart = self._actor_now(ch, other)
                if d > TOL: return (f, part, f'{other.name} {opart}', d)
        return None

    def query(self, ch, xy, yaw, frame=0, tol=TOL, exempt=(), others=True):
        """Would `ch` (its pose at `frame`) be clear with its root at xy (m) and heading yaw (rad)? Body vs scene meshes, and
        vs the other characters as they are at `frame`. Nothing is keyed; the scene is evaluated once per (character, frame)."""
        key = (ch.name, frame)
        if key not in self._rel:
            self.sc.frame_set(frame); bpy.context.view_layer.update()
            R = ch.root.matrix_world.copy(); Ri = R.inverted()
            self._rel[key] = (R, {l: Ri @ o.matrix_world for l, o in part_meshes(ch)})
        R, rel = self._rel[key]
        loc, rot, sca = R.decompose(); e = rot.to_euler(); e.z = yaw; loc.x, loc.y = xy
        Rn = Matrix.LocRotScale(loc, e, sca); mats = {l: Rn @ m for l, m in rel.items()}
        best = Clearance()
        for _, part, piece, d in self._hits_now(ch, tol, exempt, mats):
            if d > best.depth_m: best = Clearance(d, piece, part)
        if others:
            for o in (self.cast.values() if isinstance(self.cast, dict) else self.cast):
                if o is ch: continue
                if (o.name, frame) not in self._rel:
                    self.sc.frame_set(frame); bpy.context.view_layer.update()
                    Ro = o.root.matrix_world.copy(); self._rel[(o.name, frame)] = (Ro, {l: Ro.inverted() @ p.matrix_world for l, p in part_meshes(o)})
                Ro, relo = self._rel[(o.name, frame)]
                d, pa, pb = self._pair(ch, mats, o, {l: Ro @ m for l, m in relo.items()})
                if d > tol and d > best.depth_m: best = Clearance(round(d, 3), o.name, pa)
        return best

    def _pair(self, a, mats_a, b, mats_b):
        import interact
        best = (0.0, None, None)
        boxes_b = [(lb, _obb(ob, mats_b[lb])) for lb, ob in part_meshes(b)]
        for la, oa in part_meshes(a):
            A = _obb(oa, mats_a[la])
            for lb, B in boxes_b:
                d = interact.obb_depth(A, B)
                if d > best[0]: best = (d, la, lb)
        return best

    def sweep(self, ch, poses, frame=0, tol=TOL, exempt=(), step=0.10, first=True):
        """Worst clearance over a list of (xy, yaw) root poses; consecutive yaws are subdivided so no body corner moves more
        than `step` m between samples (a turn in place sweeps the 2-stud-wide body). first=True returns at the first blocked
        sample (planners only need blocked/clear; the final gate re-checks every frame exactly)."""
        dense = [poses[0]]
        for (p0, y0), (p1, y1) in zip(poses, poses[1:]):
            dy = (y1 - y0 + math.pi) % (2 * math.pi) - math.pi
            k = max(1, int(abs(dy) * 1.12 / step), int(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / step))   # 1.12 m = R6 corner radius
            dense += [((p0[0] + (p1[0] - p0[0]) * i / k, p0[1] + (p1[1] - p0[1]) * i / k), y0 + dy * i / k) for i in range(1, k + 1)]
        worst = Clearance()
        for xy, yaw in dense:
            c = self.query(ch, xy, yaw, frame, tol, exempt)
            if c.depth_m > worst.depth_m:
                worst = c
                if first: return worst
        return worst


    def nearest_clear(self, ch, xy, yaw, frame=0, turn_from=None, step=0.125, max_r=4.0, exempt=()):
        """Closest spot to xy (spiral, metres) where the body is clear at `yaw` AND, if turn_from is given, through the whole
        turn from turn_from to yaw. Returns ((x, y), distance_m); raises ValueError if none within max_r."""
        def ok(p):
            if self.query(ch, p, yaw, frame, exempt=exempt).depth_m > 0: return False
            if turn_from is None: return True
            return self.sweep(ch, [(p, turn_from), (p, yaw)], frame, exempt=exempt).depth_m == 0
        if ok(xy): return tuple(xy), 0.0
        r = step
        while r <= max_r:
            for a in range(0, 360, 15):
                p = (xy[0] + r * math.cos(math.radians(a)), xy[1] + r * math.sin(math.radians(a)))
                if ok(p): return p, r
            r += step
        raise ValueError(f'no clear spot within {max_r} m of {xy}')


    def _hits_now(self, ch, tol, exempt, mats=None):
        """Body parts vs obstacles on the CURRENT pose, or at explicit part world matrices `mats` {label: Matrix}."""
        out = []; ex = set(exempt)
        for label, obj in part_meshes(ch):
            M = mats[label] if mats else None
            cs = _part_box(obj, tol, M); a = np.array([c[:] for c in cs]); lo, hi = a.min(0), a.max(0); tree = None
            near = np.nonzero(np.all(self._hi >= lo, axis=1) & np.all(self._lo <= hi, axis=1))[0] if len(self.obs) else []
            for i in near:
                piece, bvh, _, _, anc = self.obs[i]
                if piece in ex or anc & ex: continue
                tree = tree or BVHTree.FromPolygons(cs, BOX_FACES)
                if tree.overlap(bvh): out.append((None, label, piece, self._depth(obj, bvh, tol, M)))
                elif _inside(bvh, Vector(a.mean(0))):   # wholly inside a closed obstacle: no triangles cross (Codex review #1)
                    out.append((None, label, piece, 0.40))
        return out

    def limb_hits(self, obj, M, frame, owner=None, tol=TOL, exempt=(), own_torso_max=OWN_TORSO_MAX, own_hair_max=OWN_HAIR_MAX):
        """A limb box `obj` at a HYPOTHETICAL world matrix M (e.g. an arm at candidate angles): worst Clearance vs the scene
        meshes and vs every character's torso/head/legs as they are at `frame`; for its OWNER the head is strict and the torso
        is allowed up to own_torso_max (the agreed R6 rule). Nothing is keyed."""
        self.sc.frame_set(frame); bpy.context.view_layer.update()
        cs = _part_box(obj, tol, M); a = np.array([c[:] for c in cs]); lo, hi = a.min(0), a.max(0); tree = None; ex = set(exempt)
        best = Clearance()
        near = np.nonzero(np.all(self._hi >= lo, axis=1) & np.all(self._lo <= hi, axis=1))[0] if len(self.obs) else []
        for i in near:
            piece, bvh, _, _, anc = self.obs[i]
            if piece in ex or anc & ex: continue
            tree = tree or BVHTree.FromPolygons(cs, BOX_FACES)
            if tree.overlap(bvh):
                d = self._depth(obj, bvh, tol, M)
                if d > best.depth_m: best = Clearance(d, piece, obj.name)
        import interact
        A = _obb(obj, M)
        for o in (self.cast.values() if isinstance(self.cast, dict) else self.cast):
            hp_ = getattr(o, 'hair_pivot', None)
            for h in [o.head_mesh] + ([x for x in hp_.children_recursive if x.type == 'MESH'] if hp_ else []):
                # head + hair are strict and EXACT (triangles): boxes around a rounded head / spiky locks overestimate (4.5 cm vs 0)
                if not h.data.vertices: continue
                Mh = h.matrix_world; ha = np.array([p[:] for p in _corners(Mh, *local_bounds(h))])
                if np.any(hi < ha.min(0)) or np.any(lo > ha.max(0)): continue
                key = h.data.as_pointer()
                if key not in self._head_bvh:
                    self._head_bvh[key] = BVHTree.FromPolygons([v.co[:] for v in h.data.vertices], [p.vertices[:] for p in h.data.polygons])
                hb = self._head_bvh[key]; inv = Mh.inverted()
                if o is owner and h is not o.head_mesh:
                    # OWN hair: the GATE's measure exactly (hair vertices inside the arm box, minus the allowance). The triangle
                    # bucket read every true depth in [10, 20) cm as 0: lunch 11.8, backyard 14.1, park 18.2 cm passed here
                    d = interact._pts_depth(interact.world_pts(h), np.array(M), *local_bounds(obj)) - own_hair_max
                    if d > best.depth_m: best = Clearance(d, f'{o.name} hair', obj.name)
                    continue
                if BVHTree.FromPolygons([inv @ p for p in cs], BOX_FACES).overlap(hb):
                    d = self._depth(obj, hb, tol, M, transform=inv)
                    if d > best.depth_m: best = Clearance(d, f'{o.name} {"head" if h is o.head_mesh else "hair"}', obj.name)
            for lb, ob in part_meshes(o):   # torso/legs ARE boxes: OBB is exact for them; the rounded head was checked above
                if lb == 'head' or (o is owner and lb.startswith('leg')): continue
                if o is owner and lb == 'torso':   # include the gate's torso-points-in-arm measure (containment is directional)
                    lo_t, hi_t = local_bounds(ob)
                    d = max(interact._pts_depth(np.array([(M @ v.co)[:] for v in obj.data.vertices]), ob.matrix_world, lo_t, hi_t),
                            interact._pts_depth(interact.world_pts(ob), M, *local_bounds(obj))) - own_torso_max
                else:
                    d = interact.obb_depth(A, _obb(ob))
                limit = 0.0 if o is owner and lb == 'torso' else tol
                if d > limit and d > best.depth_m: best = Clearance(d, f'{o.name} {lb}', obj.name)
        return best

    def _actor_now(self, a, b):
        """Worst OBB overlap of two characters on the current pose."""
        return self._pair(a, {l: o.matrix_world for l, o in part_meshes(a)}, b, {l: o.matrix_world for l, o in part_meshes(b)})
