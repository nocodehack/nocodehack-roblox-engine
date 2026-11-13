"""rig.py - R6 character for the Roblox short engine (studs, S = 0.5 m; forward = local -Y).
Sides use the CHARACTER's own left/right: 'R' = local -X (locomotion side -1, index 0), 'L' = local +X (side +1, index 1).
Hierarchy: root (feet centre on the floor) -> upper (pivot at hips, z = 2 studs: torso, shoulders, head) + hips -> legs.
Parts are the exact R6 sizes; the head is the authentic Roblox head mesh from assets/r6_parts.blend (Aeresei R6 rig v2.22)."""
import bpy, math
from pathlib import Path
from types import SimpleNamespace
from mathutils import Matrix
import claude_still as cs
import locomotion as lo
import faces

S = cs.S
ASSETS = Path(__file__).resolve().parent / 'assets'
SIDE = {'R': -1, 'L': 1}
IDX = {'R': 0, 'L': 1}
CAST = {}   # name -> SimpleNamespace


def _keep(o, p):
    bpy.context.view_layer.update()
    w = o.matrix_world.copy(); o.parent = p; o.matrix_world = w


def _head_mesh():
    me = bpy.data.meshes.get('R6 Head')
    if me is None:
        with bpy.data.libraries.load(str(ASSETS / 'r6_parts.blend')) as (src, dst):
            dst.meshes = ['R6 Head']
        me = dst.meshes[0]
        me.transform(Matrix.Scale(S, 4))      # file is in studs
        for p in me.polygons: p.use_smooth = True
    return me


def lin(hex_col):
    h = hex_col.lstrip('#'); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c)


def material(name, hex_or_rgb, rough=0.38):
    rgb = lin(hex_or_rgb) if isinstance(hex_or_rgb, str) else hex_or_rgb
    return bpy.data.materials.get(name) or cs.mat(name, rgb, rough, 0.5)   # Roblox plastic: low roughness, real specular


HAIR_FLOOR = '#24242B'   # R-look2: darkest hair albedo (charcoal, hint of blue); #2E2E38 read grey under day fill, #141414 + low-key = flat black


def hair_floor(hex_col):
    """Lift near-black hair toward HAIR_FLOOR (smoothly, by linear luminance) so lights still describe its form."""
    y = lambda c: .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
    c, f = lin(hex_col), lin(HAIR_FLOOR); t = y(c) / y(f)
    if t >= 1: return hex_col
    srgb = lambda v: v * 12.92 if v <= .0031308 else 1.055 * v ** (1 / 2.4) - .055
    return '#%02X%02X%02X' % tuple(round(255 * srgb(a * t + b * (1 - t))) for a, b in zip(c, f))


def hair_shine(m, hex_col):
    """DARK hair keeps a soft highlight in every look (look._lowkey skips materials tagged 'hair'); spec > .2 turned it grey/silver
    under the day sky fill. Other hair colours are left exactly as before."""
    c = lin(hex_col); bs = m.node_tree.nodes.get('Principled BSDF')
    if .2126 * c[0] + .7152 * c[1] + .0722 * c[2] > .05: return m
    m['hair'] = True
    if bs: bs.inputs['Roughness'].default_value = .45; bs.inputs['Specular IOR Level'].default_value = .2
    return m


