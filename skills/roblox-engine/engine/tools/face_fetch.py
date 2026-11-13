"""face_fetch.py - classic Roblox Face accessories -> assets/faces/<id>_<slug>/{face.png, meta.json}.
Route (catalog search no longer lists classic faces): face ids from public face-code lists (research/faces/cands.txt 'id name'),
texture image id from Studio (InsertService:LoadAsset -> Decal.Texture; research/faces/tex.txt 'id|texid'), pixels from the public
thumbnails API for that IMAGE id (real texture, alpha kept). Tags come from research/faces/tags.json (id -> [emotion, talk_pair_id|null]).
  python tools/face_fetch.py fetch     download every face.png (skips existing) and write meta.json (emotion from tags.json if present)"""
import io, json, re, sys, time, urllib.request
from pathlib import Path
from PIL import Image

E = Path(__file__).resolve().parents[1]; R = E / 'research' / 'faces'; OUT = E / 'assets' / 'faces'
UA = {'User-Agent': 'roblox-engine-face-fetch/1.0'}


def get(url, tries=5):
    for k in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
        except Exception:
            if k == tries - 1: raise
            time.sleep(3 * (k + 1))


def slug(s):
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')[:24] or 'x'


def fetch():
    names = dict(l.strip().split(' ', 1) for l in (R / 'cands.txt').read_text(encoding='utf-8').splitlines() if l.strip())
    tex = dict(l.strip().split('|') for l in (R / 'tex.txt').read_text().splitlines() if l.strip())
    tags = json.loads((R / 'tags.json').read_text(encoding='utf-8')) if (R / 'tags.json').exists() else {}
    used = set()
    for fid, name in names.items():
        s = slug(name) if re.search('[a-z0-9]', name.lower()) else 'sym' + fid[-4:]
        while s in used: s += '2'
        used.add(s); d = OUT / f'{fid}_{s}'
        if not (d / 'face.png').exists():
            try:
                j = json.loads(get(f'https://thumbnails.roblox.com/v1/assets?assetIds={tex[fid]}&size=420x420&format=Png'))['data'][0]
                im = Image.open(io.BytesIO(get(j['imageUrl']))).convert('RGBA')
            except Exception as e: print('FAIL', fid, name, e); continue
            d.mkdir(parents=True, exist_ok=True); im.save(d / 'face.png'); time.sleep(0.2)
        emo, pair = tags.get(fid, [None, None])
        (d / 'meta.json').write_text(json.dumps({'id': fid, 'name': name, 'slug': s, 'texture_id': tex[fid], 'emotion': emo, 'talk_pair': pair}, indent=1, ensure_ascii=False), encoding='utf-8')
        print('OK', d.name)


if __name__ == '__main__': fetch()
