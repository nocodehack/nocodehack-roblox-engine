"""Claude still 1: reference frame-1 close-up, built from an empty file.
Run from this folder: blender -b --factory-startup --offline-mode --python-exit-code 1 -P claude_still.py -- [--preview]
Spec is in studs (S = 0.5 m); every light in watts; asserts guard the build."""
import bpy, math, sys, json, time
import numpy as np
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
S = 0.5  # one Roblox stud in metres
PREVIEW = '--preview' in sys.argv

def st(*v):  # studs -> metres
    return tuple(x * S for x in v)

# ---------- materials ----------
def mat(name, rgb, rough=0.8, spec=0.12):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*rgb, 1)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = 0
    b.inputs['Specular IOR Level'].default_value = spec
    return m

def checker_mat(name, c1, c2, scale):
    m = mat(name, c1, 0.6, 0.2)
    nt = m.node_tree
    tc = nt.nodes.new('ShaderNodeTexCoord'); ck = nt.nodes.new('ShaderNodeTexChecker')
    ck.inputs['Color1'].default_value = (*c1, 1); ck.inputs['Color2'].default_value = (*c2, 1)
    ck.inputs['Scale'].default_value = scale
    nt.links.new(tc.outputs['Object'], ck.inputs['Vector'])
    nt.links.new(ck.outputs['Color'], nt.nodes['Principled BSDF'].inputs['Base Color'])
    return m

# ---------- primitives (stud inputs) ----------
def box(name, loc, dim, m, bevel=0.03, segs=2, parent=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=st(*loc))
    o = bpy.context.object; o.name = name
    o.scale = st(*dim); bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)  # keep origin at the object (was baked to world 0)
    o.data.materials.append(m)
    if bevel:
        b = o.modifiers.new('bevel', 'BEVEL'); b.width = bevel * S; b.segments = segs
        o.modifiers.new('wn', 'WEIGHTED_NORMAL')
        for p in o.data.polygons: p.use_smooth = True
    if parent: o.parent = parent
    return o

def cyl(name, loc, r, h, m, bevel=0, segs=3, verts=64, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r * S, depth=h * S, location=st(*loc), rotation=rot)
    o = bpy.context.object; o.name = name; o.data.materials.append(m)
    for p in o.data.polygons: p.use_smooth = len(p.vertices) == 4
    if bevel:
        b = o.modifiers.new('rim', 'BEVEL'); b.width = bevel * S; b.segments = segs; b.limit_method = 'ANGLE'
        o.modifiers.new('wn', 'WEIGHTED_NORMAL')
    return o

def empty(name, loc, rot=(0, 0, 0), parent=None):
    e = bpy.data.objects.new(name, None); bpy.context.collection.objects.link(e)
    e.location = st(*loc); e.rotation_euler = rot
    if parent: e.parent = parent
    return e

def keep_parent(o, p):
    bpy.context.view_layer.update()
    w = o.matrix_world.copy(); o.parent = p; o.matrix_world = w

def text(body, loc, size, m, rot=(math.pi / 2, 0, 0)):
    c = bpy.data.curves.new('txt', 'FONT'); c.body = body; c.size = size * S
    c.align_x = c.align_y = 'CENTER'; c.extrude = 0.004
    o = bpy.data.objects.new('Text ' + body[:12], c); bpy.context.collection.objects.link(o)
    o.location = st(*loc); o.rotation_euler = rot; o.data.materials.append(m)
    return o

