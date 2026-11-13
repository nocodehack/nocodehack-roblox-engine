"""hair_qa.py - QA every library hair on a stock R6 character: 4-view turntable (front, 3/4, side, back) + numbers.
  blender -b --factory-startup --offline-mode -P tools/hair_qa.py -- [ids... | all] [--color #3A2A1E] [--out assets/hair/sheet.jpg]
Checks per hair (printed as one QA line, PASS/WARN):
  face   = share of the 3x3 face grid (mouth..eye rows) hidden by the hair from a front eye-level camera (bangs). WARN > 0.34
  eyes   = same for the eye row only. WARN > 0.67 (anime fringes may cover some of it)
  torso  = share of hair vertices inside the torso box (hair through the body). WARN > 0.02
  float  = rays up from the head centre: first hair surface above the head top. INFO only (shell meshes are open underneath; the
           eye check on the sheet found no visible gaps where this read 0.6 stud)
Library sheet: one row per hair, 4 views + id label -> --out (and trace/<time>_hair_sheet.jpg)."""
import sys, math, time, json, subprocess
from pathlib import Path
E = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(E))


def sheet(rows_json, out):
    """System python (Blender's has no PIL): rows.json -> labelled library sheet."""
    from PIL import Image, ImageDraw
    rows = json.loads(Path(rows_json).read_text()); T, C = 190, 5     # grid: per hair front + 3/4 + back, 5 hairs per row
    img = Image.new('RGB', (C * T * 3, ((len(rows) + C - 1) // C) * (T + 16)), (20, 20, 24)); dr = ImageDraw.Draw(img)
    for r, (name, warn, tiles) in enumerate(rows):
        x, y = (r % C) * T * 3, (r // C) * (T + 16)
        dr.text((x + 4, y + 2), name + (' WARN ' + ','.join(warn) if warn else ''), fill=(255, 200, 80) if warn else (160, 230, 160))
        for k, j in enumerate((0, 1, 3)): img.paste(Image.open(tiles[j]).convert('RGB').resize((T, T)), (x + k * T, y + 16))
    Path(out).parent.mkdir(parents=True, exist_ok=True); img.save(out, quality=85)
    tr = E / 'trace' / f"{time.strftime('%Y%m%d-%H%M%S')}_hair_sheet.jpg"; img.save(tr, quality=85)
    print('SHEET', out, tr, f'{len(rows)} hairs')


if '--sheet' in sys.argv:
    sheet(sys.argv[2], sys.argv[3]); sys.exit()
import bpy
from mathutils import Vector
import rig, look
from bpy_extras.object_utils import world_to_camera_view

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
def opt(k, d):
    return argv[argv.index(k) + 1] if k in argv else d
COL = opt('--color', '#3A2A1E'); OUT = Path(opt('--out', str(E / 'assets' / 'hair' / 'sheet.jpg')))
ids = [a for a in argv if not a.startswith('--') and a not in (COL, str(OUT), opt('--out', ''))]
dirs = sorted(d for d in (E / 'assets' / 'hair').glob('*_*') if (d / 'mesh.obj').exists())
if ids and ids != ['all']: dirs = [d for d in dirs if d.name.split('_', 1)[0] in ids]
TMP = E / 'trace' / '_hairqa'; TMP.mkdir(exist_ok=True)
S = rig.S


def scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene; look.tier(sc, 'draft')    # same shading as story drafts
    sc.render.resolution_x = sc.render.resolution_y = 320; sc.render.resolution_percentage = 100
    sc.world = bpy.data.worlds.new('w'); sc.world.color = (0.75, 0.78, 0.82); sc.display.shading.background_type = 'WORLD'
    sc.view_settings.view_transform = 'Standard'   # factory AgX renders the Workbench sheet too dark
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
    cam.data.lens = 60
    return sc, cam


def aim(cam, pos, tgt):
    cam.location = pos; cam.rotation_euler = (tgt - pos).to_track_quat('-Z', 'Y').to_euler()


def checks(sc, cam, ch, hair):
    bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
    hm = ch.head_mesh; M = hm.matrix_world
    lo_ = Vector([min(c[i] for c in hm.bound_box) for i in range(3)]); hi_ = Vector([max(c[i] for c in hm.bound_box) for i in range(3)])
    P = cam.matrix_world.translation; hid = {};
    for b in (-0.36, -0.14, 0.1):
        for a in (-0.3, 0.0, 0.3):
            w = M @ Vector(((lo_.x + hi_.x) / 2 + a * (hi_.x - lo_.x), lo_.y, (lo_.z + hi_.z) / 2 + b * (hi_.z - lo_.z)))
            d = w - P; hit, _, _, _, obj, _ = sc.ray_cast(dg, P, d.normalized(), distance=d.length - 0.02)
            hid.setdefault(b, []).append(bool(hit and obj == hair))
    face = sum(sum(v) for v in hid.values()) / 9; eyes = sum(hid[0.1]) / 3
    t = ch.torso; tl = [t.matrix_world @ Vector(c) for c in t.bound_box]
    tlo = Vector([min(c[i] for c in tl) for i in range(3)]); thi = Vector([max(c[i] for c in tl) for i in range(3)])
    vs = [hair.matrix_world @ v.co for v in hair.data.vertices]
    torso = sum(all(tlo[i] < v[i] < thi[i] for i in range(3)) for v in vs) / max(len(vs), 1)
    top = (M @ Vector((0, 0, hi_.z))).z
    o = M.translation.copy(); hits = []   # rays up from the head centre (crown and 4 tilts): first hair surface above the head top
    for dx, dy in ((0, 0), (0.3, 0), (-0.3, 0), (0, 0.3), (0, -0.3)):
        hit, loc, _, _, obj, _ = sc.ray_cast(dg, o, Vector((dx, dy, 1)).normalized(), distance=4 * S)
        while hit and obj != hair:
            hit, loc, _, _, obj, _ = sc.ray_cast(dg, loc + Vector((dx, dy, 1)).normalized() * 1e-3, Vector((dx, dy, 1)).normalized(), distance=4 * S)
        if hit: hits.append(loc.z)
    flo = (min(hits) - top) / S if hits else 9.9   # 9.9 = no hair over the head at all
    return face, eyes, torso, flo


def main():
    rows = []; t0 = time.time()
    for d in dirs:
        sc, cam = scene()
        ch = rig.make('Q', (0, 0), 0, hair=COL, hair_style='lib:' + d.name.split('_', 1)[0])
        hair = next(o for o in ch.hair_pivot.children if o.name.startswith('hair lib'))
        head = ch.head.matrix_world.translation.copy()
        aim(cam, head + Vector((0, -7 * S, 0)), head)
        face, eyes, torso, flo = checks(sc, cam, ch, hair)
        warn = [k for k, bad in (('face', face > 0.34), ('eyes', eyes > 0.67), ('torso', torso > 0.02), ('float', False)) if bad]
        print(f"QA {'WARN ' + ','.join(warn) if warn else 'PASS'} {d.name} face {face:.2f} eyes {eyes:.2f} torso {torso:.3f} float {flo:.2f}st verts {len(hair.data.vertices)}")
        tiles = []
        for k, yaw in enumerate((0, 35, 90, 180)):
            a = math.radians(yaw); off = Vector((math.sin(a), -math.cos(a), 0.12)) * 8 * S
            aim(cam, head + off + Vector((0, 0, -0.35 * S)), head + Vector((0, 0, -0.45 * S)))
            p = TMP / f'{d.name}_{k}.png'; sc.render.filepath = str(p); bpy.ops.render.render(write_still=True); tiles.append(p)
        rows.append((d.name, warn, tiles))
    rj = TMP / 'rows.json'; rj.write_text(json.dumps([(n, w, [str(p) for p in t]) for n, w, t in rows]))
    subprocess.run(['python', __file__, '--sheet', str(rj), str(OUT)], check=True)
    print(f'QA done {len(rows)} hairs {time.time() - t0:.0f}s')

main()
