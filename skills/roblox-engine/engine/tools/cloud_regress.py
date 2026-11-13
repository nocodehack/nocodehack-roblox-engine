"""cloud_regress.py - run the gate checks (story.py --tier none) of many stories IN PARALLEL on Vertex AI spot CPU jobs.
  python tools/cloud_regress.py chase cookie snack            (one job per scene, spread over 3 regions)
  python tools/cloud_regress.py --all [--per story] [--regions a,b] [--machine e2-standard-4] [--keep-going]
Reuses tools/farm_run.py (gcloud wrappers with timeouts, prices, cost row).  Results: stories/<s>/scenes/sNN/report.json and
trace/cregress_<run id>_<story>.txt (same line format as trace/regress_R184_*.txt); cost row in trace/render_costs.csv + SPEND.md."""
import argparse, copy, datetime as dt, json, os, re, subprocess, sys, tarfile, tempfile, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import farm_run as F

ENG, BUCKET = F.ENG, F.BUCKET
SHAPE = {('e2', 'standard'): 4.0, ('n1', 'standard'): 3.75, ('n1', 'highcpu'): 0.9}   # GiB RAM per vCPU
STORY_PREFIX = ('chase', 'cookie', 'homework', 'phone', 'school', 'snack', 'blind', 'L1_')
SKIP_DIRS = {'.git', '.claude', 'trace', 'docs', 'research', 'shorts', 'tests', '__pycache__', 'out', 'build'}


def stories_all():
    return sorted(d for d in os.listdir(os.path.join(ENG, 'stories')) if d.startswith(STORY_PREFIX)
                  and os.path.exists(os.path.join(ENG, 'stories', d, 'story.json')))


def n_scenes(s):
    return len(json.load(open(os.path.join(ENG, 'stories', s, 'story.json'), encoding='utf-8'))['scenes'])


def make_tar(path, stories):
    """engine code + assets + tools + only the selected stories' *.json; no out/, build/, scenes/, .git, trace, media."""
    def add(tf, p, arc):
        if os.path.isdir(p):
            for n in sorted(os.listdir(p)):
                if n in SKIP_DIRS or n.lower().endswith('.mp4'): continue
                add(tf, os.path.join(p, n), arc + '/' + n)
        else: tf.add(p, arc)
    with tarfile.open(path, 'w:gz') as tf:
        for n in sorted(os.listdir(ENG)):
            p = os.path.join(ENG, n)
            if (os.path.isfile(p) and n.endswith('.py')) or n in ('assets', 'tools'): add(tf, p, n)
        for s in stories:
            for n in os.listdir(os.path.join(ENG, 'stories', s)):
                if n.endswith('.json'): tf.add(os.path.join(ENG, 'stories', s, n), f'stories/{s}/{n}')


# ---------------------------------------------------------------- price of a CPU machine (Billing Catalog, cached next to prices.json)
def cpu_prices(machine, regions):
    fam, kind, n = machine.split('-')[0], machine.split('-')[1], int(machine.split('-')[-1]); assert (fam, kind) in SHAPE, f'supported: {list(SHAPE)}'
    cache = os.path.join(F.FARM, 'prices_cpu.json'); C = json.load(open(cache)) if os.path.exists(cache) else {}
    if fam not in C or any(r not in C[fam] for r in regions):
        tok = F.token(); res, pt = [], ''
        while True:
            u = 'https://cloudbilling.googleapis.com/v1/services/6F81-5844-456A/skus?pageSize=5000&currencyCode=EUR' + (f'&pageToken={pt}' if pt else '')
            for t in range(6):   # the catalog API answers 429 after a few calls: back off
                try: d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'Authorization': 'Bearer ' + tok}))); break
                except urllib.error.HTTPError as e:
                    if e.code != 429 or t == 5: raise
                    time.sleep(30)
            res += d['skus']; pt = d.get('nextPageToken', '')
            if not pt: break
        kind = 'Instance' if fam == 'e2' else 'Predefined Instance'
        def rate(what, reg):
            s = next(s for s in res if s['description'].startswith(f'Spot Preemptible {fam.upper()} {kind} {what} running') and reg in s['serviceRegions'])
            r = s['pricingInfo'][0]['pricingExpression']['tieredRates'][-1]['unitPrice']; return float(r.get('units', 0)) + r['nanos'] / 1e9
        C[fam] = {r: dict(core=rate('Core', r), ram=rate('Ram', r)) for r in ('europe-west4', 'us-central1', 'asia-southeast1')}
        json.dump(C, open(cache, 'w'), indent=1)
    return {r: C[fam][r]['core'] * n + C[fam][r]['ram'] * n * SHAPE[(fam, kind)] for r in regions}   # EUR/h; Vertex adds no mgmt fee on CPU types (none in catalog)


