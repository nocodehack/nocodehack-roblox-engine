"""farm_run.py - render a built story in TRUE high quality ('hq' tier) on Google Cloud spot A100s (Vertex AI custom jobs).
  python tools/farm_run.py <story> [--gpus 8] [--regions europe-west4,us-central1,asia-southeast1]
  python tools/farm_run.py <story> --scene s01 --stills 10,40        (only a few frames -> stories/<story>/hq_stills/)
  python tools/farm_run.py --refresh-prices                           (re-read SKU prices from the Cloud Billing Catalog)
  python tools/farm_run.py --reconcile                                (fill actual billed cost next to the estimate, needs billing export)
Every run is a "render" <story>-<timestamp>; its jobs, timings and cost estimate go to trace/renders/<id>.json,
trace/render_costs.csv and SPEND.md.  Cost = Vertex job billed seconds x public SKU price (tools/gcloud-farm/prices.json)."""
import argparse, csv, datetime as dt, glob, json, math, os, re, shutil, subprocess, sys, tempfile, time, urllib.request, urllib.parse

ENG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FARM = os.environ.get('ENGINE_FARM_DIR', os.path.join(ENG, 'farm'))   # env overrides: see research/PORTABILITY.md
PRICES = os.path.join(FARM, 'prices.json')
GC = os.environ.get('GCLOUD') or os.path.expandvars(r'%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd')
GSUTIL = os.environ.get('GSUTIL') or os.path.expandvars(r'%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin\gsutil.cmd')
BLENDER = os.environ.get('BLENDER', r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe')
PROJECT = os.environ.get('ENGINE_GCP_PROJECT', ''); BUCKET = os.environ.get('ENGINE_GCP_BUCKET', PROJECT + '-farm')
def image(region):   # replicated per region (Artifact Registry repo 'farm' in each) so spot GPUs pull locally, not across continents
    return f'{region}-docker.pkg.dev/{PROJECT}/farm/blender:5.2.3'
BUCKET_REGION = 'europe-west4'   # farm bucket location (for inter-region transfer pricing)
MACHINE, GPU_TYPE, GPUS_PER_JOB = 'a2-highgpu-1g', 'NVIDIA_TESLA_A100', 1
A2_1G = dict(vcpu=12, ram_gib=85)   # a2-highgpu-1g shape
FPS = 24
# R208 fast HQ: 67 % res (720x1280) + 64 spp, Lanczos to 1080x1920 at assembly = same look (local A/B MAE 1.7/255), 3.3x faster.
# --full restores native 1080x1920 128 spp.
HQ_PCT, HQ_SPP = 67, 64
TURN = '-'   # 'N:F' turntable (--turntable)
ENVS = ''   # 'env K=V ' prefix for the farm Blender command (--env)
SHADOW = '-'   # 'shadow' = shadow-catcher floor in alpha mode
CUTOUT = '-'   # --cutout Name1,Name2: transparent PNG cutouts of those cast members only (MG stills)
ENGINE_FILES = sorted(f for f in os.listdir(ENG) if f.endswith('.py'))   # R229 ALL engine modules: R207 look.py imports space -> every HQ job crashed on import (3 named files were uploaded)
TRACE = os.path.join(ENG, 'trace'); RENDERS = os.path.join(TRACE, 'renders')
CSV = os.path.join(TRACE, 'render_costs.csv'); SPEND = os.path.join(ENG, 'SPEND.md')
PENDING = os.path.join(TRACE, 'farm_pending.json')   # image builds not yet charged to a render
COLS = ['render_id', 'story', 'scenes', 'frames', 'resolution', 'samples', 'gpus', 'gpu_minutes', 'wall_minutes', 'est_cost_eur',
        'est_cost_usd', 'cost_per_frame_eur', 'cost_per_second_of_video_eur', 'actual_cost_eur', 'start_utc', 'end_utc']


def run(cmd, check=True, timeout=300):
    """Output goes to temp FILES (pipes can fill / be held open by gcloud.cmd's grandchildren) and the whole process tree is
    killed on timeout, so no call can hang forever."""
    with tempfile.TemporaryFile() as fo, tempfile.TemporaryFile() as fe:
        p = subprocess.Popen(cmd, stdout=fo, stderr=fe, stdin=subprocess.DEVNULL)
        try: rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(p.pid)], capture_output=True)
            p.wait(); rc = -9
        fo.seek(0); fe.seek(0)
        o, e = fo.read().decode('utf-8', 'replace'), fe.read().decode('utf-8', 'replace')
    if rc == -9: e += f' TIMEOUT after {timeout}s'
    r = subprocess.CompletedProcess(cmd, rc, o, e)
    if check and rc:
        raise RuntimeError(f'{cmd[:4]} failed (rc {rc}): {e[-800:]}')
    return r


def gcloud(*a, check=True, timeout=120):
    return run([GC, *a, f'--project={PROJECT}'], check, timeout)


