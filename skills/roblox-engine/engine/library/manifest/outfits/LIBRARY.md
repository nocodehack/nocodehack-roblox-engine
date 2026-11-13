# Outfit library (real Roblox classic Shirt / Pants templates)
Use: `import outfits; outfits.apply(char, shirt=outfits.lib('hoodie2','shirt'), pants=outfits.lib('jeans','pants'))`
Story cast key (live): `"outfit": {"shirt": "lib:<tag>", "pants": "lib:<tag>"}`. Tag + number = Nth item of that tag (sorted by asset id); a bare
asset id works too. Pictures: sheet.jpg (front + 3/4 per outfit; shirts over blue pants, pants under a white shirt). Folder = `<id>_<kind>_<slug>/`
with template.png (700x669 thumbnail of the 585x559 template, alpha kept) and meta.json (id, name, kind, tags, template_id).

Shirt tags: anime1-2, armor1-3, casual1-18, chef1-3, costume1-6, denim_jacket1-2, fight1-13, gi1, hawaiian1-3, hoodie1-3, jacket1-9, jersey1, kimono1-3, lab_coat1-3, leather_jacket1-3, ninja1-3, pajamas1-3, pirate1-3, police_uniform1-3, racing1, sailor1-3, school1-6, school_uniform1-3, sport1-2, suit1-7, superhero1-3, tee1-6, turtleneck1-3, tuxedo1-3, uniform1-3, varsity_jacket1-3, work1-6
Pants tags: armor_pants1-2, black_pants1-3, camo_pants1-2, cargo_pants1-3, casual1-20, dress1-7, fight1-3, jeans1-3, khaki1-3, plaid_skirt1-2, ripped_jeans1-3, school1-2, shorts1-3, skirt1-3, sport1-3, suit1-3, suit_pants1-3
Broad tags (casual, fight, costume, jacket, work, school, sport) are mixed bags; narrow ones (hoodie, kimono, tuxedo, ...) are specific.
Dresses/skirts are pants templates (`dress`, `skirt`, `plaid_skirt`). Anime/fight looks: fight, kimono, gi, ninja, armor, anime.
Removed on purpose: team/brand jerseys (Bulls, Lakers, Barcelona, Arsenal, Red Bull, Ferrari) and a Nike pants; legacy templates with printed guide text.

## Add more
1. `python tools/outfit_fetch.py queue shirt "<keyword>" --tag <tag> --n 4` (and `pants`) -> research/outfits/queue.json (public catalog search,
   subcategory ClassicShirts / ClassicPants).
2. Open Roblox Studio (logged in), paste tools/outfit_batch.luau with IDS = the queue ids into the MCP execute_luau (Edit). It only reads the
   template asset id of each item (InsertService:LoadAsset).
3. `python tools/outfit_fetch.py collect` (reads OUTFITJSON lines from the Studio log, fetches each template via the public thumbnails API).
4. `blender -b --factory-startup --offline-mode -P tools/outfit_qa.py` rebuilds sheet.jpg; look for logos / printed guide text and delete those folders.
Why this route: assetdelivery.roblox.com answers HTTP 401 for every classic clothing item (even 2008 ones), Studio's own cache only holds a
72x68 LOD, and the item thumbnail is a render. The thumbnail of the TEMPLATE IMAGE asset (id from Studio) is the real template at 700x669.

## Mapping (outfits.py)
Template regions (585x559, y from top): torso front (231,74,128x128), back (427,74), right (165,74,64x128), left (361,74), top (231,8,128x64),
bottom (231,204); right arm/leg = left half: sides at x 19/85/151/217 (Right, Front, Left, Back; y 355, 64x128), top (217,289), bottom (217,485);
left arm/leg: sides at x 308/374/440/506, top (308,289), bottom (308,485). tests/test_outfits.py renders every face of every part from outside
and checks region id + no mirroring (30/30).

## DBZ (R165, from Creator Store rigs read in Studio; unused template regions cleared: guide text/logos/black bg)
Shirt tags: goku_gi1 (4726830505, from "Dummy [Goku Edition]" 9213234604; orange gi + blue undershirt/sash + kanji, bare-arm-free sleeves), vegeta_armor1-2 (5584916611 from "Vegeta" 8380301490, black-bg template; 6245033312 from "Vegeta" 16991428731, blue bodysuit + white armour + gold trim)
Pants tags: vegeta_armor1-2 (5584922888 from 8380301490; 6245040505 from 16991428731, blue bodysuit legs + white boots)
Pairs: 5584916611+5584922888, 6245033312+6245040505 (best, transparent-bg). goku_gi PANTS: none usable (Dummy Goku pants image is not a template, 700x700; 5670655222 GokuGi is MeshParts, no clothing; 192291165 only had guide-text templates). Use orange via cast pants colour.
Rejected: 26571531/26574411 (Goku 192291165, printed "ROBLOX template" text), Vegeta Model 12543221496 (pink "Don't copy this" watermark), SSG Vegeta 8168031035 (templates not 585:559).
Not QA-rendered on the R6 sheet (outfit_qa.py needs Blender; checked flat template images by eye only).
