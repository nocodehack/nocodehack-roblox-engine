# short.schema.md - field reference for the engine's story files

Every key below is one that the code reads (build.py, story.py, rooms.py, sets.py, look.py, poses.py, faces.py, rig.py, camera.py, assets.py). Keys not listed are ignored.
Check a story in 1 s before building: `python tools/story_lint.py stories/<name>/story.json` (story.py runs it first). How to write stories: WRITER_GUIDE.md.

## 1. Two file types

| File | What it is | Built by |
|---|---|---|
| `short.json` | One scene: `seconds`, `cast`, `set`, `props`, `beats`, `shots` | `build.py <short.json>` (Blender) |
| `story.json` | Shared cast looks + `scenes[]`, each scene becomes a short.json | `story.py <story.json>` |

Model file: `stories/cookie/story.json`.

Render tiers (`--tier`): `draft` Workbench check, `preview` / `mid` = the cloud hq look on your own GPU (50 % + 8 / 32 spp + OIDN, upscaled to 1080x1920, resumable, `--frames a-b` for a part; timings in research/RENDER_TIERS.md), `hq` = cloud farm (tools/farm_run.py).

Minimal `story.json`:
```json
{
  "title": "Demo",
  "fps": 24,
  "cast": [{"name": "Max", "shirt": "#C4281C", "pants": "#1B2A35", "hair": "#7A1212", "face": "smile"}],
  "scenes": [{
    "set": {"preset": "kitchen"},
    "seconds": 4,
    "cast": [{"name": "Max", "at": [-8, -6], "yaw": -40}],
    "beats": [{"t": 0.3, "who": "Max", "pose": "proud"}],
    "shots": [{"t": 0, "kind": "medium", "on": ["Max"]}]
  }]
}
```

Minimal `short.json` (same scene, standalone):
```json
{
  "title": "Demo s01",
  "seconds": 4,
  "set": {"preset": "kitchen"},
  "cast": [{"name": "Max", "at": [-8, -6], "yaw": -40}],
  "props": [{"name": "cup", "kind": "food-kit/cookie", "on": "table", "at": [0, 0]}],
  "beats": [{"t": 0.3, "who": "Max", "pose": "proud"}],
  "shots": [{"t": 0, "kind": "medium", "on": ["Max"]}]
}
```

Story rules (story.py):
- `fps` is top level (default 24). It is copied into every scene.
- A scene takes `set`, `seconds`, `cast`, `props`, `beats`, `shots`, and optionally `look`, `breathe`, `fps`. Every scene key except `cast` is passed straight through.
- Each scene `cast` entry is merged over its looks entry (`{**look, **scene_entry}`), so the name must exist in the story `cast`.

## 2. Units and axes

| Thing | Unit |
|---|---|
| `seconds`, `t`, `until`, `talk`, `shake`, `wiggle_s` | seconds (converted to frames at `fps`) |
| positions (`at`, walk points, `set.size`, dress `at`, `z`) | studs; 1 stud = 0.5 m |
| `yaw`, `turn`, `rot`, `side`, `stride` | degrees |
| `speed` | studs per second |
| `lens` | mm |
| `jump` | studs (see section 6) |

- Room is centred on (0, 0). The camera side is the front, at -Y. Walls: `back` = +Y, `front` = -Y, `left` = -X, `right` = +X.
- Yaw 0 faces -Y (toward the camera). Yaw +90 faces +X, yaw -90 faces -X (from the `yaw_to` formula `atan2(dx, -dy)`).
- Props with `on` use offsets from the surface centre. Props without `on` use world studs.

## 3. set

`set` is one object. If it is missing, the preset is `classroom`.

### Presets (rooms.py PRESETS unless noted)

| preset | kind | size W x D (studs) | notes |
|---|---|---|---|
| `living_room` | interior | 30 x 24 | sofa, coffee table, armchair, tv stand, bookcase, plants |
| `bedroom` | interior | 26 x 22 | bed, nightstand, desk + chair, rug, bear |
| `kitchen` | interior | 26 x 22 | fridge/sink/stove counter row, round `table` + 2 chairs, bar |
| `store` | interior | 32 x 26 | shelves, freezers, `counter` (cash register), fruit display |
| `hallway` | interior | 14 x 32 | bench, plant, bookcases |
| `classroom2` | interior | 30 x 28 | 6 desks + chairs, `teacher desk`, bookcases |
| `street` | exterior | 80 x 70 | grass ground, suburban road, houses, fences, trees; day only |
| `park` | exterior | 70 x 60 | grass, path |
| `wasteland` | exterior | 80 x 70 | sand, rock pillars around a clear ~14-stud fighting circle, mesas on the horizon (fights) |
| `classroom` | sets.py | fixed | the default; own geometry (board, desks). Keys: `board` (text), `notes` (list of wall notes), `desks` (list of `{at:[x,y], main, chair}`, `at` is in classroom model units, not studs; use the default unless needed) |
| `room` | fallback | 28 x 24 | not in PRESETS; empty box, no dress |

### Override keys (any key in `set` overrides the preset; `dress` is appended to the preset's dress list)

| key | default | meaning |
|---|---|---|
| `size` | preset | `[W, D]` studs |
| `height` | 11 | wall height, studs |
| `wall` | preset | wall hex |
| `trim` | `#F3EAD3` | trim hex |
| `floor` | `wood` | `wood`, `checker`, `tile`, `carpet`, `grass`, `asphalt` |
| `floor_color` | floor default | hex |
| `door` | `#8A5A33` | door leaf hex |
| `wall_low` | darker wall | lower wainscot hex |
| `wainscot` | true | two-tone walls + chair rail |
| `windows` | preset | list of `[wall, u, width, height, sill]` (sill default 3) |
| `doors` | preset | list of `[wall, u, width]` (opening height min(H-1.5, 8.5)) |
| `decor` | true | wall paintings |
| `ceiling_lamps` | true | interior ceiling lamps |
| `seed` | 7 interior / 3 exterior | random seed for decor and street dressing |
| `time` | `day` | `day`, `evening`, `night`. Only changes the lighting (look.py). Outdoors, `evening` = `day`; `night` adds street lamps |
| `mood` | `default` | scene light mood (look.py R181): `default`, `warm`, `cool`, `dramatic`, `sunset`, `night`, `spooky`. A cool rim light is on in every mood. Works on rooms.py presets AND imported rbx sets; for the cook20 `classroom` use the story key `"look": "reference:dramatic"` (works for any set as `"auto:dramatic"`). Env `LOOK_MOOD` is the fallback, `LOOK_RIM=0` turns the rim off |
| `outdoor` | false | set by `street` and `park` |
| `park` | false | adds the park path |
| `dress` | (appended) | list of dress entries and row entries (below) |

