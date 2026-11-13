"""acting.py - AUTOMATIC ACTING LAYER (critic R195: 'stiff square poses, face-only acting, same idle reused').
inject(spec, beats, log) adds ordinary beats (marked 'auto': True) to a scene's beat list, from what the story already says:
  1. LISTENER REACTION  while someone talks, each free listener reacts once ~0.5 s into the line: shouted at -> cower pose +
                        scared face; a joke -> Roblox 'laugh' clip; a question -> 'shrug' clip; else a nod ('agree') on every
                        other line. The face returns to what it was 1.6 s later.
  2. EMOTION SILHOUETTE a beat that only sets a strong face (shock, angry, sad, scared, joy...) gets the matching body pose,
                        released to idle 1.5 s later if the character is still free.
  0. START STANCE       a standing character with nothing to do in the first second opens the scene in a stance, not square.
  3. IDLE LIFE          a standing character with nothing to do for > 2.5 s changes its stance (poses 'stand_a/b/c':
                        contrapposto, never square) and glances at whoever is talking.
  4. AFTER A LINE       a speaker's last talk gesture is not left frozen: 0.35 s after the line the arms come down into a
                        stance, if the character stays free.
  5. MOOD MIRROR        a listener with a plain face picks up the speaker's mood for the line (joy -> happy, sad -> worry).
v2 (critic R195 'face-only acting, narrow range'): every pick ALTERNATES per character (shock -> recoil -> shock, cower ->
recoil, sad -> slump, a question -> shrug clip -> 'curious' lean), so the same emotion never gives the same body twice.
Stance beats carry 'stance': True: the camera never cuts to someone for only changing stance.
Everything goes through the normal beat machinery (motion_trial, clear_gesture, the gates): nothing here keys anything.
A character who CARRIES a prop in one hand acts with the rest of the body (that arm is skipped: it belongs to the prop); a
taker of a handoff (the build picks the hand) is left alone. A SEATED character only shifts its chest (no arms, no lean
forward: the table). Explicit story beats always win (a character is only touched while it has no beat of its own); the build skips an auto beat
whose character is still moving or on the floor when its frame comes. Off: story or scene key "auto_acting": false.
Pure Python (no bpy): python acting.py runs the self-check."""

ACTION = ('walk', 'run', 'grab', 'give', 'sit', 'stand', 'fall', 'get_up', 'jump', 'turn', 'anim', 'wiggle', 'dodge', 'down')
FIGHT = ('attack', 'block', 'knockback', 'fly', 'land', 'aura', 'beam', 'charge', 'transform', 'impact')
SILHOUETTE = (('shock', ('shock', 'recoil')), ('scream', ('shock', 'hands_up')), ('angry', ('angry', 'lean_in')), ('furious', ('angry',)),
              ('cry', ('sad', 'slump')), ('sad', ('sad', 'slump')), ('scared', ('cower', 'recoil')), ('joy', ('cheer', 'fist_pump_R')),
              ('laugh', ('cheer', 'fist_pump_R')), ('smug', ('gloat', 'proud')), ('confused', ('curious', 'shrug')))
STANCES = ('stand_a', 'stand_b', 'stand_c')
MIRROR = (('joy', 'emo:happy'), ('laugh', 'emo:happy'), ('grin', 'emo:happy'), ('happy', 'emo:happy'), ('sad', 'worry'), ('cry', 'worry'))
PLAIN = ('smile', 'neutral', 'lib:smile', 'emo:neutral')


def _dur(b):
    if 'talk' in b: return float(b['talk']) + 0.3
    if 'anim' in b: return float(b.get('loop', 2.0)) + 0.5
    if any(k in b for k in ACTION): return 3.0   # approach + action: real length unknown before the build (the build re-checks)
    return 1.0


def _reaction(tb, k=0):
    """(pose or None, anim or None, face) a listener plays for the talk beat tb, or None for a plain line. k = how many
    reactions this listener has played: the second answer to the same kind of line is a different body."""
    mood = (str(tb.get('face', '')) + ' ' + str(tb.get('pose', ''))).lower(); say = str(tb.get('say', ''))
    if any(w in mood for w in ('angry', 'scream', 'furious', 'evil')) or say.isupper() and len(say) > 3: return ('cower', 'recoil')[k % 2], None, 'emo:scared'
    if any(w in mood for w in ('laugh', 'joy', 'silly', 'grin', 'smug')): return None, 'laugh', 'emo:laugh'
    if '?' in say: return (None, 'shrug', 'emo:confused') if k % 2 == 0 else ('curious', None, 'emo:confused')
    return None


