"""face_tears.py <face_slug> [--color #4FA8F0] - classic Roblox cry faces draw tears in BLACK (creator: "vegeta tears are black lol").
Recolors the tear drops of a library face blue: dark blobs at the sides of the face (centre x < 30 % or > 70 % of the width) between
the eye line and the mouth bottom. The original is kept as face_orig.png (re-runs start from it). Run once per cry face, then rebuild.
  python tools/face_tears.py whaaaaaa"""
import argparse, glob, json, os, shutil
from collections import deque
import numpy as np
from PIL import Image

ENG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def blobs(mask):
    H, W = mask.shape; seen = np.zeros_like(mask); out = []
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]: continue
        q = deque([(y, x)]); seen[y, x] = 1; pts = []
        while q:
            cy, cx = q.popleft(); pts.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not seen[ny, nx]: seen[ny, nx] = 1; q.append((ny, nx))
        out.append(np.array(pts))
    return out


def tint(slug, color):
    d = next(p for p in glob.glob(os.path.join(ENG, 'assets', 'faces', f'*_{slug}')) if os.path.isdir(p))
    meta = json.load(open(os.path.join(d, 'meta.json'), encoding='utf-8'))
    src = os.path.join(d, 'face_orig.png')
    if not os.path.exists(src): shutil.copy(os.path.join(d, 'face.png'), src)
    a = np.array(Image.open(src).convert('RGBA')); H, W = a.shape[:2]
    y0 = meta.get('eyes', [0.25, 0.5])[0] * H; y1 = meta.get('mouth', [0, 0, 0, 0.85])[3] * H
    dark = (a[..., 3] > 40) & (a[..., :3].astype(int).sum(-1) < 250)
    rgb = np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)]); n = 0
    for p in blobs(dark):
        cy, cx = p[:, 0].mean(), p[:, 1].mean()
        if len(p) > 20 and (cx < 0.3 * W or cx > 0.7 * W) and y0 <= cy <= y1:
            a[p[:, 0], p[:, 1], :3] = rgb; n += 1
    Image.fromarray(a).save(os.path.join(d, 'face.png'))
    print(f'{slug}: {n} tear blobs -> {color}')
    assert n, 'no tear blobs found (face has no side drops?)'
    return n


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('slug'); ap.add_argument('--color', default='#4FA8F0'); x = ap.parse_args()
    tint(x.slug, x.color)
