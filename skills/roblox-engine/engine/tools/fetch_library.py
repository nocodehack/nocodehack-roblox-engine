"""fetch_library.py - rebuild the Roblox character libraries on THIS machine from the shipped id manifest (library/manifest/).
The public repo ships only ids + our own tags/placement (meta.json); meshes, textures, clothes and animation keys come from Roblox.
  python tools/fetch_library.py status                 what is missing per library
  python tools/fetch_library.py public                 faces + clothes from Roblox's public image API (no Studio needed)
  python tools/fetch_library.py jobs                   write the Studio jobs (Luau + MCP steps) to library/jobs/JOBS.md
  python tools/fetch_library.py collect hair           after the hair jobs ran in Studio: meshes/textures from Studio's cache
  python tools/fetch_library.py collect anims <file>.. after each anims job: the file the MCP saved its result to
  python tools/fetch_library.py collect set <id>       after that set's insert + export + mesh jobs ran in Studio
Studio jobs need Roblox Studio open (any place, Edit mode, logged in) with the Studio MCP connected. Nothing is saved or published."""
import io, json, re, shutil, sys, time, urllib.request, zipfile
from pathlib import Path

E = Path(__file__).resolve().parents[1]; A = E / 'assets'; MAN = E / 'library' / 'manifest'; JOBS = E / 'library' / 'jobs'
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
NEED = {'hair': ('mesh.obj', 'meta.json'), 'faces': ('face.png', 'meta.json'), 'outfits': ('template.png', 'meta.json'),
        'anims': ('anim.json', 'meta.json'), 'rbxsets': ('scene.json',)}
RBXMESH = 'https://github.com/PrintedScript/RBXMesh/archive/refs/heads/main.zip'   # AGPL: fetched here, never shipped
R6_RIG = 'https://devforum.roblox.com/t/r6-ik-fk-blender-rig-v25/3586405'


def manifest(kind):
    return sorted(d for d in (MAN / kind).iterdir() if d.is_dir()) if (MAN / kind).exists() else []


def complete(d, kind): return all((d / f).exists() for f in NEED[kind])


def missing(kind): return [m for m in manifest(kind) if not complete(A / kind / m.name, kind)]


def meta(m): return json.loads((m / 'meta.json').read_text(encoding='utf-8')) if (m / 'meta.json').exists() else {}


def seed(m, kind):
    """manifest folder -> assets/<kind>/<same name>/ with our meta (placement, tags) before the Roblox files arrive."""
    d = A / kind / m.name; d.mkdir(parents=True, exist_ok=True)
    for f in m.iterdir():
        if f.is_file() and not (d / f.name).exists(): shutil.copy2(f, d / f.name)
    return d


def unseed(kind):
    """remove folders a failed fetch left half-filled (the engine treats a folder as a usable library item)."""
    for m in manifest(kind):
        d = A / kind / m.name
        if d.exists() and not complete(d, kind): shutil.rmtree(d); print('INCOMPLETE (removed)', kind, m.name)


def status():
    for k in NEED:
        n, miss = len(manifest(k)), len(missing(k))
        print(f'{k:8s} {n - miss}/{n}' + ('' if not miss else f'  missing {miss}'))
    r6 = (A / 'r6_parts.blend').exists()
    print(f"r6 parts {'OK' if r6 else 'missing (optional: authentic head mesh; download the rig at ' + R6_RIG + ', then blender -b <rig .blend> --factory-startup -P tools/extract_r6_parts.py)'}")


def public():
    from PIL import Image
    from outfit_fetch import get, thumb
    for kind, key, fname in (('faces', 'texture_id', 'face.png'), ('outfits', 'template_id', 'template.png')):
        for m in missing(kind):
            tid = meta(m).get(key)
            try:
                im = Image.open(io.BytesIO(thumb(tid) if kind == 'outfits' else get(json.loads(get(
                    f'https://thumbnails.roblox.com/v1/assets?assetIds={tid}&size=420x420&format=Png'))['data'][0]['imageUrl']))).convert('RGBA')
            except Exception as e: print('FAIL', kind, m.name, str(e)[:80]); continue
            d = seed(m, kind); im.save(d / fname); print('OK', kind, m.name); time.sleep(0.25)
    status()


def chunks(xs, n): return [xs[i:i + n] for i in range(0, len(xs), n)]


