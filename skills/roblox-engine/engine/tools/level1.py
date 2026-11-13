r"""level1.py - LEVEL 1 test runner (LEVEL1.md). Gates on the cloud for every L1 story of a field, then the field checks.
  python tools/level1.py            all fields
  python tools/level1.py move       one field (move | face | cam | acc)
  python tools/level1.py move --local   gates locally (story.py --tier none) instead of the cloud
A test PASSES when every scene's REPORT is PASS and every scene's report.json["L1"] has ok == True with no failed check
(a field owner adds report["L1"] = {"ok": bool, "checks": {name: {"ok": bool, "value": ..., "limit": ...}}} in build.py).
Writes trace/L1_report.md (one row per test) and prints it."""
import json, subprocess, sys, time
from pathlib import Path

ENG = Path(__file__).resolve().parents[1]
FIELDS = ('move', 'face', 'cam', 'acc')


def tests(field=None):
    return sorted(d.name for d in (ENG / 'stories').iterdir()
                  if d.name.startswith('L1_') and (field is None or d.name.startswith(f'L1_{field}_')) and (d / 'story.json').exists())


def gates(names, local):
    if not names: return
    if local:
        for n in names:
            subprocess.run([sys.executable, str(ENG / 'story.py'), str(ENG / 'stories' / n / 'story.json'), '--tier', 'none'],
                           cwd=ENG, capture_output=True, text=True)
    else:
        out = ENG / 'trace' / f"L1_cloud_{time.strftime('%H%M')}.txt"
        with open(out, 'w', encoding='utf-8') as f:
            subprocess.run([sys.executable, str(ENG / 'tools' / 'cloud_regress.py'), *names], cwd=ENG, stdout=f, stderr=subprocess.STDOUT)


def verdict(name):
    sd = ENG / 'stories' / name / 'scenes'
    reps = sorted(sd.glob('s*/report.json')) if sd.exists() else []
    if not reps: return 'NOT RUN', ['no scene reports']
    why = []
    for r in reps:
        d = json.loads(r.read_text(encoding='utf-8'))
        errs = d.get('errors', [])   # report.json: 'gates' = 'PASS' or a FAIL line; 'errors' only when something failed
        if errs or str(d.get('gates', '')).strip() != 'PASS':
            why.append(f"{r.parent.name} gates: {'; '.join(map(str, errs))[:160] or str(d.get('gates'))[:160]}")
        l1 = d.get('L1')
        if not l1: why.append(f'{r.parent.name}: no L1 field checks'); continue
        fld = name.split('_')[1]   # a stage is judged on its OWN field checks (+ any crash); the final Level 1 run needs all
        mine = {k: v for k, v in l1.get('checks', {}).items() if k.startswith(fld + '.') or k.endswith('.crash')}
        if not mine: why.append(f'{r.parent.name}: no {fld} checks'); continue
        bad = [f"{k}={v.get('value')}" for k, v in mine.items() if not v.get('ok')]
        if bad: why.append(f"{r.parent.name} L1 fail: {', '.join(bad)[:200]}")
    return ('PASS' if not why else 'FAIL'), why


def main():
    a = sys.argv[1:]; field = next((x for x in a if x in FIELDS), None); local = '--local' in a
    names = tests(field)
    if '--no-run' not in a: gates(names, local)
    rows = [f"| test | verdict | why |", "|---|---|---|"]
    n_pass = 0
    for n in names:
        v, why = verdict(n); n_pass += v == 'PASS'
        rows.append(f"| {n} | {v} | {' / '.join(why)[:300]} |")
    head = f"# LEVEL 1 {field or 'all'} - {n_pass}/{len(names)} PASS ({time.strftime('%Y-%m-%d %H:%M')})"
    txt = head + '\n' + '\n'.join(rows) + '\n'
    (ENG / 'trace' / f"L1_report_{field or 'all'}.md").write_text(txt, encoding='utf-8')
    print(txt)


if __name__ == '__main__':
    main()
