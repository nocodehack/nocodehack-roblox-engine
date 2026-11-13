# WRITER_GUIDE - writing Shorts for the Roblox-style Blender engine

Written for an AI assistant that has never seen this engine, and for the person next to it. Field reference: `short.schema.md`.

## 1. What the engine is
1. You write ONE file, `stories/<name>/story.json`: the cast (looks), then scenes (set, positions, timed beats, camera shots).
2. `story.py` turns every scene into a Blender build: R6 Roblox-style characters walk, sit, talk, fight and react on their own.
3. Every scene is checked by gates (body overlap, foot slide, hidden faces, jump cuts) and prints one `REPORT PASS|FAIL` line.
4. The draft video is flat-shaded and fast; HQ (Cycles) is rendered on a GPU farm; `tools/sound_mix.py` adds SFX, music, voice, captions.
5. Output: a 1080x1920 vertical Short. You never animate by hand: you direct with JSON.

## 2. Setup
- Blender 5.2, ffmpeg + ffprobe on PATH, Python 3.10+ with `numpy` and `pillow`.
- Blender somewhere else (or Linux/macOS): set `BLENDER=/path/to/blender`.
- HQ farm only: Google Cloud SDK (`GCLOUD`, `GSUTIL` if not in the default Windows place), `ENGINE_GCP_PROJECT`,
  `ENGINE_GCP_BUCKET`, `ENGINE_FARM_DIR` (prices cache). Everything machine-specific is listed in `research/PORTABILITY.md`.
- Run all commands from the engine folder.

## 3. The loop (6 steps)

| # | Step | Command | Typical time |
|---|---|---|---|
| 1 | Write `stories/<name>/story.json` | (editor) | - |
| 2 | Lint | `python tools/story_lint.py stories/<name>/story.json` | ~1 s |
| 3 | Gates only (no video) | `python story.py stories/<name>/story.json --tier none` | 1-2 min per scene, 3 scenes in parallel |
| 4 | Draft video | `python story.py stories/<name>/story.json --tier draft` | 1-2 min per scene (`--only 2` = scene 2 only) |
| 5 | LOOK at `stories/<name>/draft_sheet.jpg` (16 frames) and `draft.mp4` | open the files | 1 min |
| 6 | HQ + post + sound | `python tools/farm_run.py <name> --scene s01 --stills 10,40` (check stills first), then `python tools/farm_run.py <name> --gpus 8`, then any 2D post, then `python tools/sound_mix.py stories/<name>/story.json --video stories/<name>/hq.mp4` | farm: minutes (costs cloud money: ask the person first); locally: hours |

- `story.py` runs the lint first. Errors stop the build (`--no-lint` builds anyway); warnings are printed and the build goes on.
- Fix ERRORs always. Read every WARN: each one is a mistake that already cost a build.
- Only fix what a REPORT or a frame shows. One change, one scene (`--only k`), then the next.

## 4. Minimal story
```json
{
  "title": "Cookie thief",
  "fps": 24,
  "cast": [
    {"name": "Max", "shirt": "#C4281C", "pants": "#1B2A35", "hair": "#7A1212", "hair_style": "lib:spiky_anime1", "face": "smile", "face_family": "drawn"},
    {"name": "Lia", "shirt": "#2E9C9A", "pants": "#1B2A35", "hair": "#E8A33D", "hair_style": "lib:ponytail3", "face": "smile", "face_family": "drawn"}
  ],
  "scenes": [{
    "set": {"preset": "kitchen"},
    "seconds": 6,
    "cast": [{"name": "Max", "at": [-8, -6], "yaw": -40, "face": "smug"}, {"name": "Lia", "at": [8, -3], "yaw": 60}],
    "props": [{"name": "cookie", "kind": "food-kit/cookie", "on": "table", "at": [0.4, 0]}],
    "beats": [
      {"t": 0.3, "who": "Max", "look": "cookie", "face": "smug"},
      {"t": 1.2, "who": "Max", "walk": "cookie", "speed": 6},
      {"t": 3.5, "who": "Max", "grab": {"prop": "cookie", "hand": "R", "until": 5.9}},
      {"t": 4.4, "who": "Lia", "talk": 1.1, "say": "Hey! My cookie!", "face": "angry", "pose": "point_R"}
    ],
    "shots": [{"t": 0, "kind": "medium", "on": ["Max"]}, {"t": 4.3, "kind": "close", "on": ["Lia"]}]
  }]
}
```
Axes: studs (1 stud = 0.5 m), room centred on (0, 0), the camera side is -Y, `yaw` 0 faces the camera, +90 faces +X.
Interior sets are ~26x22 studs (`short.schema.md` section 3 lists every preset, its size and its piece names).

