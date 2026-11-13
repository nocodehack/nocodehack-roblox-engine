"""story.py <story.json> [--tier none|draft|look|final|mid|preview] [--only k] [--jobs n] [--frames a-b] [--no-lint] - multi-location stories (tools/story_lint.py runs first).
Local GPU tiers: mid (hq look, 50 % + 32 spp + OIDN, upscaled to 1080x1920) and preview (same at 8 spp); --frames a-b renders only
frames a..b of each scene (timing / spot checks: no scene video, no join); mid/preview frames resume after a stop.
story.json = {'title', 'cast': [{name, shirt, pants, hair, skin, hair_style, face}],      # looks, shared by every scene
              'scenes': [{'set': {...}, 'seconds': s, 'cast': [{'name', 'at', 'yaw', 'face'}], 'props', 'beats', 'shots'}]}
Each scene becomes scenes/sNN/short.json (cast looks merged in) built by build.py in its own Blender process; the scene videos are
joined into <tier>.mp4 with one 16-frame sheet and REPORT lines collected in report.txt (copied to trace/)."""
import json, os, subprocess, sys, time, shutil, zlib
from pathlib import Path
import look

E = Path(__file__).resolve().parent
BL = os.environ.get('BLENDER', 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe')   # BLENDER overrides (cloud_regress runs on Linux)


def frames_arg(argv):
    """--frames a-b -> build.py's ['--range', 'a', 'b'] (frames a..b of every scene); no --frames -> []."""
    if '--frames' not in argv: return []
    a, b = (int(x) for x in argv[argv.index('--frames') + 1].split('-'))
    assert 0 <= a <= b, f'--frames a-b needs 0 <= a <= b, got {a}-{b}'
    return ['--range', str(a), str(b)]


def main():
    sp = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(E / 'tools')); import story_lint   # lint first: a 1 s check before minutes of Blender
    lr = story_lint.lint(sp)
    for l in lr.lines(): print(l)
    print(f'LINT {"FAIL" if lr.errors else "OK"} | {len(lr.errors)} error(s), {len(lr.warnings)} warning(s)', flush=True)
    if lr.errors and '--no-lint' not in sys.argv: sys.exit('lint errors: fix them, or run with --no-lint to build anyway')
    story = json.loads(sp.read_text(encoding='utf-8')); d = sp.parent
    tier = sys.argv[sys.argv.index('--tier') + 1] if '--tier' in sys.argv else 'draft'
    only = int(sys.argv[sys.argv.index('--only') + 1]) if '--only' in sys.argv else None
    looks = {c['name']: c for c in story['cast']}
    jobs = int(sys.argv[sys.argv.index('--jobs') + 1]) if '--jobs' in sys.argv else 3   # scenes build in parallel (24 cores)
    rng = frames_arg(sys.argv)
    inherited = {key: story[key] for key in ('look', 'set') if key in story}
    scenes = look.contrast_moods([{**inherited, **scene} for scene in story['scenes']])
    seed = story.get('seed', zlib.crc32(story['title'].encode('utf-8')))
    work = []
    import acting; fams = acting.story_families(story, acting.load_lib())   # ONE face family per character for the whole Short
    fmap = acting.story_face_map(story, fams, acting.load_lib())   # ONE decal per (character, emotion) for the whole Short
    for k, sc in enumerate(scenes, 1):
        sd = d / 'scenes' / f's{k:02d}'; sd.mkdir(parents=True, exist_ok=True)
        cast = [{'face_family': fams.get(c['name']), 'face_map': fmap.get(c['name'], {}), **looks[c['name']], **c} for c in sc['cast']]
        spec = {'title': f"{story['title']} s{k:02d}", 'fps': story.get('fps', 24), 'auto_acting': story.get('auto_acting', True), **({'camera': story['camera']} if 'camera' in story else {}), **({'frame': story['frame']} if 'frame' in story else {}), **({'strict_crowd': True} if story.get('strict_crowd') else {}), **{x: v for x, v in sc.items() if x != 'cast'}, 'cast': cast}
        spec['set'] = {'seed': seed, **spec.get('set', {'preset': 'classroom'})}
        (sd / 'short.json').write_text(json.dumps(spec, indent=1))
        work.append((k, sd))
    def run_scene(k, sd):
        if only is not None and only != k: return k, 'REPORT skipped'
        r = subprocess.run([BL, '-b', '--factory-startup', '--offline-mode', '--python-exit-code', '1', '-P', str(E / 'build.py'), '--',
                            str(sd / 'short.json'), '--tier', tier, *rng], capture_output=True, text=True, cwd=E)
        (sd / 'log.txt').write_text(r.stdout + r.stderr, encoding='utf-8')
        rep = next((l for l in r.stdout.splitlines() if l.startswith('REPORT')), f'REPORT CRASH exit {r.returncode}')
        if r.returncode and 'CRASH' in rep:
            rep += ' ' + ' | '.join([l for l in (r.stdout + r.stderr).splitlines() if 'Error' in l and 'HIP' not in l][-3:])
        return k, rep
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        res = dict(ex.map(lambda w: run_scene(*w), work))
    reports, vids = [], []
    for k, sd in work:
        print(f's{k:02d}', res[k], flush=True); reports.append(f's{k:02d} {res[k]}')
        if (sd / f'{tier}.mp4').exists(): vids.append(sd / f'{tier}.mp4')
    if tier == 'none' or rng:   # gates only / a frame range (no scene videos): nothing to join (an empty concat produced ffmpeg errors)
        (d / 'report.txt').write_text('\n'.join(reports) + '\n')
        print('STORY', 'PASS' if all('PASS' in r or 'skipped' in r for r in reports) else 'FAIL', '|', len(story['scenes']), 'scenes | gates only')
        return
    lst = d / 'concat.txt'; lst.write_text(''.join(f"file '{v.as_posix()}'\n" for v in vids))
    out = d / f'{tier}.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(lst), '-c', 'copy', str(out)])
    n = int(float(subprocess.run(['ffprobe', '-v', 'error', '-count_packets', '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_packets',
                                  '-of', 'csv=p=0', str(out)], capture_output=True, text=True).stdout.strip() or 16))
    step = max(1, n // 16)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(out), '-vf', f"select='not(mod(n\\,{step}))',scale=180:-2,tile=8x2", '-frames:v', '1',
                    str(d / f'{tier}_sheet.jpg')])
    (d / 'report.txt').write_text('\n'.join(reports) + '\n')
    stamp = time.strftime('%Y%m%d-%H%M%S'); t = E / 'trace'; t.mkdir(exist_ok=True)
    for src, nm in ((d / f'{tier}_sheet.jpg', 'sheet.jpg'), (d / 'report.txt', 'report.txt'), (sp, 'story.json')):
        if src.exists(): shutil.copy2(src, t / f'{stamp}_{d.name}_{tier}_{nm}')
    print('STORY', 'PASS' if all('PASS' in r or 'skipped' in r for r in reports) else 'FAIL', '|', len(story['scenes']), 'scenes |', out)


if __name__ == '__main__':
    main()