def inject(spec, beats, log, valid_face=lambda f: True):
    if not spec.get('auto_acting', True) or any(k in b for b in beats for k in FIGHT): return beats
    names = [c['name'] for c in spec['cast']]; T = float(spec['seconds'])
    own = {n: sorted((b for b in beats if b['who'] == n), key=lambda b: b['t']) for n in names}
    hands = {}   # name -> the hands that carry a prop at some point of the scene (those arms belong to the prop)
    for p in spec.get('props', []):
        if p.get('held_by'): hands.setdefault(p['held_by'], set()).add(p.get('hand', 'R'))
    for b in beats:
        if 'grab' in b: hands.setdefault(b['who'], set()).add(b['grab'].get('hand', 'R') if isinstance(b['grab'], dict) else 'R')
        if isinstance(b.get('give'), dict): hands.setdefault(b['give']['to'], set()).update('RL')   # the build picks the taking hand
    holding = {n for n, h in hands.items() if len(h) > 1}   # both arms taken: never touched
    carry = lambda n: sorted(hands.get(n, ()))
    def free(n, a, z):
        return not any(b['t'] - 0.4 < z and b['t'] + _dur(b) > a for b in own[n])
    def state(n, t, key_on, key_off):   # e.g. on the floor at t: last 'fall' later than last 'get_up'
        on = max([b['t'] for b in own[n] if (key_on in b or (key_on == 'fall' and 'down' in b)) and b['t'] <= t] or [-1])   # a character that starts 'down' lies like a fallen one
        off = max([b['t'] for b in own[n] if key_off in b and b['t'] <= t] or [-1])
        return on > off
    def face_at(n, t):
        c = next(c for c in spec['cast'] if c['name'] == n)
        return next((b['face'] for b in reversed(own[n]) if 'face' in b and b['t'] <= t), c.get('face', 'smile'))
    out = []; note = lambda s: log.setdefault('notes', []).append('auto acting: ' + s)
    # 2. EMOTION SILHOUETTE (first: it edits story beats in place, the other two then see them as busy)
    used = {}
    for b in beats:
        n = b['who']
        if n not in names or 'face' not in b or 'pose' in b or 'talk' in b or 'look' in b or any(k in b for k in ACTION) or n in holding: continue
        if state(n, b['t'], 'fall', 'get_up') or state(n, b['t'], 'sit', 'stand'): continue
        opts = next((p for w, p in SILHOUETTE if w in str(b['face']).lower()), None)
        if opts is None: continue
        pose = opts[used.get((n, opts), 0) % len(opts)]; used[(n, opts)] = used.get((n, opts), 0) + 1
        b['pose'] = pose; b['auto_pose'] = True; b['_skip'] = list(b.get('_skip', ())) + carry(n); note(f"t{b['t']} {n} face {b['face']} -> body pose {pose}")
        nxt = next((x['t'] for x in own[n] if x['t'] > b['t']), T)
        if nxt - b['t'] > 2.2 and b['t'] + 1.5 < T - 0.3:
            out.append({'t': round(b['t'] + 1.5, 3), 'who': n, 'stance': True, 'pose': STANCES[(names.index(n) + len(out)) % 3], '_skip': carry(n), 'auto': True})
    # 0. START STANCE: nobody opens a scene standing square (skipped for a character who acts, walks or sits within the first second)
    for i, n in enumerate(names):
        first = own[n][0] if own[n] else None
        if n in holding or any('sit' in x for x in own[n][:1]) or (first and first['t'] < 1.0 and any(k in first for k in ACTION + ('pose', 'talk'))): continue
        out.append({'t': 0.0, 'who': n, 'stance': True, 'pose': STANCES[i % 3], '_skip': ['head'] + carry(n), 'move': 1, 'auto': True}); note(f"t0 {n} opens in {STANCES[i % 3]}")
    # 1. LISTENER REACTIONS
    last = {}; nods = 0; played = {}
    for tb in sorted((b for b in beats if b.get('talk') and b['who'] in names), key=lambda b: b['t']):
        plain = _reaction(tb) is None; nods += plain; tr = round(tb['t'] + 0.5, 3)
        mood = (str(tb.get('face', '')) + ' ' + str(face_at(tb['who'], tb['t']))).lower()
        for n in names:
            pose, anim, face = _reaction(tb, played.get(n, 0)) or (None, 'agree' if nods % 2 else None, None)
            if plain:   # MOOD MIRROR: a plain-faced listener picks up the speaker's mood for the line
                face = next((f_ for w, f_ in MIRROR if w in mood and face_at(n, tr) in PLAIN), None)
                if not anim and not face: continue
            if n == tb['who'] or n in holding or tr - last.get(n, -9) < 2.5 or tr + 1.8 > T: continue
            if not free(n, tr - 0.3, tr + 2.0) or state(n, tr, 'fall', 'get_up'): continue
            if state(n, tr, 'sit', 'stand') and pose: continue   # seated: clips play upper body only (the build), poses lean: skip
            nb = {'t': tr, 'who': n, 'auto': True, '_skip': carry(n)}
            if pose: nb['pose'] = pose
            if anim: nb['anim'] = anim; nb['anim_skip'] = ['legR', 'legL'] + (['R', 'L'] if anim == 'agree' else carry(n))   # a nod is head + chest (its arm keys cut Zed's own hair 2.7 cm); upper body only: a reaction never steps (the 'agree' clip slid Zed's feet 6.4 cm)
            if face and valid_face(face):
                nb['face'] = face; out.append({'t': round(tr + 1.6, 3), 'who': n, 'face': face_at(n, tr), 'auto': True})
            if pose: out.append({'t': round(tr + 1.6, 3), 'who': n, 'stance': True, 'pose': STANCES[(names.index(n) + len(out)) % 3], '_skip': carry(n), 'auto': True})
            out.append(nb); last[n] = tr; played[n] = played.get(n, 0) + (not plain); note(f"t{tr} {n} reacts to {tb['who']}: {pose or anim or face}")
    # 4. AFTER A LINE: the last talk gesture comes down into a stance
    for tb in [b for b in beats if b.get('talk') and b['who'] in names and b.get('gesture', True)]:
        n = tb['who']; t = round(tb['t'] + float(tb['talk']) + 0.35, 3)
        if n in holding or t + 1.0 > T or state(n, t, 'fall', 'get_up') or state(n, t, 'sit', 'stand'): continue
        if any(x is not tb and x['t'] - 0.4 < t + 1.2 and x['t'] + _dur(x) > t - 0.3 for x in own[n]) or any(x['who'] == n and abs(x['t'] - t) < 1.2 for x in out): continue
        out.append({'t': t, 'who': n, 'stance': True, 'pose': STANCES[(names.index(n) + len(out)) % 3], '_skip': ['head'] + carry(n), 'move': 7, 'auto': True})
        note(f"t{t} {n} line over: arms down into {out[-1]['pose']}")
    # 3. IDLE LIFE
    busy_auto = {n: [x['t'] for x in out if x['who'] == n] for n in names}
    for n in names:
        if n in holding: continue
        edges = [0.0] + [b['t'] + _dur(b) for b in own[n]]; starts = [b['t'] for b in own[n]] + [T]
        k = 0
        for a, z in zip(edges, starts):
            t = a + 1.5
            while t < z - 1.0 and t < T - 0.8:
                if not state(n, t, 'fall', 'get_up') and all(abs(t - x) > 1.8 for x in busy_auto[n]):
                    nb = {'t': round(t, 3), 'who': n, 'stance': True, 'pose': STANCES[(names.index(n) + k) % 3], '_skip': ['head'] + carry(n), 'move': 8, 'auto': True}; k += 1
                    if state(n, t, 'sit', 'stand'): nb.update(pose={'body': (-1.0, 5.0 * (1 if k % 2 else -1), 2.5 * (1 if k % 2 else -1))}, _skip=['R', 'L', 'head'])
                    spk = next((b['who'] for b in beats if b.get('talk') and b['who'] != n and b['t'] <= t <= b['t'] + float(b['talk'])), None)
                    if spk: nb['look'] = spk
                    out.append(nb); note(f"t{nb['t']} {n} idle life: {nb['pose'] if isinstance(nb['pose'], str) else 'seated shift'}{' + glance at ' + spk if spk else ''}")
                t += 2.5
    return sorted(beats + out, key=lambda b: b['t'])


