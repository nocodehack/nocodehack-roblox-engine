# FORMATS - which Short to write (read this BEFORE writing a story.json)

Source: `research/formats/FORMATS-STUDY.md` (3,141 Roblox-style Shorts, titles only, no transcripts: timings below are OUR design targets, not measurements).
Rule of the study: Shorts under 30 s have the best median views (2.7-3.0M); 45-60 s only pays for narrated/story formats. Default to 15-30 s.
All example wording is ours. Never copy a creator's line.

## Pick a format from one line

| The idea in one line | format | rank |
|---|---|---|
| a relatable family/sibling situation that escalates | `skit` | 1 |
| the viewer IS a character and the others react to "you" | `pov` | 2 |
| something happens at a clock time ("3 AM", "Monday 7:00") | `time_skit` | 3 |
| a strange world with one rule, shown on a crowd | `in_this_world` | 4 |
| a told story with a flip in the last line | `narrated_twist` | 5 |
| the same task done twice, A vs B | `versus` | 6 |
| the viewer picks 1 or 2 | `choice` | 7 |
| rich kid vs poor kid with a reversal | `rich_poor` | 8, lottery (median 140k, rare huge hits) |
| a tier list / counting down | `ranking` | 9, needs many characters: skip for now |
| "what if ..." | `what_if` | 10, WEAK (median 13k): only as a title-card variant of `in_this_world` |
| a chat on a phone | `text_message` | 11, WEAK and not supported (no phone UI): write it as `narrated_twist` |

`format` is a preset only: explicit keys always win. `python tools/story_lint.py <story>` prints what the preset applied and warns when the
story lacks what the format needs. Every key below is optional; stories without them render exactly as before.

## Keys the formats use (full reference: short.schema.md section 9)
`header` (premise text, whole video) | `captions` (`cards` | `word`) | `narrator` + beat `narrate` | `voices` | `cards` (title, time, label, counter, choice) |
beat `freeze` | `split` (stacked pairs of scenes) | scene `crowd` | scene `camera: {"mode": "pov", "who": "<name>"}`.
A `narrate` or `freeze` beat still needs `t` and `who` (the character on screen at that moment); other keys on it are optional.
Times of cards are seconds INSIDE their scene and must end before the scene ends.

---

## 1. `skit` (family / sibling / "be like" / "when you...")  - rank 1, 25 pt
- Pick when: one relatable situation, 2-3 characters, one location, it gets worse three times and ends on a punch.
- Title/hook shape: "When your little brother ___ and swears ___" / "Be like the sibling who ___". Our own wording each time.
- Preset: captions `cards`, narrator off, camera `story_cuts` (or `static_wide`), 15-30 s.
- Beats: 15 s = setup 0-3, escalation 3-10, punchline 10-13, reaction hold 13-15. 30 s = setup 0-5, two escalations 5-22, punchline 22-27, tag 27-30.
  60 s = 3-4 escalations, each bigger, still one location (only if the idea really needs it).
- Voice: silent + SFX, or 1-4 word lines (blips). Keys: `header` always (the premise stays on top), `say` lines for the few spoken words. No narrator.
```json
{"title": "Charger hide", "format": "skit", "header": "when your little brother hides your charger and swears he is innocent",
 "scenes": [{"set": {"preset": "bedroom"}, "seconds": 14, "cast": [{"name": "Sis", "at": [-6, -4]}, {"name": "Bro", "at": [6, -2], "yaw": -40}],
   "beats": [{"t": 1.0, "who": "Sis", "face": "angry", "talk": 1.2, "say": "Where is it?"}, {"t": 9.0, "who": "Bro", "face": "smug"}]}]}
```

## 2. `pov` ("POV: ...")  - rank 2, 16 pt
- Pick when: the viewer is a character ("you") and everyone else reacts to the lens: new kid, teacher picks you, you are late.
- Title/hook: "POV: you ___ and everyone ___". Header carries the POV line.
- Preset: captions `cards`, narrator off, camera `pov`, 15-30 s.
- Beats: 15 s = hook 0-2 (someone turns to you), situation 2-9, reaction to "you" 9-15. 30 s adds one escalation. 60 s is rare.
- Voice: silent or short lines aimed at the lens. Put the "you" character in the scene cast (it never appears on screen; the camera is its eyes).
  Camera: `"camera": {"mode": "pov", "who": "You"}` - eye height, small handheld drift, the other characters look into the lens at the start (their own `look`/`turn` beats win).
