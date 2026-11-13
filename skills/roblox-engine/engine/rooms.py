"""rooms.py - generic sets for ANY story: interiors (shell with real window/door holes + Kenney furniture + wall decor) and
exteriors (ground, roads, houses, trees). All spec units are STUDS; the room is centred on the origin, camera side = -Y (front).
spec = {'preset': 'living_room' | 'bedroom' | 'kitchen' | 'store' | 'hallway' | 'room' | 'street' | 'park',
        'size': [W, D], 'height': H, 'wall': '#hex', 'floor': 'wood'|'checker'|'tile'|'carpet'|'grass'|'asphalt', 'floor_color': '#hex',
        'windows': [[wall, u, width, height, sill]], 'doors': [[wall, u, width]], 'dress': [{'asset': name, 'at': [x, y], 'rot': deg,
        'name': label, 'z': studs, 'scale': k}], 'decor': true, 'time': 'day'|'evening'|'night'}
Walls: 'back' (+Y), 'front' (-Y), 'left' (-X), 'right' (+X); u = position along the wall (studs from its centre).
Preset values are defaults; any key in the story's spec overrides them, and 'dress' entries are ADDED to the preset's."""
import math, random
import bpy
from mathutils import Vector
import assets

S = 0.5
M = {}


def hexrgb(h):
    h = h.lstrip('#'); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c)


def mat(name, col, rough=0.7, emit=0.0):
    if name in M: return M[name]
    m = bpy.data.materials.new(name); m.use_nodes = True; rgb = hexrgb(col) if isinstance(col, str) else col
    b = m.node_tree.nodes['Principled BSDF']; b.inputs['Base Color'].default_value = (*rgb, 1); b.inputs['Roughness'].default_value = rough
    m.diffuse_color = (*rgb, 1)
    if emit: b.inputs['Emission Color'].default_value = (*rgb, 1); b.inputs['Emission Strength'].default_value = emit
    M[name] = m; return m


def pattern_mat(name, kind, c1, c2, scale):
    """Floor patterns: checker (two colours) or planks (brick texture as boards)."""
    if name in M: return M[name]
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; b = nt.nodes['Principled BSDF']
    b.inputs['Roughness'].default_value = 0.55 if kind == 'checker' else 0.65
    tc = nt.nodes.new('ShaderNodeTexCoord')
    if kind == 'checker':
        t = nt.nodes.new('ShaderNodeTexChecker'); t.inputs['Scale'].default_value = scale
    else:
        t = nt.nodes.new('ShaderNodeTexBrick'); t.inputs['Scale'].default_value = scale; t.inputs['Mortar Size'].default_value = 0.004
        t.inputs['Mortar'].default_value = (*[v * 0.6 for v in hexrgb(c2)], 1); t.offset = 0.5; t.squash = 1.0
        t.inputs['Brick Width'].default_value = 1.6; t.inputs['Row Height'].default_value = 0.2
    nt.links.new(tc.outputs['Object'], t.inputs['Vector'])
    t.inputs['Color1'].default_value = (*hexrgb(c1), 1); t.inputs['Color2'].default_value = (*hexrgb(c2), 1)
    nt.links.new(t.outputs['Color'], b.inputs['Base Color']); m.diffuse_color = (*hexrgb(c1), 1)
    M[name] = m; return m


def box(name, c, size, material, parent=None):
    """c = centre (x, y, z) metres, size metres."""
    d = bpy.data.meshes.new(name); x, y, z = (s / 2 for s in size)
    v = [(-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z), (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z)]
    d.from_pydata(v, [], [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]); d.update()
    o = bpy.data.objects.new(name, d); bpy.context.collection.objects.link(o); o.location = c; d.materials.append(material)
    if parent: o.parent = parent
    return o


FLOORS = {'wood': ('planks', '#A0683A', '#8A5530', 0.9), 'checker': ('checker', '#2E3A55', '#C9CED6', 0.5),
          'tile': ('checker', '#F2F0E8', '#8FA9C9', 1.2), 'carpet': ('flat', '#7A8FB8', None, 0),
          'grass': ('flat', '#5DAA3C', None, 0), 'asphalt': ('flat', '#4A4D52', None, 0),
          'sand': ('flat', '#D6BC90', None, 0)}   # R-look2: paler sand (was #C9A46A) so the cast separates

