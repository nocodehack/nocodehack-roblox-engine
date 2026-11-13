"""hair_studio.py - hairs the public endpoint refuses (HTTP 401) via Roblox Studio (logged in), no cookies touched.
1) Run tools/hair_batch.luau in Studio (MCP execute_luau, Edit) with IDS set; save its returned JSON to a file.
2) python tools/hair_studio.py collect <json> [--mark-ms N]
   Studio downloaded each mesh/texture into its content cache (%LOCALAPPDATA%/Roblox/rbx-storage files + rbx-storage.db rows);
   entries are matched to ids by the per-id time window from the Luau JSON -> assets/hair/<id>_<slug>/ mesh.obj, tex.png, meta.json.
Also refreshes placement meta (exact Studio CFrames) for hairs already fetched by hair_fetch.py."""
import json, os, re, sqlite3, shutil, struct, sys, tempfile
from pathlib import Path

E = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hair_fetch import mesh_to_obj, OUT

RBX = Path(os.environ['LOCALAPPDATA']) / 'Roblox'
SIGS = {b'version ': 'mesh', b'\xabKTX 20': 'ktx', b'\x89PNG': 'png'}
BC = {131: 'bc1', 132: 'bc1', 133: 'bc1', 134: 'bc1', 135: 'bc2', 136: 'bc2', 137: 'bc3', 138: 'bc3', 145: 'bc7', 146: 'bc7'}


def payload(b):
    """RBXH cache record -> (kind, body) by locating the body signature after the header."""
    for sig, kind in SIGS.items():
        i = b.find(sig, 0, 256)
        if i >= 0: return kind, b[i:]
    return None, None


def entries(t0, t1):
    """All cache payloads written in [t0, t1] ms: big ones are files, small ones live inline in the sqlite db."""
    got = []
    for f in (RBX / 'rbx-storage').glob('*/*'):
        if t0 <= f.stat().st_mtime * 1000 <= t1:
            k, body = payload(f.read_bytes())
            if k: got.append((k, body))
    tmp = Path(tempfile.mkdtemp())
    for ext in ('', '-wal', '-shm'):   # copy: Studio holds the live db open
        p = RBX / f'rbx-storage.db{ext}'
        if p.exists(): shutil.copy(p, tmp / f'db{ext}')
    c = sqlite3.connect(tmp / 'db')
    for content, in c.execute('select content from files where atime between ? and ? and content is not null', (t0, t1)):
        k, body = payload(content)
        if k: got.append((k, body))
    c.close()
    return got


def ktx2_png(b, path):
    """KTX2 (zstd supercompressed BCn, as Roblox ships textures) -> PNG of mip level 0."""
    import zstandard, texture2ddecoder as td
    from PIL import Image
    vk, _, w, h = struct.unpack('<IIII', b[12:28]); sc = struct.unpack('<I', b[44:48])[0]
    off, ln, uln = struct.unpack('<QQQ', b[80:104])
    data = b[off:off + ln]
    if sc == 2: data = zstandard.ZstdDecompressor().decompress(data, max_output_size=uln or w * h * 4)
    if vk in BC: rgba = getattr(td, 'decode_' + BC[vk])(data, w, h); mode = 'BGRA'
    elif vk in (37, 43): rgba = data; mode = 'RGBA'
    else: raise RuntimeError(f'ktx vkFormat {vk} not handled')
    Image.frombuffer('RGBA', (w, h), rgba, 'raw', mode, 0, 1).save(path)
    return w, h


def log_rows():
    """HAIRJSON lines printed by hair_batch.luau, from the newest Studio log (last row per id wins)."""
    lg = max((RBX / 'logs').glob('*Studio*'), key=lambda p: p.stat().st_mtime)
    rows = {}
    for ln in lg.read_text(encoding='utf-8', errors='replace').splitlines():
        i = ln.find('HAIRJSON ')
        if i >= 0: r = json.loads(ln[i + 9:]); rows[r['id']] = r
    return list(rows.values())


def collect(js, pad=400):
    rows = log_rows() if js == 'log' else json.loads(Path(js).read_text(encoding='utf-8'))
    done = {d.name.split('_', 1)[0] for d in OUT.glob('*_*') if (d / 'mesh.obj').exists() and (d / 'meta.json').exists() and 'att' in (d / 'meta.json').read_text()}
    if js == 'log': rows = [r for r in rows if r['id'] not in done]
    for r in rows:
        if r.get('err'): print('SKIP', r['id'], r['err'][:80]); continue
        slug = re.sub(r'[^a-z0-9]+', '_', (r.get('name') or r['id']).lower()).strip('_')[:40]
        old = sorted(OUT.glob(f"{r['id']}_*"))
        d = old[0] if old else OUT / f"{r['id']}_{slug}"; d.mkdir(parents=True, exist_ok=True)
        meta = json.loads((d / 'meta.json').read_text()) if (d / 'meta.json').exists() else {}
        meta.update({k: v for k, v in r.items() if k not in ('t0', 't1')}); meta['source'] = meta.get('source', 'studio')
        meshes, texs = [], []
        for k, body in entries(r['t0'] - pad, r['t1'] + pad):
            (meshes if k == 'mesh' else texs).append((k, body))
        if not (d / 'mesh.obj').exists():
            ok = None
            for _, body in sorted(meshes, key=lambda x: -len(x[1])):
                try: ok = mesh_to_obj(body, d / 'mesh.obj'); break
                except Exception as e: last = e
            if not ok:
                print('NOMESH', r['id'], slug, 'candidates', [m[1][:12] for m in meshes]); continue
            meta['verts'], meta['tris'] = ok
        if not (d / 'tex.png').exists() and texs:
            k, body = texs[0]
            if k == 'png': (d / 'tex.png').write_bytes(body)
            else: ktx2_png(body, d / 'tex.png')
        (d / 'meta.json').write_text(json.dumps(meta, indent=1))
        print('HAIR', r['id'], d.name, r.get('kind'), 'verts', meta.get('verts'), 'att', bool(meta.get('att')), 'tex', (d / 'tex.png').exists())


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'collect': collect(a[1])
