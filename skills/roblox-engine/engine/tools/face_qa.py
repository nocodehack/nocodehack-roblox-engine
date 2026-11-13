"""face_qa.py - every library face on the R6 head (front, draft), labelled emotion + name + talk partner -> assets/faces/sheet.jpg
  blender -b --factory-startup --offline-mode -P tools/face_qa.py        (renders to trace/_faceqa, stitches with system python)"""
import sys, json, subprocess
from pathlib import Path
E = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(E))
T, C = 150, 11
if '--sheet' in sys.argv:
    from PIL import Image, ImageDraw
    rows = json.loads(Path(sys.argv[2]).read_text()); R = (len(rows) + C - 1) // C
    img = Image.new('RGB', (C * T, R * (T + 26)), (20, 20, 24)); dr = ImageDraw.Draw(img)
    for i, (png, l1, l2) in enumerate(rows):
        x, y = (i % C) * T, (i // C) * (T + 26); dr.text((x + 2, y + 1), l1, fill=(160, 230, 160)); dr.text((x + 2, y + 12), l2, fill=(230, 200, 120))
        img.paste(Image.open(png).convert('RGB').resize((T, T)), (x, y + 26))
    img.save(sys.argv[3], quality=85); print('SHEET', sys.argv[3], len(rows)); sys.exit()
import bpy
from mathutils import Vector
import rig, look, faces
TMP = E / 'trace' / '_faceqa'; TMP.mkdir(parents=True, exist_ok=True); S = rig.S
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene; look.tier(sc, 'draft'); sc.render.resolution_percentage = 100; sc.render.resolution_x = sc.render.resolution_y = 300
sc.world = bpy.data.worlds.new('w'); sc.world.color = (0.75, 0.78, 0.82); sc.view_settings.view_transform = 'Standard'
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = 'ORTHO'; cam.data.ortho_scale = 2.0 * S
sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN')); sc.collection.objects.link(sun); sun.rotation_euler = (1.0, 0, 0.3); sun.data.energy = 3
ch = rig.make('Q', (0, 0), 0); bpy.context.view_layer.update()
hp = ch.head.matrix_world.translation; cam.location = hp + Vector((0, -10 * S, 0)); cam.rotation_euler = (1.5708, 0, 0)
rows = []
for i, (s, m) in enumerate(faces.library().items()):
    faces.set('Q', 'lib:' + s, 1); sc.frame_set(1)
    p = TMP / f'{m["id"]}.png'; sc.render.filepath = str(p); bpy.ops.render.render(write_still=True)
    pr = m['pair_slug']; rows.append((str(p), f"{m['emotion']} {m['name'][:16]}", f"talk: {faces.library()[pr]['name'][:14] if pr else '-'}"))
    for o in bpy.data.objects:   # keep one decal visible at a time
        if o.name.startswith('Q face lib:') : o.hide_render = o.hide_viewport = True
rj = TMP / 'rows.json'; rj.write_text(json.dumps(rows)); (E / 'assets' / 'faces').mkdir(exist_ok=True)
subprocess.run(['python', __file__, '--sheet', str(rj), str(E / 'assets' / 'faces' / 'sheet.jpg')], check=True)