PRESETS = {'living_room': {'size': [30, 24],
                 'height': 11,
                 'wall': '#E9C88A',
                 'floor': 'wood',
                 'windows': [['back', -7, 8, 6, 3], ['right', 2, 7, 6, 3]],
                 'doors': [['left', -4, 5]],
                 'dress': [{'asset': 'loungeSofaLong', 'at': [-1, 8.5], 'rot': 0, 'name': 'sofa'},
                           {'asset': 'pillowBlue', 'at': [-3, 8.6], 'z': 1.0, 'solid': False},
                           {'asset': 'pillow', 'at': [1, 8.6], 'z': 1.0, 'solid': False},
                           {'asset': 'tableCoffee', 'at': [-1, 1.6], 'name': 'coffee table'},   # 0.4 m further from the sofa: a 1.0 m gap was too tight for R6 side-steps (R150)
                           {'asset': 'rugRectangle', 'at': [-1, 3], 'solid': False},
                           {'row': [{'asset': 'cabinetTelevision', 'name': 'tv stand'}], 'wall': 'front', 'start': -2},
                              {'asset': 'televisionModern', 'at': [0.4, -10.8], 'z': 2.2, 'rot': 180, 'name': 'tv', 'solid': False},
                           {'asset': 'loungeChair', 'at': [9, 4], 'rot': -90, 'name': 'armchair'},
                           {'asset': 'sideTable', 'at': [11.5, 8], 'name': 'side table'},
                           {'asset': 'lampRoundTable', 'at': [11.5, 8], 'z': 1.5, 'solid': False},
                           {'asset': 'lampRoundFloor', 'at': [-11, 9.5]},
                           {'asset': 'pottedPlant', 'at': [13, 10]},
                           {'row': ['bookcaseOpen', {'asset': 'bookcaseClosedWide', 'name': 'bookcase'}], 'wall': 'left', 'start': 2},
                           {'asset': 'speaker', 'at': [-12.5, -9]},
                           {'asset': 'plantSmall1', 'at': [-1, 2.4], 'z': 1.25, 'solid': False}]},
 'bedroom': {'size': [26, 22],
             'height': 11,
             'wall': '#9FC6E8',
             'floor': 'wood',
             'windows': [['back', 6, 7, 6, 3]],
             'doors': [['left', 4, 5]],
             'dress': [{'asset': 'bedSingle', 'at': [-6, 6], 'rot': 0, 'name': 'bed'},
                       {'asset': 'cabinetBedDrawerTable', 'at': [-1.8, 9], 'name': 'nightstand'},
                       {'asset': 'lampRoundTable', 'at': [-1.8, 9], 'z': 1.55, 'solid': False},
                       {'asset': 'desk', 'at': [9, 7.8], 'rot': 0, 'name': 'desk'},
                       {'asset': 'chairDesk', 'at': [9, 5], 'rot': 180, 'name': 'desk chair'},
                       {'asset': 'computerScreen', 'at': [9, 8.4], 'z': 2.15, 'rot': 0, 'solid': False},
                       {'asset': 'rugRound', 'at': [0, 1], 'solid': False},
                       {'row': ['bookcaseClosedWide', 'cardboardBoxClosed'], 'wall': 'right', 'start': -6},
                       {'asset': 'bear', 'at': [-6, 8.5], 'z': 1.5, 'solid': False},
                       {'asset': 'coatRackStanding', 'at': [-11.5, -8]},
                       {'asset': 'trashcan', 'at': [11.5, 9.5]}]},
 'kitchen': {'size': [26, 22],
             'height': 11,
             'wall': '#F6D58E',
             'floor': 'tile',
             'windows': [['back', 1, 6, 5, 4.5]],
             'doors': [['right', -4, 5]],
             'dress': [{'row': [{'asset': 'kitchenFridgeLarge', 'name': 'fridge'},
                                'kitchenCabinet',
                                'kitchenCabinetDrawer',
                                {'asset': 'kitchenSink', 'name': 'sink'},
                                'kitchenCabinet',
                                {'asset': 'kitchenStove', 'name': 'stove'},
                                {'asset': 'kitchenCabinetDrawer', 'name': 'counter'}],
                        'wall': 'back'},
                       {'row': ['kitchenCabinetUpper', 'kitchenCabinetUpper'], 'wall': 'back', 'start': -7, 'z': 6.2},
                       {'row': ['kitchenCabinetUpperDouble'], 'wall': 'back', 'start': 6, 'z': 6.2},
                       {'asset': 'tableRound', 'at': [1, 0], 'name': 'table'},
                       {'asset': 'chair', 'at': [-4.0, 0], 'rot': 90},   # pulled out: room to stand in front (bench affordance_every_seat)
                       {'asset': 'chair', 'at': [6.0, 0], 'rot': -90},
                       {'asset': 'rugRound', 'at': [1, 0], 'solid': False},
                       {'asset': 'pottedPlant', 'at': [-11.5, -9]},
                       {'asset': 'trashcan', 'at': [11.5, 3]},
                       {'row': ['kitchenBar', 'kitchenBarEnd'], 'wall': 'left', 'start': -4}]},
 'store': {'size': [32, 26],
           'height': 12,
           'wall': '#F4F1E8',
           'floor': 'tile',
           'windows': [['front', -8, 10, 7, 1.5]],
           'doors': [['front', 6, 6]],
           'dress': [{'row': ['shelf-end', 'shelf-boxes', 'shelf-bags', 'shelf-boxes', 'shelf-end'], 'wall': 'back'},
                     {'asset': 'shelf-boxes', 'at': [-8, 3], 'name': 'shelf A'},
                     {'asset': 'shelf-bags', 'at': [-8, 6]},
                     {'asset': 'shelf-boxes', 'at': [0, 3], 'name': 'shelf B'},
                     {'asset': 'shelf-bags', 'at': [0, 6]},
                     {'row': ['freezers-standing', 'freezers-standing'], 'wall': 'right', 'start': 0},
                     {'asset': 'cash-register', 'at': [9, -5], 'name': 'counter'},
                     {'asset': 'display-fruit', 'at': [-11, -5], 'name': 'fruit'},
                     {'asset': 'display-bread', 'at': [-11, -1]},
                     {'asset': 'shopping-cart', 'at': [4, -8]},
                     {'asset': 'shopping-basket', 'at': [12, -9]}]},
 'hallway': {'size': [14, 32],
             'height': 11,
             'wall': '#E6D3A3',
             'floor': 'checker',
             'windows': [['right', 8, 6, 6, 3]],
             'doors': [['left', -6, 5], ['left', 6, 5], ['back', 0, 6]],
             'dress': [{'asset': 'bench', 'at': [5, -4], 'rot': -90},
                       {'asset': 'pottedPlant', 'at': [5, 3]},
                       {'asset': 'trashcan', 'at': [-5.5, 0]},
                       {'row': ['bookcaseClosedDoors', 'bookcaseClosedDoors'], 'wall': 'right', 'start': -12}]},
 'classroom2': {'size': [30, 28],
                'height': 12,
                'wall': '#E9C46A',
                'floor': 'checker',
                'windows': [['right', -2, 7, 6, 3], ['right', 7, 7, 6, 3]],
                'doors': [['left', 8, 5]],
                # R6 seated shins (1 stud thick) cannot fit under these desks: keep them in front of the desk edge (R127 Lia 31 cm)
                'dress': [{'asset': 'desk', 'at': [-7, -3], 'rot': 0},
                          {'asset': 'desk', 'at': [-7, 3.8], 'rot': 0},
                          {'asset': 'desk', 'at': [0, -3], 'rot': 0},
                          {'asset': 'desk', 'at': [0, 3.8], 'rot': 0},
                          {'asset': 'desk', 'at': [7, -3], 'rot': 0},
                          {'asset': 'desk', 'at': [7, 3.8], 'rot': 0},
                          {'asset': 'chairDesk', 'at': [-7, -7.0], 'rot': 180},
                          {'asset': 'chairDesk', 'at': [-7, -0.2], 'rot': 180},
                          {'asset': 'chairDesk', 'at': [0, -7.0], 'rot': 180},
                          {'asset': 'chairDesk', 'at': [0, -0.2], 'rot': 180},
                          {'asset': 'chairDesk', 'at': [7, -7.0], 'rot': 180},
                          {'asset': 'chairDesk', 'at': [7, -0.2], 'rot': 180},
                          {'asset': 'desk', 'at': [0, 10], 'rot': 180, 'name': 'teacher desk'},
                          {'row': ['bookcaseOpenLow', 'bookcaseOpenLow', 'bookcaseClosed'], 'wall': 'left', 'start': -8},
                          {'asset': 'pottedPlant', 'at': [13, 12]},
                          {'asset': 'trashcan', 'at': [-13, 12]}]},
 'school_hallway': {'size': [16, 40],
                    'height': 11,
                    'wall': '#E8DDB5',
                    'floor': 'checker',
                    'wall_low': '#3A6EA5',
                    'windows': [['back', 0, 6, 6, 3]],
                    'doors': [['right', -10, 5], ['right', 6, 5]],
                    'dress': [{'lockers': 9, 'wall': 'left', 'start': -17},
                              {'lockers': 4, 'wall': 'right', 'start': -4, 'color': '#C0392B'},
                              {'asset': 'trashcan', 'at': [6.5, 13]},
                              {'asset': 'bench', 'at': [6.3, 16], 'rot': -90}]},
 'bathroom': {'size': [20, 18],
              'height': 11,
              'wall': '#BFE3D0',
              'floor': 'tile',
              'wall_low': '#E8F4EE',
              'windows': [['back', 5, 4, 4, 5]],
              'doors': [['left', -4, 5]],
              'dress': [{'row': ['toilet', 'bathroomSink', {'asset': 'bathroomCabinet', 'name': 'cabinet'}], 'wall': 'back', 'start': -8},
                        {'asset': 'bathtub', 'at': [6.5, 4], 'rot': -90, 'name': 'tub'},
                        {'asset': 'bathroomMirror', 'at': [-3.3, 8.6], 'z': 3.6, 'solid': False},
                        {'asset': 'rugRounded', 'at': [0, 0], 'solid': False},
                        {'asset': 'trashcan', 'at': [-8.5, 3]}]},
 'office': {'size': [30, 24],
            'height': 11,
            'wall': '#D9DEE5',
            'floor': 'carpet',
            'floor_color': '#5C6B7A',
            'windows': [['back', -6, 8, 6, 3], ['back', 7, 8, 6, 3]],
            'doors': [['left', -6, 5]],
            'dress': [{'asset': 'desk', 'at': [-7, 4], 'rot': 0, 'name': 'desk 0'},   # chairs stand pulled out: 1.8 studs to stand in front of the seat (bench affordance_every_seat)
                      {'asset': 'desk', 'at': [0, 4], 'rot': 0, 'name': 'desk 1'},
                      {'asset': 'desk', 'at': [7, 4], 'rot': 0, 'name': 'desk 2'},
                      {'asset': 'computerScreen', 'at': [-7, 4.4], 'z': 2.15, 'solid': False},
                      {'asset': 'computerScreen', 'at': [0, 4.4], 'z': 2.15, 'solid': False},
                      {'asset': 'computerScreen', 'at': [7, 4.4], 'z': 2.15, 'solid': False},
                      {'asset': 'chairDesk', 'at': [-7, 0.2], 'rot': 180},
                      {'asset': 'chairDesk', 'at': [0, 0.2], 'rot': 180},
                      {'asset': 'chairDesk', 'at': [7, 0.2], 'rot': 180},
                      {'row': ['bookcaseClosedDoors', 'bookcaseClosedDoors', 'pottedPlant'], 'wall': 'right', 'start': -6},
                      {'asset': 'trashcan', 'at': [12, 10]}]},
 'forest': {'outdoor': True, 'size': [70, 60], 'floor': 'grass', 'time': 'day', 'forest': True},
 'city': {'outdoor': True, 'size': [80, 70], 'floor': 'asphalt', 'time': 'day', 'city': True},
 'street': {'outdoor': True, 'size': [80, 70], 'floor': 'grass', 'time': 'day'},
 'park': {'outdoor': True, 'size': [70, 60], 'floor': 'grass', 'time': 'day', 'park': True},
 'wasteland': {'outdoor': True, 'size': [80, 70], 'floor': 'sand', 'time': 'day', 'wasteland': True}}


