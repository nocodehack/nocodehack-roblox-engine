"""Extract the 6 authentic R6 part meshes (+ their materials/UVs) from the Aeresei R6 rig into assets/r6_parts.blend.
Run: blender -b "<rig .blend>" --factory-startup -P tools/extract_r6_parts.py   (rig scripts stay disabled)
Prints each part's world size in metres and its origin offset from the bbox centre, so rig.py can fit them to exact studs."""
import bpy, sys
from pathlib import Path
from mathutils import Vector

OUT = Path(__file__).resolve().parent.parent / 'assets' / 'r6_parts.blend'
NAMES = ['Head_MBlocky', 'Torso_MBlocky', 'Left Arm_MBlocky', 'Right Arm_MBlocky', 'Left Leg_MBlocky', 'Right Leg_MBlocky']
bpy.context.view_layer.update()
keep = set()
for n in NAMES:
    o = bpy.data.objects.get(n)
    assert o and o.type == 'MESH', f'missing {n}'
    W = o.matrix_world
    pts = [W @ Vector(c) for c in o.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)]); hi = Vector([max(p[i] for p in pts) for i in range(3)])
    me = o.data.copy(); me.name = 'R6 ' + n.replace('_MBlocky', '')
    me.transform(W)                       # bake world transform, then centre on the bbox
    me.transform(__import__('mathutils').Matrix.Translation(-(lo + hi) / 2))
    keep.add(me)
    mats = [m.name for m in me.materials if m]
    print(f'PART {n}: size {tuple(round(v, 4) for v in (hi - lo))} verts {len(me.vertices)} uv {len(me.uv_layers)} mats {mats}')
bpy.data.libraries.write(str(OUT), keep, fake_user=True)
print('WROTE', OUT)
