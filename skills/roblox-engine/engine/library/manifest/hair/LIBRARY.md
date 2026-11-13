# Hair library (real Roblox hair accessories)
Use in a story cast: `"hair_style": "lib:<tag>"` (e.g. `lib:goku1`) or `lib:<asset id>`; `"hair": "#hex"` recolours it
(texture shading kept). Pictures: sheet.jpg (front, 3/4, back per hair). QA numbers: ../../trace/_hairqa/qa.txt.

Tags: goku1-4, vegeta1-4, super_saiyan1-4, spiky_anime1, spiky_messy1-2, spiky_tall1, spiky_villain1, side_swept1,
fluffy_fringe1, short_anime1, emo1/2/4, long_straight1/3/4, ponytail1-4, messy_bun1-4, curly2, afro1-4, buzz_cut3-4,
pigtails1-4, wavy1-4.
Known: fluffy_fringe1 and ponytail1 cover the eyes (style); wavy3 covers 44 % of the face.

## Add more hairs
1. `python tools/hair_queue.py "<keyword>" ... --n 4`  (catalog search -> research/hair/studio/queue.txt)
2. Old/Roblox-made items: `python tools/hair_fetch.py id <ID>` (public endpoint). Newer UGC returns HTTP 401 ->
   Studio route: paste tools/hair_batch.luau (IDS = 16 ids) into Roblox Studio via MCP execute_luau (Edit, logged in).
3. `python tools/hair_studio.py collect log`  (reads HAIRJSON lines from the Studio log, takes each id's mesh + texture
   from Studio's own download cache by time window; mesh v1-v7 incl. Draco; KTX2 textures decoded)
4. Rename the new folder to `<id>_<tag>N`, then QA:
   `blender -b --factory-startup --offline-mode -P tools/hair_qa.py -- all`
Colour variants of one item share a mesh -> Studio does not download it twice -> NOMESH (it is a duplicate; skip it).
Placement = Roblox's own: handle = Head.HairAttachment(0,0.6,0) * inverse(handle attachment); MeshPart mesh bbox-centred,
scaled Size/MeshSize; vertices inside the R6 torso are pushed out to its surface (R15-made long hair).
