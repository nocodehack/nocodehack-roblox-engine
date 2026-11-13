"""l1_face.py - LEVEL 1 FACES field checks (LEVEL1.md section 2). build.py calls checks(sc, spec, log) after every build; each
check is read from the built scene itself (the face decals' hide_render keys), not from the schedule that made them:
  family      every character shows faces of ONE family the whole scene, the story-wide one (cast 'face_family', story.py)
              (creator bug '0:11 weird faces': a thin-line Roblox decal and our thick drawn face on one character mid-walk)
  one_face    exactly one face decal is visible on every character on every frame
  texture     every face shown has a loaded image with pixels and its decal hangs on that character's head
  twins       every face worn has its talk ('_talk') and blink ('_shut') twin in its own family
  close_hold  no face is static > 1.5 s on a close-up (mouth flaps and blinks count as changes)
  emotions    every emotion the story writes is on the face at its beat (the family's NEAR emotion when the family has none)"""
import faces, acting, space

CLOSE_HOLD_S = 1.5


def _hidden(o, n):
    fc = next((c for c in space.fcurves_of(o) if c.data_path == 'hide_render'), None)
    return [fc.evaluate(f) > 0.5 for f in range(n)] if fc else [o.hide_render] * n


def _image(o):
    m = o.active_material
    return next((nd.image for nd in m.node_tree.nodes if nd.type == 'TEX_IMAGE'), None) if m and m.node_tree else None


def shown(n):
    """{character: [kind shown on frame f | None (no face) | 'a+b' (two at once)]} for frames 0..n-1."""
    out = {}
    for name, decals in faces._LIB.items():
        hid = {k: _hidden(o, n) for k, o in decals.items()}
        out[name] = [(lambda on: on[0] if len(on) == 1 else ('+'.join(on) if on else None))([k for k in decals if not hid[k][f]]) for f in range(n)]
    return out


TWIN_IOU = .9


def checks(sc, spec, log):
    lib = faces.library(); fps = spec.get('fps', 24); n = sc.frame_end + 1
    fam = log.get('face_family', {}); want_fam = {c['name']: c.get('face_family') for c in spec.get('cast', [])}
    vis = shown(n); res = {}
    worn = {name: sorted({k for k in row if k and '+' not in k}) for name, row in vis.items()}
    fams = {name: sorted({str(acting.face_family(k, lib)) for k in ks}) for name, ks in worn.items()}
    bad_f = {nm: fs for nm, fs in fams.items() if len(fs) != 1 or fs[0] != fam.get(nm, fs[0]) or (want_fam.get(nm) and fs[0] != want_fam[nm])}
    res['family'] = {'ok': not bad_f and bool(fams), 'value': {nm: '+'.join(fs) for nm, fs in fams.items()}, 'limit': '1 family per character'}
    holes = {nm: sum(1 for k in row if k is None or '+' in k) for nm, row in vis.items()}
    res['one_face'] = {'ok': not any(holes.values()), 'value': {nm: v for nm, v in holes.items() if v} or 0, 'limit': 0}
    bad_t = []
    for nm, ks in worn.items():
        head = faces._HEAD.get(nm)
        for k in ks:
            o = faces._LIB[nm][k]; img = _image(o)
            if img is None or not img.size[0] or not (img.packed_file or img.has_data): bad_t.append(f'{nm}:{k} image')
            if head is None or o.parent is not head or (o.matrix_parent_inverse @ o.matrix_basis).translation.length > 0.01: bad_t.append(f'{nm}:{k} off head')
    res['texture'] = {'ok': not bad_t, 'value': bad_t[:6] or 'all loaded, on the head', 'limit': 'image + on head'}
    bad_w = sorted({f'{nm}:{acting._base(k)}' for nm, ks in worn.items() for k in ks if not faces.twins_ok(k)
                    or acting.face_family(k, lib) != acting.face_family(acting._base(k), lib)})
    res['twins'] = {'ok': not bad_w, 'value': bad_w[:6] or 'talk + blink twins for every face', 'limit': '_talk + _shut'}
    bad_e = sorted({f'{nm}:{b} {iou:.2f}' for nm, ks in worn.items() for b in {acting._base(k) for k in ks}
                    if b != 'blink' and (iou := faces.twin_eye_iou(nm, b)) < TWIN_IOU})   # a talk twin keeps the base's eyes AND brows
    res['twin_eyes'] = {'ok': not bad_e, 'value': bad_e[:6] or 'every talk twin keeps its base eyes + brows', 'limit': f'iou >= {TWIN_IOU}'}
    bad_m = sorted({f'{nm}:{b}' for nm, ks in worn.items() for b in {acting._base(k) for k in ks} if b != 'blink' and not faces.twin_mouth_ok(nm, b)})
    res['twin_mouth'] = {'ok': not bad_m, 'value': bad_m[:6] or 'every talk twin keeps its base mouth mood', 'limit': 'frown stays a frown'}
    emo_k = {}
    for nm, ks in worn.items():
        for b in {acting._base(k) for k in ks if k != 'blink'}:
            if b.startswith('lib:') and acting.face_family(b, lib) != 'drawn': emo_k.setdefault((nm, acting.face_emotion(b, lib)), set()).add(b)
    two = sorted(f'{nm}:{e}={sorted(v)}' for (nm, e), v in emo_k.items() if len(v) > 1)
    res['one_decal'] = {'ok': not two, 'value': two[:4] or 'one decal per character and emotion', 'limit': 1}
    hold = {}
    for nm, d in log.get('faces', {}).items():
        row = vis.get(nm, [])
        for f0, f1 in d.get('closes', []):
            run = 1
            for f in range(f0 + 1, min(f1, n - 1) + 1):
                run = run + 1 if row[f] == row[f - 1] else 1; hold[nm] = max(hold.get(nm, 0), run)
    worst = max(hold.values(), default=0) / fps
    res['close_hold'] = {'ok': worst <= CLOSE_HOLD_S, 'value': round(worst, 2), 'limit': CLOSE_HOLD_S}
    miss = []; reqs = log.get('face_req', [])
    for t, who, emo in reqs:
        f = int(round(float(t) * fps)) + 1
        if who not in vis or f >= n or any(w == who and t < t2 <= t + 0.25 for t2, w, _ in reqs): continue
        k = vis[who][f]; got = acting.face_emotion(k, lib) if k and '+' not in k else None
        ok_ = {emo} if acting.face_pool(emo, lib, fam.get(who)) else next(({e} for e in acting.NEAR.get(emo, ()) if acting.face_pool(e, lib, fam.get(who))), {got})
        if got not in ok_: miss.append(f't{t} {who} {emo}->{got}')
    res['emotions'] = {'ok': not miss, 'value': miss[:6] or f'{len(reqs)} honored', 'limit': 'written emotion shown'}
    return res