# ---------------------------------------------------------------- jobs
def job_script(rid, story, tag, k):
    out = f'/gcs/{BUCKET}/regress/{rid}/out/{story}/{tag}'
    only = f'--only {k}' if k else ''
    return '; '.join([
        'mkdir -p /tmp/w && cd /tmp/w', f'cp /gcs/{BUCKET}/regress/{rid}/engine.tgz . && tar xzf engine.tgz', 'date -u +"T0 %s"',
        'PY=$(ls /opt/blender-*/5.2/python/bin/python3* | grep -v config | head -1); echo "PY=$PY"',   # Blender's bundled python (container has no system python; story.py is stdlib only)
        f'BLENDER=/usr/local/bin/blender $PY -u story.py stories/{story}/story.json --tier none {only} > story.log 2>&1',
        'echo "story.py rc $?" >> story.log', 'date -u +"T1 %s"', f'mkdir -p {out}', f'cp story.log {out}/',
        f'cd stories/{story} && for f in $(find scenes -name report.json -o -name log.txt); do mkdir -p {out}/$(dirname $f) && cp $f {out}/$f; done'])


def submit(region, name, script, machine, tmp):
    y = (f'workerPoolSpecs:\n  - machineSpec: {{machineType: {machine}}}\n    replicaCount: 1\n    containerSpec:\n      imageUri: {F.image(region)}\n'
         f'      command: ["/bin/sh", "-c"]\n      args: [{json.dumps(script)}]\nscheduling: {{strategy: SPOT, timeout: 3000s}}\n')
    cfg = os.path.join(tmp, name + '.yaml'); open(cfg, 'w').write(y)
    return json.loads(F.gcloud('ai', 'custom-jobs', 'create', f'--region={region}', f'--display-name={name}', f'--config={cfg}', '--format=json').stdout)['name']


