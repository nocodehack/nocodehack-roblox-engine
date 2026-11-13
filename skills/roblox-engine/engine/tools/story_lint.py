"""story_lint.py - check a story.json in about a second, WITHOUT Blender, before a 1-2 minute-per-scene build.
  python tools/story_lint.py stories/<name>/story.json [--quiet]
ERROR = the build will fail or the key/value is ignored.  WARN = it will probably look or sound wrong.
Every line: LEVEL  where (scene / beat / shot index)  key: problem -> fix.   Exit code 1 when there is an error.
Name lists are read from the engine files (poses.py, fight.py, faces.py, rooms.py, camera.py, assets/*) by parsing, never by importing bpy.
story.py runs this first (errors stop the build unless --no-lint)."""
import ast, difflib, glob, json, math, os, re, shutil, subprocess, sys
from pathlib import Path

E = Path(__file__).resolve().parent.parent
A = E / 'assets'

# ---------------------------------------------------------------- keys the engine reads (build.py, fight.py, camera.py, story.py, tools/sound_mix.py)
TOP = {'title', 'fps', 'mood', 'cast', 'scenes', 'seed', 'camera', 'look', 'set', 'auto_acting', 'strict_crowd', 'frame',
       'format', 'header', 'captions', 'narrator', 'voices', 'cards', 'split'}   # frame: B1 [w, h]
SCENE = {'set', 'seconds', 'cast', 'props', 'beats', 'shots', 'look', 'breathe', 'fps', 'camera', 'establish', 'inserts', 'reactions',
         'pitch', 'ecu', 'auto_acting', 'auto_faces', 'strict_crowd', 'music', 'title', 'crowd'}
SET = {'preset', 'size', 'height', 'wall', 'trim', 'floor', 'floor_color', 'door', 'wall_low', 'wainscot', 'windows', 'doors', 'decor',
       'ceiling_lamps', 'seed', 'time', 'mood', 'outdoor', 'park', 'dress', 'rbx', 'at', 'rot', 'scale', 'ground', 'board', 'notes', 'desks'}
LOOKS = {'name', 'shirt', 'pants', 'skin', 'hair', 'hair_style', 'face', 'face_family', 'face_marks', 'outfit'}
SCAST = LOOKS | {'at', 'yaw'}
PROP = {'name', 'kind', 'on', 'at', 'z', 'rot', 'held_by', 'hand', 'until'}
BEAT = {'t', 'who', 'walk', 'speed', 'run', 'stride', 'hand', 'sit', 'stand', 'fall', 'get_up', 'give', 'throw', 'turn', 'pose', 'jump',
        'wiggle', 'wiggle_s', 'anim', 'loop', 'anim_speed', 'anim_skip', 'face', 'talk', 'gesture', 'look', 'track', 'grab', 'move',
        'attack', 'block', 'dodge', 'knockback', 'down', 'fly', 'land', 'power_up', 'aura', 'aura_color', 'beam', 'exclaim', 'transform',
        'say', 'voice', 'sfx', 'type', 'narrate', 'narrate_voice', 'freeze'}
SHOT = {'t', 'kind', 'on', 'lens', 'track', 'hold', 'angle', 'side', 'push', 'shake', 'shake_amp', 'keep_two', 'profile', 'front', 'frame',
        'move', 'ots', 'ecu', 'punch'}
SUB = {'attack': {'move', 'target', 'blocked', 'catch', 'no_look', 'flurry', 's', 'hold', 'relax'},
       'knockback': {'from', 'distance', 'height', 'to', 'pose', 'side'}, 'fly': {'to', 'height', 's'},
       'beam': {'to', 'charge', 's', 'color', 'hand', 'hands', 'size', 'deflect'}, 'give': {'prop', 'to', 'hand'},
       'grab': {'prop', 'hand', 'until'}, 'throw': {'prop', 'to', 'catch', 'catch_hand', 'miss', 'react', 'style'},
       'down': {'pose', 'crater', 'side', 'yaw'}, 'land': {'crater'}, 'aura': {'s', 'color'},
       'transform': {'hair', 'hair_color', 's', 'aura', 'hold', 'face', 'face_after'}}
CAMERA = {'mode', 'hero', 'with', 'on', 'at', 'kind', 'side', 'lens', 'who'}
MODES = {'story_cuts', 'follow_oneshot', 'ots_dialogue', 'static_wide', 'topdown_reveal', 'punch_in', 'chase_track', 'two_shot_react', 'pov'}
ANGLES = {'low', 'high', 'top'}
MOVES_CAM = {'still', 'push', 'pull', 'arc', 'track', 'follow'}
FLOORS = {'wood', 'checker', 'tile', 'carpet', 'grass', 'asphalt', 'sand', 'concrete'}
TIMES = {'day', 'evening', 'night'}
LIGHT_MOODS = {'default', 'warm', 'cool', 'dramatic', 'sunset', 'night', 'spooky'}
FAMILIES = {'drawn', 'classic', 'bigeye'}
HAIR_BUILTIN = {'spiky', 'short', 'long', 'ponytail', 'bun', 'none'}
PROP_BUILTIN = {'box', 'book', 'phone', 'ball', 'cake'}
CHANNELS = {'R', 'L', 'legR', 'legL', 'head', 'body'}
FORMATS = {   # format presets (FORMATS.md): captions, narrator needed, camera default, length hint (s), what the story needs
    'skit': ('cards', False, 'story_cuts', 30, 'header'), 'pov': ('cards', False, 'pov', 30, 'pov camera + header'),
    'time_skit': ('cards', False, 'static_wide', 30, 'time cards'), 'in_this_world': ('word', True, 'story_cuts', 60, 'narrator + title card'),
    'narrated_twist': ('word', True, 'story_cuts', 45, 'narrator'), 'versus': ('cards', False, 'static_wide', 30, 'split + label cards'),
    'choice': ('cards', False, 'static_wide', 30, 'choice card'), 'rich_poor': ('cards', False, 'static_wide', 30, 'split + label cards'),
    'ranking': ('cards', False, 'story_cuts', 45, 'counter cards'), 'what_if': ('word', True, 'story_cuts', 45, 'narrator + title card'),
    'text_message': ('word', True, 'story_cuts', 45, 'narrator (no phone UI exists)')}
WEAK = {'what_if', 'text_message'}
CARD_TYPES = {'title', 'time', 'label', 'counter', 'choice'}; CARD_KEYS = {'type', 'text', 'scene', 't', 'dur', 'a', 'b'}
CROWD_AREAS = {'back', 'sides', 'all'}; NARR_WPS = 2.6   # narrator words per second
WORD_S, REACH, GUARD, WALK_SPEED = 0.38, 6.6, 3.6, 9.5   # 0.38 s per spoken word; fight.py: strike reach 6.6, guard distance 3.6