`windows` and `doors` `wall` values use the same names as the walls above.

### dress entry (single item)

| key | required | meaning |
|---|---|---|
| `asset` | yes | Kenney model: bare stem (`sofa`) or `kit/stem` (`furniture-kit/...`) |
| `at` | yes | `[x, y]` studs |
| `rot` | no (0) | degrees |
| `name` | no | label. Used by `props.on`, `beats.look`, `beats.turn`, `beats.sit`, `shots` (set pieces are only targets for `look`/`turn`/`sit`/`props.on`) |
| `z` | no (0) | elevation, studs |
| `scale` | no (1) | multiplier on the kit scale |
| `solid` | no (true) | false = no collision (rugs, pillows, lamps on tables) |

### row (a run of items along one wall, edge to edge)

```json
{"row": ["kitchenCabinet", {"asset": "kitchenSink", "name": "sink"}], "wall": "back", "start": -4, "gap": 0.05, "z": 0}
```

| key | default | meaning |
|---|---|---|
| `row` | (required) | list of asset strings or dicts (`asset`, `name`, `scale`, `z`, `solid`) |
| `wall` | `back` | `back`, `front`, `left`, `right` |
| `start` | centred | `u`: position along the wall, studs from its centre |
| `gap` | 0.05 | studs between items |
| `z` | 0 | elevation, studs (items may override it) |

- Items use real model widths. The run is clamped to stay inside the wall (0.3 stud margin).
- On `front` the run is mirrored in x: `u` is measured toward -X.

## 4. cast

| key | default | meaning |
|---|---|---|
| `name` | (required) | unique character name |
| `at` | `[0, 0]` | `[x, y]` studs on the floor |
| `yaw` | 0 | degrees (0 faces the camera) |
| `face` | `smile` | starting expression (see face kinds) |
| `face_family` | from the faces | `drawn` (the built-in kinds), `classic` (thin-line / dot-eyed Roblox library faces) or `bigeye` (library faces with outlined eyes: Epic Face, Anime Surprise...). ONE family per character for the whole Short: every face the story, the auto acting or a fight gives the character is drawn in it (same emotion; a near one when the family has none). Omitted = the family of the cast `face`, else of the character's first family-specific beat `face` (built-in kind or `lib:`), else `drawn`; story.py decides it once over all scenes |
| `shirt` | `#C4281C` | hex |
| `pants` | `#1B2A35` | hex |
| `skin` | `#F5CD30` | hex |
| `hair` | `#5A3A22` | hex |
| `hair_style` | `spiky` | `spiky`, `short`, `long`, `ponytail`, `bun`, `none`, or a REAL Roblox hair `lib:<tag or id>` e.g. `lib:goku1`, `lib:vegeta2`, `lib:afro1` (list + pictures: assets/hair/LIBRARY.md, assets/hair/sheet.jpg). `hair` colour recolours it. |
| `face_marks` | none | list of scars drawn on every face decal the character wears (twins, blinks, both families): `scar_x_cheek_L` (X on the left cheek), `scar_eye_R` (vertical scar over the right eye). Unknown name = a note in log errors, no crash. |
| `outfit` | none | Real Roblox classic clothing: `{"shirt": "lib:<tag>", "pants": "lib:<tag>"}` (either optional), e.g. `{"shirt": "lib:hoodie1", "pants": "lib:jeans1"}`. Tags: assets/outfits/LIBRARY.md, pictures assets/outfits/sheet.jpg (school_uniform, suit, hoodie, gi, kimono, armor, dress, plaid_skirt, ...). Transparent parts show `shirt`/`pants` colours. Unknown tag = note + plain colour. |
| (casting) | | Long HANGING hair (pigtails, long_straight, wavy) + one-hand face poses (cover_mouth, facepalm, think) can clip: rigid R6 arms pass through the locks (> 10 cm, gate fails; the engine tries both hands first). Prefer short/bun/ponytail hair for characters who touch their face. |

- The first `cast` entry of a scene is the **hero**: the cut-jump check uses its head.
- Face kinds (the `drawn` family): `smile, grin, o, worry, sheepish, blink, neutral, angry, sad, smug, scream, joy, cry, scared, confused, disgust, laugh`.
- Every drawn kind except `blink` has a talk twin `<kind>_talk` (open mouth; `o`/`scream`/`laugh` half close) and a blink twin `<kind>_shut` (eyes closed, same brows and mouth). Both are valid `face` values.
- Emotion words (`happy, joy, laugh, smug, neutral, sad, cry, angry, shock, scared, sleepy, sheepish, silly, cool, confused, disgust, love, evil`) and `emo:<emotion>` pick a face of that emotion inside the character's family; `lib:<slug>` of another family becomes the same emotion in the character's family (note in the log).

## 5. props

| key | default | meaning |
|---|---|---|
| `name` | (required) | label; used by `grab`, `give`, `walk`, `look`, `shots.on` |
| `kind` | `box` | built-in or Kenney model (below) |
| `on` | none | set-piece name (dress `name`), e.g. `table`, `counter`, `coffee table`. `desk:i` works only on the classroom preset |
| `at` | `[0, 0]` | with `on`: `[dx, dy]` studs from the surface centre. Without `on`: `[x, y]` world studs |
| `z` | 0 | height in studs; used only when `on` is absent |
| `rot` | 0 | degrees |
| `held_by` | none | cast name: the prop starts in that character's hand (carry pose at t=0) |
| `hand` | `R` | `R` or `L`, with `held_by` |
| `until` | end | seconds: when the held prop is released (dropped unless handed over) |

