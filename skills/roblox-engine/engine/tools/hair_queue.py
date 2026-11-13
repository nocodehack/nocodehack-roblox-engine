"""hair_queue.py - catalog keyword search -> research/hair/studio/queue.txt (ids for hair_batch.luau), skipping ids already in assets/hair.
  python tools/hair_queue.py "goku hair" "vegeta hair" ... [--n 5]"""
import json, sys, urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hair_fetch import get, OUT, E
a = sys.argv[1:]; n = int(a[a.index('--n') + 1]) if '--n' in a else 5
kws = [k for k in a if not k.startswith('--') and k != str(n)]
have = {d.name.split('_', 1)[0] for d in OUT.glob('*_*')}
q = E / 'research' / 'hair' / 'studio' / 'queue.txt'; seen = set(q.read_text().split()) if q.exists() else set()
new = []
for k in kws:
    d = json.loads(get('https://catalog.roblox.com/v1/search/items/details?' + urllib.parse.urlencode({'Keyword': k, 'Limit': 30})))
    got = [str(x['id']) for x in d.get('data', []) if x.get('itemType') == 'Asset' and x.get('assetType') in (8, 41)]
    got = [i for i in got if i not in have and i not in seen and i not in new][:n]
    print(k, got); new += got
with open(q, 'a') as f: f.write('\n'.join(new) + '\n')
print('QUEUE +', len(new), '->', q)