# ---------------------------------------------------------------- name lists parsed from the engine
def _ast_dict_keys(path, name):
    keys = set()
    for n in ast.walk(ast.parse(Path(path).read_text(encoding='utf-8'))):
        if isinstance(n, ast.Assign):
            for tg in n.targets:
                if isinstance(tg, ast.Name) and tg.id == name and isinstance(n.value, ast.Dict):
                    keys |= {k.value for k in n.value.keys if isinstance(k, ast.Constant)}
                if isinstance(tg, ast.Subscript) and isinstance(tg.value, ast.Name) and tg.value.id == name and isinstance(tg.slice, ast.Constant):
                    keys.add(tg.slice.value)
    return keys


def _ast_tuple(path, name):
    for n in ast.parse(Path(path).read_text(encoding='utf-8')).body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets) and isinstance(n.value, ast.Tuple):
            return tuple(e.value for e in n.value.elts)
    return ()


def _presets():
    tree = ast.parse((E / 'rooms.py').read_text(encoding='utf-8')); out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PRESETS' for t in n.targets):
            for k, v in zip(n.value.keys, n.value.values):
                d = {kk.value: vv for kk, vv in zip(v.keys, v.values) if isinstance(kk, ast.Constant)}
                size = ast.literal_eval(d['size']) if 'size' in d else None
                outdoor = isinstance(d.get('outdoor'), ast.Constant) and d['outdoor'].value
                out[k.value] = {'size': size, 'outdoor': bool(outdoor)}
    return out


def _pieces():
    """Set-piece names per preset, from short.schema.md 'Preset pieces' (rooms.py builds them at run time inside Blender)."""
    out = {}
    if not (E / 'short.schema.md').exists(): return out   # cloud tarball has no .md files: then every piece name is accepted
    for line in (E / 'short.schema.md').read_text(encoding='utf-8').splitlines():
        m = re.match(r'- \*\*(\w+)\*\* \(.*?\): (.*)', line)
        if m: out[m.group(1)] = set(re.findall(r'`([^`]+)`', m.group(2)))
    return out


class Lib:
    def __init__(self):
        self.poses = _ast_dict_keys(E / 'poses.py', 'LIB') | _ast_dict_keys(E / 'fight.py', 'MOVES')
        kinds = _ast_tuple(E / 'faces.py', 'KINDS')
        self.faces = set(kinds) | {k + t for k in kinds if k != 'blink' for t in ('_talk', '_shut')}
        self.emotions = set(_ast_tuple(E / 'faces.py', 'EMOTIONS'))
        self.lib_faces, self.face_emos = set(), set()
        for m in glob.glob(str(A / 'faces' / '*' / 'meta.json')):
            j = json.loads(Path(m).read_text(encoding='utf-8')); self.lib_faces |= {str(j.get('slug')), str(j.get('id'))}; self.face_emos.add(j.get('emotion'))
        self.marks = _ast_dict_keys(E / 'faces.py', 'MARKS')
        src = (E / 'fight.py').read_text(encoding='utf-8')
        m = re.search(r"if move not in \(([^)]*)\)", src)
        self.attacks = set(re.findall(r"'(\w+)'", m.group(1))) if m else {'punch_R', 'punch_L', 'kick_R', 'uppercut_R', 'tap_R'}
        self.anims = {Path(p).parent.name for p in glob.glob(str(A / 'anims' / '*' / 'anim.json'))}
        self.hair = [Path(p).parent.name.lower() for p in glob.glob(str(A / 'hair' / '*_*' / 'mesh.obj'))]
        self.outfits = []
        for m in glob.glob(str(A / 'outfits' / '*_*' / 'meta.json')):
            j = json.loads(Path(m).read_text(encoding='utf-8')); self.outfits.append((int(Path(m).parent.name.split('_')[0]), j['kind'], str(j['id']), j.get('tags', [])))
        self.outfits.sort()
        self.kenney = json.loads((A / 'kenney' / 'catalog.json').read_text(encoding='utf-8'))
        self.presets = _presets(); self.pieces = _pieces()
        self.rbx = [Path(p).name.lower() for p in glob.glob(str(A / 'rbxsets' / '*_*')) if os.path.isdir(p)]
        self.sfx = {d.name for d in (A / 'sfx').iterdir() if d.is_dir() and not d.name.startswith('_')} | {'whoosh', 'boing', 'pop'}
        self.music = {Path(p).stem for p in glob.glob(str(A / 'music' / '*.ogg'))} | {'battle'}
        self.sizes = set(re.findall(r"'(\w+)': \(", re.search(r"SIZES = \{[^}]*\}", (E / 'camera.py').read_text(encoding='utf-8')).group(0)))

    def hair_ok(self, h):   # rig.hair_dir: id prefix, else substring of the folder name
        if h in HAIR_BUILTIN: return True
        if not h.startswith('lib:'): return False
        k = h[4:].lower(); return any(d.split('_', 1)[0] == k or k in d for d in self.hair)

    def outfit_ok(self, tag, kind):   # outfits.lib
        k = str(tag).split(':', 1)[-1].lower(); ms = [o for o in self.outfits if o[1] == kind]
        if any(o[2] == k for o in ms): return True
        mm = re.fullmatch(r'(.*?)(\d*)', k); t, n = mm.group(1), int(mm.group(2) or 1)
        return 1 <= n <= len([o for o in ms if t in o[3]])

    def face_ok(self, f):
        if not isinstance(f, str): return False
        if f in self.faces: return True
        b = f[:-5] if f.endswith(('_talk', '_shut')) else f
        if b.startswith('lib:'): return b[4:] in self.lib_faces
        emo = b.removeprefix('emo:').partition('#')[0]
        return emo in self.emotions and emo in self.face_emos

    def kenney_ok(self, name):   # assets.find
        kit, _, stem = name.rpartition('/')
        fs = [e['file'][:-4] for e in self.kenney if not kit or e['kit'] == kit]
        return any(s == stem or s.startswith(stem) or stem in s for s in fs)


# ---------------------------------------------------------------- helpers
def near(x, pool):
    m = difflib.get_close_matches(str(x), sorted(map(str, pool)), 1, 0.6)
    return f" (did you mean '{m[0]}'?)" if m else ''


def is_xy(v): return isinstance(v, (list, tuple)) and len(v) >= 2 and all(isinstance(a, (int, float)) for a in v[:2])


def num(v): return isinstance(v, (int, float)) and not isinstance(v, bool)


_DUR = {}
def audio_seconds(path):
    if path in _DUR: return _DUR[path]
    exe = shutil.which('ffprobe'); d = None
    if exe:
        try:
            r = subprocess.run([exe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path], capture_output=True, text=True, timeout=5)
            d = float(r.stdout.strip())
        except (ValueError, subprocess.SubprocessError, OSError): d = None
    _DUR[path] = d; return d


