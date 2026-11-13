"""Overlay helpers for sound_mix.py: ASS lines for header / cards / freeze labels / word captions, and the ffmpeg
filter graph for split (top/bottom stacking) and freeze-frames. Pure functions, no I/O (sound_mix.py runs ffmpeg)."""
import re

# Extra styles; same font as today's captions (Arial Black). Format matches the V4+ header in sound_mix.ass.
STYLES = [
    ('Word', 130, 0, 2, 430, '&H00FFFFFF'), ('Narr', 84, 1, 2, 800, '&H00D8F2FF'), ('Header', 62, 0, 8, 150, '&H00FFFFFF'),
    ('Card', 150, 0, 5, 0, '&H00FFFFFF'), ('Counter', 260, 0, 8, 330, '&H0000E5FF'), ('Tag', 56, 0, 7, 0, '&H00FFFFFF'),
]
KEY = '&H0000E5FF&'   # key word colour (amber, BGR)


def style_lines():
    return ''.join(f"Style: {n},Arial Black,{sz},{c},&H00FFFFFF,&H00000000,&H80000000,1,{it},0,0,100,100,0,0,"
                   f"{3 if n == 'Tag' else 1},{4 if n == 'Tag' else 9},3,{an},70,70,{mv},1\n" for n, sz, it, an, mv, c in STYLES)


def ts(t): return f'{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}'


def box(t0, t1, alpha, layer=1, y0=0, h=1920):
    """Full-width rectangle (alpha '00' opaque .. 'FF' clear) as an ASS drawing."""
    return (f"Dialogue: {layer},{ts(t0)},{ts(t1)},Card,,0,0,0,,{{\an7\pos(0,{y0})\p1\1c&H000000&\1a&H{alpha}&\bord0\shad0}}"
            f"m 0 0 l 1080 0 1080 {h} 0 {h}{{\p0}}")


def txt(t0, t1, style, text, pos=None, layer=2, fx=''):
    p = (f"\an{7 if style == 'Tag' else 5}\pos({pos[0]},{pos[1]})" if pos else '')
    return f"Dialogue: {layer},{ts(t0)},{ts(t1)},{style},,0,0,0,,{{{p}{fx}}}{text}"


def word_cards(text, t0, dur, style='Word'):
    """Word-by-word cards [t0,t1,ass_text]; *key* word gets the key colour. Time per word ~ its length + 2 chars."""
    ws = text.split(); wt = [len(w.strip('*')) + 2 for w in ws]; out, t = [], t0
    for w, k in zip(ws, wt):
        d = dur * k / sum(wt); key = w.startswith('*') and w.endswith('*') and len(w) > 2
        w = w.strip('*').upper(); out.append([t, t + d, f'{{\c{KEY}}}{w}' if key else w]); t += d
    return out


def extra_events(story, offs, freezes):
    """ASS Dialogue lines for header, cards and freeze labels. offs = absolute start second per scene (0-based list)."""
    ev, total = [], offs[-1] + 99 if offs else 99
    if story.get('header'): ev.append(txt(0, total, 'Header', str(story['header']).upper()))
    for c in story.get('cards', []):
        a = offs[int(c.get('scene', 1)) - 1] + float(c.get('t', 0)); b = a + float(c.get('dur', 1.5)); ty = c.get('type', 'label')
        text = str(c.get('text', '')).upper()
        if ty == 'title': ev += [box(a, b, '00', 1), txt(a, b, 'Card', text, (540, 960))]
        elif ty == 'time': ev += [box(a, b, '80', 1), txt(a, b, 'Card', text, (540, 960))]
        elif ty == 'counter': ev.append(txt(a, b, 'Counter', text))
        elif ty == 'choice':
            ev += [box(a, b, '40', 1, 1500, 300), txt(a, b, 'Card', '1', (270, 1650), fx='\fs100'), txt(a, b, 'Card', '2', (810, 1650), fx='\fs100'),
                   txt(a, b, 'Tag', str(c.get('a', '')).upper(), (270, 1560)), txt(a, b, 'Tag', str(c.get('b', '')).upper(), (810, 1560))]
        else: ev.append(txt(a, b, 'Tag', f' {text} ', (60, 330 if c.get('pos', 'top') == 'top' else 1290), fx=''))
    for t, d, label in freezes:
        if label: ev.append(txt(t, t + d, 'Card', label.upper(), (540, 800), fx='\fs120'))
    return ev


def video_graph(story, offs, freezes, fps, W=1080, H=1920):
    """ffmpeg filter_complex text (input [0:v] -> [v]) for split pairs + freeze-frames, or None when neither is used.
    split [a,b]: during scene a's slot the frame is a (top half, centre-cropped) over b's first seconds (bottom half);
    scene b's own slot then plays normally afterwards (shortcut: no timeline merge, merge slots in the story if unwanted)."""
    parts, cur = [], '[0:v]'; hh = H // 2
    crop = f'scale={W}:{hh}:force_original_aspect_ratio=increase,crop={W}:{hh}'
    for k, (sa, sb) in enumerate(story.get('split', [])):
        a0, b0 = offs[sa - 1], offs[sb - 1]; a1 = offs[sa] if sa < len(offs) else a0 + 3; d = a1 - a0
        parts.append(f'{cur}split=3[m{k}][t{k}][u{k}]')
        parts.append(f'[t{k}]trim=start={a0}:duration={d},{crop}[ta{k}]')
        parts.append(f'[u{k}]trim=start={b0}:duration={d},setpts=PTS+{a0 - b0}/TB,{crop}[tb{k}]')
        parts.append(f'[ta{k}][tb{k}]vstack,setpts=PTS[s{k}]')
        parts.append(f'[m{k}][s{k}]overlay=eof_action=pass[o{k}]'); cur = f'[o{k}]'
    for k, (t, d, _) in enumerate(freezes):
        f0 = round(t * fps); f1 = f0 + max(1, round(d * fps)) - 1
        parts += [f'{cur}split[za{k}][zb{k}]', f'[za{k}][zb{k}]freezeframes=first={f0}:last={f1}:replace={f0}[z{k}]']; cur = f'[z{k}]'
    if not parts: return None
    parts[-1] = parts[-1][:parts[-1].rindex('[')] + '[v]'
    return ';'.join(parts)
