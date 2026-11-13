"""Sound + edit pack: auto SFX, blip voice, music bed, captions, -14 LUFS master.
Usage: python tools/sound_mix.py stories/<name>/story.json [--video in.mp4] [--out out.mp4|out.wav]
         [--mood cheery|tense|chill|battle] [--no-voice] [--no-music] [--seed N]
Default video = the first of <story dir>/hq.mp4, mid.mp4, preview.mp4, draft.mp4 that exists, default out = <video>_sound.mp4. A .wav --out writes the audio master only.
Times come from the scene reports (retimes replayed from report notes); no Blender needed. No TTS / ElevenLabs:
the voice is synthesized gibberish blips. Assets: assets/sfx (Kenney CC0 + synth), assets/music (original loops)."""
import argparse, glob, hashlib, json, math, os, random, re, subprocess, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import overlays

SR = 44100
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cache = {}


def db(x): return 10 ** (x / 20)


# ---------------------------------------------------------------- timeline
def scene_timeline(sc, rep, fps):
    """Resolve one scene: retimed beats/shots (seconds, scene-local) + walk spans. Returns dict."""
    beats = [dict(b) for b in sc.get('beats', [])]; beats.sort(key=lambda b: b['t'])
    shots = [dict(s) for s in sc.get('shots', [])]
    for n in rep.get('notes', []):   # replay build.py retime_after / settle waits, in order
        m = re.match(r't([\d.]+) (\S+) .*retimed \+([\d.]+)s', n)
        if m:
            t0, who, dl = float(m[1]), m[2], float(m[3])
            i0 = next((i for i, b in enumerate(beats) if b.get('who') == who and abs(b['t'] - t0) < 0.011 and '_own' not in b), None)
            if i0 is None: continue
            beats[i0]['_own'] = dl
            for b in beats[i0 + 1:]:
                if b['t'] >= t0: b['t'] = round(b['t'] + dl, 3)
            for s in shots:
                if s['t'] > t0 + 1e-6: s['t'] = round(s['t'] + dl, 3)
                elif s['t'] > t0 - 1e-6: s['t'] = round(s['t'] + max(0.0, dl - 0.6), 3)
            continue
        m = re.match(r't([\d.]+) (\S+) waits ([\d.]+)s', n)
        if m:
            b = next((b for b in beats if b.get('who') == m[2] and abs(b['t'] - float(m[1])) < 0.011 and '_wait' not in b), None)
            if b: b['_wait'] = float(m[3])
    return {'beats': beats, 'shots': shots}


def walk_spans(beats, rep, pos, fps):
    """[(who, t0, t1, run)] for every walk/sit-route: report walks win, else dist/speed. Also sets b['_eff']."""
    rw = {}
    for w in rep.get('walks', []): rw.setdefault(w['who'], []).append((w['f0'] / fps, w['f1'] / fps))
    spans = []
    for k, b in enumerate(beats):
        b['_eff'] = b['t'] + (b.get('_own', 0) if ('give' in b or 'turn' in b or 'grab' in b) else 0) + b.get('_wait', 0)
        if 'walk' in b or b.get('run') or 'sit' in b:
            w = b.get('who', ''); run = bool(b.get('run')) or b.get('speed', 9.5) >= 10
            if rw.get(w) and ('walk' in b or 'sit' in b):
                t0, t1 = rw[w].pop(0)
            else:
                if 'walk' not in b: continue
                tgt = b['walk'] if isinstance(b['walk'], list) else [b['walk']]
                p, d = pos.get(w, (0, 0)), 0.0
                for e in tgt:
                    q = tuple(e) if isinstance(e, (list, tuple)) else pos.get(e)
                    if q: d += max(0.0, math.dist(p, q) - (3 if not isinstance(e, (list, tuple)) else 0)); p = q
                    else: d += 6.0
                pos[w] = p; t0 = b['_eff']; t1 = t0 + d / b.get('speed', 9.5)
                nxt = next((x['_eff'] if '_eff' in x else x['t'] for x in beats[k + 1:] if x.get('who') == w and ('give' in x or 'sit' in x or 'fall' in x)), None)
                if nxt is not None and nxt > t0 + 0.4: t1 = min(t1, nxt)
            spans.append((w, t0, t1, run)); b['_walk_end'] = t1
    return spans


