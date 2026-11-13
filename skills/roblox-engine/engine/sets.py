"""sets.py - set presets and props. Geometry of the classroom is lifted from cook20.py (Codex, 2026-11-08) and built under a
root empty scaled K = 0.77 so its furniture matches exact R6 proportions (cook20 torso 1.30 m vs R6 1.0 m).
Public: build(spec) -> dict(marks={name: (x, y) studs}, supports=[(xmin, xmax, ymin, ymax, top_z) metres], blockers=[objects]).
Props: prop(kind, name, at_studs) -> pivot empty (origin at the prop's base centre)."""
import math, os, random
import bpy
from mathutils import Vector
import claude_still as cs

S = cs.S
K = 0.77
P = math.pi
U = S / K          # 1 stud in cook20 units (inside the scaled root)
_root = None
M = {}             # materials


def _mat(name, rgb, rough=.65, emission=0):
    if name in M: return M[name]
    m = bpy.data.materials.new(name); m.diffuse_color = (*rgb, 1); m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (*rgb, 1); b.inputs['Roughness'].default_value = rough
    b.inputs['Specular IOR Level'].default_value = .12
    if emission:
        b.inputs['Emission Color'].default_value = (*rgb, 1); b.inputs['Emission Strength'].default_value = emission
    M[name] = m
    return m


def _link(o, parent):
    o.parent = parent if parent is not None else _root


def mesh(name, verts, faces, material, parent=None):
    d = bpy.data.meshes.new(name); d.from_pydata(verts, [], faces); d.update()
    o = bpy.data.objects.new(name, d); bpy.context.collection.objects.link(o); o.data.materials.append(material)
    _link(o, parent); return o


def box(name, pos, size, material, parent=None, bevel=.025):
    bpy.ops.mesh.primitive_cube_add(size=1); o = bpy.context.object; o.name = name
    o.dimensions = size; bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    _link(o, parent); o.location = pos; o.data.materials.append(material)
    if bevel:
        b = o.modifiers.new('bevel', 'BEVEL'); b.width, b.segments = bevel, 2
        o.modifiers.new('wn', 'WEIGHTED_NORMAL')
    return o


def cyl(name, pos, radius, height, material, parent=None, bevel=.025, vertices=64):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=height); o = bpy.context.object; o.name = name
    _link(o, parent); o.location = pos; o.data.materials.append(material)
    for p in o.data.polygons: p.use_smooth = len(p.vertices) == 4
    if bevel:
        b = o.modifiers.new('rim', 'BEVEL'); b.width, b.segments = bevel, 3
        o.modifiers.new('wn', 'WEIGHTED_NORMAL')
    return o


def orb(name, pos, scale, material, parent=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8); o = bpy.context.object; o.name = name
    _link(o, parent); o.location, o.scale = pos, scale; o.data.materials.append(material)
    for p in o.data.polygons: p.use_smooth = True
    return o


def text(name, body, pos, size, material, parent=None, rotation=(P / 2, 0, 0)):
    d = bpy.data.curves.new(name, 'FONT'); d.body, d.size, d.align_x, d.align_y = body, size, 'CENTER', 'CENTER'; d.extrude = .002
    o = bpy.data.objects.new(name, d); bpy.context.collection.objects.link(o)
    _link(o, parent); o.location, o.rotation_euler = pos, rotation; d.materials.append(material); return o


def line(name, points, radius, material, parent=None):
    d = bpy.data.curves.new(name, 'CURVE'); d.dimensions, d.bevel_depth, d.bevel_resolution = '3D', radius, 2
    s = d.splines.new('POLY'); s.points.add(len(points) - 1)
    for p, co in zip(s.points, points): p.co = (*co, 1)
    o = bpy.data.objects.new(name, d); bpy.context.collection.objects.link(o); _link(o, parent); d.materials.append(material); return o


def mats():
    c = dict(
        yellow=('Warm Roblox yellow', (1, .72, .002), .80), red=('Birthday red', (.57, .001, .002), .80),
        pink=('Raspberry pink', (.65, .025, .28), .65), teal=('Turquoise shirt', (.016, .38, .40), .65),
        navy=('Navy trousers', (.018, .035, .065), .65), dark=('Soft black', (.008, .013, .02), .65),
        white=('Icing white', (.98, .95, .82), .7), paper=('Book paper', (.85, .83, .73), .9),
        pageedge=('Fine page lines', (.5, .45, .35), 1), wood=('Orange school furniture', (.60, .21, .046), .65),
        woodedge=('Honey edge', (.35, .095, .018), .65), metal=('Painted charcoal steel', (.018, .023, .027), .4),
        wall=('Butter classroom walls', (.70, .49, .23), .95), trim=('Cream window trim', (.91, .83, .62), .65),
        cork=('Bulletin cork', (.31, .12, .043), 1), green=('School green', (.027, .22, .11), .65),
        blue=('Poster blue', (.03, .34, .42), .65), tileA=('Floor blue slate', (.095, .14, .20), .85),
        tileB=('Floor pale slate', (.24, .31, .37), .85))
    out = {k: _mat(*v) for k, v in c.items()}
    out['sky'] = _mat('Sky beyond glass', (.40, .70, .83), 1, .3)
    return out


def desk(x, y, main=False, chair=True):
    """x, y in cook20 units (inside root). Returns the desktop object."""
    m = mats()
    width, depth = (3.5, 1.4) if main else (2.0, 1.05)
    top = box('desk top', (x, y, 1.70), (width, depth, .16), m['wood'], bevel=.035)
    box('Desktop front lip', (x, y - depth / 2, 1.66), (width, .035, .12), m['woodedge'], bevel=.01)
    for sx in (-1, 1):
        for sy in (-1, 1):
            box('Black desk leg', (x + sx * (width / 2 - .15), y + sy * (depth / 2 - .13), .83), (.065, .065, 1.64), m['metal'])
    if not main and chair:
        box('Chair seat', (x, y + 1.05, 1.16), (1.1, 1, .12), m['wood'])
        box('Chair back', (x, y + 1.48, 1.87), (1.05, .10, .96), m['wood'])
        for sx in (-1, 1): box('Chair upright', (x + sx * .44, y + 1.48, 1.24), (.06, .06, 2.12), m['metal'])
    return top