# ---------- face texture (own drawing, numpy) ----------
def face_image(kind, n=512):
    yy, xx = np.mgrid[0:n, 0:n] / n  # yy=0 bottom row in Blender pixel order
    rgba = np.zeros((n, n, 4), np.float32)
    def ink(mask, col=(0, 0, 0)):
        rgba[mask, :3] = col; rgba[mask, 3] = 1
    for cx in (0.33, 0.67):  # big black oval eyes with one white highlight
        ink(((xx - cx) / 0.085) ** 2 + ((yy - 0.62) / 0.13) ** 2 < 1)
        ink(((xx - cx + 0.025) / 0.025) ** 2 + ((yy - 0.68) / 0.03) ** 2 < 1, (1, 1, 1))
    if kind == 'smile':  # thick open smile crescent
        x = (xx - 0.5) / 0.2
        top = 0.36 - 0.0 * x; bot = 0.36 - 0.13 * np.sqrt(np.clip(1 - x ** 2, 0, 1))
        ink((abs(x) < 1) & (yy < top + 0.012) & (yy > bot - 0.012) & (yy < 0.36 - 0.13 * np.sqrt(np.clip(1 - x ** 2, 0, 1)) + 0.035))
    img = bpy.data.images.new('face_' + kind, n, n, alpha=True)
    img.pixels.foreach_set(rgba.ravel()); img.pack()
    assert rgba[..., 3].sum() > 2000, 'face too empty'
    return img