SCENE_OFFS = []   # absolute start second of every scene (cards / split / freeze need it)
FREEZES = []   # (abs t, dur, label) from beat key 'freeze'
MUSIC_SEGS = []   # (start s, end s, mood) per scene with its own 'music' (filled by extract_events, used by mix)


def extract_events(story, sdir, seed=1):
    """-> (events[{t,kind,who,vol}], talks[{t,dur,who,text}], total_seconds, mood). Absolute story seconds."""
    rng = random.Random(seed); fps = story.get('fps', 24); ev, talks, off = [], [], 0.0
    MUSIC_SEGS.clear(); SCENE_OFFS.clear(); FREEZES.clear()
    face = {c['name']: c.get('face', 'smile') for c in story.get('cast', [])}
    last_pop = last_whoosh = -9.0; last_step = -9.0; fights = 0; busy = set()
    def add(t, kind, who='', vol=1.0, dur=None): ev.append({'t': round(t, 3), 'kind': kind, 'who': who, 'vol': vol, **({'dur': dur} if dur else {})})
    for si, sc in enumerate(story['scenes']):
        rp = os.path.join(sdir, 'scenes', f's{si + 1:02d}', 'report.json')
        rep = json.load(open(rp)) if os.path.exists(rp) else {}
        tl = scene_timeline(sc, rep, fps); beats, shots = tl['beats'], tl['shots']
        frames = rep.get('frames') or round(max(sc.get('seconds', 5), max([b['t'] for b in beats] + [0]) + 1) * fps)
        SCENE_OFFS.append(off)
        pos = {c['name']: tuple(c['at']) for c in sc.get('cast', []) if 'at' in c}
        for c in sc.get('cast', []): face.setdefault(c['name'], c.get('face', 'smile')); face[c['name']] = c.get('face', face[c['name']])
        floor = {'park': 'grass', 'street': 'grass', 'wasteland': 'concrete'}.get(sc.get('set', {}).get('preset', ''), 'wood')
        # scene cut transition
        if si: add(off - 0.1, 'whoosh', '', 0.55)
        spans = walk_spans(beats, rep, pos, fps)
        for w, t0, t1, run in spans:   # footsteps
            iv = 0.33 if run else 0.47; t = t0 + 0.1; n = 0
            while t < t1 - 0.05:
                if off + t - last_step >= 0.12:
                    edge = min(1.0, (t - t0) / 0.4 + 0.4, (t1 - t) / 0.3 + 0.4)
                    add(off + t, 'step_' + floor, w, (0.62 if run else 0.5) * edge * db(rng.uniform(-2.5, 1.5))); last_step = off + t
                t += iv * rng.uniform(0.9, 1.1); n += 1
            if run and t1 - t0 > 0.5: add(off + t0, 'whoosh', w, 0.35)
        sits = {s[0]: s for s in rep.get('sit_spans', [])}
        wend = lambda b: b.get('_walk_end', b['_eff'])
        prev_end = {}
        for k, b in enumerate(beats):
            w, t = b.get('who', ''), b['_eff']
            for sp in spans:   # an actor's next action waits for its walk to finish (engine behaviour)
                if sp[0] == w and sp[1] - 0.2 <= b['t'] < sp[2] and 'walk' not in b and 'sit' not in b: t = max(t, sp[2])
            if 'sit' in b:
                s = sits.get(w); ts = s[1] / fps if s and s[1] / fps < frames / fps else wend(b) + 0.3
                add(off + ts, 'creak', w, 0.8)
                if s and s[2] / fps < frames / fps - 0.1: add(off + s[2] / fps, 'creak', w, 0.5)
            if b.get('stand'): add(off + t, 'creak', w, 0.6); add(off + t, 'cloth', w, 0.35)
            if b.get('fall'): add(off + t, 'whoosh', w, 0.4); add(off + t + 0.45, 'thud', w, 0.9)
            if b.get('get_up'): add(off + t, 'cloth', w, 0.5)
            if b.get('jump'): add(off + t - 0.05, 'boing', w, 0.55); add(off + t + 0.42, 'land', w, 0.45)
            if 'knockback' in b: add(off + t, 'whoosh', w, 0.6); add(off + t + 0.7, 'thud', w, 0.9); add(off + t + 0.7, 'crash', w, 1.0)   # crash on top of the thud
            if 'attack' in b:
                blk = isinstance(b['attack'], dict) and b['attack'].get('blocked')   # blocked = a deflect, not a punch
                add(off + t - 0.2, 'whoosh', w, 0.5); add(off + t, 'punch', w, 0.85 if blk else 1.0); fights += 1   # a stopped punch still SOUNDS like a punch (creator 2026-11-10), a touch quieter
                fl_ = isinstance(b['attack'], dict) and b['attack'].get('flurry')   # a flurry = one punch per strike, faster and faster (same gaps as fight.story_beat)
                if fl_ and len(fl_) > 1:
                    n_ = len(fl_); tot_ = float(b['attack'].get('s') or .3 * (n_ - 1)); w_ = [1.4 - i_ / max(1, n_ - 2) * .8 for i_ in range(n_ - 1)] if n_ > 2 else [1.0]; tt_ = t
                    for x_ in w_: tt_ += max(4 / fps, tot_ * x_ / sum(w_)); add(off + tt_, 'punch', w, 0.85)
                if blk: add(off + t, 'block', w, 0.6)
            if b.get('block'): add(off + t, 'block', w, 0.7)
            if 'dodge' in b: add(off + t - 0.1, 'whoosh', w, 0.5)
            if 'fly' in b: add(off + t, 'dash', w, 0.7)
            if b.get('land') is True: add(off + t, 'thud', w, 0.8)
            elif isinstance(b.get('land'), dict) and b['land'].get('crater'): add(off + t, 'thud', w, 0.9); add(off + t, 'crash', w, 1.0)   # body into a crater
            if 'power_up' in b or 'aura' in b: add(off + t, 'aura', w, 0.8)
            if 'beam' in b:   # charge rises over the charge time and ends at fire; the beam sound lasts the beam seconds
                ch = float(b['beam'].get('charge', 0.6)); add(off + t - ch, 'charge', w, 0.8, ch); add(off + t, 'beam', w, 1.0, float(b['beam'].get('s', 1.5)))
            if b.get('sfx'): add(off + t, b['sfx'], w, 1.0)   # beat key 'sfx': any kind (e.g. 'screech') at the beat time
            if b.get('exclaim'): add(off + t, 'alert', w, 0.6)
            if b.get('type'):   # beat key 'type': seconds of keyboard typing (uneven key clicks, short pauses between words)
                tt = t
                while tt < t + float(b['type']): add(off + tt, 'click', w, rng.uniform(0.22, 0.4)); tt += rng.uniform(0.07, 0.16) + (0.22 if rng.random() < 0.15 else 0)
            if 'grab' in b:
                add(off + t, 'pick', w, 0.7)
                if isinstance(b['grab'], dict) and b['grab'].get('until'): add(off + b['grab']['until'], 'place', w, 0.6)
            if 'give' in b: add(off + t, 'pick', w, 0.7); add(off + t + 0.35, 'place', b['give'].get('to', w), 0.45)
            if isinstance(b.get('turn'), (int, float)) and abs(b['turn']) >= 120 or (isinstance(b.get('turn'), str) and rng.random() < 0.3):
                add(off + t - 0.1, 'whoosh', w, 0.3)
            nf = b.get('face')
            if nf and nf.replace('_talk', '') != face.get(w, '').replace('_talk', ''):
                if off + t - last_pop > 1.2 and rng.random() < 0.7 and t > 0.4: add(off + t - 0.08, 'pop', w, 0.4); last_pop = off + t
                face[w] = nf
            if b.get('narrate'):   # narrator line: no mouth, own voice file (or silent until voices.py makes one)
                vp = os.path.join(sdir, b['narrate_voice']) if b.get('narrate_voice') else None
                nd = len(load(vp)) / SR if vp and os.path.exists(vp) else max(1.2, 0.38 * len(str(b['narrate']).split()))
                talks.append({'t': off + t, 'dur': float(nd), 'who': 'Narrator', 'text': b['narrate'], 'narr': True, **({'voice': vp} if vp and os.path.exists(vp) else {})})
            if b.get('freeze'):   # freeze-frame + label + hit SFX
                fz = b['freeze'] if isinstance(b['freeze'], dict) else {}
                FREEZES.append((off + t, float(fz.get('dur', 1.0)), fz.get('label', ''))); add(off + t, 'punch', w, 0.9)
            if b.get('talk') or b.get('say'):
                dur = b.get('talk') or max(1.2, 0.38 * len(str(b['say']).split()))
                talks.append({'t': off + t, 'dur': float(dur), 'who': w, 'text': b.get('say', ''), **({'voice': os.path.join(sdir, b['voice'])} if b.get('voice') else {})})   # beat key 'voice' = a recorded line (path from the story folder) instead of blips
        for s in shots[1:]:   # some cuts get a subtle swoosh
            t = s['t']
            if rng.random() < 0.4 and off + t - last_whoosh > 2.0 and not any(abs(e['t'] - (off + t)) < 0.4 and e['kind'] == 'whoosh' for e in ev):
                add(off + t - 0.12, 'whoosh', '', 0.3); last_whoosh = off + t
        if sc.get('music'): MUSIC_SEGS.append((off, off + frames / fps, sc['music']))   # scene key 'music': another loop for this scene (e.g. the fight track stops at a reveal)
        off += frames / fps
    mood = story.get('mood') or ('tense' if fights >= 2 else 'cheery')
    ev.sort(key=lambda e: e['t']); talks.sort(key=lambda x: x['t'])
    return ev, talks, off, mood


