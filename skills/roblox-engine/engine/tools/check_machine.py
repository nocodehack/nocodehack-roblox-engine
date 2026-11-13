"""check_machine.py - preflight for a new machine: Blender, ffmpeg/ffprobe, Python packages, GPU, character libraries.
  python tools/check_machine.py        prints one line per check and exits 1 if a required one fails"""
import importlib.util, os, shutil, subprocess, sys
from pathlib import Path

E = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(E))
BL = os.environ.get('BLENDER', 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe')   # same default as story.py
LIBS = {'assets/r6_parts.blend': 'R6 body parts (tools/extract_r6_parts.py)', 'assets/hair': 'hair library', 'assets/faces': 'face library',
        'assets/outfits': 'clothes library', 'assets/anims': 'animation library', 'assets/rbxsets': 'Roblox sets'}


def run(cmd):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip().splitlines()[0]
    except Exception: return None


def main():
    bad = []
    def check(ok, name, fix, required=True):
        print(('OK   ' if ok else ('MISSING ' if required else 'WARN ')) + name + ('' if ok else f'  -> {fix}'))
        if required and not ok: bad.append(name)
    bl = shutil.which(BL) or (BL if os.path.exists(BL) else None)
    v = run([bl, '--version']) if bl else None
    check(bool(v), f'Blender ({v or BL})', 'install Blender 5.2 or set BLENDER=/path/to/blender')
    for t in ('ffmpeg', 'ffprobe'):
        check(bool(shutil.which(t)), t, f'install ffmpeg and put {t} on PATH')
    check(sys.version_info >= (3, 10), f'Python {sys.version.split()[0]}', 'use Python 3.10 or newer')
    for m, pip in (('numpy', 'numpy'), ('PIL', 'pillow')):
        check(importlib.util.find_spec(m) is not None, f'python package {pip}', f'pip install {pip}')
    gpu = run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader']) if shutil.which('nvidia-smi') else None
    check(bool(gpu), f'GPU ({gpu or "no NVIDIA GPU found"})', 'renders fall back to CPU (slow); AMD/Apple GPUs also work in Blender', required=False)
    for rel, what in LIBS.items():
        p = E / rel
        have = p.exists() and (p.is_file() or any(p.iterdir()))
        if rel == 'assets/r6_parts.blend':
            check(have, f'{what} ({rel})', 'optional: authentic head mesh, see tools/fetch_library.py status', required=False)
        else:   # Roblox libraries are required: they come from the user's Roblox Studio (tools/fetch_library.py)
            check(have, f'{what} ({rel})', 'run python tools/fetch_library.py status, then public + the Roblox Studio jobs')
    print('READY' if not bad else f'NOT READY: {len(bad)} missing')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
