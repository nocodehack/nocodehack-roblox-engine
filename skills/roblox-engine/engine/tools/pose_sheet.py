"""pose_sheet.py - every poses.LIB pose on one sheet (Workbench, 3/4 view), the hold frame after the settle.
  python tools/pose_sheet.py out.jpg [pose ...]      (plain Python: it runs Blender for the rows, then labels + stacks with PIL)
Evidence for pose-library changes: run before and after, compare the silhouettes."""
import sys, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try: import bpy
except ImportError:   # plain Python: render the rows in Blender, then label + stack them
    import os, subprocess
    from PIL import Image, ImageDraw
    BL = os.environ.get('BLENDER', 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe')
    out = Path(sys.argv[1]).resolve()
    r = subprocess.run([BL, '-b', '--factory-startup', '--offline-mode', '--python-exit-code', '1', '-P', __file__, '--', str(out)] + sys.argv[2:], capture_output=True, text=True)
    rows = [l.split('|') for l in r.stdout.splitlines() if l.startswith('ROW|')]
    assert r.returncode == 0 and rows, (r.stdout + r.stderr)[-2000:]
    sheet = Image.new('RGB', (2000, 250 * len(rows)), 'white')
    for k, (_, p, names) in enumerate(rows):
        im = Image.open(p).convert('RGB'); d = ImageDraw.Draw(im)
        for i, nm in enumerate(names.split(',')): d.text((i * 200 + 6, 4), nm, fill=(255, 255, 255))
        sheet.paste(im, (0, 250 * k)); im.close(); os.remove(p)
    sheet.save(out, quality=88); print('POSE_SHEET', out); sys.exit(0)
import rig, poses, interact as ia, fight   # fight adds its MOVES to the LIB (not shown here)

args = sys.argv[sys.argv.index('--') + 1:]
out = Path(args[0]).resolve(); names = args[1:] or [k for k in poses.LIB if k not in fight.MOVES]
PER = 10
for r0 in range(0, len(names), PER):
    row = names[r0:r0 + PER]
    bpy.ops.wm.read_factory_settings(use_empty=True); rig.CAST.clear(); ia.reset()
    sc = bpy.context.scene; sc.render.fps = 24
    for i, nm in enumerate(row):
        ch = rig.make(f'P{i}', (i * 7.0, 0), 0, shirt='#2E6FB0', pants='#22303C', hair_style='none')
        poses.beat(sc, ch, nm, 10, move=4)
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
    cam.data.type = 'ORTHO'; cam.data.ortho_scale = PER * 3.5
    cx = (PER - 1) * 3.5 / 2
    cam.location = (cx + 4.0, -20, 2.75); cam.rotation_euler = (math.radians(86), 0, math.radians(11.3))   # 3/4: depth reads
    sc.render.engine = 'BLENDER_WORKBENCH'; sc.display.shading.light = 'STUDIO'; sc.display.shading.color_type = 'MATERIAL'
    sc.display.shading.show_shadows = False; sc.render.resolution_x = 2000; sc.render.resolution_y = 250
    sc.frame_set(16); p = out.with_name(f'{out.stem}_row{r0}.png'); sc.render.filepath = str(p)
    bpy.ops.render.render(write_still=True)
    print('ROW|' + str(p) + '|' + ','.join(row))
