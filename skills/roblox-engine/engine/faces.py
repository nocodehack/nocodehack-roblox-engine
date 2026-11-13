"""faces.py - reference flat decal faces (black ovals + white highlight), drawn with numpy, swapped by keyframe.
Kinds: smile grin o worry sheepish blink neutral angry sad smug scream joy cry scared confused disgust laugh (the 'drawn' face family).
Every drawn kind except blink has '<kind>_talk' (open mouth; an already open mouth half closes) and '<kind>_shut' (eyes closed, same
brows + mouth) twins, so a drawn face talks and blinks without leaving its own drawing.
Use: faces.attach(char_name, head_pivot, kinds) once, then faces.set(char_name, kind, frame) any number of times (decals are made on first use)."""
import json, zlib
from pathlib import Path
import bpy
import numpy as np
import claude_still as cs

KINDS = ('smile', 'grin', 'o', 'worry', 'sheepish', 'blink', 'neutral', 'angry', 'sad', 'smug', 'scream', 'joy', 'cry', 'scared', 'confused', 'disgust', 'laugh')
TALKABLE = tuple(k for k in KINDS if k != 'blink')
_BUILTIN = KINDS + tuple(k + t for k in TALKABLE for t in ('_talk', '_shut'))   # open-mouth + closed-eye twin of each expression
HEAD_R, HEAD_H = 0.605, 1.2   # studs, the authentic R6 head
_LIB = {}                       # char name -> {kind: decal object}
_HEAD = {}                      # char name -> head pivot (lazy decals for library faces)

# ---- Roblox face library (assets/faces, tools/face_fetch.py): real classic Face decals tagged by emotion ----
# Story/cast face keys: 'lib:<slug>' (e.g. lib:uh_oh, see assets/faces/LIBRARY.md), 'emo:<emotion>' or a bare emotion that is not a
# built-in kind (shock, cry, laugh, ...): picks a library face deterministically per character, 'emo:shock#2' = the next one.
# Talking: '<key>_talk' = the face's open-mouth partner (meta talk_pair); no partner -> a twin made from the texture (meta 'mouth',
# tools/face_measure.py): a line mouth opens into a dark oval with teeth, an already open mouth half closes. '<key>_shut' = the blink
# twin (eye band squashed flat). Every measured library face therefore talks and blinks.
LIB_DIR = Path(__file__).resolve().parent / 'assets' / 'faces'
EMOTIONS = ('happy', 'joy', 'laugh', 'smug', 'neutral', 'sad', 'cry', 'angry', 'shock', 'scared', 'sleepy', 'sheepish', 'silly', 'cool', 'confused', 'disgust', 'love', 'evil')
_FL = {}


def library():
    """{slug: meta + 'dir', ...} loaded once from assets/faces/*/meta.json; adds 'pair_slug' (open-mouth partner or None)."""
    if not _FL:
        ms = [dict(json.loads(m.read_text(encoding='utf-8')), dir=m.parent) for m in sorted(LIB_DIR.glob('*/meta.json'))]
        byid = {m['id']: m['slug'] for m in ms}
        for m in ms: m['pair_slug'] = byid.get(m.get('talk_pair')); _FL[m['slug']] = m
    return _FL


def emotion_faces(emo): return [s for s, m in library().items() if m['emotion'] == emo]


def is_lib(kind):
    b = kind[:-5] if kind.endswith(('_talk', '_shut')) else kind
    return b.startswith(('lib:', 'emo:')) or (b.split('#')[0] in EMOTIONS and b.split('#')[0] not in _BUILTIN)


