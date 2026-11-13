"""farm_hq.py - runs INSIDE the cloud Blender container on a built scene.blend: applies the engine's 'hq' tier and renders a
frame range to an output folder.  blender -b scene.blend -P farm_hq.py -- <engine_dir> <out_dir> <f0> <f1> [CUDA|OPTIX]
engine_dir = a copy of the engine code (look.py + its imports) uploaded next to the blend (look.tier needs it)."""
import sys, os, time
import bpy
a = sys.argv[sys.argv.index('--') + 1:]
eng, out, f0, f1 = a[0], a[1], int(a[2]), int(a[3]); dev = a[4] if len(a) > 4 else 'CUDA'
sys.path.insert(0, eng)
import look
sc = bpy.context.scene
look.tier(sc, os.environ.get('FARM_TIER', 'hq'), device=dev)   # farm_run --env FARM_TIER=draft: the flat draft look on the cloud
look.hq_shots(sc)   # R211 camera motion blur off + R224 light shafts hidden in front of the camera (in look.py, shared with mid/preview)
if len(a) > 6:   # fast HQ (farm_run.py HQ_PCT/HQ_SPP); 'WxH' = absolute size (farm_run.py --res)
    if 'x' in a[5]: sc.render.resolution_x, sc.render.resolution_y = (int(v) for v in a[5].split('x')); sc.render.resolution_percentage = 100
    else: sc.render.resolution_percentage = int(a[5])
    sc.cycles.samples = int(a[6])
if len(a) > 7 and a[7] != '-':   # farm_run.py --cutout A,B (no floor shadow) / --alpha (whole cast + shadow catcher)
    print('alpha mode, hidden from camera:', look.alpha_mode(sc, set(a[7].split(',')), shadow=len(a) > 8 and a[8] == 'shadow'), flush=True)
os.makedirs(out, exist_ok=True)
t0 = time.time()
tt = a[9].split(':') if len(a) > 9 and a[9] != '-' else None   # farm_run.py --turntable N:F (orbit N steps at scene frame F)
piv = look.turntable(sc, int(tt[1]), set(a[7].split(',')) if a[7] != '-' else None) if tt else None
for f in range(f0, f1 + 1):
    p = os.path.join(out, f'{f:04d}.png')
    if os.path.exists(p): continue          # resumable (spot preemption)
    if piv: import math; piv.rotation_euler.z = 2 * math.pi * f / int(tt[0]); sc.frame_set(int(tt[1]))
    else: sc.frame_set(f)
    sc.render.filepath = p; bpy.ops.render.render(write_still=True)
    print(f'HQ frame {f} done {time.time() - t0:.0f}s', flush=True)
print(f'HQ chunk {f0}-{f1} done in {time.time() - t0:.0f}s', flush=True)
