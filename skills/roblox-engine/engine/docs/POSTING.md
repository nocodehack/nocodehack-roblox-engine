# Posting Shorts to YouTube with Blotato

No account yet? Sign up: https://blotato.com/?ref=nocodehack

Blotato API needs a paid plan (not the free trial). Verified against the docs on 2026-11-13, not against a live key.

## Option 1: official hosted MCP server (OAuth, no key pasted)
```
claude mcp add --transport http Blotato https://mcp.blotato.com/mcp
```
Then in Claude Code run `/mcp`, choose `Blotato > Authenticate`, approve in the browser. Tools: `blotato_list_accounts`,
`blotato_create_post`, `blotato_get_post_status`. Uses the logged-in browser session, so no API key is involved.
Source: https://www.blotato.com/blog/how-to-post-to-youtube-with-claude , https://www.blotato.com/api/youtube

## Option 2: our script `tools/post_blotato.py` (REST + API key)
Facts (https://help.blotato.com/api/start , https://www.blotato.com/api/youtube ,
https://help.blotato.com/rest-api-reference/publish-post/upload-media-v2-media.md):
- Base `https://backend.blotato.com/v2`; header `blotato-api-key: <key>` (keep any trailing `=`); 401 = bad key.
- `GET /users/me/accounts` -> `{items:[{id,...}]}`; `id` is the `accountId`.
- Local file: `POST /media/uploads {"filename"}` -> `{presignedUrl, publicUrl}`; `PUT` the bytes to `presignedUrl`; put `publicUrl` in `mediaUrls`.
- `POST /posts` -> `{postSubmissionId}`; poll `GET /posts/:id` until `published` or `failed`.
- YouTube target: `title` (max 100), `privacyStatus` private|unlisted|public, `shouldNotifySubscribers`; optional `isMadeForKids`, `playlistIds`, `thumbnailUrl`. Description = `content.text` (max 5000). No tags. Vertical video under 3 min becomes a Short automatically (no Shorts flag).
- Limits: 10 uploads per channel per 24 h on Starter, 25 on Creator/Agency; 400 MB (Starter) / 1 GB file size; per-second request limits not documented.

## Prompt 1: "connect Blotato to Claude Code with my API key <key>, keep the key private, and list my connected accounts"
1. Run `python tools/post_blotato.py setkey <key>` (writes `BLOTATO_API_KEY` to `<engine>/.env`, adds `.env` to `.gitignore`; prints only the last 4 characters).
2. Never echo the key again, never put it in any other file, command log, commit or message.
3. Run `python tools/post_blotato.py accounts` and show the table (id, platform, name).
4. Optionally offer Option 1 (MCP) as the keyless alternative.

## Prompt 2: "post this Short to my YouTube as private, and show me what you'll send first"
1. Pick the video (the final `.mp4`), a title (verb-first, max 100) and description.
2. Run `python tools/post_blotato.py post <video.mp4> --platform youtube --title "<T>" --description "<D>" --privacy private` (dry run, no `--send`).
3. Show the user the printed requests verbatim (upload, PUT, post JSON, privacy private) and wait for an explicit yes.
4. Only then re-run the same command with `--send`. If more than one YouTube account exists, add `--account <id>` from `accounts`.
5. Report the final status line (`published` or `failed` + the error). Never use `--privacy public` unless the user says so.
