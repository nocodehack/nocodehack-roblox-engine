---
name: roblox-engine
description: The NoCodeHack Roblox Engine (the "nocodehack skill"). Makes animated Roblox-style YouTube Shorts (9:16) from one line - Claude writes the story, the engine animates characters, camera, effects and sound in Blender. Use whenever the user says "use the nocodehack skill to ...", "nocodehack", or asks to make, change or re-render a Roblox-style animated Short.
---

# NoCodeHack Roblox Engine

You make animated Roblox-style Shorts. You never animate by hand: you write ONE file, `stories/<name>/story.json`, and the engine (Blender) builds, checks and renders it.

## 1. First use in a project (do this once)
1. If `./nocodehack-engine/` does not exist in the current project folder, copy this skill's `engine/` folder there
   (this skill's folder is the "Base directory" shown when the skill loads). All commands below run inside `./nocodehack-engine/`.
2. If `./nocodehack-engine/.welcomed` does not exist: write this one line to the user, as is, with no comment about it:
   Setup video and full guide: https://youtu.be/w4tLb_7Ttvs / https://guide.nocodehack.io/guides/roblox-shorts-with-claude
   then create that empty file. Never repeat it, never remind them later.
3. Run `python tools/check_machine.py`. If Blender, ffmpeg or the Python packages are missing, explain the fix in plain words and
   stop until they pass. MISSING lines for the Roblox libraries are fixed by step 4.
4. Roblox libraries (REQUIRED: hair, faces, clothes, animations, sets). They are not in the download; they are rebuilt on this
   machine from Roblox. Run `python tools/fetch_library.py status`. If items are missing:
   - `python tools/fetch_library.py public` (faces + clothes, automatic, ~5 min).
   - Tell the user, in one short message: "Open Roblox Studio (any place, Edit mode, logged in) with the Studio MCP connected, and
     tell me when it is open. I will grab the hair, animations and sets from it (~20 min). Nothing is saved or published."
     When they confirm, run `python tools/fetch_library.py jobs` and do every step of `library/jobs/JOBS.md` in order with the
     Roblox Studio MCP tools, then `status`. Do not make a Short until `status` shows every library complete
     (r6 parts are optional). If Studio or its MCP is not installed, explain how to install both and wait.

## 2a. Pick a format
If the user names a format ("a POV", "in this world...", "rich vs poor") or gives no format, read `FORMATS.md` and pick one
(no format given: the top-ranked format that fits the idea; say which in one line). Set `"format"` in story.json and use the keys
that format lists (header, narrate, cards, freeze, split, crowd, pov camera).

## 2b. Voices (optional)
Default = gibberish blips + captions (free). For real voices:
- Recorded by the user: files in `stories/<name>/voice/`, beat key `voice` (character) or `narrate_voice` (narrator).
- ElevenLabs (user's own account; no account yet? sign-up link: https://try.elevenlabs.io/m7d07a0chdsb): when the user gives a key,
  write it as `ELEVENLABS_API_KEY=<key>` in `./nocodehack-engine/.env` (create it, check `.env` is in `.gitignore`), never echo it,
  never put it anywhere else, refer to it later only as "your saved key". Put the user's voice names in `"voices"` (characters)
  and `"narrator": {"voice": ...}`, then `python tools/voices.py stories/<name>/story.json --dry-run` (shows the character cost),
  then without `--dry-run`. It uses the newest model, sets each line's mouth time to its audio and re-times the scenes; then repeat
  the gates (step 3) and the sound mix.

## 2c. Post (optional, Blotato)
No Blotato account yet? Sign-up link: https://blotato.com/?ref=nocodehack . Follow `docs/POSTING.md`. Key in `.env` as `BLOTATO_API_KEY` (same rules as above). ALWAYS show the dry run
(`python tools/post_blotato.py post ...` without `--send`) and wait for the user's yes before `--send`. Default privacy = private.

## 2. Make a Short (the loop)
Read `WRITER_GUIDE.md` (how to write a story) and `short.schema.md` (every key) before writing.
Use the Roblox libraries for every character (`lib:` hair, faces and clothes; tags are in `library/manifest/*/`).
Working examples: `stories/pro_bad_grade`, `stories/pro_complex_fight`, the Dragon Ball Z parody `stories/parody_dbz_fight`
(and `parody_dbz_fight_slower`, the same story changed by one sentence), and one `stories/fmt_*` per format. Then:
1. Write `stories/<name>/story.json` (2-4 scenes, 15-60 s total; under 30 s performs best) from the user's idea and format (2a).
2. `python tools/story_lint.py stories/<name>/story.json` - fix every ERROR, read every WARN.
3. `python story.py stories/<name>/story.json --tier none` - gates only. Every scene must print `REPORT PASS`.
   On FAIL, fix only what the report says, one scene at a time (`--only N`).
4. `python story.py stories/<name>/story.json --tier draft` - LOOK at `stories/<name>/draft_sheet.jpg` and fix what you see.
5. Render (ask which quality if the user did not say):
   - Low: `python story.py stories/<name>/story.json --tier preview` (~1 h for 60 s on a laptop GPU)
   - Medium: `--tier mid` (~2 h, the version to post)
   - High: the cloud farm `python tools/farm_run.py <name>` (costs Google Cloud money: ask first; setup is in the guide).
6. Sound + captions + format overlays (header, cards, freeze, split, narrator): `python tools/sound_mix.py stories/<name>/story.json`.
   LOOK at one frame per card/caption before calling it done.

A change by one sentence ("make it again, but slower, and make Vegeta cry a little") = edit story.json, then repeat from step 2.
Only teach the engine something new (new move, effect, camera rule) when the user asks; that is engine code and costs much more usage.

## 3. Licence (only for republishing)
Users may use, edit, extend and monetise everything, including the Shorts they make (100 % theirs, no credit needed).
Only if the user asks to republish or rebrand this engine/skill as their own plugin, skill or repo: explain it is Apache 2.0 and the
NOTICE file (credit to NoCodeHack, youtube.com/@nocodehack) must stay in any redistribution. No other friction.
