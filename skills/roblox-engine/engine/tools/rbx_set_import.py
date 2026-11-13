"""rbx_set_import.py - Roblox Studio model -> Blender set (Roblox's Creator Store library as engine sets).
Pipeline (see LIBRARY.md):
  1. insert the model in Studio (MCP insert_asset -> workspace.SetImport.imp_<id>), run tools/rbx_set_export.luau (parts -> Studio log lines
     'RBXSET|id|chunk|json') and tools/rbx_set_meshes.luau (per-mesh time windows 'RBXMESH|id|json').
  2. python tools/rbx_set_import.py fetch <id> [slug]   -> assets/rbxsets/<id>_<slug>/ scene.json + meshes/*.obj + textures/*.png
  3. build(dir, at, rot, scale) inside Blender (sets.rbx_set wraps it), or
     blender -b --factory-startup -P tools/rbx_set_import.py -- build <dir> out.blend
Axes: Roblox (x right, y up, z back) -> Blender (x, -z, y); 1 stud = 0.5 m (S). Asserted by selftest(): a 4x1x2 block is 2 x 1 x 0.5 m... see _p.
Meshes come from Studio's content cache by time window (tools/hair_studio.py logic), decals/textures that are not in the cache from the public
thumbnails API. Unions cannot be exported (AssetId unreadable): they become their bounding box. CornerWedge apex corner is approximate."""
import json, math, os, re, sys, time, urllib.request
from pathlib import Path

E = Path(__file__).resolve().parents[1]
OUT = E / 'assets' / 'rbxsets'
S = 0.5
PX = (0, 1, 2)
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(E))


def _p(v):
    """Roblox vector (x, y, z) in studs -> Blender metres (x, -z, y) * S. numpy (n,3) or tuple."""
    import numpy as np
    a = np.asarray(v, float)
    return np.stack([a[..., 0], -a[..., 2], a[..., 1]], -1) * S


def asset_num(s):
    m = re.search(r'(\d{4,})', s or '')
    return m.group(1) if m else None


# ------------------------------------------------------------------ fetch (plain python)
def studio_log():
    import hair_studio as hs
    return max((hs.RBX / 'logs').glob('*Studio*'), key=lambda p: p.stat().st_mtime)


def parse_log(aid):
    """Last complete dump of set `aid` from the newest Studio log -> (parts, end_meta, mesh_rows)."""
    parts, end, rows = [], None, []
    for ln in studio_log().read_text(encoding='utf-8', errors='replace').splitlines():
        i = ln.find('RBXSET|' + aid + '|')
        if i >= 0:
            _, _, ch, js = ln[i:].split('|', 3)
            if ch == '0': parts, end = [], None
            try:
                if ch == 'END': end = json.loads(js)
                elif ch != 'ERR': parts += json.loads(js)
            except ValueError: print('LOG LINE CUT', ln[:50])
            continue
        i = ln.find('RBXMESH|' + aid + '|')
        if i >= 0: rows.append(json.loads(ln[i:].split('|', 2)[2]))
    return parts, end, rows


def cache_candidates(t0, t1):
    """(mtime_ms, kind, body) of every content-cache payload written/read in [t0, t1]."""
    import hair_studio as hs, shutil, sqlite3, tempfile
    got = []
    for f in (hs.RBX / 'rbx-storage').glob('*/*'):
        t = f.stat().st_mtime * 1000
        if t0 <= t <= t1:
            k, body = hs.payload(f.read_bytes())
            if k: got.append((t, k, body))
    tmp = Path(tempfile.mkdtemp())
    for ext in ('', '-wal', '-shm'):
        p = hs.RBX / f'rbx-storage.db{ext}'
        if p.exists(): shutil.copy(p, tmp / f'db{ext}')
    c = sqlite3.connect(tmp / 'db')
    for t, content in c.execute('select atime, content from files where atime between ? and ? and content is not null', (t0, t1)):
        k, body = hs.payload(content)
        if k: got.append((t, k, body))
    c.close(); shutil.rmtree(tmp, ignore_errors=True)
    return got


def obj_bbox(path):
    import numpy as np
    v = np.array([[float(x) for x in l.split()[1:4]] for l in open(path) if l.startswith('v ')])
    return v.min(0), v.max(0)


def get(url, tries=3):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=40).read()
        except Exception as e:
            err = e; time.sleep(1 + i)
    raise err