```json
{"title": "New kid", "format": "pov", "header": "POV: you are the new kid and the teacher picks you first",
 "scenes": [{"set": {"preset": "classroom"}, "seconds": 12, "camera": {"mode": "pov", "who": "You"},
   "cast": [{"name": "You", "at": [0, -8], "yaw": 180}, {"name": "Teacher", "at": [0, 3]}],
   "beats": [{"t": 1.0, "who": "Teacher", "face": "smile", "talk": 1.5, "say": "You. Up here."}]}]}
```

## 3. `time_skit` (clock-time skit)  - rank 3, 12 pt
- Pick when: the joke is WHEN ("at 3 AM the whole house is awake", "Sunday 11 PM, homework").
- Title/hook: "When you wake up at 3 AM and ___". Time cards ARE the structure.
- Preset: captions `cards`, narrator off, camera `static_wide`, 15-30 s.
- Beats: 15 s = time card 0-2, one beat, tag. 30 s = 2-3 time cards (each scene starts with one, relit with `set.time`: day / evening / night). 60 s = 5-6 cards.
- Keys: `cards` type `time` ("3:00 AM"), `header`. Blips + SFX, or one `say` per scene.
```json
{"title": "3 AM house", "format": "time_skit", "header": "when you wake up at 3 AM and the whole house is awake",
 "cards": [{"type": "time", "text": "3:00 AM", "scene": 1, "t": 0.0, "dur": 1.6}, {"type": "time", "text": "3:05 AM", "scene": 2, "t": 0.0, "dur": 1.6}],
 "scenes": [{"set": {"preset": "bedroom", "time": "night"}, "seconds": 8, "cast": [{"name": "Kid", "at": [0, -4]}], "beats": [{"t": 2.0, "who": "Kid", "face": "scared"}]},
            {"set": {"preset": "kitchen", "time": "night"}, "seconds": 8, "cast": [{"name": "Kid", "at": [0, -4]}], "beats": [{"t": 2.0, "who": "Kid", "face": "scream"}]}]}
```

## 4. `in_this_world` (premise + narrator)  - rank 4, 12 pt
- Pick when: one bizarre rule, shown on a crowd and one protagonist; characters mime, the narrator talks.
- Title/hook: "In this world, everyone's ___" (the rule goes on a title card). `what_if` = the same with "WHAT IF ..." on the card (weak: use only on request).
- Preset: captions `word` (key word coloured with `*word*`), narrator ON, camera `story_cuts`, 30-60 s (hint 45).
- Beats: 15 s = rule card 0-3, rule shown 3-8, consequence 8-13, sting 13-15. 30 s = card, rule, 2 vignettes, twist. 60 s = card, rule, 3-4 escalating vignettes, one protagonist, a final turn that re-reads the rule.
- Keys: `cards` type `title` at scene 1 t 0; `narrator`; `narrate` on beats; `crowd` on the wide scenes (6-14 extras, area `back`/`sides`).
```json
{"title": "Shadow truth", "format": "in_this_world", "narrator": {"voice": "Adam"}, "captions": "word",
 "cards": [{"type": "title", "text": "IN THIS WORLD...", "scene": 1, "t": 0.0, "dur": 1.5}],
 "scenes": [{"set": {"preset": "park"}, "seconds": 12, "crowd": {"n": 10, "area": "back"}, "cast": [{"name": "Kid", "at": [0, -4]}],
   "beats": [{"t": 1.6, "who": "Kid", "narrate": "In this world, everyone's *shadow* tells the truth."}]}]}
```