def face_decal(name, head_r, head_h, img, parent):
    # curved strip hugging the cylinder front, 120 degrees wide
    seg = 32; vs = []; faces = []; uvs = []
    for i in range(seg + 1):
        a = math.radians(-60 + 120 * i / seg)
        x, y = math.sin(a) * (head_r + 0.004), -math.cos(a) * (head_r + 0.004)
        vs += [(x * S, y * S, -head_h / 2 * S * 0.9), (x * S, y * S, head_h / 2 * S * 0.9)]
    for i in range(seg):
        faces.append((2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1))
    me = bpy.data.meshes.new(name); me.from_pydata(vs, [], faces); me.update()
    uv = me.uv_layers.new()
    for p in me.polygons:
        p.use_smooth = True
        for li in p.loop_indices:
            vi = me.loops[li].vertex_index; uv.data[li].uv = ((vi // 2) / seg, vi % 2)
    o = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(o)
    m = bpy.data.materials.new(name + ' ink'); m.use_nodes = True; nt = m.node_tree
    tex = nt.nodes.new('ShaderNodeTexImage'); tex.image = img
    b = nt.nodes['Principled BSDF']; b.inputs['Roughness'].default_value = 0.6; b.inputs['Specular IOR Level'].default_value = 0.05
    nt.links.new(tex.outputs['Color'], b.inputs['Base Color']); nt.links.new(tex.outputs['Alpha'], b.inputs['Alpha'])
    me.materials.append(m); o.parent = parent
    assert len(me.polygons) == seg
    return o

# ---------- hair: curved tapered locks (own sweep mesh) ----------
def sweep_lock(name, pts, widths, m, flat=0.6, sides=5):
    P = [Vector(p) for p in pts]; vs = []; fs = []
    for i, (c, w) in enumerate(zip(P, widths)):
        t = (P[min(i + 1, len(P) - 1)] - P[max(i - 1, 0)]).normalized()
        up = Vector((0, 0, 1)) if abs(t.z) < 0.95 else Vector((0, 1, 0))
        a = t.cross(up).normalized(); b2 = t.cross(a).normalized()
        for j in range(sides):
            ang = j * math.tau / sides
            vs.append(tuple((c + w * (math.cos(ang) * a + flat * math.sin(ang) * b2)) * S))
    n = len(P)
    for i in range(n - 1):
        for j in range(sides):
            fs.append((i * sides + j, i * sides + (j + 1) % sides, (i + 1) * sides + (j + 1) % sides, (i + 1) * sides + j))
    fs.append(tuple(reversed(range(sides)))); fs.append(tuple(range((n - 1) * sides, n * sides)))
    me = bpy.data.meshes.new(name); me.from_pydata(vs, [], fs); me.update()
    o = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(o); o.data.materials.append(m)
    for p in me.polygons: p.use_smooth = True
    assert all(math.isfinite(c) for v in vs for c in v)
    return o

def hair(parent, m, top_z):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.66 * S, location=(0, 0.03 * S, (top_z - 0.02) * S))
    cap = bpy.context.object; cap.name = 'hair cap'; cap.scale = (1.0, 1.0, 0.68); cap.data.materials.append(m)
    for p in cap.data.polygons: p.use_smooth = True
    cap.parent = parent; n = 0
    m2 = bpy.data.materials.get(m.name + ' light')
    if m2 is None:
        m2 = m.copy(); m2.name = m.name + ' light'
        bc = m2.node_tree.nodes['Principled BSDF'].inputs['Base Color']
        bc.default_value = tuple(min(1.0, c * 1.45) for c in bc.default_value[:3]) + (1,)
    def lock(pts, w, flat=0.6):
        nonlocal n
        o = sweep_lock('hair lock', pts, w, m2 if n % 2 else m, flat); o.parent = parent; n += 1
    # crown: 14 locks rising and flaring outward, curving at the tip
    for i in range(9):
        az = math.radians(-150 + i * (300 / 8)); r0 = 0.40
        d = Vector((math.sin(az), math.cos(az), 0))  # az 0 = back
        h = 0.65 + 0.16 * math.cos(az * 0.5) + 0.06 * math.sin(i * 2.1)
        b0 = Vector((0, 0.03, top_z - 0.05)) + d * r0
        lock([b0, b0 + d * 0.16 + Vector((0, 0, h * 0.35)), b0 + d * 0.32 + Vector((0, 0, h * 0.75)), b0 + d * 0.34 + Vector((0, 0.05, h))],
             [0.34, 0.28, 0.12, 0.004])
    # temple locks: sweep out and up at the sides and back
    for side in (-1, 1):
        for k in range(3):
            z = top_z - 0.25 - k * 0.14; y = 0.25 - k * 0.28
            b0 = Vector((side * 0.55, y, z))
            lock([b0, b0 + Vector((side * 0.22, 0.05, 0.1)), b0 + Vector((side * 0.42, 0.08, 0.26)), b0 + Vector((side * 0.42, 0.1, 0.5))],
                 [0.27, 0.24, 0.12, 0.004])
    # fringe: two locks over the forehead, one crossing the right eye
    lock([Vector((-0.2, -0.45, top_z - 0.02)), Vector((0.0, -0.62, top_z - 0.12)), Vector((0.2, -0.66, top_z - 0.38)), Vector((0.32, -0.62, top_z - 0.72))], [0.2, 0.19, 0.11, 0.004], 0.5)
    lock([Vector((-0.42, -0.38, top_z - 0.05)), Vector((-0.55, -0.52, top_z - 0.2)), Vector((-0.6, -0.5, top_z - 0.45))], [0.18, 0.15, 0.004], 0.5)
    assert n == 17
    return n

# ---------- character ----------
def r6(name, loc, shirt, hairm, face, yaw=0, arm_pose=49):
    root = empty(name, loc, (0, 0, math.radians(yaw)))
    box(name + ' torso', (0, 0, 3.0), (2, 1, 2), shirt, parent=root)
    for side in (-1, 1):  # shoulder pivot at torso top outer edge; arm hangs then rests forward on desk
        piv = empty(name + ' shoulder', (side * 1.0, 0, 4.0), (math.radians(-arm_pose), math.radians(-side * 10), 0), parent=root)
        arm = box(name + ' arm', (side * 0.5, 0, -1.0), (1, 1, 2), SKIN)
        arm.parent = piv
    for side in (-1, 1):
        box(name + ' leg', (side * 0.5, -1.0, 1.5), (1, 2, 1), PANTS, parent=root)
    head = empty(name + ' head', (0, 0, 4.62), (math.radians(-4), 0, math.radians(-5)), parent=root)
    h = cyl(name + ' head mesh', (0, 0, 0), 0.62, 1.24, SKIN, bevel=0.16, segs=4)
    h.parent = head; h.location = (0, 0, 0)
    face_decal(name + ' face', 0.62, 1.24, face, head)
    hair(head, hairm, 0.62)
    return root

# ---------- scene ----------
def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    global SKIN, PANTS
    SKIN = mat('Roblox yellow', (1.0, 0.78, 0.002), 0.8, 0.12)
    PANTS = mat('Blue pants', (0.04, 0.09, 0.32))
    red = mat('Red shirt', (0.57, 0.001, 0.002), 0.8)
    hair_red = mat('Red hair', (0.40, 0.0003, 0.002), 0.55, 0.25)
    hair_or = mat('Orange hair', (0.9, 0.3, 0.02), 0.4, 0.3)
    wall = mat('Warm yellow wall', (0.95, 0.78, 0.45), 0.85)
    trim = mat('Cream trim', (0.9, 0.82, 0.62), 0.7)
    desk_top = mat('Orange desk', (0.85, 0.22, 0.03), 0.55, 0.3)
    metal = mat('Black metal', (0.02, 0.02, 0.02), 0.4, 0.4)
    cork = mat('Cork', (0.42, 0.24, 0.10), 0.95, 0.05)
    frame = mat('Wood frame', (0.25, 0.12, 0.05), 0.7)
    white = mat('Cake white', (0.92, 0.88, 0.8), 0.5)
    cake_red = mat('Cake red', (0.75, 0.02, 0.02), 0.45, 0.3)
    ink = mat('Ink', (0.02, 0.02, 0.02), 0.6)
    pastel = [mat('note ' + str(i), c, 0.85) for i, c in enumerate([(0.95, 0.55, 0.5), (0.55, 0.8, 0.85), (0.98, 0.9, 0.45),
              (0.7, 0.9, 0.6), (0.95, 0.75, 0.85), (0.98, 0.98, 0.92)])]
    floor = checker_mat('Navy checker floor', (0.04, 0.05, 0.12), (0.22, 0.25, 0.36), 1.33)

    # room: back wall y=+9, right wall x=+9 with window, floor z=0
    box('floor', (0, 2, -0.1), (40, 40, 0.2), floor, bevel=0)
    box('back wall', (0, 9.2, 8), (40, 0.4, 16), wall, bevel=0)
    box('left wall', (-9.2, 0, 8), (0.4, 40, 16), wall, bevel=0)
    box('right wall lower', (9.2, 0, 2.5), (0.4, 40, 5), wall, bevel=0)
    box('right wall upper', (9.2, 0, 13.5), (0.4, 40, 5), wall, bevel=0)
    box('right wall a', (9.2, -10, 8), (0.4, 16, 16), wall, bevel=0)
    box('right wall b', (9.2, 12, 8), (0.4, 8, 16), wall, bevel=0)
    box('ceiling', (0, 0, 16.1), (40, 40, 0.2), trim, bevel=0)
    box('wall trim', (0, 9.0, 12.2), (40, 0.2, 0.3), trim, bevel=0)
    # cork board with pastel notes
    box('cork board', (-1.0, 8.95, 8.6), (11, 0.15, 5.0), cork, bevel=0.02)
    box('board frame', (-1.0, 9.0, 8.6), (11.4, 0.1, 5.4), frame, bevel=0.02)
    labels = ['Lunch\nMenu', 'Picture\nDay', 'Spelling\nTest Wed', 'Field trip\nFri', 'Great job\nclass!',
              'Recess\nRules', 'Art Club', 'Library\nTues', 'Science\nFair', 'Book Fair']
    for i, lab in enumerate(labels):
        cx = -5.2 + (i % 5) * 2.1; cz = 9.8 - (i // 5) * 2.3
        box('note', (cx, 8.85, cz), (1.75, 0.04, 1.8), pastel[i % 6], bevel=0)
        text(lab, (cx, 8.82, cz - 0.1), 0.34, ink)
        cyl('pin', (cx, 8.8, cz + 0.72), 0.08, 0.1, pastel[(i + 2) % 6], rot=(math.pi / 2, 0, 0), verts=16)
    # bunting along the top of the back wall
    for i in range(22):
        x = -10 + i * 0.95; z = 12.2 - 0.35 * math.sin(i / 21 * math.pi)
        tri = bpy.data.meshes.new('flag'); tri.from_pydata([st(x - 0.4, 8.9, z), st(x + 0.4, 8.9, z), st(x, 8.9, z - 0.8)], [], [(0, 1, 2)])
        o = bpy.data.objects.new('bunting flag', tri); bpy.context.collection.objects.link(o)
        o.data.materials.append([cake_red, pastel[1], pastel[2], pastel[3], pastel[4]][i % 5])
    # clock
    cyl('clock face', (6.0, 8.9, 11.0), 0.9, 0.15, white, rot=(math.pi / 2, 0, 0))
    cyl('clock rim', (6.0, 8.95, 11.0), 1.0, 0.12, ink, rot=(math.pi / 2, 0, 0))
    box('hand h', (6.0, 8.8, 11.25), (0.08, 0.02, 0.5), ink, bevel=0)
    box('hand m', (6.3, 8.8, 11.0), (0.6, 0.02, 0.06), ink, bevel=0)
    # ---- set dressing (round 2): posters, shelf, globe, plants, wainscot, side desks
    green = mat('Poster green', (0.05, 0.35, 0.12), 0.85); blue = mat('Poster blue', (0.04, 0.16, 0.55), 0.85)
    wtxt = mat('Poster text', (0.95, 0.95, 0.9), 0.8)
    box('poster science', (7.0, 8.95, 6.6), (2.8, 0.06, 3.6), green, bevel=0)
    text('SCIENCE', (7.0, 8.9, 7.6), 0.5, wtxt); text('ask why!', (7.0, 8.9, 6.6), 0.32, wtxt)
    box('poster read', (-8.2, 8.95, 6.2), (2.4, 0.06, 3.0), blue, bevel=0)
    text('READ!', (-8.2, 8.9, 6.5), 0.62, wtxt); text('every day', (-8.2, 8.9, 5.5), 0.3, wtxt)
    box('wainscot', (0, 9.05, 2.0), (40, 0.1, 4.0), mat('Wainscot', (0.85, 0.58, 0.26), 0.85), bevel=0)
    box('wainscot rail', (0, 8.98, 4.05), (40, 0.12, 0.18), trim, bevel=0)
    shelf = mat('Shelf wood', (0.35, 0.17, 0.06), 0.75)
    sx, sy = -6.6, 8.2
    box('shelf body', (sx, sy, 2.6), (3.6, 1.0, 5.2), shelf, bevel=0.02)
    for k, z in enumerate((1.0, 2.6, 4.2)):
        box('shelf board', (sx, sy - 0.05, z), (3.4, 0.9, 0.12), shelf, bevel=0)
        for j in range(7):
            bh = 0.9 + 0.25 * ((j * 7 + k * 3) % 4) / 3
            box('shelf book', (sx - 1.4 + j * 0.42, sy - 0.15, z + 0.06 + bh / 2), (0.32, 0.7, bh),
                [pastel[j % 6], cake_red, pastel[(j + 2) % 6]][(j + k) % 3], bevel=0)
    globe_m = mat('Globe sea', (0.05, 0.25, 0.65), 0.5)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.55 * S, location=st(sx + 1.0, sy - 0.1, 5.9))
    g = bpy.context.object; g.name = 'globe'; g.data.materials.append(globe_m)
    for p in g.data.polygons: p.use_smooth = True
    cyl('globe stand', (sx + 1.0, sy - 0.1, 5.3), 0.25, 0.2, frame)
    pot = mat('Pot', (0.55, 0.18, 0.06), 0.8); leaf = mat('Leaf', (0.08, 0.35, 0.06), 0.7)
    for (px, py) in ((8.2, 7.8), (-8.4, 3.0)):
        cyl('plant pot', (px, py, 0.5), 0.45, 1.0, pot)
        for a in range(7):
            ang = a * math.tau / 7
            bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=0.18 * S, radius2=0.0, depth=1.4 * S,
                                            location=st(px + 0.3 * math.cos(ang), py + 0.3 * math.sin(ang), 1.6))
            lf = bpy.context.object; lf.name = 'plant leaf'; lf.data.materials.append(leaf)
            lf.rotation_euler = (0.5 * math.sin(ang), 0.5 * math.cos(ang), 0)
    # side desk rows for depth (empty desks + chairs)
    for (dx, dy) in ((-6.4, 1.2), (6.6, 1.6), (-6.0, 6.0), (7.4, 5.6)):
        box('side desk top', (dx, dy, 2.55), (3.8, 2.2, 0.16), desk_top, bevel=0.03)
        for ax in (-1, 1):
            for ay in (-1, 1):
                box('side desk leg', (dx + ax * 1.7, dy + ay * 0.95, 1.25), (0.12, 0.12, 2.5), metal, bevel=0)

    # window opening glass (sky) on right wall
    box('window glass', (9.35, 1.0, 8.0), (0.05, 6, 6), mat('Sky', (0.55, 0.75, 0.95), 0.2), bevel=0)

    # desks: hero desk + classmate desk behind
    def desk(x, y, w=4.2, d=2.4):
        box('desk top', (x, y, 2.55), (w, d, 0.16), desk_top, bevel=0.03)
        for sx in (-1, 1):
            for sy in (-1, 1):
                box('desk leg', (x + sx * (w / 2 - 0.15), y + sy * (d / 2 - 0.15), 1.25), (0.12, 0.12, 2.5), metal, bevel=0)
    desk(0, -1.3, w=6.0)
    desk(-2.2, 4.2)
    desk(3.6, 5.0)

    hero_face = face_image('smile')
    r6('Hero', (0, 0.2, 0), red, hair_red, hero_face, yaw=0, arm_pose=8)
    r6('Classmate', (-2.4, 5.6, 0), mat('Teal shirt', (0.05, 0.4, 0.45)), hair_or, hero_face, yaw=12, arm_pose=8)

    r6('Classmate2', (3.6, 6.4, 0), mat('Pink shirt', (0.8, 0.2, 0.4)), mat('Purple hair', (0.35, 0.05, 0.5), 0.5, 0.25), hero_face, yaw=-10, arm_pose=8)
    wood = mat('Chair wood', (0.45, 0.22, 0.08), 0.7)
    for (x, y) in ((0, 0.2), (-2.4, 5.6), (3.6, 6.4)):
        box('chair seat', (x, y + 0.3, 1.9), (2.2, 2.0, 0.2), wood, bevel=0.02)
        box('chair back', (x, y + 1.35, 3.0), (2.2, 0.2, 2.0), wood, bevel=0.02)
        for sx in (-1, 1):
            for sy in (-0.6, 1.2):
                box('chair leg', (x + sx * 0.95, y + sy, 0.95), (0.1, 0.1, 1.9), metal, bevel=0)
    bc = [mat('book a', (0.85, 0.06, 0.06), 0.7), mat('book b', (0.06, 0.35, 0.9), 0.7), mat('book c', (1.0, 0.72, 0.04), 0.7)]
    for i in range(3):
        box('book', (-2.0, -1.4, 2.70 + i * 0.16), (1.1 - i * 0.08, 0.8, 0.15), bc[i], bevel=0.01)
    box('notebook', (-0.45, -1.4, 2.66), (0.9, 0.7, 0.04), white, bevel=0)
    box('pencil', (0.3, -1.5, 2.70), (0.7, 0.06, 0.06), mat('Pencil', (0.95, 0.6, 0.05), 0.6), bevel=0)

    # cake: 2 tiers, red bands, "12" topper, on the front right of the hero desk
    cx, cy, top = 2.4, -1.22, 2.63
    cyl('cake base plate', (cx, cy, top + 0.03), 0.47, 0.06, white)
    cyl('cake tier 1', (cx, cy, top + 0.24), 0.40, 0.36, white, bevel=0.03)
    cyl('cake band 1', (cx, cy, top + 0.22), 0.41, 0.12, cake_red)
    cyl('cake tier 2', (cx, cy, top + 0.58), 0.30, 0.32, white, bevel=0.03)
    cyl('cake band 2', (cx, cy, top + 0.56), 0.31, 0.10, cake_red)
    t = text('12', (cx, cy, top + 0.95), 0.45, cake_red, rot=(math.pi / 2, 0, math.radians(-15)))
    t.data.extrude = 0.03

    # ---------- lights (watts, metre scale) ----------
    sc.world = bpy.data.worlds.new('World'); sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes['Background']; bg.inputs['Color'].default_value = (1, 1, 1, 1); bg.inputs['Strength'].default_value = 0.15
    def light(name, kind, loc, target, watts, rgb, size=2.0):
        d = bpy.data.lights.new(name, kind); d.energy = watts; d.color = rgb
        if kind == 'AREA': d.size = size; d.shape = 'DISK'
        else: d.angle = math.radians(4)
        o = bpy.data.objects.new(name, d); bpy.context.collection.objects.link(o)
        o.location = st(*loc); o.rotation_euler = (Vector(st(*target)) - o.location).to_track_quat('-Z', 'Y').to_euler()
        return o
    light('key', 'AREA', (4.7, 7.4, 6.0), (0, 0, 3.4), 300, (1.0, 0.7605, 0.4621), 1.7)
    light('fill', 'AREA', (-1.6, -2.6, 5.6), (0, 0, 3.6), 30, (1.0, 1.0, 1.0), 2.5)
    light('bounce', 'AREA', (0, 2.2, 8.4), (0, 2.2, 0), 220, (1.0, 1.0, 1.0), 4.0)
    light('sun', 'SUN', (20, -2, 20), (0, 3, 0), 2.0, (1.0, 0.9, 0.75))

    # ---------- camera: tight close-up like reference frame 1 ----------
    cd = bpy.data.cameras.new('cam'); cd.lens = 38; cd.sensor_fit = 'VERTICAL'; cd.sensor_height = 36
    cam = bpy.data.objects.new('cam', cd); bpy.context.collection.objects.link(cam)
    cam.location = st(0.3, -9.0, 6.6)
    cam.rotation_euler = (Vector(st(0.1, 1.2, 3.9)) - cam.location).to_track_quat('-Z', 'Y').to_euler()
    sc.camera = cam

    # ---------- render ----------
    sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'
    sc.cycles.samples = 24 if PREVIEW else 128; sc.cycles.use_denoising = True; sc.cycles.seed = 7
    sc.cycles.adaptive_threshold = 0.03; sc.cycles.time_limit = 30 if PREVIEW else 200
    sc.cycles.max_bounces = 8; sc.cycles.diffuse_bounces = 5
    sc.render.resolution_x, sc.render.resolution_y = 540, 960
    sc.render.resolution_percentage = 50 if PREVIEW else 100
    sc.view_settings.view_transform = 'AgX'; sc.view_settings.look = 'AgX - Medium High Contrast'
    sc.view_settings.exposure = 0.15
    # build checks
    assert abs(bpy.data.objects['Hero torso'].dimensions.z - 2 * S) < 1e-6
    assert sum(1 for o in bpy.data.objects if o.name.startswith('hair')) == 3 * (17 + 1)
    return sc

if __name__ == '__main__':
    t0 = time.time(); sc = build()
    out = ROOT / ('preview.png' if PREVIEW else 'still.png')
    sc.render.filepath = str(out); bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / 'still.blend'))
    (ROOT / 'render_log.json').write_text(json.dumps({'out': out.name, 'seconds': round(time.time() - t0, 1),
                                                      'samples': sc.cycles.samples}))
    print('DONE', out, round(time.time() - t0, 1))
