"""look.py - lighting/colour presets + render tiers.
Preset 'soft_window' = Codex cook20 lights (positions scaled by sets.K, energy x K^2 to keep the same light on the subject),
AgX Medium High Contrast, exposure -0.25. Tiers: draft (Workbench), look (Cycles 8 spp 50%), final (Cycles 32 spp 100%),
hq (cloud farm look), mid / preview (the hq look on the local GPU at 50 %, 32 / 8 spp + OIDN, resumable, upscaled to 1080x1920).
Look/final/HQ concentrate light on the cast; draft retains the base lighting and grade."""
import os, math
try:
    import bpy
except ModuleNotFoundError as error:
    if error.name != 'bpy': raise
    bpy = None  # Story planning uses contrast_moods in ordinary Python, before Blender jobs exist.
if bpy is not None:
    from mathutils import Vector
    import sets
    K = sets.K
# R-look2 day exteriors: sky fill opposite the sun + warm ground bounce (shadow side ~2-2.5 stops under the lit side), softer curve
DAY_EXT = dict(sky_fill=1000, bounce=300, world=1.4, look='AgX - Medium High Contrast', sat=1.15, exp=-0.6, key=300, bg_sat=1.15)   # bg_sat: background-only (1.0 = dull taupe desert)
LOWKEY_BG_SAT = 1.3   # R207c: 2.0 turned the beige classroom red-orange (director review); background-only saturation
_DAY_EXPOSURE = {'classroom': -1.25, 'classroom2': -1.1, 'school_hallway': -.65,
                 'living_room': -.9, 'bedroom': -.9, 'kitchen': -1.5, 'store': -1.4,
                 'hallway': -.75, 'bathroom': -1.83, 'office': -.9, 'room': -.9}
_NIGHT_EXPOSURE = {'classroom': -.25, 'classroom2': .1, 'school_hallway': -.35,
                   'living_room': .8, 'bedroom': .15, 'kitchen': -.4, 'store': -.03,
                   'hallway': -.45, 'bathroom': -1.02, 'office': .15, 'room': .9}

LIGHTS = {
    'soft_window': [('Huge soft window', (5, -1.4, 6.5), (0, .7, 1.8), 1050, (1, .84, .61), 5),
              ('Front softbox', (-3, -4, 5), (0, .5, 2.4), 180, (.89, .94, 1), 5),
              ('Hair rim', (-1, 4, 6), (0, .8, 2.5), 400, (1, .76, .49), 3.5),
              ('Classroom bounce', (1, 2, 6.4), (0, 2, 1), 450, (1, .88, .69), 5)],
}


def _light(name, kind, loc, tgt, w, col, size=1.0):
    d = bpy.data.lights.new(name, kind); d.energy, d.color = w, col
    if kind == 'AREA': d.shape, d.size = 'DISK', size
    if kind == 'SUN': d.angle = math.radians(size)
    o = bpy.data.objects.new(name, d); bpy.context.collection.objects.link(o); o.location = Vector(loc)
    o.rotation_euler = (Vector(tgt) - o.location).to_track_quat('-Z', 'Y').to_euler()
    return o


def window_light(info, side, d):
    """Sun through the windows of `side`: a bright patch on the floor + a faint volumetric-look beam (additive transparent quads, no real
    volume = cheap). Objects are named 'VFX lightshaft *' (space.World skips the VFX prefix, so they are never obstacles); tier() hides them in the draft tier. d = direction the sun rays travel."""
    S = 0.5; x0, x1, y0, y1 = info['bounds']; pl = {'right': x1, 'left': x0, 'back': y1, 'front': y0}[side]
    if d.z > -.05: return

    def mat(name, strength, fac):
        m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
        tr, em, mx, out = (nt.nodes.new(k) for k in ('ShaderNodeBsdfTransparent', 'ShaderNodeEmission', 'ShaderNodeMixShader', 'ShaderNodeOutputMaterial'))
        em.inputs['Color'].default_value = (1, .8, .45, 1); em.inputs['Strength'].default_value = strength; mx.inputs['Fac'].default_value = fac
        nt.links.new(tr.outputs[0], mx.inputs[1]); nt.links.new(em.outputs[0], mx.inputs[2]); nt.links.new(mx.outputs[0], out.inputs['Surface'])
        m.diffuse_color = (1, .8, .45, fac); return m
    patch_m, beam_m = mat('lightshaft patch', 2.5, .28), mat('lightshaft beam', 6.0, .05)

    def mesh(name, verts, faces, m):
        me = bpy.data.meshes.new(name); me.from_pydata(verts, [], faces); me.update(); me.materials.append(m)
        o = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(o); o.visible_shadow = False; o.visible_glossy = False; o.hide_select = True
    for u, w, sill, h in info['windows'].get(side, []):
        ua, ub, za, zb = (u - w / 2) * S, (u + w / 2) * S, sill * S, (sill + h) * S
        P = [{'back': (a, pl, z), 'front': (a, pl, z), 'left': (pl, a, z), 'right': (pl, a, z)}[side] for a, z in ((ua, za), (ub, za), (ub, zb), (ua, zb))]
        Q = []
        for p in P:
            v = Vector(p); t = (.015 - v.z) / d.z; q = v + d * t
            Q.append((min(max(q.x, x0 + .05), x1 - .05), min(max(q.y, y0 + .05), y1 - .05), .015))
        mesh('VFX lightshaft patch', [Q[0], Q[1], Q[2], Q[3]], [(0, 1, 2, 3)], patch_m)
        top = [Vector(P[2]), Vector(P[3])]; bot = [Vector(Q[2]), Vector(Q[3])]
        mesh('VFX lightshaft beam', [*map(tuple, P), *Q], [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)], beam_m)


def _world(sc, col, strength):
    if sc.world is None: sc.world = bpy.data.worlds.new('World')
    sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes['Background']; bg.inputs['Color'].default_value = (*col, 1); bg.inputs['Strength'].default_value = strength


SKIES = {   # R152 graded sky: (stop, linear rgb) from the horizon (0) to the zenith (1); stars only at night
    'day': ([(0, (.82, .9, 1.0)), (.3, (.5, .7, 1.0)), (1, (.16, .38, .9))], 1.1),
    'sunset': ([(0, (1.0, .55, .24)), (.18, (.95, .42, .38)), (.5, (.42, .3, .6)), (1, (.1, .13, .38))], 1.0),
    'night': ([(0, (.07, .09, .26)), (.4, (.03, .04, .14)), (1, (.008, .012, .06))], 1.0)}