def thumb_png(aid, path):
    """Image/decal asset id -> PNG via the public thumbnails API (alpha kept). Returns False when Roblox has no image."""
    try:
        d = json.loads(get(f'https://thumbnails.roblox.com/v1/assets?assetIds={aid}&size=420x420&format=Png&returnPolicy=PlaceHolder'))['data'][0]
        if not d.get('imageUrl') or d.get('state') not in ('Completed', None): return False
        b = get(d['imageUrl'])
        if len(b) < 200: return False
        Path(path).write_bytes(b); return True
    except Exception:
        return False


def fetch(aid, slug=None):
    import hair_studio as hs
    from hair_fetch import mesh_to_obj
    parts, end, rows = parse_log(aid)
    if not parts or not end: raise SystemExit(f'no complete RBXSET dump for {aid} in {studio_log().name}')
    slug = slug or re.sub(r'[^a-z0-9]+', '_', end['name'].lower()).strip('_')[:30]
    d = OUT / f'{aid}_{slug}'; (d / 'meshes').mkdir(parents=True, exist_ok=True); (d / 'textures').mkdir(exist_ok=True)
    need = {}                                       # mesh id -> expected MeshSize (or None)
    for p in parts:
        if p.get('mesh') and p['mesh']['id']: need[asset_num(p['mesh']['id'])] = p['mesh']['ms']
        if p.get('sm') and p['sm']['id']: need.setdefault(asset_num(p['sm']['id']), None)
    meshes, textures, bad = {}, {}, []
    for f in (d / 'meshes').glob('*.obj'): meshes[f.stem] = f'meshes/{f.name}'     # keep what an earlier fetch already got
    for f in (d / 'textures').glob('*.png'): textures[f.stem] = f'textures/{f.name}'
    for r in rows:                                  # cache windows: mesh (+ texture) per row
        mid, tid = asset_num(r['mesh']), asset_num(r.get('tex'))
        if mid in meshes or mid is None: continue
        cands = sorted(cache_candidates(r['t0'] - 100, r['t1'] + 100), key=lambda c: abs(c[0] - r['t0'] - 150))
        for t, k, body in cands:
            if k != 'mesh': continue
            f = d / 'meshes' / f'{mid}.obj'
            try: mesh_to_obj(body, f)
            except Exception: continue
            lo, hi = obj_bbox(f); want = need.get(mid)
            if want and any(abs((hi[i] - lo[i]) - want[i]) > 0.04 * max(want[i], 0.1) for i in range(3)): f.unlink(); continue
            meshes[mid] = f'meshes/{mid}.obj'; break
        else: bad.append(mid)
        if tid and tid not in textures:
            for t, k, body in cands:
                if k == 'mesh': continue
                f = d / 'textures' / f'{tid}.png'
                try:
                    if k == 'png': f.write_bytes(body)
                    else: hs.ktx2_png(body, f)
                    textures[tid] = f'textures/{tid}.png'; break
                except Exception: continue
    miss = [m for m in need if m not in meshes]
    if miss and rows:   # cache reads do not always touch atime: match the leftovers by bounding box among the recent cache entries
        pool = [c for c in cache_candidates(min(r['t0'] for r in rows) - 900000, max(r['t1'] for r in rows) + 60000) if c[1] == 'mesh']
        for mid in miss:
            want = need[mid]
            for t, k, body in sorted(pool, key=lambda c: -c[0]):
                f = d / 'meshes' / f'{mid}.obj'
                try: mesh_to_obj(body, f); lo, hi = obj_bbox(f)
                except Exception: continue
                if want and all(abs((hi[i] - lo[i]) - want[i]) <= 0.04 * max(want[i], 0.1) for i in range(3)):
                    meshes[mid] = f'meshes/{mid}.obj'; bad = [b for b in bad if b != mid]; break
                f.unlink()
    # every image still missing (decals, SurfaceAppearance, mesh textures not in cache) from the thumbnails API
    want_img = set()
    for p in parts:
        for dc in p.get('d', []): want_img.add(asset_num(dc['id']))
        if p.get('mesh') and p['mesh'].get('tex'): want_img.add(asset_num(p['mesh']['tex']))
        if p.get('sm') and p['sm'].get('tex'): want_img.add(asset_num(p['sm']['tex']))
        if p.get('sa') and p['sa'].get('col'): want_img.add(asset_num(p['sa']['col']))
    for i in sorted(x for x in want_img if x and x not in textures):
        f = d / 'textures' / f'{i}.png'
        if thumb_png(i, f): textures[i] = f'textures/{i}.png'
    scene = {'id': aid, 'slug': slug, 'name': end['name'], 'stats': end['stats'], 'parts': parts, 'meshes': meshes, 'textures': textures}
    (d / 'scene.json').write_text(json.dumps(scene), encoding='utf-8')
    print(f"FETCH {aid} {slug}: parts {len(parts)} meshes {len(meshes)}/{len(need)} (bad {bad}) images {len(textures)}/{len(want_img - {None})}")
    import subprocess
    subprocess.run([sys.executable, str(E / 'tools' / 'rbx_set_doc.py'), d.name], cwd=E, check=True)
    return d