def token():
    return run([GC, 'auth', 'print-access-token']).stdout.strip()


def iso(s):
    return dt.datetime.fromisoformat(re.sub(r'(\.\d{6})\d*Z$', r'\1+00:00', s.replace('Z', '+00:00')) if s else None) if s else None


# ---------------------------------------------------------------- prices (Cloud Billing Catalog, cached)
def refresh_prices():
    out = {'date': dt.date.today().isoformat(), 'source': 'cloudbilling.googleapis.com v1 services/*/skus', 'cur': {}}
    tok = token()
    for cur in ('EUR', 'USD'):
        def skus(svc):
            res, pt = [], ''
            while True:
                u = f'https://cloudbilling.googleapis.com/v1/services/{svc}/skus?pageSize=5000&currencyCode={cur}' + (f'&pageToken={pt}' if pt else '')
                d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'Authorization': 'Bearer ' + tok})))
                res += d['skus']; pt = d.get('nextPageToken', '')
                if not pt: return res

        def rate(s, tier=-1):
            r = s['pricingInfo'][0]['pricingExpression']['tieredRates'][tier]['unitPrice']
            return float(r.get('units', 0)) + r['nanos'] / 1e9

        def find(sk, pat, region_word):   # one SKU whose description matches and which covers the region
            hit = [s for s in sk if re.search(pat, s['description']) and not re.search('Commitment|80', s['description']) and region_word in s['serviceRegions']]
            assert hit, (pat, region_word)
            return hit[0]
        ce, vx = skus('6F81-5844-456A'), skus('C7E2-9256-1C43')
        c = {'region': {}}
        for reg in ('europe-west4', 'us-central1', 'asia-southeast1'):
            core = rate(find(ce, r'^Spot Preemptible A2 Instance Core running', reg))
            ram = rate(find(ce, r'^Spot Preemptible A2 Instance Ram running', reg))
            gpu = rate(find(ce, r'^Nvidia Tesla A100 GPU attached to Spot Preemptible VMs running', reg))
            # Vertex AI training management fee (charged on top of the VM resources; applied to spot too = conservative upper bound)
            mc = rate(find(vx, r'^Vertex AI: Training/Pipelines management fee on A2 Instance Core', reg))
            mr = rate(find(vx, r'^Vertex AI: Training/Pipelines management fee on A2 Instance RAM', reg))
            mg = rate(find(vx, r'^Vertex AI: Training/Pipelines management fee on Nvidia Tesla A100', reg))
            c['region'][reg] = {'vm_spot_hr': core * A2_1G['vcpu'] + ram * A2_1G['ram_gib'] + gpu,
                                'vertex_mgmt_hr': mc * A2_1G['vcpu'] + mr * A2_1G['ram_gib'] + mg,
                                'parts': dict(core=core, ram=ram, a100=gpu, mgmt_core=mc, mgmt_ram=mr, mgmt_a100=mg)}
        bd = next(s for s in skus('8B5D-EF7D-EB12') if s['description'] == 'Build time e2-standard-2')
        c['build_min'] = rate(bd)
        st = skus('95FF-2EF5-5EA1')
        c['storage_gb_month'] = rate(next(s for s in st if s['description'] == 'Standard Storage Netherlands'))
        c['egress_internet_gb'] = rate(next(s for s in st if s['description'].startswith('Download Worldwide Destinations (excluding')), 1)  # first paid tier (first 100GB/mo are free)
        inter = {}
        for s in ce:   # cross-continent transfer out of a VM, to Europe (job writes PNGs to the EU bucket)
            m = re.match(r'Network Inter Region Egress from (Americas|APAC|Asia Pacific|Southeast Asia|Indonesia) to (EMEA|Europe)$', s['description'])
            if m: inter[m.group(1)] = rate(s, 0)
        c['inter_region_gb'] = {'us-central1': inter.get('Americas'), 'asia-southeast1': inter.get('APAC') or inter.get('Asia Pacific') or inter.get('Southeast Asia'),
                                'europe-west4': 0.0}
        out['cur'][cur] = c
    json.dump(out, open(PRICES, 'w'), indent=1)
    print('prices ->', PRICES)
    return out


def prices():
    return json.load(open(PRICES)) if os.path.exists(PRICES) else refresh_prices()


# ---------------------------------------------------------------- cost
def job_cost(P, j, cur):
    c = P['cur'][cur]['region'][j['region']]
    return j['billed_s'] / 3600 * (c['vm_spot_hr'] + c['vertex_mgmt_hr'])


def render_cost(P, r):
    out = {}
    for cur in ('EUR', 'USD'):
        c = P['cur'][cur]
        gpu = sum(job_cost(P, j, cur) for j in r['jobs'])
        build = sum(b['seconds'] for b in r.get('builds', [])) / 60 * c['build_min']
        gb_dl = r.get('download_bytes', 0) / 1e9
        egress = gb_dl * c['egress_internet_gb']
        storage = (r.get('upload_bytes', 0) + r.get('download_bytes', 0)) / 1e9 * c['storage_gb_month'] / 30   # ~1 day retained
        inter = sum(r.get('region_png_bytes', {}).get(g, 0) / 1e9 * (c['inter_region_gb'].get(g) or 0) for g in c['inter_region_gb'])
        out[cur] = dict(vertex_jobs=gpu, cloud_build=build, gcs_egress=egress, gcs_storage=storage, inter_region=inter, total=gpu + build + egress + storage + inter)
    return out