## 5. Cookbook (copied from stories that pass)

**Two people talking, with reactions** (blind2_classroom). Listeners react on their own; give a beat only for a specific reaction.
```json
{"t": 0.8, "who": "Ms Rae", "pose": "point_R", "face": "smile", "talk": 2.0, "say": "Okay, eyes up. Quiet."},
{"t": 5.0, "who": "Ms Rae", "turn": "Max", "face": "angry", "talk": 1.2, "say": "Max! What's that?"},
{"t": 5.6, "who": "Max", "pose": "cower", "face": "worry"},
{"t": 6.2, "who": "Lia", "pose": "shock", "face": "scream"}
```
`talk` = seconds of mouth movement, ~0.38 s per word of `say`. Lines must not overlap.

**Walk in + sit, stand up later** (L1_move_08_sit_stand, living_room).
```json
{"t": 0.3, "who": "Uma", "sit": "sofa"},
{"t": 0.8, "who": "Wes", "walk": [[-4, -9]], "speed": 7},
{"t": 4.2, "who": "Uma", "stand": true},
{"t": 5.4, "who": "Uma", "sit": "sofa"}
```
`sit` walks to the seat by itself. A seated character must `stand` before any `walk` or `turn`. Points are wrapped: `[[x, y]]`.

**Give a prop** (L1_move_07_carry_give, store; prop `{"name": "box", "kind": "box", "on": "counter", "at": [0, -1.2]}`).
```json
{"t": 0.3, "who": "Ada", "walk": "box"},
{"t": 1.4, "who": "Ada", "grab": {"prop": "box", "hand": "R"}},
{"t": 2.6, "who": "Ada", "give": {"prop": "box", "to": "Bo"}}
```
A prop can also start in a hand: `{"name": "note", "kind": "book", "held_by": "Lia", "hand": "R"}`. Props are declared per scene.

**Fight exchange** (showcase_yamcha scene 2, preset `wasteland`): run in, blocked flurry, blocked strike, uppercut, knockback into the curl pose, top-down shot.
```json
{"t": 3.0, "who": "Vegeta", "walk": [[0.6, 0]], "run": true, "speed": 13},
{"t": 3.9, "who": "Vegeta", "attack": {"flurry": ["punch_R", "punch_L", "punch_R", "kick_R", "punch_L", "punch_R"], "target": "Yamcha", "blocked": true, "s": 1.8}},
{"t": 7.5, "who": "Vegeta", "attack": {"move": "punch_R", "target": "Yamcha", "blocked": true, "hold": 0.45, "relax": true}},
{"t": 8.0, "who": "Yamcha", "attack": {"move": "uppercut_R", "target": "Vegeta"}, "face": "smug"},
{"t": 8.1, "who": "Vegeta", "knockback": {"from": "Yamcha", "to": [-7.3, 0.5], "height": 6, "pose": "curl"}, "face": "scream"}
```
Shots for it (side-on two-shots, then the body from above):
```json
{"t": 2.9, "kind": "full", "on": ["Vegeta", "Yamcha"], "lens": 35, "hold": true, "keep_two": true, "profile": true},
{"t": 7.6, "kind": "full", "on": ["Yamcha", "Vegeta"], "lens": 32, "hold": true, "keep_two": true, "profile": true, "shake": [8.0]},
{"t": 9.15, "kind": "wide", "on": ["Vegeta"], "angle": "top", "profile": true, "lens": 35, "frame": 11, "move": "still", "hold": true}
```
Strikes: `punch_R`, `punch_L`, `kick_R`, `uppercut_R`, `tap_R`. The fist lands AT `t`; the wind-up starts 0.55 s before, and the
attacker must be within 6.6 studs of the target at that moment. Leave 0.6 s between one fighter's strikes (or use `flurry`).
Knockback 0.1 s after the hit; `to` must be free floor (>= 3 studs from anyone). A later scene can start the body down:
`{"t": 0, "who": "Vegeta", "down": {"pose": "curl", "crater": true}}` with the cast `at` = the landing point.

