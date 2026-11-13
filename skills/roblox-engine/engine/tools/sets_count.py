"""sets_count.py -- <preset> ... : build each preset in Blender and print how many wall-decor pieces (wd_*) it got, by kind."""
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bpy, sets, assets
for pr in sys.argv[sys.argv.index('--') + 1:]:
    sets.build({'preset': pr})
    wd = [q for q in assets.PLACED if q['name'].startswith('wd_')]
    print('COUNT', pr, len(wd), dict(Counter(q['name'].split('_')[1] for q in wd)), 'solid', sum(q['solid'] for q in wd))
    bpy.ops.wm.read_factory_settings(use_empty=True); assets.reset(); sets.M.clear(); __import__('rooms').M.clear()