def _sky(sc, kind, strength=None):
    """World shader = horizon-to-zenith gradient on the view direction (identical in EEVEE/Cycles, so draft and look/final agree) + stars at night."""
    stops, st = SKIES[kind]
    if sc.world is None: sc.world = bpy.data.worlds.new('World')
    w = sc.world; w.use_nodes = True; nt = w.node_tree; nt.nodes.clear()
    new = nt.nodes.new
    tc, sep, mr, cr, bg, out = new('ShaderNodeTexCoord'), new('ShaderNodeSeparateXYZ'), new('ShaderNodeMapRange'), new('ShaderNodeValToRGB'), new('ShaderNodeBackground'), new('ShaderNodeOutputWorld')
    mr.inputs['From Min'].default_value, mr.inputs['From Max'].default_value = -0.02, 0.85; mr.clamp = True
    nt.links.new(tc.outputs['Generated'], sep.inputs[0]); nt.links.new(sep.outputs['Z'], mr.inputs['Value']); nt.links.new(mr.outputs['Result'], cr.inputs['Fac'])
    el = cr.color_ramp.elements
    while len(el) > 1: el.remove(el[-1])
    el[0].position, el[0].color = stops[0][0], (*stops[0][1], 1)
    for pos, c in stops[1:]: e = el.new(pos); e.color = (*c, 1)
    col = cr.outputs['Color']
    if kind == 'night':   # ~10 % of the Voronoi cells carry a star (a tiny dot), faded in above the horizon
        vo, vs, gt, lt, mul, up, mu2, mv = (new(k) for k in ('ShaderNodeTexVoronoi', 'ShaderNodeSeparateColor', 'ShaderNodeMath', 'ShaderNodeMath', 'ShaderNodeMath', 'ShaderNodeMath', 'ShaderNodeMath', 'ShaderNodeMath'))
        vo.inputs['Scale'].default_value = 45; nt.links.new(tc.outputs['Generated'], vo.inputs['Vector'])
        nt.links.new(vo.outputs['Color'], vs.inputs[0]); gt.operation = 'GREATER_THAN'; nt.links.new(vs.outputs[0], gt.inputs[0]); gt.inputs[1].default_value = 0.9
        lt.operation = 'LESS_THAN'; nt.links.new(vo.outputs['Distance'], lt.inputs[0]); lt.inputs[1].default_value = 0.14
        mul.operation = 'MULTIPLY'; nt.links.new(gt.outputs[0], mul.inputs[0]); nt.links.new(lt.outputs[0], mul.inputs[1])
        up.operation = 'GREATER_THAN'; nt.links.new(sep.outputs['Z'], up.inputs[0]); up.inputs[1].default_value = 0.05
        mu2.operation = 'MULTIPLY'; nt.links.new(mul.outputs[0], mu2.inputs[0]); nt.links.new(up.outputs[0], mu2.inputs[1])
        mv.operation = 'MULTIPLY'; mv.inputs[1].default_value = 6.0; nt.links.new(mu2.outputs[0], mv.inputs[0])
        com = new('ShaderNodeCombineColor')
        for i in range(3): nt.links.new(mv.outputs[0], com.inputs[i])
        mx2 = new('ShaderNodeMix'); mx2.data_type = 'RGBA'; mx2.blend_type = 'ADD'; mx2.inputs['Factor'].default_value = 1.0
        nt.links.new(cr.outputs['Color'], mx2.inputs['A']); nt.links.new(com.outputs[0], mx2.inputs['B']); col = mx2.outputs['Result']
    nt.links.new(col, bg.inputs['Color']); bg.inputs['Strength'].default_value = strength if strength is not None else st
    nt.links.new(bg.outputs[0], out.inputs['Surface'])


def apply_auto(sc, info):
    """Generic light for rooms.py sets. Day interior: warm sun through the biggest window wall (sharp shafts on the floor) +
    a big soft ceiling fill + a cool front fill on the camera side + blue sky in the windows. Night: moon + warm lamps.
    Outdoor day: sun + sky. reference palette = warm, saturated, AgX Medium High Contrast."""
    S = 0.5; W, D, H = info.get('W', 28) * S, info.get('D', 24) * S, info.get('H', 11) * S
    t = info.get('time', 'day'); out = info.get('outdoor', False)
    ws = {k: sum(w for _, w, _, _ in v) for k, v in info.get('windows', {}).items() if v}
    side = max(ws, key=ws.get) if ws else 'right'
    sdir = {'right': Vector((1, -0.35, 0)), 'left': Vector((-1, -0.35, 0)), 'back': Vector((0.35, 1, 0)), 'front': Vector((0.35, -1, 0))}[side]
    if t == 'night':   # readable night (reference blizzard look): blue moon key, blue sky glow, warm practical lamps
        _light('Moon', 'SUN', Vector((6, 4, 12)), (0, 0, 0), 0.35, (.5, .64, 1.0), 2)   # sun 1.3 = daylight in Cycles
        if out:
            for i, lp in enumerate(info.get('lamps', [])):   # downward pools of warm light, darkness between them
                o = _light(f'Street lamp {i}', 'SPOT', lp, (lp[0], lp[1], 0), 2600, (1, .7, .4))
                o.data.spot_size = math.radians(110); o.data.spot_blend = 0.6; o.data.shadow_soft_size = 0.3
            _light('Front fill', 'AREA', (0, -6, 4), (0, 0, 1.6), 150, (.55, .65, 1), 6)
        else:   # indoor night: one warm lamp pool + cool moonlit fill, dark corners
            _light('Lamp warm', 'POINT', (W * 0.25, D * 0.15, H * 0.75), (0, 0, 0), 520, (1, .7, .4))
            _light('Front fill', 'AREA', (0, -D * 0.45, H * 0.6), (0, 0, 1.6), 70, (.55, .65, 1), 4)
        _world(sc, (.03, .05, .14), 1.0); exposure = -0.3 if out else -0.35
        if out: _sky(sc, 'night')
    elif out and t == 'sunset':   # R152: low warm sun from the side, orange horizon, purple zenith
        _light('Sun', 'SUN', (16, 5, 8), (0, 0, 0), 4.0, (1, .66, .36), 3)
        _light('Front fill', 'AREA', (0, -9, 4), (0, 0, 1.6), 500, (1, .82, .7), 8)
        _sky(sc, 'sunset'); exposure = 0.05
    elif out:
        _light('Sun', 'SUN', (12, 3, 22), (0, 0, 0), 5.0, (1, .9, .72), 2)   # high + from the side: houses never shade the cast; R152 warmer key (green ground bounce was tinting faces)
        _light('Front fill', 'AREA', (0, -9, 4), (0, 0, 1.6), 600, (1, .94, .86), 8)   # warm-neutral fill, was cold blue-white
        _sky(sc, 'day'); exposure = 0.15
    else:
        sun_from = sdir * 12 + Vector((0, 0, 7.5)); r2 = sets.R2()      # R149: warmer, higher-contrast day interior (SETS_R2=0 = round-1 palette)
        _light('Sun', 'SUN', sun_from, (0, 0, 0), (12.0 if r2 else 10.0) if t == 'day' else 5.0, ((1, .8, .5) if r2 else (1, .84, .58)) if t == 'day' else (1, .6, .36), 1.0)
        _light('Ceiling fill', 'AREA', (0, 0, H - 0.3), (0, 0, 0), (34 if r2 else 42) * W * D / 40, (1, .86, .66) if r2 else (1, .9, .75), max(W, D) * 0.6)
        if r2 and t == 'day': window_light(info, side, -sun_from.normalized())
        k = sdir.normalized() * 4.5 + Vector((0, -2.0, 0))           # warm KEY from the window side onto the acting area (front third)
        _light('Window key', 'AREA', (k.x, k.y, H * 0.7), (0, -1.5, 1.4), 950, (1, .85, .62), 2.5)
        _light('Front fill', 'AREA', (-1.5, -D * 0.45, H * 0.55), (0, 0, 1.6), 260, (.88, .93, 1), 4)
        _light('Back rim', 'AREA', (1.5, D * 0.4, H * 0.75), (0, 0, 2.0), 300, (1, .8, .55), 3)
        _world(sc, (.55, .7, .95) if r2 else (.5, .72, 1.0), 0.4 if r2 else 0.45); exposure = -0.1
    sc.view_settings.view_transform = 'AgX'
    try: sc.view_settings.look = 'AgX - Punchy'                      # saturated Roblox colour (reference palette)
    except TypeError: sc.view_settings.look = 'AgX - Medium High Contrast'
    sc.view_settings.exposure = exposure
    sc.render.use_motion_blur = False


