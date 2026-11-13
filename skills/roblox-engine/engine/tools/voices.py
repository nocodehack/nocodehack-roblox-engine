"""ElevenLabs voices for a story: fills beat `voice`/`narrate_voice` (+ `talk` for `say` lines).
Usage: python tools/voices.py stories/<name>/story.json [--model eleven_v4] [--redo] [--dry-run]
Key: ELEVENLABS_API_KEY in <engine>/.env (never printed beyond the last 4 chars). Cache: stories/<name>/voice/<hash>.mp3."""
import argparse, hashlib, json, os, shutil, subprocess, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNUP = 'https://try.elevenlabs.io/m7d07a0chdsb'
API = 'https://api.elevenlabs.io'


def read_env(path=None):
    out = {}
    for ln in open(path or os.path.join(ROOT, '.env'), encoding='utf-8') if os.path.exists(path or os.path.join(ROOT, '.env')) else []:
        if '=' in ln and not ln.lstrip().startswith('#'): k, v = ln.split('=', 1); out[k.strip()] = v.strip().strip('"\'')
    return out


def http(method, url, key, body=None):
    """Real HTTP layer; tests replace it (http=...) so no live request is ever made by tests."""
    rq = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, method=method, headers={'xi-api-key': key, 'Content-Type': 'application/json'})
    return urllib.request.urlopen(rq, timeout=60).read()


def lines(story):
    """[(beat, key, text, voice_name)] for every say / narrate line."""
    out = []
    for sc in story.get('scenes', []):
        for b in sc.get('beats', []):
            if b.get('say') and story.get('voices', {}).get(b.get('who')): out.append((b, 'voice', b['say'], story['voices'][b['who']]))
            if b.get('narrate'): out.append((b, 'narrate_voice', b['narrate'], (story.get('narrator') or {}).get('voice')))
    return out


def dur(path):
    return float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path], capture_output=True, text=True).stdout)


def polish(raw, out):   # trim lead/trail silence, loudnorm -16 LUFS
    af = 'silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=1:stop_threshold=-45dB:stop_duration=0.3,loudnorm=I=-16:TP=-1.5:LRA=11'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', raw, '-af', af, '-ar', '44100', out], check=True)


def run(story_path, model='eleven_v4', redo=False, dry=False, http=http, env=None):
    story = json.load(open(story_path, encoding='utf-8')); sdir = os.path.dirname(os.path.abspath(story_path)); L = lines(story)
    chars = sum(len(t) for _, _, t, _ in L); print(f'{len(L)} lines, {chars} characters (about {chars} credits)')
    if dry or not L: return 0
    key = (env if env is not None else read_env()).get('ELEVENLABS_API_KEY')
    if not key:
        print(f'No ELEVENLABS_API_KEY. Sign up: {SIGNUP}\nThen add a line ELEVENLABS_API_KEY=... to {os.path.join(ROOT, ".env")}'); return 1
    print('key ends ...' + key[-4:])
    ids = {v['name'].lower(): v['voice_id'] for v in json.loads(http('GET', API + '/v1/voices', key))['voices']}
    os.makedirs(os.path.join(sdir, 'voice'), exist_ok=True); shutil.copy(story_path, story_path + '.bak')
    for b, k, text, vn in L:
        vid = ids.get(str(vn).lower(), vn)   # a raw id is accepted
        rel = 'voice/' + hashlib.md5(f'{text}|{vid}|{model}'.encode()).hexdigest()[:12] + '.mp3'; fp = os.path.join(sdir, rel)
        if redo or not os.path.exists(fp):
            for attempt in (1, 2):
                try: raw = http('POST', f'{API}/v1/text-to-speech/{vid}?output_format=mp3_44100_128', key, {'text': text, 'model_id': model}); break
                except Exception as e:
                    if attempt == 2: raise
            open(fp + '.raw.mp3', 'wb').write(raw); polish(fp + '.raw.mp3', fp); os.remove(fp + '.raw.mp3')
        b[k] = rel
        if k == 'voice': b['talk'] = round(dur(fp), 2)   # mouth time; narrator lines never move mouths, so no talk
    json.dump(story, open(story_path, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    return 0


if __name__ == '__main__':
    a = argparse.ArgumentParser(); a.add_argument('story'); a.add_argument('--model', default='eleven_v4'); a.add_argument('--redo', action='store_true'); a.add_argument('--dry-run', action='store_true')
    x = a.parse_args(); sys.exit(run(x.story, x.model, x.redo, x.dry_run))
