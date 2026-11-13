"""Probe a built scene: blender -b shorts/<n>/build/scene.blend -P tools/probe_scene.py -- <frame> <obj> [<obj> ...]
Prints world location (studs), yaw (deg) of each object at the frame, and the active camera."""
import bpy, sys, math
a = sys.argv[sys.argv.index('--') + 1:]
f = int(a[0]); sc = bpy.context.scene; sc.frame_set(f)
for n in a[1:]:
    o = bpy.data.objects[n]; p = o.matrix_world.translation
    print(f'PROBE f{f} {n}: studs ({p.x / .5:.2f}, {p.y / .5:.2f}, {p.z / .5:.2f}) yaw {math.degrees(o.matrix_world.to_euler().z):.0f}')
c = sc.camera; p = c.matrix_world.translation
print(f'PROBE f{f} camera {c.name} studs ({p.x / .5:.2f}, {p.y / .5:.2f}, {p.z / .5:.2f}) lens {c.data.lens:.0f}')