def apply(sc, preset='soft_window', info=None):
    """preset may carry a mood: 'auto:dramatic' / 'reference:night'. Mood source order: story `look` suffix, set.mood (info['spec']), env LOOK_MOOD."""
    preset, _, mood = (preset or 'soft_window').partition(':')
    mood = mood or ((info or {}).get('spec') or {}).get('mood') or os.environ.get('LOOK_MOOD') or 'default'
    m = MOODS.get(mood)
    if m is None: print('WARNING unknown mood', mood); mood, m = 'default', MOODS['default']
    if m.get('time') and info is not None: info = dict(info, time=m['time'])
    _base(sc, preset, info); _mood(sc, m, info); neutral_bounce()
    sc['look_mood'], sc['look_outdoor'] = mood, bool((info or {}).get('outdoor'))
    sc['look_time'] = (info or {}).get('time', 'day')
    sc['look_preset'] = (((info or {}).get('spec') or {}).get('preset', 'classroom' if info is None else 'room'))
    if (info or {}).get('bounds'): sc['look_bounds'] = info['bounds']
    if os.environ.get('LOOK_ATMOSPHERE', '1') != '0':
        import vfx
        # The legacy classroom has no rooms.py info; its window dimensions are in set units.
        dust_info = info if info is not None else dict(bounds=(-6.85*K, 6.85*K, -11.95*K, 6.05*K),
                                                     windows={'right': [(1.8*K*2, 4.2*K*2, 1.9*K*2, 3.6*K*2)]})
        vfx.window_dust(sc, dust_info)
        weather = (((info or {}).get('spec') or {}).get('weather', 'none'))
        vfx.weather(sc, info or {}, weather)


def neutral_bounce(sat=0.25):
    """Green ground/grass/leaves look green to the CAMERA but bounce near-grey light (Cycles Light Path): faces in parks read
    green otherwise (critic R151 + REPEAT R200 frames 13/15/16). Only plain-colour green Principled materials; idempotent."""
    import bpy
    for m in bpy.data.materials:
        if not m.use_nodes or m.get('neutral_bounce'): continue
        nt = m.node_tree; bs = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if bs is None or out is None or bs.inputs['Base Color'].is_linked or not out.inputs['Surface'].is_linked: continue
        r, g, b, a = bs.inputs['Base Color'].default_value
        if not (g > r * 1.15 and g > b * 1.15): continue
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        dull = nt.nodes.new('ShaderNodeBsdfPrincipled'); dull.inputs['Base Color'].default_value = (y + (r - y) * sat, y + (g - y) * sat, y + (b - y) * sat, a)
        dull.inputs['Roughness'].default_value = bs.inputs['Roughness'].default_value
        lp = nt.nodes.new('ShaderNodeLightPath'); mix = nt.nodes.new('ShaderNodeMixShader')
        src = out.inputs['Surface'].links[0].from_socket
        nt.links.new(lp.outputs['Is Camera Ray'], mix.inputs['Fac'])
        nt.links.new(dull.outputs['BSDF'], mix.inputs[1]); nt.links.new(src, mix.inputs[2])
        nt.links.new(mix.outputs['Shader'], out.inputs['Surface']); m['neutral_bounce'] = True


def _base(sc, preset, info):
    if preset == 'auto' or (info is not None and preset not in LIGHTS):
        return apply_auto(sc, info or {})
    for name, loc, tgt, w, col, size in LIGHTS[preset]:
        d = bpy.data.lights.new(name, 'AREA'); d.energy, d.color, d.shape, d.size = w * K * K, col, 'DISK', size * K
        o = bpy.data.objects.new(name, d); bpy.context.collection.objects.link(o)
        o.location = Vector(loc) * K
        o.rotation_euler = (Vector(tgt) * K - o.location).to_track_quat('-Z', 'Y').to_euler()
    if sc.world is None: sc.world = bpy.data.worlds.new('World')
    sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes['Background']; bg.inputs['Color'].default_value = (1, 1, 1, 1); bg.inputs['Strength'].default_value = .15
    sc.view_settings.view_transform = 'AgX'; sc.view_settings.look = 'AgX - Medium High Contrast'; sc.view_settings.exposure = -.25
    sc.render.use_motion_blur = False


# ---- R181 moods. key/fill/rim/prac = (colour or None, energy multiplier) on the base lights by role; 'rim' key = the cool back light separating
# the blocky characters from the background (on in EVERY mood, default included; LOOK_RIM=0 turns it off for A/B). Metres, camera side = -Y.
# add = extra lights (name, kind, loc, target, watts, colour, size); sky = outdoor sky kind.
MOODS = {
    'default': dict(rim=((.62, .78, 1.0), 170)),
    'warm': dict(key=((1, .55, .2), .9), fill=((.45, .6, 1), .3), rim=((.6, .76, 1), 220), world=((1, .78, .58), .8), exp=-0.3, look='AgX - Punchy', sun=(10, -7, 6),
                 add=[('Golden key', 'AREA', (3.5, -3.8, 3.2), (0, -1.4, 1.3), 900, (1, .62, .28), 2.5)]),
    'cool': dict(key=((.22, .42, 1), .6), fill=((.28, .46, 1), .7), rim=((.75, .88, 1), 200), world=((.3, .5, 1), .7), exp=-0.25, look='AgX - Punchy',
                 add=[('Warm practical', 'POINT', (1.8, -2.0, 2.0), (0, 0, 0), 550, (1, .6, .28), .3)]),
    'dramatic': dict(key=((1, .86, .7), .55), fill=((.45, .55, 1), .08), rim=((.5, .68, 1), 520), world=((.6, .7, 1), .25), exp=-0.3, look='AgX - Medium High Contrast', sun=(14, -2, 4),
                     add=[('Low side key', 'AREA', (4.2, -1.2, 1.7), (0, -1.4, 1.3), 420, (1, .85, .68), 1.4)]),
    'sunset': dict(time='sunset', sky='sunset', key=((1, .4, .1), 1.3), fill=((.8, .42, .9), .6), rim=((.9, .5, .95), 320), world=((1, .5, .7), .8), exp=0.0, look='AgX - Punchy', sun=(15, -3, 2.2),
                   add=[('Low sun', 'AREA', (5, -1.5, 1.4), (0, -1.4, 1.3), 800, (1, .42, .12), 2)]),
    'night': dict(time='night', key=((.3, .45, 1), 3.0), fill=((.3, .4, 1), .3), rim=((.55, .7, 1), 400), world=((.4, .5, 1), .5), exp=-0.3, look='AgX - Punchy',
                  add=[('Practical pool', 'POINT', (1.6, -2.2, 2.2), (0, 0, 0), 250, (1, .62, .3), .3)]),
    'spooky': dict(key=((.25, .8, .65), .15), fill=((.25, .7, .6), .12), rim=((.4, .9, .8), 300), world=((.15, .45, .4), .3), exp=-0.4, look='AgX - High Contrast',
                   add=[('Underlight', 'AREA', (0, -3.2, .3), (0, -1.3, 1.6), 380, (.25, 1, .7), 2.5)]),
}
_ROLE = {'Sun': 'key', 'Moon': 'key', 'Window key': 'key', 'Huge soft window': 'key', 'Back rim': 'rim_old', 'Hair rim': 'rim_old'}


