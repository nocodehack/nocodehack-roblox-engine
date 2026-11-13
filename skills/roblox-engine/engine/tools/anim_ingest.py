"""Studio dump file(s) (JSON {slug: {id, loop, pri, kf}} + padding) -> assets/anims/<slug>/anim.json + meta.json.
python tools/anim_ingest.py <dump.txt> [--src default|<name>]"""
import json, pathlib, sys
root = pathlib.Path(__file__).resolve().parent.parent / 'assets' / 'anims'
src = sys.argv[sys.argv.index('--src') + 1] if '--src' in sys.argv else 'Roblox default R6 Animate'
t = open(sys.argv[1], encoding='utf8').read()
t = t[t.index('{'):] if not t.startswith('{') else t
d, _ = json.JSONDecoder().raw_decode(t)
for k, a in d.items():
    p = root / k; p.mkdir(parents=True, exist_ok=True)
    kf = a.pop('kf')
    if not a.get('name'): a['name'] = k
    json.dump({'kf': kf}, open(p / 'anim.json', 'w'), separators=(',', ':'))
    meta = {'id': a['id'], 'name': a['name'], 'source': a.get('source', src), 'duration': kf[-1]['t'], 'loop': a['loop'], 'priority': a.get('pri')}
    json.dump(meta, open(p / 'meta.json', 'w'), indent=1)
    print(k, meta['id'], meta['duration'], len(kf), 'loop' if meta['loop'] else '')