def _floor_mat(kind, col=None):
    k, c1, c2, sc = FLOORS.get(kind, FLOORS['wood'])
    if col: c1 = col
    return pattern_mat('floor ' + kind, k, c1, c2, sc) if k != 'flat' else mat('floor ' + kind, c1, 0.85)


def _wall(side, W, D, H, openings, m, t=0.4):
    """Solid wall split around openings [(u, width, z0, height)] (studs) -> boxes in metres. Returns the opening rects."""
    L = W if side in ('back', 'front') else D
    ops = sorted(openings)
    segs, u0 = [], -L / 2
    for u, w, z0, h in ops:
        a, b = u - w / 2, u + w / 2
        if a > u0: segs.append((u0, a, 0, H))
        if z0 > 0: segs.append((a, b, 0, z0))
        if z0 + h < H: segs.append((a, b, z0 + h, H))
        u0 = b
    if u0 < L / 2: segs.append((u0, L / 2, 0, H))
    for a, b, z0, z1 in segs:
        um, ul, zm, zl = (a + b) / 2, b - a, (z0 + z1) / 2, z1 - z0
        if side == 'back': c, s = (um, D / 2 + t / 2, zm), (ul, t, zl)
        elif side == 'front': c, s = (um, -D / 2 - t / 2, zm), (ul, t, zl)
        elif side == 'left': c, s = (-W / 2 - t / 2, um, zm), (t, ul, zl)
        else: c, s = (W / 2 + t / 2, um, zm), (t, ul, zl)
        box(f'{side} wall', tuple(v * S for v in c), tuple(v * S for v in s), m)