**Fly in and land** (scene 1):
```json
{"t": 11.2, "who": "Saibaman", "fly": {"to": "Yamcha", "height": 3, "s": 0.45}, "sfx": "screech"},
{"t": 11.65, "who": "Saibaman", "land": true, "pose": "hands_up", "face": "scream"},
{"t": 12.3, "who": "Yamcha", "attack": {"move": "punch_L", "target": "Saibaman", "no_look": true}}
```
The strike comes after the flyer has landed (fly `t` + `s` < strike `t` - 0.55).

**Energy beam + deflect** (scene 3):
```json
{"t": 7.8, "who": "Goku", "beam": {"to": "Yamcha", "charge": 3.0, "s": 1.8, "color": "#5AC8FF", "hands": "both", "size": 1.8, "deflect": {"after": 0.6, "to": [20, 30, 40]}}, "face": "scream"}
```
The ball charges for `charge` s BEFORE `t`. Without `deflect`, add a `knockback` on the target ~0.15 s after `t`.

**Power-up aura** (saiyan): `{"t": 1.7, "who": "Goku", "power_up": 2.0, "face": "angry", "aura_color": "#FFD23F"}`.
Aura only (no brace pose): `{"t": 9.25, "who": "Yamcha", "aura": {"s": 3.0, "color": "#FFD23F"}}`.

**Typing at a desk with a picture on the screen** (scene 4). Image path is from the engine folder.
```json
"props": [{"name": "screen", "kind": "screen:stories/showcase_yamcha/screen.png", "on": "desk", "at": [-1.3, -0.3], "rot": 205},
          {"name": "keyboard", "kind": "computerKeyboard", "on": "desk", "at": [0.2, 0.5], "rot": 180}],
"beats": [{"t": 0, "who": "Yamcha", "sit": "desk chair", "look": "screen"},
          {"t": 0.1, "who": "Yamcha", "pose": {"R": [34, -8], "L": [34, 8], "head": [8, 0, 0]}, "wiggle": "R", "wiggle_s": 5.0, "type": 5.2}]
```
`type` = seconds of keyboard clicks in the sound mix. The desk and chair came from the scene's `set.dress` (`"name": "desk"`, `"name": "desk chair"`).

**Face marks** (story cast): `"face_marks": ["scar_x_cheek_L", "scar_eye_R"]`; also `dots6_forehead`, `veins_head`.

**Recorded voice lines + captions**: files in `stories/<name>/voice/`, path from the story folder; `talk` = the file's length.
```json
{"t": 0.2, "who": "Vegeta", "talk": 3.53, "say": "Yamcha? Please. The man is dead weight.", "voice": "voice/01_vegeta.mp3", "pose": "arms_crossed", "face": "smug"}
```
`say` = caption text (2-4 words per card). `"say": ""` = voice without caption. No `voice` = gibberish blips.

**Music**: story key `"mood": "tense"` (loops: `cheery`, `tense`, `chill`, `battle`); one scene with another loop: scene key `"music": "chill"`.
`set.mood` is the LIGHT (`warm`, `cool`, `dramatic`, `sunset`, `night`, `spooky`), not the music.

## 6. Camera advice
1. First shot at `t` 0. Shots >= 0.5 s; 1.2-2.5 s reads best. Cut on the action (a shot starts 0.1 s before the beat it shows).
2. Dialogue: `medium` on the speaker, `close` for the punchline face. `hold: true` stops the automatic splitter.
3. `"establish": false` (scene key) when the scene should open on a face, not on a tiny-people wide.
4. `"pitch": false` (scene key) when big hair hides faces under automatic high angles.
5. Fight two-shots: `"profile": true` + `"keep_two": true`, or the camera may sit behind one fighter.
6. A body on the ground: `"kind": "wide", "angle": "top", "frame": 11, "move": "still"`. Never a close-up on someone lying or flying.
7. Two characters > 8 studs apart in one shot become a single unless `keep_two: true`.
8. Close-ups sit the face high; captions take the lower third. Check one captioned frame for a cropped chin.
9. `front: true` keeps the camera on the front side (desks, sofas facing the camera).
10. `shake: [t]` on the shot that contains the impact.

## 7. The 15 most common mistakes (each one cost a build)