def write_csv():
    rows = []
    for f in sorted(glob.glob(os.path.join(RENDERS, '*.json'))):
        r = json.load(open(f)); k = r['cost']
        rows.append([r['id'], r['story'], ' '.join(r['scenes']), r['frames'], r['resolution'], r['samples'], r['gpus'], f"{r['gpu_minutes']:.2f}",
                     f"{r['wall_minutes']:.2f}", f"{k['EUR']['total']:.4f}", f"{k['USD']['total']:.4f}", f"{k['EUR']['total'] / max(r['frames'], 1):.4f}",
                     f"{k['EUR']['total'] / max(r['frames'] / FPS, 1e-9):.4f}", '' if r.get('actual_cost_eur') is None else f"{r['actual_cost_eur']:.4f}",
                     r['start_utc'], r['end_utc']])
    with open(CSV, 'w', newline='') as fh:
        w = csv.writer(fh); w.writerow(COLS); w.writerows(rows)


def finish(r, P):
    r['cost'] = render_cost(P, r)
    os.makedirs(RENDERS, exist_ok=True)
    json.dump(r, open(os.path.join(RENDERS, r['id'] + '.json'), 'w'), indent=1)
    write_csv()
    k = r['cost']['EUR']; kd = r['cost']['USD']; sec = max(r['frames'] / FPS, 1e-9)
    line = (f"- RENDER {r['id']} | {r['story']} {','.join(r['scenes'])} | {r['frames']} frames {r['resolution']} {r['samples']}spp | {r['gpus']} GPUs, "
            f"{r['gpu_minutes']:.1f} GPU-min, wall {r['wall_minutes']:.1f} min | est {k['total']:.2f} EUR / {kd['total']:.2f} USD "
            f"(jobs {k['vertex_jobs']:.2f}, build {k['cloud_build']:.2f}, gcs {k['gcs_egress'] + k['gcs_storage'] + k['inter_region']:.2f}) | actual: pending reconcile")
    with open(SPEND, 'a', encoding='utf-8') as fh: fh.write(line + '\n')
    print(f"RENDER COST {r['id']}: {k['total']:.2f} EUR ({r['gpu_minutes']:.1f} GPU-min, {r['frames']} frames, {k['total'] / sec:.3f} EUR/s of video)")


# ---------------------------------------------------------------- scenes / upload
PACK = '''import bpy, sys, json, os
out, remote = sys.argv[sys.argv.index('--') + 1:][:2]
try: bpy.ops.file.pack_all()
except Exception as e: print('PACK WARN', e)
# image sequences / movies cannot be packed: ship their folders to the bucket and point the .blend at the /gcs copy
for k, im in enumerate(list(bpy.data.images) + list(bpy.data.movieclips)):
    if getattr(im, 'source', 'MOVIE') in ('SEQUENCE', 'MOVIE') and getattr(im, 'packed_file', None) is None and im.filepath:
        f = os.path.abspath(bpy.path.abspath(im.filepath)); tag = f'{k}_{os.path.basename(os.path.dirname(f))}'
        print('SEQ', json.dumps([os.path.dirname(f), tag])); im.filepath = f'{remote}/seq/{tag}/{os.path.basename(f)}'
bpy.ops.wm.save_as_mainfile(filepath=out, copy=True)
sc = bpy.context.scene
print('RANGE', json.dumps([sc.frame_start, sc.frame_end]))
'''


def gs(*a, check=True):
    return run([GSUTIL, '-q', *a], check, timeout=900)


def gs_ls(prefix):
    r = run([GSUTIL, 'ls', prefix], check=False, timeout=120)
    return r.stdout.split() if r.returncode == 0 else []


def pack_upload(story, scene, tmp, rep):
    src = os.path.join(ENG, 'stories', story, 'scenes', scene, 'build', 'scene.blend')
    assert os.path.exists(src), src
    pk = os.path.join(tmp, 'pack.py'); open(pk, 'w').write(PACK)
    dst = os.path.join(tmp, f'{scene}.blend')
    r = run([BLENDER, '-b', src, '-P', pk, '--', dst, f'/gcs/{BUCKET}/hq/{story}/{scene}'], timeout=900)
    f0, f1 = json.loads(re.search(r'RANGE (\[.*?\])', r.stdout).group(1))
    for d, tag in (json.loads(m) for m in re.findall(r'^SEQ (\[.*\])\r?$', r.stdout, re.M)):
        assert os.path.isdir(d), f'sequence folder missing: {d}'
        gs('-m', 'cp', '-r', os.path.join(d, '*'), f'gs://{BUCKET}/hq/{story}/{scene}/seq/{tag}/')
    gs('cp', dst, f'gs://{BUCKET}/hq/{story}/{scene}/scene.blend')
    rep['upload_bytes'] += os.path.getsize(dst)
    return f0, f1