def classroom(spec):
    m = mats(); random.seed(21)
    from rooms import hexrgb
    for key, field in (('wall', 'wall'), ('trim', 'trim'), ('tileA', 'floor_color')):
        if field in spec: m[key] = _mat('Classroom ' + field + ' ' + spec[field], hexrgb(spec[field]), .85)
    box('Back wall', (0, 6.2, 3.4), (14, .22, 6.8), m['wall'])
    # room extended to the front (y -12) with a front wall, so reverse angles never see the void
    box('Right window wall', (7, -2.9, 3.4), (.2, 18.4, 6.8), m['wall'])
    box('Left wall', (-7, -2.9, 3.4), (.2, 18.4, 6.8), m['wall'])
    box('Front wall', (0, -12.1, 3.4), (14, .22, 6.8), m['wall'])
    box('Ceiling', (0, -2.9, 6.9), (14, 18.4, .15), m['trim'])
    box('Front door', (-4.2, -11.95, 1.55), (1.6, .10, 3.1), m['wood'])
    orb('Door knob', (-3.65, -11.88, 1.5), (.06, .05, .06), m['dark'])
    box('Front whiteboard frame', (1.5, -11.97, 3.5), (5.2, .06, 2.3), m['trim'])
    box('Front whiteboard', (1.5, -11.93, 3.5), (5.0, .03, 2.1), _mat('Whiteboard', (.9, .92, .93), .3))
    text('Whiteboard writing', spec.get('board', 'Quiz Friday!'), (1.5, -11.91, 3.9), .35, m['blue'], rotation=(P / 2, 0, P))
    for i in range(27):
        x = -6.8 + i * .51
        mesh('Front bunting', [(x, -11.85, 5.78), (x + .48, -11.85, 5.78), (x + .24, -11.85, 5.40)], [(0, 1, 2)], [m['pink'], m['yellow'], m['teal'], m['red'], m['blue']][i % 5])
    box('Floor', (0, -2.5, -.065), (14, 19, .10), m['tileA'], bevel=0)
    box('Wall skirting', (0, 6.04, .19), (14, .10, .30), m['trim'])
    box('Noticeboard frame', (-.3, 6.02, 3.50), (6.7, .14, 2.35), m['woodedge'])
    box('Noticeboard cork', (-.3, 5.93, 3.5), (6.45, .06, 2.10), m['cork'])
    notes_m = [_mat('Paper peach', (.94, .48, .32)), _mat('Paper lemon', (.91, .76, .30)), _mat('Paper mint', (.34, .64, .49)), _mat('Paper cream', (.92, .86, .68))]
    notes = spec.get('notes', ['Picture\nDay', 'Book Fair', 'Spelling\nTest Wed', 'Field Trip\nFriday', 'Lunch\nMenu', 'Library\nTuesday', 'Great job\nclass!', 'Science\nFair'])
    for j, s in enumerate(notes[:8]):
        x = -2.8 + (j % 4) * 1.62; z = 4.06 - (j // 4) * 1.08
        box('Pinned announcement', (x, 5.87, z), (1.22, .018, .86), notes_m[j % 4], bevel=.004)
        text('School announcement', s, (x, 5.845, z), .145, m['dark'])
        orb('Red drawing pin', (x, 5.82, z + .35), (.023, .013, .023), m['red'])
    for x, mm, title, sub in [(4.65, m['green'], 'SCIENCE', 'ask why!'), (-5.1, m['blue'], 'READ!', 'every day')]:
        box('Bright learning poster', (x, 6.03, 3.65), (1.65, .035, 2.25), mm)
        text('Poster heading', title, (x, 5.997, 3.95), .27, m['white']); text('Poster subline', sub, (x, 5.997, 3.28), .16, m['white'])
    c = cyl('Clock dark rim', (3.15, 6.0, 5.18), .49, .07, m['dark']); c.rotation_euler.x = P / 2
    c = cyl('Clock cream dial', (3.15, 5.95, 5.18), .45, .04, m['white']); c.rotation_euler.x = P / 2
    for i in range(12):
        a = i * math.tau / 12
        line('Clock tick', [(3.15 + .39 * math.sin(a), 5.915, 5.18 + .39 * math.cos(a)), (3.15 + .35 * math.sin(a), 5.915, 5.18 + .35 * math.cos(a))], .012, m['dark'])
    line('Clock hands', [(3.15, 5.90, 5.49), (3.15, 5.90, 5.18), (2.91, 5.90, 5.05)], .018, m['dark'])
    for i in range(27):
        x = -6.8 + i * .51
        mesh('Party bunting', [(x, 5.87, 5.78), (x + .48, 5.87, 5.78), (x + .24, 5.87, 5.40)], [(0, 1, 2)], [m['red'], m['teal'], m['yellow'], m['pink'], m['blue']][i % 5])
    line('Bunting string', [(-7, 5.86, 5.79), (7, 5.86, 5.79)], .013, m['white'])
    box('Window sky', (6.87, 1.8, 3.7), (.04, 4.1, 3.4), m['sky'])
    for y in (-.3, 1.8, 3.9): box('Window vertical bar', (6.78, y, 3.7), (.15, .09, 3.6), m['trim'])
    for z in (1.9, 3.7, 5.5): box('Window crossbar', (6.77, 1.8, z), (.16, 4.35, .10), m['trim'])
    box('Window sill', (6.66, 1.8, 1.88), (.48, 4.5, .12), m['trim'])
    box('Cabinet', (4.9, 5.35, .98), (2.2, .9, 1.95), m['woodedge'])
    for x in (4.38, 5.42):
        box('Cabinet door', (x, 4.87, 1.0), (.97, .05, 1.65), m['wood']); orb('Cabinet knob', (x + .30, 4.82, 1.12), (.04, .035, .04), m['dark'])
    orb('Class globe', (5.5, 5.23, 2.43), (.36, .36, .36), m['blue']); cyl('Globe foot', (5.5, 5.23, 2.03), .22, .07, m['dark'])
    cyl('Plant pot', (4.25, 5.18, 2.12), .17, .28, m['red'])
    for i in range(8):
        a = i * 2.4; tip = (4.25 + math.sin(a) * .30, 5.18 + math.cos(a) * .20, 2.55 + random.random() * .25)
        line('Plant stem', [(4.25, 5.18, 2.21), tip], .015, m['green'])
        mesh('Plant leaf', [tip, (tip[0] + .13, tip[1], tip[2] + .13), (tip[0] - .09, tip[1] - .05, tip[2] + .22)], [(0, 1, 2)], m['green'])
    tops = []
    for d in spec.get('desks', [{'at': [0, -0.4], 'main': True}, {'at': [-3.5, 3.3]}, {'at': [3.3, 4.2]}]):
        tops.append(desk(d['at'][0] * U, d['at'][1] * U, d.get('main', False), d.get('chair', True)))
    return tops


def build(spec):
    """spec = {'preset': 'classroom', ...}. Returns marks/supports/blockers in WORLD metres / studs."""
    global _root
    if spec.get('preset') == 'rbx':     # imported Roblox Creator Store set (assets/rbxsets), see LIBRARY.md
        return rbx_set(spec['rbx'], spec.get('at', (0, 0)), spec.get('rot', 0), spec.get('scale', 1), spec)
    explicit_floor = 'floor' in spec
    spec = interior_palette(spec)
    if spec.get('preset', 'classroom') != 'classroom':     # generic sets for any story (rooms.py + Kenney assets)
        import rooms, assets
        info = rooms.build(spec); _dress_set(spec.get('preset', 'room'), info)
        if not info.get('outdoor') and not explicit_floor:
            # Keep the preset's wood/tile construction, with seams rather than competing checker colours.
            floor = bpy.data.objects.get('floor')
            if floor:
                for node in floor.data.materials[0].node_tree.nodes:
                    if node.type in ('TEX_CHECKER', 'TEX_BRICK'):
                        color = node.inputs['Color1'].default_value
                        node.inputs['Color2'].default_value = (*(c * .9 for c in color[:3]), 1)
                        if node.type == 'TEX_BRICK': node.inputs['Mortar'].default_value = (*(c * .75 for c in color[:3]), 1)
        if info.get('outdoor') and os.environ.get('SETS_R152', '1') != '0': _outdoor(spec.get('preset', 'room'), info)
        obs = assets.obstacles()
        return {'supports': obs, 'desk_tops': [], 'root': None, 'bounds': info['bounds'], 'obstacles': obs, 'info': info}
    _root = bpy.data.objects.new('SET', None); bpy.context.collection.objects.link(_root); _root.scale = (K, K, K)
    preset = spec.get('preset', 'classroom')
    tops = classroom(spec) if preset == 'classroom' else []
    bpy.context.view_layer.update()
    if preset == 'classroom': _dress_set(preset)
    supports = []
    for t in tops:
        pts = [t.matrix_world @ Vector(c) for c in t.bound_box]
        supports.append((min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    bounds = (-6.85 * K, 6.85 * K, -11.95 * K, 6.05 * K) if preset == 'classroom' else None   # inner walls, metres
    return {'supports': supports, 'desk_tops': tops, 'root': _root, 'bounds': bounds}


# ---------------- props (world metres; built unscaled at R6 scale) ----------------
def prop(kind, name, at, rot_deg=0):
    """at = (x, y, z) metres of the prop base centre. Returns the pivot empty; meshes are its children."""
    global _root
    keep = _root; _root = None
    m = mats()
    piv = bpy.data.objects.new(name, None); bpy.context.collection.objects.link(piv)
    piv.location = at; piv.rotation_euler.z = math.radians(rot_deg)
    k = K
    if kind == 'cake':
        cyl(name + ' plate', (0, 0, .025 * k), .49 * k, .05 * k, m['white'], piv, .018 * k)
        cyl(name + ' tier 1', (0, 0, .15 * k), .405 * k, .22 * k, m['red'], piv, .027 * k)
        cyl(name + ' filling', (0, 0, .275 * k), .412 * k, .065 * k, m['white'], piv, .012 * k)
        cyl(name + ' tier 2', (0, 0, .37 * k), .36 * k, .15 * k, m['red'], piv, .025 * k)
        cyl(name + ' icing', (0, 0, .465 * k), .375 * k, .07 * k, m['white'], piv, .025 * k)
        for j in range(12):
            a = j * math.tau / 12
            orb(name + ' pearl', (.335 * k * math.sin(a), .335 * k * math.cos(a), .507 * k), (.042 * k, .042 * k, .035 * k), m['white'], piv)
    elif kind == 'book':
        cover = m['red']
        box(name + ' pages', (0, 0, .075 * k), (.68 * k, .90 * k, .12 * k), m['paper'], piv, .008)
        for z in (0, .15): box(name + ' cover', (0, 0, z * k + .014 * k), (.73 * k, .94 * k, .028 * k), cover, piv, .012 * k)
    elif kind == 'ball':
        orb(name + ' ball', (0, 0, .3), (.3, .3, .3), m['red'], piv)
    elif kind == 'phone':
        box(name + ' body', (0, 0, .3), (.32, .05, .56), m['dark'], piv, .015)        # Roblox-scale phone (hand is 0.5 m wide)
        box(name + ' screen', (0, -.027, .3), (.28, .004, .48), _mat('Phone screen', (.2, .5, .9), .3, 1.5), piv, 0)
    elif kind.startswith('screen'):   # 'screen:<image path>' = a desk monitor showing that image (emissive), facing -Y (showcase twist: the fight is on a screen)
        W, H = 1.9, 1.1
        box(name + ' stand', (0, .06, .02), (.7, .4, .04), m['dark'], piv, .01); box(name + ' neck', (0, .08, .2), (.12, .06, .4), m['dark'], piv, .01)
        box(name + ' body', (0, 0, .35 + H / 2), (W + .12, .07, H + .12), m['dark'], piv, .02)
        import os
        img = kind.partition(':')[2]; img = img if os.path.isabs(img) else os.path.join(os.path.dirname(os.path.abspath(__file__)), img)
        me = bpy.data.meshes.new(name + ' picture')
        me.from_pydata([(-W / 2, -.04, .35), (W / 2, -.04, .35), (W / 2, -.04, .35 + H), (-W / 2, -.04, .35 + H)], [], [(0, 1, 2, 3)])
        uv = me.uv_layers.new(name='UVMap')
        for i, c in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))): uv.data[i].uv = c
        o = bpy.data.objects.new(name + ' picture', me); bpy.context.collection.objects.link(o); o.parent = piv
        mt = bpy.data.materials.new(name + ' picture'); mt.use_nodes = True; mt.diffuse_color = (.93, .9, .84, 1); nt = mt.node_tree
        for n_ in list(nt.nodes): nt.nodes.remove(n_)
        out = nt.nodes.new('ShaderNodeOutputMaterial'); em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Strength'].default_value = 1.6
        if os.path.exists(img):
            tx = nt.nodes.new('ShaderNodeTexImage'); tx.image = bpy.data.images.load(img); tx.image.pack(); nt.links.new(tx.outputs['Color'], em.inputs['Color'])
        else: em.inputs['Color'].default_value = (.93, .9, .84, 1)
        nt.links.new(em.outputs['Emission'], out.inputs['Surface']); me.materials.append(mt)
    elif kind != 'box':      # any Kenney model by name ('food-kit/pizza-box', 'laptop', 'cupcake', ...): holdable copy, not an obstacle
        import assets
        e = assets.find(kind); k = assets.KIT_SCALE.get(e['kit'], 1.0)
        big = max(e['size_x'], e['size_y'], e['size_z']) * k
        assets.place(kind, (0, 0), parent=piv, register=False, scale=min(1.0, 0.8 / big))   # hand props <= 0.8 m (pizza box was 2.8 m)
    else:
        box(name + ' box', (0, 0, .25), (.5, .5, .5), m['wood'], piv)
    _root = keep
    return piv