def _frame(side, W, D, u, w, z0, h, m):
    """Window/door trim (4 thin boxes) on the inside face of a wall."""
    q = 0.35
    for du, dz, su, sz in ((0, -q / 2, w + q, q), (0, h + q / 2, w + q, q), (-w / 2 - q / 2, h / 2, q, h), (w / 2 + q / 2, h / 2, q, h)):
        uu, zz = u + du, z0 + dz
        if side == 'back': c, s = (uu, D / 2 - 0.05, zz), (su, 0.3, sz)
        elif side == 'front': c, s = (uu, -D / 2 + 0.05, zz), (su, 0.3, sz)
        elif side == 'left': c, s = (-W / 2 + 0.05, uu, zz), (0.3, su, sz)
        else: c, s = (W / 2 - 0.05, uu, zz), (0.3, su, sz)
        if (z0 == 0 and dz < 0): continue      # doors: no bottom bar
        box('trim', tuple(v * S for v in c), tuple(v * S for v in s), m)


def painting_mat(rng, axis):
    """Unique pixel-art painting (48x48, closest filtering): landscape/sunset/night/abstract. axis 'x' or 'y' = wall direction."""
    import numpy as np
    n = 48; kind = rng.choice(['land', 'sunset', 'night', 'abstract', 'land'])
    pal = {'land': ((.35, .65, .95), (.75, .9, 1.0), (.3, .7, .25), (1, .9, .3)), 'sunset': ((.95, .45, .25), (1, .8, .4), (.35, .2, .4), (1, .95, .6)),
           'night': ((.05, .07, .2), (.15, .2, .45), (.1, .25, .15), (.95, .95, .85)), 'abstract': ((.95, .3, .35), (.2, .6, .9), (1, .85, .2), (.2, .2, .25))}[kind]
    img = np.zeros((n, n, 4), dtype=np.float32); img[..., 3] = 1
    yy, xx = np.mgrid[0:n, 0:n] / n
    if kind == 'abstract':
        img[..., :3] = pal[0]
        for _ in range(4):
            cx, cy, r = rng.random(), rng.random(), rng.uniform(.1, .3); c = rng.choice(pal[1:])
            img[((xx - cx) ** 2 + (yy - cy) ** 2) < r * r, :3] = c
    else:
        for k in range(3): img[..., k] = pal[0][k] * yy + pal[1][k] * (1 - yy)       # sky gradient (top = row n-1)
        ph, amp = rng.uniform(0, 6), rng.uniform(.05, .12)
        img[yy < 0.38 + amp * np.sin(xx * 6 + ph), :3] = pal[2]                       # hills
        cx, cy = rng.uniform(.2, .8), rng.uniform(.6, .85)
        img[((xx - cx) ** 2 + (yy - cy) ** 2) < 0.012, :3] = pal[3]                     # sun / moon
    im = bpy.data.images.new(f'painting {rng.random():.6f}', n, n); im.pixels = img.ravel().tolist()
    m = bpy.data.materials.new(im.name); m.use_nodes = True; nt = m.node_tree; b = nt.nodes['Principled BSDF']
    b.inputs['Roughness'].default_value = 0.5
    tc = nt.nodes.new('ShaderNodeTexCoord'); sep = nt.nodes.new('ShaderNodeSeparateXYZ'); com = nt.nodes.new('ShaderNodeCombineXYZ')
    t = nt.nodes.new('ShaderNodeTexImage'); t.image = im; t.interpolation = 'Closest'
    nt.links.new(tc.outputs['Generated'], sep.inputs[0]); nt.links.new(sep.outputs['X' if axis == 'x' else 'Y'], com.inputs['X'])
    nt.links.new(sep.outputs['Z'], com.inputs['Y']); nt.links.new(com.outputs[0], t.inputs['Vector'])
    nt.links.new(t.outputs['Color'], b.inputs['Base Color']); m.diffuse_color = (*pal[0], 1)
    return m


