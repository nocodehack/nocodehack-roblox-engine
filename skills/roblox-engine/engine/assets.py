"""assets.py - CC0 Kenney model library (assets/kenney, catalog.json) placed at Roblox R6 scale.
Each kit has one scale factor (kit units -> world metres) fitted so furniture/cars/buildings match a 5-stud (2.5 m) R6 character.
place(name, at_studs, rot_deg) imports the GLB once (hidden library collection) and adds shared-mesh copies under a pivot empty.
Every placed piece is registered in PLACED: footprint rect + top height -> obstacles for walking/grabs and supports for `on:`."""
import json, math
from pathlib import Path
import bpy
from mathutils import Vector, Matrix

S = 0.5
ROOT = Path(__file__).resolve().parent / 'assets' / 'kenney'
KIT_SCALE = {'furniture-kit': 2.85, 'building-kit': 1.9, 'car-kit': 2.5, 'city-kit-suburban': 10.0, 'city-kit-commercial': 10.0,
             'city-kit-roads': 10.0, 'nature-kit': 5.0, 'retro-urban-kit': 4.2, 'mini-shop': 2.4, 'food-kit': 3.0}   # food x3: hand props read bigger in Roblox
_CAT = None
_LIB = {}          # rel_path -> (collection, [objects])
PLACED = []        # dicts: name, pivot, rect (xmin, xmax, ymin, ymax) m, top m, solid bool


def catalog():
    global _CAT
    if _CAT is None:
        _CAT = json.loads((ROOT / 'catalog.json').read_text(encoding='utf-8'))
    return _CAT


def find(name):
    """'kit/file' or bare stem ('bedDouble', 'tree_blocks'). Exact stem match first, then prefix."""
    kit, _, stem = name.rpartition('/')
    c = [e for e in catalog() if (not kit or e['kit'] == kit)]
    for test in (lambda s: s == stem, lambda s: s.startswith(stem), lambda s: stem in s):
        hit = [e for e in c if test(e['file'][:-4])]
        if hit: return min(hit, key=lambda e: len(e['file']))
    raise KeyError(f'asset {name} not in assets/kenney/catalog.json')


def names(kit=None, contains=''):
    return sorted(e['kit'] + '/' + e['file'][:-4] for e in catalog() if (kit is None or e['kit'] == kit) and contains in e['file'])


def _load(e):
    key = e['rel_path']
    if key in _LIB: return _LIB[key]
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(ROOT / key))
    objs = [o for o in bpy.data.objects if o not in before]
    col = bpy.data.collections.new('LIB ' + e['file'])
    for o in objs:
        for c in list(o.users_collection): c.objects.unlink(o)
        col.objects.link(o)
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(b) for o in objs if o.type == 'MESH' for b in o.bound_box]
    # Kenney origins vary (corner, top, base): normalise every model so its pivot = BASE CENTRE
    off = Vector(((min(p.x for p in pts) + max(p.x for p in pts)) / 2, (min(p.y for p in pts) + max(p.y for p in pts)) / 2,
                  min(p.z for p in pts))) if pts else Vector()
    _LIB[key] = (col, objs, off)
    return _LIB[key]


def place(name, at=(0, 0), rot=0.0, z=0.0, scale=1.0, label=None, solid=True, parent=None, register=True):
    """at = (x, y) studs, z studs, rot degrees about Z. Returns the pivot empty (origin = model origin, usually base centre)."""
    e = find(name); col, objs, off = _load(e)
    k = KIT_SCALE.get(e['kit'], 1.0) * scale
    piv = bpy.data.objects.new(label or e['file'][:-4], None); bpy.context.collection.objects.link(piv)
    piv.location = (at[0] * S, at[1] * S, z * S); piv.rotation_euler = (0, 0, math.radians(rot)); piv.scale = (k, k, k)
    if parent is not None: piv.parent = parent
    copies = {}
    for o in objs:
        c = o.copy(); copies[o] = c; bpy.context.collection.objects.link(c)
    for o, c in copies.items():
        if o.parent in copies: c.parent = copies[o.parent]; c.matrix_parent_inverse = o.matrix_parent_inverse.copy()
        else: c.parent = piv; c.matrix_parent_inverse = Matrix.Translation(-off)
    bpy.context.view_layer.update()
    pts = [c.matrix_world @ Vector(b) for c in copies.values() if c.type == 'MESH' for b in c.bound_box]
    if pts and register:
        rect = (min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts))
        PLACED.append({'name': piv.name, 'pivot': piv, 'rect': rect, 'top': max(p.z for p in pts),
                       'solid': solid and max(p.z for p in pts) - min(p.z for p in pts) > 0.12})
    return piv


def reset():
    _LIB.clear(); PLACED.clear()


def obstacles():
    """Footprint rects (with top z) of every solid placed piece, same format as sets supports: (x0, x1, y0, y1, top)."""
    return [(*p['rect'], p['top']) for p in PLACED if p['solid']]


def support(name):
    """(xmin, xmax, ymin, ymax, top) of the main HORIZONTAL SURFACE of the placed piece `name` (for props `on`): the height whose
    upward-facing faces have the largest total area (a counter top, not the cash register screen on it), and those faces' rect."""
    for p in PLACED:
        if p['name'] != name: continue
        areas, rects = {}, {}
        for o in p['pivot'].children_recursive:
            if o.type != 'MESH': continue
            M = o.matrix_world; R = M.to_3x3().normalized()
            for poly in o.data.polygons:
                nz = (R @ poly.normal).z
                if nz < 0.95: continue
                pts = [M @ o.data.vertices[i].co for i in poly.vertices]
                zk = round(sum(q.z for q in pts) / len(pts), 2); a = poly.area * M.to_scale().x * M.to_scale().y
                areas[zk] = areas.get(zk, 0) + a
                r = rects.get(zk, [9e9, -9e9, 9e9, -9e9])
                rects[zk] = [min(r[0], *(q.x for q in pts)), max(r[1], *(q.x for q in pts)), min(r[2], *(q.y for q in pts)), max(r[3], *(q.y for q in pts))]
        cand = {z: a for z, a in areas.items() if z > 0.15}          # ignore the floor-level base
        if not cand: return (*p['rect'], p['top'])
        z = max(cand, key=cand.get)
        return (*rects[z], z)
    raise KeyError(f'no placed piece named {name}')