# ---------------------------------------------------------------- jobs
def submit(region, name, segs, story, outbase, tmp):
    """segs = [(scene, f0, f1)] ; one Vertex custom job = one spot A100, runs the segments one after another."""
    base = f'/gcs/{BUCKET}/hq/{story}'
    cmds = ['nvidia-smi -L', 'date -u +"T0 %s"']
    for sc, a, b in segs:
        cmds.append(f'{ENVS}blender -b {base}/{sc}/scene.blend -P {base}/engine/farm_hq.py -- {base}/engine {base}/{outbase}/{sc} {a} {b} CUDA {HQ_PCT} {HQ_SPP} {CUTOUT} {SHADOW} {TURN}')
    cmds.append('date -u +"T1 %s"')
    y = f'''workerPoolSpecs:
  - machineSpec: {{machineType: {MACHINE}, acceleratorType: {GPU_TYPE}, acceleratorCount: {GPUS_PER_JOB}}}
    replicaCount: 1
    containerSpec:
      imageUri: {image(region)}
      command: ["/bin/sh", "-c"]
      args: [{json.dumps("; ".join(cmds))}]
scheduling: {{strategy: SPOT, timeout: 14400s}}
'''
    cfg = os.path.join(tmp, name + '.yaml'); open(cfg, 'w').write(y)
    r = gcloud('ai', 'custom-jobs', 'create', f'--region={region}', f'--display-name={name}', f'--config={cfg}', '--format=json')
    return json.loads(r.stdout)['name']   # projects/N/locations/R/customJobs/ID


def describe(jname, region):
    return json.loads(gcloud('ai', 'custom-jobs', 'describe', jname, f'--region={region}', '--format=json').stdout)


def job_record(d, region, segs):
    st, en, cr = iso(d.get('startTime')), iso(d.get('endTime')), iso(d.get('createTime'))
    ms = d['jobSpec']['workerPoolSpecs'][0]['machineSpec']
    return dict(name=d['name'], region=region, state=d['state'], machine=ms['machineType'], gpu=ms.get('acceleratorType'),
                gpu_count=ms.get('acceleratorCount', 0), strategy=d['jobSpec'].get('scheduling', {}).get('strategy', 'ON_DEMAND'),
                create=d.get('createTime'), start=d.get('startTime'), end=d.get('endTime'), segs=segs,
                billed_s=(en - st).total_seconds() if st and en else 0.0, queue_s=(st - cr).total_seconds() if st and cr else 0.0)


def missing_runs(story, outbase, scene, f0, f1):
    have = {int(m.group(1)) for u in gs_ls(f'gs://{BUCKET}/hq/{story}/{outbase}/{scene}/') if (m := re.search(r'(\d{4})\.png$', u))}
    runs, cur = [], None
    for f in range(f0, f1 + 1):
        if f in have: cur = None; continue
        if cur: cur[1] = f
        else: cur = [f, f]; runs.append(cur)
    return [(scene, a, b) for a, b in runs]


def split(runs, n):
    """cut the list of (scene, a, b) frame runs into n chunks of ~equal frame counts."""
    total = sum(b - a + 1 for _, a, b in runs); n = max(1, min(n, total)); per = math.ceil(total / n)
    chunks, cur, left = [], [], per
    for sc, a, b in runs:
        while a <= b:
            take = min(left, b - a + 1); cur.append((sc, a, a + take - 1)); a += take; left -= take
            if left == 0: chunks.append(cur); cur, left = [], per
    if cur: chunks.append(cur)
    return chunks


def split_weighted(runs, w):
    """cut (scene, a, b) runs into len(w) chunks with frame counts proportional to w (a GPU's speed)."""
    total = sum(b - a + 1 for _, a, b in runs); n = max(1, min(len(w), total)); w = w[:n]; tw = sum(w)
    quota = [max(1, round(total * x / tw)) for x in w]; quota[-1] = max(1, total - sum(quota[:-1]))
    chunks, cur, k = [], [], 0; left = quota[0]
    for sc, a, b in runs:
        while a <= b:
            take = min(left, b - a + 1); cur.append((sc, a, a + take - 1)); a += take; left -= take
            if left == 0 and k < n - 1: chunks.append(cur); cur = []; k += 1; left = quota[k]
    if cur: chunks.append(cur)
    assert sum(b - a + 1 for c in chunks for _, a, b in c) == total
    return chunks


