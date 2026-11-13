"""gallery.py [preset ...] - build a 2-character test scene in every rooms.py preset and render 3 look stills each
-> shorts/g_<preset>/out/look + one combined sheet trace/<stamp>_gallery.jpg. Regression bench for 'any story' sets."""
import json, subprocess, sys, time
from pathlib import Path
E = Path(__file__).resolve().parents[1]
BL = 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'
PRESETS = sys.argv[1:] or ['bedroom', 'kitchen', 'store', 'hallway', 'classroom2', 'street', 'park', 'living_room:night']
rows = []
for pr in PRESETS:
    name, _, time_ = pr.partition(':')
    d = E / 'shorts' / f'g_{name}{"_" + time_ if time_ else ""}'; d.mkdir(parents=True, exist_ok=True)
    st = {'preset': name}
    if time_: st['time'] = time_
    spec = {'title': f'gallery {pr}', 'seconds': 3, 'set': st,
            'cast': [{'name': 'Max', 'at': [-2.5, -4], 'yaw': -25, 'shirt': '#C4281C', 'hair': '#7A1212', 'face': 'smile'},
                     {'name': 'Lia', 'at': [2.5, -3.5], 'yaw': 25, 'shirt': '#2E9C9A', 'hair': '#E8A33D', 'face': 'grin'}],
            'beats': [{'t': 0.3, 'who': 'Max', 'pose': 'talk_a', 'look': 'Lia'}, {'t': 1.3, 'who': 'Lia', 'pose': 'shrug', 'look': 'Max'}],
            'shots': [{'t': 0, 'kind': 'wide', 'on': ['Max', 'Lia'], 'lens': 30}, {'t': 1.0, 'kind': 'medium', 'on': ['Max', 'Lia'], 'lens': 40},
                      {'t': 2.0, 'kind': 'close', 'on': ['Lia'], 'lens': 50}]}
    (d / 'short.json').write_text(json.dumps(spec, indent=1))
    r = subprocess.run([BL, '-b', '--factory-startup', '--offline-mode', '--python-exit-code', '1', '-P', str(E / 'build.py'), '--',
                        str(d / 'short.json'), '--tier', 'look', '--frames', '10', '36', '60'], capture_output=True, text=True, cwd=E)
    rep = [l for l in r.stdout.splitlines() if l.startswith('REPORT')]
    err = [l for l in (r.stdout + r.stderr).splitlines() if 'Error' in l and 'HIP' not in l][:3]
    print(pr, r.returncode, rep[0] if rep else 'NO REPORT', err)
    if r.returncode == 0: rows.append(d / 'out' / 'look')
stamp = time.strftime('%Y%m%d-%H%M%S'); out = E / 'trace' / f'{stamp}_gallery.jpg'
args, fc = [], ''
k = 0
for row in rows:
    for f in sorted(row.glob('*.png')):
        args += ['-i', str(f)]; fc += f'[{k}]scale=180:-2[v{k}];'; k += 1
if k:
    per = 3; lay = '|'.join(f'{(i % (per * 4)) * 180}_{(i // (per * 4)) * 320}' for i in range(k))
    fc += ''.join(f'[v{i}]' for i in range(k)) + f'xstack=inputs={k}:layout={lay}:fill=black'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *args, '-filter_complex', fc, str(out)])
    print('SHEET', out)