# ------------------------------------------------------------------ Blender builder
def _srgb(c):
    return [((x / 255) / 12.92 if x / 255 <= .04045 else (((x / 255) + .055) / 1.055) ** 2.4) for x in c]


# roughness, metallic, emission strength per Roblox material
MAT = {'SmoothPlastic': (.3, 0, 0), 'Plastic': (.5, 0, 0), 'Neon': (.4, 0, 4), 'Glass': (.05, 0, 0), 'Wood': (.6, 0, 0), 'WoodPlanks': (.6, 0, 0),
       'Metal': (.35, .8, 0), 'DiamondPlate': (.35, .8, 0), 'CorrodedMetal': (.6, .5, 0), 'Foil': (.15, 1, 0), 'Marble': (.15, 0, 0),
       'Granite': (.5, 0, 0), 'Ice': (.1, 0, 0), 'Fabric': (.95, 0, 0), 'Concrete': (.9, 0, 0), 'Brick': (.85, 0, 0), 'Cobblestone': (.8, 0, 0),
       'Slate': (.7, 0, 0), 'Grass': (.95, 0, 0), 'Sand': (1, 0, 0), 'Pebble': (.9, 0, 0), 'ForceField': (.2, 0, 1)}
_MC = {}
SEATS = ('Seat', 'VehicleSeat')


def material(key):
    """key = ('flat', rgb, mat, tr, refl) | ('tex', png, rgb, mat, tr)."""
    import bpy
    try:
        if key in _MC and _MC[key].name in bpy.data.materials: return _MC[key]
    except ReferenceError:  # Factory resets invalidate material pointers between scene builds.
        pass
    kind = key[0]; rgb, mat, tr = key[1 if kind == 'flat' else 2], key[2 if kind == 'flat' else 3], key[3 if kind == 'flat' else 4]
    rough, metal, emit = MAT.get(mat, (.55, 0, 0))
    m = bpy.data.materials.new(f'rbx_{mat}_{len(_MC)}'); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']; col = (*_srgb(rgb), 1)
    b.inputs['Roughness'].default_value = rough; b.inputs['Metallic'].default_value = metal
    if 'Specular IOR Level' in b.inputs: b.inputs['Specular IOR Level'].default_value = .15
    alpha = 1 - tr
    if mat == 'Glass': alpha = min(alpha, .25) if tr < .5 else alpha
    if kind == 'tex':
        t = m.node_tree.nodes.new('ShaderNodeTexImage'); t.image = bpy.data.images.load(key[1]); t.interpolation = 'Linear'
        m.node_tree.links.new(t.outputs['Color'], b.inputs['Base Color'])
        if t.image.channels == 4 or True: m.node_tree.links.new(t.outputs['Alpha'], b.inputs['Alpha'])
        if emit: m.node_tree.links.new(t.outputs['Color'], b.inputs['Emission Color']); b.inputs['Emission Strength'].default_value = emit
        b.inputs['Alpha'].default_value = alpha
        if alpha < 1: pass
    else:
        b.inputs['Base Color'].default_value = col; b.inputs['Alpha'].default_value = alpha
        if emit: b.inputs['Emission Color'].default_value = col; b.inputs['Emission Strength'].default_value = emit
    if hasattr(m, 'surface_render_method'): m.surface_render_method = 'DITHERED'
    _MC[key] = m
    return m