def main():
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(); ap.add_argument('stories', nargs='*'); ap.add_argument('--all', action='store_true')
    ap.add_argument('--per', default='scene', choices=['scene', 'story']); ap.add_argument('--regions', default='europe-west4,us-central1,asia-southeast1')
    ap.add_argument('--machine', default='e2-standard-4'); ap.add_argument('--timeout-min', type=int, default=45)
    ap.add_argument('--cancel-all', action='store_true', help='list + cancel every live cr-* job (safety net)')
    a = ap.parse_args()
    if a.cancel_all:
        for reg in a.regions.split(','):
            for st in ('RUNNING', 'PENDING', 'QUEUED'):
                for jn in F.gcloud('ai', 'custom-jobs', 'list', f'--region={reg}', f'--filter=displayName:cr- AND state=JOB_STATE_{st}', '--format=value(name)', timeout=180).stdout.split():
                    print('cancel', reg, jn); F.gcloud('ai', 'custom-jobs', 'cancel', jn, f'--region={reg}', check=False)
        return
    names =stories_all() if a.all else a.stories; assert names, 'give story names or --all'
    regions = a.regions.split(','); P = F.prices(); price = cpu_prices(a.machine, regions)
    now = dt.datetime.now(dt.timezone.utc); stamp = now.strftime('%Y%m%d-%H%M%S'); rid = f'R190-{stamp}'; t0 = time.time()
    tmp = tempfile.mkdtemp(prefix='cregress_')
    rep = dict(id=rid, story='regress ' + ' '.join(names), scenes=[], frames=0, resolution='gates-only', samples=0, gpus=0, jobs=[], builds=[], upload_bytes=0,
               download_bytes=0, region_png_bytes={}, start_utc=now.isoformat(), prices_date=P['date'])
    P2 = copy.deepcopy(P)   # farm_run.finish prices jobs from P[cur].region[r].vm_spot_hr + vertex_mgmt_hr: swap in the CPU machine price
    for cur in ('EUR', 'USD'):
        fx = 1.0 if cur == 'EUR' else P['cur']['USD']['storage_gb_month'] / P['cur']['EUR']['storage_gb_month']   # EUR->USD via the catalog's own ratio
        for r in regions: P2['cur'][cur]['region'][r] = dict(vm_spot_hr=price[r] * fx, vertex_mgmt_hr=0.0, parts={})
    work = []   # (story, tag, k)
    for s in names:
        if a.per == 'story': work.append((s, 'all', 0))
        else: work += [(s, f's{k:02d}', k) for k in range(1, n_scenes(s) + 1)]
    results = {}; live = {}   # live: job name -> dict(region, item, tries, t_sub)
    pend = []; tries = {}
    try:
        tar = os.path.join(tmp, 'engine.tgz'); make_tar(tar, names); rep['upload_bytes'] = os.path.getsize(tar)
        F.gs('cp', tar, f'gs://{BUCKET}/regress/{rid}/engine.tgz')
        print(f'{rid}: {len(work)} job(s) [{a.machine} spot, ~{price[regions[0]]:.3f} EUR/h], engine.tgz {rep["upload_bytes"] / 1e6:.0f} MB, upload {time.time() - t0:.0f}s')
        def launch(item, reg):
            s, tag, k = item; n = tries[item] = tries.get(item, -1) + 1
            nm = re.sub('[^a-z0-9-]', '-', f'cr-{stamp}-{s}-{tag}-{n}'.lower())
            jn = submit(reg, nm, job_script(rid, s, tag, k), a.machine, tmp)
            live[jn] = dict(region=reg, item=item, t_sub=time.time())
        for i, item in enumerate(work):
            try: launch(item, regions[i % len(regions)])
            except RuntimeError as e: print('  submit failed, trying next region:', str(e)[:160]); launch(item, regions[(i + 1) % len(regions)])
        print(f'  submitted {len(live)} jobs'); lastp = 0
        while live:
            time.sleep(20)
            for reg in {v['region'] for v in live.values()}:
                try: js = json.loads(F.gcloud('ai', 'custom-jobs', 'list', f'--region={reg}', f'--filter=displayName:cr-{stamp}', '--format=json', timeout=180).stdout or '[]')
                except RuntimeError as e: print('  list failed, retry next poll:', str(e)[:120]); continue
                for d in js:
                    v = live.get(d['name'])
                    if not v: continue
                    st = d['state']; item = v['item']; s, tag, k = item
                    if st == 'JOB_STATE_RUNNING' or st == 'JOB_STATE_PENDING' or st == 'JOB_STATE_QUEUED':
                        if not d.get('startTime') and time.time() - v['t_sub'] > 600:   # no spot capacity: move on
                            F.gcloud('ai', 'custom-jobs', 'cancel', d['name'], f'--region={reg}', check=False); st = 'JOB_STATE_CANCELLED'
                        elif time.time() - v['t_sub'] > a.timeout_min * 60: raise RuntimeError(f'timeout {s}/{tag}')
                        else: continue
                    if st not in ('JOB_STATE_SUCCEEDED', 'JOB_STATE_FAILED', 'JOB_STATE_CANCELLED', 'JOB_STATE_EXPIRED'): continue
                    del live[d['name']]; rep['jobs'].append(F.job_record(d, reg, [(f'{s}/{tag}', 0, 0)]))
                    r = F.run([F.GSUTIL, 'cat', f'gs://{BUCKET}/regress/{rid}/out/{s}/{tag}/story.log'], check=False, timeout=120)
                    lines = [l for l in r.stdout.splitlines() if re.match(r's\d\d REPORT', l) and 'skipped' not in l]
                    if r.returncode or not lines:   # preempted / crashed before the report: retry once per region
                        n = tries[item]
                        if n < len(regions):
                            print(f'  {s}/{tag} {st} no report, resubmit -> {regions[(regions.index(reg) + 1) % len(regions)]}')
                            launch(item, regions[(regions.index(reg) + 1) % len(regions)]); continue
                        lines = [f'{tag} REPORT CRASH cloud job {st}']
                    for l in lines: print(f'  {s} {l}  [{reg}, {rep["jobs"][-1]["billed_s"]:.0f}s]'); results.setdefault(s, {})[l.split()[0]] = l
            if time.time() - lastp > 60: lastp = time.time(); print(f'  ... {len(live)} job(s) live, {sum(len(x) for x in results.values())}/{len(work) if a.per == "scene" else "?"} reports, {time.time() - t0:.0f}s')
        # download reports + write trace files
        os.makedirs(os.path.join(ENG, 'trace'), exist_ok=True)
        for s in names:
            dl = os.path.join(tmp, 'dl', s); os.makedirs(dl, exist_ok=True)
            F.run([F.GC, 'storage', 'cp', '-r', f'gs://{BUCKET}/regress/{rid}/out/{s}/*', dl, f'--project={F.PROJECT}'], check=False, timeout=600)
            for root, _, fs in os.walk(dl):
                for f in fs:
                    m = re.search(r'(s\d\d)$', root)
                    if f == 'report.json' and m:
                        dst = os.path.join(ENG, 'stories', s, 'scenes', m.group(1)); os.makedirs(dst, exist_ok=True)
                        open(os.path.join(dst, f), 'wb').write(open(os.path.join(root, f), 'rb').read())
            rs = results.get(s, {}); ls = [rs[k] for k in sorted(rs)]
            ok = len(ls) == n_scenes(s) and all(' PASS' in l for l in ls)
            open(os.path.join(ENG, 'trace', f'cregress_{rid}_{s}.txt'), 'w').write('\n'.join(ls) + f'\nSTORY {"PASS" if ok else "FAIL"} | {n_scenes(s)} scenes | gates only\n')
        rep['scenes'] = [f'{s}/{k}' for s in names for k in sorted(results.get(s, {}))]
        print(f'\n{"story":<22}{"scenes":>7}{"pass":>6}  verdict'); fails = 0
        for s in names:
            rs = results.get(s, {}); p = sum(' PASS' in l for l in rs.values()); fails += n_scenes(s) - p
            print(f'{s:<22}{n_scenes(s):>7}{p:>6}  {"PASS" if p == n_scenes(s) else "FAIL"}')
        print(f'TOTAL {len(work)} jobs, {fails} failing scene(s), wall {(time.time() - t0) / 60:.1f} min')
    except BaseException as e:
        rep['error'] = f'{type(e).__name__}: {e}'[:500]; print('RUN FAILED (cost row is still written):', rep['error']); raise
    finally:
        for jn, v in live.items(): F.gcloud('ai', 'custom-jobs', 'cancel', jn, f'--region={v["region"]}', check=False)   # never leave jobs running
        rep['end_utc'] = dt.datetime.now(dt.timezone.utc).isoformat(); rep['wall_minutes'] = (time.time() - t0) / 60
        rep['gpus'] = len(rep['jobs']); rep['gpu_minutes'] = sum(j['billed_s'] for j in rep['jobs']) / 60   # 'gpus'/'gpu_minutes' columns = jobs / job-minutes here
        F.finish(rep, P2)
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