class Report:
    def __init__(self): self.items = []
    def add(self, lvl, where, key, msg): self.items.append((lvl, where, key, msg))
    def err(self, where, key, msg): self.add('ERROR', where, key, msg)
    def warn(self, where, key, msg): self.add('WARN', where, key, msg)
    @property
    def errors(self): return [i for i in self.items if i[0] == 'ERROR']
    @property
    def warnings(self): return [i for i in self.items if i[0] == 'WARN']
    def info(self, where, key, msg): self.add('INFO', where, key, msg)
    def lines(self): return [f'{l:<5} {w:<16} {k}: {m}' for l, w, k, m in self.items]


def unknown(R, where, d, allowed, what):
    for k in d:
        if k not in allowed and not str(k).startswith('_'):
            R.err(where, k, f'unknown {what} key, ignored{near(k, allowed)}')


# ---------------------------------------------------------------- scene timeline: where is everyone (approximately)
class Track:
    """Per character: piecewise-linear moves (t0, t1, p0, p1) + state spans (seated / lying / flying)."""
    def __init__(self, cast):
        self.moves = {n: [] for n in cast}; self.start = dict(cast)
        self.seated = {n: [] for n in cast}; self.lying = {n: [] for n in cast}; self.flying = {n: [] for n in cast}
    def at(self, n, T):
        p = self.start.get(n)
        for t0, t1, p0, p1 in self.moves.get(n, []):
            if T < t0: break
            if p0 is None or p1 is None: p = p1; continue
            u = 1.0 if T >= t1 or t1 <= t0 else (T - t0) / (t1 - t0)
            p = (p0[0] + (p1[0] - p0[0]) * u, p0[1] + (p1[1] - p0[1]) * u)
        return p
    def move(self, n, t0, t1, p1):
        p0 = self.at(n, t0); self.moves[n].append((t0, t1, p0, p1)); self.moves[n].sort(key=lambda m: m[0])
    @staticmethod
    def open_span(spans, t): spans.append([t, 1e9])
    @staticmethod
    def close_span(spans, t):
        if spans and spans[-1][1] == 1e9: spans[-1][1] = t
    @staticmethod
    def inside(spans, t0, t1=None):
        t1 = t0 if t1 is None else t1; return any(a <= t1 and t0 <= b for a, b in spans)


def toward(p, q, gap):   # the point `gap` short of q coming from p
    if p is None or q is None: return None
    dx, dy = q[0] - p[0], q[1] - p[1]; d = math.hypot(dx, dy)
    if d <= gap or d < 1e-6: return p
    return (q[0] - dx / d * gap, q[1] - dy / d * gap)


def dist(p, q): return math.hypot(p[0] - q[0], p[1] - q[1]) if p is not None and q is not None else None