def contrast_moods(scenes):
    """Return scene specs with adjacent automatic moods varied; leave inputs and explicit mood/time choices intact.

    Call once on the complete ordered list BEFORE splitting it into build jobs (not wired into build.py).
    Supply inherited story look/set choices in each spec. Resolution mirrors build.py's emotion tally and apply()'s
    look suffix > set.mood > LOOK_MOOD precedence. A changed scene gets an explicit look suffix, making repeat calls stable.
    """
    result, previous = [], None
    for scene in scenes:
        spec = scene.get('set') or {}
        preset, sep, suffix = scene.get('look', 'soft_window' if spec.get('preset', 'classroom') == 'classroom' else 'auto').partition(':')
        mood = suffix or spec.get('mood') or os.environ.get('LOOK_MOOD')
        pinned = bool(sep or mood or spec.get('time', 'day') != 'day')
        if not mood and spec.get('time', 'day') == 'day':
            words = ' '.join(str(b.get(k, '')) for b in scene.get('beats', []) for k in ('face', 'pose', 'anim')).lower()
            words += ' attack' * sum(1 for b in scene.get('beats', []) if 'attack' in b or 'transform' in b)
            tally = {m: sum(words.count(w) for w in ws) for m, ws in (
                ('dramatic', ('angry', 'shock', 'scream', 'evil', 'furious', 'rage', 'attack')),
                ('cool', ('sad', 'cry', 'worry', 'scared', 'cower')),
                ('warm', ('joy', 'happy', 'laugh', 'cheer', 'love', 'grin', 'smile', 'dance')))}
            best = max(tally, key=tally.get)
            if tally[best] >= 2 and sorted(tally.values())[-2] < tally[best]: mood = best
        mood = mood or {'night': 'night', 'sunset': 'sunset'}.get(spec.get('time'), 'default')
        if mood not in MOODS: mood = 'default'
        if mood == previous and not pinned:
            mood = {'default': 'warm', 'warm': 'sunset', 'cool': 'dramatic', 'dramatic': 'cool',
                    'sunset': 'warm', 'night': 'cool', 'spooky': 'dramatic'}[mood]
            if 'time' in spec and MOODS[mood].get('time'): mood = 'default'
            scene = dict(scene, look=preset + ':' + mood)
        result.append(scene); previous = mood
    return result


def _tint_world(sc, tint, mult):
    w = sc.world
    if w is None or not w.use_nodes: return
    bg = next((n for n in w.node_tree.nodes if n.type == 'BACKGROUND'), None)
    if bg is None: return
    bg.inputs['Strength'].default_value *= mult
    c = bg.inputs['Color']
    if c.is_linked:
        mx = w.node_tree.nodes.new('ShaderNodeMix'); mx.data_type = 'RGBA'; mx.blend_type = 'MULTIPLY'; mx.inputs['Factor'].default_value = 1.0
        mx.inputs['B'].default_value = (*tint, 1); src = c.links[0].from_socket
        w.node_tree.links.new(src, mx.inputs['A']); w.node_tree.links.new(mx.outputs['Result'], c)
    else:
        c.default_value = tuple(a * b for a, b in zip(c.default_value, (*tint, 1)))


def _mood(sc, m, info):
    out = (info or {}).get('outdoor', False)
    for o in [o for o in bpy.data.objects if o.type == 'LIGHT']:
        role = _ROLE.get(o.name, 'prac' if o.name.startswith(('Street lamp', 'Lamp')) else 'fill'); col, mult = m.get(role, (None, 1))
        if role in ('key', 'fill') and col: o.data.color = col
        o.data.energy *= mult
        if o.name == 'Sun' and out and m.get('sun'): o.location = Vector(m['sun']); o.rotation_euler = (-o.location).to_track_quat('-Z', 'Y').to_euler()
    if m.get('sky') and out: _sky(sc, m['sky'])
    if m.get('world'): _tint_world(sc, *m['world'])
    for name, kind, loc, tgt, w, col, size in m.get('add', []): _light(name, kind, loc, tgt, w, col, size)
    if os.environ.get('LOOK_RIM', '1') != '0' and m.get('rim'):
        col, w = m['rim']; _light('Rim cool', 'AREA', (-2.6, 3.4, 3.4), (0, -1.2, 1.3), w, col, 3)
    sc.view_settings.exposure += m.get('exp', 0)
    if os.environ.get('LOOK_DEBUG'): print('LOOKDBG', [(x.name, tuple(round(c, 2) for c in x.data.color), round(x.data.energy, 1)) for x in bpy.data.objects if x.type == 'LIGHT'])
    if m.get('look'):
        try: sc.view_settings.look = m['look']
        except TypeError: pass


# shortcut: mist has no light in-scattering; use local volumes when moving lights must illuminate fog.
ATMOSPHERE = {  # haze colour/opacity, shadow lift, midtone gamma, highlight gain (scene-linear before AgX)
    'default': ((.58, .69, .85), .12, (1, 1, 1.002), (1, 1, 1), (1, 1, 1)),
    'warm': ((.95, .66, .32), .18, (1.003, 1, .996), (1.025, 1.005, .98), (1.04, 1.01, .96)),
    'cool': ((.32, .49, .85), .22, (.997, 1, 1.008), (.98, 1, 1.03), (.96, 1, 1.045)),
    'dramatic': ((.28, .37, .62), .24, (.984, .99, 1.006), (.985, .99, 1.015), (1.07, 1.035, 1.02)),
    'sunset': ((.85, .35, .32), .22, (1.006, .996, 1.008), (1.025, .985, 1.01), (1.045, .99, 1.015)),
    'night': ((.18, .16, .48), .28, (.996, .997, 1.012), (.99, .98, 1.035), (.94, .95, 1.055)),
    'spooky': ((.18, .43, .37), .34, (.994, 1.009, 1.006), (.975, 1.025, 1.01), (.95, 1.04, 1.015)),
}