## 5. `narrated_twist` (revenge / karma / sad)  - rank 5, 9 pt
- Pick when: a told story, first line is the hook with stakes, the last line flips who was right.
- Title/hook: hook that ends in an ellipsis ("My neighbour asked me to water his plants, then I saw ..."). Our own story each time.
- Preset: captions `word`, narrator ON, camera `story_cuts` (slow push-ins, close-up reaction at the twist), 30-45 s.
- Beats: 15 s = hook 0-2, 2 beats, twist at 11, button. 30 s = hook, setup, conflict, twist at 22, payoff. 60 s = hook, setup, 2 conflicts, twist ~42, payoff, loop line.
- Keys: `narrator`, `narrate` beats; `freeze` on the twist beat (`{"label": "...", "dur": 1.0}`); optional `title` card is NOT used (the hook is spoken).
```json
{"title": "Plant cameras", "format": "narrated_twist", "narrator": {"voice": "Adam"},
 "scenes": [{"set": {"preset": "living_room"}, "seconds": 9, "cast": [{"name": "Kid", "at": [0, -4]}],
   "beats": [{"t": 0.5, "who": "Kid", "narrate": "My neighbour asked me to water his plants, then I saw the *cameras*..."},
             {"t": 6.0, "who": "Kid", "face": "scream", "freeze": {"label": "HE WAS WATCHING", "dur": 1.0}}]}]}
```

## 6. `versus` (A vs B)  - rank 6, 9 pt
- Pick when: the same task done twice by two kinds of person (cautious vs reckless sibling, mom vs dad, noob vs pro).
- Title/hook: "A vs B at ___". Header = the title.
- Preset: captions `cards`, narrator off, camera `static_wide` (SAME framing for A and B so the comparison reads), 30 s.
- Beats: 15 s = hook 0-1.5, A 1.5-7, B 7-13, result 13-15. 30 s = 3 rounds. 60 s = 3-4 rounds, the last is the twist.
- Keys: `split: [[1, 2]]` = scene 1 on top, scene 2 below (build both scenes with the same set, same seconds, same camera); `cards` type `label` ("A" / "B") one per scene.
```json
{"title": "Dentist", "format": "versus", "header": "cautious sibling vs reckless sibling at the dentist", "split": [[1, 2]],
 "cards": [{"type": "label", "text": "CAUTIOUS", "scene": 1, "t": 0.0, "dur": 8.0}, {"type": "label", "text": "RECKLESS", "scene": 2, "t": 0.0, "dur": 8.0}]}
```

## 7. `choice` (1 or 2 / would you rather)  - rank 7, 9 pt
- Pick when: two options the viewer can argue about ("door A or door B").
- Hook: the question on a `choice` card; end with a comment prompt.
- Preset: captions `cards`, narrator off, camera `static_wide`, 30 s. Music, no narrator (or a narrated question).
- Beats: 15 s = prompt 0-3, option 1 3-8, option 2 8-13, "comment yours" 13-15. 30 s = 2 rounds. 60 s = 3-4 rounds.
- Keys: `cards` type `choice` with `a` / `b` texts held for the whole prompt; one scene per option.
```json
{"title": "Two doors", "format": "choice", "cards": [{"type": "choice", "text": "PICK ONE", "a": "RED DOOR", "b": "BLUE DOOR", "scene": 1, "t": 0.0, "dur": 3.0}]}
```

## 8. `rich_poor` - rank 8, lottery
- Versus with a reversal in the last 3 s (the poor one wins). Median 140k, a few 20-96M hits. Same keys as `versus`. Mark in the plan: "lottery, do not expect the median".

## 9. `ranking` - rank 9
- Needs many distinct characters/props: skip for now. If asked: `counter` cards ("#3", "#2", "#1"), one scene per rank, `static_wide`.

## 10. `what_if` - rank 10, WEAK
- Median 13k. Write it as `in_this_world` with the card text "WHAT IF ...". Do not pick it on its own.

## 11. `text_message` - rank 11, WEAK, not supported
- Needs a phone UI overlay we do not have. Write the same story as `narrated_twist` or skip it.

## Checklist before you hand a story over
1. `format` set, `header` or title card present when the format needs it (lint warns).
2. Total length at or under the format's hint (lint warns above it).
3. `python tools/story_lint.py` = 0 errors; read every WARN.
4. Gates: `python story.py <story> --tier none`, then `--tier draft` and LOOK at `draft_sheet.jpg`.