def make(name, at=(0, 0), yaw=0, shirt='#C4281C', pants='#0D69AC', skin='#F5CD30', hair='#5A3A22', face='smile', hair_style='spiky', outfit=None):
    """at = (x, y) in studs on the floor, yaw in degrees (0 = facing -Y, toward the default camera)."""
    hair = hair_floor(hair)
    sk, sh, pa, ha = (material(f'{name} {k}', v) for k, v in (('skin', skin), ('shirt', shirt), ('pants', pants), ('hair', hair)))
    hair_shine(ha, hair)
    ch = lo.make_r6_standing(name, cs.st(at[0], at[1], 0), yaw, shirt=sh, pants=pa, skin=sk, hairm=ha)
    # authentic head mesh replaces the cylinder
    old = bpy.data.objects[name + ' head mesh']
    if (ASSETS / 'r6_parts.blend').exists():   # public install without the Roblox head file keeps the built-in cylinder head
        old.data = _head_mesh().copy(); old.data.materials.clear(); old.data.materials.append(sk)
        old.modifiers.clear()
    else:   # fit the built-in head just inside the face decal (radius faces.HEAD_R), or the decal hides inside it
        bpy.context.view_layer.update(); k = 2 * 0.59 * S / max(old.dimensions.x, old.dimensions.y)
        old.scale = (old.scale.x * k, old.scale.y * k, old.scale.z)
    # face library replaces the single decal
    bpy.data.objects.remove(bpy.data.objects[name + ' face'], do_unlink=True)
    kinds = (face,) + tuple(k for k in faces.KINDS if k != face)
    faces.attach(name, ch.head, kinds)
    if hair_style == 'none':
        for o in list(ch.head.children):
            if o.name.startswith('hair'): bpy.data.objects.remove(o, do_unlink=True)
    # upper-body pivot at the hips carries torso, shoulders and head (lean, twist, breathe)
    up = bpy.data.objects.new(name + ' upper', None); bpy.context.collection.objects.link(up)
    up.parent = ch.root; up.location = cs.st(0, 0, 2.0); up.rotation_mode = 'XYZ'
    for o in [ch.torso, ch.head] + ch.shoulders:
        _keep(o, up)
    ch.head.rotation_mode = 'XYZ'
    hp = bpy.data.objects.new(name + ' hair pivot', None); bpy.context.collection.objects.link(hp)
    hp.parent = ch.head; hp.location = cs.st(0, 0, 0.6)
    for o in [o for o in ch.head.children if o.name.startswith('hair')]:
        _keep(o, hp)
    if hair_style.startswith('lib:'):
        for o in list(hp.children_recursive): bpy.data.objects.remove(o, do_unlink=True)
        for i_, hs_ in enumerate(hair_style.split('+')):   # 'lib:a+lib:b' = a front piece plus a back piece
            lib_hair(hp, hair, hs_ if hs_.startswith('lib:') else 'lib:' + hs_, f'{name} hair' + (str(i_) if i_ else ''), ch.torso)
    elif hair_style not in ('spiky', 'none'):
        style_hair(hp, ha, hair_style)
    ch.upper, ch.hair_pivot, ch.name, ch.home = up, hp, name, (cs.st(at[0], at[1], 0), math.radians(yaw))
    ch.arm = {s: ch.shoulders[IDX[s]] for s in 'RL'}
    ch.arms_piv = list(ch.shoulders)
    ch.leg = {s: ch.hips[IDX[s]] for s in 'RL'}
    ch.head_mesh = old
    if outfit:   # real Roblox classic clothing: {"shirt": "lib:<tag>", "pants": "lib:<tag>"}; shirt/pants colours show through alpha
        import outfits
        for kind in ('shirt', 'pants'):
            if not outfit.get(kind): continue
            try: outfit[kind + '_path'] = outfits.lib(outfit[kind], kind)
            except KeyError: print(f'OUTFIT {name}: unknown {kind} {outfit[kind]!r}, kept the plain colour')
        outfits.apply(ch, shirt=outfit.get('shirt_path'), pants=outfit.get('pants_path'))
    CAST[name] = ch
    return ch


HAIR_STYLES = ('spiky', 'short', 'long', 'ponytail', 'bun', 'none')   # + 'lib:<asset id or name part>' = real Roblox hair (assets/hair)


def hair_dir(key):
    """'lib:13176641832' / 'lib:brown_charmer' -> assets/hair/<id>_<slug>/ (None if not found)."""
    k = key.split(':', 1)[1].lower()
    ds = [d for d in sorted((ASSETS / 'hair').glob('*_*')) if (d / 'mesh.obj').exists()]
    return next((d for d in ds if d.name.split('_', 1)[0] == k), None) or next((d for d in ds if k in d.name.lower()), None)