def _bloom(sc, strength=0.35, threshold=1.0, atmosphere=False):
    """Subtle glow on bright highlights and lamps (compositor Glare, fog glow); everything below `threshold` untouched.
    Blender 5: the compositor is a node GROUP on scene.compositing_node_group (scene.node_tree is gone)."""
    if sc.get('big_beam'): strength = max(strength, 1.6)   # a big energy beam must bloom (white-hot core, coloured halo)
    ng = sc.compositing_node_group
    if ng is None or not ng.get('look_atmosphere'):
        ng = bpy.data.node_groups.new('Look atmosphere', 'CompositorNodeTree')
        ng['look_atmosphere'] = True
    for nd in list(ng.nodes): ng.nodes.remove(nd)
    if not any(i.in_out == 'OUTPUT' for i in ng.interface.items_tree):
        ng.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    if sc.get('lowkey_active'):
        for layer in sc.view_layers:
            layer.use_pass_object_index = True; layer.use_pass_diffuse_color = True; layer.update_render_passes()
    rl = ng.nodes.new('CompositorNodeRLayers'); gl = ng.nodes.new('CompositorNodeGlare'); out = ng.nodes.new('NodeGroupOutput')
    for k, v in (('Type', 'Fog Glow'), ('Quality', 'High'), ('Threshold', threshold), ('Strength', strength), ('Size', .9 if sc.get('big_beam') else 0.6)):
        gl.inputs[k].default_value = v
    rl.scene = sc
    image = rl.outputs['Image']
    if atmosphere:
        color, amount, lift, gamma, gain = ATMOSPHERE.get(sc.get('look_mood', 'default'), ATMOSPHERE['default'])
        if sc.get('lowkey_active') or sc.get('daylight_active'):
            amount *= .65
            color = tuple(c * .45 for c in color)
        for layer in sc.view_layers: layer.use_pass_mist = True
        if sc.world is None: _world(sc, (0, 0, 0), 0)
        sc.world.mist_settings.start = 8 if sc.get('look_outdoor') else 2
        sc.world.mist_settings.depth = 45 if sc.get('look_outdoor') else 14
        sc.world.mist_settings.falloff = 'LINEAR'
        fac = ng.nodes.new('ShaderNodeMath'); fac.operation = 'MULTIPLY'; fac.inputs[1].default_value = amount
        ng.links.new(rl.outputs['Mist'], fac.inputs[0])
        haze = ng.nodes.new('ShaderNodeMixRGB'); haze.blend_type = 'MIX'; haze.inputs[2].default_value = (*color, 1)
        ng.links.new(fac.outputs[0], haze.inputs[0]); ng.links.new(image, haze.inputs[1])
        grade = ng.nodes.new('CompositorNodeColorBalance')
        for name, value in (('Lift', lift), ('Gamma', gamma), ('Gain', gain)):
            next(s for s in grade.inputs if s.name == name and s.type == 'RGBA').default_value = (*value, 1)
        ng.links.new(haze.outputs[0], grade.inputs['Image']); image = grade.outputs['Image']
    if sc.get('lowkey_active'):
        sat = ng.nodes.new('CompositorNodeHueSat')
        saturation = 1.0 if sc.get('look_mood') in ('night', 'spooky') else DAY_EXT['bg_sat'] if sc.get('look_day_exterior') else LOWKEY_BG_SAT   # R238: 1.6 (R217) at night = an all-RED room on warm walls (t_night_room s02)
        sat.inputs['Saturation'].default_value = float(os.environ.get('LOWKEY_BG_SAT', saturation))
        ng.links.new(image, sat.inputs['Image'])
        # Saturation must not turn lit trees and coloured walls into black silhouettes.
        before, after = ng.nodes.new('CompositorNodeRGBToBW'), ng.nodes.new('CompositorNodeRGBToBW')
        ng.links.new(image, before.inputs[0]); ng.links.new(sat.outputs['Image'], after.inputs[0])
        ratio = ng.nodes.new('ShaderNodeMath'); ratio.operation = 'DIVIDE'
        ng.links.new(before.outputs[0], ratio.inputs[0]); ng.links.new(after.outputs[0], ratio.inputs[1])
        bright = ng.nodes.new('ShaderNodeMixRGB'); bright.blend_type = 'MULTIPLY'; bright.inputs[0].default_value = 1
        ng.links.new(sat.outputs['Image'], bright.inputs[1]); ng.links.new(ratio.outputs[0], bright.inputs[2])
        image = bright.outputs[0]
        # Grade the set, preserving the cast's material colours under neutral light.
        mask = ng.nodes.new('CompositorNodeIDMask'); mask.inputs['Index'].default_value = 1; mask.inputs['Anti-Alias'].default_value = True
        ng.links.new(rl.outputs['Object Index'], mask.inputs[0])
        mix = ng.nodes.new('ShaderNodeMixRGB')
        ng.links.new(mask.outputs[0], mix.inputs[0]); ng.links.new(image, mix.inputs[1])
        # Indirect coloured bounce must not recolour the cast either.
        hue = ng.nodes.new('ShaderNodeMixRGB'); hue.blend_type = 'HUE'; hue.inputs[0].default_value = 1
        ng.links.new(rl.outputs['Image'], hue.inputs[1]); ng.links.new(rl.outputs['Diffuse Color'], hue.inputs[2])
        ng.links.new(hue.outputs[0], mix.inputs[2]); image = mix.outputs[0]
    if (sc.get('look_day_interior') and sc.get('daylight_active')) or (sc.get('look_day_exterior') and sc.get('lowkey_active')):
        sat = ng.nodes.new('CompositorNodeHueSat'); sat.inputs['Saturation'].default_value = 1.4 if sc.get('look_day_interior') else DAY_EXT['sat']
        ng.links.new(image, sat.inputs['Image']); image = sat.outputs['Image']
    ng.links.new(image, gl.inputs['Image']); ng.links.new(gl.outputs['Image'], out.inputs[0])
    sc.compositing_node_group = ng


