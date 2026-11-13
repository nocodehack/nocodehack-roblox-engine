"""rbx_set_sheet.py - evidence sheet for the imported Roblox sets: per set a Cycles look still (9:16 medium-wide, one standing R6 character
for scale) next to the Studio thumbnail. Plain python:  python tools/rbx_set_sheet.py [tag ...]  -> assets/rbxsets/sheet.jpg + <set>/preview.jpg
Blender worker (one set):  blender -b --factory-startup --offline-mode -P tools/rbx_set_sheet.py -- <set dir>"""
import json, math, subprocess, sys
from pathlib import Path
E = Path(__file__).resolve().parents[1]
BL = 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'


def worker(sdir):
    sys.path.insert(0, str(E)); sys.path.insert(0, str(E / 'tools'))
    import bpy, assets, rig, look, sets
    from mathutils import Vector
    bpy.ops.wm.read_factory_settings(use_empty=True); assets.reset()
    sc = bpy.context.scene
    r = sets.rbx_set(Path(sdir).name.split('_')[0], (0, 0), 0, 1, {'outdoor': 'park' in sdir})
    x0, x1, y0, y1 = r['bounds']; S = 0.5
    look.apply(sc, 'auto', r['info'])
    obs = assets.obstacles()
    free = lambda x, y: not any(a - .5 < x < b + .5 and c - .5 < y < d + .5 and t > .3 for a, b, c, d, t in obs) and x0 + .6 < x < x1 - .6 and y0 + .6 < y < y1 - .6
    cx = (x0 + x1) / 2; D = y1 - y0
    spot = None   # the clear spot nearest the front third of the set centre line
    for dy in [0.35 * D + k * .5 for k in sorted(range(-8, 9), key=abs)]:
        for dx in [0, 1, -1, 2, -2, 3, -3]:
            if free(cx + dx, y0 + dy): spot = (cx + dx, y0 + dy); break
        if spot: break
    spot = spot or (cx, y0 + .3 * D)
    for q in assets.PLACED:   # the sheet camera stands inside the front wall: hide whatever is a thin wall right there
        if q['rect'][3] < y0 + 1.0 or q['rect'][1] < x0 + 1.0 and False:
            for o in q['pivot'].children_recursive: o.hide_render = True
    ch = rig.make('Max', (spot[0] / S, spot[1] / S), 0)
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
    cam.data.lens = 12; cam.data.sensor_fit = 'VERTICAL'
    Wd = x1 - x0; cy = y0 - min(0.45 * Wd, 22)      # outside the (hidden) front wall, high enough to see over the furniture
    cam.location = (cx, cy, 1.6 + 0.12 * Wd); tgt = Vector((cx, (y0 + y1) / 2, 0.6))
    cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler()
    look.tier(sc, 'look'); sc.render.resolution_x, sc.render.resolution_y = 540, 960; sc.render.resolution_percentage = 100
    sc.cycles.samples = 48; sc.render.filepath = str(Path(sdir) / 'preview.png'); bpy.ops.render.render(write_still=True)
    (Path(sdir) / 'counts.json').write_text(json.dumps(r['info']['counts'])); print('SHEET_OK', sdir, 'char at', spot, 'bounds', r['bounds'], r['info']['counts'])


def main(tags):
    from PIL import Image, ImageDraw
    sys.path.insert(0, str(E / 'tools'))
    import rbx_set_import as ri
    root = E / 'assets' / 'rbxsets'
    dirs = [d for d in sorted(root.iterdir()) if (d / 'scene.json').exists() and (not tags or any(t in d.name for t in tags))]
    rows = []
    for d in dirs:
        r = subprocess.run([BL, '-b', '--factory-startup', '--offline-mode', '--python-exit-code', '1', '-P', __file__, '--', str(d)], capture_output=True, text=True, cwd=E)
        out = [l for l in r.stdout.splitlines() if l.startswith('SHEET_OK')]
        print(d.name, r.returncode, out[0][:200] if out else (r.stdout + r.stderr)[-600:])
        if r.returncode: continue
        im = Image.open(d / 'preview.png').convert('RGB'); im.save(d / 'preview.jpg', quality=88)
        th = d / 'thumb.png'
        if not th.exists(): ri.thumb_png(d.name.split('_')[0], th)
        rows.append((d, im, th))
    CW, CH, per = 600, 700, 4   # cell: still 360x640 + Studio thumbnail 240x240 + counts text
    nrow = (len(rows) + per - 1) // per; sheet = Image.new('RGB', (per * CW, nrow * CH), (20, 20, 20)); dr = ImageDraw.Draw(sheet)
    for i, (d, im, th) in enumerate(rows):
        ox, oy = (i % per) * CW, (i // per) * CH
        sheet.paste(im.resize((360, 640)), (ox + 4, oy + 50))
        if th.exists():
            t = Image.open(th).convert('RGB'); t.thumbnail((232, 232)); sheet.paste(t, (ox + 368, oy + 50))
        sc = json.loads((d / 'scene.json').read_text()); st = sc['stats']; ct = json.loads((d / 'counts.json').read_text()) if (d / 'counts.json').exists() else {}
        dr.text((ox + 6, oy + 6), d.name[:60], fill=(255, 255, 255))
        dr.text((ox + 6, oy + 24), f"Studio parts {st['parts']} mesh {st['mesh']} union {st['union']} decal {st['decal']} scripts {st['scripts']}", fill=(200, 200, 120))
        for j, (k, v) in enumerate(ct.items()): dr.text((ox + 368, oy + 300 + 14 * j), f'{k}: {v}', fill=(170, 220, 170))
    sheet.save(root / 'sheet.jpg', quality=85)
    print('SHEET', root / 'sheet.jpg')


if __name__ == '__main__':
    if '--' in sys.argv: worker(sys.argv[sys.argv.index('--') + 1])
    else: main(sys.argv[1:])