def resolve(name, kind):
    """Library kind (maybe '_talk') -> (slug of the face to draw, is_talk). Built-in kinds are not passed here."""
    talk = kind.endswith('_talk'); b = kind[:-5] if kind.endswith(('_talk', '_shut')) else kind
    if b.startswith('lib:'):
        slug = b[4:]; lib = library()
        if slug not in lib: slug = next((s for s, m in lib.items() if m['id'] == slug), None)
        assert slug, f'unknown library face {kind}'
    else:
        emo, _, n = b.removeprefix('emo:').partition('#'); pool = emotion_faces(emo)
        assert pool, f'no library face for emotion {emo}'
        slug = pool[(zlib.crc32(f'{name}/{emo}'.encode()) + int(n or 0)) % len(pool)]
    p = library()[slug]['pair_slug']   # the open-mouth partner only when it is drawn in the same style (one family per character)
    if talk and p and library()[p].get('family') == library()[slug].get('family') and library()[slug].get('pair_ok'): slug = p   # pair_ok: same eyes AND brows (tools/face_measure.py)
    return slug


def twins_ok(kind):
    """True when the face has both twins: '_talk' (open mouth) and '_shut' (blink), drawn in its own family."""
    b = kind[:-5] if kind.endswith(('_talk', '_shut')) else kind
    if not is_lib(b): return b == 'blink' or (b + '_talk' in _BUILTIN and b + '_shut' in _BUILTIN)
    m = library()[resolve('', b)]; return 'eyes' in m and ('mouth' in m or bool(m['pair_slug']))


def twin_eye_iou(name, kind):
    """Overlap (0..1) of the ink in the eye + brow band between a face and its '_talk' twin; 1 = only the mouth differs."""
    b = kind[:-5] if kind.endswith(('_talk', '_shut')) else kind
    def ink(k):
        im = image(k, name=name) if not is_lib(k) else lib_image(name, k); W, H = im.size
        px = np.empty(W * H * 4, np.float32); im.pixels.foreach_get(px); return px.reshape(H, W, 4)[..., 3] > .5
    y0 = library()[resolve(name, b)]['eyes'][1] + .02 if is_lib(b) else .40   # the eye + brow band's lower edge, fraction from the TOP
    a, t = ink(b), ink(b + '_talk'); r = int(a.shape[0] * (1 - y0)); a, t = a[r:], t[r:]
    return float((a & t).sum() / max(1, (a | t).sum()))


