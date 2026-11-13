"""faces_sheet.py <out.png> - every face kind (incl. *_talk twins) drawn on yellow tiles with labels, one sheet."""
import sys
from pathlib import Path
import bpy, numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import faces
out = sys.argv[sys.argv.index('--') + 1]
kinds = faces.KINDS; n = 256; cols = 7; rows = (len(kinds) + cols - 1) // cols
sheet = np.zeros((rows * n, cols * n, 4), np.float32); sheet[..., :3] = (0.96, 0.8, 0.19); sheet[..., 3] = 1
for i, k in enumerate(kinds):
    im = faces.image(k, n); px = np.array(im.pixels[:], np.float32).reshape(n, n, 4)
    r, c = rows - 1 - i // cols, i % cols; tile = sheet[r * n:(r + 1) * n, c * n:(c + 1) * n]
    a = px[..., 3:4]; tile[..., :3] = tile[..., :3] * (1 - a) + px[..., :3] * a
img = bpy.data.images.new('sheet', cols * n, rows * n); img.pixels.foreach_set(sheet.ravel())
img.filepath_raw = out; img.file_format = 'PNG'; img.save(); print('FACES', len(kinds), list(kinds))