def _decor(W, D, H, wall_has, rng):
    """Wall decor: picture frames, posters, a clock - placed on wall spans free of openings."""
    cols = ['#E63946', '#2A9D8F', '#F4A261', '#457B9D', '#8AC926', '#FF70A6', '#6A4C93']
    fr = mat('frame wood', '#5B3A1E', 0.6)
    for side in ('back', 'left', 'right', 'front'):
        L = W if side in ('back', 'front') else D
        for u in [L * k / 6 for k in (-2, -1, 0, 1, 2)]:
            if any(abs(u - ou) < ow / 2 + 3 for ou, ow in wall_has.get(side, [])): continue
            if rng.random() < 0.2: continue
            w, h = rng.choice([(3, 4), (4, 3), (2.5, 2.5), (5, 3.5)]); z = H * rng.uniform(0.5, 0.62)
            canvas = painting_mat(rng, 'x' if side in ('back', 'front') else 'y')
            for nm, m, dd, ww, hh in (('frame', fr, 0.06, w + 0.4, h + 0.4), ('poster', canvas, 0.12, w, h)):
                if side == 'back': c, s = (u, D / 2 - dd, z), (ww, 0.08, hh)
                elif side == 'front': c, s = (u, -D / 2 + dd, z), (ww, 0.08, hh)
                elif side == 'left': c, s = (-W / 2 + dd, u, z), (0.08, ww, hh)
                else: c, s = (W / 2 - dd, u, z), (0.08, ww, hh)
                box(nm, tuple(v * S for v in c), tuple(v * S for v in s), m)
    # clock on the back wall
    if not any(abs(ou) < ow / 2 + 2 for ou, ow in wall_has.get('back', [])):
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=1.0 * S, depth=0.15 * S, location=(0, (D / 2 - 0.1) * S, H * 0.82 * S),
                                            rotation=(math.pi / 2, 0, 0))
        o = bpy.context.object; o.name = 'clock'; o.data.materials.append(mat('clock face', '#F8F4EA', 0.4))


def interior(sp):
    W, D = sp['size']; H = sp.get('height', 11); rng = random.Random(sp.get('seed', 7))
    wm = mat('walls ' + sp.get('wall', '#E9C88A'), sp.get('wall', '#E9C88A'), 0.9)
    trim = mat('trim', sp.get('trim', '#F3EAD3'), 0.6)
    box('floor', (0, 0, -0.1 * S), (W * S + 0.4, D * S + 0.4, 0.2 * S), _floor_mat(sp.get('floor', 'wood'), sp.get('floor_color')))
    box('ceiling', (0, 0, (H + 0.15) * S), (W * S + 0.4, D * S + 0.4, 0.3 * S), mat('ceiling', '#F4EFE4', 0.9))
    for side, (a, b, c) in {'back': (0, D / 2 - 0.15, 0.3), 'front': (0, -D / 2 + 0.15, 0.3)}.items():
        box('skirting', (a * S, b * S, c * S / 2 + 0.05), (W * S, 0.12, c * S), trim)
    ops = {s: [] for s in ('back', 'front', 'left', 'right')}; has = {}
    for wdef in sp.get('windows', []):
        side, u, w, h = wdef[:4]; sill = wdef[4] if len(wdef) > 4 else 3
        ops[side].append((u, w, sill, h)); has.setdefault(side, []).append((u, w))
    for ddef in sp.get('doors', []):
        side, u, w = ddef[:3]; ops[side].append((u, w, 0, min(H - 1.5, 8.5))); has.setdefault(side, []).append((u, w))
    for side in ops:
        _wall(side, W, D, H, ops[side], wm)
        for u, w, z0, h in ops[side]: _frame(side, W, D, u, w, z0, h, trim)
    for ddef in sp.get('doors', []):     # a closed door leaf just outside the opening (reads as a door, keeps the void out)
        side, u, w = ddef[:3]; h = min(H - 1.5, 8.5); dm = mat('door', sp.get('door', '#8A5A33'), 0.6)
        c = {'back': (u, D / 2 + 0.5, h / 2), 'front': (u, -D / 2 - 0.5, h / 2), 'left': (-W / 2 - 0.5, u, h / 2), 'right': (W / 2 + 0.5, u, h / 2)}[side]
        s = (w, 0.3, h) if side in ('back', 'front') else (0.3, w, h)
        box('door leaf', tuple(v * S for v in c), tuple(v * S for v in s), dm)
    # outside: ground + trees + sky seen through windows
    box('outside ground', (0, 0, -0.3 * S), ((W + 120) * S, (D + 120) * S, 0.2 * S), mat('outside grass', '#6DB24A', 0.9))
    for i, (x, y) in enumerate([(W / 2 + 12, -6), (W / 2 + 16, 8), (-8, D / 2 + 14), (9, D / 2 + 18), (-W / 2 - 14, 4)]):
        assets.place('tree_default' if i % 2 else 'tree_blocks', (x, y), rot=i * 50, scale=1.4, solid=False)
    if sp.get('wainscot', True):     # two-tone walls: darker lower panel + chair rail (cheap richness, very Roblox-house)
        low = sp.get('wall_low') or '#%02X%02X%02X' % tuple(int(int(sp.get('wall', '#E9C88A').lstrip('#')[i:i + 2], 16) * 0.72) for i in (0, 2, 4))
        lm = mat('wall low ' + low, low, 0.85); zh = 3.2
        for side in ('back', 'front', 'left', 'right'):
            L = W if side in ('back', 'front') else D
            spans, u0 = [], -L / 2
            for u, w, z0, h in sorted(ops[side]):
                if z0 < zh: spans.append((u0, u - w / 2)); u0 = u + w / 2
            spans.append((u0, L / 2))
            for a, b in spans:
                if b - a < 0.3: continue
                um, ul = (a + b) / 2, b - a
                for nm, m_, zc, zs, dd in (('wainscot', lm, zh / 2, zh, 0.06), ('chair rail', trim, zh, 0.3, 0.12)):
                    if side == 'back': c, s_ = (um, D / 2 - dd / 2, zc), (ul, dd, zs)
                    elif side == 'front': c, s_ = (um, -D / 2 + dd / 2, zc), (ul, dd, zs)
                    elif side == 'left': c, s_ = (-W / 2 + dd / 2, um, zc), (dd, ul, zs)
                    else: c, s_ = (W / 2 - dd / 2, um, zc), (dd, ul, zs)
                    box(nm, tuple(v * S for v in c), tuple(v * S for v in s_), m_)
    if sp.get('decor', True): _decor(W, D, H, has, rng)
    if sp.get('ceiling_lamps', True):
        for x in (-W / 4, W / 4):
            assets.place('lampSquareCeiling', (x, 0), z=H - 0.95, solid=False)
    return {'bounds': (-W / 2 * S, W / 2 * S, -D / 2 * S, D / 2 * S), 'windows': ops, 'H': H, 'W': W, 'D': D}


