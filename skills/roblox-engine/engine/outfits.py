"""outfits.py - real Roblox classic Shirt / Pants templates on the R6 boxes (assets/outfits, see LIBRARY.md).
  apply(char, shirt=<path|None>, pants=<path|None>)   char = rig.make(...) result or its name; paths = template PNGs
  lib('school2', 'shirt') -> path   tag + number (1 = first of that tag, sorted by id) or a bare asset id
Roblox layout: each part gets the official 585x559 template regions (torso/arms/legs, 6 faces). Layers (Roblox order): base colour,
pants (torso + legs), shirt (torso + arms); transparent template pixels show the layer below, so the cast colour stays visible.
Each part gets ONE baked image (layers composited over its current base colour), so Workbench/EEVEE texture colour and Cycles agree.
Roblox axes -> ours: Front -Y, Back +Y, character Right = local -X, Left = +X, Top +Z, Bottom -Z (rig.py: 'R' = local -X)."""
import json
from pathlib import Path
import numpy as np
import bpy

DIR = Path(__file__).resolve().parent / 'assets' / 'outfits'
W, H = 585, 559
# (x, y, w, h) in template pixels, y from the top. Faces named by Roblox NormalId.
TORSO = {'Right': (165, 74, 64, 128), 'Front': (231, 74, 128, 128), 'Left': (361, 74, 64, 128), 'Back': (427, 74, 128, 128),
         'Top': (231, 8, 128, 64), 'Bottom': (231, 204, 128, 64)}


def _limb(x0, order):   # arms/legs: top/bottom above/below four 64x128 side faces
    d = {f: (x0 + 66 * i, 355, 64, 128) for i, f in enumerate(order)}
    d['Top'] = (217 if x0 == 19 else 308, 289, 64, 64)
    d['Bottom'] = (d['Top'][0], 485, 64, 64)
    return d


LIMB_R = _limb(19, ('Right', 'Front', 'Left', 'Back'))      # character's right arm / leg = left half of the template
LIMB_L = _limb(308, ('Right', 'Front', 'Left', 'Back'))
REGIONS = {'torso': TORSO, 'armR': LIMB_R, 'armL': LIMB_L, 'legR': LIMB_R, 'legL': LIMB_L}
# face normal (our local axes) -> (Roblox face name, viewer-right axis, image-up axis), both seen from OUTSIDE the face
AX = {(0, -1): ('Front', (1, 0, 0), (0, 0, 1)), (0, 1): ('Back', (-1, 0, 0), (0, 0, 1)),
      (-1, 0): ('Right', (0, -1, 0), (0, 0, 1)), (1, 0): ('Left', (0, 1, 0), (0, 0, 1))}
TOPS = {1: ('Top', (1, 0, 0), (0, 1, 0)), -1: ('Bottom', (1, 0, 0), (0, -1, 0))}


def lib(tag, kind='shirt'):
    """'school2' / 'hoodie' / '16586020240' -> template.png path of that kind (KeyError if none)."""
    import re
    ms = []
    for m in sorted(DIR.glob('*_*/meta.json'), key=lambda p: int(p.parent.name.split('_')[0])):
        j = json.loads(m.read_text(encoding='utf-8'))
        if j['kind'] == kind: ms.append((m.parent, j))
    k = str(tag).split(':', 1)[-1].lower()
    for d, j in ms:
        if j['id'] == k: return d / 'template.png'
    mm = re.fullmatch(r'(.*?)(\d*)', k); t, n = mm.group(1), int(mm.group(2) or 1)
    hit = [d for d, j in ms if t in j['tags']]
    if len(hit) < n or n < 1: raise KeyError(f'{kind} {tag} not in assets/outfits')
    return hit[n - 1] / 'template.png'


def _lin(a):   # sRGB 0..1 -> linear
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def _base(part):
    m = part.data.materials[0] if part.data.materials else None
    bsdf = m.node_tree.nodes.get('Principled BSDF') if m and m.node_tree else None
    return tuple(bsdf.inputs['Base Color'].default_value[:3]) if bsdf else (0.8, 0.8, 0.8)