def farm(story, work, regions, outbase, rep, tmp, tag):
    """work = {scene: (f0, f1)} ; submits chunks, polls, resubmits failed ones (<=3 retries per chunk).  Returns when all frames exist."""
    live, retries, t_end = {}, {}, time.time() + 9 * 3600
    def runs_left():
        return [x for sc, (a, b) in work.items() for x in missing_runs(story, outbase, sc, a, b)]
    # chunk sizes weighted by measured region speed (s/frame, R151: EU 15, US 17, Asia 21): equal chunks left Asia finishing last
    SPEED = {'europe-west4': 15.0, 'us-central1': 17.0, 'asia-southeast1': 21.0}
    regs = [regions[i % len(regions)] for i in range(rep['gpus'])]
    todo = split_weighted(runs_left(), [1.0 / SPEED.get(r, 18.0) for r in regs])
    for i, ch in enumerate(todo): live[i] = (None, regs[i], ch)
    pending = list(range(len(todo))); nid = len(todo); lastp = 0
    try:
        for i in pending:
            reg, ch = live[i][1], live[i][2]
            live[i] = (submit(reg, f'hq-{tag}-{i}', ch, story, outbase, tmp), reg, ch)
            print(f'  submitted chunk {i} -> {reg} ({sum(b - a + 1 for _, a, b in ch)} frames)')
        _poll(live, retries, t_end, regions, work, story, outbase, rep, tmp, tag, runs_left, nid, lastp)
    finally:
        for jn, reg, _ in live.values():   # never leave GPUs running after an error / timeout
            if jn: gcloud('ai', 'custom-jobs', 'cancel', jn, f'--region={reg}', check=False)


def _poll(live, retries, t_end, regions, work, story, outbase, rep, tmp, tag, runs_left, nid, lastp):
    while live and time.time() < t_end:
        time.sleep(20)
        for i in list(live):
            jn, reg, ch = live[i]
            try: d = describe(jn, reg)
            except RuntimeError as e: print('  describe failed, retrying next poll:', str(e)[:120]); continue
            s = d['state']
            if s in ('JOB_STATE_SUCCEEDED', 'JOB_STATE_FAILED', 'JOB_STATE_CANCELLED', 'JOB_STATE_EXPIRED'):
                rep['jobs'].append(job_record(d, reg, ch)); del live[i]
                print(f'  job {jn.split("/")[-1]} [{reg}] {s} billed {rep["jobs"][-1]["billed_s"]:.0f}s')
                rem = [x for sc, a, b in ch for x in missing_runs(story, outbase, sc, a, b)]
                if rem:
                    retries[i] = retries.get(i, 0) + 1
                    assert retries[i] <= 3, f'chunk {i} failed 3 times: {rem}'
                    reg2 = regions[(regions.index(reg) + 1) % len(regions)] if s != 'JOB_STATE_SUCCEEDED' else reg   # preempted/no capacity -> try another region
                    live[nid] = (submit(reg2, f'hq-{tag}-{i}r{retries[i]}', rem, story, outbase, tmp), reg2, rem)
                    print(f'  resubmitted {len(rem)} run(s) -> {reg2}'); retries[nid] = retries[i]; nid += 1
        if time.time() - lastp > 60:
            lastp = time.time(); print(f'  ... {len(live)} job(s) running, frames done: {sum(b - a + 1 for sc, (a, b) in work.items()) - sum(b - a + 1 for _, a, b in runs_left())}')
    assert not live, 'timeout'


def job_logs(rep, story, tag):
    d = os.path.join(ENG, 'stories', story, 'hq_logs'); os.makedirs(d, exist_ok=True)
    for j in rep['jobs']:
        fn = os.path.join(d, j['name'].split('/')[-1] + '.txt')
        # NOT 'stream-logs': it follows the job and was the thing that hung the runner. 'logging read' returns and exits.
        r = gcloud('logging', 'read', f'resource.type="ml_job" AND resource.labels.job_id="{j["name"].split("/")[-1]}"', '--order=asc',
                   '--freshness=3d', '--limit=3000', '--format=value(timestamp,textPayload)', check=False, timeout=120)
        open(fn, 'w', encoding='utf-8').write(r.stdout + r.stderr)
        j['frame_times'] = [float(x) for x in re.findall(r'HQ frame \d+ done (\d+)s', r.stdout + r.stderr)]
        j['log'] = fn


