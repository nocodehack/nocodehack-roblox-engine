"""anims_sheet.py - contact sheet of every imported Roblox animation: 6 frames across its duration on one R6 (Workbench draft look).
  blender -b --factory-startup --offline-mode -P tools/anims_sheet.py -- [--out assets/anims/sheet.jpg]
One row per clip (label = slug, duration, loop). Frames are the CONVERTED animation keyed on the rig by anims.play (what the engine uses)."""
import sys, math, json, subprocess
from pathlib import Path
E = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(E))
T, N = 200, 6


def sheet(rows_json, out):
    """System python (Blender's has no PIL)."""
    from PIL import Image, ImageDraw
    rows = json.loads(Path(rows_json).read_text())
    img = Image.new('RGB', (N * T, len(rows) * (T + 16)), (20, 20, 24)); dr = ImageDraw.Draw(img)
    for r, (label, tiles) in enumerate(rows):
        y = r * (T + 16); dr.text((4, y + 2), label, fill=(160, 230, 160))
        for k, p in enumerate(tiles): img.paste(Image.open(p).convert('RGB').resize((T, T)), (k * T, y + 16))
    img.save(out, quality=82); print('SHEET', out, len(rows), 'clips')


if '--sheet' in sys.argv:
    sheet(sys.argv[2], sys.argv[3]); sys.exit()
import bpy
from mathutils import Vector
import rig, look, anims

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = Path(argv[argv.index('--out') + 1]) if '--out' in argv else E / 'assets' / 'anims' / 'sheet.jpg'
TMP = E / 'trace' / '_animsheet'; TMP.mkdir(parents=True, exist_ok=True)
S = rig.S
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene; look.tier(sc, 'draft')
sc.render.resolution_x = sc.render.resolution_y = 320; sc.render.resolution_percentage = 100
sc.world = bpy.data.worlds.new('w'); sc.world.color = (0.75, 0.78, 0.82); sc.display.shading.background_type = 'WORLD'
sc.view_settings.view_transform = 'Standard'
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam; cam.data.lens = 40
ch = rig.make('A', (0, 0), 0, hair_style='short')
fps = sc.render.fps / sc.render.fps_base
rows = []
for slug in anims.slugs():
    m = anims.meta(slug)
    for o in bpy.data.objects: o.animation_data_clear()
    sc.frame_set(0)
    f0 = 1000; anims.play(sc, ch, slug, f0, blend=0)
    pos = Vector((0.9 * S * 4, -7.5 * S, 3.2 * S)); aim = Vector((0, 0, 3.0 * S))
    cam.location = pos; cam.rotation_euler = (aim - pos).to_track_quat('-Z', 'Y').to_euler()
    tiles = []
    for k in range(N):
        sc.frame_set(round(f0 + m['duration'] * fps * k / (N - 1)))
        p = TMP / f'{slug}_{k}.png'; sc.render.filepath = str(p); bpy.ops.render.render(write_still=True); tiles.append(str(p))
    rows.append((f"{slug}  id {m['id']}  {m['duration']:.2f}s{' loop' if m['loop'] else ''}  [{m['name']}]", tiles))
rj = TMP / 'rows.json'; rj.write_text(json.dumps(rows))
subprocess.run(['python', __file__, '--sheet', str(rj), str(OUT)], check=True)