# ---------------------------------------------------------------- the checks
_LIB = []
def lint(story_path):
    if not _LIB: _LIB.append(Lib())   # the name lists are read once per process
    R = Report(); L = _LIB[0]; sp = Path(story_path).resolve(); sdir = sp.parent
    try: S = json.loads(sp.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        R.err('story', 'json', f'cannot read: {e} -> fix the JSON syntax (a missing comma or bracket near the position shown)'); return R
    if not isinstance(S, dict): R.err('story', 'json', 'the file must be one JSON object {...}'); return R
    unknown(R, 'story', S, TOP, 'top-level')
    for k in ('title', 'cast', 'scenes'):
        if k not in S: R.err('story', k, f'missing -> add "{k}"')
    if not isinstance(S.get('cast', []), list) or not isinstance(S.get('scenes', []), list):
        R.err('story', 'cast/scenes', 'must be lists [...]'); return R
    if 'mood' in S and S['mood'] not in L.music: R.err('story', 'mood', f"music loop '{S['mood']}' does not exist, sound_mix crashes -> one of {sorted(L.music)}{near(S['mood'], L.music)}")
    fps = S.get('fps', 24)
    looks = {}
    for i, c in enumerate(S.get('cast', [])):
        w = f'cast[{i}]'
        if not isinstance(c, dict) or 'name' not in c: R.err(w, 'name', 'every cast entry needs a "name"'); continue
        if c['name'] in looks: R.err(w, 'name', f"'{c['name']}' is listed twice -> one entry per character")
        looks[c['name']] = c; unknown(R, w, c, LOOKS, 'cast')
        check_looks(R, L, w, c)
    total = 0.0; nsc = len(S.get('scenes', []))
    for si, sc in enumerate(S.get('scenes', [])):
        if not isinstance(sc, dict): R.err(f's{si + 1:02d}', 'scene', 'must be an object'); continue
        total += float(sc.get('seconds', 0) or 0)
        lint_scene(R, L, S, sc, si, looks, sdir, fps)
    lint_formats(R, L, S, total, sdir)
    if total > 60.5: R.warn('story', 'seconds', f'total {total:.1f} s is over a 60 s Short -> trim scenes or beats')
    return R


def lint_formats(R, L, S, total, sdir):
    """The format keys (SPEC): format, header, captions, narrator, voices, cards, split, scene crowd, beat narrate / freeze, camera pov."""
    scenes = [x for x in S.get('scenes', []) if isinstance(x, dict)]; N = len(scenes); fm = S.get('format')
    secs = lambda k: float(scenes[k - 1].get('seconds', 0) or 0) if 1 <= k <= N else 0.0
    if 'format' in S:
        if fm not in FORMATS: R.err('story', 'format', f"'{fm}' -> one of {sorted(FORMATS)}{near(fm, FORMATS)}")
        else:
            cap, narr, cam, hint, need = FORMATS[fm]
            R.info('story', 'format', f"{fm} applies: captions={S.get('captions', cap)}{'' if 'captions' in S else ' (preset)'}, narrator={'on' if narr else 'off'} (preset), camera default={cam}, length hint <= {hint} s; needs: {need}")
            if fm in WEAK: R.warn('story', 'format', f"'{fm}' is a weak format (FORMATS.md): the study median is tiny -> prefer in_this_world / narrated_twist")
            if total > hint + 0.5: R.warn('story', 'seconds', f"{total:.1f} s is over the {fm} hint of {hint} s (Shorts under 30 s perform best) -> trim")
            if narr and not S.get('narrator') and not any(isinstance(b, dict) and 'narrate' in b for x in scenes for b in x.get('beats', []) or []):
                R.warn('story', 'narrator', f"{fm} is a narrated format but there is no narrator or narrate beat -> add \"narrator\" and \"narrate\" beats")
            if fm in ('skit', 'pov', 'versus', 'rich_poor', 'time_skit') and not S.get('header'): R.warn('story', 'header', f"{fm} wants a persistent premise line -> add \"header\"")
            ctypes = {c.get('type') for c in S.get('cards', []) or [] if isinstance(c, dict)}
            for ft, ct in (('time_skit', 'time'), ('choice', 'choice'), ('in_this_world', 'title'), ('what_if', 'title')):
                if fm == ft and ct not in ctypes: R.warn('story', 'cards', f"{fm} wants a '{ct}' card -> add one to \"cards\"")
            if fm in ('versus', 'rich_poor') and not S.get('split'): R.warn('story', 'split', f"{fm} wants \"split\": [[1, 2]] (two scenes stacked)")
            if fm == 'pov' and not any(_cam_mode(S, x) == 'pov' for x in scenes): R.warn('story', 'camera', 'pov format but no scene has "camera": {"mode": "pov", "who": ...}')
    if 'header' in S:
        if not isinstance(S['header'], str) or not S['header'].strip(): R.err('story', 'header', 'must be a non-empty string')
        elif len(S['header']) > 90: R.warn('story', 'header', f"{len(S['header'])} characters: a header over ~90 does not fit the top of a 9:16 frame -> shorten")
    if 'captions' in S and S['captions'] not in ('cards', 'word'): R.err('story', 'captions', "-> 'cards' or 'word'")
    nv = S.get('narrator')
    if nv is not None:
        if not isinstance(nv, dict) or len(set(nv) & {'voice', 'file_dir'}) != 1 or set(nv) - {'voice', 'file_dir'} or not all(isinstance(v, str) and v for v in nv.values()):
            R.err('story', 'narrator', 'must be {"voice": "<name or id>"} or {"file_dir": "voice/narrator"} (exactly one, a non-empty string)')
        elif 'file_dir' in nv and not (sdir / nv['file_dir']).is_dir(): R.warn('story', 'narrator', f"folder '{nv['file_dir']}' not found next to the story")
    vs = S.get('voices')
    if vs is not None:
        if not isinstance(vs, dict) or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in vs.items()): R.err('story', 'voices', 'must be {"<character>": "<voice name or id>"}')
        else:
            names = {c.get('name') for c in S.get('cast', []) if isinstance(c, dict)}
            for k in vs:
                if k not in names: R.err('story', 'voices', f"'{k}' is not in the cast{near(k, names)}")
    cards = S.get('cards')
    if cards is not None:
        if not isinstance(cards, list): R.err('story', 'cards', 'must be a list of {"type", "text", "scene", "t", "dur"}')
        else:
            for i, c in enumerate(cards):
                w = f'cards[{i}]'
                if not isinstance(c, dict): R.err(w, 'card', 'must be an object'); continue
                unknown(R, w, c, CARD_KEYS, 'card')
                if c.get('type') not in CARD_TYPES: R.err(w, 'type', f"'{c.get('type')}' -> one of {sorted(CARD_TYPES)}")
                if c.get('type') == 'choice':
                    if not (isinstance(c.get('a'), str) and isinstance(c.get('b'), str) and c['a'] and c['b']): R.err(w, 'a/b', 'a choice card needs both "a" and "b" texts')
                elif not (isinstance(c.get('text'), str) and c['text'].strip()): R.err(w, 'text', 'missing or empty')
                sc_ = c.get('scene')
                if not (isinstance(sc_, int) and not isinstance(sc_, bool) and 1 <= sc_ <= N): R.err(w, 'scene', f'{sc_!r} -> a scene number 1..{N}'); continue
                if not num(c.get('t')) or c['t'] < 0: R.err(w, 't', 'seconds into the scene, a number >= 0'); continue
                if not num(c.get('dur')) or c['dur'] <= 0: R.err(w, 'dur', 'seconds, a number > 0'); continue
                if c['t'] + c['dur'] > secs(sc_) + 1e-6: R.err(w, 'dur', f"the card ends at {c['t'] + c['dur']:.2f} s, after scene {sc_} ends ({secs(sc_):g} s) -> shorten it or raise the scene seconds")
    sp = S.get('split')
    if sp is not None:
        if not isinstance(sp, list): R.err('story', 'split', 'must be a list of pairs [[1, 2]]')
        else:
            used = set()
            for i, pr in enumerate(sp):
                w = f'split[{i}]'
                if not (isinstance(pr, list) and len(pr) == 2 and all(isinstance(k, int) and not isinstance(k, bool) and 1 <= k <= N for k in pr)): R.err(w, 'pair', f'must be two scene numbers 1..{N}, e.g. [1, 2]'); continue
                if pr[0] == pr[1]: R.err(w, 'pair', 'a scene cannot be split against itself')
                if used & set(pr): R.err(w, 'pair', f'scene {sorted(used & set(pr))} is already in another pair')
                used |= set(pr)
                if abs(secs(pr[0]) - secs(pr[1])) > 0.5: R.warn(w, 'pair', f'scenes {pr[0]} and {pr[1]} last {secs(pr[0]):g} and {secs(pr[1]):g} s: the shorter half freezes -> give both the same "seconds"')
                lab = {c.get('scene') for c in cards or [] if isinstance(c, dict) and c.get('type') == 'label'}
                if not set(pr) <= lab: R.warn(w, 'pair', 'each half wants a "label" card (A / B) so the comparison reads')
    for si, sc in enumerate(scenes):
        W = f's{si + 1:02d}'; cw = sc.get('crowd')
        if cw is not None:
            if not isinstance(cw, dict): R.err(W, 'crowd', 'must be {"n": 12, "area": "back"}')
            else:
                unknown(R, W + ' crowd', cw, {'n', 'area', 'act'}, 'crowd')
                if not (isinstance(cw.get('n'), int) and not isinstance(cw.get('n'), bool) and 1 <= cw['n'] <= 40): R.err(W, 'crowd', '"n" must be a whole number 1..40')
                elif cw['n'] > 24: R.warn(W, 'crowd', f"{cw['n']} extras: build time grows; 6-14 reads as a crowd in 9:16")
                if cw.get('area', 'all') not in CROWD_AREAS: R.err(W, 'crowd', f"area '{cw.get('area')}' -> one of {sorted(CROWD_AREAS)}")
                if cw.get('act', 'mixed') not in ('idle', 'cheer', 'mixed'): R.err(W, 'crowd', "act -> idle, cheer or mixed")
        cam = sc.get('camera', S.get('camera'))
        if _cam_mode(S, sc) == 'pov':
            who = cam.get('who') if isinstance(cam, dict) else None
            sc_names = [c.get('name') for c in sc.get('cast', []) or [] if isinstance(c, dict)]
            if who not in sc_names: R.err(W, 'camera', f"pov needs \"who\": a character of this scene (got {who!r}){near(who, sc_names)}")
            elif len(sc_names) < 2: R.warn(W, 'camera', 'a pov scene with one character has nobody to look at the lens')
        prev = -1e9
        for bi, b in enumerate(sc.get('beats', []) or []):
            if not isinstance(b, dict): continue
            w = f'{W} beat[{bi}]'
            if 'narrate' in b:
                if not (isinstance(b['narrate'], str) and b['narrate'].strip()): R.err(w, 'narrate', 'must be a non-empty string')
                else:
                    if not S.get('narrator') and not b.get('narrate_voice'): R.warn(w, 'narrate', 'no top-level "narrator" -> voices.py has no voice for this line')
                    if num(b.get('t')):
                        if b['t'] < prev - 0.05: R.warn(w, 'narrate', f"starts at {b['t']} while the line before still runs until {prev:.1f} (~{NARR_WPS} words/s) -> start at {prev:.1f}")
                        prev = b['t'] + len(b['narrate'].split()) / NARR_WPS
                        if prev > secs(si + 1) + 0.5: R.warn(w, 'narrate', f"~{len(b['narrate'].split())} words end at ~{prev:.1f} s, after the scene ({secs(si + 1):g} s)")
            if 'narrate_voice' in b:
                if not (isinstance(b['narrate_voice'], str) and (sdir / b['narrate_voice']).exists()): R.err(w, 'narrate_voice', f"file {b['narrate_voice']!r} not found (path from the story folder)")
            if 'freeze' in b:
                fz = b['freeze']
                if not isinstance(fz, dict): R.err(w, 'freeze', 'must be {"label": "...", "dur": 1.0}')
                else:
                    unknown(R, w + ' freeze', fz, {'label', 'dur'}, 'freeze')
                    if not num(fz.get('dur', 1.0)) or not 0.2 <= fz.get('dur', 1.0) <= 3: R.err(w, 'freeze', '"dur" seconds 0.2..3')
                    if 'label' in fz and not isinstance(fz['label'], str): R.err(w, 'freeze', '"label" must be a string')