# ---------------- wall dressing (R141): flush, seeded decor on every interior set ----------------
_WALLNAMES = {'back wall', 'front wall', 'left wall', 'right wall', 'right window wall', 'floor', 'ceiling', 'outside ground', 'skirting',
              'wainscot', 'chair rail', 'checker tile', 'wall skirting'}
R2 = lambda: __import__('os').environ.get('SETS_R2', '1') != '0'      # R149: head-height wall layer (SETS_R2=0 = round-1 look)
_FONT = dict(zip('ABCDEFGHIKLMNOPQRSTUVWYZ!', ('01110/10001/10001/11111/10001/10001/10001 11110/10001/10001/11110/10001/10001/11110 01110/10001/10000/10000/10000/10001/01110 '
    '11110/10001/10001/10001/10001/10001/11110 11111/10000/10000/11110/10000/10000/11111 11111/10000/10000/11110/10000/10000/10000 01110/10001/10000/10111/10001/10001/01111 '
    '10001/10001/10001/11111/10001/10001/10001 01110/00100/00100/00100/00100/00100/01110 10001/10010/10100/11000/10100/10010/10001 10000/10000/10000/10000/10000/10000/11111 '
    '10001/11011/10101/10101/10001/10001/10001 10001/11001/10101/10011/10001/10001/10001 01110/10001/10001/10001/10001/10001/01110 11110/10001/10001/11110/10000/10000/10000 '
    '01110/10001/10001/10001/10101/10010/01101 11110/10001/10001/11110/10100/10010/10001 01111/10000/10000/01110/00001/00001/11110 11111/00100/00100/00100/00100/00100/00100 '
    '10001/10001/10001/10001/10001/10001/01110 10001/10001/10001/10001/10001/01010/00100 10001/10001/10001/10101/10101/11011/10001 11111/00001/00010/00100/01000/10000/11111 '
    '00100/00100/00100/00100/00100/00000/00100').split()))