def absorb_builds(rep):
    st = json.load(open(PENDING)) if os.path.exists(PENDING) else {'since': (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()}
    r = gcloud('builds', 'list', '--region=europe-west4', '--limit=20', '--format=json', check=False)
    try: bl = json.loads(r.stdout or '[]')
    except ValueError: bl = []
    for b in bl:
        if b['createTime'] > st['since'] and b.get('startTime') and b.get('finishTime'):
            rep['builds'].append(dict(id=b['id'], seconds=(iso(b['finishTime']) - iso(b['startTime'])).total_seconds()))
    st['since'] = dt.datetime.now(dt.timezone.utc).isoformat()
    os.makedirs(TRACE, exist_ok=True); json.dump(st, open(PENDING, 'w'))


# ---------------------------------------------------------------- reconcile
def reconcile():
    tok = token(); H = {'Authorization': 'Bearer ' + tok}
    def api(u, body=None):
        rq = urllib.request.Request(u, data=json.dumps(body).encode() if body else None, headers={**H, 'Content-Type': 'application/json'})
        return json.load(urllib.request.urlopen(rq))
    tbl = None
    try:
        for ds in api(f'https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT}/datasets').get('datasets', []):
            did = ds['datasetReference']['datasetId']
            for t in api(f'https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT}/datasets/{did}/tables').get('tables', []):
                if t['tableReference']['tableId'].startswith('gcp_billing_export'): tbl = f"{PROJECT}.{did}.{t['tableReference']['tableId']}"
    except Exception as e:
        print('BigQuery not reachable:', e)
    if not tbl:
        print('NO BILLING EXPORT FOUND. Actual cost needs Billing > Billing export > BigQuery export (standard usage cost) enabled once in the\n'
              'Cloud Console for the billing account, into a dataset in project', PROJECT, '(console-only step, data starts flowing after enabling and lags hours).\n'
              'Until then estimates in render_costs.csv stay unreconciled.')
        return
    for f in sorted(glob.glob(os.path.join(RENDERS, '*.json'))):
        r = json.load(open(f)); a = iso(r['start_utc']) - dt.timedelta(minutes=10); b = iso(r['end_utc']) + dt.timedelta(minutes=10)
        q = (f"SELECT SUM(cost) c, ANY_VALUE(currency) cur FROM `{tbl}` WHERE project.id='{PROJECT}' AND usage_start_time >= '{a.isoformat()}' "
             f"AND usage_end_time <= '{b.isoformat()}' AND service.description IN ('Vertex AI','Compute Engine','Cloud Build','Cloud Storage','Artifact Registry')")
        res = api(f'https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT}/queries', {'query': q, 'useLegacySql': False})
        row = res.get('rows')
        if res.get('jobComplete') and row and row[0]['f'][0]['v'] is not None:
            r['actual_cost_eur'] = float(row[0]['f'][0]['v']); r['actual_currency'] = row[0]['f'][1]['v']
            json.dump(r, open(f, 'w'), indent=1)
            print(f"{r['id']}: estimate {r['cost']['EUR']['total']:.2f} EUR, actual {r['actual_cost_eur']:.2f} {r['actual_currency']}")
        else: print(r['id'], 'no billing rows yet (billing lags hours)')
    write_csv()


# ---------------------------------------------------------------- video
def main():
    sys.stdout.reconfigure(line_buffering=True); sys.stderr.reconfigure(line_buffering=True)   # live progress even when piped
    ap = argparse.ArgumentParser(); ap.add_argument('story', nargs='?'); ap.add_argument('--gpus', type=int, default=8)
    ap.add_argument('--regions', default='europe-west4,us-central1,asia-southeast1'); ap.add_argument('--scene'); ap.add_argument('--stills')
    ap.add_argument('--reconcile', action='store_true'); ap.add_argument('--resume', help='render id whose frames to continue (default: a fresh output folder)'); ap.add_argument('--refresh-prices', action='store_true')
    ap.add_argument('--frames', help='a-b: render only this frame range of --scene (re-render a moment, not the whole scene)')
    ap.add_argument('--blend', help='render ANY .blend (e.g. an MG scene built with docs/MG_API.md) instead of a story scene; needs --frames')
    ap.add_argument('--res', help='WxH output size, e.g. 960x540 (default: the story 9:16 1080x1920 via 67 %% + upscale)')
    ap.add_argument('--spp', type=int, help='Cycles samples (default 64, --full 128)')
    ap.add_argument('--turntable', help='N:F orbit the camera 360 deg in N frames around the cast at scene frame F (with --scene; MG turntables)')
    ap.add_argument('--env', action='append', default=[], help='K=V passed to Blender on the farm (evidence switches, e.g. LOOK_SHAFT_KEEP=1)')
    ap.add_argument('--alpha', action='store_true', help='whole cast on a transparent background + shadow-catcher floor, 16-bit RGBA PNG + hq_alpha.mov (motion graphics)')
    ap.add_argument('--cutout', help='cast names (comma list): render only them on a transparent background (stills for graphics)')
    ap.add_argument('--full', action='store_true', help='native 1080x1920 128 spp (default: fast 67 %% + 64 spp, upscaled)')
    a = ap.parse_args()
    global HQ_PCT, HQ_SPP, CUTOUT, SHADOW, ENVS, TURN
    sj = os.path.join(ENG, 'stories', a.story or '', 'story.json'); fr_ = json.load(open(sj, encoding='utf-8')).get('frame') if a.story and os.path.exists(sj) else None
    OUT_WH = (a.res.lower().replace('x', ':') if a.res else f'{fr_[0]}:{fr_[1]}' if fr_ else '1080:1920')   # B1 story 'frame' (16:9)
    if a.full: HQ_PCT, HQ_SPP = 100, 128
    if a.turntable: TURN = a.turntable; a.frames = a.frames or f"0-{int(a.turntable.split(':')[0]) - 1}"
    if a.env: ENVS = 'env ' + ' '.join(a.env) + ' '
    if a.cutout: CUTOUT = a.cutout.replace(' ', '')
    if a.alpha:
        CUTOUT = ','.join(c['name'] for c in json.load(open(os.path.join(ENG, 'stories', a.story, 'story.json'), encoding='utf-8'))['cast']); SHADOW = 'shadow'
    if a.refresh_prices: return refresh_prices()
    if a.reconcile: return reconcile()
    if a.blend:   # B5: an outside .blend goes through the same farm as a one-scene story '_mg'
        assert a.frames, '--blend needs --frames a-b'
        a.scene = re.sub(r'[^a-z0-9]+', '_', os.path.splitext(os.path.basename(a.blend))[0].lower()).strip('_') or 'mg'; a.story = a.story or '_mg'
        bd = os.path.join(ENG, 'stories', a.story, 'scenes', a.scene, 'build'); os.makedirs(bd, exist_ok=True)
        shutil.copy(a.blend, os.path.join(bd, 'scene.blend'))
    if a.res: HQ_PCT = a.res.lower()   # farm_hq.py reads 'WxH' as an absolute size at 100 %
    if a.spp: HQ_SPP = a.spp
    assert a.story, 'story required'
    story, regions = a.story, a.regions.split(','); P = prices()
    now = dt.datetime.now(dt.timezone.utc); rid = f"{story}-{now.strftime('%Y%m%d-%H%M%S')}"
    tmp = tempfile.mkdtemp(prefix='farm_'); T = {}; t0 = time.time()
    rep = dict(id=rid, story=story, scenes=[], frames=0, resolution='1080x1920', samples=128, gpus=0, jobs=[], builds=[], upload_bytes=0,
               download_bytes=0, region_png_bytes={}, start_utc=now.isoformat(), prices_date=P['date'],
               notes='excluded from estimate: boot disk, Artifact Registry cross-region image pull, VM egress of CUDA cache; reconcile shows the gap')
    sdir = os.path.join(ENG, 'stories', story, 'scenes')
    scenes = [a.scene] if a.scene else sorted(d for d in os.listdir(sdir) if os.path.exists(os.path.join(sdir, d, 'build', 'scene.blend')))
    absorb_builds(rep)
    try:
        # 1 pack + upload
        work = {}
        for sc in scenes: work[sc] = pack_upload(story, sc, tmp, rep)
        stills = [int(x) for x in a.stills.split(',')] if a.stills else None
        if stills:
            assert a.scene, '--stills needs --scene'; work = {a.scene: (min(stills), max(stills))}
        elif a.frames:
            assert a.scene, '--frames needs --scene'; work = {a.scene: tuple(int(x) for x in a.frames.split('-'))}
        gs('-m', 'cp', *[os.path.join(ENG, f) for f in ENGINE_FILES], f'gs://{BUCKET}/hq/{story}/engine/')   # one parallel copy
        gs('cp', os.path.join(ENG, 'tools', 'farm_hq.py'), f'gs://{BUCKET}/hq/{story}/engine/farm_hq.py')
        T['upload'] = time.time() - t0; t1 = time.time()
        # 2 render
        # a FRESH output folder per render: the shared 'out/' made a re-render skip every frame (they existed from the last
        # render) and download the OLD video for 0.16 EUR (R148). --resume <render id> continues a run's own folder.
        outbase = (f"stills_{rid[-15:]}" if stills else f"out_{(a.resume or rid)[-15:]}")
        if stills:
            rep['gpus'] = 1; segs = [(a.scene, f, f) for f in stills]
            jn = submit(regions[0], f'hq-{rid[-15:]}', segs, story, outbase, tmp)
            print('submitted', jn.split('/')[-1], regions[0])
            t_stop = time.time() + 3600
            while True:
                time.sleep(20)
                try: d = describe(jn, regions[0])
                except RuntimeError as e: print('  describe failed, retrying:', str(e)[:120]); d = {'state': ''}
                if time.time() > t_stop:
                    gcloud('ai', 'custom-jobs', 'cancel', jn, f'--region={regions[0]}', check=False); raise RuntimeError('stills job timeout')
                print('  ', d['state'])
                if d['state'] in ('JOB_STATE_SUCCEEDED', 'JOB_STATE_FAILED', 'JOB_STATE_CANCELLED'): break
            rep['jobs'].append(job_record(d, regions[0], segs)); assert d['state'] == 'JOB_STATE_SUCCEEDED', d.get('error')
            rep['frames'] = len(stills); rep['scenes'] = [a.scene]
        else:
            rep['gpus'] = a.gpus; rep['scenes'] = scenes; rep['frames'] = sum(b - a_ + 1 for a_, b in work.values())
            farm(story, work, regions, outbase, rep, tmp, rid[-15:])
        T['render'] = time.time() - t1; t2 = time.time()
        job_logs(rep, story, rid)
        # 3 download + assemble
        dl = os.path.join(tmp, 'dl'); os.makedirs(dl)
        run([GC, 'storage', 'cp', '-r', f'gs://{BUCKET}/hq/{story}/{outbase}/*', dl, f'--project={PROJECT}'], timeout=1800)
        pngs = glob.glob(os.path.join(dl, '*', '*.png')); rep['download_bytes'] = sum(os.path.getsize(p) for p in pngs)
        tot_frames = max(len(pngs), 1)
        for j in rep['jobs']:
            n = sum(b - a_ + 1 for _, a_, b in j['segs']); rep['region_png_bytes'][j['region']] = rep['region_png_bytes'].get(j['region'], 0) + n * rep['download_bytes'] / tot_frames
        root = os.path.join(ENG, 'stories', story)
        if stills:
            sd = os.path.join(root, 'hq_stills'); os.makedirs(sd, exist_ok=True)
            for p in pngs: shutil.copy(p, os.path.join(sd, f'{os.path.basename(os.path.dirname(p))}_{os.path.basename(p)}'))
            print('stills ->', sd)
        else:
            # frame numbers may start at 1 or 0 -> use start_number per scene
            parts = []
            for sc in scenes:
                fr = sorted(glob.glob(os.path.join(dl, sc, '*.png')))
                if a.blend or CUTOUT != '-':   # B5 / alpha: keep the PNG frames (16-bit RGBA in alpha mode) for motion graphics
                    kd = os.path.join(sdir, sc, 'frames'); os.makedirs(kd, exist_ok=True)
                    for p_ in fr: shutil.copy(p_, kd)
                first = int(os.path.basename(fr[0])[:4])
                out = os.path.join(sdir, sc, 'hq.mp4')
                run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS), '-start_number', str(first), '-i', os.path.join(dl, sc, '%04d.png'),
                     '-vf', f'scale={OUT_WH}:flags=lanczos', '-c:v', 'libx264', '-crf', '16', '-pix_fmt', 'yuv420p', out], timeout=900); parts.append(out)
                if CUTOUT != '-':   # cutout: keep the alpha for motion graphics (mp4 cannot carry it)
                    run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS), '-start_number', str(first), '-i', os.path.join(dl, sc, '%04d.png'),
                         '-vf', f'scale={OUT_WH}:flags=lanczos', '-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le',
                         os.path.join(sdir, sc, 'hq_alpha.mov')], timeout=900)
            lst = os.path.join(tmp, 'list.txt'); open(lst, 'w').write(''.join(f"file '{p.replace(chr(92), '/')}'\n" for p in parts))
            run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', os.path.join(root, 'hq.mp4')])
            shutil.copy(os.path.join(root, 'hq.mp4'), os.path.join(root, f'hq_{rid}.mp4'))   # keep every render (a re-render overwrote the creator's favourite)
            allp = sorted(glob.glob(os.path.join(dl, '*', '*.png'))); pick = [allp[int(i * (len(allp) - 1) / 15)] for i in range(min(16, len(allp)))]
            run(['ffmpeg', '-y', '-loglevel', 'error', *sum([['-i', p] for p in pick], []), '-filter_complex',
                 f"{''.join(f'[{i}:v]scale=270:480[v{i}];' for i in range(len(pick)))}{''.join(f'[v{i}]' for i in range(len(pick)))}xstack=inputs={len(pick)}:layout="
                 + '|'.join(f"{(i % 8) * 270}_{(i // 8) * 480}" for i in range(len(pick))), os.path.join(root, 'hq_sheet.jpg')])
            print('video ->', os.path.join(root, 'hq.mp4'))
        T['download+assemble'] = time.time() - t2
    except BaseException as e:
        rep['error'] = f'{type(e).__name__}: {e}'[:500]; print('RUN FAILED (cost row is still written):', rep['error']); raise
    finally:
        end = dt.datetime.now(dt.timezone.utc); rep['end_utc'] = end.isoformat(); rep['wall_minutes'] = (time.time() - t0) / 60
        rep['gpu_minutes'] = sum(j['billed_s'] for j in rep['jobs']) / 60; rep['phase_s'] = T
        if not rep['scenes']: rep['scenes'] = scenes
        if not rep['frames']: rep['frames'] = max(len(glob.glob(os.path.join(tmp, 'dl', '*', '*.png'))), 1)
        print('phases (s):', {k: round(v) for k, v in T.items()}, '| job queue s:', [round(j['queue_s']) for j in rep['jobs']])
        for j in rep['jobs']:
            ft = j.get('frame_times', [])
            print(f"  job {j['name'].split('/')[-1]} {j['region']}: {j['state']} billed {j['billed_s']:.0f}s queue {j['queue_s']:.0f}s" + (f", cumulative frame finish times {ft}" if ft else ''))
        finish(rep, P)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