def _cam_mode(S, sc):
    cam = sc.get('camera', S.get('camera'))
    return cam if isinstance(cam, str) else cam.get('mode', 'story_cuts') if isinstance(cam, dict) else 'story_cuts'


def check_looks(R, L, w, c):
    if 'hair_style' in c and not L.hair_ok(str(c['hair_style'])):
        R.err(w, 'hair_style', f"'{c['hair_style']}' not found (falls back to a default) -> spiky/short/long/ponytail/bun/none or lib:<tag> from assets/hair/LIBRARY.md{near(c['hair_style'], HAIR_BUILTIN)}")
    if 'face' in c and not L.face_ok(c['face']):
        R.err(w, 'face', f"unknown face '{c['face']}' (replaced by a default) -> a face kind from short.schema.md section 4{near(c['face'], L.faces)}")
    if 'face_family' in c and c['face_family'] not in FAMILIES: R.err(w, 'face_family', f"'{c['face_family']}' -> drawn, classic or bigeye")
    for m in c.get('face_marks', []) or []:
        if m not in L.marks: R.err(w, 'face_marks', f"unknown mark '{m}' (not drawn) -> one of {sorted(L.marks)}{near(m, L.marks)}")
    o = c.get('outfit')
    if o is not None:
        if not isinstance(o, dict): R.err(w, 'outfit', 'must be {"shirt": "lib:<tag>", "pants": "lib:<tag>"}')
        else:
            for k, v in o.items():
                if k not in ('shirt', 'pants'): R.err(w, 'outfit', f"unknown key '{k}' -> shirt / pants")
                elif not L.outfit_ok(v, k): R.err(w, 'outfit', f"{k} '{v}' not in assets/outfits (plain colour instead) -> a tag from assets/outfits/LIBRARY.md")
    for k in ('shirt', 'pants', 'skin', 'hair'):
        if k in c and not re.fullmatch(r'#[0-9A-Fa-f]{6}', str(c[k])): R.err(w, k, f"'{c[k]}' is not a #RRGGBB colour")
    h = c.get('hair')
    if isinstance(h, str) and re.fullmatch(r'#[0-9A-Fa-f]{6}', h) and str(c.get('hair_style', 'spiky')) != 'none':
        if max(int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)) < 0x24:
            R.warn(w, 'hair', f'{h} is near-black: outdoors it crushes to a silhouette -> use #2A2A2E or lighter')


