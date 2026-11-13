"""camera_stats.py <story dir> ... - camera language numbers of built stories (from scenes/sNN/log.txt + report.json):
shots, sizes, near-identical consecutive framings (same size + focus, < 3 studs and < 10 deg apart), pitched shots (|el| >= 12 deg: low / high / top >= 55), inserts, establishing, eyes~ / fg~ of each shot."""
import json, re, sys
from pathlib import Path
for d in sys.argv[1:]:
    for sd in sorted(Path(d).glob('scenes/s*')):
        log = (sd / 'log.txt').read_text(encoding='utf-8', errors='replace') if (sd / 'log.txt').exists() else ''
        rows = re.findall(r"^SHOT (S\d+ \w+) score (\S+) lens (\d+)(?: el (-?\d+))?", log, re.M)
        vis = json.loads((sd / 'report.json').read_text()).get('visibility', {}) if (sd / 'report.json').exists() else {}
        kinds = [n.split()[1] for n, *_ in rows]; el = [int(r[3]) for r in rows if r[3]]   # logs before R213 have no 'el'
        low, high, top = sum(e <= -12 for e in el), sum(12 <= e < 55 for e in el), sum(e >= 55 for e in el)
        eyes = {c.split()[0]: x for c, v in vis.items() for k, x in v.items() if k.endswith(' eyes~')}
        fg = {c.split()[0]: x for c, v in vis.items() for k, x in v.items() if k == 'fg~' and x > 0.1}
        pos = [[float(x) for x in m] for m in re.findall(r"^SHOT S\d+ \w+ score .*? pos studs \[(-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\]", log, re.M)]
        subj = [next(iter(v), '').split(' ')[0] for v in vis.values()]   # first measured key = the focus
        twins = [rows[i][0] for i in range(1, min(len(rows), len(pos), len(subj))) if kinds[i] == kinds[i - 1] and subj[i] == subj[i - 1]
                 and (not el or abs(el[i] - el[i - 1]) < 10) and sum((a - b) ** 2 for a, b in zip(pos[i], pos[i - 1])) ** 0.5 < 3.0]
        print(f"{Path(d).name} {sd.name}: {len(rows)} shots {dict((k, kinds.count(k)) for k in sorted(set(kinds)))} | low {low} high {high} top {top} "
              f"| el {el} | near-identical cuts {twins} | eyes~ {eyes} | fg~>0.1 {fg}")