def mouth_curve(name, kind):
    """Mouth mood of a face texture: +1 smile (middle of the mouth lower than its corners), -1 frown, 0 flat/open symmetric."""
    im = image(kind, name=name) if not is_lib(kind) else lib_image(name, kind); W, H = im.size
    px = np.empty(W * H * 4, np.float32); im.pixels.foreach_get(px); a = px.reshape(H, W, 4)[..., 3] > .5
    y0 = library()[resolve(name, kind[:-5] if kind.endswith('_talk') else kind)]['mouth'][1] if is_lib(kind) else .60   # mouth top from the TOP (drawn: mouths sit below y=.45)
    a = a[:int(H * (1 - y0))]   # bottom-first rows: the mouth part
    if not is_lib(kind): a = a[:, int(.33 * W):int(.67 * W)] & (np.arange(a.shape[0])[:, None] < .40 * H)   # drawn: the mouth only (no tears / sweat)
    cols = np.where(a.any(0))[0]
    if len(cols) < 6 or not a.any(): return 0
    c = {x: np.where(a[:, x])[0].mean() for x in cols}; w = len(cols); end = [c[x] for x in cols[:max(1, w // 5)]] + [c[x] for x in cols[-max(1, w // 5):]]
    mid = [c[x] for x in cols[2 * w // 5: 3 * w // 5 + 1]]
    d = (np.mean(end) - np.mean(mid)) / H   # rows grow upward: corners higher than the middle = smile
    return 0 if abs(d) < .012 else (1 if d > 0 else -1)


_MOOD = {**dict.fromkeys(('angry', 'sad', 'worry', 'cry', 'scared', 'disgust'), -1), **dict.fromkeys(('smug', 'neutral', 'sheepish', 'confused'), 0)}


def twin_mouth_ok(name, kind):
    """The '_talk' twin keeps the mouth's mood: a drawn kind's twin must have the kind's mood (frown / flat / smile, _MOOD), a library
    face's twin must not flip the base mouth's sign (frown <-> smile)."""
    b = kind[:-5] if kind.endswith(('_talk', '_shut')) else kind
    if kind.endswith('_shut') or b in ('blink', 'o', 'scream', 'laugh') or not twins_ok(b): return True   # already open mouths: the twin half closes them
    t = mouth_curve(name, b + '_talk')
    return t == _MOOD.get(b, 1) or (b in ('smile', 'grin', 'joy') and t >= 0) if not is_lib(b) else True   # library twins: the base's own line + an oval; judged by eye


def _squash(px, y0, y1, k):
    """Rows y0..y1 (fractions from the TOP of the texture) of px (H, W, 4, bottom row first) squashed to k of their height
    around the band centre; the freed rows become transparent."""
    H = px.shape[0]; r0, r1 = int(H * (1 - y1)), int(H * (1 - y0)); c = (r0 + r1) / 2; out = px.copy(); out[r0:r1] = 0
    rows = np.arange(r0, r1); src = np.round(c + (rows - c) / k).astype(int); ok = (src >= r0) & (src < r1)
    out[rows[ok]] = px[src[ok]]
    return out


def lib_image(name, kind):
    slug = resolve(name, kind); m = library()[slug]
    twin = next((t for t in ('_talk', '_shut') if kind.endswith(t) and 'mouth' in m), '')
    if twin == '_talk' and resolve(name, kind[:-5]) != slug: twin = ''   # a real open-mouth partner face: drawn as it is
    nm = 'face_lib_' + slug + twin
    img = bpy.data.images.get(nm)
    if img is None and not twin:
        img = bpy.data.images.load(str(m['dir'] / 'face.png'), check_existing=False); img.name = nm
        img.alpha_mode = 'STRAIGHT'; img.pack()
    elif img is None:
        src = lib_image(name, 'lib:' + slug); W, H = src.size
        px = np.empty(W * H * 4, np.float32); src.pixels.foreach_get(px); px = px.reshape(H, W, 4)
        x0, y0, x1, y1 = m['mouth']
        if twin == '_shut': px = _squash(px, m['eyes'][0], m['eyes'][1], 0.2)
        elif m.get('mouth_open'): px = _squash(px, y0, y1, 0.5)
        else:   # a line mouth: open oval over it (teeth strip on top, like the built-in talk twins)
            yy, xx = np.mgrid[0:H, 0:W]; xx = xx / W; yy = 1 - yy / H
            rx = min(0.12, max(0.07, 0.36 * (x1 - x0))); ry = 0.75 * rx; cy = min((y0 + y1) / 2 + 0.2 * ry, 0.97 - ry)
            e = ((xx - (x0 + x1) / 2) / rx) ** 2 + ((yy - cy) / ry) ** 2 < 1
            px = px.copy(); px[e] = (0, 0, 0, 1); px[e & (yy < cy - 0.35 * ry)] = (1, 1, 1, 1)
        img = bpy.data.images.new(nm, W, H, alpha=True); img.alpha_mode = 'STRAIGHT'; img.pixels.foreach_set(px.ravel()); img.pack()
    return img


class _Kinds(tuple):
    def __contains__(self, k):
        if tuple.__contains__(self, k): return True
        try: return is_lib(k) and bool(resolve('x', k))
        except AssertionError: return False


class _Talkable(tuple):
    def __contains__(self, k):
        if tuple.__contains__(self, k): return True
        if not is_lib(k): return False
        b = k[:-5] if k.endswith('_talk') else k
        if b.startswith('lib:'): m = library()[resolve('', b)]; return m['pair_slug'] is not None or 'mouth' in m
        return any(library()[s]['pair_slug'] or 'mouth' in library()[s] for s in emotion_faces(b.removeprefix('emo:').partition('#')[0]))



KINDS = _Kinds(_BUILTIN); TALKABLE = _Talkable(TALKABLE)   # membership also accepts library kinds (build.py validates with `in`)


def image(kind, n=512, name=''):
    if is_lib(kind): return lib_image(name, kind)
    full_kind = kind; talk = kind.endswith('_talk'); shut = kind.endswith('_shut')   # '<expr>_talk' = expr eyes, open mouth;
    kind = kind[:-5] if talk or shut else kind                                        # '<expr>_shut' = closed eyes, expr brows + mouth
    yy, xx = np.mgrid[0:n, 0:n] / n          # yy = 0 is the bottom row (Blender pixel order)
    a = np.zeros((n, n), bool); white = np.zeros((n, n), bool); blue = np.zeros((n, n), bool); pink = np.zeros((n, n), bool)
    def ell(cx, cy, rx, ry): return ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 < 1
    x = xx - 0.5
    sgn = np.where(xx < 0.5, 1.0, -1.0)      # +1 for the left eye, -1 for the right eye (mirror for brows)
    eye_cx = np.where(xx < 0.5, 0.32, 0.68)
    # eyes
    if kind in ('joy', 'laugh'):              # closed happy arcs ^ ^ (their '_shut' twin is the same drawing)
        for cx in (0.32, 0.68): a |= (abs(xx - cx) < 0.085) & (abs(yy - (0.70 - 1.1 * abs(xx - cx))) < 0.026)
    elif kind == 'blink' or shut:
        for cx in (0.33, 0.67): a |= (abs(xx - cx) < 0.09) & (abs(yy - 0.6 + 6 * (xx - cx) ** 2) < 0.018)
    else:
        rx, ry = {'o': (0.10, 0.165), 'worry': (0.10, 0.165), 'scream': (0.115, 0.18), 'scared': (0.115, 0.18)}.get(kind, (0.095, 0.155))
        for cx in (0.32, 0.68):
            small = kind == 'confused' and cx > 0.5            # confused: one eye squints smaller
            e = ell(cx, 0.62, rx * (0.75 if small else 1), ry * (0.7 if small else 1))
            if kind == 'smug': e &= yy < 0.655                 # half-lidded
            if kind == 'disgust': e &= abs(yy - 0.6) < 0.055   # squint slits
            if kind == 'angry': e &= yy < 0.62 + 0.9 * (xx - cx) * (1 if cx < 0.5 else -1) + 0.1
            a |= e
            if kind == 'scared': white |= ell(cx, 0.62, 0.055, 0.085)   # tiny pupils in wide whites read as fear
            else: white |= ell(cx - 0.032, 0.675, 0.03, 0.04) & (kind not in ('smug', 'disgust'))
    if kind == 'cry':                          # tear streams under both eyes (also while blinking / talking)
        for cx in (0.30, 0.70): blue |= (abs(xx - cx) < 0.03) & (yy < 0.5) & (yy > 0.2 + 2 * abs(xx - cx))
    if kind == 'scared': blue |= ell(0.83, 0.74, 0.03, 0.05) | ((abs(xx - 0.83) < 0.6 * (yy - 0.74)) & (yy > 0.74) & (yy < 0.82))   # sweat drop
    # brows
    near = abs(xx - eye_cx) < 0.11
    if kind == 'angry': a |= near & (abs(yy - (0.80 - 0.5 * (xx - eye_cx) * sgn)) < 0.026)
    if kind == 'disgust': a |= near & (abs(yy - (0.74 - 0.3 * (xx - eye_cx) * sgn)) < 0.024)
    if kind in ('sad', 'worry', 'cry'): a |= near & (abs(yy - (0.83 + 0.4 * (xx - eye_cx) * sgn)) < 0.022)
    if kind == 'scared': a |= near & (abs(yy - (0.87 + 0.45 * (xx - eye_cx) * sgn)) < 0.022)
    if kind == 'confused':                     # one flat brow, one raised arch
        a |= (abs(xx - 0.32) < 0.1) & (abs(yy - 0.80) < 0.022)
        a |= (abs(xx - 0.68) < 0.1) & (abs(yy - (0.86 - 4 * (xx - 0.68) ** 2)) < 0.022)
    # mouths
    if talk and kind in ('o', 'scream', 'laugh'):   # an already open mouth: the talk twin half closes it
        if kind == 'o': a |= ell(0.5, 0.29, 0.07, 0.065)
        else:
            m = ell(0.5, 0.29, 0.13, 0.085) & (yy < 0.33); a |= m; white |= m & (yy > 0.295)
    elif talk:                                  # speaking: an open version of the SAME mouth mood (a frown opens as a frown, never a smile)
        if kind in ('angry', 'sad', 'worry', 'cry', 'scared', 'disgust'):   # frown: arched top, flat bottom (angry: teeth strip along the flat bottom)
            cy = 0.25 + {'angry': -0.02, 'cry': -0.01}.get(kind, 0.0); m = ell(0.5, cy, 0.12, 0.085) & (yy > cy)
            a |= m; white |= m & (yy < cy + 0.035) & (kind == 'angry')
        elif kind in ('smug', 'neutral', 'sheepish', 'confused'):   # flat mood: a plain open oval
            m = ell(0.5, 0.30, 0.10, 0.06); a |= m
        else:                                   # smile moods: D-shaped mouth, teeth strip on top
            m = ell(0.5, 0.29, 0.12 if kind not in ('grin', 'joy') else 0.15, 0.085) & (yy < 0.33)
            a |= m; white |= m & (yy > 0.29)
    elif kind in ('smile', 'blink'):
        arc = 0.36 - 0.13 * np.sqrt(np.clip(1 - (x / 0.2) ** 2, 0, 1))
        a |= (abs(x) < 0.22) & (abs(yy - arc) < 0.05)
    elif kind in ('grin', 'joy'):
        lo = 0.36 - 0.17 * np.sqrt(np.clip(1 - (x / 0.22) ** 2, 0, 1))
        m = (abs(x) < 0.22) & (yy < 0.37) & (yy > lo); a |= m; white |= m & (yy > 0.30)
    elif kind == 'laugh':                       # huge open laugh: teeth on top, tongue at the bottom
        lo = 0.38 - 0.24 * np.sqrt(np.clip(1 - (x / 0.26) ** 2, 0, 1))
        m = (abs(x) < 0.26) & (yy < 0.39) & (yy > lo); a |= m; white |= m & (yy > 0.33); pink |= m & ell(0.5, lo.min() + 0.02, 0.12, 0.07)
    elif kind == 'o':
        a |= ell(0.5, 0.28, 0.08, 0.11)
    elif kind == 'scream':
        m = ell(0.5, 0.25, 0.13, 0.15); a |= m; white |= m & (yy > 0.34)
    elif kind == 'worry':
        a |= (abs(x) < 0.16) & (abs(yy - (0.24 + 0.6 * x ** 2)) < 0.045)
    elif kind == 'sheepish':
        a |= (abs(x) < 0.18) & (abs(yy - (0.29 + 0.25 * x)) < 0.045)
        a |= (abs(xx - 0.75) < 0.05) & (abs(yy - 0.28) < 0.05)
    elif kind == 'neutral':
        a |= (abs(x) < 0.13) & (abs(yy - 0.31) < 0.024)
    elif kind in ('angry', 'sad'):
        arc = 0.25 + 0.08 * np.sqrt(np.clip(1 - (x / 0.16) ** 2, 0, 1))
        a |= (abs(x) < 0.16) & (abs(yy - arc) < 0.035)
    elif kind == 'cry':                         # wide wobbling frown
        arc = 0.22 + 0.11 * np.sqrt(np.clip(1 - (x / 0.21) ** 2, 0, 1)) + 0.012 * np.sin(x * 60)
        a |= (abs(x) < 0.21) & (abs(yy - arc) < 0.038)
    elif kind == 'scared':                      # trembling zigzag mouth
        a |= (abs(x) < 0.17) & (abs(yy - (0.28 + 0.025 * np.sin(x * 48))) < 0.026)
    elif kind == 'confused':                    # slanted squiggle
        a |= (abs(x) < 0.15) & (abs(yy - (0.29 - 0.18 * x + 0.016 * np.sin(x * 45))) < 0.026)
    elif kind == 'disgust':                     # wavy frown, tongue out at one corner
        a |= (abs(x) < 0.19) & (abs(yy - (0.30 - 1.0 * x ** 2 + 0.018 * np.sin(x * 40))) < 0.028)
        pink |= ell(0.58, 0.245, 0.05, 0.05) & (yy < 0.27)
    elif kind == 'smug':
        a |= (x > -0.12) & (x < 0.17) & (abs(yy - (0.30 + 0.35 * np.clip(x, 0, None) + 0.05 * x)) < 0.03)
    rgba = np.zeros((n, n, 4), np.float32); rgba[a, 3] = 1; rgba[white & a, :3] = 1
    rgba[blue & ~a] = (0.45, 0.78, 1.0, 1.0); rgba[pink] = (0.93, 0.42, 0.5, 1.0)
    img = bpy.data.images.new('face_' + full_kind, n, n, alpha=True); img.pixels.foreach_set(rgba.ravel()); img.pack()
    assert a.sum() > 1500, f'face {full_kind} too empty'
    return img


def attach(name, head_pivot, kinds=KINDS):
    """The decal of the first kind on the head (the start face); every other kind is made on first use by set() (hidden before
    that frame), so a character only carries the faces it wears. Returns {kind: object}."""
    lib = {kinds[0]: _decal(name, kinds[0], head_pivot, False)}
    _LIB[name] = lib; _HEAD[name] = head_pivot
    return lib


# ---- face marks (scars): drawn over EVERY decal a character wears (twins, blinks, both families) at fixed texture coordinates ----
# (u, v) 0..1 across the decal, v up; u < .5 = the character's RIGHT side. Each mark = list of strokes ((u0,v0),(u1,v1),width_in_v).
MARKS = {'scar_x_cheek_L': [((.74, .57), (.84, .45), .014), ((.74, .45), (.84, .57), .014)],   # classic eyes sit at u .34-.46 / .54-.65, v .64-.78; mouth u .3-.7, v < .42
         'scar_eye_R': [((.37, .86), (.43, .54), .018)],
         'dots6_forehead': [((u, v), (u + .001, v), .030) for u in (.46, .54) for v in (.983, .943, .903)]}   # six incense dots (a tiny stroke = a round dot)
MARKS['veins_head'] = [((.30, .99), (.38, .86), .012), ((.38, .86), (.33, .80), .010), ((.50, .99), (.50, .88), .012), ((.50, .88), (.56, .83), .010), ((.70, .99), (.63, .87), .012), ((.63, .87), (.68, .81), .010)]   # creature veins over the brow
_MARK_COLS = {'dots6_forehead': (196, 142, 104), 'veins_head': (38, 92, 30)}   # per-mark colour (default _MARK_COL)
_MARK_COL = (112, 28, 22)
_MARKS = {}   # char name -> [valid mark names]
NOTES = []    # unknown mark names (reported by build.py as errors, never a crash)


def set_marks(name, marks):
    ok = [m for m in (marks or []) if m in MARKS]
    NOTES.extend(f'{name}: unknown face mark {m!r} (known: {sorted(MARKS)})' for m in (marks or []) if m not in MARKS)
    _MARKS[name] = ok


def mark_layer(W, H, marks):
    """(H, W, 4) float RGBA of the strokes, bottom row first (Blender order): distance-to-segment with a ~2.5 px soft edge (numpy; Blender has no PIL)."""
    yy, xx = np.mgrid[0:H, 0:W]; x = (xx + .5) / W; y = (yy + .5) / H; px_ = 1 / H
    out = np.zeros((H, W, 4), np.float32); out[..., :3] = np.array(_MARK_COL, np.float32) / 255
    for m in marks:
        a = np.zeros((H, W), np.float32)
        for (u0, v0), (u1, v1), w in MARKS[m]:
            dx, dy = u1 - u0, v1 - v0; t = np.clip(((x - u0) * dx + (y - v0) * dy) / (dx * dx + dy * dy), 0, 1)
            d = np.hypot(x - (u0 + t * dx), y - (v0 + t * dy))
            a = np.maximum(a, np.clip((w / 2 + 1.25 * px_ - d) / (2.5 * px_), 0, 1))
        new = a > out[..., 3]   # each mark keeps its own colour where it is the strongest
        out[new, :3] = np.array(_MARK_COLS.get(m, _MARK_COL), np.float32) / 255; out[..., 3] = np.maximum(out[..., 3], a)
    return out


def composite(px, layer):
    """Straight-alpha 'over' of layer on px (both (H, W, 4))."""
    ma, a = layer[..., 3:], px[..., 3:]; oa = ma + a * (1 - ma)
    rgb = (layer[..., :3] * ma + px[..., :3] * a * (1 - ma)) / np.maximum(oa, 1e-6)
    return np.concatenate([rgb, oa], -1)


def _marked(name, img):
    marks = _MARKS.get(name)
    if not marks: return img
    nm = f'{img.name}__{name}'; out = bpy.data.images.get(nm)
    if out is None:
        W, H = img.size; px = np.empty(W * H * 4, np.float32); img.pixels.foreach_get(px)
        px = composite(px.reshape(H, W, 4), mark_layer(W, H, marks))
        out = bpy.data.images.new(nm, W, H, alpha=True); out.alpha_mode = 'STRAIGHT'; out.pixels.foreach_set(px.ravel().astype(np.float32)); out.pack()
    return out


def _decal(name, k, head_pivot, hidden):
    img = image(k, name=name) if is_lib(k) else (bpy.data.images.get('face_' + k) or image(k))
    img = _marked(name, img)
    o = cs.face_decal(f'{name} face {k}', HEAD_R, HEAD_H, img, head_pivot)
    o.hide_render = o.hide_viewport = hidden
    return o


def set(name, kind, frame):
    """Show `kind` from `frame` on (constant keys on visibility)."""
    lib = _LIB[name]
    if kind not in lib and kind in KINDS:   # faces are created on first use: hidden at frame 0 AND at every frame already keyed
        import space                          # (a decal made late, e.g. by a close-up accent, must not stay on past the next face)
        keyed = {0} | {round(p.co.x) for o_ in lib.values() for fc in space.fcurves_of(o_) if fc.data_path == 'hide_render' for p in fc.keyframe_points}
        o = lib[kind] = _decal(name, kind, _HEAD[name], True)
        for f in sorted(keyed):
            for a in ('hide_render', 'hide_viewport'): o.keyframe_insert(a, frame=f)
    assert kind in lib, f'{name} has no face {kind}'
    for k, o in lib.items():
        o.hide_render = o.hide_viewport = k != kind
        o.keyframe_insert('hide_render', frame=frame); o.keyframe_insert('hide_viewport', frame=frame)


def blinks(name, schedule, start=30, period=78, end=10_000, guard=6, skip=('joy', 'laugh', 'blink')):
    """schedule {frame: kind} -> adds 3-frame blinks every `period` frames away from changes; then keys all faces."""
    sched = dict(schedule); changes = sorted(sched)
    f = start
    while f < end:
        cur = sched[max([c for c in changes if c <= f], default=changes[0])]
        if cur not in skip and not cur.endswith(('_talk', '_shut')) and all(abs(f - c) > guard for c in changes):
            sched[f] = cur + '_shut'; sched[f + 3] = cur   # every face blinks with its own '_shut' twin (library: eye band squashed)
        f += period
    for fr, k in sorted(sched.items()):
        set(name, k, fr)
    return sched