# ---------------- EXPRESSION RANGE (critic R248: 'the same dot-and-line faces repeat; reference changes the whole face SHAPE per beat') ----------------
# face_pass() gives every face beat and every talk line an exact face ('_lib' on the beat; 'face' keeps the emotion word the camera
# and the silhouettes read): the writer's emotion always wins (an explicit 'lib:<slug>' is kept as written), the DRAWING is picked
# from the pool of that emotion (Roblox library faces + the built-in drawn kinds) by the beat's intensity, never one of the
# character's last two faces. Big beats (caps, '!', shock/fear/triumph poses) take the most exaggerated face of the emotion
# (meta 'intensity', tools/face_measure.py). Off: scene key "auto_faces": false (or "auto_acting": false).
FACE_EMO = {'smile': 'happy', 'grin': 'joy', 'o': 'shock', 'worry': 'sad', 'sheepish': 'sheepish', 'neutral': 'neutral', 'angry': 'angry',
            'sad': 'sad', 'smug': 'smug', 'scream': 'shock', 'joy': 'joy', 'cry': 'cry', 'scared': 'scared', 'confused': 'confused',
            'disgust': 'disgust', 'laugh': 'laugh'}                                                # built-in kind -> emotion pool
BUILTIN_I = {'smile': .35, 'grin': .55, 'o': .6, 'worry': .35, 'sheepish': .4, 'neutral': .2, 'angry': .6, 'sad': .5, 'smug': .45, 'scream': .9, 'joy': .7,
             'cry': .85, 'scared': .75, 'confused': .4, 'disgust': .6, 'laugh': .9}