# ---------------------------------------------------------------- audio
def load(path):
    if path not in _cache:
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '1', '-ar', str(SR), '-'], capture_output=True, check=True).stdout
        _cache[path] = np.frombuffer(raw, '<f4').copy()
    return _cache[path]


def pick(kind, rng):
    base = {'whoosh': 'synth/whoosh', 'boing': 'synth/boing', 'pop': 'synth/pop'}.get(kind, kind)
    d, _, stem = base.partition('/')
    fs = sorted(glob.glob(os.path.join(ROOT, 'assets', 'sfx', d, (stem or '*') + '*.ogg')))
    mine = sorted(f for e_ in ('ogg', 'mp3', 'wav') for f in glob.glob(os.path.join(ROOT, 'assets', 'sfx', d, 'mine', '*.' + e_)))   # the creator's own picks (chosen by ear) replace the library for that kind
    if mine and not stem: fs = mine
    return fs[rng.randrange(len(fs))]


def blips(dur, who, rng_seed):
    """Animal-Crossing-style gibberish: 3-5 syllables/s, pitch per character, short rising/falling glides."""
    r = random.Random(rng_seed); h = int(hashlib.md5(who.encode()).hexdigest()[:6], 16)
    f0 = 190 + (h % 1000) / 1000 * 230; scale = (0, 2, 4, 7, 9, 12); n = int(SR * dur); out = np.zeros(n + SR // 4); t = 0.0
    rate = r.uniform(3.0, 5.0); formant = 0.25 + (h >> 8) % 100 / 200
    while t < dur - 0.06:
        sd = min(r.uniform(0.07, 0.13), dur - t); f = f0 * 2 ** (r.choice(scale) / 12 + r.uniform(-0.03, 0.03))
        k = np.arange(int(SR * sd)) / SR; fm = f * (1 + r.uniform(-0.08, 0.1) * k / sd)
        ph = 2 * np.pi * np.cumsum(fm) / SR
        y = np.sin(ph) + formant * np.sin(2 * ph) + 0.12 * np.sin(3 * ph)
        y *= np.minimum(1, k / 0.006) * np.minimum(1, (sd - k) / 0.02) * np.exp(-3 * k / sd)
        i = int(t * SR); out[i:i + y.size] += y * 0.4
        t += (1 / rate) * r.uniform(0.85, 1.2) + (0.14 if r.random() < 0.12 else 0)
    return out[:n]


def smooth(x, win):
    c = np.cumsum(np.concatenate([np.zeros(win), x])); y = (c[win:] - c[:-win]) / win
    return np.concatenate([y[win // 2:], np.full(win // 2, y[-1])])[:x.size]


def mix(story_events, talks, total, mood, voice=True, music=True, seed=1, duck_db=-6):
    rng = random.Random(seed); N = int((total + 0.8) * SR); L = np.zeros(N); R = np.zeros(N)
    def put(x, t, g, pan=0.0):
        i = int(max(0, t) * SR); x = x[:max(0, N - i)]
        if not x.size: return
        L[i:i + x.size] += x * g * (1 - max(0, pan)); R[i:i + x.size] += x * g * (1 + min(0, pan))
    talkmask = np.zeros(N)
    for tk in talks: talkmask[int(tk['t'] * SR):int((tk['t'] + tk['dur']) * SR)] = 1
    for e in story_events:
        x = load(pick(e['kind'], rng)).copy(); i = int(e['t'] * SR); under = i < N and talkmask[min(i, N - 1)] > 0
        g = {'crash': 1.0, 'punch': 1.0, 'beam': 1.0, 'charge': .7, 'aura': .55, 'dash': .6, 'deflect': .7, 'screech': .8, 'step_wood': .55, 'step_grass': .55, 'step_concrete': .55, 'whoosh': .5, 'pop': .6, 'boing': .5, 'zap': .4, 'power': .4}.get(e['kind'], .8) * e['vol']
        if e['kind'].startswith('step') and under: g *= db(-4.5)
        elif under: g *= db(-2)
        x *= (db(rng.uniform(-1.5, 1.5)))
        if e['kind'] in ('charge', 'beam') and e.get('dur'):   # fit the sound to the scene seconds
            n = int((e['dur'] + (0.25 if e['kind'] == 'beam' else 0)) * SR)
            if x.size < n: x = np.concatenate([x, np.tile(x[-int(.4 * SR):], (n - x.size) // int(.4 * SR) + 1)])[:n] if e['kind'] == 'beam' else np.concatenate([np.zeros(n - x.size), x])
            elif e['kind'] == 'charge': x = x[-n:].copy()   # keep the end (the peak)
            else: x = x[:n].copy()
            f = int((0.3 if e['kind'] == 'beam' else 0.05) * SR); x[-f:] *= np.linspace(1, 0, f) if e['kind'] == 'beam' else 1; x[:int(.04 * SR)] *= np.linspace(0, 1, int(.04 * SR))
        if e['kind'].startswith(('step', 'pop', 'boing')):   # random pitch variation by resampling
            sp = rng.uniform(0.92, 1.1); x = np.interp(np.arange(0, x.size, sp), np.arange(x.size), x)
        put(x, e['t'], g, rng.uniform(-0.3, 0.3))
    if voice:
        for tk in talks:
            if tk.get('voice'): put(load(tk['voice']), tk['t'], 1.0); continue
            if tk.get('narr'): continue   # narrator without a file stays silent
            put(blips(tk['dur'], tk['who'], int(hashlib.md5(f"{tk['who']}{tk['t']:.2f}".encode()).hexdigest()[:4], 16)), tk['t'], 0.7)
    if music:
        m = next(load(q) for q in (os.path.join(ROOT, 'assets', 'music', mood + e_) for e_ in ('.mp3', '.ogg')) if os.path.exists(q) and (mood == 'battle' or q.endswith('.ogg'))); bed = np.tile(m, N // m.size + 1)[:N]   # battle: the creator's own battle.mp3 wins over battle.ogg
        if mood == 'battle':   # any battle track (his mp3 or the ogg) is levelled to a steady bed, else loud passages bury the voices
            env_ = np.sqrt(smooth(bed ** 2, SR)) + 1e-4; bed = bed * smooth(np.clip(db(-14) / env_, 0.1, 3.0), SR)
        for a_, b_, m2 in MUSIC_SEGS:   # hard cut to the scene's own loop (level matched to a normal bed), 80 ms fades
            q2 = os.path.join(ROOT, 'assets', 'music', m2 + '.ogg'); i0, i1 = int(a_ * SR), min(N, int(b_ * SR))
            if not os.path.exists(q2) or i1 <= i0: continue
            x2 = np.tile(load(q2), (i1 - i0) // load(q2).size + 1)[:i1 - i0] * (0.18 / 0.26 if mood == 'battle' else 1.0)
            f_ = min(int(0.08 * SR), (i1 - i0) // 2); x2[:f_] *= np.linspace(0, 1, f_); x2[-f_:] *= np.linspace(1, 0, f_); bed[max(0, i0 - f_):i0] *= np.linspace(1, 0, min(f_, i0)); bed[i0:i1] = x2
        duck = 1 - (1 - db(duck_db)) * np.clip(smooth(talkmask, int(0.3 * SR)) * 1.5, 0, 1)   # -6 dB under talk
        env = np.minimum(1, np.arange(N) / (0.8 * SR)) * np.minimum(1, (N - np.arange(N)) / (1.2 * SR))
        bed = bed * duck * env * (0.26 if mood == 'battle' else 0.18); L += bed; R += bed   # a BED under sfx/voice: 0.5 was the loudest layer and buried them (critic R151)
    return np.stack([L, R], 1).astype('<f4')


def loudness(path):
    p = subprocess.run(['ffmpeg', '-nostats', '-i', path, '-af', 'ebur128=peak=true', '-f', 'null', '-'], capture_output=True, text=True).stderr
    s = p[p.rfind('Summary:'):]
    return float(re.search(r'I:\s+(-?[\d.]+) LUFS', s)[1]), float(re.search(r'Peak:\s+(-?[\d.]+) dBFS', s)[1])


PRE = 'acompressor=threshold=0.1:ratio=3:attack=5:release=80,alimiter=limit=0.7:level=false'   # tame transients so loudnorm can reach -14


def master_wav(stereo, out_wav):
    """loudnorm two-pass: -14 LUFS integrated, TP <= -1 dBTP."""
    tmp = out_wav + '.raw.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(SR), '-ac', '2', '-i', 'pipe:0', tmp], input=stereo.tobytes(), check=True)
    tgt = 'I=-14:TP=-2:LRA=11'   # TP -2 + limiter 0.8 leaves AAC headroom (homework -14.8 LUFS / -1.2 dBFS); TP -1 overshot and needed trims
    j = subprocess.run(['ffmpeg', '-nostats', '-i', tmp, '-af', f'{PRE},loudnorm={tgt}:print_format=json', '-f', 'null', '-'], capture_output=True, text=True).stderr
    m = json.loads(j[j.rfind('{'):j.rfind('}') + 1])
    f = f"loudnorm={tgt}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true"
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', tmp, '-af', f'{PRE},{f},alimiter=limit=0.8:level=false', '-ar', '48000', out_wav], check=True)
    os.remove(tmp)


# ---------------------------------------------------------------- captions
def chunks(text, n=3, max_chars=14):
    """Cards of <= n words AND <= max_chars characters (Arial Black 118 px fills the 1080 px frame at ~16 chars: R252
    'GET: KITCHEN. STRATEGY' ran off both edges). A single longer word gets its own card."""
    out, cur = [], []
    for w_ in text.split():
        if cur and (len(cur) >= n or len(' '.join(cur + [w_])) > max_chars): out.append(' '.join(cur)); cur = []
        cur.append(w_)
    return out + [' '.join(cur)] if cur else out


def ass(talks, path, story=None):
    """Big Roblox-style cards, 2-4 words each, lower-third safe zone (1080x1920)."""
    ts = lambda t: f'{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}'
    h = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n\n[V4+ Styles]\n"
         "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
         "Style: Default,Arial Black,118,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,9,3,2,70,70,430,1\n\n"
         "[Events]\nFormat: Layer,Start,End,Style,Name,Text,Effect\n".replace('Text,Effect', 'Text').replace('Layer,Start,End,Style,Name,Text', 'Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text'))
    story = story or {}; h = h.replace('\n\n[Events]', '\n' + overlays.style_lines() + '\n[Events]')
    cards = []
    for tk in talks:
        if not tk['text']: continue
        st = 'Narr' if tk.get('narr') else 'Default'
        if story.get('captions') == 'word':   # word-by-word, *key* word coloured
            cards += [c + [st if tk.get('narr') else 'Word'] for c in overlays.word_cards(tk['text'], tk['t'], tk['dur'])]; continue
        cs = chunks(tk['text'].replace('*', '')); tw = sum(len(c) for c in cs)
        t = tk['t']
        for c in cs:
            d = tk['dur'] * len(c) / tw
            cards.append([t, t + d, c.upper(), st]); t += d
    cards.sort(key=lambda c: c[0]); lines = []
    for i, (t0, t1, c, st) in enumerate(cards):   # ONE card at a time: overlapping lines stacked two cards ("CHEY!!GETE!", R212b)
        if i + 1 < len(cards): t1 = min(t1, cards[i + 1][0])
        if t1 - t0 < (0.08 if st == 'Word' else 0.2): continue   # a cut-off card flashing for a few frames reads as a glitch
        lines.append(f"Dialogue: 0,{ts(t0)},{ts(t1)},{st},,0,0,0,,{{\\fad(40,0)\\fscx88\\fscy88\\t(0,90,\\fscx100\\fscy100)}}{c}")
    if story.get('header') or story.get('cards') or FREEZES: lines += overlays.extra_events(story, SCENE_OFFS, FREEZES)
    open(path, 'w', encoding='utf-8').write(h + '\n'.join(lines) + '\n')
    return len(lines)


# ---------------------------------------------------------------- main
TAG = ['-metadata', 'comment=Made with NoCodeHack Roblox Engine']   # provenance tag on every finished mp4 (NOTICE)
VIDEOS = ('hq.mp4', 'mid.mp4', 'preview.mp4', 'draft.mp4')   # default video: the best tier rendered


def probe_fps(video):
    n, _, d = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=r_frame_rate', '-of', 'csv=p=0', video], capture_output=True, text=True).stdout.strip().partition('/')
    return float(n) / float(d or 1)


def probe_size(video):
    return [int(v) for v in subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', video], capture_output=True, text=True).stdout.strip().split(',')]


def run(story_path, video=None, out=None, mood=None, voice=True, music=True, seed=1, verbose=True):
    story = json.load(open(story_path, encoding='utf-8')); sdir = os.path.dirname(os.path.abspath(story_path))
    video = video or next((p for p in (os.path.join(sdir, n) for n in VIDEOS) if os.path.exists(p)), os.path.join(sdir, 'hq.mp4'))
    out = out or os.path.splitext(video)[0] + '_sound.mp4'
    ev, talks, total, m = extract_events(story, sdir, seed); m = mood or m
    if os.path.exists(video) and not out.endswith('.wav'):
        total = max(total, float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', video], capture_output=True, text=True).stdout))
    if verbose:
        print(f'{len(ev)} sfx events, {len(talks)} talk spans, {total:.2f}s, mood={m}')
        for e in ev: print(f"  {e['t']:7.2f}  {e['kind']:<14} {e['who']}")
        for t in talks: print(f"  {t['t']:7.2f}  VOICE {t['who']} {t['dur']:.1f}s {t['text']}")
    wav = os.path.splitext(out)[0] + '.wav' if not out.endswith('.wav') else out
    master_wav(mix(ev, talks, total, m, voice, music, seed, -8 if any(t.get('narr') for t in talks) else -6), wav)
    if not out.endswith('.wav'):
        cmd = ['ffmpeg', '-v', 'error', '-y', '-i', os.path.abspath(video), '-i', os.path.abspath(wav)]; vf = []
        with tempfile.TemporaryDirectory() as td:
            g = overlays.video_graph(story, SCENE_OFFS, FREEZES, probe_fps(video), *probe_size(video)); mp = '0:v'
            if any(t['text'] for t in talks) or story.get('header') or story.get('cards') or FREEZES:
                ass(talks, os.path.join(td, 'c.ass'), story); vf = ['-vf', "ass=c.ass"]
            if g:   # split / freeze graph first, then the captions burn on its output
                vf = ['-filter_complex', g + (';[v]ass=c.ass[w]' if vf else '')]; mp = '[w]' if vf[1].endswith('[w]') else '[v]'
            cmd += vf + ['-map', mp, '-map', '1:a'] + (['-c:v', 'libx264', '-crf', '18', '-preset', 'medium', '-pix_fmt', 'yuv420p'] if vf else ['-c:v', 'copy'])
            cmd += ['-c:a', 'aac', '-b:a', '192k', '-shortest'] + TAG + [os.path.abspath(out)]
            subprocess.run(cmd, check=True, cwd=td)
        os.remove(wav)
    lufs, peak = loudness(out)
    if not out.endswith('.wav') and peak is not None and float(peak) > -1.0:   # AAC/resample overshoot past the -1.9 dB limiter
        g = -(float(peak) + 1.3); tmp2 = os.path.splitext(out)[0] + '_pk.mp4'   # (homework R151: -0.04 dBFS) -> trim the gain once
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', out, '-c:v', 'copy', '-af', f'volume={g:.2f}dB', '-c:a', 'aac', '-b:a', '192k'] + TAG + [tmp2], check=True)
        os.replace(tmp2, out); lufs, peak = loudness(out)
        if verbose: print(f'peak guard: {g:.2f} dB applied')
    if verbose: print(f'OUT {out}  integrated {lufs} LUFS, sample peak {peak} dBFS')
    return ev, talks, lufs, peak


if __name__ == '__main__':
    a = argparse.ArgumentParser(); a.add_argument('story'); a.add_argument('--video'); a.add_argument('--out')
    a.add_argument('--mood', choices=['cheery', 'tense', 'chill', 'battle']); a.add_argument('--no-voice', action='store_true'); a.add_argument('--no-music', action='store_true'); a.add_argument('--seed', type=int, default=1)
    x = a.parse_args(); run(x.story, x.video, x.out, x.mood, not x.no_voice, not x.no_music, x.seed)