def lint_scene(R, L, S, sc, si, looks, sdir, fps):
    W = f's{si + 1:02d}'
    unknown(R, W, sc, SCENE, 'scene')
    secs = sc.get('seconds')
    if not num(secs) or secs <= 0: R.err(W, 'seconds', 'missing or not a positive number -> "seconds": 6'); secs = 1e9
    st = {**S.get('set', {}), **sc.get('set', {})} if isinstance(sc.get('set', {}), dict) else {}
    unknown(R, W + ' set', st, SET, 'set')
    preset = st.get('preset', 'classroom')
    known_presets = set(L.presets) | {'classroom', 'room', 'rbx'}
    if preset not in known_presets: R.err(W + ' set', 'preset', f"unknown preset '{preset}' (an empty room instead) -> one of {sorted(known_presets)}{near(preset, known_presets)}")
    if preset == 'rbx' and not any(str(st.get('rbx', '')).lower() in d for d in L.rbx):
        R.err(W + ' set', 'rbx', f"'{st.get('rbx')}' not in assets/rbxsets -> a slug from assets/rbxsets/LIBRARY.md")
    if 'floor' in st and st['floor'] not in FLOORS: R.err(W + ' set', 'floor', f"'{st['floor']}' -> one of {sorted(FLOORS)}")
    if 'time' in st and st['time'] not in TIMES: R.err(W + ' set', 'time', f"'{st['time']}' -> day, evening or night")
    if 'mood' in st and st['mood'] not in LIGHT_MOODS:
        R.err(W + ' set', 'mood', f"light mood '{st['mood']}' unknown -> one of {sorted(LIGHT_MOODS)} (music loops go in the story/scene key, not set.mood)")
    if 'music' in sc and sc['music'] not in L.music: R.err(W, 'music', f"music loop '{sc['music']}' does not exist -> one of {sorted(L.music)}{near(sc['music'], L.music)}")
    pinfo = L.presets.get(preset, {'size': [28, 24], 'outdoor': False} if preset == 'room' else {'size': None, 'outdoor': False})
    size = st.get('size', pinfo['size']) if preset not in ('rbx', 'classroom') else None
    outdoor = st.get('outdoor', pinfo['outdoor'])
    pieces = set(L.pieces.get(preset, set()))
    for d in st.get('dress', []) or []:
        if isinstance(d, dict):
            if d.get('name'): pieces.add(d['name'])
            for x in d.get('row', []) or []:
                if isinstance(x, dict) and x.get('name'): pieces.add(x['name'])
    def piece_ok(n):
        n = re.sub(r'\.\d{3}$', '', str(n))   # '.001' = the next one of the same piece
        return preset in ('rbx', 'classroom') or n in pieces or any(p.startswith(n) for p in pieces) or not pieces
    cam = sc.get('camera', S.get('camera'))
    mode = cam if isinstance(cam, str) else cam.get('mode', 'story_cuts') if isinstance(cam, dict) else 'story_cuts'
    if isinstance(cam, dict): unknown(R, W + ' camera', cam, CAMERA, 'camera')
    if mode not in MODES: R.err(W, 'camera', f"unknown mode '{mode}' -> one of {sorted(MODES)}{near(mode, MODES)}")

    # cast
    cast = {}
    for i, c in enumerate(sc.get('cast', []) or []):
        w = f'{W} cast[{i}]'
        if not isinstance(c, dict) or 'name' not in c: R.err(w, 'name', 'every scene cast entry needs a "name"'); continue
        n = c['name']
        if n not in looks: R.err(w, 'name', f"'{n}' is not in the story cast (story.py crashes) -> add it to the top-level cast{near(n, looks)}")
        if n in cast: R.err(w, 'name', f"'{n}' twice in this scene")
        unknown(R, w, c, SCAST, 'scene cast'); check_looks(R, L, w, {k: v for k, v in c.items() if k in LOOKS})
        at = c.get('at', [0, 0])
        if not is_xy(at): R.err(w, 'at', 'must be [x, y] studs'); at = [0, 0]
        cast[n] = (float(at[0]), float(at[1]))
        if size and is_xy(size):
            hx, hy = size[0] / 2, size[1] / 2
            if abs(at[0]) > hx or abs(at[1]) > hy:
                (R.warn if outdoor else R.err)(w, 'at', f'{list(at)} is outside the {size[0]}x{size[1]} set -> keep |x| < {hx:g}, |y| < {hy:g}')
    names = list(cast)
    downs = {b.get('who') for b in sc.get('beats', []) or [] if isinstance(b, dict) and 'down' in b}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            d = dist(cast[a], cast[b])
            if d < 3.0 and not (a in downs or b in downs): R.warn(W + ' cast', 'at', f'{a} and {b} start {d:.1f} studs apart (bodies touch) -> at least 3 studs')

    # props
    props = {}
    for i, p in enumerate(sc.get('props', []) or []):
        w = f'{W} prop[{i}]'
        if not isinstance(p, dict) or 'name' not in p: R.err(w, 'name', 'every prop needs a "name"'); continue
        unknown(R, w, p, PROP, 'prop'); props[p['name']] = p
        k = str(p.get('kind', 'box'))
        if k.startswith('screen'):
            img = k.partition(':')[2]
            if not img or not (Path(img) if os.path.isabs(img) else E / img).exists():
                R.err(w, 'kind', f"screen image '{img}' not found (a blank screen) -> path from the engine folder, e.g. screen:stories/<name>/screen.png")
        elif k not in PROP_BUILTIN and not L.kenney_ok(k):
            R.err(w, 'kind', f"prop kind '{k}' is not built-in ({', '.join(sorted(PROP_BUILTIN))}) and not a Kenney model (assets/kenney/catalog.md)")
        if p.get('held_by') and p['held_by'] not in cast: R.err(w, 'held_by', f"'{p['held_by']}' is not in this scene's cast{near(p['held_by'], cast)}")
        if p.get('on') and not piece_ok(p['on']): R.warn(w, 'on', f"'{p['on']}' is not a known set piece of '{preset}' -> an exact name from short.schema.md 'Preset pieces' or a dress name")
    def prop_xy(n):
        p = props.get(n)
        if not p: return None
        if p.get('held_by') in cast: return None
        return tuple(p['at'][:2]) if is_xy(p.get('at')) and not p.get('on') else None

    # beats
    beats = sc.get('beats', []) or []
    T = Track(cast); talks = []; last_attack = {}
    def target_ok(w, key, v, allow_xy=False):
        if isinstance(v, str):
            if v in cast or v in props: return True
            if piece_ok(v): return True
            R.warn(w, key, f"'{v}' is not a cast, prop or known set-piece name of '{preset}'{near(v, list(cast) + list(props) + list(pieces))}"); return False
        if allow_xy and is_xy(v): return True
        return False
    order = sorted(range(len(beats)), key=lambda i: beats[i].get('t', 0) if isinstance(beats[i], dict) and num(beats[i].get('t')) else 0)
    for i in order:
        b = beats[i]; w = f'{W} beat[{i}]'
        if not isinstance(b, dict): R.err(w, 'beat', 'must be an object'); continue
        unknown(R, w, b, BEAT, 'beat')
        t = b.get('t'); who = b.get('who')
        if not num(t): R.err(w, 't', 'missing or not a number (seconds)'); continue
        if who not in cast: R.err(w, 'who', f"'{who}' is not in this scene's cast{near(who, cast)}"); continue
        if t < 0 or t > secs: R.err(w, 't', f'{t} is outside the scene (0..{secs}) and is ignored -> move it inside or raise "seconds"')
        for k, allowed in SUB.items():
            v = b.get(k)
            if isinstance(v, dict): unknown(R, f'{w} {k}', v, allowed, k)
        if isinstance(b.get('beam'), dict) and isinstance(b['beam'].get('deflect'), dict): unknown(R, f'{w} beam.deflect', b['beam']['deflect'], {'after', 'to', 'hand'}, 'deflect')
        # names
        pose = b.get('pose')
        if isinstance(pose, str) and pose not in L.poses: R.err(w, 'pose', f"unknown pose '{pose}' (nearest pose or dropped){near(pose, L.poses)}")
        if isinstance(pose, dict):
            for ch in pose:
                if ch not in CHANNELS: R.err(w, 'pose', f"channel '{ch}' -> R, L, legR, legL, head, body{near(ch, CHANNELS)}")
        if 'face' in b and not L.face_ok(b['face']): R.err(w, 'face', f"unknown face '{b['face']}' (replaced by a default){near(b['face'], L.faces)}")
        if 'anim' in b and b['anim'] not in L.anims: R.err(w, 'anim', f"unknown anim '{b['anim']}' -> a slug from assets/anims/LIBRARY.md{near(b['anim'], L.anims)}")
        if 'wiggle' in b and b['wiggle'] not in CHANNELS: R.err(w, 'wiggle', f"'{b['wiggle']}' -> R, L, legR, legL, head, body")
        if 'sfx' in b and str(b['sfx']).split('/')[0] not in L.sfx: R.err(w, 'sfx', f"sound '{b['sfx']}' has no folder in assets/sfx (sound_mix crashes){near(b['sfx'], L.sfx)}")
        if 'type' in b and not num(b['type']): R.err(w, 'type', 'seconds of keyboard typing, a number')
        for k in ('look', 'turn'):
            if isinstance(b.get(k), str): target_ok(w, k, b[k])
        if isinstance(b.get('sit'), str): target_ok(w, 'sit', b['sit'])
        for k in ('grab', 'give', 'throw'):
            v = b.get(k)
            if isinstance(v, dict):
                if v.get('prop') not in props: R.err(w, k, f"prop '{v.get('prop')}' is not in this scene's props (props are declared per scene){near(v.get('prop'), props)}")
                if k == 'give' and v.get('to') not in cast: R.err(w, 'give', f"'to' '{v.get('to')}' is not in this scene's cast{near(v.get('to'), cast)}")
            elif v is not None: R.err(w, k, f'must be an object, e.g. {{"prop": "cup"{", " + chr(34) + "to" + chr(34) + ": " + chr(34) + "Lia" + chr(34) if k != "grab" else ""}}}')
        # seated
        if b.get('stand'): Track.close_span(T.seated[who], t)
        seated = Track.inside([s for s in T.seated[who] if s[0] < t], t)
        if seated and ('walk' in b or ('turn' in b and 'sit' not in b)):
            R.warn(w, 'walk' if 'walk' in b else 'turn', f'{who} is seated: a turn/walk without "stand" breaks the seat -> add {{"t": {t}, "who": "{who}", "stand": true}} first')
        # movement
        if 'walk' in b:
            wv = b['walk']; goal = None; pts = wv if isinstance(wv, list) else [wv]
            if isinstance(wv, list) and is_xy(wv) and not isinstance(wv[0], list):
                R.err(w, 'walk', f'a bare point {wv} is read as two names -> wrap it: [[{wv[0]}, {wv[1]}]]'); pts = []
            p = T.at(who, t); length = 0.0
            for e in pts:
                q = None
                if is_xy(e): q = (float(e[0]), float(e[1]))
                elif isinstance(e, str):
                    target_ok(w, 'walk', e)
                    q = toward(p, T.at(e, t), 3.0) if e in cast else prop_xy(e)
                if q is not None and p is not None: length += dist(p, q)
                p = q
            goal = p
            if goal is not None and size and is_xy(size) and not outdoor and (abs(goal[0]) > size[0] / 2 or abs(goal[1]) > size[1] / 2):
                R.err(w, 'walk', f'goal {[round(goal[0], 1), round(goal[1], 1)]} is outside the {size[0]}x{size[1]} room')
            sp_ = b.get('speed', 13 if b.get('run') else WALK_SPEED) or WALK_SPEED
            T.move(who, t, t + length / sp_, goal)
        if b.get('sit'): Track.open_span(T.seated[who], t)
        if isinstance(b.get('fly'), dict):
            fl = b['fly']; to = fl.get('to'); s_ = float(fl.get('s', 1.0)); p0 = T.at(who, t)
            if isinstance(to, str):
                if to not in cast: R.err(w, 'fly', f"'to' '{to}' is not in this scene's cast{near(to, cast)}"); q = None
                else: q = toward(p0, T.at(to, t + s_), GUARD)
            elif isinstance(to, list) and to and is_xy(to[-1]): q = tuple(map(float, to[-1][:2]))
            else: R.err(w, 'fly', 'to must be a list of [x, y] points ([[4, 0]]) or a cast name'); q = None
            if q is not None and p0 is not None and s_ > 0 and dist(p0, q) / s_ > 25 and not Track.inside(T.flying[who], t - 0.05):
                R.warn(w, 'fly', f'{dist(p0, q):.0f} studs in {s_} s from the ground reads as a teleport -> s >= {math.ceil(dist(p0, q) / 2.5) / 10:.1f} or start from the air')
            if q is not None and size and is_xy(size) and (abs(q[0]) > size[0] / 2 - 1 or abs(q[1]) > size[1] / 2 - 1):
                R.warn(w, 'fly', f'lands at {[round(q[0], 1), round(q[1], 1)]}, outside the {size[0]}x{size[1]} set')
            T.move(who, t, t + s_, q); Track.open_span(T.flying[who], t)
        if b.get('land'): Track.close_span(T.flying[who], t)
        if 'down' in b: Track.open_span(T.lying[who], t)
        if b.get('fall'): Track.open_span(T.lying[who], t + 0.5)
        if b.get('get_up'): Track.close_span(T.lying[who], t)
        # fight
        a = b.get('attack')
        if a is not None:
            if not isinstance(a, dict): R.err(w, 'attack', 'must be {"move": "punch_R", "target": "<name>"}')
            else:
                tg = a.get('target'); fl_ = a.get('flurry')
                if tg not in cast or tg == who: R.err(w, 'attack', f"target '{tg}' is not another character in this scene{near(tg, cast)}")
                if fl_ is not None:
                    if not (isinstance(fl_, list) and len(fl_) >= 2 and all(m in L.attacks for m in fl_)): R.err(w, 'attack', f'flurry must be a list of 2+ strikes from {sorted(L.attacks)}')
                elif a.get('move') not in L.attacks: R.err(w, 'attack', f"move '{a.get('move')}' -> one of {sorted(L.attacks)}{near(a.get('move'), L.attacks)}")
                if tg in cast and tg != who:
                    tw = t - 0.55; d = dist(T.at(who, tw), T.at(tg, tw))
                    if d is not None and d > REACH + 0.3:
                        R.err(w, 'attack', f'{who} is {d:.1f} studs from {tg} at the wind-up (t {tw:.2f}); a strike needs <= {REACH} -> walk/fly in earlier or move the attack later')
                    elif d is not None and d > REACH: R.warn(w, 'attack', f'{who} is {d:.1f} studs from {tg} at the wind-up, the limit is {REACH}')
                    pa, pt = T.at(who, t), T.at(tg, t)
                    if pa is not None and pt is not None and dist(pa, pt) > GUARD: T.move(who, tw, t, toward(pa, pt, GUARD))
                if fl_ is None:
                    lt = last_attack.get(who)
                    if lt is not None and t - lt < 0.6: R.warn(w, 'attack', f'{t - lt:.2f} s after the previous strike of {who} -> leave >= 0.6 s (or use "flurry")')
                    last_attack[who] = t
                else: last_attack[who] = t + float(a.get('s') or 0.3 * (len(fl_) - 1))
        kb = b.get('knockback')
        if kb is not None:
            if not isinstance(kb, dict): R.err(w, 'knockback', 'must be {"from": "<name>", "distance": 8}')
            else:
                fr = kb.get('from')
                if fr not in cast or fr == who: R.err(w, 'knockback', f"'from' '{fr}' is not another character in this scene{near(fr, cast)}")
                p0 = T.at(who, t); land = None
                if is_xy(kb.get('to')): land = (float(kb['to'][0]), float(kb['to'][1]))
                elif fr in cast and p0 is not None:
                    pf = T.at(fr, t); dx, dy = p0[0] - pf[0], p0[1] - pf[1]; dd = math.hypot(dx, dy) or 1.0; k_ = float(kb.get('distance', 8))
                    land = (p0[0] + dx / dd * k_, p0[1] + dy / dd * k_)
                if land is not None:
                    if size and is_xy(size) and (abs(land[0]) > size[0] / 2 - 1 or abs(land[1]) > size[1] / 2 - 1):
                        R.warn(w, 'knockback', f'lands at {[round(land[0], 1), round(land[1], 1)]}, outside the set (the engine shortens it) -> a "to" inside |x| < {size[0] / 2 - 1:g}, |y| < {size[1] / 2 - 1:g}')
                    for o in cast:
                        if o == who: continue
                        po = T.at(o, t + 1.0); r = 2.6 + (1.7 if T.inside(T.lying[o], t + 1.0) else 1.4)
                        if po is not None and dist(po, land) < r - 0.6:
                            R.warn(w, 'knockback', f'lands {dist(po, land):.1f} studs from {o} (the engine turns or shortens the blast) -> a "to" >= {r:.1f} studs from {o}')
                    T.move(who, t, t + 1.0, land)
                Track.open_span(T.lying[who], t + 1.0)
        bm = b.get('beam')
        if isinstance(bm, dict):
            if isinstance(bm.get('to'), str) and bm['to'] not in cast: R.err(w, 'beam', f"'to' '{bm['to']}' is not in this scene's cast{near(bm['to'], cast)}")
            df = bm.get('deflect')
            if isinstance(df, dict) and not (0 < float(df.get('after', 0.5)) < float(bm.get('s', 1.0)) - 0.1):
                R.err(w, 'beam', f"deflect.after must be inside the beam: 0 < after < s - 0.1 (s = {bm.get('s', 1.0)})")
            if t - float(bm.get('charge', 0.6)) < 0: R.warn(w, 'beam', 'the charge starts before the scene -> t >= charge')
        # speech
        say, talk = b.get('say'), b.get('talk')
        if talk is not None and not num(talk): R.err(w, 'talk', 'seconds, a number')
        voice = b.get('voice'); vdur = None
        if voice:
            vp = sdir / voice
            if not vp.exists(): R.err(w, 'voice', f"file '{voice}' not found (path from the story folder) -> record it or fix the path")
            else: vdur = audio_seconds(str(vp))
        if say and talk is None: R.warn(w, 'talk', f'"say" without "talk": captions show but the mouth does not move -> "talk": {round(vdur or WORD_S * len(str(say).split()), 2)}')
        if num(talk):
            if vdur:
                if abs(talk - vdur) > 0.35: R.warn(w, 'talk', f'{talk} s but the voice file lasts {vdur:.2f} s -> "talk": {vdur:.2f}')
            elif say:
                exp = WORD_S * len(str(say).split())
                if abs(talk - exp) > max(1.0, 0.6 * exp): R.warn(w, 'talk', f'{talk} s for {len(str(say).split())} words (~{exp:.1f} s at 0.38 s/word) -> "talk": {exp:.1f}')
            if t + talk > secs + 0.05: R.warn(w, 'talk', f'the line ends at {t + talk:.2f}, after the scene end {secs} -> raise "seconds" or start earlier')
            talks.append((t, t + talk, who, i))
    # sorted enough (in file order)
    ts = [b.get('t') for b in beats if isinstance(b, dict) and num(b.get('t'))]
    for i in range(1, len(ts)):
        if ts[i] < max(ts[:i]) - 1.5: R.warn(f'{W} beat[{i}]', 't', f'{ts[i]} comes after a beat at {max(ts[:i])} in the file: keep beats in time order so they are easy to read')
    talks.sort()
    for x in range(len(talks)):
        for y in range(x + 1, len(talks)):
            a0, a1, aw, ai = talks[x]; b0, b1, bw, bi = talks[y]
            if b0 < a1 - 0.15:
                R.warn(f'{W} beat[{bi}]', 'talk', f'{bw} speaks at {b0} while {aw} (beat[{ai}]) is still talking until {a1:.2f} -> start at {a1:.2f} or shorten beat[{ai}]')

    # shots
    shots = sc.get('shots', []) or []
    if shots and mode in ('follow_oneshot', 'ots_dialogue', 'static_wide', 'chase_track', 'two_shot_react'):
        R.warn(W, 'shots', f"camera mode '{mode}' writes its own shots: yours are ignored")
    ss = sorted([(s.get('t', 0), k) for k, s in enumerate(shots) if isinstance(s, dict) and num(s.get('t'))])
    if ss and ss[0][0] > 0.01: R.warn(f'{W} shot[{ss[0][1]}]', 't', f'the first shot starts at {ss[0][0]} -> the first shot needs "t": 0')
    for j, (st0, k) in enumerate(ss):
        s = shots[k]; w = f'{W} shot[{k}]'; st1 = ss[j + 1][0] if j + 1 < len(ss) else secs
        unknown(R, w, s, SHOT, 'shot')
        if st0 > secs: R.err(w, 't', f'{st0} is after the scene end {secs}: never shown')
        if st1 - st0 < 0.5 - 1e-6 and st1 <= secs: R.warn(w, 't', f'{st1 - st0:.2f} s long: shorter than 0.5 s reads as a glitch -> merge it')
        kind = s.get('kind', 'medium')
        if kind not in L.sizes: R.err(w, 'kind', f"'{kind}' -> one of {sorted(L.sizes)}{near(kind, L.sizes)}")
        if 'angle' in s and s['angle'] not in ANGLES: R.err(w, 'angle', f"'{s['angle']}' -> low, high or top")
        if 'move' in s and s['move'] not in MOVES_CAM: R.err(w, 'move', f"'{s['move']}' -> one of {sorted(MOVES_CAM)}")
        on = s.get('on', names[:1])
        on = [on] if isinstance(on, str) else on
        bad = [n for n in on if n not in cast and n not in props]
        for n in bad: R.err(w, 'on', f"'{n}' is not a cast or prop name of this scene (set pieces are not accepted){near(n, list(cast) + list(props))}")
        on = [n for n in on if n in cast]
        if on and kind in ('close', 'insert', 'medium'):
            f = on[0]; mid = (st0 + min(st1, secs)) / 2
            if kind == 'close' and (T.inside(T.lying[f], mid) or T.inside(T.flying[f], mid)):
                R.warn(w, 'kind', f"close-up on {f} while lying/flying: the face is lost -> 'wide' with \"angle\": \"top\" (+ \"frame\": 11) for a body on the ground")
        if len(on) >= 2 and not s.get('keep_two'):
            d = dist(T.at(on[0], st0), T.at(on[1], st0))
            if d is not None and d > 8: R.warn(w, 'on', f'{on[0]} and {on[1]} are {d:.1f} studs apart: the engine makes it a single on {on[0]} -> add "keep_two": true')
        if s.get('angle') == 'top' and kind in ('close', 'medium'): R.warn(w, 'angle', 'a top view this tight cuts the body -> "kind": "wide" + "frame": 11')
        if s.get('shake'):
            sh = s['shake'] if isinstance(s['shake'], list) else [s['shake']]
            for x in sh:
                if num(x) and not (st0 <= x <= st1): R.warn(w, 'shake', f'shake at {x} is outside this shot ({st0}..{st1:.2f}): shakes belong to the shot that shows them')


def main():
    if len(sys.argv) < 2: print(__doc__); sys.exit(2)
    R = lint(sys.argv[1])
    if '--quiet' not in sys.argv or R.errors:
        for l in R.lines(): print(l)
    print(f'LINT {"FAIL" if R.errors else "OK"} | {len(R.errors)} error(s), {len(R.warnings)} warning(s) | {sys.argv[1]}')
    sys.exit(1 if R.errors else 0)


if __name__ == '__main__':
    main()