_TITLES = ['READ!', 'SCIENCE', 'MATH', 'ART', 'MUSIC', 'HISTORY', 'BE KIND', 'QUIZ', 'TEAM', 'GO!', 'LUNCH', 'WOW!']
_PAPER = ['#F28B6B', '#F2C94C', '#8FD4B0', '#F3E5B5', '#9CC8E8', '#F59CC0']
_SCHOOL = {'classroom', 'classroom2', 'school_hallway'}
_ROOM_DRESSING = {
    'living_room': ('picture', 'picture', 'shelf', 'lamp'),
    'bedroom': ('poster', 'picture', 'shelf', 'lamp'),
    'kitchen': ('shelf', 'tiles', 'shelf', 'lamp'),
    'store': ('sign', 'sign', 'shelf', 'lamp'),
    'hallway': ('sign', 'picture', 'lamp'),
    'bathroom': ('tiles', 'shelf', 'lamp'),
    'office': ('picture', 'shelf', 'lamp'),
    'room': ('picture', 'shelf', 'lamp'),
}
_PALETTE_FAMILIES = (  # wall, lower wall, floor, trim: quiet floors keep the cast dominant.
    ('#D9B785', '#9B7955', '#8D765F', '#F3E9D8'),  # honey
    ('#89B7DE', '#497AA5', '#697E95', '#E5EDF6'),  # blue
    ('#80C5C4', '#397F89', '#658486', '#E5F3F1'),  # teal
    ('#ABD1AE', '#5E9276', '#7A8975', '#EFF4E8'),  # sage
    ('#C0C8D5', '#78869C', '#737C8D', '#F1F3F8'),  # grey
    ('#EEF0E8', '#A1B8AC', '#89928B', '#FFFFFF'),  # white
)
_INTERIOR_PALETTE = dict(living_room=0, bedroom=1, kitchen=3, store=5, hallway=2,
                         bathroom=5, office=4, room=1, classroom=3, classroom2=1, school_hallway=4)


def interior_palette(spec):
    """Room family rotated by a stable story seed; explicit material choices always win."""
    preset = spec.get('preset', 'classroom')
    if preset not in _INTERIOR_PALETTE: return dict(spec)
    colors = _PALETTE_FAMILIES[(_INTERIOR_PALETTE[preset] + int(spec.get('seed', 0))) % len(_PALETTE_FAMILIES)]
    palette = dict(zip(('wall', 'wall_low', 'floor_color', 'trim'), colors))
    if preset in ('hallway', 'classroom2', 'school_hallway'): palette['floor'] = 'carpet'
    if 'wall' in spec:
        palette.pop('wall_low'); palette.pop('trim')
    return {**palette, **spec}


class _Dec:
    """One decor piece in WALL coordinates (u along the wall, d out from it, z up; metres). Geometry is bucketed per material
    (one mesh object per material) under a pivot empty that is registered in assets.PLACED."""
    def __init__(s, kind, side, plane, n):
        s.side, s.plane, s.name = side, plane, f'wd_{kind}_{n}'
        s.geo = {}; s.lo = [9e9] * 3; s.hi = [-9e9] * 3
        s.flip = side in ('front', 'right')       # u runs right-to-left for a viewer facing these walls: mirror text

    def w(s, u, d, z):                       # wall coords -> world
        p = s.plane
        return {'back': (u, p - d, z), 'front': (u, p + d, z), 'left': (p + d, u, z), 'right': (p - d, u, z)}[s.side]

    def poly(s, pts, m):
        v, f = s.geo.setdefault(m, ([], []))
        k = len(v)
        for q in pts:
            v.append(s.w(*q))
            for i in range(3): s.lo[i] = min(s.lo[i], q[i]); s.hi[i] = max(s.hi[i], q[i])
        f.append(tuple(range(k, k + len(pts))))

    def b(s, u, d, z, su, sd, sz, m):        # box centred at (u, d, z)
        x, y, h = su / 2, sd / 2, sz / 2
        c = [(u + a * x, d + b_ * y, z + c_ * h) for c_ in (-1, 1) for a, b_ in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)): s.poly([c[i] for i in q], m)

    def cyl(s, u, d, z, r, h, m, axis='d', n=14):   # axis 'd' = disc facing out of the wall, 'z' = upright pot
        ring = [(math.cos(i * math.tau / n), math.sin(i * math.tau / n)) for i in range(n)]
        if axis == 'd':
            lo = [(u + r * a, d - h / 2, z + r * c) for a, c in ring]; hi = [(u + r * a, d + h / 2, z + r * c) for a, c in ring]
        else:
            lo = [(u + r * a, d + r * c, z - h / 2) for a, c in ring]; hi = [(u + r * a, d + r * c, z + h / 2) for a, c in ring]
        for i in range(n):
            j = (i + 1) % n; s.poly([lo[i], lo[j], hi[j], hi[i]], m)
        s.poly(lo[::-1], m); s.poly(hi, m)

    def sph(s, u, d, z, r, m, n=10):
        rg = [[(u + r * math.sin(a) * math.cos(i * math.tau / n), d + r * math.sin(a) * math.sin(i * math.tau / n), z + r * math.cos(a)) for i in range(n)]
              for a in (math.pi * k / 6 for k in range(1, 6))]
        for k in range(4):
            for i in range(n): j = (i + 1) % n; s.poly([rg[k][i], rg[k][j], rg[k + 1][j], rg[k + 1][i]], m)
        for ring, top in ((rg[0], z + r), (rg[-1], z - r)):
            for i in range(n): j = (i + 1) % n; s.poly([ring[i], ring[j], (u, d, top)], m)

    def text(s, t, u, z, px, m, d=.05, th=.012):
        """Blocky 5x7 caps centred on u, bottom at z, pixel size px (m). Unknown characters are spaces."""
        g = -1 if s.flip else 1; u0 = u - g * (6 * len(t) - 1) * px / 2
        for k, ch in enumerate(t):
            rows = _FONT.get(ch, '00000/' * 6 + '00000').split('/')
            for r, row in enumerate(rows):
                c = 0
                while c < 5:
                    if row[c] == '1':
                        e = c
                        while e + 1 < 5 and row[e + 1] == '1': e += 1
                        s.b(u0 + g * ((6 * k + (c + e + 1) / 2) * px), d, z + (6.5 - r) * px, (e - c + 1) * px, th, px, m); c = e
                    c += 1

    def done(s):
        piv = bpy.data.objects.new(s.name, None); bpy.context.collection.objects.link(piv)
        for m, (v, f) in s.geo.items():
            d = bpy.data.meshes.new(s.name); d.from_pydata(v, [], f); d.update()
            o = bpy.data.objects.new(s.name + ' ' + m.name, d); bpy.context.collection.objects.link(o); o.parent = piv; d.materials.append(m)
        cs = [s.w(u, d, 0) for u in (s.lo[0], s.hi[0]) for d in (s.lo[1], s.hi[1])]
        return piv, (min(c[0] for c in cs), max(c[0] for c in cs), min(c[1] for c in cs), max(c[1] for c in cs)), s.hi[2]


