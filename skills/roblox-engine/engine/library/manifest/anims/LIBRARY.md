# Roblox R6 animation library (R180)

Roblox's own R6 animations as acting data. `anims.play(sc, ch, slug, f0, speed=1.0, loop_until=None, skip=())`; beat key `{"anim": "dance2", "loop": 2.0}`. Raw data: `assets/anims/<slug>/anim.json` (per keyframe: time, per Pose rotation vector + position + easing), `meta.json`. Contact sheet: `sheet.jpg` (6 frames per clip).

Source A = Roblox default R6 Animate script ids (KeyframeSequenceProvider). Source B = Creator Store free model 'R6 Versions of R15 Emotes & Dances' (110796770261450, Storflin6564; 85 clips inside, 11 imported, baked at ~30 fps, long ones decimated to every 2nd key). Rest of pack B can be imported with the same Luau (see LOG R180).

| slug | asset id | duration s | loop | what | source |
|---|---|---|---|---|---|
| agree | 110796770261450 | 1.97 | no | agreeing nod + hand gesture | B |
| applaud | 110796770261450 | 3.00 | yes | clapping | B |
| cheer | 129423030 | 1.04 | no | default /e cheer (both arms up) | A |
| climb | 180436334 | 0.46 | yes | default ladder climb | A |
| cower | 110796770261450 | 6.30 | yes | cowering in fear | B |
| curtsy | 110796770261450 | 2.43 | no | curtsy bow | B |
| dance | 182435998 | 1.15 | yes | default /e dance | A |
| dance2 | 182491037 | 1.15 | yes | default /e dance2 | A |
| dance3 | 182491277 | 2.17 | yes | default /e dance3 | A |
| disagree | 110796770261450 | 1.97 | no | tsundere disagree head shake + arms | B |
| fall | 180436148 | 0.65 | yes | default falling flail | A |
| haha | 110796770261450 | 4.28 | no | belly laugh | B |
| hello | 110796770261450 | 1.70 | no | hello hand | B |
| idle | 180435571 | 1.00 | yes | default idle breathing | A |
| jump | 125750702 | 0.62 | no | default jump arms-up tuck | A |
| laugh | 129423131 | 1.12 | no | default /e laugh (right arm to belly) | A |
| point | 128853357 | 1.12 | no | default /e point (LEFT arm straight forward) | A |
| salute | 110796770261450 | 3.70 | no | military salute | B |
| shrug | 110796770261450 | 1.67 | no | shrug (arms out) | B |
| shy | 110796770261450 | 6.30 | no | shy fidget, head down | B |
| tantrum | 110796770261450 | 3.13 | yes | stomping tantrum | B |
| toolnone | 182393478 | 0.50 | yes | default tool-hold arm (right arm forward) | A |
| walk | 180426354 | 0.67 | yes | default walk cycle (run = same asset 180426354, play with anim_speed ~1.6) | A |
| wave | 128777973 | 1.50 | no | default /e wave (right arm up, swings) | A |
