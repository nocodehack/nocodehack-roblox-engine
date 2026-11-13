"""preset_pieces.py <out.md> - build every rooms.py preset and list the named set pieces (targets for sit/walk/on/look)."""
import sys, re
from pathlib import Path
import bpy
E = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(E))
import rooms, assets, sets
out = sys.argv[sys.argv.index('--') + 1]
lines = ['## Preset pieces (names usable in sit / walk / on / look)', '',
         'Exact names, or for `sit` the start of a name ("chair", "bench", "sofa" = nearest match). `.001` suffixes = more of the same.', '']
for name, p in rooms.PRESETS.items():
    bpy.ops.wm.read_factory_settings(use_empty=True); assets.reset(); rooms.M.clear(); sets.M.clear()
    sets.build({'preset': name})
    names = sorted({re.sub(r'\.\d+$', '', q['name']) for q in assets.PLACED if not q['name'].startswith(('tree', 'lampSquareCeiling', 'flower', 'grass', 'plant_', 'rock_'))})
    w, d = p.get('size', ['?', '?'])
    lines.append(f"- **{name}** ({'outdoor' if p.get('outdoor') else 'room'} {w}x{d} studs): " + ', '.join(f'`{n}`' for n in names))
Path(out).write_text('\n'.join(lines) + '\n', encoding='utf-8'); print('PIECES', len(rooms.PRESETS))
