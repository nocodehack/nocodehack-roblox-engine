"""Post a video to YouTube through Blotato's REST API (stdlib only).
  python tools/post_blotato.py setkey <key>
  python tools/post_blotato.py accounts
  python tools/post_blotato.py post video.mp4 --platform youtube --title T [--description D] [--privacy private] [--account ID] [--send]
Default for `post` is a DRY RUN: prints the requests, sends nothing. Docs: https://help.blotato.com/api/start
"""
import argparse, json, mimetypes, sys, time, urllib.error, urllib.request
from pathlib import Path

BASE = "https://backend.blotato.com/v2"
ENGINE = Path(__file__).resolve().parent.parent
ENV = ENGINE / ".env"
KEYNAME = "BLOTATO_API_KEY"
SIGNUP = "https://blotato.com/?ref=nocodehack"


def die(msg):
    sys.exit("error: " + msg)


def read_env(path=None):
    out = {}
    p = Path(path or ENV)
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")  # keeps a trailing '=' of the key
    return out


def mask(key):
    return "****" + key[-4:] if key else "(not set)"


def set_key(key, path=None):
    p = Path(path or ENV)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    lines = [l for l in lines if not l.strip().startswith(KEYNAME + "=")] + [f"{KEYNAME}={key}"]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    gi = p.parent / ".gitignore"
    cur = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    if ".env" not in [c.strip() for c in cur]:
        gi.write_text("\n".join(cur + [".env"]) + "\n", encoding="utf-8")


def get_key():
    k = read_env().get(KEYNAME, "")
    if not k:
        die(f"{KEYNAME} is not set.\nNo Blotato account yet? Sign up: {SIGNUP} (API needs a paid plan).\n"
            "Then copy the key (Blotato > Settings > API) and save it with:\n  python tools/post_blotato.py setkey <key>")
    return k


def _open(req):
    """The only network call; tests replace it. Returns (status, body_bytes)."""
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def call(method, url, key=None, body=None, raw=None, ctype=None):
    h = {}
    if key:
        h["blotato-api-key"] = key
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if ctype:
        h["Content-Type"] = ctype
    st, resp = _open(urllib.request.Request(url, data=data, headers=h, method=method))
    if st == 401:
        die("401 from Blotato: API key invalid (keep the full key, including any trailing '='). API needs a paid plan.")
    if st >= 400:
        die(f"Blotato {method} {url} -> {st}: {resp[:400].decode('utf-8', 'replace')}")
    return json.loads(resp) if resp else {}


def post_body(account_id, media_url, a):
    return {"post": {"accountId": account_id,
                     "content": {"text": a.description or "", "mediaUrls": [media_url], "platform": "youtube"},
                     "target": {"targetType": "youtube", "title": a.title, "privacyStatus": a.privacy,
                                "shouldNotifySubscribers": False, "isMadeForKids": False}}}


def cmd_accounts(a):
    items = call("GET", BASE + "/users/me/accounts", get_key()).get("items", [])
    if not items:
        print("No connected accounts. Connect them in Blotato > Settings > Accounts.")
    for i in items:
        print(i.get("id"), i.get("platform", ""), i.get("username") or i.get("fullname") or i.get("name") or "", sep="\t")


def cmd_post(a):
    v = Path(a.video)
    if not v.is_file():
        die(f"video not found: {v}")
    if len(a.title) > 100:
        die("title is over 100 characters (YouTube limit)")
    if len(a.description or "") > 5000:
        die("description is over 5000 characters")
    key = read_env().get(KEYNAME, "")
    ctype = mimetypes.guess_type(v.name)[0] or "video/mp4"
    if not a.send:
        acct = a.account or "<the only connected YouTube account, looked up at send time>"
        body = post_body(acct, "<publicUrl from step 2>", a)
        print(f"DRY RUN - nothing is sent. Key: {mask(key)}. Add --send to post.\n")
        print(f"1) POST {BASE}/media/uploads  header blotato-api-key: {mask(key)}\n   {json.dumps({'filename': v.name})}")
        print(f"2) PUT <presignedUrl>  Content-Type: {ctype}  body: {v.stat().st_size} bytes of {v}")
        print(f"3) POST {BASE}/posts  header blotato-api-key: {mask(key)}\n{json.dumps(body, indent=2)}")
        print(f"4) GET {BASE}/posts/<postSubmissionId> until published/failed\n"
              f"Privacy: {a.privacy}. Vertical video under 3 min posts as a Short automatically.")
        return
    key = get_key()
    if not a.account:
        yt = [i for i in call("GET", BASE + "/users/me/accounts", key).get("items", []) if i.get("platform") == "youtube"]
        if len(yt) != 1:
            die(f"found {len(yt)} YouTube accounts; pass --account <id> (see `accounts`)")
        a.account = str(yt[0]["id"])
    up = call("POST", BASE + "/media/uploads", key, body={"filename": v.name})
    call("PUT", up["presignedUrl"], raw=v.read_bytes(), ctype=ctype)  # presigned URL: no api-key header
    sub = call("POST", BASE + "/posts", key, body=post_body(a.account, up["publicUrl"], a))["postSubmissionId"]
    print("submitted:", sub)
    for _ in range(40):
        st = call("GET", f"{BASE}/posts/{sub}", key)
        print("status:", st.get("status"))
        if st.get("status") in ("published", "failed"):
            print(json.dumps(st, indent=2))
            sys.exit(0 if st["status"] == "published" else 1)
        time.sleep(a.poll)
    die("still processing; check the Blotato dashboard, submission id " + sub)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    k = s.add_parser("setkey"); k.add_argument("key")
    s.add_parser("accounts")
    q = s.add_parser("post"); q.add_argument("video")
    q.add_argument("--platform", default="youtube", choices=["youtube"])
    q.add_argument("--title", required=True); q.add_argument("--description", default="")
    q.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    q.add_argument("--account"); q.add_argument("--send", action="store_true")
    q.add_argument("--poll", type=float, default=5.0)
    a = p.parse_args(argv)
    if a.cmd == "setkey":
        set_key(a.key)
        print(f"saved to {ENV} as {mask(a.key)}; .env is gitignored")
    elif a.cmd == "accounts":
        cmd_accounts(a)
    else:
        cmd_post(a)


if __name__ == "__main__":
    main()
