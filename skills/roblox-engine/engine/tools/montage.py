"""montage.py out.jpg img1 img2 ... : side-by-side contact sheet (each image scaled to height 640)."""
import sys
from PIL import Image
ims = [Image.open(p).convert('RGB') for p in sys.argv[2:]]
ims = [i.resize((int(i.width * 640 / i.height), 640)) for i in ims]
s = Image.new('RGB', (sum(i.width for i in ims), 640)); x = 0
for i in ims: s.paste(i, (x, 0)); x += i.width
s.save(sys.argv[1], quality=88)