BIG_EMO = ('shock', 'scared', 'cry', 'laugh', 'disgust', 'evil', 'angry')                         # emotions that start high
BIG_POSE = ('shock', 'hands_head', 'hands_up', 'cower', 'recoil', 'cheer', 'fist_pump', 'facepalm', 'tantrum', 'gloat', 'cover_mouth')
SAY_EMO = (('laugh', ('haha', 'lol', 'funny', 'hilarious')), ('disgust', ('ew', 'eww', 'gross', 'yuck', 'stinks', 'disgusting')),
           ('scared', ('help', 'scary', 'monster', 'ghost', 'afraid', 'hide')), ('shock', ('what', 'wow', 'whoa', 'no way', 'impossible', 'wait')),
           ('sad', ('sorry', 'miss', 'lost', 'dropped', 'broke', 'broken', 'alone', 'sad')), ('angry', ('stop', 'never', 'hate', 'mine', 'enough', 'grounded', 'how dare')),
           ('smug', ('told you', 'easy', 'obviously', 'of course', 'actually', 'technically', 'loophole', 'watching you')),
           ('joy', ('yes', 'yay', 'okay', 'great', 'thanks', 'thank you', 'won', 'win', 'best', 'awesome', 'deal')))
ACCENT = {'joy': 'joy_talk', 'laugh': 'laugh_talk'}   # drawn kinds with closed eyes cannot blink: a mouth pop instead (every other face blinks: '_shut')
# ---------------- FACE FAMILIES (LEVEL 1, creator bug '0:11 weird faces': one character switched between a thin-line Roblox decal and
# our thick drawn face mid-walk) ----------------
# A character wears ONE face family for the whole Short: 'drawn' = the built-in kinds (faces.py numpy drawings), library faces by
# meta 'family' (tools/face_measure.py: 'classic' = thin-line / dot eyes, 'bigeye' = outlined eyes with whites and pupils).
# decide_families() picks it per character (cast 'face_family' > the cast 'face' > the first face beat that names a family >
# 'drawn'; story.py decides over the whole story so every scene agrees); to_family() maps any face into the family by emotion
# (NEAR when the family has no face of that emotion) and intensity; pick_face(..., fam=) keeps the automatic picks inside it.
FAMILIES = ('drawn', 'classic', 'bigeye')
NEAR = {'cry': ('sad', 'scared'), 'scared': ('shock', 'sad'), 'laugh': ('joy', 'happy'), 'joy': ('happy', 'laugh'), 'happy': ('joy', 'laugh'),
        'confused': ('neutral', 'sheepish'), 'disgust': ('angry', 'sad'), 'evil': ('smug', 'angry'), 'sleepy': ('neutral', 'sad'),
        'silly': ('joy', 'happy'), 'cool': ('smug', 'happy'), 'love': ('happy', 'joy'), 'sheepish': ('happy', 'neutral'), 'smug': ('happy', 'joy'),
        'neutral': ('happy', 'sheepish'), 'shock': ('scared', 'laugh'), 'sad': ('cry', 'neutral'), 'angry': ('disgust', 'evil')}


def _base(k):
    return k[:-5] if str(k).endswith(('_talk', '_shut')) else k


def face_emotion(kind, lib):
    k = _base(str(kind))
    if k.startswith('lib:'): return lib.get(k[4:], {}).get('emotion')
    k = k.removeprefix('emo:').split('#')[0]
    return FACE_EMO.get(k, k)


def face_intensity(kind, lib):
    k = _base(str(kind))
    return lib.get(k[4:], {}).get('intensity', .5) if k.startswith('lib:') else BUILTIN_I.get(k, .5)


def face_family(kind, lib):
    """'drawn' for a built-in kind, the library face's meta 'family', None for a family-free key (emo:<x>, a bare emotion, unknown)."""
    k = _base(str(kind))
    if k.startswith('lib:'):
        m = lib.get(k[4:]) or next((m for m in lib.values() if m.get('id') == k[4:]), None)
        return m.get('family', 'classic') if m else None
    return 'drawn' if k in FACE_EMO or k == 'blink' else None


def face_pool(emo, lib, fam=None):
    """[(key, intensity)] every face that can play the emotion: auto library faces + the built-in drawn kinds. With a family: only
    that family's faces (its non-auto library faces when it has no auto one of the emotion)."""
    ls = [('lib:' + s, m.get('intensity', .5), m.get('auto', True)) for s, m in lib.items() if m['emotion'] == emo and fam in (None, m.get('family', 'classic'))]
    pool = [(k, i) for k, i, a in ls if a] or ([(k, i) for k, i, a in ls] if fam else [])
    return sorted(pool + [(k, BUILTIN_I[k]) for k, e in FACE_EMO.items() if e == emo and fam in (None, 'drawn')])


