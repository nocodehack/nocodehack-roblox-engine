"""outfit_fetch.py - classic Roblox Shirt/Pants templates -> assets/outfits/<id>_<kind>_<slug>/{template.png, meta.json}.
Route (assetdelivery now answers 401 for ALL clothing, thumbnails are renders not templates): catalog search is public, the template
image id comes from Studio (InsertService:LoadAsset, logged in), the pixels from the public thumbnails API (Image thumbnail 700x669 = the
template; Studio's own cache only holds a 72x68 LOD, so it is NOT used).
  python tools/outfit_fetch.py queue shirt "school uniform" [--tag school] [--n 4]   catalog search -> research/outfits/queue.txt
  (paste tools/outfit_batch.luau with IDS from the queue into Studio via MCP execute_luau)
  python tools/outfit_fetch.py collect                                              Studio log OUTFITJSON rows -> assets/outfits/
Only non-blank templates with the 585:559 aspect are kept; duplicates (same template) skipped."""
import json, os, re, sys, time, urllib.request, urllib.parse
from pathlib import Path

E = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
OUT = E / 'assets' / 'outfits'; Q = E / 'research' / 'outfits' / 'queue.json'
UA = {'User-Agent': 'roblox-engine-outfit-fetch/1.0'}
SUB = {'shirt': 'ClassicShirts', 'pants': 'ClassicPants'}


def get(url, tries=4):
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
        except Exception as e:
            if k == tries - 1: raise
            time.sleep(4 * (k + 1))


def slug(s):
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')[:24] or 'x'


def queue(kind, kw, tag, n):
    url = 'https://catalog.roblox.com/v1/search/items/details?' + urllib.parse.urlencode(
        {'category': 'Clothing', 'subcategory': SUB[kind], 'keyword': kw, 'limit': 30})
    q = json.loads(Q.read_text(encoding='utf-8')) if Q.exists() else {}
    have = {p.name.split('_')[0] for p in OUT.glob('*_*')}
    new = [x for x in json.loads(get(url)).get('data', []) if x.get('itemType') == 'Asset' and str(x['id']) not in have and str(x['id']) not in q][:n]
    for x in new: q[str(x['id'])] = {'kind': kind, 'name': x['name'], 'tag': tag}
    Q.parent.mkdir(parents=True, exist_ok=True); Q.write_text(json.dumps(q, indent=1, ensure_ascii=False), encoding='utf-8')
    print(kw, [x['id'] for x in new])


def log_rows():
    lg = max((Path(os.environ['LOCALAPPDATA']) / 'Roblox' / 'logs').glob('*Studio*'), key=lambda p: p.stat().st_mtime); rows = {}
    for ln in lg.read_text(encoding='utf-8', errors='replace').splitlines():
        i = ln.find('OUTFITJSON ')
        if i >= 0: r = json.loads(ln[i + 11:]); rows[r['id']] = r
    return list(rows.values())


def thumb(tid):
    """Template image asset id -> thumbnail 'Image' 700x669 PNG = the template itself (alpha kept), public, no login."""
    d = json.loads(get(f'https://thumbnails.roblox.com/v1/assets?assetIds={tid}&size=700x700&format=Png'))['data'][0]
    return get(d['imageUrl']) if d.get('imageUrl') else None


def collect():
    import io
    from PIL import Image
    q = json.loads(Q.read_text(encoding='utf-8')) if Q.exists() else {}
    seen = {json.loads(m.read_text(encoding='utf-8')).get('template_id') for m in OUT.glob('*_*/meta.json')}
    have = {p.name.split('_')[0] for p in OUT.glob('*_*')}
    for r in log_rows():
        if r['id'] in have: continue
        if r.get('err') or not r.get('tpl') or not r.get('kind'): print('SKIP', r['id'], str(r.get('err'))[:60]); continue
        tid = re.sub(r'\D', '', r['tpl'])
        if tid in seen: print('DUP', r['id']); continue
        try: raw = thumb(tid); im = Image.open(io.BytesIO(raw)).convert('RGBA')
        except Exception as e: print('NOIMG', r['id'], e); continue
        if abs(im.size[0] / im.size[1] - 585 / 559) > 0.02 or im.convert('L').getextrema()[1] < 8: print('BAD', r['id'], im.size); continue
        info = q.get(r['id'], {}); name = info.get('name') or r.get('name', r['id'])
        d = OUT / f"{r['id']}_{r['kind']}_{slug(name)}"; d.mkdir(parents=True, exist_ok=True); im.save(d / 'template.png')
        (d / 'meta.json').write_text(json.dumps({'id': r['id'], 'name': name, 'kind': r['kind'], 'tags': [info['tag']] if info.get('tag') else [], 'template_id': tid}, indent=1, ensure_ascii=False), encoding='utf-8')
        seen.add(tid); print('OK', d.name); time.sleep(0.3)


if __name__ == '__main__':
    a = sys.argv[1:]; opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    if a[0] == 'queue': queue(a[1], a[2], opt('--tag', ''), int(opt('--n', 4)))
    else: collect()
