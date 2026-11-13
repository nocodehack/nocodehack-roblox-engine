"""blender -b shorts/<n>/build/scene.blend -P tools/outdoor_sky_check.py -- <out_prefix> [yaw_deg] : head-height low-angle plates of the sky/backdrop in
all three skies (day/sunset/night), Cycles 16 spp, to eyeball horizon, hills and stars."""
import bpy, sys, math
from pathlib import Path
sys.path.insert(0, str(Path(bpy.data.filepath).resolve().parents[3]))
import look
a = sys.argv[sys.argv.index('--') + 1:]; sc = bpy.context.scene
cam = bpy.data.objects.new('chk', bpy.data.cameras.new('chk')); sc.collection.objects.link(cam)
yaw = math.radians(float(a[1])) if len(a) > 1 else 0
cam.location = (7, -9, 1.5); cam.rotation_euler = (math.radians(88), 0, yaw); cam.data.lens = 24; sc.camera = cam
sc.render.engine = 'CYCLES'; sc.cycles.samples = 16; sc.cycles.device = 'CPU'; sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 540, 960, 100
for o in list(bpy.data.objects):
    if o.type == 'CAMERA' and o is not cam: o.hide_render = True
for kind in ('day', 'sunset', 'night'):
    look._sky(sc, kind); sc.render.filepath = f'{a[0]}_{kind}.png'; bpy.ops.render.render(write_still=True)