def pick_face(emo, want, lib, avoid=(), soft=(), fam=None):
    """The face of `emo` closest to intensity `want` (>= .85: the most exaggerated one), not in avoid (the character's last
    faces) and, if possible, not in soft (what the others wear now). With a family: only its faces, a NEAR emotion when it has
    none of `emo`. None = no pool for that emotion."""
    pool = face_pool(emo, lib, fam)
    for e2 in (NEAR.get(emo, ()) if fam and not pool else ()):
        pool = face_pool(e2, lib, fam)
        if pool: break
    for ban in (tuple(avoid) + tuple(soft), tuple(avoid), tuple(avoid)[-1:], ()):
        c = [x for x in pool if x[0] not in ban]
        if c: return (max(c, key=lambda x: (x[1], x[0])) if want >= .85 else min(c, key=lambda x: (abs(x[1] - want), -x[1], x[0])))[0]
    return None


def to_family(kind, fam, lib, fmap=None):
    """Any face key -> the same moment in family `fam`: kept when it is already in it, else the family's face of the same emotion
    (NEAR emotion, else any face of the family) closest in intensity; the '_talk' / '_shut' twin suffix is kept."""
    k = str(kind); b = _base(k); suf = k[len(b):]
    if not fam or face_family(b, lib) == fam: return k
    if b == 'blink': b, suf = 'neutral', '_shut'
    emo = face_emotion(b, lib); want = face_intensity(b, lib)
    new = (fmap or {}).get(emo) or pick_face(emo, want, lib, fam=fam) or pick_face('neutral', want, lib, fam=fam)   # fmap: the character's one decal per emotion
    if not new:   # a family without that emotion or a near one: its face closest in intensity
        allf = [x for e in {m['emotion'] for m in lib.values()} | set(FACE_EMO.values()) for x in face_pool(e, lib, fam)]
        new = min(allf, key=lambda x: (abs(x[1] - want), x[0]))[0] if allf else None
    return new + suf if new else k


def decide_families(cast, beats, lib, default='drawn'):
    """{name: family} for one scene: cast 'face_family' > the family of the cast 'face' > the first face beat with a family > default."""
    out = {}
    for c in cast:
        n = c['name']; f = c.get('face_family') if c.get('face_family') in FAMILIES else None
        f = f or (face_family(c['face'], lib) if 'face' in c else None)
        f = f or next((face_family(b['face'], lib) for b in sorted(beats, key=lambda b: b.get('t', 0))
                       if b.get('who') == n and 'face' in b and face_family(b['face'], lib)), None)
        out[n] = f or default
    return out


def story_families(story, lib):
    """{name: family} for a whole story: the first scene that names a family for the character decides it for every scene."""
    looks = {c['name']: c for c in story.get('cast', [])}; out = {}
    for sc in story.get('scenes', []):
        for n, f in decide_families([{**looks.get(c['name'], {}), **c} for c in sc.get('cast', [])], sc.get('beats', []), lib, None).items():
            if out.get(n) is None: out[n] = f
    return {n: out.get(n) or decide_families([c], [], lib)[n] for n, c in looks.items()}


def story_face_map(story, fams, lib):
    """{name: {emotion: 'lib:<slug>'}}: ONE decal per (character, emotion) for the whole story (classic-style families; drawn kinds are
    already one per word). Chosen once, in cast order, at a strong-but-readable intensity, avoiding the decals the earlier characters got."""
    out, taken = {}, set()
    for c in story.get('cast', []):
        n = c['name']; fam = fams.get(n); out[n] = {}
        if fam in (None, 'drawn'): continue
        claimed = {}   # a decal the writer names (cast face / beat face 'lib:x' of the character's family) owns its emotion's slot
        for who, w in [(c['name'], c.get('face')) for c in story['cast']] + [(b.get('who'), b.get('face')) for sc in story.get('scenes', []) for b in sc.get('beats', [])]:
            if who == n and str(w).startswith('lib:') and face_family(w, lib) == fam: claimed.setdefault(face_emotion(w, lib), _base(w))
        for e in sorted({m['emotion'] for m in lib.values() if m.get('family', 'classic') == fam}):
            if e in claimed: out[n][e] = claimed[e]; taken.add(claimed[e]); continue
            k = pick_face(e, .85 if e in ('angry', 'shock', 'scared', 'cry', 'laugh') else .78, lib, soft=taken, fam=fam)   # big emotions: the open-mouthed strong decal
            if k: out[n][e] = k; taken.add(k)
    return out


def load_lib():
    """The face library metas {slug: meta} without bpy (story.py, tests)."""
    import json
    from pathlib import Path
    return {m['slug']: m for m in (json.loads(p.read_text(encoding='utf-8')) for p in sorted((Path(__file__).resolve().parent / 'assets' / 'faces').glob('*/meta.json')))}


def say_emotion(say):
    import re
    s = str(say or '').lower(); words = re.findall(r"[a-z']+", s)
    return next((e for e, ws in SAY_EMO if any((w in s) if ' ' in w else (w in words) for w in ws)), None)