def dress_walls(planes, H, windows=(), density=1.6, seed=0, zmin=1.75, curtains=True, corner_plants=True, room_type='room'):
    """Place wall-mounted decor on a rectangular room. planes = (xmin, xmax, ymin, ymax) of the INNER wall faces (m); H = ceiling (m);
    windows = [(side, u0, u1, z0, z1)] openings (m; doors have z0 = 0); density scales the count. Everything is flush (<= 0.25 m off
    the wall) and registered NON-solid in assets.PLACED, so routing and the body gate are unchanged; the small corner plants stick out
    further and are registered solid. Free space = scene meshes near each wall (furniture, existing posters) + openings. Seeded."""
    import assets, rooms
    rng = random.Random(seed); mm = rooms.mat; school = room_type in _SCHOOL
    x0, x1, y0, y1 = planes; ztop = H - .5; r2 = R2()
    if r2: zmin = 1.0                                                  # R149 head-height band 1.0-2.6 m (bunting / curtains still use ztop)
    zband = min(ztop, 2.6) if r2 else ztop
    if ztop - zmin < 1.2 or density <= 0: return 0
    bpy.context.view_layer.update()
    boxes = []                                                  # world AABBs (x0, x1, y0, y1, z0, z1) of every set mesh
    for o in bpy.context.scene.objects:
        if o.type != 'MESH' or o.hide_render or o.name.split('.')[0].lower() in _WALLNAMES: continue
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        boxes.append((min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts), min(p.z for p in pts), max(p.z for p in pts)))
    for s, u0, u1, z0, z1 in windows:                           # doors reserve a 1 m deep floor patch (swing / corner plants)
        if z0 == 0:
            boxes.append({'back': (u0, u1, y1 - 1, y1), 'front': (u0, u1, y0, y0 + 1), 'left': (x0, x0 + 1, u0, u1), 'right': (x1 - 1, x1, u0, u1)}[s] + (0, H))
    plane = {'back': y1, 'front': y0, 'left': x0, 'right': x1}
    span = {'back': (x0, x1), 'front': (x0, x1), 'left': (y0, y1), 'right': (y0, y1)}
    occ = {s: [] for s in plane}                                # what already hangs/stands at each wall: (u0, u1, z0, z1)
    for s in plane:
        for bx in boxes:
            d0, d1 = {'back': (y1 - bx[3], y1 - bx[2]), 'front': (bx[2] - y0, bx[3] - y0), 'left': (bx[0] - x0, bx[1] - x0),
                      'right': (x1 - bx[1], x1 - bx[0])}[s]
            if d0 < .35 and d1 > -.05:
                u = (bx[0], bx[1]) if s in ('back', 'front') else (bx[2], bx[3]); occ[s].append((u[0], u[1], bx[4], bx[5]))
    for s, u0, u1, z0, z1 in windows: occ[s].append((u0 - .5, u1 + .5, z0 - .1, z1 + .15 if z0 > 0 else H))
    n = [0]; placed = []

    def free(s, u0, u1, z0, z1, mg=.18, zlo=None):
        return not any(u0 - mg < b[1] and u1 + mg > b[0] and z0 - mg < b[3] and z1 + mg > b[2] for b in occ[s]) and \
            u0 > span[s][0] + .25 and u1 < span[s][1] - .25 and z0 >= (zmin if zlo is None else zlo) - .01 and z1 <= ztop

    def find(s, w, h, fr, mg=.18):
        for _ in range(60 if not r2 else 25):
            if span[s][1] - span[s][0] < w + .8: return None
            u = rng.uniform(span[s][0] + w / 2 + .3, span[s][1] - w / 2 - .3)
            zc = rng.uniform(zmin + h / 2, zband - h / 2) if r2 else zmin + (ztop - zmin) * rng.uniform(*fr)   # r2: anywhere inside the band
            if free(s, u - w / 2, u + w / 2, zc - h / 2, zc + h / 2, mg): return u, zc
        return None

    def new(kind, s): n[0] += 1; return _Dec(kind, s, plane[s], n[0])

    def fin(dc, s, solid=False):
        piv, rect, top = dc.done(); assets.PLACED.append({'name': dc.name, 'pivot': piv, 'rect': rect, 'top': top, 'solid': solid})
        occ[s].append((dc.lo[0], dc.hi[0], dc.lo[2], dc.hi[2])); placed.append(dc.name)

    wood, dark, cork, white = mm('wd wood', '#6B4423', .7), mm('wd dark', '#2A2A33', .6), mm('wd cork', '#C48A52', 1), mm('wd white', '#F5F1E6', .8)
    pin, gold, lg = mm('wd pin', '#D63A2F', .5), mm('wd gold', '#F0B323', .35), mm('wd leaf', '#2E9B4E', .7)
    sun = mm('wd sun', '#FFD84D', .6)
    pal = [mm('wd c' + c, c, .75) for c in ('#E63946', '#2A9D8F', '#F4A261', '#457B9D', '#8AC926', '#FF70A6', '#6A4C93', '#FFC933')]

    def cork_board(s, u, zc):
        w, h = (rng.uniform(1.5, 2.5), rng.uniform(1.0, 1.4)) if r2 else (rng.uniform(1.7, 2.3), rng.uniform(1.1, 1.4)); dc = new('cork', s)
        dc.b(u, .04, zc, w, .08, h, wood); dc.b(u, .085, zc, w - .16, .03, h - .16, cork)
        cols = int((w - .3) / .46); rows = 2 if h > 1.2 or (r2 and h > 1.0) else 1
        for r in range(rows):
            for c in range(cols):
                if rng.random() < .1: continue
                pu = u - (cols - 1) * .23 + c * .46 + rng.uniform(-.04, .04)
                pz = zc + ((.26 if r == 0 else -.26) if rows == 2 else 0) + rng.uniform(-.03, .03); pc = rng.choice(_PAPER)
                dc.b(pu, .104, pz, .34, .012, .28, mm('wd paper' + pc, pc, .9))
                for k in (-.03, .02): dc.b(pu, .112, pz + k, .22, .004, .02, dark)
                dc.b(pu, .108, pz + .11, .045, .02, .045, pin)
        return dc

    def poster(s, u, zc):
        w, h = (rng.uniform(.9, 1.25), rng.uniform(1.3, 1.65)) if r2 else (rng.uniform(.8, 1.1), rng.uniform(1.1, 1.5)); v = rng.randrange(3); dc = new('poster', s)
        bg = rng.choice(pal); dc.b(u, .02, zc, w, .04, h, bg); fg = rng.choice([p for p in pal if p != bg])
        if r2:                                                     # bold procedural title + a simple shape, no images
            t = rng.choice(_TITLES if school else ('DREAM', 'SPACE', 'STARS')); px = min(w * .86 / (6 * len(t) - 1), h * .17 / 7)
            dc.text(t, u, zc + h * .22, px, dark if bg in (pal[2], pal[7]) else white)
            if v == 1: dc.b(u, .05, zc - h * .12, w * .55, .02, h * .26, fg)
            else: dc.cyl(u, .05, zc - h * .12, w * .24, .02, sun if v else white)
            dc.b(u, .052, zc - h * .38, w * .55, .02, h * .05, white)
            return dc
        if v == 0:
            dc.cyl(u + w * .15, .05, zc + h * .2, w * .2, .02, sun); dc.b(u, .05, zc - h * .28, w * .9, .02, h * .3, fg)
            dc.poly([(u - w * .4, .052, zc - h * .13), (u - w * .05, .052, zc - h * .13), (u - w * .22, .052, zc + h * .02)], white)
        elif v == 1:
            for i in range(3): dc.b(u, .05, zc + (i - 1) * h * .27, w * .8, .02, h * .17, fg if i % 2 == 0 else white)
        else:
            dc.cyl(u, .05, zc + h * .1, w * .32, .02, white); dc.cyl(u, .065, zc + h * .1, w * .17, .02, fg)
        dc.b(u, .052, zc - h * .4, w * .6, .02, h * .07, white)
        return dc

    def picture(s, u, zc):
        w, h = rng.uniform(.8, 1.25), rng.uniform(.6, .9); dc = new('frame', s)
        dc.b(u, .03, zc, w, .06, h, rng.choice([wood, dark, white])); dc.b(u, .062, zc, w - .14, .02, h - .14, mm('wd sky', '#8CC9EE', .8))
        dc.b(u, .066, zc - h * .2, w - .14, .02, h * .22, mm('wd hill', '#5DAA3C', .8)); dc.cyl(u + w * .22, .07, zc + h * .12, h * .1, .02, sun)
        return dc

    def clock(s, u, zc):
        dc = new('clock', s); dc.cyl(u, .04, zc, .42, .08, dark); dc.cyl(u, .085, zc, .37, .03, white)
        for a in range(12):
            t = a * math.tau / 12; dc.b(u + .31 * math.sin(t), .102, zc + .31 * math.cos(t), .03, .01, .07 if a % 3 == 0 else .035, dark)
        for ang, ln, wd in ((rng.uniform(0, 6.28), .22, .028), (rng.uniform(0, 6.28), .31, .018)):
            ca, sa = math.cos(ang), math.sin(ang)
            dc.poly([(u - wd * ca, .108, zc + wd * sa), (u + wd * ca, .108, zc - wd * sa), (u + wd * ca + ln * sa, .108, zc - wd * sa + ln * ca),
                     (u - wd * ca + ln * sa, .108, zc + wd * sa + ln * ca)], dark)
        return dc

    def shelf(s, u, zc):
        w = rng.uniform(1.2, 2.0); dc = new('shelf', s); tiers = 2 if (ztop - zc > 1.0 and rng.random() < .45) else 1
        if not school: w = min(w, 1.6); tiers = 1
        for t in range(tiers):
            z = zc + t * .75 - (.3 if tiers == 2 else 0)
            dc.b(u, .06 if r2 else .115, z, w, .12 if r2 else .23, .05, wood)
            for e in (-1, 1): dc.b(u + e * w * .38, .05, z - .09, .04, .09, .14, wood)
            cur = u - w / 2 + .1
            while cur < u + w / 2 - .15:
                k = rng.random()
                if room_type in ('kitchen', 'bathroom', 'store'):
                    dc.cyl(cur + .07, .08, z + .16, .065, .26, rng.choice(pal), 'z')
                    dc.cyl(cur + .07, .08, z + .30, .07, .035, gold if room_type == 'kitchen' else white, 'z')
                    dc.b(cur + .07, .146, z + .16, .08, .012, .10, white)
                    cur += .22; continue
                if k < .62:                                   # a run of books
                    for _ in range(rng.randint(3, 6)):
                        bw = rng.uniform(.045, .09)
                        if cur + bw > u + w / 2 - .06: break
                        bh = rng.uniform(.2, .34); dc.b(cur + bw / 2, .06 if r2 else .105, z + .025 + bh / 2, bw, .1 if r2 else .16, bh, rng.choice(pal)); cur += bw + .004
                    cur += .02
                elif k < .8:                                  # potted plant
                    cy, cr = (.06, .045) if r2 else (.11, .07)
                    dc.cyl(cur + .1, cy, z + .12, .05 if r2 else .08, .16, rng.choice(pal), 'z')
                    for a in range(5):
                        t2 = a * 1.3; px, py = cur + .1 + cr * math.cos(t2), cy + cr * math.sin(t2)
                        dc.poly([(cur + .1, cy, z + .2), (px + .05, py, z + .38), (px - .04, py, z + .3)], lg)
                    cur += .26
                elif school and r2 and k < .86:                # globe on a stand
                    dc.cyl(cur + .1, .07, z + .04, .045, .03, dark, 'z'); dc.cyl(cur + .1, .07, z + .09, .012, .1, dark, 'z')
                    dc.sph(cur + .1, .08, z + .21, .08, mm('wd globe', '#2E86C1', .4)); cur += .24
                elif school and k < .9:                        # trophy
                    dc.cyl(cur + .08, .11, z + .05, .07, .05, dark, 'z'); dc.cyl(cur + .08, .11, z + .14, .018, .14, gold, 'z')
                    dc.cyl(cur + .08, .11, z + .26, .07, .12, gold, 'z'); cur += .2
                else:                                         # jar
                    dc.cyl(cur + .07, .11, z + .09, .06, .14, mm('wd jar', '#BDE3F2', .3), 'z'); cur += .17
        return dc

    def lamp(s, u, zc):
        dc = new('lamp', s); dc.b(u, .015, zc, .14, .03, .22, dark); dc.b(u, .05, zc - .04, .05, .08, .05, dark)
        dc.cyl(u, .06 if r2 else .09, zc + .02, .055 if r2 else .09, .12 if r2 else .2, mm('wd lamp', '#FFE2A8', .5, 3.0), 'z')
        return dc

    def sign(s, u, zc):
        dc = new('sign', s)
        t = rng.choice(('FRESH', 'SALE', 'OPEN')) if room_type == 'store' else 'EXIT'
        dc.b(u, .04, zc, 1.6, .08, .55, pal[1] if room_type == 'hallway' else pal[0])
        dc.text(t, u, zc - .16, min(1.4 / (6 * len(t) - 1), .045), white, d=.09)
        return dc

    def tiles(s, u, zc):
        dc = new('tiles', s); dc.b(u, .02, zc, 1.6, .04, .8, white)
        for i in range(8):
            for j in range(4):
                dc.b(u - .7 + i * .2, .045, zc - .3 + j * .2, .19, .012, .19,
                     pal[1] if (i + j) % 3 else pal[3])
        return dc

    kinds2 = [(cork_board, 2.0, 1.2, 0), (cork_board, 2.0, 1.2, 0), (poster, 1.1, 1.5, 0), (poster, 1.1, 1.5, 0), (shelf, 1.6, .7, 0), (shelf, 1.6, .7, 0),
              (picture, 1.0, .8, 0), (cork_board, 1.6, 1.0, 0), (lamp, .3, .3, 0)]
    kinds = [(cork_board, 2.3, 1.4, (.1, .75)), (poster, 1.1, 1.5, (.1, .85)), (poster, 1.1, 1.5, (.1, .85)), (picture, 1.25, .9, (.1, .85)),
             (cork_board, 2.3, 1.4, (.1, .75)), (shelf, 2.0, .6, (.0, .75)), (shelf, 2.0, .6, (.0, .75)), (lamp, .3, .3, (.1, .8))]
    if not school:
        pieces = {'poster': (poster, 1.25, 1.65), 'picture': (picture, 1.25, .9),
                  'shelf': (shelf, 1.6, .7), 'lamp': (lamp, .3, .3), 'sign': (sign, 1.6, .55), 'tiles': (tiles, 1.6, .8)}
        kinds2 = [(*pieces[k], 0) for k in _ROOM_DRESSING.get(room_type, _ROOM_DRESSING['room'])]
        kinds = [(*p[:3], (.1, .8)) for p in kinds2]
    def aquarium(s, u):
        w = 1.3; dc = new('aquarium', s); water = mm('wd water', '#5CC8D8', .1); dk2 = mm('wd cabinet', '#7A4A28', .6)
        water.node_tree.nodes['Principled BSDF'].inputs['Alpha'].default_value = .4
        dc.b(u, .25, .35, w, .5, .7, dk2); dc.b(u, .25, .5, w - .1, .46, .02, dark)
        dc.b(u, .22, .78, w - .06, .42, .06, dark); dc.b(u, .22, 1.3, w - .06, .42, .04, dark)      # tank base + lid
        for e in (-1, 1): dc.b(u + e * (w / 2 - .06), .22, 1.04, .04, .42, .46, dark)               # corner posts
        dc.b(u, .22, 1.04, w - .14, .36, .46, water); dc.b(u, .22, .83, w - .14, .36, .05, mm('wd gravel', '#D9B77E', .9))
        for k in range(3):
            fx = u - .4 + k * .4 + rng.uniform(-.08, .08); fz = 1.0 + rng.uniform(-.06, .14)
            dc.sph(fx, .22, fz, .045, mm('wd fish', '#FF7A1A', .4)); dc.poly([(fx + .03, .22, fz), (fx + .11, .22, fz + .05), (fx + .11, .22, fz - .05)], mm('wd fish', '#FF7A1A', .4))
            dc.poly([(fx + .25, .22, .86), (fx + .22, .22, 1.12), (fx + .29, .22, 1.0)], lg)
        return dc

    if school and r2 and rng.random() < .55 and not os.environ.get('SETS_AQ') == '0':  # aquarium only in schools
        for s in rng.sample(list(plane), 4):
            if span[s][1] - span[s][0] < 4: continue
            for _ in range(20):
                u = rng.uniform(span[s][0] + 1.2, span[s][1] - 1.2)
                rc = {'back': (u - .75, u + .75, y1 - .75, y1), 'front': (u - .75, u + .75, y0, y0 + .75), 'left': (x0, x0 + .75, u - .75, u + .75),
                      'right': (x1 - .75, x1, u - .75, u + .75)}[s]
                if free(s, u - .65, u + .65, 0, 1.4, .1, zlo=0) and not any(b[0] < rc[1] and b[1] > rc[0] and b[2] < rc[3] and b[3] > rc[2] and b[4] < 1.5 for b in boxes):
                    fin(aquarium(s, u), s, True); break
            else: continue
            break
    for s in ('back', 'left', 'right', 'front'):
        L = span[s][1] - span[s][0]; goal = round(density * L / 2.6 * (1.25 if s == 'back' else 1.0))
        if r2:                                                  # R149: fill ~50-70 % of the free 1.0-2.6 m band, boards first
            cells = sum(free(s, u, u + .2, z, z + .2, 0) for u in [span[s][0] + .25 + .2 * i for i in range(int(max(L - .9, 0) / .2))]
                        for z in (zmin + .2 * j for j in range(int((zband - zmin) / .2))))
            target = rng.uniform(.5, .7) * cells * .04; cover = 0.; tries = 0
            if (s == 'back' or rng.random() < .35) and not any(q.startswith('wd_clock') for q in placed):
                r = find(s, .9, .9, 0, .08)
                if r: fin(clock(s, *r), s); cover += .8
            while cover < target and tries < 90:
                tries += 1
                fn, w, h, fr = rng.choice(kinds2 if tries > 3 else kinds2[:2])
                if fn is lamp and sum(p.startswith('wd_lamp') for p in placed) >= 2: continue
                r = find(s, w, h, fr, .08)
                if r: fin(fn(s, *r), s); o = occ[s][-1]; cover += (o[1] - o[0]) * (o[3] - o[2])
        else:
            if (s == 'back' or rng.random() < .35) and not any(p.startswith('wd_clock') for p in placed):
                r = find(s, .9, .9, (.5, 1.0))
                if r: fin(clock(s, *r), s)
            got = 0
            for _ in range(goal * 3):
                if got >= goal: break
                fn, w, h, fr = rng.choice(kinds)
                if fn is lamp and sum(p.startswith('wd_lamp') for p in placed) >= 2: continue
                r = find(s, w, h, fr)
                if r: fin(fn(s, *r), s); got += 1
        if school and rng.random() < (.6 if r2 else .5) and H > (3.2 if r2 else 4.2):            # school bunting
            a, c = span[s][0] + .4, span[s][1] - .4; zt = min(H - .25, 3.1) if r2 else H - .25
            if c - a > 3 and not any(b[2] < zt + .05 and b[3] > zt - .4 and b[1] > a and b[0] < c for b in occ[s]):
                dc = new('bunting', s); cols = [mm('wd bunt' + str(i), x, .8) for i, x in enumerate(('#E63946', '#F4C430', '#2A9D8F', '#FF70A6', '#457B9D'))]
                k = int((c - a) / .42); step = (c - a) / k
                dc.b((a + c) / 2, .02, zt + .02, c - a, .012, .012, white)
                for i in range(k):
                    ua = a + i * step; dc.poly([(ua, .02, zt), (ua + step * .92, .02, zt), (ua + step * .46, .02, zt - .34)], cols[i % 5])
                fin(dc, s)
    if curtains:
        for s, u0, u1, z0, z1 in windows:
            if z0 <= 0 or z1 - z0 < .8: continue
            ci = len(placed) % 4; cm = mm('wd curtain%d' % ci, ('#E8836B', '#6FB1D6', '#F2C94C', '#9BC88B')[ci], .9)
            for e, (a, c) in enumerate(((u0 - .75, u0 - .2), (u1 + .2, u1 + .75))):
                zb, zt = z0 - .15, min(z1 + .3, ztop)
                if not free(s, a, c, zb, zt, 0): continue
                dc = new('curtain', s); dc.b((a + c) / 2, .06 if r2 else .08, (zb + zt) / 2, c - a, .08 if r2 else .1, zt - zb, cm)
                if e == 0: dc.b((u0 + u1) / 2, .05, zt + .04, u1 - u0 + 1.6, .04, .05, wood)
                fin(dc, s)
    if corner_plants:
        for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            if rng.random() < .3: continue
            sx, sy = (1 if cx == x0 else -1), (1 if cy == y0 else -1); px, py = cx + sx * .3, cy + sy * .3
            rx, ry = sorted((cx, cx + sx * .9)), sorted((cy, cy + sy * .9))
            if any(b[0] < rx[1] and b[1] > rx[0] and b[2] < ry[1] and b[3] > ry[0] and b[5] > .15 for b in boxes): continue
            n[0] += 1; dc = _Dec('plant', 'back', 0, n[0]); dc.w = lambda u, d, z: (u, d, z)      # these are in world coordinates
            dc.cyl(px, py, .17, .17, .3, rng.choice(pal), 'z')
            for a in range(9):
                t2 = a * .7; ox, oy = px + .13 * math.cos(t2), py + .13 * math.sin(t2); h2 = .75 + .35 * rng.random()
                dc.poly([(px, py, .3), (ox + .09, oy, h2), (ox - .08, oy + .05, h2 - .12)], lg)
            piv, _, top = dc.done(); assets.PLACED.append({'name': dc.name, 'pivot': piv, 'rect': (px - .2, px + .2, py - .2, py + .2), 'top': top, 'solid': True})
            placed.append(dc.name)
    return len(placed)