def exterior(sp):
    W, D = sp['size']; rng = random.Random(sp.get('seed', 3))
    box('ground', (0, 0, -0.1 * S), ((W + 200) * S, (D + 200) * S, 0.2 * S), _floor_mat(sp.get('floor', 'grass')))
    if sp.get('forest'):   # forest clearing: dense trees around a clear acting circle, rocks, bushes, a campfire
        for i in range(60):   # behind/beside the clearing; the camera side (-Y) only gets far trees
            a = rng.uniform(0, 2 * math.pi); r = rng.uniform(16, 34); x, y = r * math.cos(a), r * math.sin(a) + 8
            if y < -4 and r < 30: continue
            assets.place(rng.choice(['tree_pineTallD', 'tree_default', 'tree_cone', 'tree_blocks', 'tree_cone_dark']),
                         (x, y), rot=rng.uniform(0, 360), scale=rng.uniform(1.4, 2.0))
        for i in range(12):
            a = rng.uniform(0.15 * math.pi, 0.85 * math.pi); r = rng.uniform(9, 15)   # back arc only
            assets.place(rng.choice(['rock_largeA', 'rock_smallA', 'plant_bush', 'plant_bushLarge']),
                         (r * math.cos(a), r * math.sin(a) + 6), rot=rng.uniform(0, 360), scale=1.2, solid=False)
        assets.place('campfire_logs', (2, 5), label='campfire', scale=1.4)
        for i in range(20):
            assets.place(rng.choice(['grass', 'flower_purpleA', 'flower_yellowA']), (rng.uniform(-25, 25), rng.uniform(14, 30)), solid=False)
    elif sp.get('wasteland'):   # rocky battle plateau: open fighting circle (r ~18 studs), rock pillars around, mesas far away
        for i in range(16):   # pillars in a ring; the camera side (-Y) keeps a wide gap so cameras stay clear
            a = rng.uniform(0, 2 * math.pi); r = rng.uniform(22, 34); x, y = r * math.cos(a), r * math.sin(a) + 4   # big pillars: footprint ~6 studs
            if y < -8 and abs(x) < 22: continue
            assets.place(rng.choice(['rock_tallA', 'rock_tallB', 'rock_tallC', 'rock_tallE', 'rock_tallG', 'rock_tallI']),
                         (x, y), rot=rng.uniform(0, 360), scale=rng.uniform(1.0, 1.7) * (.65 if y > 12 else 1), label=f'rock pillar {i}')   # R-look2 lower (was 1.2-2.2, far side x.65): sky behind the cast   # 4.5 = 32-stud cliffs reaching the centre (R121)
        for i in range(9):    # mesas on the horizon (no collision: far outside the acting area)
            a = math.radians(-10 + i * 25); r = rng.uniform(55, 75)
            assets.place(rng.choice(['cliff_large_rock', 'cliff_block_rock', 'cliff_blockHalf_rock']), (r * math.cos(a), r * math.sin(a) + 10),
                         rot=rng.uniform(0, 360), scale=rng.uniform(5, 8), solid=False)
        for i in range(26):   # rubble: back arc only (non-solid rubble on the camera side filled the lens, R119)
            a = rng.uniform(0.1 * math.pi, 0.9 * math.pi); r = rng.uniform(9, 30)
            assets.place(rng.choice(['rock_smallA', 'rock_smallC', 'rock_smallFlatA', 'rock_smallG']),
                         (r * math.cos(a), r * math.sin(a) + 4), rot=rng.uniform(0, 360), scale=rng.uniform(1.0, 2.0), solid=False)
        for x, y in ((-24, 18), (26, 14)):
            assets.place('cactus_tall', (x, y), scale=1.6, solid=False)
        # R-look2 sandstone: the kit's peach 'dirt' + teal 'grass' caps rendered as a dark saturated orange wall behind every
        # character; pale warm beige rock with a darker tan strata cap (teal stays only on the cacti)
        for m in {m for o in bpy.data.objects if o.type == 'MESH' for m in o.data.materials if m and m.use_nodes}:
            col = (.92, .73, .55) if m.name.startswith('dirt') else (.60, .41, .27)   # sunlit peach-tan + darker warm strata if m.name.startswith('grass') else None
            bs = m.node_tree.nodes.get('Principled BSDF')
            if col and bs: bs.inputs['Base Color'].default_value = (*col, 1); m.diffuse_color = (*col, 1)
    elif sp.get('city'):   # downtown: wide sidewalk, road, shop fronts close behind, skyscrapers behind them, traffic, street lights
        box('road', (0, 11 * S, 0.01), ((W + 200) * S, 14 * S, 0.02), mat('road asphalt', '#3F4247', 0.8))
        for x in range(-60, 61, 8):
            box('lane mark', (x * S, 11 * S, 0.025), (4 * S, 0.4 * S, 0.01), mat('lane paint', '#F2F2F2', 0.6))
        box('sidewalk', (0, 0, 0.06), ((W + 200) * S, 16 * S, 0.12), mat('city sidewalk', '#B9B6B0', 0.8))
        for i, x in enumerate(range(-44, 45, 11)):
            assets.place('city-kit-commercial/building-' + 'abcdefghijklmn'[(i * 3) % 14], (x, 26), rot=0, label=f'shop {i}')
            assets.place('city-kit-commercial/building-skyscraper-' + 'abcde'[i % 5], (x + 5, 46), rot=0, solid=False)
        for i, x in enumerate(range(-40, 41, 16)):
            assets.place('city-kit-commercial/building-' + 'abcdefghijklmn'[(i * 5 + 2) % 14], (x, -30), rot=180, label=f'shop front {i}')
        for i, x in enumerate((-26, -6, 18, 34)):
            assets.place(['car-kit/taxi', 'car-kit/sedan', 'car-kit/van', 'car-kit/police'][i], (x, 8 if i % 2 else 14),
                         rot=90 if i % 2 else -90, label=f'car {i}')
        lamps = []
        for x in (-20, 0, 20):
            assets.place('city-kit-roads/light-square', (x, 6.5), rot=180)
            q = assets.PLACED[-1]; lamps.append(((q['rect'][0] + q['rect'][1]) / 2, (q['rect'][2] + q['rect'][3]) / 2, q['top'] - 0.3))
    elif sp.get('park'):
        box('path', (0, 0, 0.02), (6 * S, (D + 40) * S, 0.04), mat('park path', '#D9C29A', 0.9))
        for i in range(14):
            x = rng.choice([-1, 1]) * rng.uniform(8, W / 2); y = rng.uniform(-D / 2, D / 2 + 20)
            assets.place(rng.choice(['tree_default', 'tree_blocks', 'tree_cone', 'tree_oak' if False else 'tree_default']), (x, y), rot=rng.uniform(0, 360), scale=1.6)
        for y in (-6, 8):
            assets.place('bench', (5, y), rot=-90, label=f'bench {y}')
        for i in range(30):   # flower beds: off the path and outside the acting area (|x| < 14, -12 < y < 8 stays clear)
            x = rng.choice([-1, 1]) * rng.uniform(14, W / 2); y = rng.uniform(-D / 2, D / 2)
            if rng.random() < 0.5: x, y = rng.uniform(-W / 2, W / 2), rng.choice([rng.uniform(10, D / 2), rng.uniform(-D / 2, -14)])
            if abs(x) < 4: continue
            assets.place(rng.choice(['flower_redA', 'flower_yellowA', 'flower_purpleA', 'grass']), (x, y), solid=False, scale=1.5)
    else:   # suburban street (reference density): sidewalk right behind the cast, road, houses close with fenced yards both sides
        box('road', (0, 11 * S, 0.01), ((W + 200) * S, 12 * S, 0.02), mat('road asphalt', '#45484D', 0.8))
        for x in range(-60, 61, 8):
            box('lane mark', (x * S, 11 * S, 0.025), (4 * S, 0.4 * S, 0.01), mat('lane paint', '#F2F2F2', 0.6))
        box('sidewalk', (0, 3 * S, 0.06), ((W + 200) * S, 4 * S, 0.12), mat('sidewalk', '#C9C6C0', 0.8))
        box('sidewalk far', (0, 19 * S, 0.06), ((W + 200) * S, 4 * S, 0.12), mat('sidewalk', '#C9C6C0', 0.8))
        box('curb', (0, 5.1 * S, 0.09), ((W + 200) * S, 0.3 * S, 0.18), mat('curb', '#A9A6A0', 0.8))
        box('curb far', (0, 16.9 * S, 0.09), ((W + 200) * S, 0.3 * S, 0.18), mat('curb', '#A9A6A0', 0.8))
        types = 'abcdefghijklmnopqrstu'; cars = ['car-kit/sedan', 'car-kit/suv', 'car-kit/van', 'car-kit/taxi', 'car-kit/hatchback-sports']
        for i, x in enumerate(range(-48, 49, 16)):            # far side: houses 31 studs back, fence line, bushes, trees
            assets.place(f'city-kit-suburban/building-type-{types[(i * 5 + 2) % 21]}', (x, 31), rot=180, scale=1.5, label=f'house {i}')
            assets.place('city-kit-suburban/fence-1x4', (x - 5, 22.5), rot=0, scale=0.8, solid=False)
            assets.place('nature-kit/plant_bushLarge', (x + 5, 23), scale=1.2, solid=False)
            assets.place('city-kit-suburban/tree-large', (x + 8, 21.5), scale=1.0, solid=False)
        for i, x in enumerate(range(-40, 41, 16)):            # near side (reverse angles): houses + yards kept BEHIND the camera zone
            assets.place(f'city-kit-suburban/building-type-{types[(i * 7 + 4) % 21]}', (x, -38), scale=1.5, label=f'house front {i}')
            assets.place('nature-kit/plant_bush', (x + 6, -28), scale=1.4, solid=False)   # cameras live in y -6..-26: keep it clear
            assets.place('city-kit-suburban/fence-1x4', (x - 4, -29), scale=0.8, solid=False)
        for i, x in enumerate((-30, -12, 20, 38)):            # parked cars both kerbs
            assets.place(cars[i % len(cars)], (x, 7.5 if i % 2 else 14.5), rot=90 if i % 2 else -90, label=f'car {i}')
        lamps = []
        for x in (-24, 4, 28):
            lp = assets.place('retro-urban-kit/detail-light-single', (x, 1.5), rot=180)
            q = assets.PLACED[-1]; lamps.append(((q['rect'][0] + q['rect'][1]) / 2, (q['rect'][2] + q['rect'][3]) / 2 - 0.4, q['top'] - 0.25))
            assets.place('city-kit-suburban/tree-small', (x + 9, 1.2), scale=1.2)
        assets.place('city-kit-commercial/dumpster' if False else 'retro-urban-kit/detail-dumpster-closed', (-16, 1.5), rot=180, scale=0.8)
        for i in range(30):                                     # flowers in the YARDS only (never in the acting strip y -13..0)
            assets.place(rng.choice(['flower_redA', 'flower_yellowA', 'flower_purpleA']),
                         (rng.uniform(-W / 2, W / 2), rng.uniform(-34, -28) if i % 2 else rng.uniform(21, 27)), solid=False, scale=1.0)
    return {'bounds': (-W / 2 * S, W / 2 * S, -D / 2 * S, D / 2 * S), 'windows': {}, 'H': 60, 'W': W, 'D': D, 'outdoor': True,
            'lamps': locals().get('lamps', [])}


