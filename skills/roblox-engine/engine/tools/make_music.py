"""Synthesize the 3 music loops (assets/music) and 4 synth SFX (assets/sfx/synth). Original, numpy only, CC0.
Run: python tools/make_music.py  (idempotent; overwrites the generated files)."""
import os, subprocess, sys
import numpy as np
SR = 44100
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mtof = lambda m: 440.0 * 2 ** ((m - 69) / 12)


def pluck(f, dur, rng, decay=0.996):
    n = int(SR * dur); p = max(2, int(SR / f)); buf = rng.uniform(-1, 1, p); out = np.empty(n)
    for i in range(n):
        j = i % p; out[i] = buf[j]; buf[j] = decay * 0.5 * (buf[j] + buf[(j + 1) % p])
    return out


def tone(f, dur, harm=(1.0, 0.3), dec=4.0, att=0.004):
    t = np.arange(int(SR * dur)) / SR; y = sum(a * np.sin(2 * np.pi * f * (k + 1) * t) for k, a in enumerate(harm))
    return y * np.minimum(1, t / att) * np.exp(-dec * t)


def noise_hit(dur, rng, hp=0.9, dec=40):
    t = np.arange(int(SR * dur)) / SR; n = rng.normal(size=t.size); n = n - hp * np.concatenate([[0], n[:-1]])
    return n * np.exp(-dec * t)


def render(bpm, bars, chords, style, seed):
    rng = np.random.default_rng(seed); beat = 60 / bpm; N = int(SR * beat * 4 * bars); tail = SR * 2
    buf = np.zeros(N + tail)

    def put(x, t, g):
        i = int(t * SR); buf[i:i + x.size] += g * x[:max(0, min(x.size, buf.size - i))]
    for b in range(bars):
        root, quality = chords[b % len(chords)]; t0 = b * 4 * beat
        notes = [root + s for s in ({'M': (0, 4, 7, 12), 'm': (0, 3, 7, 12), 'M7': (0, 4, 7, 11), 'm7': (0, 3, 7, 10)}[quality])]
        for k in range(8):   # eighth-note feel
            t = t0 + k * beat / 2
            if style == 'cheery':
                put(pluck(mtof(notes[(0, 2, 1, 3, 2, 1, 3, 2)[k] % 4] + 12), 0.5, rng), t, 0.30)
                if k % 4 == 0: put(pluck(mtof(root - 12), 0.6, rng, 0.998), t, 0.55)
                if k % 2: put(noise_hit(0.05, rng), t, 0.07)
                if k in (0, 5) and b % 2: put(tone(mtof(notes[3] + 12), 0.6, (1, .2, .1), 5), t, 0.09)   # sparse glock
            elif style == 'tense':
                put(tone(mtof(root - 12), beat / 2, (1, .6, .4, .2), 6), t, 0.55)
                if k % 2: put(noise_hit(0.04, rng, 0.95, 60), t, 0.08)
                if k in (0, 3, 6): put(tone(mtof(notes[1 + k % 2] + 12), 0.35, (1, .5, .25), 7), t, 0.14)
            else:
                if k % 4 == 0:
                    for nn in notes[:3]: put(tone(mtof(nn), 1.6, (1, .35, .12), 1.6, 0.01), t, 0.15)
                if k in (0, 3, 4, 7): put(tone(mtof(root - 12), 0.7, (1, .2), 3.5), t, 0.5)
                if k % 4 == 2: put(noise_hit(0.06, rng, 0.7, 50), t, 0.08)
                if k == 0 or k == 4: put(tone(60, 0.18, (1,), 22) * 1.0, t, 0.35)   # soft kick
    out = buf[:N].copy(); out[:tail] += buf[N:N + tail]   # fold the ring-out onto the start: seamless loop
    return out / np.abs(out).max() * 0.5


def save_wav(path, x, ogg=False):
    p = path + '.f32'; x.astype('<f4').tofile(p)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', p, '-c:a', 'libvorbis', '-q:a', '3', path], check=True)
    os.remove(p)


def whoosh(rng, dur=0.4):
    n = int(SR * dur); t = np.arange(n) / SR; x = rng.normal(size=n); y = np.zeros(n); lp = 0.0
    cut = 0.04 + 0.5 * np.sin(np.pi * t / dur) ** 2   # one-pole low-pass sweeping up then down
    for i in range(n): lp += cut[i] * (x[i] - lp); y[i] = lp
    return y * np.sin(np.pi * t / dur) ** 2 / (np.abs(y).max() + 1e-9) * 0.8


def boing(dur=0.42, f0=330):
    t = np.arange(int(SR * dur)) / SR; f = f0 * (1 + 1.2 * (1 - np.exp(-t * 9))) * (1 + 0.04 * np.sin(2 * np.pi * 22 * t))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-6 * t) * np.minimum(1, t / 0.004) * 0.7


def pop(dur=0.12):
    t = np.arange(int(SR * dur)) / SR; f = 500 + 900 * np.exp(-t * 40)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-30 * t) * 0.7


if __name__ == '__main__':
    os.makedirs(f'{ROOT}/assets/music', exist_ok=True); os.makedirs(f'{ROOT}/assets/sfx/synth', exist_ok=True)
    M = {'cheery': (108, [(48, 'M'), (55, 'M'), (57, 'm'), (53, 'M')]),
         'tense': (118, [(57, 'm'), (53, 'M'), (50, 'm'), (52, 'M')]),
         'chill': (84, [(53, 'M7'), (52, 'm7'), (50, 'm7'), (48, 'M7')])}
    for i, (name, (bpm, ch)) in enumerate(M.items()):
        save_wav(f'{ROOT}/assets/music/{name}.ogg', render(bpm, 8, ch, name, 10 + i)); print('music', name)
    r = np.random.default_rng(5)
    for i in range(3): save_wav(f'{ROOT}/assets/sfx/synth/whoosh_{i}.ogg', whoosh(r, 0.32 + 0.1 * i))
    for i, f in enumerate((300, 380, 460)): save_wav(f'{ROOT}/assets/sfx/synth/boing_{i}.ogg', boing(f0=f))
    for i in range(3): save_wav(f'{ROOT}/assets/sfx/synth/pop_{i}.ogg', pop(0.1 + 0.02 * i) * (0.85 + 0.1 * i))