_HILLS = {'wasteland': ('#C4A783', '#D4BE9A'), 'forest': ('#3E7F46', '#6FA58A')}   # (near, far) hill colours per preset, default grass


def _outdoor(preset, info):
    """R152 outdoor depth: far-ground disk (no hard ground edge), 2 hill rings (far one hazed toward the sky), a tree line, and edge dressing
    (lamps/fences/bushes/trees) kept off the acting area (|x| < 17 and -14 < y < 16 studs stay clear; camera side only gets far trees). All backdrop is non-solid + unregistered."""
    import rooms, assets
    rng = random.Random(31 + len(preset)); t = info.get('time', 'day'); W, D = info['W'], info['D']; M = 0.5
    tint = {'day': (1, 1, 1), 'sunset': (1.0, .72, .62), 'night': (.1, .13, .3)}.get(t, (1, 1, 1))
    def col(h, haze=0.0):
        c = [int(h.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4)]; sky = (.62, .76, .92) if t == 'day' else tint
        c = [(c[i] * (1 - haze) + sky[i] * haze) * (tint[i] if t != 'day' else 1) for i in range(3)]
        return '#%02X%02X%02X' % tuple(int(min(1, v) * 255) for v in c)
    near, far = _HILLS.get(preset, ('#5E9E4A', '#7FB19A'))
    ground = {'wasteland': '#D6BC90', 'city': '#7C8B6A'}.get(preset, '#6AA848')
    d = rooms.box('far ground', (0, 0, -0.06), (3000, 3000, 0.04), rooms.mat('far ground ' + col(ground), col(ground), 0.9))
    for ring, (r0, r1, n, hh, c, haze) in enumerate(((190, 230, 18, (22, 40), far, 0.55), (115, 150, 22, (10, 22), near, 0.2))):
        for i in range(n):
            a = 2 * math.pi * (i + rng.uniform(-.3, .3)) / n; r = rng.uniform(r0, r1); w = rng.uniform(40, 70); h = rng.uniform(*hh)
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1, location=(r * math.cos(a) * M, r * math.sin(a) * M, 0))
            o = bpy.context.object; o.name = f'VFX hill {ring}.{i}'; o.scale = (w * M, w * M * .6, h * M); o.rotation_euler = (0, 0, a + 1.57)
            o.data.materials.append(rooms.mat('hill ' + c + t + str(ring), col(c, haze), 0.95)); o.data.polygons.foreach_set('use_smooth', [False] * len(o.data.polygons))
            o.visible_shadow = False
    trees = ['tree_default', 'tree_blocks', 'tree_cone'] if preset != 'wasteland' else ['cactus_tall', 'rock_tallA']
    if preset in ('park', 'forest', 'street', 'city'):    # tree line between the play area and the hills, plus a few far houses/skyline
        for i in range(34):
            a = 2 * math.pi * i / 34 + rng.uniform(-.05, .05); r = rng.uniform(78, 100)
            assets.place(rng.choice(trees), (r * math.cos(a), r * math.sin(a) * .85), rot=rng.uniform(0, 360), scale=rng.uniform(2.4, 3.6), solid=False, register=False)
    if preset in ('street', 'park'):
        types = 'abcdefghijklmnopqrstu'
        for i in range(10):
            x = -90 + i * 20 + rng.uniform(-4, 4); y = 66 + rng.uniform(0, 14)
            assets.place(f'city-kit-suburban/building-type-{types[(i * 5 + 3) % 21]}', (x, y), rot=180, scale=1.5 + rng.uniform(0, .4), solid=False, register=False)
    if preset == 'city':
        for i in range(12):
            x = -110 + i * 20 + rng.uniform(-3, 3); y = 85 + rng.uniform(0, 25)
            assets.place('city-kit-commercial/building-skyscraper-' + 'abcde'[i % 5], (x, y), rot=0, scale=rng.uniform(1.4, 2.4), solid=False, register=False)
    lamps = info.setdefault('lamps', [])
    def lamp(x, y, rot=180):
        assets.place('retro-urban-kit/detail-light-single', (x, y), rot=rot)
        q = assets.PLACED[-1]; lamps.append(((q['rect'][0] + q['rect'][1]) / 2, (q['rect'][2] + q['rect'][3]) / 2, q['top'] - 0.25))
    if preset == 'park':      # mid layer: lamps along the path edge, fence rows + bushes + big trees on the flanks and behind
        for x, y in ((-9, 18), (9, 18), (-20, 6), (20, 6)): lamp(x, y)
        for side in (-1, 1):
            for k in range(8):
                assets.place('city-kit-suburban/fence-1x4', (side * (W / 2 - 1), -14 + k * 5.5), rot=90, scale=1.3, solid=False)
            for y in (0, 10, 22):
                assets.place('tree_default', (side * rng.uniform(19, 24), y + rng.uniform(-2, 2)), scale=rng.uniform(1.8, 2.3), rot=rng.uniform(0, 360))
                assets.place('plant_bushLarge', (side * rng.uniform(18, 26), y + 5), scale=1.5, solid=False)
        for x in range(-30, 31, 10):      # back border: hedge line + trees
            assets.place('plant_bushLarge', (x, D / 2 - 1), scale=1.8, solid=False)
            if x % 20 == 0: assets.place('tree_blocks', (x + 3, D / 2 + 3), scale=2.2, rot=rng.uniform(0, 360))
        for x in (-28, 28):               # rear-camera side: only far, non-blocking green
            assets.place('plant_bushLarge', (x, -D / 2 + 2), scale=1.8, solid=False)
    elif preset in ('street', 'city'):
        for x in (-34, 34): lamp(x, 1.5 if preset == 'street' else 6.5)
    elif preset == 'forest':
        for i in range(10):
            a = rng.uniform(0, 2 * math.pi); r = rng.uniform(40, 56)
            assets.place(rng.choice(trees), (r * math.cos(a), r * math.sin(a) + 8), scale=rng.uniform(2.2, 3.0), solid=False, register=False)