| # | Mistake | Fix |
|---|---|---|
| 1 | A strike fired before the flyer/runner had arrived | the distance is checked at the WIND-UP (`t` - 0.55): arrive first; lint `attack ... at the wind-up` |
| 2 | A fast `fly` from the ground (30 studs in 0.45 s) | `s` >= distance / 25, or a short hop; lint `teleport` |
| 3 | A knockback landing on another character | `to` a free spot >= 3 studs from everyone; lint `knockback ... lands` |
| 4 | Turning or walking a seated character | `stand: true` first; lint `is seated` |
| 5 | A close-up that cropped the face under the captions | `medium`, or check a captioned frame before HQ |
| 6 | A fight two-shot filmed from behind one fighter | `profile: true` + `keep_two: true` |
| 7 | A top view that cut the body | `kind: wide`, `angle: top`, `frame: 11`, `move: still` |
| 8 | Near-black hair (#141414) crushed to a silhouette outdoors | #2A2A2E or lighter; lint `near-black` |
| 9 | The caption file held garbage | after `sound_mix`, look at ONE frame with a caption |
| 10 | Effects fine in draft, broken in HQ | always one HQ still (`--stills`) before a full HQ render |
| 11 | Automatic high angles hid faces under big hair | scene key `pitch: false` |
| 12 | Establishing wides opened on tiny characters | scene key `establish: false` |
| 13 | `walk: [4, -3]` (read as two names) | wrap points: `[[4, -3]]` |
| 14 | `talk` far from the line length (mouth flaps after the voice ended) | `talk` = voice file seconds, or 0.38 s per word |
| 15 | A name typo (`arms_crosed`, a cast name not in the story cast, a prop not declared in THIS scene) | lint prints the name and "did you mean" |

More: two characters starting < 3 studs apart touch; walks ending exactly 3 studs from a standing character get rejected; two walkers
need lanes >= 5 studs apart; long hanging hair + hand-to-face poses clip (prefer short/bun/ponytail); `bigeye` faces only cover
shock/joy/laugh/confused/silly, so write `face_family` (`drawn` or `classic`) for every lead.

## 8. Reading the result
`story.py` prints one line per scene and a verdict:
```
s02 REPORT PASS | hits 0 worst 0.0cm | slide 0.7cm | cuts OK | build 66.5s | render 0s |
STORY PASS | 4 scenes | gates only
```
- `FAIL <reasons>`: the gate names. `hits N worst Xcm` = body overlaps (> 2 cm fails), `slide` = foot slide (> 2 cm fails),
  `cuts` = jump cuts; a hidden face names the shot. `REPORT CRASH` = Blender error: read `stories/<name>/scenes/sNN/log.txt`.
- `stories/<name>/scenes/sNN/report.json`: `errors` (what failed: unknown names, grab/give/walk failures, fight input), `notes`
  (retimes, routing, knockback turned "blocked by NAME", `lands curled, body centre x,y` for continuity), `visibility` per shot
  (`~` = preference only, not a gate), `L1` checks.
- Fix the story, rerun that scene only: `--only k`. Never edit the engine to pass one story.

## 9. What the engine cannot do yet
- Effects are simple: aura, beam, ball, flash, dust, crater, smoke. No fire, water, magic particles, destruction.
- Accessories (hats, glasses, bags) are untested. Hair: only the tags in `assets/hair/LIBRARY.md` (about 50, many anime styles);
  outfits only from `assets/outfits/LIBRARY.md`; faces only from the libraries.
- No lip sync: the mouth flaps for `talk` seconds. No hand fingers, no cloth simulation.
- Rigid R6 limbs: elbows and knees do not bend, hands pass through long hair, hugs and fine hand contact read poorly.
- HQ needs the GPU farm (minutes, costs money) or hours on one local GPU. Drafts are flat-shaded on purpose.
- The lint knows positions approximately (walks to props/furniture are not followed); a clean lint is not a passing gate.

## 14. Formats (which Short to write)
Read `FORMATS.md` first: a one-line table picks the format (`skit`, `pov`, `time_skit`, `in_this_world`, `narrated_twist`, `versus`, `choice`), then the block gives the hook shape, beat structure for 15 / 30 / 60 s (under 30 s performs best), voice mode and the keys to use.
Set `"format": "<name>"` at the top of story.json. It is a preset only: the lint prints what it applies and warns when the story lacks what the format needs (header, cards, narrator, split, pov camera, length over the hint). Keys: `header`, `captions`, `narrator`, `voices`, `cards`, `split`, scene `crowd`, beat `narrate` / `freeze`, camera mode `pov`: `short.schema.md` section 9. Examples: `stories/fmt_<format>/story.json`.
