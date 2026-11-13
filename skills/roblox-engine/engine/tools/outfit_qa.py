"""outfit_qa.py - turntable sheet of every library outfit on a stock R6 character (front, 3/4, side, back).
  blender -b --factory-startup --offline-mode -P tools/outfit_qa.py -- [--out assets/outfits/sheet.jpg] [--n 0]
Shirts are shown over the default blue pants, pants under a plain white shirt. Labels: tag + id. Sheet is stitched by system python."""
import sys, math, json, subprocess
from pathlib import Path
E = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(E))
T, C = 150, 6


def sheet(rows_json, out):
    from PIL import Image, ImageDraw
    rows = json.loads(Path(rows_json).read_text()); R = (len(rows) + C - 1) // C
    img = Image.new('RGB', (C * T * 2, R * (T + 14)), (20, 20, 24)); dr = ImageDraw.Draw(img)
    for r, (name, tiles) in enumerate(rows):
        x, y = (r % C) * T * 2, (r // C) * (T + 14); dr.text((x + 3, y + 1), name, fill=(160, 230, 160))
        for k, j in enumerate((0, 1)): img.paste(Image.open(tiles[j]).convert('RGB').resize((T, T)), (x + k * T, y + 14))
    img.save(out, quality=85); print('SHEET', out, len(rows))


if '--sheet' in sys.argv:
    sheet(sys.argv[2], sys.argv[3]); sys.exit()
import bpy
from mathutils import Vector
import rig, look, outfits
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = Path(argv[argv.index('--out') + 1]) if '--out' in argv else E / 'assets' / 'outfits' / 'sheet.jpg'
TMP = E / 'trace' / '_outfitqa'; TMP.mkdir(exist_ok=True); S = rig.S
rows = []
for d in sorted(outfits.DIR.glob('*_*/meta.json'), key=lambda p: (json.loads(p.read_text(encoding='utf-8'))['kind'], p.parent.name)):
    meta = json.loads(d.read_text(encoding='utf-8')); tp = d.parent / 'template.png'
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene; look.tier(sc, 'draft'); sc.render.resolution_percentage = 100; sc.render.resolution_x = sc.render.resolution_y = 300
    sc.world = bpy.data.worlds.new('w'); sc.world.color = (0.75, 0.78, 0.82); sc.display.shading.background_type = 'WORLD'; sc.view_settings.view_transform = 'Standard'
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam; cam.data.lens = 60
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN')); sc.collection.objects.link(sun); sun.rotation_euler = (0.9, 0.3, 0.6); sun.data.energy = 3
    ch = rig.make('Q', (0, 0), 0, shirt='#EEEEEE' if meta['kind'] == 'pants' else '#C4281C')
    outfits.apply(ch, shirt=tp if meta['kind'] == 'shirt' else None, pants=tp if meta['kind'] == 'pants' else None)
    ctr = Vector((0, 0, 3.0 * S)); tiles = []
    for yaw in (0, 35, 90, 180):
        a = math.radians(yaw); pos = ctr + Vector((math.sin(a), -math.cos(a), 0.1)) * 11 * S
        cam.location = pos; cam.rotation_euler = (ctr - pos).to_track_quat('-Z', 'Y').to_euler()
        p = TMP / f"{d.parent.name}_{yaw}.png"; sc.render.filepath = str(p); bpy.ops.render.render(write_still=True); tiles.append(str(p))
    rows.append((f"{meta['kind'][:2]} {(meta['tags'] or ['-'])[0]} {meta['id']}", tiles))
rj = TMP / 'rows.json'; rj.write_text(json.dumps(rows)); OUT.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(['python', __file__, '--sheet', str(rj), str(OUT)], check=True)