**kind:**
- Built-in: `box` (default), `book`, `phone`, `ball`, `cake`.
- Any Kenney model: `kit/name` (e.g. `food-kit/cookie`, `food-kit/pizza-box`) or a bare stem (`laptop`). Props are holdable copies, not obstacles, and are scaled to at most 0.8 m.
- Kit names with scale factors (assets.py KIT_SCALE): furniture-kit, building-kit, car-kit, city-kit-suburban, city-kit-commercial, city-kit-roads, nature-kit, retro-urban-kit, mini-shop, food-kit.

## 6. beats

Each beat: `t` (seconds, required), `who` (cast name, required). Beats run in time order. Within one beat the keys run in this order: `walk`, `sit`, `stand`, `fall`/`get_up`, `give`, `throw`, `turn`, `pose`, `jump`, `wiggle`, `face`, `talk`, `look`, `grab`.

| key | value | what it does |
|---|---|---|
| `walk` | a prop or cast name, or a list of elements | Each element: a prop name (stand where the hand reaches it), a cast name (stop 3 studs short, facing them), or `[x, y]` studs. Wrap points in a list: `[[4, -3]]`. a set-piece name (`"fridge"`, `"sofa"`: stop 1.5 studs in front of its nearest side, facing it) |
| `speed` | studs/s, default 9.5 | `>= 10` switches to the run cycle |
| `run` | bool | forces the run cycle |
| `stride` | degrees, default 30 | walk stride |
| `hand` | `R`/`L` | hand for a prop-goal walk (default: the later grab's hand) |
| `sit` | seat piece name, or a word (`chair`, `bench`, `sofa`) | routes to the seat front, then sits. A word picks the nearest piece whose name starts with it |
| `stand` | true | stands up from the last `sit` |
| `fall` | `back` (default, any truthy), `forward` | tips over from the feet over ~0.5 s |
| `get_up` | true | reverses the last fall |
| `give` | `{prop, to, hand?}` | giver must hold `prop`. Hands meet between them. If > 3.4 studs away, the giver walks up first. `hand` = taker's hand (default: nearer hand) |
| `throw` | `{prop, to, catch?, ...}` | throws a prop the character HOLDS (see "throw" below). `to` = a cast name, `[x, y]` studs, a set-piece name or another prop |
| `turn` | degrees (number), or a name (cast, prop, set piece) | turns over `move` frames before `t` |
| `pose` | LIB name, or a channel dict | see pose list below |
| `jump` | height in studs (true = 0.9) | squash-and-stretch hop |
| `wiggle` | channel: `R`, `L`, `legR`, `legL`, `head`, `body` | oscillates that channel (waves) |
| `wiggle_s` | seconds, default 0.8 | wiggle length |
| `anim` | slug in assets/anims (`dance2`, `wave`, `cheer`, `point`, `laugh`, `shrug`, `salute`, `cower`, ... see assets/anims/LIBRARY.md) | plays Roblox's own R6 animation at `t` (anims.py). `loop` = seconds to keep repeating it (omit = once), `anim_speed` (default 1), `anim_skip` = channels to leave alone, e.g. `["legR","legL"]` while walking; legs are skipped automatically while seated |
| `face` | face kind | expression, set 2 frames before `t`, holds until the next `face` |
| `talk` | seconds | mouth flaps on the current talkable expression (base must be talkable). Gestures unless `gesture: false` |
| `gesture` | bool, default true | talk hand gestures: each line plays its own run from the talk bank (`poses.TALK`), picked by the line's mood (`face` + `say`: `!`/angry = jabs, `?` = half shrug, sad/worry = small, smug/grin = dismissive), never the same as the line before. Compact when seated or crowded; an arm that carries a prop keeps carrying |
| `look` | cast, prop or set-piece name | head aims at it; `track: true` follows a moving target |
| `grab` | `{prop, hand?, until?}` | `prop` (required), `hand` (default `R`), `until` = seconds the prop is released |
| `move` | frames, default 4 | transition length for `pose`, `turn`, `look` |
| `attack` | `{move, target}` | FIGHT. `move` = `punch_R`, `punch_L`, `kick_R`, `uppercut_R`; the fist/foot CONTACTS the target (head; torso for kicks) exactly at `t` (wind-up starts 0.55 s earlier). The attacker twists into the strike, steps in with planted steps if needed (must start within 6.6 studs; 1 stud per 0.17 s, so a run-in longer than 2 studs starts before the wind-up and cuts short whatever walk the attacker was still doing), then steps back to guard distance (3.6 studs). A target hit mid-walk stops walking. The target reacts automatically (hit pose, small push, face) + impact flash + camera shake |
| `attack` extras | `blocked: true` | the defender stops the strike with ONE raised palm (`catch`: `R`/`L`, default the same hand every time): no flinch, no push, face kept, small white flash, no camera shake. Three in a row 0.6 s apart work |
| `attack` extras | `no_look: true` | the attacker's head keeps its heading (face stays on its look target / the camera) while the body turns into a short backhand swat |
| `attack` move | `tap_R` | flat-hand tap on the face (upper chest if the head cannot be reached), tiny wind-up, small recoil, no push; follow with a `knockback` + `pose: curl` for a one-tap KO |
| `block` | true | guard pose at `t` |
| `dodge` | `back`, `R`, `L` | 1.5-stud dodge reached at `t`, returns over 8 frames |
| `knockback` | `{from, distance: 8, height: 2}` | launched away from `from` (a cast name), lands on the back (+ dust). `get_up` afterwards works. The landing never touches another actor (standing or lying) or a set piece: the blast is turned or shortened |
| `knockback` extras | `to: [x, y]`, `pose: "curl"`, `side: R/L` | `to` = the spot (studs) the root lands on (overrides `distance`); `pose: curl` = lands lying on its side, curled, face down, in a bigger crater (radius 2.6), the "defeated in a crater" meme; `get_up` rolls it back and stands up |
| `down` | `{pose: "curl", crater: true, side, yaw}` | at `t` (use 0) the character is already lying curled over its `at`, crater already there; auto acting, gaze and `look` leave it alone until `get_up` |
| `fly` | `{to, height: 4, s: 1.0}` | `to` = list of `[x, y]` studs, or a cast name (stops at guard distance). Follow with `land: true`. From the ground it pops straight up over 2 frames first (feet clear, then legs swing and body turns): no takeoff foot slide at any speed |
| `land` | true or `{crater: true}` | descends to the ground with a bounce (+ dust); `crater` adds a crater and a thick smoke column that hangs ~1 s |
| `power_up` | seconds | brace pose + flame aura (`aura_color`, default gold) |
| `aura` | seconds or `{s, color}` | aura only |
| `beam` | `{to, charge: 0.6, s: 1.0, color, hand: R}` | energy ball charges in the hand for `charge` s BEFORE `t` (the ball grows the whole time, a 2.8 s charge is fine), beam fires at `t` for `s` s at the target's chest (+ flash, sparkles). Add a `knockback` beat on the target ~0.15 s later |
| `beam` extras | `hands: "both"` | two-hand wave: both arms pulled to one hip during the charge, ball between the hands, both thrust forward at `t` |
| `beam` extras | `deflect: {after: 0.5, to: [x, y, z], hand: R}` | the target holds the beam on one raised palm (no flinch, no knockback), after `after` s flicks it: the beam bends at his hand and shoots to the world point `to` (studs, default up into the sky) until the beam ends, flash at the hand. Needs `0 < after < s - 0.1` |
| `exclaim` | true | "!" over the head |

**Fight example** (preset `wasteland` is a battle plateau): `{"t": 1.5, "who": "Goku", "attack": {"move": "punch_R", "target": "Vegeta"}}`, then `{"t": 3.8, "who": "Vegeta", "knockback": {"from": "Goku", "distance": 9, "height": 3}}`. Leave ~0.6 s between one fighter's attacks. **Fight shots:** automatic attack, dodge and knockback coverage uses a wider two-shot of both fighters (`wide`, 35 mm), keeping room for the action. Authored shots keep their requested size and angle. Full test story: stories/saiyan/story.json.

### throw (L1 movement, build.py + release.py)

`{"t": 2.0, "who": "Kai", "throw": {"prop": "ball", "to": "Lou", "catch": true}}`

The thrower must hold `prop` (a `grab` earlier, or `held_by`). Both turn to face each other with planted steps, the arm winds up
for 8 frames and the prop leaves the hand **at the arm's swing** (release frame = `t` + 8 frames, later if a turn or an earlier
move is still running: later beats are retimed). The flight is a real ballistic arc (gravity 9.81 m/s2, about 6.5 m/s, 0.42-1.3 s).