def _dress_set(preset, info=None, K_=1.0):
    """Hook used by build(): wall decor for an interior preset (info from rooms.build, or None for the cook20 classroom)."""
    import os, zlib
    if os.environ.get('SETS_DRESS', '1') == '0': return 0
    seed = zlib.crc32(preset.encode())
    if info is None:       # classroom: inner faces of the cook20 walls x K, ceiling underside
        return dress_walls((-6.9 * K, 6.9 * K, -11.99 * K, 6.09 * K), 6.82 * K, seed=seed, zmin=1.35, curtains=False, room_type=preset)
    if info.get('outdoor'): return 0
    if preset == 'kitchen':
        import assets
        counter = next((p for p in assets.PLACED if p['name'] == 'counter'), None)
        if counter:
            x0, x1, y0, y1, top = assets.support(counter['name'])
            for asset, x in (('food-kit/honey', x0 + (x1-x0)*.3), ('food-kit/bottle-oil', x0 + (x1-x0)*.7)):
                e = assets.find(asset)
                scale = .28 / (max(e['size_x'], e['size_y'], e['size_z']) * assets.KIT_SCALE[e['kit']])
                assets.place(asset, (x / assets.S, (y0+y1) / (2*assets.S)), z=top / assets.S,
                             scale=scale, solid=False, label='kitchen ' + e['file'][:-4])
    S_ = 0.5; ws = []
    for side, ops in info['windows'].items():
        for u, w, sill, h in ops: ws.append((side, (u - w / 2) * S_, (u + w / 2) * S_, sill * S_, (sill + h) * S_))
    return dress_walls(info['bounds'], info['H'] * S_, ws, seed=seed, room_type=preset,
                       curtains=preset in ('living_room', 'bedroom', 'room'))