def _lowkey(sc, enabled):
    """Tier-local lighting; retain the R202 state for draft and paired measurements."""
    if not sc.get('lowkey_ready'):
        if not enabled: return
        sc['lowkey_ready'] = True
        sc['lowkey_world'] = sc.world
        sc['lowkey_exposure'] = sc.view_settings.exposure
        sc['lowkey_look'] = sc.view_settings.look
        mood = sc.get('look_mood', 'default')
        night = mood == 'night' or sc.get('look_time') == 'night'
        day_exterior = sc.get('look_outdoor') and sc.get('look_time', 'day') == 'day' and mood in ('default', 'warm', 'cool')
        sc['look_day_exterior'] = bool(day_exterior)
        interior_day = not sc.get('look_outdoor') and mood in ('default', 'warm', 'cool') and not night
        ambient = (1.25 if not sc.get('look_outdoor') else .4) if mood == 'spooky' else (
            1.8 if night else 1.2 if mood == 'sunset' else .7 if interior_day and mood == 'default' else 1)
        for o in list(sc.objects):
            if o.type != 'LIGHT': continue
            o.data['lowkey_energy'] = o.data.energy
            o.data['lowkey_original_color'] = list(o.data.color)
            # Broad fill and infinite suns light the entire set, erasing dark corners.
            o.data.energy *= ((.45 if o.data.type == 'SUN' else .25) if day_exterior else
                             ((.08 if interior_day else .10) if o.data.type == 'SUN' else
                              (.12 if interior_day else .15)) * ambient)
            if day_exterior and o.data.type == 'SUN': o.data.color = (1, .98, .95)
            if night and o.name in ('Sun', 'Window key', 'Huge soft window'): o.data.energy = 0
            o.data['lowkey_dimmed'] = o.data.energy
        original = sc.world
        sc.world = bpy.data.worlds.new('Low key world')
        _world(sc, {'night': (.018, .008, .12), 'cool': (.012, .035, .16),
                    'spooky': (.005, .07, .045), 'warm': (.07, .022, .004),
                    'sunset': (.09, .012, .035)}.get(mood, (.012, .028, .09)), .18)
        if day_exterior: _sky(sc, 'day', DAY_EXT['world'])
        sc['lowkey_dark_world'] = sc.world
        sc.world = original
        key = (1, .98, .95)
        rim = {'warm': (.18, .3, 1), 'sunset': (.5, .12, 1), 'spooky': (.1, 1, .6)}.get(mood, (.16, .28, 1))
        # Cap exposure-adjusted night keys too: living_room's +0.8 EV otherwise clips yellow arms.
        night_exposure = _NIGHT_EXPOSURE.get(sc.get('look_preset'), 0) if mood == 'night' else 0
        key_watts = min(400, 240 * 2 ** -night_exposure) if night else 400
        # Head targets keep the local pools on seated, walking and off-centre cast too.
        for head in [o for o in sc.objects if o.name.endswith(' head mesh')]:
            root = head
            while root.parent: root = root.parent
            receivers = bpy.data.collections.new('Subject light ' + head.name)
            for child in root.children_recursive:
                if child.type == 'MESH':
                    receivers.objects.link(child)
                    child['lowkey_index'] = child.pass_index; child.pass_index = 1
                    for mat in child.data.materials:   # hair keeps its own albedo floor + gloss (rig.hair_floor/hair_shine)
                        if not mat or not mat.use_nodes or 'lowkey_specular' in mat or mat.get('hair'): continue
                        bs = mat.node_tree.nodes.get('Principled BSDF')
                        if bs:
                            mat['lowkey_specular'] = bs.inputs['Specular IOR Level'].default_value
                            # Dark fabric/hair must retain its albedo despite the readable face key.
                            nt = mat.node_tree; base = bs.inputs['Base Color']
                            tone = nt.nodes.new('ShaderNodeMixRGB'); tone.name = 'Low key black retention'; tone.blend_type = 'MULTIPLY'
                            value = nt.nodes.new('ShaderNodeRGBToBW')
                            for socket in (tone.inputs[1], value.inputs[0]):
                                if base.is_linked: nt.links.new(base.links[0].from_socket, socket)
                                else: socket.default_value = base.default_value
                            scale = nt.nodes.new('ShaderNodeMapRange'); scale.clamp = True
                            scale.inputs['From Max'].default_value = .12; scale.inputs['To Min'].default_value = .3   # R-look2: .05 crushed dark cloth to black
                            nt.links.new(value.outputs[0], scale.inputs['Value']); nt.links.new(scale.outputs['Result'], tone.inputs[2])
                            nt.links.new(tone.outputs[0], base)
            # Keep faces lit on reverse-angle cuts without spilling the key over the set.
            frame = bpy.data.objects.new('Low key rig ' + head.name, None)
            sc.collection.objects.link(frame); frame.rotation_euler.x = math.pi / 2
            c = frame.constraints.new('COPY_LOCATION'); c.target = head
            cuts = sorted([(m.frame, m.camera) for m in sc.timeline_markers if m.camera], key=lambda x: x[0])
            if not cuts and sc.camera: cuts = [(sc.frame_start, sc.camera)]
            for cam in dict.fromkeys(cam for _, cam in cuts):
                c = frame.constraints.new('COPY_ROTATION'); c.target = cam
                for f, active in cuts:
                    c.influence = float(active == cam); c.keyframe_insert('influence', frame=f)
            from space import fcurves_of
            for fc in fcurves_of(frame):
                for k in fc.keyframe_points: k.interpolation = 'CONSTANT'
            for role, offset, watts, color, size in (
                    ('key', (.7, -.5, 2.4), DAY_EXT['key'] if day_exterior else key_watts, key, .4 if mood == 'dramatic' else 1.4),
                    ('rim', (-1.2, 1.0, -1.6), 25, rim, .8)):
                o = _light('Low key ' + role + ' ' + head.name, 'AREA', offset, (0, 0, 0), watts, color, size)
                o.parent = frame
                c = o.constraints.new('DAMPED_TRACK'); c.target = head; c.track_axis = 'TRACK_NEGATIVE_Z'
                o.light_linking.receiver_collection = receivers
                o.light_linking.blocker_collection = receivers
                o['lowkey_light'] = True
        if day_exterior:   # broad sky fill from the side opposite the sun (camera side) + warm bounce off the ground, whole set
            sun = next((o for o in sc.objects if o.type == 'LIGHT' and o.name == 'Sun'), None)
            away = -Vector((sun.location.x, sun.location.y, 0)).normalized() if sun else Vector((-1, 0, 0))
            p = away * 9 + Vector((0, -6, 5))
            for name, loc, tgt, watts, col, size in (('Day sky fill', tuple(p), (0, 0, 1.2), DAY_EXT['sky_fill'], (.82, .9, 1), 12),
                                                     ('Day ground bounce', (0, -1.5, .05), (0, -1.5, 3), DAY_EXT['bounce'], (1, .86, .66), 8)):
                _light(name, 'AREA', loc, tgt, watts, col, size)['lowkey_light'] = True
        background = bpy.data.collections.new('Background light receivers')
        for obj in sc.objects:
            if obj.type == 'MESH' and 'lowkey_index' not in obj: background.objects.link(obj)
        if night and sc.get('look_preset') == 'office':
            x0, x1, y0, y1 = sc.get('look_bounds', (-7.5, 7.5, -6, 6))
            practical = _light('Office practical', 'SPOT', (x0*.5, 0, 4.5), (x0+.15, y1*.35, 1.5), 900, (1, .78, .5))
            practical.data.spot_size = math.radians(75); practical.data.spot_blend = .65
            practical.light_linking.receiver_collection = background; practical['lowkey_light'] = True
        sc['lowkey_background_receivers'] = background
        for obj in sc.objects:
            if obj.type != 'LIGHT' or obj.get('lowkey_light'): continue
            if obj.light_linking.receiver_collection:
                obj['lowkey_receivers'] = obj.light_linking.receiver_collection
        sc.frame_set(sc.frame_current)
        for mat in bpy.data.materials:
            if not mat.use_nodes: continue
            for bs in [n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED']:
                if not bs.inputs['Emission Strength'].default_value: continue
                # Legacy classroom has an emissive daytime sky card rather than window holes.
                if night and mat.name.startswith('Sky beyond glass'):
                    mat['lowkey_emission'] = bs.inputs['Emission Strength'].default_value
                    mat['lowkey_color'] = list(bs.inputs['Base Color'].default_value)
                    bs.inputs['Base Color'].default_value = (.006, .009, .055, 1)
                    bs.inputs['Emission Color'].default_value = (.006, .009, .055, 1)
                    bs.inputs['Emission Strength'].default_value = .15
        # Save both material states below so switching back to draft is lossless.
        for mat in bpy.data.materials:
            if 'lowkey_emission' in mat:
                bs = mat.node_tree.nodes.get('Principled BSDF')
                mat['lowkey_dark_color'] = list(bs.inputs['Base Color'].default_value)
                mat['lowkey_dark_emission'] = bs.inputs['Emission Strength'].default_value
    if not sc.get('lowkey_ready'): return
    sc['lowkey_active'] = enabled
    sc.world = sc['lowkey_dark_world'] if enabled else sc['lowkey_world']
    sc.view_settings.exposure = (-.08 if sc.get('look_mood') == 'default' and not sc.get('look_outdoor') else
                                 DAY_EXT['exp'] if sc.get('look_day_exterior') else 0) if enabled else sc['lowkey_exposure']
    sc.view_settings.look = (DAY_EXT['look'] if sc.get('look_day_exterior') else 'AgX - Punchy') if enabled else sc['lowkey_look']
    if enabled and sc.get('look_mood') == 'night' and sc.get('look_preset') in _NIGHT_EXPOSURE:
        sc.view_settings.exposure = _NIGHT_EXPOSURE[sc['look_preset']]
        sc.view_settings.look = 'AgX - Very High Contrast' if sc['look_preset'] == 'office' else 'AgX - High Contrast'
    for o in sc.objects:
        if 'lowkey_index' in o: o.pass_index = 1 if enabled else o['lowkey_index']
        if o.get('lowkey_light'): o.hide_render = not enabled
        elif o.type == 'LIGHT' and 'lowkey_energy' in o.data:
            o.data.energy = o.data['lowkey_dimmed'] if enabled else o.data['lowkey_energy']
            o.light_linking.receiver_collection = sc['lowkey_background_receivers'] if enabled else o.get('lowkey_receivers')
            if 'lowkey_original_color' in o.data:
                o.data.color = (1, .98, .95) if enabled and sc.get('look_day_exterior') and o.data.type == 'SUN' else o.data['lowkey_original_color']
        if o.name.startswith('VFX lightshaft') and enabled and sc.get('look_mood') in ('night', 'spooky'): o.hide_render = True
    for mat in bpy.data.materials:
        if 'lowkey_specular' in mat:
            bs = mat.node_tree.nodes.get('Principled BSDF')
            bs.inputs['Specular IOR Level'].default_value = 0 if enabled else mat['lowkey_specular']
            mat.node_tree.nodes['Low key black retention'].inputs[0].default_value = float(enabled)
        if 'lowkey_emission' not in mat: continue
        bs = mat.node_tree.nodes.get('Principled BSDF')
        color = mat['lowkey_dark_color'] if enabled else mat['lowkey_color']
        bs.inputs['Base Color'].default_value = color; bs.inputs['Emission Color'].default_value = color
        bs.inputs['Emission Strength'].default_value = mat['lowkey_dark_emission'] if enabled else mat['lowkey_emission']


def _daylight(sc, enabled):
    """Keep broad daylight, with a linked coloured edge on the cast; preserve the base state for draft."""
    if enabled and not sc.get('daylight_ready'):
        sc['daylight_ready'] = True
        sc['daylight_exposure'] = sc.view_settings.exposure
        sc['daylight_look'] = sc.view_settings.look
        for o in sc.objects:
            if o.type != 'LIGHT': continue
            o.data['daylight_energy'] = o.data.energy
            o.data['daylight_color'] = list(o.data.color)
        for head in [o for o in sc.objects if o.name.endswith(' head mesh')]:
            root = head
            while root.parent: root = root.parent
            receivers = bpy.data.collections.new('Day rim receivers ' + head.name)
            for child in root.children_recursive:
                if child.type == 'MESH': receivers.objects.link(child)
            color = {'warm': (.18, .38, 1), 'cool': (.3, .8, 1)}.get(sc.get('look_mood'), (.25, .55, 1))
            rim = _light('Day rim ' + head.name, 'AREA', (-1.5, 1.2, 1), (0, 0, 0), 160, color, 1)
            rim.parent = head
            track = rim.constraints.new('DAMPED_TRACK'); track.target = head; track.track_axis = 'TRACK_NEGATIVE_Z'
            rim.light_linking.receiver_collection = receivers
            rim.light_linking.blocker_collection = receivers
            rim['day_rim'] = True
    if not sc.get('daylight_ready'): return
    sc['daylight_active'] = enabled
    for o in sc.objects:
        if o.type != 'LIGHT' or 'daylight_energy' not in o.data: continue
        original = o.data['daylight_energy']; fill = 1980 if sc.get('look_mood') == 'cool' else 1800
        o.data.energy = (fill if o.name in ('Front fill', 'Front softbox') else original * .45) if enabled else original
        o.data.color = tuple(.6 + .4*c for c in o.data['daylight_color']) if enabled else o.data['daylight_color']
    sc.view_settings.exposure = (_DAY_EXPOSURE[sc['look_preset']] - (.1 if sc.get('look_mood') == 'warm' else 0)) if enabled else sc['daylight_exposure']
    sc.view_settings.look = 'AgX - Punchy' if enabled else sc['daylight_look']


LOCAL = {'mid': 32, 'preview': 8}   # local GPU tiers -> spp: the cloud hq look at 50 % (540x960), Lanczos to 1080x1920 at assembly


def alpha_mode(sc, keep, shadow=True):
    """Transparent render for motion graphics (farm_run.py --alpha / --cutout): only the cast members in `keep` (and their
    effects: VFX objects other than set dressing) are seen by the camera, on a transparent film, 16-bit RGBA PNG (straight
    alpha). The set is invisible to every ray (cloud test: a set kept for bounce greyed the whole shadow catcher); with `shadow`, a
    shadow-catcher floor at z=0 keeps the cast's contact shadows. Returns the number of hidden objects."""
    import bpy
    def root(o):
        while o.parent: o = o.parent
        return o
    setish = ('VFX hill', 'VFX lightshaft', 'VFX sky', 'VFX ground', 'VFX cloud')
    n = 0
    for o in bpy.data.objects:
        if o.type in ('LIGHT', 'CAMERA'): continue
        r = root(o).name
        if r in keep or (o.name.startswith('VFX') and not o.name.startswith(setish)): continue
        o.visible_camera = o.visible_shadow = o.visible_diffuse = o.visible_glossy = False   # no bounce either: a set that only
        o.visible_transmission = o.visible_volume_scatter = False; n += 1                      # blocks indirect light greys the whole catcher
    if shadow:
        me = bpy.data.meshes.new('Alpha shadow catcher'); s_ = 400.0
        me.from_pydata([(-s_, -s_, 0), (s_, -s_, 0), (s_, s_, 0), (-s_, s_, 0)], [], [(0, 1, 2, 3)])
        ob = bpy.data.objects.new('Alpha shadow catcher', me); sc.collection.objects.link(ob); ob.is_shadow_catcher = True
    sc.render.film_transparent = True
    im = sc.render.image_settings; im.file_format = 'PNG'; im.color_mode = 'RGBA'; im.color_depth = '16'
    return n


def turntable(sc, frame, keep=None):
    """Turntable for motion graphics (farm_run.py --turntable N:F): freeze the scene at `frame`, take the camera active there, drop its
    animation and the shot markers, and parent it to a pivot at the centre of the cast roots in `keep` (all roots of the cast when
    None). Returns the pivot: rotate pivot.rotation_euler.z through 0..2*pi to orbit the camera."""
    import bpy
    sc.frame_set(frame)
    cam = next((m.camera for m in sorted(sc.timeline_markers, key=lambda m: m.frame) if m.camera and m.frame <= frame), None) or sc.camera
    for m in list(sc.timeline_markers): m.camera = None
    sc.camera = cam; mw = cam.matrix_world.copy(); cam.animation_data_clear(); cam.matrix_world = mw
    roots = [o for o in bpy.data.objects if not o.parent and o.type == 'EMPTY' and (keep is None or o.name in keep) and o.children]
    from mathutils import Vector
    c = sum((o.matrix_world.translation for o in roots), Vector()) / max(1, len(roots))
    piv = bpy.data.objects.new('Turntable pivot', None); sc.collection.objects.link(piv); piv.location = (c.x, c.y, 0)
    sc.view_layers[0].update(); cam.parent = piv; cam.matrix_parent_inverse = piv.matrix_world.inverted(); cam.matrix_world = mw
    return piv


def hq_shots(sc):
    """What farm_hq.py does per shot on top of the hq tier (shared by the local mid/preview tiers)."""
    for o in bpy.data.objects:   # R211: camera motion blur ghosted whole frames at cuts (critic R206 frame 9: a marker cut samples the
        if o.type == 'CAMERA': o.cycles.use_motion_blur = False   # next camera outside its shot); moves are slow push-ins, characters still blur
    return 0 if os.environ.get('LOOK_SHAFT_KEEP') == '1' else shafts_off_in_front(sc)   # env = evidence only: the pre-R224 milky veil


def shafts_off_in_front(sc):
    """R224 a camera INSIDE a window light-shaft volume (or looking through one within 6 m) renders a milky veil over the whole
    frame (factory kitchen Short: lum 0.54 -> 0.31, contrast 0.48 -> 0.83 with the shaft hidden). Hide such a shaft for that
    shot only (constant keys at the marker cuts); every other shot keeps its window light."""
    shafts = [o for o in bpy.data.objects if o.name.startswith('VFX lightshaft')]
    marks = sorted((m.frame, m.camera) for m in sc.timeline_markers if m.camera)
    if not shafts or not marks: return 0
    def hits(o, cam, f):
        sc.frame_set(f); inv = o.matrix_world.inverted(); bb = [Vector(c) for c in o.bound_box]
        lo = Vector([min(c[i] for c in bb) for i in range(3)]) - Vector((.05,) * 3); hi = Vector([max(c[i] for c in bb) for i in range(3)]) + Vector((.05,) * 3)
        p0 = cam.matrix_world.translation; d = cam.matrix_world.to_3x3() @ Vector((0, 0, -1))
        for k in range(13):   # sample the view segment 0..6 m in object space
            q = inv @ (p0 + d * (k * 0.5))
            if all(lo[i] <= q[i] <= hi[i] for i in range(3)): return True
        return False
    n = 0
    for o in shafts:
        o.hide_render = False; o.keyframe_insert('hide_render', frame=sc.frame_start)
    for i, (f0, cam) in enumerate(marks):
        f1 = marks[i + 1][0] - 1 if i + 1 < len(marks) else sc.frame_end
        for o in shafts:
            bad = any(hits(o, cam, f) for f in {f0, (f0 + f1) // 2, f1})
            o.hide_render = bad; o.keyframe_insert('hide_render', frame=f0); n += bad
    # bool keys always step: the hide holds exactly from cut to cut
    print(f'SHAFTS hidden in {n} shot(s) (camera inside or looking through)', flush=True)
    return n


def todo_frames(out, frames, key):
    """Local tiers render resumably: frames already in <out> from the same key (spec + engine code) are skipped, a different or
    missing key starts the folder clean, a PNG cut off mid-write (no IEND trailer) is rendered again."""
    import shutil
    from pathlib import Path
    out = Path(out); stamp = out / 'key.txt'
    if out.exists() and (not stamp.exists() or stamp.read_text() != key): shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True); stamp.write_text(key)
    def done(p):
        try:
            with open(p, 'rb') as fh: fh.seek(-12, 2); return fh.read(8)[4:] == b'IEND'
        except OSError: return False
    return [f for f in frames if not done(out / f'{f:04d}.png')]


RESR = os.environ.get('REALESRGAN', 'realesrgan-ncnn-vulkan')


def frame_size(sc):
    """(width, height) of the final video: story key 'frame' (B1, e.g. [1920, 1080]) or the Short default 1080x1920."""
    f = sc.get('frame'); return (int(f[0]), int(f[1])) if f else (1080, 1920)


def upscale(out, up, size=(1080, 1920)):
    """-> (frames dir, ffmpeg -vf args) for the 1080x1920 video: ENGINE_UPSCALE=realesrgan + the exe present -> Real-ESRGAN x2 frames
    in <up>; otherwise Lanczos in ffmpeg (the farm's upscale)."""
    import subprocess
    from pathlib import Path
    if os.environ.get('ENGINE_UPSCALE') == 'realesrgan' and os.path.exists(RESR):
        Path(up).mkdir(parents=True, exist_ok=True)
        r = subprocess.run([RESR, '-i', str(out), '-o', str(up), '-n', 'realesr-animevideov3', '-s', '2', '-f', 'png'], capture_output=True, text=True)
        if r.returncode == 0: return Path(up), ['-vf', f'scale={size[0]}:{size[1]}:flags=lanczos']   # x2 is already 1080x1920; the scale is a guard
        print('WARNING Real-ESRGAN failed, Lanczos instead:', r.stderr[-300:], flush=True)
    return Path(out), ['-vf', f'scale={size[0]}:{size[1]}:flags=lanczos']


def tier(sc, name, device=None):
    if name in LOCAL:   # mid / preview: the hq tier + farm_hq's per-shot fixes, then local resolution and samples
        tier(sc, 'hq', device=device); hq_shots(sc)
        sc.render.resolution_percentage, sc.cycles.samples = 50, LOCAL[name]
        return
    r = sc.render
    atmosphere = name != 'draft' and os.environ.get('LOOK_ATMOSPHERE', '1') != '0'
    # Cap saved window-beam shaders too: off-axis shafts can evade the farm's camera-ray check.
    for mat in bpy.data.materials:
        if mat.name.startswith('lightshaft beam') and mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == 'EMISSION': node.inputs['Strength'].default_value = min(node.inputs['Strength'].default_value, 1)
    for o in bpy.data.objects:
        if o.name.startswith('VFX lightshaft'): o.hide_render = name == 'draft'      # window light is a look/final/hq extra; draft stays as fast as before
        if o.name.startswith('VFX window dust'): o.hide_render = not atmosphere
    # R230: bright day interiors keep broad light and the original world; low-key is reserved for other moods/exteriors.
    day_interior = (not sc.get('look_outdoor') and sc.get('look_mood', 'default') in ('default', 'warm', 'cool')
                    and sc.get('look_time', 'day') != 'night' and os.environ.get('LOOK_LOWKEY_DAY_INTERIOR', '0') != '1')
    sc['look_day_interior'] = bool(day_interior)
    enabled = name != 'draft' and os.environ.get('LOOK_LOWKEY', '1') != '0'
    if day_interior:
        _lowkey(sc, False)
        _daylight(sc, enabled and sc.get('look_preset') in _DAY_EXPOSURE)
    else:
        _daylight(sc, False)
        _lowkey(sc, enabled)
    for o in sc.objects:
        if o.get('day_rim'): o.hide_render = not (atmosphere and sc.get('daylight_active') and os.environ.get('LOOK_RIM', '1') != '0')
        if o.name.startswith('VFX weather'): o.hide_render = not atmosphere
    if not atmosphere and name != 'hq' and sc.compositing_node_group and sc.compositing_node_group.get('look_atmosphere'):
        sc.compositing_node_group = None
    r.resolution_x, r.resolution_y = (v // 2 for v in frame_size(sc))   # B1: half of the story frame (default 540x960)
    r.image_settings.file_format = 'PNG'
    if name == 'draft':
        ids = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]
        r.engine = 'BLENDER_WORKBENCH' if 'BLENDER_WORKBENCH' in ids else ids[0]
        r.resolution_percentage = 50
        sh = sc.display.shading
        sh.light = 'STUDIO'; sh.color_type = 'TEXTURE'; sh.show_shadows = True; sh.shadow_intensity = 0.35
        sh.show_cavity = False; sc.display.render_aa = 'FXAA'
        if r.engine == 'BLENDER_EEVEE': sc.eevee.taa_render_samples = 8   # 5.2 headless has no Workbench -> EEVEE; 64 -> 8 samples = 3x faster, same image (R122: mean diff 0.3/255)
        return
    r.engine = 'CYCLES'
    sc.cycles.use_denoising = True; sc.cycles.max_bounces = 6; sc.cycles.diffuse_bounces = 3; sc.cycles.glossy_bounces = 3
    r.use_persistent_data = True
    sc.cycles.samples, r.resolution_percentage = (8, 50) if name == 'look' else (32, 100)
    if name == 'hq':   # TRUE high quality (cloud A100s): native 1080x1920, 128 spp + denoise, motion blur, bloom on highlights
        (r.resolution_x, r.resolution_y), r.resolution_percentage = frame_size(sc), 100
        sc.cycles.samples = 128; sc.cycles.use_adaptive_sampling = True; sc.cycles.adaptive_threshold = 0.01
        sc.cycles.max_bounces = 8; sc.cycles.diffuse_bounces = 4; sc.cycles.glossy_bounces = 4
        sc.cycles.denoiser = 'OPENIMAGEDENOISE'   # the cloud driver has no OptiX libs; OIDN is GPU-agnostic
        r.use_motion_blur = True; r.motion_blur_shutter = 0.35   # short shutter: snappy Roblox moves stay crisp, fast ones streak a little
    if atmosphere or name == 'hq': _bloom(sc, atmosphere=atmosphere)
    want = device or os.environ.get('RENDER_DEV')
    pr = bpy.context.preferences.addons['cycles'].preferences
    for dev in [want] if want else ['OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI']:   # auto: first GPU backend with a device
        try: pr.compute_device_type = dev
        except TypeError: continue   # backend not in this Blender build
        pr.get_devices()
        for d in pr.devices: d.use = d.type == dev
        if any(d.use for d in pr.devices):
            sc.cycles.device = 'GPU'
            print('RENDER DEVICE', dev, '|', ', '.join(d.name for d in pr.devices if d.use), flush=True)
            break
    else:
        print('WARNING no', want or 'OPTIX/CUDA/HIP/METAL/ONEAPI', 'GPU, rendering on CPU (slow)', flush=True)