def _fix_out(v, f):
    """Flip triangles that face the centroid (convex pieces)."""
    import numpy as np
    c = v.mean(0); a, b, d = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    n = np.cross(b - a, d - a); inward = (n * ((a + b + d) / 3 - c)).sum(1) < 0
    f = f.copy(); f[inward] = f[inward][:, ::-1]
    return f


def g_box(sz):
    import numpy as np
    h = np.array(sz) / 2; v = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], float) * h
    f = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
    return v, _fix_out(v, f), np.ones(12, bool)


def g_wedge(sz):
    import numpy as np
    a, b, c = np.array(sz) / 2
    v = np.array([[-a, -b, -c], [a, -b, -c], [a, -b, c], [-a, -b, c], [-a, b, c], [a, b, c]], float)
    f = np.array([[0, 1, 2], [0, 2, 3], [3, 2, 5], [3, 5, 4], [0, 1, 5], [0, 5, 4], [0, 3, 4], [1, 5, 2]])
    return v, _fix_out(v, f), np.ones(8, bool)


def g_corner(sz):
    import numpy as np
    a, b, c = np.array(sz) / 2   # shortcut: apex corner (-x, +z) is a guess, the exact Roblox corner is not documented, fix if a story needs it
    v = np.array([[-a, -b, -c], [a, -b, -c], [a, -b, c], [-a, -b, c], [-a, b, c]], float)
    f = np.array([[0, 1, 2], [0, 2, 3], [3, 2, 4], [0, 3, 4], [0, 1, 4], [1, 2, 4]])
    return v, _fix_out(v, f), np.ones(6, bool)


def g_ball(sz, nu=16, nv=10):
    import numpy as np
    v = [[0, 0, -1]]; f = []
    for j in range(1, nv):
        th = math.pi * j / nv
        for i in range(nu):
            ph = 2 * math.pi * i / nu; v.append([math.sin(th) * math.cos(ph), -math.cos(th), math.sin(th) * math.sin(ph)])
    v = [[0, -1, 0]] + [p for p in v[1:]] + [[0, 1, 0]]
    top = len(v) - 1
    for i in range(nu):
        f.append([0, 1 + (i + 1) % nu, 1 + i])
        f.append([top, 1 + (nv - 2) * nu + i, 1 + (nv - 2) * nu + (i + 1) % nu])
    for j in range(nv - 2):
        for i in range(nu):
            a = 1 + j * nu + i; b = 1 + j * nu + (i + 1) % nu
            f += [[a, b, a + nu], [b, b + nu, a + nu]]
    v = np.array(v, float) * (np.array(sz) / 2); f = np.array(f)
    return v, _fix_out(v, f), np.zeros(len(f), bool)


def g_cyl(sz, axis=0, n=24):
    """Roblox Part cylinder: axis = local X (Size.X long, Y/Z diameter); SpecialMesh cylinder: axis Y."""
    import numpy as np
    L, d1, d2 = (sz[axis], sz[(axis + 1) % 3], sz[(axis + 2) % 3])
    ring = [[math.cos(2 * math.pi * i / n) * d1 / 2, math.sin(2 * math.pi * i / n) * d2 / 2] for i in range(n)]
    v, f, sharp = [], [], []
    for z in (-L / 2, L / 2):
        for r in ring: v.append([r[0], r[1], z])
    for i in range(n):
        a, b = i, (i + 1) % n; f += [[a, b, n + b], [a, n + b, n + a]]; sharp += [False, False]
    for z, base in ((-L / 2, 2 * n), (L / 2, 3 * n + 1)):     # separate cap rings so the side normals stay smooth
        v.append([0, 0, z]); ci = len(v) - 1
        for r in ring: v.append([r[0], r[1], z])
        for i in range(n): f.append([ci, ci + 1 + (i + 1) % n, ci + 1 + i]); sharp.append(True)
    v = np.array(v, float)
    # (k, l, axis) -> local xyz: ring plane = (axis+1, axis+2), length along axis
    out = np.zeros_like(v); out[:, axis] = v[:, 2]; out[:, (axis + 1) % 3] = v[:, 0]; out[:, (axis + 2) % 3] = v[:, 1]
    return out, _fix_out(out, np.array(f)), np.array(sharp)