| key | default | meaning |
|---|---|---|
| `prop` | (required) | the held prop |
| `to` | (required) | cast name, `[x, y]` studs (floor point or the top of the piece under it), a set-piece name (lands on its top) or a prop name (the target) |
| `catch` | true | `to` = a character: true = they catch it (the hand meets the prop, then carries it; they can `throw` it on), false = it HITS their chest and drops in front of them |
| `catch_hand` | a free hand, right first | `R` / `L` |
| `miss` | false | `to` = a character: true = they reach, the prop flies past the hand (`"miss": "L"` = past the other side) and lands on the floor ~2.6 studs behind them, one bounce |
| `react` | recoil | for a hit (`catch: false`): the target plays `recoil` + face `o`; `"react": "fall"` = falls on the back (follow with `get_up`). A `pose`/`fall`/`anim` beat the story gives the target within 0.3 s of the hit replaces it |
| `style` | auto | `under` (toss) or `over` (overhand). Auto = `over` for hits and for more than 14 studs |

- A prop target (`"to": "crate"`) is knocked off its support in the throw direction, tips over and stays lying; the thrown prop drops under the hit.
- An uncaught prop bounces once and rests; it can be picked up again (`walk` + `grab`).
- A catcher with both hands full (or lying on the floor) is hit instead (note). A thrower lying on the floor = error.
- Not checked: furniture in the flight path (the arc usually clears it; aim over open floor).
- report.json `throws` lists every throw (`f_release`, `f_end`, `kind`); LEVEL 1 checks them (`l1_move.py`: arc physics, no prop inside a body or arm, catch contact, rests at the end).

**pose: LIB names (50):**
`idle, proud, point_R, point_L, shrug, cheer, fist_pump_R, facepalm_R, facepalm_L, shock, cower, think_R, think_L, wave_R, talk_a, talk_b, angry, sad, hands_up, cover_mouth_R, cover_mouth_L, hands_head, reach_R, reach_L, carry_R, carry_L, hold_out, arms_crossed, look_down, look_up, lean_in, kick_R, recoil, gloat, slump, curious, stand_a, stand_b, stand_c, explain_R, open_palms, insist_R, both_down, count_R, dismiss_R, plead, ask, explain_s, ask_s, both_s`

Pose library v2: no pose is symmetric (torso lean + twist, countered head, one arm acts while the other balances). `recoil` = pulled back with hands half up, `gloat` = chest out and chin up, `slump` = defeated, `curious` = head cocked and leaning in, `stand_a/b/c` = relaxed standing stances, `explain_R` .. `both_s` = the talk gestures (usable as poses too). Timing of every pose: anticipation, overshoot, a small rebound, settle; the chest leads by a frame and the head trails by a frame.

