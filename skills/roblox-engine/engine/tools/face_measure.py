"""face_measure.py - measure every library face texture and write the numbers the acting layer picks faces by into its meta.json:
  intensity  0..1  how exaggerated the face is (rank over the library of: mouth box area, eye band height, total ink) - big
                   beats (shock, fear, triumph, disgust) take the highest of their emotion, small beats the lowest
  eyes       [y0, y1]          eye band, fractions of the image height from the TOP (faces.py squashes it for a blink twin)
  mouth      [x0, y0, x1, y1]  mouth box, fractions from the top-left (faces.py: open-mouth / half-closed talk twin)
  mouth_open true = the mouth is already an open shape (talk twin = half closed instead of opened)
  auto       false = never picked automatically (off-style: only by an explicit lib:<slug>)
  family     visual style (LEVEL 1 faces: one family per character for the whole Short): 'bigeye' = outlined eyes with whites and
             pupils (white ink >= 9 % of the eye band: Epic Face, Anime Surprise...), else 'classic' (thin-line / dot eyes); FAMILY overrides
CURATED below overrides the measure where the eye disagrees (assets/faces/sheet.jpg). Rerun after tools/face_fetch.py fetch:
  python tools/face_measure.py            (plain Python + Pillow; prints the ranking per emotion)"""
import json
from pathlib import Path
import numpy as np
from PIL import Image

LIB = Path(__file__).resolve().parent.parent / 'assets' / 'faces'
# off-style or unreadable as an emotion at Short size (logos, costumes, eye patches, text symbols that read as noise)
NO_AUTO = ('roblox_madness_face', 'extreme', 'hypnoface', 'sym1558', 'silence', 'stitchface', 'classic_vampire', 'vampire', 'slickfang',
           'angry_zombie', 'bad_dog', 'robot_smile', 'braces', 'playful_vampire', 'drool', 'lazy_eye', 'i_wuv_u', 'sym7848', 'chubs',
           'not_sure_if', 'shhh', 'sym4577', 'sym6173', '3', '32', 'dizzy_face', 'monster_face', 'i_didn_t_eat_that_cookie', 'sick_day')
FAMILY = {'i_wuv_u': 'classic'}   # solid eyes with a big highlight: reads with the dot-eyed classics
CURATED = {'whaaaaaa': 1.0, 'roar': 1.0, 'd': 0.95, 'epic_face': 1.0, 'xd_2_0': 0.95, 'sadfaic': 0.9, 'anime_surprise': 1.0,
           'super_happy_joy': 1.0, 'furious_george': 0.9, 'rawr': 0.85, 'surprise': 0.9, 'sweat_it_out': 0.9, 'hold_it_in': 0.95,
           'stink_eye': 0.9, 'awkward_eyeroll': 0.8, 'laughing_fun': 0.85, 'cheerful_grin': 0.9, 'awesome_face': 0.9, 'monster_smile': 1.0}


def measure(png):
    im = np.array(Image.open(png).convert('RGBA')); a = im[..., 3] > 128; H, W = a.shape
    rows = np.where(a.any(1))[0]; top, bot = rows[0], rows[-1]
    # the eyes / mouth split = the widest empty row gap inside the ink (a face with no gap: split at 55 % of its height)
    gaps = [(rows[i + 1] - rows[i], rows[i], rows[i + 1]) for i in range(len(rows) - 1) if rows[i + 1] - rows[i] > 4]
    g = max(gaps, default=None)
    e1, m0 = (g[1], g[2]) if g else (int(top + 0.55 * (bot - top)),) * 2
    cols = np.where(a[m0:].any(0))[0]
    mouth = [cols[0] / W, m0 / H, (cols[-1] + 1) / W, (bot + 1) / H]
    mw, mh = mouth[2] - mouth[0], mouth[3] - mouth[1]
    eb = slice(top, e1 + 1); white = ((im[eb][..., :3].min(-1) > 230) & a[eb]).sum() / max(1, a[eb].sum())
    return {'eyes': [round(top / H, 3), round((e1 + 1) / H, 3)], 'mouth': [round(v, 3) for v in mouth],
            'mouth_open': bool(mh > 0.09 and a[m0:].sum() / (H * W) > 0.012), '_m': mw * mh, '_e': (e1 - top) / H, '_ink': a.mean(), 'family': 'bigeye' if white >= 0.09 else 'classic'}


def main():
    metas = {p: json.loads(p.read_text(encoding='utf-8')) for p in sorted(LIB.glob('*/meta.json'))}
    ms = {p: measure(p.parent / 'face.png') for p in metas}
    rank = lambda k: {p: r / (len(ms) - 1) for r, p in enumerate(sorted(ms, key=lambda p: ms[p][k]))}
    rm, re_, ri = rank('_m'), rank('_e'), rank('_ink')
    out = {}
    for p, m in metas.items():
        x = ms[p]; s = m['slug']
        m.update(intensity=CURATED.get(s, round(min(0.85, 0.5 * rm[p] + 0.25 * re_[p] + 0.25 * ri[p]), 2)), eyes=x['eyes'], mouth=x['mouth'],
                 mouth_open=x['mouth_open'], auto=s not in NO_AUTO, family=FAMILY.get(s, x['family']))
        p.write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding='utf-8'); out.setdefault(m['emotion'], []).append(m)
    for e, l in sorted(out.items()):
        print(f'{e:9}', ' '.join(f"{m['slug']}{'' if m['auto'] else '*'}{'' if m['family'] == 'classic' else '^'}={m['intensity']}" for m in sorted(l, key=lambda m: -m['intensity'])))
    byid = {m['id']: (p, m) for p, m in ((p, json.loads(p.read_text(encoding='utf-8'))) for p in metas)}   # pair_ok: the talk partner has the same eyes AND brows
    for p, m in byid.values():
        t = byid.get(m.get('talk_pair'))
        if t:
            a, b = (np.array(Image.open(q.parent / 'face.png').convert('RGBA').resize((128, 128)))[..., 3] > 128 for q in (p, t[0]))
            r = max(1, int(128 * (m['eyes'][1] + .02))); m['pair_ok'] = bool((a[:r] & b[:r]).sum() / max(1, (a[:r] | b[:r]).sum()) >= .9)
            p.write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding='utf-8')
    assert all(any(m['auto'] for m in l) for l in out.values()), 'an emotion with no auto face'


if __name__ == '__main__':
    main()