FACE = {   # NormalId -> (normal, right, up) in Roblox local axes, viewed from outside
    'Front': ((0, 0, -1), (-1, 0, 0), (0, 1, 0)), 'Back': ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    'Right': ((1, 0, 0), (0, 0, -1), (0, 1, 0)), 'Left': ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
    'Top': ((0, 1, 0), (1, 0, 0), (0, 0, -1)), 'Bottom': ((0, -1, 0), (1, 0, 0), (0, 0, 1))}


def g_face(sz, face, tile=None):
    """Quad on a part face (decal / texture), 2 cm off the surface; UV tiles by studs when `tile`."""
    import numpy as np
    n, r, u = (np.array(x, float) for x in FACE[face])
    h = np.array(sz) / 2; w_ = abs(r) @ np.array(sz); h_ = abs(u) @ np.array(sz)
    c = n * (abs(n) @ h + 0.03)
    v = np.array([c - r * w_ / 2 - u * h_ / 2, c + r * w_ / 2 - u * h_ / 2, c + r * w_ / 2 + u * h_ / 2, c - r * w_ / 2 + u * h_ / 2])
    f = np.array([[0, 1, 2], [0, 2, 3]])
    mu, mv = (w_ / tile[0], h_ / tile[1]) if tile else (1, 1)
    uv = np.array([[0, 0], [mu, 0], [mu, mv], [0, mv]])
    return v, _fix_out(v, f), np.ones(2, bool), uv[f]


def read_obj(path):
    import numpy as np
    vs, ts, fs = [], [], []
    for l in open(path):
        if l.startswith('v '): vs.append(l.split()[1:4])
        elif l.startswith('vt '): ts.append(l.split()[1:3])
        elif l.startswith('f '): fs.append([int(x.split('/')[0]) - 1 for x in l.split()[1:4]])
    v = np.array(vs, float); f = np.array(fs, int)
    t = np.array(ts, float) if len(ts) == len(vs) else np.zeros((len(vs), 2))
    return v, f, t


class Acc:
    """Accumulates world-space triangles of one object (Blender metres), several materials."""
    def __init__(self): self.v, self.f, self.uv, self.sh, self.mi, self.mats, self.n = [], [], [], [], [], [], 0

    def add(self, v, f, uv, sharp, key):
        import numpy as np
        if key not in self.mats: self.mats.append(key)
        self.v.append(v); self.f.append(f + self.n); self.uv.append(uv); self.sh.append(sharp)
        self.mi.append(np.full(len(f), self.mats.index(key))); self.n += len(v)

    def empty(self): return not self.v


def _mesh(name, acc):
    import bpy, numpy as np
    v = np.concatenate(acc.v); f = np.concatenate(acc.f).astype(np.int32)
    me = bpy.data.meshes.new(name); me.from_pydata(v.tolist(), [], f.tolist()); me.update()
    uv = me.uv_layers.new(name='UVMap'); uv.data.foreach_set('uv', np.concatenate(acc.uv).reshape(-1, 2).ravel().astype(np.float32))
    me.attributes.new('sharp_face', 'BOOLEAN', 'FACE').data.foreach_set('value', np.concatenate(acc.sh).astype(bool))
    me.polygons.foreach_set('material_index', np.concatenate(acc.mi).astype(np.int32))
    for k in acc.mats: me.materials.append(material(k))
    return me


def _world_mat(cf):
    import numpy as np
    return np.array(cf[3:12], float).reshape(3, 3), np.array(cf[:3], float)