**pose: contact poses (the hand is solved onto the face, arm's length):** `facepalm_R`, `facepalm_L`, `think_R`, `think_L`, `cover_mouth_R`, `cover_mouth_L`, `hands_head`.

**pose: channel dict (instead of a name):**
- `R`, `L`: `[raise, out]` degrees
- `legR`, `legL`: `[raise, out]` degrees
- `head`: `[down, left, roll]`
- `body`: `[fwd, twist, lean]` (omitted = computed from arm pose)
- Omitted channels stay neutral. Any other name raises a KeyError.

**Automatic acting (on by default; story or scene key `auto_acting: false` turns it off):** the engine adds acting the story did not write, only while a character has no beat of its own. Start stance (nobody opens a scene standing square), listener reactions (shouted at = cower or recoil, a joke = laugh, a question = shrug or a curious lean, else a nod; a plain-faced listener also picks up the speaker's mood), emotion silhouettes (a beat that only sets a strong `face` gets a matching body pose, a different one each time), arms down into a stance after a spoken line, a stance change every ~2.5 s of standing idle, a small chest shift when seated, and a 5-9 degree head tilt on every `look`. A character carrying a prop in one hand acts with the free side. Write an explicit `pose` when a beat needs a specific body: explicit beats always win.

**face kinds:** see section 4.

## 7. shots

| key | default | meaning |
|---|---|---|
| `t` | (required) | shot start, seconds. Ends at the next shot or the scene end |
| `kind` | `medium` | `close` (1.3 m frame), `medium` (2.7 m), `full` (4.2 m), `wide` (6.5 m), `insert` (0.9 m) |
| `on` | first cast | cast or prop names; **first = focus**. Set-piece names are not accepted |
| `lens` | 50 | mm |
| `track` | false | follows a moving head |
| `hold` | false | never auto-split (see the rhythm splitter) |
| `angle` | auto | `low` (from the ground, looking up), `high` (clearly looking down) or `top` (top-down); omitted = chosen by the editor pass (emotion, falls, variety). An authored angle that no camera can read falls back to its mild version |
| `side` | 0 | degrees around the subject; + = to the subject's left |
| `push` | auto | fraction of the dolly toward the aim. Auto = 0.4 % per frame, capped at 18 %; 0 when the subject moves |
| `shake` | none | list of seconds where the camera shakes |
| `shake_amp` | 0.05 | shake amplitude |
| `profile` | auto | `true` = side-on two-shot: the lens looks ACROSS the line between the two subjects from the audience side (-Y), faces in profile (report-only). Automatic for fights (below); `false` keeps the front view |
| `front` | false | the lens stays within 30 degrees of the front of the subjects (cast playing to the camera) |
| `frame` | by `kind` | frame HEIGHT in metres. With `angle: top` it is a true straight-down view (pitch 86). `"auto"` (characters only) = fitted to the whole lying body or bodies + crater |

You normally write only `t`, `kind`, `on` (and `hold` where a shot must not be cut). The engine steers the rest (cam2, 2026-11-10; every rule yields to an authored key):

- **Fights from the side.** A two-shot of two fighters whose time span holds an `attack` (also `flurry`, `blocked`), `beam`, `knockback` or `dodge` beat between them is filmed side-on (`profile`), your size and lens kept. The engine's own pieces around a fight beat become a side-on two-shot too: `full` when the fighters are within 5 studs, `wide` beyond. When the gap closes a lot inside such a shot (a dash-in) the shot is cut at the arrival onto a tighter two-shot. Two fight two-shots in a row that would be the same side-on set-up at the same size are shot as ONE shot (a cut between them would be a jump cut; note). If no side-on camera reads both fighters, the shot is filmed from the front as written (note). A fight two-shot is not rhythm-split and gets no reaction cut-ins. Keys that switch the rule off for a shot: `profile`, `side`, `front`, `angle`, `ots`, `track`, `move`, `frame`; `hold` stops the dash-in cut. Scene switch `fights: false`.
- **A landing is seen from straight above.** After a `knockback` or `fall`, once the body has landed (measured; never earlier) and if it stays down for a second, the cut goes to a straight-down view of the whole body + its crater for 1.0-2.0 s; another body lying within 8 studs (also one lying from the scene start, `down`) joins the frame. Camera spots with a set piece between the lens and the body are rejected (other azimuths are tried; if none is clear the shot is not used, with a note). The shot covering the landing must not be `hold`, a top view or a follow shot. If the next cut comes less than 1.0 s after the landing, that cut moves later (note). Scene switch `falls: false`.
- **A close-up holds the face on every frame.** The head must stay inside the 9:16 frame and the face centre above the caption zone (38 % from the bottom; reported as `<name> safe~`, 1.0 = every frame of the moved camera). If the push-in or a pose change breaks it, the engine drops the push, then pans with the head; if the face still leaves, the shot becomes a `medium` (note).
- **A speaker in profile gets a 3/4 front view.** A `close` / `medium` single on a character whose face is sideways to the audience (talking to someone beside them) is shot from the audience side, 5-75 degrees off the face, never from behind and never through the listener. `side` or `front` wins.
- **No body slab.** In a single, another actor's arm or body covering more than 25 % of the frame (`other~`) is treated like a furniture slab: every camera round is tried before such a camera is accepted, and an engine-made piece with one goes back to the authored shot.
- **Notes say what happened.** Whenever the engine overrides or falls back on an authored shot, `notes` in report.json says so in plain words, e.g. `S05 (close on Goku at 6.3s): the face leaves the frame or drops into the caption zone on 40 % of the frames (the character moves) -> shot as a medium`, or `S03 medium at 2.6s on Yamcha: kept as written, but Yamcha's face is hidden or turned away from every camera position`.

The splitter and the editor pass write `auto: true` on their own shots. Authors do not set it.

Scene-level switches (default true; set false in the scene to switch one editor rule off): `establish`, `inserts`, `reactions`, `pitch`, `ecu`, `fights`, `falls`.

### 7b. camera (camera mode = the reel style of a scene)

Scene key (or story key: then every scene uses it; a scene's own `camera` wins): `"camera": {"mode": "<mode>", ...options}`, or just `"camera": "<mode>"`. Omitted = `story_cuts`. `camera.mode_shots` writes the shot list the style needs; the scene switches the mode turns off can be turned back on in the scene.

| mode | what you get | shots you write | editor rules |
|---|---|---|---|
| `story_cuts` (default) | the normal grammar: your shots, split to ~1.6 s pieces, establishing wide, inserts, reaction close-ups, pitch | all of them (section 7) | all on |
| `follow_oneshot` | ONE travelling camera in front of the hero for the whole scene, zero cuts. It stands at the shot-size distance off the hero's (smoothed) face, steps aside for walls, furniture and people, and never lets the face go | none (ignored) | all off |
| `ots_dialogue` | over-the-shoulder shot / reverse shot: one `medium` per speaker change, camera behind the listener's shoulder, all on ONE side of the pair (180-degree rule) | none: built from the `talk` beats (partner = the beat's `look`, else the previous speaker). Or write your own two-character `medium`/`close` shots: they get `ots: true` | all off |
| `static_wide` | one locked-off sitcom wide of the cast (handheld drift only), zero cuts. Stage the actors to it: faces toward yaw 0, entrances inside the frame | none | all off |
| `topdown_reveal` | your shots, then a top-down wide on whoever falls (`fall` / `knockback`), from 0.45 s after the fall to the scene end, slowly craning up | the shots before the reveal (default: one medium on the hero) | `ecu` off |
| `punch_in` | your shots, plus a crash zoom on the punchline face: a shot on that character that starts 1.8x wide 1 s before the beat and snaps to a close-up in 4 frames | all of them | `ecu` off |
| `chase_track` | one travelling shot of a running pair (hero + `with`), the camera ahead of them and 40 degrees to the side, zero cuts | none | all off |
| `two_shot_react` | a two-shot of hero + `with` as the master, a 1.2 s close-up on every strong `face` beat (shock, scream, joy, angry, laugh, sad...), then back to the two-shot. Stage the pair side by side facing yaw 0 | none | all off |

Options (all optional):

| key | used by | meaning |
|---|---|---|
| `hero` | all | the character the mode is about (default: first cast) |
| `with` | `chase_track`, `two_shot_react`, `ots_dialogue` | the partner (default: second cast) |
| `on` | `static_wide`, `topdown_reveal` | subject list (default: the first 4 cast / the faller) |
| `at` | `topdown_reveal`, `punch_in` | seconds: when the reveal starts / which beat is the punchline (default: 0.45 s after the first fall / the last strong face of the second half) |
| `kind` | `follow_oneshot` (`medium`), `chase_track` (`full`), `topdown_reveal` (`wide`), `two_shot_react`, `ots_dialogue` (`medium`) | shot size |
| `side`, `lens` | the mode's own shot | as in section 7 (`chase_track` side default 40) |

Rules of thumb: a follow / chase hero should walk toward open space (the camera travels ahead of the face: a hero who turns his back on the room gets a camera that swings round at 108 deg/s). `L1` camera checks (`l1_cam.py`, report.json `L1.checks.cam.*`): `faces` (the focus face reads on >= 75 % of every shot and is never lost > 10 frames), `geometry`, `empty_frames`, `tilt`, `jump_cuts`, `mode` (zero cuts, cut rhythm 1.0-2.2 s median, OTS geometry + one side of the line, zoom >= 1.4x on the punchline...).

Engine rule added with the modes (all modes): a `fall` that starts inside a shot on the faller moves the cut onto the fall, and a top-down camera is only used once the body is on the ground for at least half of the shot.

## 8. What the engine does automatically

- **Approach + lean** (`approach_spot`): for a prop goal, it finds a stance so the rigid arm lands on the prop rim at arm's length. It tries 0, 10, 20 and 30 degrees of forward hip lean, keeps the body footprint off furniture and other characters, and picks the spot nearest the walker.
- **Routing** (`plan_path`): every walk leg goes around solid set pieces, walls and other characters (0.5-stud grid A*, then line-of-sight smoothing). Logged as "routed around obstacles".
- **Prop slide**: if a prop has no reachable spot, it slides up to 4 studs toward the walker, staying on its support. Logged as a note.
- **Retiming**: a grab that waits for the approach pushes later beats, later shots and `seconds` back by the wait. The grab's `until` moves with it. Logged as a note.
- **Grab fallback**: if the arm cannot reach, the character walks to the nearest clear spot, then grabs.
- **Drops** (`drop_prop`): a prop released without a hand-off falls straight down onto the highest support under it, turns upright, bounces once (12 % height), and rests. A release in the last 0.5 s keeps the prop held.
- **Carry lift**: a pickup lifts the prop to carry height 7 frames after contact, unless a pose beat follows within 0.5 s.
- **Walk weight and shuffle**: walks get chest counter-rotation. Walks under 1.5 studs use a shuffle instead of the stride solver.
- **Relaxed holds**: a raised arm held > 1.2 s eases about 22 % toward rest.
- **Editor pass** (`camera.grammar`, R213; runs on authored shots and rhythm pieces alike; authored shots keep subject, size and time):
  - *Establishing wide*: every scene opens on a high wide. An authored opening `wide` gets `angle: high`; otherwise a 0.9 s high wide of the cast is put before the first shot (dropped again, with a note, if no camera reads it).
  - *Story-object insert*: a resting prop that is picked up (`grab`; shown during the reach, before the contact) or looked at (`look`) gets its own ~0.8 s `insert`, cut into the shot covering that moment. Once per prop, two per scene. An insert no camera reads falls back to a medium on the holder or to the authored shot (note).
  - *Reaction close-up*: in a `medium`/`full`/`wide` shot of >= 1.3 s, a strong `face` beat (shock, scream, scared, cry, angry, laugh, evil, joy, sad, worry...) of someone it shows cuts in to a `close` on that face. If instead someone NOT in the shot talks or poses (shot >= 1.6 s), the shot cuts away to them.
  - *Pitch* (when `angle` is omitted): a `fall` inside the shot -> `top`; focus on the ground (fall, knockback, get-up) or sad / cower -> `high`; proud / cheer / angry / shock / fist_pump_R / hands_up / facepalm poses, or an angry / evil / smug / scream face (singles) -> `low`; then at least one character shot in three gets `low`/`high` alternately. Engine-chosen pitches fall back (opposite pitch, mild pitch, eye level) when furniture blocks them.
  - No piece is shorter than 0.5 s.
- **Camera preferences** (never gates; reported with `~` in `visibility`): `eyes~` = both eyes visible with the character's own hair counted as an occluder (close/medium singles), `fg~` = set geometry in the lens's face (void), `fgb~` = furniture in front of the subject (wanted <= 30 % of the frame), `framed~` = head + hair inside the frame, `bg~` = void seen behind an open-sided set (wanted <= 12 %), `other~` = another actor's body across a single (wanted <= 25 %), `safe~` = share of frames with the head in frame and the face above the caption zone (close-ups: wanted 1.0). A shot with a slab or void (`fg~` > 0.1, `fgb~` > 0.3, `bg~` > 0.12) searches every camera round and keeps the least-flawed passing camera; an automatic establishing wide with one is dropped; a two-shot with one tries a single on the focus.
- **Inserts**: only for props that REST on something (a prop already in a hand never reads at insert size: the engine shows it with its holder). The frame is at least 2.2x the prop's largest side. A prop placed by `at` under a set surface is lifted onto it (note).
- **Rhythm splitter**: a shot longer than 2.2 s (unless `hold`, or `track` with length <= 3.0) is split into pieces of about 1.6 s. Pieces alternate size on the focus (wide <-> medium, full <-> close, medium <-> close), lens 50.
- **Gaze**: a walker looks forward at the start and at its goal on arrival. Heads otherwise follow `look`.
- **Blinks**: automatic blinks every ~78 frames with the face's own `_shut` twin, skipped during `joy`, `laugh`, `blink` (closed eyes).
- **Idle**: breathing on every character (`breathe`, default true), spring-follow for hair.
- **Depenetration**: arms are pushed out of props, bodies and set pieces. Contact-pose head grazes up to 12 cm are allowed.
- **Shot framing**: the camera picks the best of 15 candidate angles by face visibility and clear view, stays inside room bounds (dolly in, widen the lens), and keys the push-in. A focus lying face-down is reported only (`~`).

### REPORT line

Printed by build.py (one per scene; story.py prints `sNN REPORT ...` and `STORY PASS|FAIL`):

`REPORT PASS | FAIL <reasons> | hits N worst Xcm | slide Ycm | cuts OK | build Ns | render Ns | <video>`

Gates that cause FAIL:
- any `errors` entry (no clear spot, grab/give/walk/sit failures, hands cannot meet)
- penetration depth > 2.0 cm (`depth`)
- a walk slide > 2.0 cm (`slide`)
- jump cuts (angle < 30 deg and size ratio < 1.4)
- hidden focus: visibility below threshold. Close shots: 0.6 for the face, 0.35 for anything else. Other shots: 0.3 for a head mesh when its face is also measured, 0.5 for everything else. Non-focus heads (`~`) are not gated.

`notes` (retimes, routing, slides, lean/contact fallbacks) are informational and do not fail the scene.


## Presets added 2026-11-09 and clarifications (from a blind-writer test)
- Presets: `school_hallway` (lockers both sides), `bathroom`, `office`, `forest` (clearing + campfire), `city` (downtown), besides
  living_room, bedroom, kitchen, store, hallway, classroom, classroom2, street, park, room. Any preset + `"time": "night"`.
- `dress` also accepts `{"lockers": n, "wall": "left|right|back|front", "start": u, "color": "#hex", "name": "..."}`.
- `shots[].on` may name a prop (e.g. an `insert` on `"phone"`); the camera tracks a moving prop.
- Two characters more than 8 studs apart in one shot become a single on the first name (add `"keep_two": true` to force).
- Unknown pose/face/hair names never crash: they are reported in the REPORT line and replaced by a default.

## Preset pieces (names usable in sit / walk / on / look)

Exact names, or for `sit` the start of a name ("chair", "bench", "sofa" = nearest match). `.001` suffixes = more of the same.

- **living_room** (room 30x24 studs): `armchair`, `bookcase`, `bookcaseOpen`, `coffee table`, `lampRoundFloor`, `lampRoundTable`, `pillow`, `pillowBlue`, `plantSmall1`, `pottedPlant`, `rugRectangle`, `side table`, `sofa`, `speaker`, `tv`, `tv stand`
- **bedroom** (room 26x22 studs): `bear`, `bed`, `bookcaseClosedWide`, `cardboardBoxClosed`, `coatRackStanding`, `computerScreen`, `desk`, `desk chair`, `lampRoundTable`, `nightstand`, `rugRound`, `trashcan`
- **kitchen** (room 26x22 studs): `chair`, `counter`, `fridge`, `kitchenBar`, `kitchenBarEnd`, `kitchenCabinet`, `kitchenCabinetDrawer`, `kitchenCabinetUpper`, `kitchenCabinetUpperDouble`, `pottedPlant`, `rugRound`, `sink`, `stove`, `table`, `trashcan`
- **store** (room 32x26 studs): `counter`, `display-bread`, `freezers-standing`, `fruit`, `shelf A`, `shelf B`, `shelf-bags`, `shelf-boxes`, `shelf-end`, `shopping-basket`, `shopping-cart`
- **hallway** (room 14x32 studs): `bench`, `bookcaseClosedDoors`, `pottedPlant`, `trashcan`
- **classroom2** (room 30x28 studs): `bookcaseClosed`, `bookcaseOpenLow`, `chairDesk`, `desk`, `pottedPlant`, `teacher desk`, `trashcan`
- **school_hallway** (room 16x40 studs): `bench`, `lockers left`, `lockers right`, `trashcan`
- **bathroom** (room 20x18 studs): `bathroomMirror`, `bathroomSink`, `cabinet`, `rugRounded`, `toilet`, `trashcan`, `tub`
- **office** (room 30x24 studs): `bookcaseClosedDoors`, `chairDesk`, `computerScreen`, `desk 0`, `desk 1`, `desk 2`, `pottedPlant`, `trashcan`
- **forest** (outdoor 70x60 studs): `campfire`
- **city** (outdoor 80x70 studs): `building-skyscraper-a`, `building-skyscraper-b`, `building-skyscraper-c`, `building-skyscraper-d`, `building-skyscraper-e`, `car 0`, `car 1`, `car 2`, `car 3`, `light-square`, `shop 0`, `shop 1`, `shop 2`, `shop 3`, `shop 4`, `shop 5`, `shop 6`, `shop 7`, `shop 8`, `shop front 0`, `shop front 1`, `shop front 2`, `shop front 3`, `shop front 4`, `shop front 5`
- **street** (outdoor 80x70 studs): `car 0`, `car 1`, `car 2`, `car 3`, `detail-dumpster-closed`, `detail-light-single`, `fence-1x4`, `house 0`, `house 1`, `house 2`, `house 3`, `house 4`, `house 5`, `house 6`, `house front 0`, `house front 1`, `house front 2`, `house front 3`, `house front 4`, `house front 5`
- **park** (outdoor 70x60 studs): `bench -6`, `bench 8`

## Sound pack note (tools/sound_mix.py)

Optional beat key `say` (string): the line a character speaks. Not read by the Blender build. `tools/sound_mix.py` uses it for burned-in captions (2-4 words per card, lower third) and, with `talk` (seconds; default 0.38 s per word), for the blip voice. Optional top-level story key `mood`: `cheery` | `tense` | `chill` (music loop; default cheery, or tense when 2+ `attack` beats).
Run: `python tools/sound_mix.py stories/<name>/story.json [--video hq.mp4] [--out hq_sound.mp4]`.

## Clarifications from blind set 4 (2026-11-09)
- Imported Roblox sets: `"set": {"preset": "rbx", "rbx": "<slug>", "at": [x, y], "rot": deg, "mood": "..."}`; slugs, seats and
  footprints are in assets/rbxsets/LIBRARY.md. Seats are named `<slug>_seat_<k>` and work with `sit`.
- Library faces: cast `face` and beat `face` both accept `lib:<slug>` and `emo:<emotion>`. Every library face talks (its partner
  of the same family, else a twin made from its measured mouth) and blinks (`_shut`). A `lib:` face of another family than the
  character's (`face_family`) is replaced by the same emotion in the character's family.
- Beat key order within one beat: `walk`, `sit`, `stand`, `fall`/`get_up`, `give`, `turn`, `pose`, `jump`, fight keys,
  `wiggle`, `anim`, `face`, `talk`, `look`, `grab`. `anim` after `pose` in the same beat overrides the channels the clip
  moves: use one or the other. `exclaim`, `speed`, `gesture`, `say`, `loop`, `anim_speed`, `anim_skip` are modifiers, not steps.
- `say` = caption + voice text (sound_mix only); mouth flaps come from `talk` (seconds). Give both for a spoken line; about
  0.38 s per word.
- Props: the built-in kinds (box, book, phone, ball, cake) AND any Kenney model (`kit/name` or a bare stem such as `laptop`).
- Outfits: cast key `"outfit": {"shirt": "lib:<tag>", "pants": "lib:<tag>"}` is live (assets/outfits/LIBRARY.md tags).

## Clarifications from blind set 5 (2026-11-09)
- `props[].on` takes any placed piece name, imported rbx pieces included (exact names in assets/rbxsets/LIBRARY.md, e.g.
  `"on": "kitchen_set_Kitchen Island_7"`); the prop rests on that piece's top.
- Props are declared PER SCENE: a prop handed over in scene 1 must be declared again in scene 2 (`"held_by": "<name>"`).
- Two different `mood` keys: `set.mood` = scene LIGHT (warm/cool/dramatic/...); top-level story `mood` = MUSIC loop only
  (cheery/tense/chill, read by tools/sound_mix.py).
- `give` to a SEATED taker is supported: the giver walks up beside the seat and the taker twists toward the giver; a seated GIVER
  out of reach stands up and walks over.
- `talk` length: the mouth flaps for `talk` seconds; about 0.38 s per word of `say` keeps them in sync.

## 9. Format keys (2026-11-13; FORMATS.md says which to use; all optional, a story without them renders as before)

Top-level story keys (`tools/story_lint.py` checks every one; audio/overlay keys are built by `tools/voices.py`, `tools/sound_mix.py`):

| key | value | meaning |
|---|---|---|
| `format` | `skit` `pov` `time_skit` `in_this_world` `narrated_twist` `versus` `choice` `rich_poor` `ranking` `what_if` `text_message` | preset only (captions, narrator, camera, length hint). Lint prints what it applies and warns on what is missing. `what_if` / `text_message` = weak formats |
| `header` | string (<= ~90 chars) | premise text at the top of the frame for the whole Short |
| `captions` | `cards` (default) / `word` | lower-third cards / word-by-word with a coloured key word (`*word*` in the text) |
| `narrator` | `{"voice": "<name or id>"}` or `{"file_dir": "voice/narrator"}` | one narrator voice |
| `voices` | `{"Kid": "<voice>"}` | character voices for `say` lines (names must be in the cast) |
| `cards` | list of `{"type": title/time/label/counter/choice, "text", "scene": N, "t": s-into-scene, "dur": s}`; `choice` has `a` and `b` instead of `text` | timed text cards. The window `t..t+dur` must lie inside the scene |
| `split` | `[[1, 2]]` | scene pairs stacked top/bottom (versus). Same `seconds` in both, a `label` card each |

Scene key `crowd`: `{"n": 1..40, "area": "back" | "sides" | "all", "act": "idle" | "cheer" | "mixed"}`. Background extras (built-in parts, random built-in looks, idle breathing or a cheer/applaud/haha clip), built after the gates and cameras: never gated, never in a camera's way of the cast, never on an authored character's path. Fewer than `n` appear when the room is full (see `report.json` notes).

Beat keys: `narrate` (string, a narrator line starting at that beat; the beat still needs `t` and `who`; characters keep acting, the narrator does not move mouths), `narrate_voice` (recorded file, path from the story folder, must exist), `freeze` (`{"label": "...", "dur": 0.2..3}`, twist freeze-frame).

Camera mode `pov` (section 7b): `"camera": {"mode": "pov", "who": "<name in this scene>", "lens": 28}`. One locked-off first-person camera at `who`'s eye height, 0.4 m in front of the face, looking where its head looks, slight handheld drift, zero cuts. Every other character gets a `look` at the lens at t 0.1 unless it has its own `look`/`turn` in the first 0.5 s. Stage `who` at yaw facing the others (e.g. `"yaw": 180` at -Y facing +Y). Nothing is gated for a pov shot (no face report).