def beat_intensity(b, emo, word=None):
    say = str(b.get('say', '')); body = str(b.get('pose', '')) + ' ' + str(b.get('anim', ''))
    i = BUILTIN_I.get(word, .7 if emo in BIG_EMO else .5)
    i += .25 * any(w.isupper() and len(w) > 1 for w in say.replace('!', ' ').replace('?', ' ').split()) + .1 * ('!' in say) + .1 * ('!!' in say or '?!' in say)
    i += .25 * any(p in body for p in BIG_POSE) - .2 * ('...' in say)
    return max(0.0, min(1.0, i))


def face_pass(spec, beats, log, lib):
    """Every face beat / talk line of a character gets an exact face ('_lib') INSIDE its face family (log['face_family'], else
    decided here); b['_req'] = the emotion the story itself asked for on that beat (build.py logs it at the beat's real frame:
    log['face_req'], LEVEL 1 check 'emotions').
    Auto faces off: only the family mapping (a written face of another family -> the same emotion in the character's family)."""
    if not lib: return beats
    names = [c['name'] for c in spec['cast']]
    fam = log.setdefault('face_family', decide_families(spec['cast'], beats, lib))
    auto = spec.get('auto_faces', True) and spec.get('auto_acting', True)
    hist = {c['name']: [c.get('face', 'smile')] for c in spec['cast']}   # exact faces worn so far, per character
    mood = {c['name']: face_emotion(c.get('face', 'smile'), lib) for c in spec['cast']}
    for b in sorted(beats, key=lambda b: b['t']):
        n = b.get('who')
        if n not in names or ('face' not in b and not b.get('talk')): continue
        w = str(b['face']) if 'face' in b else None
        word = w.removeprefix('emo:').split('#')[0] if w else None
        if w and not b.get('auto') and (face_emotion(w, lib) if w.startswith('lib:') else FACE_EMO.get(word, word)):
            b['_req'] = face_emotion(w, lib) if w.startswith('lib:') else FACE_EMO.get(word, word)
        if not auto:
            if w and to_family(w, fam[n], lib) != w: b['_lib'] = to_family(w, fam[n], lib)
            continue
        if w and w.startswith('lib:') and face_family(w, lib) == fam[n]:   # the writer's exact face (in the character's family)
            hist[n].append(w); mood[n] = face_emotion(w, lib) or mood[n]; continue
        if w and w.startswith('lib:'): word = face_emotion(w, lib)   # another family's face: its emotion, drawn in this family
        emo = FACE_EMO.get(word, word) if w else (say_emotion(b.get('say')) or ('confused' if '?' in str(b.get('say', '')) and mood[n] in ('happy', 'neutral') else mood[n]))
        if word == 'scream' and mood[n] in ('angry', 'disgust', 'evil'): emo = 'angry'; b['_req'] = 'angry'   # an angry character shouts WITH his brows (the check expects what is really drawn)
        want = beat_intensity(b, emo, word) if not (w and w.startswith('lib:')) else max(beat_intensity(b, emo, word), face_intensity(w, lib))
        fm = next((c.get('face_map') or {} for c in spec['cast'] if c['name'] == n), {}).get(emo)
        k = fm or pick_face(emo, want, lib, avoid=hist[n][-2:], soft=[f for x in names if x != n for f in hist[x][1:] + hist[x][-1:]], fam=fam[n])   # soft: what the others wear now or wore in this scene (each character owns its extremes)
        if k is None: continue   # unknown word: the build's own fallback handles it (and maps it into the family)
        b['_lib'] = k; hist[n].append(k); mood[n] = emo
        log.setdefault('notes', []).append(f"face: t{b['t']} {n} {w or 'line ' + repr(str(b.get('say', ''))[:24])} -> {emo} {want:.2f} = {k}")
    return beats


def face_runs(seq):
    """seq [(frame, kind)] of one character's expression changes -> (distinct faces, longest run of identical consecutive faces)."""
    ks = [_base(k) for _, k in seq]; run = best = 0
    for i, k in enumerate(ks):
        run = run + 1 if i and k == ks[i - 1] else 1; best = max(best, run)
    return len(set(ks)), best


def face_hold(sched, spans):
    """Longest stretch (frames) one unchanged face stays ON SCREEN: sched {frame: kind} final keys, spans [(f0, f1)] shots that show it."""
    worst = 0
    for f0, f1 in spans:
        ch = [f0] + sorted(f for f in sched if f0 < f <= f1) + [f1 + 1]
        worst = max(worst, max(b - a for a, b in zip(ch, ch[1:])))
    return worst