def build(sdir, at=(0, 0), rot=0.0, scale=1.0, label=None, register=True, ground=None):
    """Place the imported set `sdir` with its footprint centre at `at` (studs), floor on z = 0, rotated `rot` deg about Z.
    Returns dict(root, solids [PLACED dicts], bounds (x0, x1, y0, y1 m), counts, lights)."""
    import bpy, numpy as np
    import assets
    sdir = Path(sdir).resolve(); sc = json.loads((sdir / 'scene.json').read_text(encoding='utf-8'))
    label = label or sc['slug']
    meshes = {k: read_obj(sdir / v) for k, v in sc['meshes'].items()}
    tex = {k: str(sdir / v) for k, v in sc['textures'].items()}
    cnt = dict(parts=0, meshpart_ok=0, meshpart_box=0, union_box=0, decals=0, decals_skipped=0, hidden=0, solids=0, text_skipped=0)
    items = []        # (part, v_world_metres (n,3), f, uv, sharp, key)
    for p in sc['parts']:
        cnt['parts'] += 1
        if p['tr'] >= 0.99 and not p.get('d'): cnt['hidden'] += 1; continue
        R, pos = _world_mat(p['cf']); sz = p['sz']; c = p['c']; rgb = p['col']; mat = p['mat']
        key = ('flat', tuple(rgb), mat, round(p['tr'], 2), 0)
        zero = lambda f: np.zeros((len(f), 3, 2))
        geo = None
        if p.get('mesh') and asset_num(p['mesh']['id']) in meshes:
            v, f, t = meshes[asset_num(p['mesh']['id'])]; lo, hi = v.min(0), v.max(0)
            lv = (v - (lo + hi) / 2) * (np.array(sz) / np.maximum(hi - lo, 1e-6))
            tid = asset_num(p['mesh'].get('tex')) or asset_num((p.get('sa') or {}).get('col'))
            if tid in tex: key = ('tex', tex[tid], (255, 255, 255), mat, round(p['tr'], 2))
            geo = (lv, f, t[f], np.zeros(len(f), bool)); cnt['meshpart_ok'] += 1
        elif p.get('sm') and p['sm']['t'] == 'FileMesh' and asset_num(p['sm']['id']) in meshes:
            v, f, t = meshes[asset_num(p['sm']['id'])]
            lv = v * np.array(p['sm']['sc']) + np.array(p['sm']['off'])
            tid = asset_num(p['sm'].get('tex'))
            if tid in tex: key = ('tex', tex[tid], (255, 255, 255), mat, round(p['tr'], 2))
            geo = (lv, f, t[f], np.zeros(len(f), bool)); cnt['meshpart_ok'] += 1
        else:
            if c == 'MeshPart' or (p.get('sm') and p['sm']['t'] == 'FileMesh'): cnt['meshpart_box'] += 1
            if p.get('un'): cnt['union_box'] += 1
            ssz = np.array(sz)
            smt = p['sm']['t'] if p.get('sm') else None
            if smt in ('Brick', 'Head', 'Sphere', 'Cylinder', 'Wedge'): ssz = ssz * np.array(p['sm']['sc'])
            shape = p.get('shape', 'Block')
            if c == 'WedgePart' or smt == 'Wedge': g = g_wedge(ssz)
            elif c == 'CornerWedgePart': g = g_corner(ssz)
            elif shape == 'Ball' or smt in ('Head', 'Sphere'): g = g_ball(ssz)
            elif shape == 'Cylinder': g = g_cyl(ssz, 0)
            elif smt == 'Cylinder': g = g_cyl(ssz, 1)
            else: g = g_box(ssz)
            geo = (g[0], g[1], zero(g[1]), g[2])
        lv, f, uv, sharp = geo
        if p['tr'] < .99: items.append((p, lv @ R.T + pos, f, uv, sharp, key))
        for dcl in p.get('d', []):
            did = asset_num(dcl['id'])
            if did not in tex: cnt['decals_skipped'] += 1; continue
            q = g_face(sz, dcl['f'], (dcl['u'], dcl['v']) if dcl.get('u') else None)
            cnt['decals'] += 1
            items.append((p, q[0] @ R.T + pos, q[1], q[3], q[2], ('tex', tex[did], tuple(dcl['col']), 'SmoothPlastic', round(dcl['tr'], 2))))
        if p.get('txt'): cnt['text_skipped'] += 1
    # set frame: footprint centre (excluding huge ground slabs), floor = top of the lowest large thin slab (else lowest bottom)
    allv = np.concatenate([it[1] for it in items]); wb = _p(allv)
    lo, hi = wb.min(0), wb.max(0)
    zfloor = lo[2]
    if ground is not None: zfloor = ground * S
    else:
        foot = (hi[0] - lo[0]) * (hi[1] - lo[1]); level = {}   # top height -> slab area there
        for it in items:
            w = _p(it[1]); a, b = w.min(0), w.max(0); th = b[2] - a[2]
            if th <= 1.0 and a[2] < lo[2] + 0.5 and b[2] < lo[2] + 1.5 and (b[0] - a[0]) * (b[1] - a[1]) > 0.01 * foot:
                level[round(float(b[2]), 2)] = level.get(round(float(b[2]), 2), 0.0) + (b[0] - a[0]) * (b[1] - a[1])
        # floor = the height MOST ground area sits at (a lawn of many patches beats one sidewalk slab: small_park had every
        # character knee-deep in grass, R191); only when that ground is a real floor (>= 25 % of the footprint in total)
        if level and max(level.values()) > 0.25 * foot: zfloor = max(level, key=level.get)
    org = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, zfloor])
    def ceiling(it):   # roofs/ceilings block the engine's lights and cameras: drop big parts above head height
        a, b = _p(it[1]).min(0) - org, _p(it[1]).max(0) - org
        return a[2] > 2.8 and (b[0] - a[0]) * (b[1] - a[1]) > 0.2 * (hi[0] - lo[0]) * (hi[1] - lo[1])
    n0 = len(items); items = [it for it in items if not ceiling(it)]; cnt['ceiling_dropped'] = n0 - len(items)
    ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    Rz = np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]])

    def world(vr):
        return ((_p(vr) - org) * scale) @ Rz.T + np.array([at[0] * S, at[1] * S, 0])

    root = bpy.data.objects.new(f'rbx_{label}', None); bpy.context.collection.objects.link(root)
    # group parts -> solid clusters (union-find on world AABBs) and one visual object per group
    info = []
    for it in items:
        w = world(it[1]); a, b = w.min(0), w.max(0)
        p = it[0]
        solid = bool(p['cc']) and p['tr'] < .99 and a[2] < 1.5 * scale
        big = (b[0] - a[0] > 6 * scale) or (b[1] - a[1] > 6 * scale)
        ground_like = (b[2] - a[2] <= .3 * scale or b[2] <= .02 * scale) and ((b[0] - a[0]) > 3 or (b[1] - a[1]) > 3)
        info.append((w, a, b, solid and not ground_like, big))
    uf = list(range(len(items)))

    def find(i):
        while uf[i] != i: uf[i] = uf[uf[i]]; i = uf[i]
        return i
    # decals belong to their part: same source part => same cluster
    byp = {}
    for i, it in enumerate(items): byp.setdefault(id(it[0]), []).append(i)
    ids = [i for i, x in enumerate(info) if x[3] and not x[4]]
    for i in ids:
        for j in ids:
            if j <= i: continue
            if items[i][0]['g'] != items[j][0]['g'] and not (items[i][0]['c'] in SEATS or items[j][0]['c'] in SEATS): continue   # a Seat joins the legs/back around it
            if info[i][1][0] < info[j][2][0] + .05 and info[j][1][0] < info[i][2][0] + .05 and info[i][1][1] < info[j][2][1] + .05 and info[j][1][1] < info[i][2][1] + .05 \
               and info[i][1][2] < info[j][2][2] + .05 and info[j][1][2] < info[i][2][2] + .05:
                uf[find(i)] = find(j)
    for lst in byp.values():
        for j in lst[1:]:
            if info[lst[0]][3] == info[j][3]: uf[find(j)] = find(lst[0]) if info[lst[0]][3] else uf[find(j)]
    clusters, vis = {}, {}
    for i, it in enumerate(items):
        if info[i][3] and not info[i][4]:
            # a decal rides with its part's cluster; a decal on a non-clustered part stays visual
            clusters.setdefault(find(i), []).append(i)
        elif info[i][3] and info[i][4]: clusters.setdefault(('big', i), []).append(i)
        else: vis.setdefault(it[0]['g'], []).append(i)
    seatbox = []   # Seat parts are usually invisible (Transparency 1): a solid cluster whose footprint holds one is a chair/sofa/bench
    for p in sc['parts']:
        if p['c'] in SEATS:
            R, pos = _world_mat(p['cf']); w = world(g_box(p['sz'])[0] @ R.T + pos); seatbox.append((w.min(0), w.max(0)))
    objs, solids = [], []
    gname = {}
    for p in sc['parts']: gname.setdefault(p['g'], p.get('gn') or f"g{p['g']}")
    for g, idx in vis.items():
        acc = Acc()
        for i in idx: acc.add(info[i][0], items[i][2], items[i][3], items[i][4], items[i][5])
        piv = bpy.data.objects.new(f'{label}_{gname[g]}', None); bpy.context.collection.objects.link(piv); piv.parent = root
        o = bpy.data.objects.new(f'{label}_{gname[g]}_vis', _mesh(f'{label}_{g}', acc)); bpy.context.collection.objects.link(o); o.parent = piv; objs.append(o)
    k = 0
    for cid, idx in clusters.items():
        g = items[idx[0]][0]['g']
        acc = Acc()
        for i in idx: acc.add(info[i][0], items[i][2], items[i][3], items[i][4], items[i][5])
        a = np.min([info[i][1] for i in idx], 0); b = np.max([info[i][2] for i in idx], 0)
        # a seat = a cluster over a Roblox Seat part, OR a named piece of sit-on furniture (beds have no Seat part: blind3 'no piece
        # white_bedroom_seat', R174)
        names_ = ' '.join(gname[items[i][0]['g']].lower() for i in idx)   # every part's model name (beds come as 'Model' + 'blanket')
        named_seat = any(w_ in names_ for w_ in ('bed', 'sofa', 'couch', 'bench', 'chair', 'stool', 'seat', 'blanket', 'pillow', 'mattress'))             and float(b[2] - a[2]) < 1.6
        k += 1; nm = f"{label}_{'seat' if named_seat or any(a[0] < sb[1][0] and sb[0][0] < b[0] and a[1] < sb[1][1] and sb[0][1] < b[1] for sb in seatbox) else gname[g]}_{k}"
        piv = bpy.data.objects.new(nm, None); bpy.context.collection.objects.link(piv); piv.parent = root
        o = bpy.data.objects.new(nm + '_m', _mesh(nm, acc)); bpy.context.collection.objects.link(o); o.parent = piv; objs.append(o)
        # Match preset pieces: a useful base-centre origin, preserving every world-space vertex.
        from mathutils import Matrix, Vector
        centre = Vector(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, a[2]))
        piv.location = centre; o.data.transform(Matrix.Translation(-centre))
        top, hgt = float(b[2]), float(b[2] - a[2])
        if hgt > 0.3 * scale or (b[0] - a[0] > 1.0 and top > .3):
            ent = {'name': nm, 'pivot': piv, 'rect': (float(a[0]), float(b[0]), float(a[1]), float(b[1])), 'top': top, 'solid': True}
            solids.append(ent); cnt['solids'] += 1
            if register: assets.PLACED.append(ent)
    bpy.context.view_layer.update()
    # footprint bounds: walls/floor extent of the set in world metres
    wa = world(allv); bounds = (float(wa[:, 0].min()), float(wa[:, 0].max()), float(wa[:, 1].min()), float(wa[:, 1].max()))
    lights = []
    for p in sc['parts']:
        for l in p.get('lt', []):
            R, pos = _world_mat(p['cf']); lights.append({**l, 'at': world(pos[None])[0].tolist()})
    return {'root': root, 'solids': solids, 'bounds': bounds, 'counts': cnt, 'lights': lights, 'size_m': ((hi - lo) * scale).tolist(), 'objects': objs}