def lockers(d, W, D):
    wall = d.get('wall', 'left'); n = d.get('lockers', 6); u0 = d.get('start', -n); col = d.get('color', '#3A6EA5')
    piv = bpy.data.objects.new(d.get('name', f'lockers {wall}'), None); bpy.context.collection.objects.link(piv)
    body, dark, metal = mat('locker ' + col, col, 0.45), mat('locker gap', '#1C2430', 0.6), mat('locker handle', '#C9CED6', 0.3)
    for i in range(n):
        u = u0 + i * 2.0 + 1.0
        parts = (('locker', body, 1.6, 1.94, 7.0, 3.5, 0.0), ('locker vent', dark, 1.66, 1.0, 0.5, 6.0, 0.0),
                 ('locker vent', dark, 1.66, 1.0, 0.5, 5.3, 0.0), ('locker handle', metal, 1.7, 0.18, 0.7, 3.6, 0.6))
        for nm, m_, dd, wu, hz, zc, du in parts:
            if wall == 'left': c, sz = (-W / 2 + dd / 2, u + du, zc), (dd, wu, hz)
            elif wall == 'right': c, sz = (W / 2 - dd / 2, u + du, zc), (dd, wu, hz)
            elif wall == 'back': c, sz = (u + du, D / 2 - dd / 2, zc), (wu, dd, hz)
            else: c, sz = (u + du, -D / 2 + dd / 2, zc), (wu, dd, hz)
            box(nm, tuple(v * S for v in c), tuple(v * S for v in sz), m_, parent=piv)
    if wall in ('left', 'right'):
        x0, x1 = (-W / 2, -W / 2 + 1.7) if wall == 'left' else (W / 2 - 1.7, W / 2); y0, y1 = u0, u0 + 2 * n
    else:
        x0, x1 = u0, u0 + 2 * n; y0, y1 = (D / 2 - 1.7, D / 2) if wall == 'back' else (-D / 2, -D / 2 + 1.7)
    assets.PLACED.append({'name': piv.name, 'pivot': piv, 'rect': (x0 * S, x1 * S, y0 * S, y1 * S),
                          'top': 7 * S, 'solid': True})


