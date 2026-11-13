"""Catalog every GLB under a kit folder: size (m) and triangle count.

Run:
  blender -b --factory-startup -P tools/catalog_assets.py -- <kenney folder> <out json>

Writes <out json> (list of dicts) and catalog.md next to it.
Each file is imported into a fresh empty scene (read_factory_settings), so
nothing leaks between models. Import failures are recorded, not fatal.
"""
import bpy
import json
import os
import sys
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
root = os.path.abspath(argv[0])
out_json = os.path.abspath(argv[1])
out_md = os.path.join(os.path.dirname(out_json), "catalog.md")

files = []
for dirpath, _, names in os.walk(root):
    for n in names:
        if n.lower().endswith(".glb"):
            files.append(os.path.join(dirpath, n))
files.sort()


def measure():
    """Return (size_xyz, triangles) over all mesh objects in the scene."""
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    tris = 0
    meshes = 0
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH":
            continue
        meshes += 1
        for corner in ob.bound_box:
            w = ob.matrix_world @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
        tris += sum(max(len(p.vertices) - 2, 0) for p in ob.data.polygons)
    if meshes == 0:
        raise RuntimeError("no mesh objects after import")
    return [round(hi[i] - lo[i], 4) for i in range(3)], tris


results = []
for path in files:
    rel = os.path.relpath(path, root).replace("\\", "/")
    entry = {"kit": rel.split("/")[0], "file": os.path.basename(path), "rel_path": rel}
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)  # clear scene + data
        bpy.ops.import_scene.gltf(filepath=path)
        (sx, sy, sz), tris = measure()
        entry.update(size_x=sx, size_y=sy, size_z=sz, triangles=tris)
    except Exception as e:  # keep going, record the failure
        entry["error"] = f"{type(e).__name__}: {e}"
        print("IMPORT ERROR:", rel, entry["error"])
    results.append(entry)

os.makedirs(os.path.dirname(out_json), exist_ok=True)
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

lines = [
    "# Kenney kit catalog",
    "",
    f"{len(results)} GLB files. Sizes in metres (x, y, z; z is up).",
    "",
]
by_kit = {}
for r in results:
    by_kit.setdefault(r["kit"], []).append(r)
for kit in sorted(by_kit):
    lines += [f"## {kit} ({len(by_kit[kit])})", ""]
    for r in by_kit[kit]:
        name = os.path.splitext(r["file"])[0]
        if "error" in r:
            lines.append(f"- {name}: IMPORT ERROR")
        else:
            lines.append(f"- {name}: {r['size_x']:.2f} x {r['size_y']:.2f} x {r['size_z']:.2f} m")
    lines.append("")
with open(out_md, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

errors = sum(1 for r in results if "error" in r)
print(f"CATALOG DONE: {len(results)} files, {errors} errors -> {out_json}")