def selftest():
    """A 4 x 1 x 2 stud block (Roblox size x, y, z) must land 2 m along Blender x, 1 m along Blender y (Roblox z), 0.5 m tall (Roblox y)."""
    import numpy as np
    v, f, _ = g_box((4, 1, 2)); w = _p(v); d = w.max(0) - w.min(0)
    assert np.allclose(d, [2.0, 1.0, 0.5]), d
    # right-handed: Roblox +X x +Y = +Z (back) must stay Blender X x Z = -Y... i.e. determinant of the map is +1
    M = _p(np.eye(3)) / S
    assert abs(np.linalg.det(M) - 1) < 1e-9
    # a point 1 stud to the Roblox front (-z) lies 0.5 m along Blender +Y (engine front is -Y for cameras, characters face +Y at yaw 0 is checked in story)
    assert np.allclose(_p((0, 0, -1)), (0, .5, 0))
    return True


if __name__ == '__main__':
    a = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    if a[0] == 'selftest': print('selftest', selftest())
    elif a[0] == 'fetch': fetch(a[1], a[2] if len(a) > 2 else None)
    elif a[0] == 'build':
        import bpy
        selftest(); bpy.ops.wm.read_factory_settings(use_empty=True)
        r = build(a[1]); print('BUILD', r['counts'], 'bounds', r['bounds'])
        if len(a) > 2: bpy.ops.wm.save_as_mainfile(filepath=a[2])
