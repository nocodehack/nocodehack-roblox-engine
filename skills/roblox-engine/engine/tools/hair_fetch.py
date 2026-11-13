"""hair_fetch.py - real Roblox hair accessories -> assets/hair/<id>_<slug>/ (mesh.obj with UVs, tex.png, meta.json).
  python tools/hair_fetch.py search "goku hair" [--n 6] [--creator Roblox]   keyword search in the Roblox catalog, fetch the top n
  python tools/hair_fetch.py id 376548738 [--name charmer]                   one accessory by asset id
Uses the public endpoints (no login): assetdelivery.roblox.com/v1/asset/?id=, catalog.roblox.com/v1/search/items/details.
Mesh parsing: third_party/RBXMesh (v1-v5, AGPL, kept outside the engine). meta.json holds what Roblox uses to place the hair:
SpecialMesh Scale/Offset and the Handle's HairAttachment CFrame (or the legacy AttachmentPoint)."""
import json, re, sys, time, struct, urllib.request, urllib.parse
from pathlib import Path

E = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = E / 'assets' / 'hair'
sys.path.insert(0, str(E.parent / 'third_party' / 'RBXMesh'))
UA = {'User-Agent': 'roblox-engine-hair-fetch/1.0'}


def get(url, tries=3):
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
        except Exception as e:
            if k == tries - 1: raise
            time.sleep(1.5 * (k + 1))


def asset(aid):
    return get(f'https://assetdelivery.roblox.com/v1/asset/?id={aid}')


def binary_rbxm_text(b):
    """Decompress a binary rbxm (LZ4 chunks) into one byte blob for regex scraping."""
    import lz4.block as lb
    p = 32; out = b''
    while p < len(b) - 16:
        name = b[p:p + 4]; clen, ulen = struct.unpack('<II', b[p + 4:p + 12]); p += 16
        raw = b[p:p + (clen or ulen)]; p += (clen or ulen)
        try: out += lb.decompress(raw, uncompressed_size=ulen) if clen else raw
        except Exception: pass
        if name == b'END\x00': break
    return out


def nums(block):
    return [float(x) for x in re.findall(r'<(?:X|Y|Z|R\d\d)>([^<]+)<', block)]


def parse_accessory(b):
    """-> dict(mesh_id, tex_id, scale, offset, att (12 floats, Handle-local HairAttachment CFrame) or None, attach_point)."""
    m = {'scale': [1, 1, 1], 'offset': [0, 0, 0], 'att': None, 'attach_point': None, 'mesh_id': None, 'tex_id': None, 'format': 'xml'}
    if b[:8] == b'<roblox!':
        t = binary_rbxm_text(b).decode('latin-1'); m['format'] = 'binary'
        ids = re.findall(r'(?:rbxassetid://|asset/\?id=)(\d+)', t)
        if ids: m['mesh_id'] = ids[0]
        if len(ids) > 1: m['tex_id'] = ids[1]
        return m
    t = b.decode('utf-8', 'replace')
    mi = re.search(r'name="MeshId"><url>[^<]*?(\d+)\s*</url>', t) or re.search(r'name="MeshID"><url>[^<]*?(\d+)\s*</url>', t)
    ti = re.search(r'name="TextureI[dD]"><url>[^<]*?(\d+)\s*</url>', t)
    m['mesh_id'] = mi.group(1) if mi else None; m['tex_id'] = ti.group(1) if ti else None
    sc = re.search(r'<Vector3 name="Scale">(.*?)</Vector3>', t, re.S); of = re.search(r'<Vector3 name="Offset">(.*?)</Vector3>', t, re.S)
    if sc: m['scale'] = nums(sc.group(1))
    if of: m['offset'] = nums(of.group(1))
    for it in re.finditer(r'<Item class="Attachment".*?</Item>', t, re.S):
        if re.search(r'name="Name">\w*(Hair|Hat)Attachment<', it.group(0)):
            cf = re.search(r'<CoordinateFrame name="CFrame">(.*?)</CoordinateFrame>', it.group(0), re.S)
            if cf: m['att'] = nums(cf.group(1)); m['att_name'] = re.search(r'name="Name">(\w+)<', it.group(0)).group(1)
            break
    ap = re.search(r'<CoordinateFrame name="AttachmentPoint">(.*?)</CoordinateFrame>', t, re.S)
    if ap: m['attach_point'] = nums(ap.group(1))
    return m