def jobs():
    JOBS.mkdir(parents=True, exist_ok=True); steps = []
    hb = (E / 'tools' / 'hair_batch.luau').read_text(encoding='utf-8')
    for i, c in enumerate(chunks([meta(m)['id'] for m in missing('hair')], 8)):
        f = JOBS / f'hair_{i + 1:02d}.luau'; f.write_text(re.sub(r'local IDS = \{[^}]*\}', 'local IDS = {%s}' % ', '.join(c), hb, count=1), encoding='utf-8')
        steps.append(f'execute_luau (Edit) with the code of `{f.relative_to(E).as_posix()}`')
    if any(s.startswith('execute_luau') for s in steps): steps.append('`python tools/fetch_library.py collect hair`')
    am = [(m.name, meta(m)) for m in missing('anims')]
    packs = sorted({str(x['id']) for _, x in am if 'Creator Store' in x.get('source', '')})
    for p in packs: steps.append(f'insert_asset assetId {p}, parentPath game.Workspace.AnimImport, assetName imp_{p} (create the AnimImport Folder first with execute_luau if it is missing)')
    ad = (E / 'tools' / 'anim_dump.luau').read_text(encoding='utf-8'); size = 0; batch = []; parts = []
    for s, x in am:                                   # ~90 000 chars per call (the MCP file route keeps 100 000)
        est = 120 * int(x.get('keys', 100)) * (2 if 'Creator Store' in x.get('source', '') else 1)
        if batch and size + est > 90000: parts.append(batch); batch, size = [], 0
        batch.append((s, x)); size += est
    if batch: parts.append(batch)
    for i, b in enumerate(parts):
        lua = ', '.join('{slug = "%s", id = "%s", name = "%s"}' % (s, x['id'], x['name']) for s, x in b)
        f = JOBS / f'anims_{i + 1:02d}.luau'; f.write_text(re.sub(r'local JOBS = \{.*\}\}', 'local JOBS = {%s}' % lua, ad, count=1), encoding='utf-8')
        steps.append(f'execute_luau (Edit) with `{f.relative_to(E).as_posix()}` -> it returns a file path: `python tools/fetch_library.py collect anims <that file>`')
    ex, me = (E / 'tools' / 'rbx_set_export.luau').read_text(encoding='utf-8'), (E / 'tools' / 'rbx_set_meshes.luau').read_text(encoding='utf-8')
    for m in missing('rbxsets'):
        sid = m.name.split('_', 1)[0]
        steps.append(f'set {m.name}: insert_asset assetId {sid}, parentPath game.Workspace.SetImport, assetName imp_{sid} (create the SetImport Folder first if missing); '
                     f'execute_luau `tools/rbx_set_export.luau`; then execute_luau `tools/rbx_set_meshes.luau` with ID = "{sid}" and FROM/TO = 1/40, 41/80, ... '
                     f'until it reports nothing left (DESTROY = true on the last call); then `python tools/fetch_library.py collect set {sid}`')
    if packs: steps.append('execute_luau: `workspace.AnimImport:Destroy()` (the animation pack copy is not needed any more)')
    txt = '# Studio jobs (run in order, Roblox Studio open in Edit mode, Studio MCP connected; never save or publish the place)\n\n' + \
          ''.join(f'{i + 1}. {s}\n' for i, s in enumerate(steps)) + '\nAt the end: `python tools/fetch_library.py status`.\n'
    (JOBS / 'JOBS.md').write_text(txt, encoding='utf-8'); print(txt if steps else 'nothing to fetch from Studio')


def rbxmesh():
    """RBXMesh (AGPL) parses old .mesh versions; downloaded into the user's engine copy, never shipped."""
    tp = E / 'third_party'
    if (tp / 'RBXMesh' / 'RBXMesh.py').exists() or (E.parent / 'third_party' / 'RBXMesh').exists(): return
    z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(RBXMESH, timeout=60).read()))
    z.extractall(tp); (tp / 'RBXMesh-main').rename(tp / 'RBXMesh'); print('RBXMesh ->', tp / 'RBXMesh')


def collect_hair():
    rbxmesh(); sys.path.insert(0, str(E / 'third_party' / 'RBXMesh'))
    for m in missing('hair'): seed(m, 'hair')
    import hair_studio; hair_studio.collect('log'); unseed('hair'); status()


def collect_anims(files):
    want = {m.name: m for m in manifest('anims')}
    for fn in files:
        t = Path(fn).read_text(encoding='utf-8', errors='replace')
        t = t[t.index('{'):]; d, _ = json.JSONDecoder().raw_decode(t)
        for s, a in d.items():
            if s not in want: print('SKIP unknown', s); continue
            if a.get('err') or not a.get('kf'): print('FAIL', s, a.get('err')); continue
            kf, keys = a['kf'], int(meta(want[s]).get('keys') or 0)
            if keys and len(kf) > 1.6 * keys: kf = kf[::2] + ([kf[-1]] if (len(kf) - 1) % 2 else [])   # library keeps every 2nd key of baked clips
            dd = seed(want[s], 'anims'); (dd / 'anim.json').write_text(json.dumps({'kf': kf}, separators=(',', ':')), encoding='utf-8')
            print('OK anim', s, len(kf), 'keys')
    status()


def collect_set(sid):
    import rbx_set_import
    m = next((m for m in manifest('rbxsets') if m.name.startswith(sid + '_')), None)
    if not m: raise SystemExit(f'set {sid} is not in the manifest')
    rbx_set_import.fetch(sid, m.name.split('_', 1)[1]); seed(m, 'rbxsets'); status()


if __name__ == '__main__':
    a = sys.argv[1:] or ['status']
    if a[0] == 'status': status()
    elif a[0] == 'public': public()
    elif a[0] == 'jobs': jobs()
    elif a[:2] == ['collect', 'hair']: collect_hair()
    elif a[:2] == ['collect', 'anims']: collect_anims(a[2:])
    elif a[:2] == ['collect', 'set']: collect_set(a[2])
    else: print(__doc__)