def face_accents(sched, spans, closes, lib, max_hold=34, fam=None):
    """Extra face keys {frame: kind} so an on-screen face is never static for > max_hold frames (~1.4 s at 24 fps):
      CHANGED FACE ON A CLOSE-UP  a close cut-in (closes [(f0, f1)]) that lands on the face the character already wore 0.5 s
                                  before gets a sibling of the same emotion (a notch stronger) from the cut on;
      CUT ACCENT                  a quick blink / mouth pop 4 frames after every cut onto the character;
      HOLD BREAKER                the same accent every <= max_hold frames while nothing else changes.
    Every face blinks with its '_shut' twin (library: faces.py squashes the eye band), closed-eye drawn kinds pop the mouth (ACCENT).
    fam: the character's face family (the close-up sibling stays in it)."""
    s = dict(sched); at = lambda f: s[max((k for k in s if k <= f), default=min(s))]
    def expr(f):   # the expression at f, seen through blinks and mouth flaps
        k = max((k for k in s if k <= f and s[k] != 'blink'), default=min(s)); return _base(s[k])
    out = {}
    for f0, f1 in closes:
        cur = expr(f0)
        if f0 < 12 or f1 - f0 < 8 or expr(f0 - 12) != cur or expr(f0 + 8) != cur or not cur in FACE_EMO: continue   # a library decal never swaps to a sibling decal (one decal per emotion); the blink accents break the hold
        emo = face_emotion(cur, lib); new = pick_face(emo, min(.84, max(face_intensity(cur, lib), .5) + .15), lib, avoid=[cur], fam=fam) if emo else None
        if not new or new == cur or face_intensity(new, lib) < face_intensity(cur, lib) - .15: continue   # never a weaker face on the close-up (scream -> o)
        end = min([k for k in s if k > f0 and s[k] != 'blink' and _base(s[k]) != cur] + [10 ** 9])
        for k in sorted({f0} | {k for k in s if f0 <= k < end}):
            v = at(k)
            if v != 'blink': s[k] = out[k] = new + v[len(cur):]   # every face has its '_talk' / '_shut' twins
    def accent(f):
        cur = at(f)
        if cur == 'blink' or cur.endswith(('_talk', '_shut')) or not (cur.startswith('lib:') or cur in FACE_EMO): return False
        for k, v in ((f, ACCENT.get(cur, cur + '_shut')), (f + 3, cur)): s[k] = out[k] = v
        return True
    for f0, f1 in spans:
        if f1 - f0 >= 14 and not any(f0 - 2 <= k <= f0 + 10 for k in s if k > 0): accent(f0 + 4)
        while True:
            ch = [f0] + sorted(k for k in s if f0 < k <= f1) + [f1 + 1]
            gap = next(((a, b) for a, b in zip(ch, ch[1:]) if b - a > max_hold), None)
            if gap is None or gap[0] + max_hold - 1 > f1 or not accent(gap[0] + max_hold - 4): break
    return out