def build(spec):
    """Merge the preset with the story's overrides, build, place 'dress'. Returns dict(bounds, supports, obstacles, info)."""
    base = dict(PRESETS.get(spec.get('preset', 'room'), {'size': [28, 24]}))
    dress = list(base.get('dress', [])) + list(spec.get('dress', []))
    base.update({k: v for k, v in spec.items() if k != 'dress'}); base['dress'] = dress
    info = exterior(base) if base.get('outdoor') else interior(base)
    W, D = base['size']
    expanded = []
    for d in dress:
        if 'lockers' in d:   # procedural school lockers along a wall: n doors, 2 studs wide, 7 tall (Kenney has none)
            lockers(d, W, D); continue
        if 'row' not in d: expanded.append(d); continue   # 'row': models edge to edge along a wall, real catalogue widths
        wall = d.get('wall', 'back'); u = d.get('start', None); gap = d.get('gap', 0.05); z = d.get('z', 0)
        items = [it if isinstance(it, dict) else {'asset': it} for it in d['row']]
        sizes = []
        for it in items:
            e = assets.find(it['asset']); k = assets.KIT_SCALE.get(e['kit'], 1.0) * it.get('scale', 1.0) / S
            sizes.append((e['size_x'] * k, e['size_y'] * k))          # studs: width along the wall, depth into the room
        L = W if wall in ('back', 'front') else D
        total = sum(w for w, _ in sizes) + gap * (len(items) - 1)
        u = -total / 2 if u is None else u
        if u + total > L / 2 - 0.3: u = L / 2 - 0.3 - total            # keep the run inside the wall
        for it, (w, dp) in zip(items, sizes):
            c = u + w / 2; off = dp / 2 + 0.25
            # Kenney furniture faces -Y at rot 0 (checked: trace/kenney_front_check.png) -> face INTO the room
            if wall == 'back': at, rot = (c, D / 2 - off), 0
            elif wall == 'front': at, rot = (-c, -D / 2 + off), 180
            elif wall == 'left': at, rot = (-W / 2 + off, -c), 90
            else: at, rot = (W / 2 - off, c), -90
            expanded.append({**it, 'at': list(at), 'rot': rot, 'z': it.get('z', z)})
            u += w + gap
    dress = expanded
    for d in dress:
        assets.place(d['asset'], tuple(d['at']), rot=d.get('rot', 0), z=d.get('z', 0), scale=d.get('scale', 1),
                     label=d.get('name'), solid=d.get('solid', True))
    info['time'] = base.get('time', 'day'); info['spec'] = base
    return info
