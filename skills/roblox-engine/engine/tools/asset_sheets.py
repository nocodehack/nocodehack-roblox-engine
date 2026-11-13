"""asset_sheets.py <zips folder> - labelled contact sheets of every Kenney model (from the kits' own preview images) so a story
writer can pick set pieces/props BY EYE. Output: assets/kenney/sheets/<kit>_<page>.jpg (8 x 6 tiles, name under each)."""
import io, sys, zipfile, glob, os, json
from PIL import Image, ImageDraw, ImageFont
E = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(E, 'assets', 'kenney', 'sheets'); os.makedirs(OUT, exist_ok=True)
cat = json.load(open(os.path.join(E, 'assets', 'kenney', 'catalog.json')))
font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 13)
T, COLS, ROWS = 170, 8, 6
for z in sorted(glob.glob(os.path.join(sys.argv[1], '*.zip'))):
    kit = os.path.splitext(os.path.basename(z))[0]; zf = zipfile.ZipFile(z)
    models = sorted(e['file'][:-4] for e in cat if e['kit'] == kit and 'detailed' not in e['file'])
    pngs = {}
    for n in zf.namelist():
        if not n.lower().endswith('.png') or 'Textures' in n: continue
        stem = os.path.basename(n)[:-4]
        for suf in ('_SE', '_NE', '_SW', '_NW', ''):
            if stem.endswith(suf) and stem[:len(stem) - len(suf)] in models:
                key = stem[:len(stem) - len(suf)]
                if key not in pngs or suf == '_SE': pngs[key] = n
                break
    page = 0
    for i in range(0, len(models), COLS * ROWS):
        sheet = Image.new('RGB', (COLS * T, ROWS * (T + 18)), (245, 245, 245)); d = ImageDraw.Draw(sheet)
        for k, m in enumerate(models[i:i + COLS * ROWS]):
            x, y = (k % COLS) * T, (k // COLS) * (T + 18)
            if m in pngs:
                im = Image.open(io.BytesIO(zf.read(pngs[m]))).convert('RGBA'); im.thumbnail((T - 10, T - 10))
                bg = Image.new('RGBA', im.size, (245, 245, 245, 255)); bg.alpha_composite(im)
                sheet.paste(bg.convert('RGB'), (x + (T - im.width) // 2, y + (T - im.height) // 2))
            d.text((x + 4, y + T), m[:24], fill=(20, 20, 20), font=font)
        page += 1; sheet.save(os.path.join(OUT, f'{kit}_{page}.jpg'), quality=82)
    print(kit, len(models), 'models,', len(pngs), 'previews,', page, 'pages')