def _template(path):
    """PNG -> float RGBA array (H, W, 4), linear colour, straight alpha, resampled to 585x559 if needed (Blender has no PIL)."""
    im = bpy.data.images.load(str(path), check_existing=False)
    im.colorspace_settings.name = 'Non-Color'; im.alpha_mode = 'CHANNEL_PACKED'   # raw bytes / 255, alpha not premultiplied
    if tuple(im.size) != (W, H): im.scale(W, H)
    a = np.empty(W * H * 4, np.float32); im.pixels.foreach_get(a); bpy.data.images.remove(im)
    a = a.reshape(H, W, 4)[::-1].copy()   # Blender rows start at the bottom -> row 0 = image top
    a[..., :3] = _lin(a[..., :3]); return a


def _bake(base, layers, name):
    """base colour (linear rgb) + [template arrays] -> packed float image (Closest sampling is set on the texture node)."""
    out = np.empty((H, W, 3), np.float32); out[:] = base
    for t in layers:
        a = t[..., 3:4]; out = out * (1 - a) + t[..., :3] * a
    px = np.concatenate([out, np.ones((H, W, 1), np.float32)], -1)[::-1]   # Blender rows start at the bottom
    im = bpy.data.images.new(name, W, H, float_buffer=True)
    im.pixels.foreach_set(px.ravel()); im.pack(); return im


def _uv(part, regions):
    """Per face: corners -> region rect, u along the outside viewer's right, v along image up (so no mirroring or swapping)."""
    me = part.data
    uvl = me.uv_layers.active or me.uv_layers.new(name='UVMap'); uvl.active_render = True   # overwrite the cube's own UVs
    vs = np.array([v.co[:] for v in me.vertices]); lo, hi = vs.min(0), vs.max(0)
    for p in me.polygons:
        n = p.normal
        if abs(n.z) > 0.5: face, r, u = TOPS[1 if n.z > 0 else -1]
        else: face, r, u = AX[(round(n.x), round(n.y))]
        x0, y0, w, h = regions[face]; r, u = np.array(r), np.array(u)
        for li in p.loop_indices:
            c = np.array(me.vertices[me.loops[li].vertex_index].co[:])
            e, f = _ext(lo, hi, r), _ext(lo, hi, u)
            fu, fv = (c @ r - e[0]) / (e[1] - e[0]), (c @ u - f[0]) / (f[1] - f[0])
            uvl.data[li].uv = ((x0 + fu * w) / W, 1 - (y0 + (1 - fv) * h) / H)


def _ext(lo, hi, axis):   # extent of the box along a unit axis (min, max of c . axis)
    a, b = lo @ axis, hi @ axis; return min(a, b), max(a, b)


def _skin(part, img, name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes['Principled BSDF']
    old = part.data.materials[0].node_tree.nodes.get('Principled BSDF') if part.data.materials and part.data.materials[0].node_tree else None
    if old:   # keep the cast material's look (roughness, specular)
        for k in ('Roughness', 'Metallic'):
            if k in old.inputs and k in b.inputs: b.inputs[k].default_value = old.inputs[k].default_value
        for k in ('Specular IOR Level', 'Specular'):
            if k in old.inputs and k in b.inputs: b.inputs[k].default_value = old.inputs[k].default_value
    tx = nt.nodes.new('ShaderNodeTexImage'); tx.interpolation = 'Closest'; tx.image = img; nt.nodes.active = tx
    nt.links.new(tx.outputs['Color'], b.inputs['Base Color'])
    m.diffuse_color = (*_base(part), 1)
    part.data.materials.clear(); part.data.materials.append(m)


def apply(char, shirt=None, pants=None):
    """Wear template PNGs on a rig.make() character (object or name). Returns {part key: object}. Safe to call once per character."""
    if isinstance(char, str):
        import rig; char = rig.CAST[char]
    if shirt is None and pants is None: return {}
    sh = _template(shirt) if shirt else None; pa = _template(pants) if pants else None
    nm = char.root.name
    parts = {'torso': (char.torso, [pa, sh]), 'armR': (char.arms[0], [sh]), 'armL': (char.arms[1], [sh]),
             'legR': (char.legs[0], [pa]), 'legL': (char.legs[1], [pa])}
    cache, done = {}, {}
    for key, (o, layers) in parts.items():
        layers = [t for t in layers if t is not None]
        if not layers: continue
        base = _base(o); ck = (key[:3], base)   # arms / legs share one image per cast colour
        if ck not in cache: cache[ck] = _bake(base, layers, f'{nm} {key[:3]} outfit')
        _uv(o, REGIONS[key]); _skin(o, cache[ck], f'{nm} {key} outfit'); done[key] = o
    return done