# ---------------- imported Roblox sets (tools/rbx_set_import.py) ----------------
def rbx_dir(id_or_tag):
    """assets/rbxsets/<id>_<slug> by full id, bare id, slug or any substring (first match)."""
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'rbxsets')
    ds = sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, 'scene.json')))
    key = str(id_or_tag).lower()
    hit = [d for d in ds if d.split('_', 1)[0] == key] or [d for d in ds if key in d.lower()]
    if not hit: raise KeyError(f'no imported Roblox set {id_or_tag!r}; have {ds}')
    return os.path.join(root, hit[0])


def rbx_set(id_or_tag, at=(0, 0), rot=0.0, scale=1.0, spec=None):
    """Place an imported Roblox Creator Store set (footprint centre at `at` studs, floor z = 0, rotated `rot` deg about Z). Solid clusters are
    registered in assets.PLACED (names '<slug>_<group>_<k>'). Returns the same dict as build(): supports/obstacles/bounds/info."""
    import sys, json, assets
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools'))
    import rbx_set_import as ri
    spec = spec or {}
    d = rbx_dir(id_or_tag); r = ri.build(d, at, rot, scale, ground=spec.get('ground'))
    x0, x1, y0, y1 = r['bounds']; hgt = r['size_m'][2] / S
    info = {'bounds': r['bounds'], 'windows': {}, 'W': (x1 - x0) / S, 'D': (y1 - y0) / S, 'H': min(max(hgt, 8), 14), 'time': spec.get('time', 'day'),
            'outdoor': bool(spec.get('outdoor', False)), 'spec': spec, 'lights': r['lights'], 'counts': r['counts']}
    obs = assets.obstacles()
    return {'supports': obs, 'desk_tops': [], 'root': r['root'], 'bounds': r['bounds'], 'obstacles': obs, 'info': info}
