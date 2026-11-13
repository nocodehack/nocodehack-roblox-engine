"""plan_view.py - top-down labelled plan of a set (+ cast marks) to check a layout written from a reference picture.
blender -b --factory-startup --offline-mode -P tools/plan_view.py -- <short.json> <out.png>
Builds only the set (rooms.py preset + dress) and the cast spots; labels every placed piece with its name; 2-stud grid; Workbench."""
import sys, json, math
from pathlib import Path
import bpy
E = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(E))
import sets, assets, rooms
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
spec = json.loads(Path(argv[0]).read_text(encoding='utf-8')); out = str(Path(argv[1]).resolve())
bpy.ops.wm.read_factory_settings(use_empty=True); assets.reset()
sc = bpy.context.scene; S = 0.5
st = sets.build(spec.get('set', {'preset': 'classroom'}))
for o in list(bpy.data.objects):            # roof off: hide ceilings/lamps so the plan sees the floor
    if o.name.startswith(('ceiling', 'lampSquareCeiling')): o.hide_render = True
def label(txt, x, y, z, size=0.45, col=(0, 0, 0)):
    c = bpy.data.curves.new(txt, 'FONT'); c.body = txt; c.size = size; c.align_x = 'CENTER'
    o = bpy.data.objects.new(txt, c); bpy.context.collection.objects.link(o); o.location = (x, y, z)
    m = bpy.data.materials.new('lab'); m.diffuse_color = (*col, 1); c.materials.append(m)
for q in assets.PLACED:
    if q['name'].startswith(('lampSquareCeiling', 'tree_')): continue    # ceiling lamps / trees outside: no label clutter
    x0, x1, y0, y1 = q['rect']; label(q['name'], (x0 + x1) / 2, (y0 + y1) / 2, q['top'] + 0.05)
for c in spec.get('cast', []):
    x, y = c.get('at', (0, 0)); label('@' + c['name'], x * S, y * S, 3.2, 0.6, (0.8, 0, 0))
b = st.get('bounds') or (-10, 10, -10, 10)
for gx in range(int(b[0] / S) // 2 * 2, int(b[1] / S) + 1, 2):    # 2-stud grid labels along the front edge
    if gx % 4 == 0: label(str(gx), gx * S, b[2] + 0.3, 0.05, 0.3, (0.2, 0.2, 0.6))
for gy in range(int(b[2] / S) // 2 * 2, int(b[3] / S) + 1, 2):
    if gy % 4 == 0: label(str(gy), b[0] + 0.3, gy * S, 0.05, 0.3, (0.2, 0.2, 0.6))
cd = bpy.data.cameras.new('plan'); cd.type = 'ORTHO'; cd.ortho_scale = max(b[1] - b[0], b[3] - b[2]) * 1.08
cam = bpy.data.objects.new('plan', cd); bpy.context.collection.objects.link(cam)
cam.location = ((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, 40); cam.rotation_euler = (0, 0, 0); sc.camera = cam
r = sc.render; r.engine = 'BLENDER_WORKBENCH'; r.resolution_x = r.resolution_y = 1000; r.filepath = out
sc.display.shading.color_type = 'MATERIAL'; sc.display.shading.light = 'FLAT'
bpy.ops.render.render(write_still=True)
print('PLAN', out, len(assets.PLACED), 'pieces')