if __name__ == '__main__':
    spec = {'seconds': 10, 'cast': [{'name': 'A', 'face': 'smile'}, {'name': 'B', 'face': 'smug'}, {'name': 'C'}], 'props': [{'name': 'x', 'held_by': 'C'}]}
    beats = [{'t': 1.0, 'who': 'A', 'talk': 1.2, 'face': 'angry', 'say': 'Give it back!'}, {'t': 4.2, 'who': 'B', 'face': 'emo:shock'},
             {'t': 5.0, 'who': 'A', 'talk': 1.0, 'say': 'Why?'}, {'t': 5.2, 'who': 'B', 'walk': [[0, 0]]}, {'t': 8.6, 'who': 'B', 'face': 'emo:shock'}]
    log = {}; out = inject(spec, [dict(b) for b in beats], log)
    get = lambda **kw: [b for b in out if all(b.get(k) == v for k, v in kw.items())]
    assert get(who='B', pose='cower', t=1.5) and get(who='B', face='smug', t=3.1), 'shouted at -> cower, face restored'
    assert get(who='B', t=4.2)[0].get('pose') == 'shock' and get(who='B', t=8.6)[0].get('pose') == 'recoil', 'strong face -> silhouette, never the same twice'
    assert [b for b in out if b['who'] == 'A' and b.get('pose') in STANCES and 2.4 < b['t'] < 2.7], 'arms come down after a line'
    assert all('R' in b['_skip'] for b in out if b['who'] == 'C' and b.get('auto') and 'pose' in b) and [b for b in out if b['who'] == 'C' and b.get('auto')], 'the arm that carries a prop is never touched'
    assert not [b for b in out if b['who'] == 'B' and b.get('auto') and 4.9 < b['t'] < 8.2], 'explicit beats win (B walks at 5.2)'
    assert [b for b in out if b['who'] == 'A' and '_skip' in b], 'idle life in a long gap'
    assert inject({**spec, 'auto_acting': False}, beats, {}) is beats
    # EXPRESSION RANGE
    L = {s_: {'emotion': e, 'intensity': i} for s_, e, i in (('roar', 'angry', 1.0), ('grr', 'angry', .6), ('rawr', 'angry', .85), ('d', 'shock', .95),
                                                            ('o', 'shock', .25), ('surprise', 'shock', .9), ('glee', 'joy', .66), ('hello', 'happy', .6))}
    bs = [{'t': t, 'who': 'A', 'face': 'angry', 'talk': .5, 'say': s_} for t, s_ in ((0, 'hm...'), (1, 'Stop.'), (2, 'STOP IT!!'), (3, 'no'), (4, 'no'))]
    bs += [{'t': 5, 'who': 'A', 'face': 'lib:grr'}, {'t': 6, 'who': 'B', 'talk': 1, 'say': 'WHAT?!'}, {'t': 7, 'who': 'B', 'face': 'shock', 'pose': 'shock'}, {'t': 8, 'who': 'B', 'face': 'zzz'}]
    cl = {**spec, 'cast': [{**c, 'face_family': 'classic'} for c in spec['cast']]}   # library-family characters (L has no 'family': classic)
    face_pass(cl, bs, {}, L); ks = [b.get('_lib') for b in bs]
    assert ks[2] == 'lib:roar' and ks[5] is None and ks[8] is None, ks                      # the shout takes the extreme; the writer's lib: face and unknown words are untouched
    assert all(len({*ks[i:i + 3]}) == 3 for i in range(3)) and face_runs(list(enumerate(ks[:5])))[1] == 1, ks   # never one of the last two
    assert face_emotion(ks[6], L) == 'shock' and ks[7] != ks[6] and face_intensity(ks[7], L) >= .9, ks   # line meaning -> shock; the pose makes it big
    assert '_lib' not in face_pass({**spec, 'auto_faces': False}, [{'t': 0, 'who': 'A', 'face': 'angry'}], {}, L)[0]
    # FACE FAMILIES: a drawn character (cast face 'smile') never gets a library face; one family per character
    lg = {}; bd = [{k_: v_ for k_, v_ in b.items() if k_ != '_lib'} for b in bs if b['who'] == 'A'] + [{'t': 9, 'who': 'A', 'face': 'emo:shock'}]
    face_pass(spec, bd, lg, L)
    assert lg['face_family'] == {'A': 'drawn', 'B': 'drawn', 'C': 'drawn'} and all(face_family(b['_lib'], L) == 'drawn' for b in bd if '_lib' in b), bd
    assert [b['_lib'] for b in bd if b['face'] == 'lib:grr'] == ['angry'] and bd[-1]['_lib'] in ('o', 'scream'), bd   # another family's face -> its emotion
    assert 'angry' in [b.get('_req') for b in bd] and bd[-1]['_req'] == 'shock'
    assert to_family('lib:roar_talk', 'drawn', L) == 'angry_talk' and to_family('scream_shut', 'classic', L) in ('lib:d_shut', 'lib:surprise_shut')
    assert to_family('blink', 'classic', L) == 'lib:hello_shut' and to_family('smile', 'drawn', L) == 'smile' and to_family('emo:joy', 'drawn', L) in ('grin', 'joy')
    assert decide_families([{'name': 'A'}, {'name': 'B', 'face': 'lib:d'}, {'name': 'C', 'face_family': 'bigeye', 'face': 'smile'}],
                           [{'t': 2, 'who': 'A', 'face': 'emo:shock'}, {'t': 3, 'who': 'A', 'face': 'lib:grr'}], L) == {'A': 'classic', 'B': 'classic', 'C': 'bigeye'}
    st = {'cast': [{'name': 'A'}, {'name': 'B'}], 'scenes': [{'cast': [{'name': 'A'}], 'beats': []}, {'cast': [{'name': 'A', 'face': 'lib:d'}, {'name': 'B'}], 'beats': []}]}
    assert story_families(st, L) == {'A': 'classic', 'B': 'drawn'}   # scene 2 names A's family: scene 1 wears it too
    assert pick_face('cry', .9, L, fam='classic') is None and to_family('cry', 'classic', L).startswith('lib:') and pick_face('cry', .9, L, fam='drawn') == 'cry'
    acc = face_accents({0: 'lib:d', 50: 'smile'}, [(10, 120)], [], L)
    assert acc[14] == 'lib:d_shut' and acc[17] == 'lib:d' and 'smile_shut' in acc.values() and face_hold({0: 'lib:d', 50: 'smile', **acc}, [(10, 120)]) <= 34, acc
    acc = face_accents({0: 'lib:d', 44: 'lib:d_talk', 48: 'lib:d'}, [(40, 70)], [(40, 70)], L)
    assert acc[40] == 'lib:surprise' and acc[44] == 'lib:surprise_talk', acc                # a close-up lands on a changed face, flaps follow
    assert face_hold({0: 'smile'}, [(0, 99)]) == 100
    print('acting self-check OK:', len(out) - len(beats), 'auto beats'); print('\n'.join(log['notes']))