def _tinted_image(path, hex_col, name):
    """Hair texture -> its shading detail (luminance / mean) times the cast hair colour, baked into a new image so Workbench
    drafts (TEXTURE colour) and Cycles show the same recoloured hair."""
    import numpy as np
    src = bpy.data.images.load(str(path), check_existing=True)
    w, h = src.size; px = np.empty(w * h * 4, np.float32); src.pixels.foreach_get(px); px = px.reshape(-1, 4)
    lum = px[:, :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    det = np.clip(lum / max(float(lum.mean()), 1e-3), 0.35, 1.6)    # keep strand shading, drop the original hue
    col = np.array(lin(hex_col), np.float32)
    if col @ np.array([.2126, .7152, .0722], np.float32) < .04: det = 1 + (det - 1) * .6   # R-look2: dark hair = soft strands, not grey streaks
    out = np.ones_like(px); out[:, :3] = np.clip(det[:, None] * col, 0, 1)   # shortcut: alpha ignored (Roblox hair textures are opaque)
    im = bpy.data.images.new(name, w, h, float_buffer=True)   # float image = linear pixels, matching col
    im.pixels.foreach_set(out.ravel()); im.pack()
    return im


def lib_hair(hp, hex_col, key, mat_name, torso=None):
    """Real Roblox hair accessory under the hair pivot (= the R6 Head's HairAttachment, 0.6 stud above the head centre).
    Roblox weld: handle = headAtt * inverse(handleAtt); a MeshPart mesh is bbox-centred and scaled Size / MeshSize.
    Roblox (x right, y up, z back) -> head-local Blender (-x, z, y): the face looks -Y here and -Z in Roblox."""
    import json
    from mathutils import Vector
    d = hair_dir(key)
    if d is None: raise KeyError(f'hair {key} not in assets/hair')
    meta = json.loads((d / 'meta.json').read_text())
    V, UV, F = [], [], []
    for ln in open(d / 'mesh.obj'):
        t = ln.split()
        if not t: continue
        if t[0] == 'v': V.append(Vector(map(float, t[1:4])))
        elif t[0] == 'vt': UV.append((float(t[1]), float(t[2])))
        elif t[0] == 'f': F.append([int(x.split('/')[0]) - 1 for x in t[1:]])
    lo_, hi_ = Vector([min(v[i] for v in V) for i in range(3)]), Vector([max(v[i] for v in V) for i in range(3)])
    if meta.get('msize'):
        c = (lo_ + hi_) / 2; k = Vector([s / m for s, m in zip(meta['size'], meta['msize'])])
        P = [Vector(((v - c)[i] * k[i] for i in range(3))) for v in V]
    else:   # legacy SpecialMesh: v * Scale + Offset, mesh not recentred
        sc, of = Vector(meta.get('scale', (1, 1, 1))), Vector(meta.get('offset', (0, 0, 0)))
        P = [Vector((v[i] * sc[i] + of[i] for i in range(3))) for v in V]
    a = meta.get('att') or meta.get('attach_point')
    A = Matrix(((a[3], a[4], a[5], a[0]), (a[6], a[7], a[8], a[1]), (a[9], a[10], a[11], a[2]), (0, 0, 0, 1))) if a else Matrix()
    M = A.inverted() if meta.get('att') else Matrix.Translation((0, -0.1, 0)) @ A.inverted()   # legacy hats hang from head top (0.5)
    P = [M @ p for p in P]
    Q = [Vector(((-p.x) * S, p.z * S, p.y * S)) for p in P]
    if torso is not None:   # R15-made long hair cuts into the deeper R6 chest: push those vertices out to the nearest torso face
        bpy.context.view_layer.update()
        T = hp.matrix_world.inverted() @ torso.matrix_world; c = [T @ Vector(b) for b in torso.bound_box]
        lo_t, hi_t = Vector([min(v[i] for v in c) for i in range(3)]), Vector([max(v[i] for v in c) for i in range(3)])
        g = 0.04 * S; n_in = 0
        for q in Q:
            if all(lo_t[i] - g < q[i] < hi_t[i] + g for i in range(3)) and q.z < hi_t.z - 0.05 * S:
                i, side = min(((i, sd) for i in (0, 1) for sd in (0, 1)), key=lambda t: abs(q[t[0]] - (lo_t, hi_t)[t[1]][t[0]]))
                q[i] = (lo_t[i] - g) if side == 0 else (hi_t[i] + g); n_in += 1
        # SHOULDER FIT (R210): wide hair (curly/afro/long) hanging beside the torso below the shoulder top sits inside the arm
        # columns, so every raised/forward arm went through it (blind6_white_bedroom: give 24 cm, shrug 16 cm). Pull those
        # vertices in to the torso sides; hair above the shoulders and behind/in front of the torso keeps its shape.
        for q in Q:
            if q.z < hi_t.z + 0.15 * S and (q.x < lo_t.x - g or q.x > hi_t.x + g):
                q.x = lo_t.x - g if q.x < lo_t.x else hi_t.x + g
    me = bpy.data.meshes.new(f'hair lib {d.name}')
    me.from_pydata([tuple(q) for q in Q], [], F)
    if UV:
        uvl = me.uv_layers.new(name='UV')
        for lp in me.loops: uvl.data[lp.index].uv = UV[lp.vertex_index]
    for p in me.polygons: p.use_smooth = True
    m = hair_shine(material(mat_name + ' lib', hex_col), hex_col)
    if (d / 'tex.png').exists() and UV:
        nt = m.node_tree; tx = nt.nodes.new('ShaderNodeTexImage'); tx.interpolation = 'Closest'
        tx.image = _tinted_image(d / 'tex.png', hex_col, f'{mat_name} lib tex'); nt.nodes.active = tx
        nt.links.new(tx.outputs['Color'], nt.nodes['Principled BSDF'].inputs['Base Color'])
    me.materials.append(m)
    o = bpy.data.objects.new('hair lib', me); bpy.context.collection.objects.link(o); o.parent = hp
    o.visible_shadow = False   # big spiky library hair cast a dark smear across the face decal in Cycles (SSJ Goku, R172);
    return o                   # Roblox does not shadow faces with hair: it still receives light and reads 3D


def style_hair(hp, m, style):
    """Replace the spiky locks under the hair pivot with another silhouette built from the same sweep locks (studs, head-local:
    hair pivot sits 0.6 stud above the head pivot; face = -Y)."""
    from mathutils import Vector
    for o in list(hp.children_recursive):
        bpy.data.objects.remove(o, do_unlink=True)
    def lock(pts, w, flat=0.7):
        o = cs.sweep_lock('hair lock', [Vector(p) for p in pts], w, m, flat); o.parent = hp
    def cap(r=0.68, zs=0.62, z=0.0, y=0.04):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=r * S, location=(0, y * S, z * S))
        c = bpy.context.object; c.name = 'hair cap'; c.scale = (1.0, 1.0, zs); c.data.materials.append(m); c.parent = hp
        for p in c.data.polygons: p.use_smooth = True
        return c
    if style == 'short':
        cap(0.66, 0.6, -0.02)
        for x in (-0.3, 0.0, 0.3):   # short fringe
            lock([(x, -0.45, 0.05), (x + 0.05, -0.62, -0.08), (x + 0.1, -0.64, -0.22)], [0.17, 0.14, 0.004], 0.5)
    elif style in ('long', 'ponytail', 'bun'):
        cap(0.69, 0.66, 0.0)
        for x in (-0.32, -0.05, 0.25):
            lock([(x, -0.45, 0.08), (x + 0.04, -0.63, -0.06), (x + 0.08, -0.66, -0.25)], [0.18, 0.15, 0.004], 0.5)
        if style == 'long':          # straight locks down the back and sides to the shoulders
            for i in range(9):
                a = math.radians(-120 + i * 30); d = Vector((math.sin(a), math.cos(a), 0)) * 0.6
                b0 = Vector((d.x, d.y + 0.04, -0.1))
                lock([b0, b0 + Vector((d.x * 0.15, d.y * 0.15, -0.45)), b0 + Vector((d.x * 0.2, d.y * 0.2, -1.05))], [0.24, 0.22, 0.05], 0.55)
        elif style == 'ponytail':
            lock([(0, 0.55, 0.1), (0, 0.95, 0.0), (0, 1.1, -0.45), (0, 1.0, -0.95)], [0.24, 0.26, 0.2, 0.02], 0.8)
            bpy.ops.mesh.primitive_torus_add(major_radius=0.12 * S, minor_radius=0.05 * S, location=(0, 0.62 * S, 0.08 * S), rotation=(math.pi / 2, 0, 0))
            t = bpy.context.object; t.name = 'hair tie'; t.parent = hp; t.data.materials.append(m)
        else:                        # bun on top
            bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.3 * S, location=(0, 0.2 * S, 0.5 * S))
            b = bpy.context.object; b.name = 'hair bun'; b.parent = hp; b.data.materials.append(m)
            for p in b.data.polygons: p.use_smooth = True
