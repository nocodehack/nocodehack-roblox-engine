"""Measure display RGB (Rec.709 luma, HSV saturation), per tile then averaged.

python tools/look_stats.py sheet.jpg --grid 8x2
python tools/look_stats.py video.mp4
The centre proxy is the central 30% of BOTH dimensions; it is not a face detector.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np


def stats(image, grid=(1, 1)):
    rgb = np.asarray(image, dtype=float) / 255
    cols, rows = grid
    h, w = rgb.shape[:2]
    if cols < 1 or rows < 1 or w < cols or h < rows:
        raise ValueError('grid must contain nonempty tiles')
    tiles = []
    for y in range(rows):
        for x in range(cols):
            a = rgb[y*h//rows:(y+1)*h//rows, x*w//cols:(x+1)*w//cols]
            luma = a @ np.array([.2126, .7152, .0722])
            hi, lo = a.max(2), a.min(2)
            sat = np.divide(hi-lo, hi, out=np.zeros_like(hi), where=hi > 0)
            th, tw = luma.shape
            centre = luma[int(th*.35):max(int(th*.35)+1, int(th*.65)),
                          int(tw*.35):max(int(tw*.35)+1, int(tw*.65))]
            tiles.append(dict(luminance=float(luma.mean()), saturation=float(sat.mean()),
                              dark_share=float((luma < .12).mean()), centre_luminance=float(centre.mean())))
    return dict(mean={k: float(np.mean([t[k] for t in tiles])) for k in tiles[0]}, tiles=tiles)


def measure(path, grid=(8, 2)):
    from PIL import Image
    path = Path(path)
    if path.suffix.lower() not in ('.mp4', '.mov', '.webm', '.mkv', '.avi'):
        with Image.open(path) as im:
            return stats(im.convert('RGB'), grid)
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'json', str(path)], check=True, capture_output=True, text=True)
    duration = float(json.loads(probe.stdout)['format']['duration'])
    if duration <= 0:
        raise ValueError('video has no duration')
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vf', f'fps=16/{duration}',
                        '-frames:v', '16', str(Path(td)/'%02d.png')], check=True)
        tiles = [measure(p, (1, 1))['mean'] for p in sorted(Path(td).glob('*.png'))]
    if not tiles:
        raise ValueError('video has no decoded frames')
    return dict(mean={k: float(np.mean([t[k] for t in tiles])) for k in tiles[0]}, tiles=tiles)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input'); p.add_argument('--grid', default='8x2')
    args = p.parse_args()
    try:
        grid = tuple(map(int, args.grid.lower().split('x')))
        if len(grid) != 2 or min(grid) < 1: raise ValueError()
    except ValueError:
        p.error('--grid must be positive COLSxROWS')
    print(json.dumps(measure(args.input, grid)['mean'], indent=2))