def chunked_mesh(b):
    """Roblox mesh v6/v7 (chunks: COREMESH v1 raw / v2 Draco, LODS) -> (verts, uvs, faces) of LOD0."""
    import numpy as np
    p = b.index(b'\n') + 1; core = lods = None
    while p + 16 <= len(b):
        name = b[p:p + 8].rstrip(b'\0'); ver, size = struct.unpack('<II', b[p + 8:p + 16]); data = b[p + 16:p + 16 + size]; p += 16 + size
        if name == b'COREMESH': core = (ver, data)
        elif name == b'LODS': lods = data
    ver, data = core
    if ver == 2:
        import DracoPy
        n = struct.unpack('<I', data[:4])[0]; m = DracoPy.decode(data[4:4 + n])
        v, f = np.asarray(m.points), np.asarray(m.faces).reshape(-1, 3)
        uv = np.asarray(m.tex_coord) if m.tex_coord is not None and len(m.tex_coord) else np.zeros((len(v), 2))
    else:   # v1: raw 40-byte vertices (pos, normal, uv, tangent, colour) then u32 faces
        nv = struct.unpack('<I', data[:4])[0]; vb = np.frombuffer(data[4:4 + nv * 40], np.uint8).reshape(nv, 40)
        v = vb[:, :12].copy().view('<f4').reshape(nv, 3); uv = vb[:, 24:32].copy().view('<f4').reshape(nv, 2)
        q = 4 + nv * 40; nf = struct.unpack('<I', data[q:q + 4])[0]; f = np.frombuffer(data[q + 4:q + 4 + nf * 12], '<u4').reshape(nf, 3)
    if lods and len(lods) >= 7:
        cnt = struct.unpack('<I', lods[3:7])[0]; offs = struct.unpack(f'<{cnt}I', lods[7:7 + 4 * cnt])
        if cnt > 1 and offs[1] > 0: f = f[offs[0]:offs[1]]
    return v, uv, f


def mesh_to_obj(mesh_bytes, path):
    """Roblox .mesh (v1-v7) -> OBJ (Roblox axes kept: x right, y up, z back; studs), LOD0 only, UVs flipped to OBJ convention."""
    if mesh_bytes[:9] in (b'version 6', b'version 7'):
        v, uv, f = chunked_mesh(mesh_bytes)
        with open(path, 'w') as o:
            o.writelines(f'v {a:.5f} {b:.5f} {c:.5f}\n' for a, b, c in v)
            o.writelines(f'vt {a:.5f} {1 - b:.5f}\n' for a, b in uv)
            o.writelines(f'f {a + 1}/{a + 1} {b + 1}/{b + 1} {c + 1}/{c + 1}\n' for a, b, c in f)
        return len(v), len(f)
    from RBXMesh import read_mesh_data
    md = read_mesh_data(mesh_bytes)
    faces = md.faces
    if getattr(md, 'LODs', None) and len(md.LODs) > 1: faces = md.faces[md.LODs[0]:md.LODs[1]]
    with open(path, 'w') as f:
        for v in md.vnts: f.write(f'v {v.vx:.5f} {v.vy:.5f} {v.vz:.5f}\n')
        for v in md.vnts: f.write(f'vt {v.tu:.5f} {1 - v.tv:.5f}\n')
        for fc in faces: f.write(f'f {fc.a + 1}/{fc.a + 1} {fc.b + 1}/{fc.b + 1} {fc.c + 1}/{fc.c + 1}\n')
    return len(md.vnts), len(faces)


def fetch(aid, name=None):
    acc = asset(aid); meta = parse_accessory(acc)
    slug = re.sub(r'[^a-z0-9]+', '_', (name or meta.get('name') or str(aid)).lower()).strip('_')[:40]
    d = OUT / f'{aid}_{slug}'; d.mkdir(parents=True, exist_ok=True)
    (d / 'accessory.rbxm').write_bytes(acc)
    if not meta['mesh_id']: raise RuntimeError('no mesh id found')
    nv, nf = mesh_to_obj(asset(meta['mesh_id']), d / 'mesh.obj')
    if meta['tex_id']: (d / 'tex.png').write_bytes(asset(meta['tex_id']))
    meta.update({'id': str(aid), 'name': name or slug, 'verts': nv, 'tris': nf})
    (d / 'meta.json').write_text(json.dumps(meta, indent=1))
    print('HAIR', aid, slug, meta['format'], 'verts', nv, 'tris', nf, 'att', 'yes' if meta['att'] else 'no', 'tex', bool(meta['tex_id']))
    return d


def search(keyword, n=6, creator=None):
    q = {'Keyword': keyword, 'Limit': 30}
    if creator: q['CreatorName'] = creator
    data = json.loads(get('https://catalog.roblox.com/v1/search/items/details?' + urllib.parse.urlencode(q)))
    items = [x for x in data.get('data', []) if x.get('itemType') == 'Asset' and x.get('assetType') in (8, 41)]
    got = []
    for x in items:
        if len(got) >= n: break
        try:
            got.append(fetch(x['id'], x.get('name'))); time.sleep(1.0)
        except Exception as e:
            print('SKIP', x['id'], x.get('name'), str(e)[:80])
    return got


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'search':
        n = int(a[a.index('--n') + 1]) if '--n' in a else 6
        cr = a[a.index('--creator') + 1] if '--creator' in a else None
        search(a[1], n, cr)
    elif a[0] == 'id':
        fetch(a[1], a[a.index('--name') + 1] if '--name' in a else None)
