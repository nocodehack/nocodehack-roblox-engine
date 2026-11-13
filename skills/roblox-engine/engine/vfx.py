"""Baked R6 effects. World points are metres; colors are hex or linear RGB.

Emission shaders render in Cycles; matching diffuse colors render in Workbench.
All effects return lists of their created objects, including lights.
"""
import math
import os
import random

import bpy
from pathlib import Path
from mathutils import Vector, Matrix

import rig

S = rig.S


def _material(color):
    name = 'VFX ' + str(color)
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = rig.material(name, color)
    rgb = m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value[:3]
    m.diffuse_color = (*rgb, 1)
    nt = m.node_tree
    emission = nt.nodes.new('ShaderNodeEmission')
    emission.inputs['Color'].default_value = (*rgb, 1)
    emission.inputs['Strength'].default_value = 5
    nt.links.new(emission.outputs[0], nt.nodes['Material Output'].inputs['Surface'])
    return m


def _glow(color, strength=12.0, hot=False):
    """Energy material for the HQ tier: hot=True = a plain very bright emitter (blooms white-hot); else a SOFT glow shell
    (bright where the surface faces the lens, fading to nothing at its silhouette) so a beam reads as light, not as a painted tube."""
    name = f'VFX glow {color} {strength} {hot}'
    m = bpy.data.materials.get(name)
    if m: return m
    base = _material(color); rgb = base.diffuse_color[:3]
    m = bpy.data.materials.new(name); m.use_nodes = True; m.diffuse_color = (*rgb, 1 if hot else .45); nt = m.node_tree
    for n in list(nt.nodes): nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial'); em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*rgb, 1); em.inputs['Strength'].default_value = strength
    if hot:
        nt.links.new(em.outputs[0], out.inputs['Surface'])
    else:
        lw = nt.nodes.new('ShaderNodeLayerWeight'); lw.inputs['Blend'].default_value = .35
        pw = nt.nodes.new('ShaderNodeMath'); pw.operation = 'POWER'; pw.inputs[1].default_value = .6
        tr = nt.nodes.new('ShaderNodeBsdfTransparent'); mx = nt.nodes.new('ShaderNodeMixShader')
        nt.links.new(lw.outputs['Facing'], pw.inputs[0]); nt.links.new(pw.outputs[0], mx.inputs[0])
        nt.links.new(em.outputs[0], mx.inputs[1]); nt.links.new(tr.outputs[0], mx.inputs[2]); nt.links.new(mx.outputs[0], out.inputs['Surface'])
        try: m.blend_method = 'BLEND'
        except Exception: pass
    return m


def _key(obj, path, frame, value):
    setattr(obj, path, value)
    obj.keyframe_insert(path, frame=frame)


def _life(obj, f0, f1):
    if f1 < f0:
        raise ValueError('effect end must follow start')
    # Hidden keys prevent first/last-key extrapolation from leaking into other shots.
    for f, hidden in ((f0 - 1, True), (f0, False), (f1, False), (f1 + 1, True)):
        for path in ('hide_render', 'hide_viewport'):
            _key(obj, path, f, hidden)


def _at(sc, frame):
    sc.frame_set(frame)
    bpy.context.view_layer.update()


def _sphere(name, point, radius, material):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=radius, location=point)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def _star(name, point, radius, material, rays=8):
    vertices = [(0, 0, 0)]
    for i in range(rays * 2):
        a = math.pi * i / rays
        r = radius if i % 2 == 0 else radius * .24
        vertices.append((math.cos(a) * r, 0, math.sin(a) * r))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], [(0, i + 1, (i + 1) % (rays * 2) + 1) for i in range(rays * 2)])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.location = point
    obj.data.materials.append(material)
    return obj


def _impact_flash_v1(sc, point, frame, color='#FFF19A', size=1.0):
    objects = []
    for i in range(2):
        obj = _star('Impact burst', point, .65, _material(color))
        obj.rotation_euler.z = i * math.pi / 2
        _life(obj, frame, frame + 4)
        for f, k in ((frame, .15), (frame + 1, 1.25), (frame + 3, .7), (frame + 4, 0)):
            _key(obj, 'scale', f, (k * size,) * 3)
        objects.append(obj)
    data = bpy.data.lights.new('Impact light', 'POINT')
    data.color = _material(color).diffuse_color[:3]
    data.shadow_soft_size = .5
    light = bpy.data.objects.new('Impact light', data)
    bpy.context.collection.objects.link(light)
    light.location = point
    _life(light, frame, frame + 4)
    for f, watts in ((frame - 1, 0), (frame, 300 * size), (frame + 1, 500 * size), (frame + 4, 0)):
        _key(data, 'energy', f, watts)
    return objects + [light]


def _energy_beam_v1(sc, start_point, end_point, f0, f1, color='#49BFFF', size=1.0, style='full'):
    delta = Vector(end_point) - Vector(start_point)
    if delta.length < 1e-6 or f1 - f0 < 3:
        raise ValueError('beam needs distinct endpoints and at least three frames')
    objects = []
    # A wire shell keeps the white core readable in opaque Workbench shading.
    big = size > 1.5
    if big: sc['big_beam'] = True   # look._bloom raises the glare for scenes that hold a big beam
    # thin white-hot core (clips to pure white, blooms), semi-transparent coloured body, faint wide halo; size 1.8 = ~1.8x the old tube
    rc, rg, rh = (.07 * size, .23 * size, .40 * size) if big else (.10 * size, .23 * size, .52 * size)
    for name, radius, material in (('Beam core', rc, _glow('#FFFFFF', 90.0 if big else 45.0, hot=True)), ('Beam glow', rg, _glow(color, 5.0 if big else 16.0)),
                                   ('Beam halo', rh, _glow(color, 2.0 if big else 4.0))):   # white-hot core, soft coloured body, wide faint halo (HQ still R-show: the flat tube + wire cage read as a painted ribbon)
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=radius, depth=1)
        obj = bpy.context.object
        obj.name = name
        obj.data.materials.append(material)
        obj.rotation_euler = delta.to_track_quat('Z', 'Y').to_euler()
        obj.visible_shadow = False
        _life(obj, f0, f1)
        for f in range(f0, f1 + 1):
            growth = min(1, (f - f0 + 1) / 3)
            fade = min(1, (f1 - f) / 3)
            radius_scale = fade * (1 + .12 * math.sin((f - f0) * 2.4))
            _key(obj, 'location', f, Vector(start_point) + delta * growth / 2)
            _key(obj, 'scale', f, (radius_scale, radius_scale, delta.length * growth))
        objects.append(obj)
    if big and style == 'full': objects += beam_flames(sc, start_point, end_point, f0, f1, color, size)
    if big:   # a HUGE beam: a bright head that races to the far end over ~4 frames, and a blue light that rides along it
        S0, S1 = Vector(start_point), Vector(end_point)
        head = _sphere('Beam head', S0, 1, _glow('#FFFFFF', 45.0, hot=True)); _life(head, f0, f1); objects.append(head)
        glow = _sphere('Beam head glow', S0, 1, _glow(color, 10.0)); _life(glow, f0, f1); objects.append(glow)
        for f in range(f0, f1 + 1):
            u = min(1.0, (f - f0 + 1) / 4); fade = min(1, (f1 - f) / 3); pulse = 1 + .1 * math.sin((f - f0) * 2.2)
            settle_ = 1.0 - .6 * min(1.0, max(0.0, (f - f0 - 4) / 6))   # the travelling head shrinks to a small glow once it has arrived (it hid the pose)
            for o, k in ((head, .36), (glow, .8)):
                _key(o, 'location', f, S0 + (S1 - S0) * u); _key(o, 'scale', f, (k * size / 3 * 1.4 * fade * pulse * settle_,) * 3)
        data = bpy.data.lights.new('Beam light', 'POINT'); data.color = _material(color).diffuse_color[:3]; data.shadow_soft_size = 1.5
        lamp = bpy.data.objects.new('Beam light', data); bpy.context.collection.objects.link(lamp); _life(lamp, f0, f1); objects.append(lamp)
        for f in range(f0, f1 + 1):
            u = min(1.0, (f - f0 + 1) / 4); mid = S0 + (S1 - S0) * (u * .5)
            _key(lamp, 'location', f, mid + Vector((0, 0, .6))); _key(data, 'energy', f, 6000 * min(1, (f1 - f) / 3))
    return objects


def beam_flames(sc, start_point, end_point, f0, f1, color, size, seed=31):
    """ANIMATED body of a big beam: the aura's flame-tongue sprites (the effect that looks good in HQ) as additive cards laid along the
    beam, tongues streaming toward the target, flickering in length/width every frame, turned toward the active camera."""
    import random
    if not (AURA_DIR / f'{AURA_TONGUES[0]}.png').exists(): return []
    rnd = random.Random(seed + f0); S0, S1 = Vector(start_point), Vector(end_point); d = S1 - S0; L = d.length; z = d.normalized()
    try: sc.cycles.transparent_max_bounces = max(sc.cycles.transparent_max_bounces, 64)
    except AttributeError: pass
    objects = []; seg = 1.6; n = max(2, int(math.ceil(L / seg * 1.5)))
    for i in range(n):
        u0 = i / n; mat = _sprite_material(AURA_TONGUES[i % len(AURA_TONGUES)], color, 5.0, 1.0)
        obj = _card('VFX beam flame', .5 * size * 1.5, seg * 1.3, mat); objects.append(obj); _life(obj, f0, f1)
        for f in range(f0, f1 + 1):
            _at(sc, f); u = min(1.0, (f - f0 + 1) / 4); fade = min(1, (f1 - f) / 3)
            if u0 > u: _key(obj, 'scale', f, (0, 1, 0)); continue
            mid = S0 + d * u0 + z * (seg * .5 * ((f * 3 + i * 5) % 7) / 7) ; cam = sc.camera
            v = (cam.matrix_world.translation - mid) if cam else Vector((0, -1, 0)); y = v - z * v.dot(z)
            y = y.normalized() if y.length > 1e-6 else Vector((0, -1, 0)); x = y.cross(z).normalized()
            obj.rotation_euler = Matrix((x, y, z)).transposed().to_euler()
            lat = rnd.uniform(-.1, .1) * size
            _key(obj, 'location', f, mid - z * seg * .65 + x * lat); _key(obj, 'rotation_euler', f, obj.rotation_euler)
            fl = rnd.uniform(.75, 1.15) * fade; _key(obj, 'scale', f, (rnd.uniform(.8, 1.2) * fl, 1, fl))
    return objects


def _ring_flash_v1(sc, point, axis, frame, size=1.0, color='#FFFFFF'):
    """An expanding bright ring (axis = the beam direction) plus a flash: the muzzle on fire and the palm that takes the beam."""
    objects = []; ax = Vector(axis).normalized()
    for k, (r0, r1, tint) in enumerate(((.15, 1.05, color), (.08, .7, '#9FE3FF'))):
        bpy.ops.mesh.primitive_torus_add(major_radius=1.0, minor_radius=.035 + .02 * (1 - k), major_segments=32, minor_segments=8)
        o = bpy.context.object; o.name = 'Beam ring'; o.data.materials.append(_glow(tint, 60.0, hot=True)); o.visible_shadow = False
        o.rotation_euler = ax.to_track_quat('Z', 'Y').to_euler(); _life(o, frame, frame + 9); objects.append(o)
        for f, s in ((frame, r0 * size), (frame + 3, (r0 + r1) / 2 * size), (frame + 9, r1 * size * 1.15)):
            _key(o, 'location', f, point); _key(o, 'scale', f, (s, s, s * (1 if f < frame + 9 else .01)))
    objects += impact_flash(sc, point, frame, '#FFFFFF', size=1.6 * size)
    return objects


def _palm_sparks_v1(sc, point, f0, f1, seed=41):
    """Hot streaks and sparks flying off the palm that holds a beam (tiny white-hot bits on ballistic arcs, a new burst every 3 frames)."""
    import random
    rnd = random.Random(seed + f0); objects = []; P = Vector(point); k = 0
    for f in range(f0, f1, 3):
        for j in range(4):
            a = rnd.uniform(0, math.tau); up = rnd.uniform(.2, 1.0); sp = rnd.uniform(.8, 2.2); life = 8
            o = _sphere('Palm spark', P, 1, _glow('#FFFFFF', 70.0, hot=True)); o.visible_shadow = False; _life(o, f, f + life); objects.append(o)
            for t in range(life + 1):
                u = t / life; q = P + Vector((math.cos(a) * sp * u, math.sin(a) * sp * u, up * 2 * u - 2.4 * u * u))
                _key(o, 'location', f + t, q); _key(o, 'scale', f + t, (.045 * (1 - u * .6),) * 3)
    return objects


def beam_debris(sc, start_point, end_point, f0, f1, seed=21):
    """Dust and small rocks blown away along the ground under a big beam (they fly out sideways and up, then fall)."""
    import random
    rnd = random.Random(seed + f0); objects = []; A = Vector(start_point); B = Vector(end_point); d = B - A; d.z = 0
    if d.length < 1e-3: return objects
    side = Vector((-d.y, d.x, 0)).normalized(); rm = _material('#8A6A4C')
    for i in range(14):   # rocks
        u = rnd.uniform(.05, .95); P = Vector((A.x, A.y, 0)) + d * u; t0 = f0 + int(u * 6) + rnd.randint(0, 4); s = rnd.choice((-1, 1))
        o = _rock('VFX beam rock', P, rnd.uniform(.08, .2), rm, rnd); _life(o, t0, t0 + 20); objects.append(o)
        for k in range(21):
            t = k / 20; q = P + side * s * rnd.uniform(.8, 1.0) * 2.5 * t + d.normalized() * 1.0 * t + Vector((0, 0, 4 * rnd.uniform(.8, 1.6) * t * (1 - t) + .05))
            _key(o, 'location', t0 + k, q); _key(o, 'rotation_euler', t0 + k, (t * 7, t * 5, 0))
    for i in range(12):   # dust
        u = rnd.uniform(.05, .95); P = Vector((A.x, A.y, .1)) + d * u; t0 = f0 + int(u * 6) + rnd.randint(0, 6)
        if _v2('dust_burst'):
            objects.append(_puff(sc, 'VFX beam dust', P + Vector((0, 0, .3)), t0, t0 + 14, rnd.uniform(1.0, 1.5), side * rnd.choice((-1, 1)) * 3.0 + Vector((0, 0, 1.2)), rnd, _viewer(sc))); continue
        o = _sphere('VFX beam dust', P, .3, _material('#BDAA83')); _life(o, t0, t0 + 14); objects.append(o)
        for dt, k, r, z in ((0, .1, 0, 0), (5, 1.0, 1.0, .4), (14, 0, 2.0, 1.0)):
            _key(o, 'location', t0 + dt, P + side * rnd.choice((-1, 1)) * r + Vector((0, 0, z))); _key(o, 'scale', t0 + dt, (k * 1.2,) * 3)
    return objects


def _charge_ball_v1(sc, ch, hand, f0, f1, color='#49BFFF', k=1.0):
    if (hand not in rig.SIDE and hand != 'both') or f1 <= f0:
        raise ValueError('charge_ball needs R/L/both and a positive interval')
    obj = _sphere('Charge ball', (0, 0, 0), 1, _glow(color, 14.0)); obj.visible_shadow = False
    core = _sphere('Charge core', (0, 0, 0), 1, _glow('#FFFFFF', 45.0, hot=True)); core.visible_shadow = False; _life(core, f0, f1)   # white-hot heart inside the soft ball
    _life(obj, f0, f1)
    hs = 'RL' if hand == 'both' else hand   # 'both': the ball floats between the two cupped hands
    tips = {h: Vector((rig.SIDE[h] * .5 * S, 0, -1.9 * S)) for h in hs}
    for f in range(f0, f1 + 1):
        _at(sc, f)
        p = sum((ch.arm[h].matrix_world @ tips[h] for h in hs), Vector()) / len(hs)
        size = (.06 + .30 * (f - f0) / (f1 - f0)) * (1 + .06 * math.sin(f * 2)) * k
        _key(obj, 'location', f, p)
        _key(obj, 'scale', f, (size,) * 3)
        _key(core, 'location', f, p); _key(core, 'scale', f, (size * .45,) * 3)
    return [obj, core]


def _aura_material(color):
    """Translucent flame: emission mixed with transparency, fading from the base to the tips (a Roblox Super Saiyan aura is
    a glowing see-through flame; the opaque emission shells hid the body, R165 ssj_test)."""
    name = 'VFX aura ' + str(color)
    m = bpy.data.materials.get(name)
    if m:
        return m
    base = _material(color); rgb = base.diffuse_color[:3]
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree
    for n_ in list(nt.nodes):
        if n_.type != 'OUTPUT_MATERIAL': nt.nodes.remove(n_)
    out = next(n_ for n_ in nt.nodes if n_.type == 'OUTPUT_MATERIAL')
    em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (*rgb, 1); em.inputs['Strength'].default_value = 4
    tr = nt.nodes.new('ShaderNodeBsdfTransparent'); mix = nt.nodes.new('ShaderNodeMixShader')
    tc = nt.nodes.new('ShaderNodeTexCoord'); sep = nt.nodes.new('ShaderNodeSeparateXYZ'); ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.0; ramp.color_ramp.elements[0].color = (0.45, 0.45, 0.45, 1)   # 55 % see-through at the base
    ramp.color_ramp.elements[1].position = 1.0; ramp.color_ramp.elements[1].color = (1, 1, 1, 1)            # fully clear at the tips
    nt.links.new(tc.outputs['Generated'], sep.inputs[0]); nt.links.new(sep.outputs['Z'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], mix.inputs['Fac']); nt.links.new(em.outputs[0], mix.inputs[1]); nt.links.new(tr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    m.diffuse_color = (*rgb, 0.4)   # draft (Workbench) shows it semi-transparent too
    for attr, val in (('surface_render_method', 'BLENDED'), ('blend_method', 'BLEND')):
        if hasattr(m, attr):
            try: setattr(m, attr, val)
            except Exception: pass
    return m


AURA_DIR = Path(__file__).resolve().parent / 'assets' / 'vfx' / 'aura_ref' / 'ssj_8092379429'
AURA_TONGUES = ('6954174382', '7451697448', '6741260601')   # Roblox SSJ aura flame-tongue sprites (Creator Store 8092379429)
AURA_CLOUDS = ('7451746284', '7451831540')                  # soft smoke clouds behind the tongues
KENNEY = AURA_DIR.parent.parent / 'kenney_particles'        # CC0 sprites (assets/vfx/LICENSES.md): the VFX v2 toolkit below


def _sprite_material(tex_id, color, strength=3.0, alpha_k=1.0, mode='add', soft=False):
    """ADDITIVE-looking sprite: emission (texture x tint) where the sprite alpha is, transparent elsewhere (Roblox emitters use
    LightEmission 1 = additive: overlaps blow out toward white)."""
    name = f'VFX sprite {tex_id} {color} {alpha_k} {strength} {mode} {soft}'
    m = bpy.data.materials.get(name)
    if m:
        return m
    rgb = _material(color).diffuse_color[:3]
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree
    for n_ in list(nt.nodes):
        if n_.type != 'OUTPUT_MATERIAL': nt.nodes.remove(n_)
    out = next(n_ for n_ in nt.nodes if n_.type == 'OUTPUT_MATERIAL')
    tex = nt.nodes.new('ShaderNodeTexImage'); path = AURA_DIR / f'{tex_id}.png'
    tex.image = bpy.data.images.load(str(path if path.exists() else KENNEY / f'{tex_id}.png'), check_existing=True)
    tint = nt.nodes.new('ShaderNodeMix'); tint.data_type = 'RGBA'; tint.blend_type = 'MULTIPLY'; tint.inputs['Factor'].default_value = 1.0
    nt.links.new(tex.outputs['Color'], tint.inputs['A']); tint.inputs['B'].default_value = (*rgb, 1)
    em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Strength'].default_value = strength
    nt.links.new(tint.outputs['Result'], em.inputs['Color'])
    # coverage = alpha x brightness: Roblox additive sprites are opaque black-background images (black = no light), clouds
    # carry real alpha; the product handles both (opaque alpha gave black cards, R167)
    bw = nt.nodes.new('ShaderNodeRGBToBW'); nt.links.new(tex.outputs['Color'], bw.inputs['Color'])
    bwv = bw.outputs['Val']
    if mode == 'mix':   # a puff's density = the sprite's DISPLAY grey (sqrt of the linear value): linear mid-grey smoke was 20 % dense, nearly invisible
        pw = nt.nodes.new('ShaderNodeMath'); pw.operation = 'POWER'; pw.inputs[1].default_value = .5; nt.links.new(bwv, pw.inputs[0]); bwv = pw.outputs[0]
    ab = nt.nodes.new('ShaderNodeMath'); ab.operation = 'MULTIPLY'; nt.links.new(tex.outputs['Alpha'], ab.inputs[0]); nt.links.new(bwv, ab.inputs[1])
    k = nt.nodes.new('ShaderNodeMath'); k.operation = 'MULTIPLY'; k.use_clamp = True; k.inputs[1].default_value = 2.0 * alpha_k
    nt.links.new(ab.outputs[0], k.inputs[0])
    # TRUE ADDITIVE (Roblox LightEmission 1): fully transparent + emission scaled by coverage -> only ever ADDS light; the
    # mix-with-transparent version darkened the face behind dim sprite pixels (dark smear on SSJ Goku, R178)
    cov = k.outputs[0]
    def mth(op, a, b=None, c=None):
        n_ = nt.nodes.new('ShaderNodeMath'); n_.operation = op
        for i, v in enumerate((a, b, c)):
            if v is None: continue
            if isinstance(v, (int, float)): n_.inputs[i].default_value = v
            else: nt.links.new(v, n_.inputs[i])
        return n_.outputs[0]
    if soft:   # toolkit sprites: per-card fade (object colour alpha, keyed) and a soft falloff to the card border (no square ever shows)
        cov = mth('MULTIPLY', cov, nt.nodes.new('ShaderNodeObjectInfo').outputs['Alpha'])
        uvm = nt.nodes.new('ShaderNodeUVMap'); uvm.uv_map = 'Mask'; sep = nt.nodes.new('ShaderNodeSeparateXYZ'); nt.links.new(uvm.outputs['UV'], sep.inputs[0])
        for ax in 'XY': cov = mth('MULTIPLY', cov, mth('SUBTRACT', 1.0, mth('POWER', mth('ABSOLUTE', mth('MULTIPLY_ADD', sep.outputs[ax], 2.0, -1.0)), 8.0)))
    tr = nt.nodes.new('ShaderNodeBsdfTransparent')
    if mode == 'mix':   # DUST / SMOKE / DIRT: a lit, see-through puff (diffuse + translucent so a back-lit card is not black) that hides what is behind it by its coverage
        em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (*rgb, 1); em.inputs['Strength'].default_value = strength
        dif = nt.nodes.new('ShaderNodeBsdfDiffuse'); tl = nt.nodes.new('ShaderNodeBsdfTranslucent')
        shade = nt.nodes.new('ShaderNodeMix'); shade.data_type = 'RGBA'   # the sprite's own light and dark give the puff its body (a flat colour read as a disc)
        shade.inputs['A'].default_value = (*[c * .75 for c in rgb], 1); shade.inputs['B'].default_value = (*[min(1.0, c * 1.25) for c in rgb], 1)
        nt.links.new(bwv, shade.inputs['Factor'])
        for bsdf in (dif, tl, em): nt.links.new(shade.outputs['Result'], bsdf.inputs['Color'])
        half = nt.nodes.new('ShaderNodeMixShader'); nt.links.new(dif.outputs[0], half.inputs[1]); nt.links.new(tl.outputs[0], half.inputs[2])
        lit = nt.nodes.new('ShaderNodeAddShader'); nt.links.new(half.outputs[0], lit.inputs[0]); nt.links.new(em.outputs[0], lit.inputs[1])
        mix = nt.nodes.new('ShaderNodeMixShader'); nt.links.new(cov, mix.inputs[0]); nt.links.new(tr.outputs[0], mix.inputs[1]); nt.links.new(lit.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs['Surface'])
    else:
        nt.links.new(mth('MULTIPLY', cov, strength), em.inputs['Strength'])
        add = nt.nodes.new('ShaderNodeAddShader')
        nt.links.new(tr.outputs[0], add.inputs[0]); nt.links.new(em.outputs[0], add.inputs[1])
        nt.links.new(add.outputs[0], out.inputs['Surface'])
    m.diffuse_color = (*rgb, 0.45)
    for attr, val in (('surface_render_method', 'BLENDED'), ('blend_method', 'BLEND')):
        if hasattr(m, attr):
            try: setattr(m, attr, val)
            except Exception: pass
    return m


def _card(name, w, h, material, center=False, uv=None):
    """A vertical sprite card in local XZ (pivot at its bottom centre, or its centre), UV 0..1 (or 4 given corners: a band of the
    texture); the 'Mask' UV layer is always 0..1 (soft border of the toolkit sprites)."""
    z0 = -h / 2 if center else 0
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(-w / 2, 0, z0), (w / 2, 0, z0), (w / 2, 0, z0 + h), (-w / 2, 0, z0 + h)], [], [(0, 1, 2, 3)])
    corners = ((0, 0), (1, 0), (1, 1), (0, 1))
    for layer, uvs in (('UVMap', uv or corners), ('Mask', corners)):
        l = mesh.uv_layers.new(name=layer)
        for li, c in zip(range(4), uvs): l.data[li].uv = c
    mesh.update(); obj = bpy.data.objects.new(name, mesh); bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def aura(sc, ch, f0, f1, color='#FFBF32', tongues=14, seed=7):
    """Roblox Super Saiyan aura (R165, matched to Creator Store 8092379429 - assets/vfx/aura_ref/NOTES.md): additive flame-tongue
    billboards 0 -> 4.8 studs tall over a 0.25-0.35 s life (peak at 40-55 %), spawned around the body and rising, two smoke
    clouds behind (~2x body), a warm core light. Cards face the ACTIVE shot camera every frame (baked after the cameras).
    Falls back to the old flame shells if the sprites are missing."""
    if f1 <= f0:
        raise ValueError('aura needs a positive interval')
    if not (AURA_DIR / f'{AURA_TONGUES[0]}.png').exists():
        return aura_shells(sc, ch, f0, f1, color)
    import random
    rnd = random.Random(seed + f0); S_ = 0.5; objects = []
    try:   # 10+ overlapping see-through cards exceed Cycles' 8 transparent bounces -> rays end BLACK (dark smear on the face, R178)
        sc.cycles.transparent_max_bounces = max(sc.cycles.transparent_max_bounces, 64)
    except AttributeError:
        pass
    def face_cam(obj, base):
        cam = sc.camera
        if cam is None: return
        d = cam.matrix_world.translation - base; d.z = 0
        if d.length > 1e-6: obj.rotation_euler = (0, 0, math.atan2(d.y, d.x) - math.pi / 2)
    life = 7   # frames (0.29 s at 24 fps)
    for i in range(tongues):
        mat = _sprite_material(AURA_TONGUES[i % len(AURA_TONGUES)], color, 3.0)
        obj = _card('VFX aura tongue', 1.2 * S_ * 2, 4.8 * S_, mat); objects.append(obj)
        _life(obj, f0, f1)
        a = rnd.uniform(0, math.tau); r = rnd.uniform(0.25, 0.6); off = rnd.randrange(life)
        for f in range(f0, f1 + 1):
            _at(sc, f)
            ph = ((f - f0 + off) % life) / life                      # 0..1 within this tongue's life
            if ph < 0.05: a = rnd.uniform(0, math.tau); r = rnd.uniform(0.25, 0.6)   # respawn somewhere else around the body
            grow = math.sin(math.pi * min(1.0, ph / 0.95)) ** 0.8     # 0 -> peak (~45 %) -> 0
            fade = min(1, (f - f0 + 1) / 5, (f1 - f + 1) / 5)
            base = ch.root.matrix_world.translation + Vector((math.cos(a) * r, math.sin(a) * r, 0.15 + 0.9 * ph))   # rising
            _key(obj, 'location', f, base); face_cam(obj, base); _key(obj, 'rotation_euler', f, obj.rotation_euler)
            s_ = max(0.0, grow * fade); _key(obj, 'scale', f, (s_ * rnd.uniform(0.8, 1.1), 1, s_))
    for j, cid in enumerate(AURA_CLOUDS):   # big soft clouds BEHIND the body (relative to the camera)
        obj = _card('VFX aura cloud', 3.2, 5.0, _sprite_material(cid, color, 1.2, 0.5)); objects.append(obj); _life(obj, f0, f1)
        for f in range(f0, f1 + 1):
            _at(sc, f); cam = sc.camera; p = ch.root.matrix_world.translation.copy()
            if cam is not None:
                d = p - cam.matrix_world.translation; d.z = 0
                if d.length > 1e-6: p += d.normalized() * 0.45   # behind the body as seen from this shot's camera
            face_cam(obj, p); pulse = 1 + 0.08 * math.sin(f * 0.9 + j * 2)
            fade = min(1, (f - f0 + 1) / 6, (f1 - f + 1) / 6)
            _key(obj, 'location', f, p - Vector((0, 0, 0.1))); _key(obj, 'rotation_euler', f, obj.rotation_euler)
            _key(obj, 'scale', f, (pulse * fade, 1, pulse * fade))
    data = bpy.data.lights.new('VFX aura light', 'POINT'); data.color = (1.0, 0.87, 0.11); data.shadow_soft_size = 1.0
    light = bpy.data.objects.new('VFX aura light', data); bpy.context.collection.objects.link(light); _life(light, f0, f1)
    for f in range(f0, f1 + 1, 2):
        _at(sc, f); _key(light, 'location', f, ch.root.matrix_world.translation + Vector((0, 0, 1.2)))
        _key(data, 'energy', f, 400 * min(1, (f - f0 + 1) / 5, (f1 - f + 1) / 5) * (1 + 0.1 * math.sin(f)))
    return objects + [light]


def aura_shells(sc, ch, f0, f1, color='#FFBF32'):
    if f1 <= f0:
        raise ValueError('aura needs a positive interval')
    objects = []
    # Open flame shells frame the silhouette without hiding it in Workbench.
    for index in range(8):
        a = index * math.tau / 8
        radial = Vector((math.cos(a), math.sin(a), 0))
        tangent = Vector((-math.sin(a), math.cos(a), 0))
        vertices = [radial * .85 - tangent * .18 + Vector((0, 0, .2)),
                    radial * 1.0 + Vector((0, 0, 1.2)),
                    radial * .65 + Vector((0, 0, 3.25 + .2 * (index % 3))),
                    radial * .83 + tangent * .18 + Vector((0, 0, .2))]
        mesh = bpy.data.meshes.new('Aura flame')
        mesh.from_pydata(vertices, [], [(0, 1, 2, 3)])
        mesh.update()
        obj = bpy.data.objects.new('Aura flame', mesh)
        bpy.context.collection.objects.link(obj)
        obj.data.materials.append(_aura_material(color))
        _life(obj, f0, f1)
        for f in range(f0, f1 + 1):
            _at(sc, f)
            pulse = 1 + .10 * math.sin(f * 1.7 + index * 2)
            fade = min(1, (f - f0 + 1) / 4, (f1 - f + 1) / 4)
            _key(obj, 'location', f, ch.root.matrix_world.translation)
            _key(obj, 'rotation_euler', f, ch.root.matrix_world.to_euler())
            _key(obj, 'scale', f, (pulse * fade, pulse * fade, (2 - pulse) * fade))
        objects.append(obj)
    return objects


def _dust_burst_v1(sc, point, frame, k=1.0):
    objects = []
    for i in range(9):
        angle = i * math.tau / 9
        direction = Vector((math.cos(angle), math.sin(angle), 0))
        obj = _sphere('Dust puff', point, .25 * k, _material('#BDAA83'))
        _life(obj, frame, frame + 10)
        for dt, radius, size in ((0, .1, .1), (3, .55, 1), (7, 1, .75), (10, 1.3, 0)):
            _key(obj, 'location', frame + dt, Vector(point) + direction * radius * k + Vector((0, 0, (.15 + dt * .025) * k)))
            _key(obj, 'scale', frame + dt, (size, size, size * .65))
        objects.append(obj)
    return objects


def window_dust(sc, info):
    """At most 36 drifting emissive mesh instances, within 1.8 m of interior windows; tier() enables them only in Cycles."""
    if info.get('outdoor') or not info.get('windows'): return []
    existing = [o for o in sc.objects if o.name.startswith('VFX window dust')]
    if existing: return existing
    x0, x1, y0, y1 = info['bounds']; rnd = random.Random(202)
    material = _material('#FFE4AD'); objects = []
    for side, windows in info['windows'].items():
        for u, width, sill, height in windows:
            for i in range(12):
                if len(objects) == 36: return objects
                a = (u + rnd.uniform(-.45, .45) * width) * .5
                z = (sill + rnd.uniform(.1, .85) * height) * .5
                depth = rnd.uniform(.2, 1.8)
                p = Vector({'right': (x1-depth, a, z), 'left': (x0+depth, a, z),
                            'back': (a, y1-depth, z), 'front': (a, y0+depth, z)}[side])
                if objects:
                    obj = bpy.data.objects.new('VFX window dust', objects[0].data); sc.collection.objects.link(obj)
                else:
                    obj = _sphere('VFX window dust', p, 1, material)
                obj.scale = (rnd.uniform(.012, .024),) * 3
                obj.hide_render = True; obj.hide_select = True
                obj.visible_shadow = obj.visible_diffuse = obj.visible_glossy = False
                for frame in range(sc.frame_start, sc.frame_end + 49, 48):
                    t = (frame - sc.frame_start) / 48
                    _key(obj, 'location', frame, p + Vector((.06*math.sin(t+i), .05*math.cos(t+i), .08*math.sin(t*.7+i))))
                objects.append(obj)
    return objects


def weather(sc, info, kind='none'):
    """Set weather=snow|rain: sparse, shared meshes and baked linear fall, without simulation or volumes."""
    if kind not in ('none', 'snow', 'rain'): raise ValueError('weather must be none, snow or rain')
    if kind == 'none' or not info.get('outdoor'): return []
    prefix = 'VFX weather ' + kind
    existing = [o for o in sc.objects if o.name.startswith(prefix)]
    if existing: return existing
    x0, x1, y0, y1 = info['bounds']
    cx, cy = (x0+x1)/2, (y0+y1)/2
    width, depth = min((x1-x0)/2, 8), min((y1-y0)/2, 8)
    rnd = random.Random((info.get('spec') or {}).get('seed', 257))
    objects = []; rain = kind == 'rain'
    material = _material('#A4C5DF' if rain else '#E2F0FF')
    for i in range(96):
        if objects:
            obj = bpy.data.objects.new(prefix, objects[0].data); sc.collection.objects.link(obj)
        else:
            obj = _sphere(prefix, (0, 0, 0), 1, material)
        radius = rnd.uniform(.018, .04)
        obj.scale = (.006, .006, .13) if rain else (radius,) * 3
        obj.cycles.use_motion_blur = False  # A fall-cycle reset must not become an upward streak in HQ.
        obj.hide_render = True; obj.hide_select = True
        obj.visible_shadow = obj.visible_diffuse = obj.visible_glossy = False
        x, y = cx+rnd.uniform(-width, width), cy+rnd.uniform(-depth, depth)
        period = rnd.randint(9, 14) if rain else rnd.randint(80, 140)
        start = sc.frame_start-rnd.randrange(period)
        for frame in range(start, sc.frame_end+period, period+1):
            _key(obj, 'location', frame, (x, y, 6))
            _key(obj, 'location', frame+period, (x+.3, y, .05))
        from space import fcurves_of
        for curve in fcurves_of(obj):
            for key in curve.keyframe_points: key.interpolation = 'LINEAR'
        objects.append(obj)
    return objects


def _decal_material(name, inner, outer_alpha=0.0, spokes=14, seed=3, cracks_only=False):
    """Scorched ground decal: dark centre fading out radially, with radial CRACK spokes (procedural, both draft and Cycles)."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree
    for n_ in list(nt.nodes):
        if n_.type != 'OUTPUT_MATERIAL': nt.nodes.remove(n_)
    out = next(n_ for n_ in nt.nodes if n_.type == 'OUTPUT_MATERIAL')
    rgb = _material(inner).diffuse_color[:3]
    tc = nt.nodes.new('ShaderNodeTexCoord'); sep = nt.nodes.new('ShaderNodeSeparateXYZ'); nt.links.new(tc.outputs['Object'], sep.inputs[0])
    # radius r = sqrt(x^2 + y^2) of the unit disk; angle for the crack spokes
    x2 = nt.nodes.new('ShaderNodeMath'); x2.operation = 'MULTIPLY'; nt.links.new(sep.outputs['X'], x2.inputs[0]); nt.links.new(sep.outputs['X'], x2.inputs[1])
    y2 = nt.nodes.new('ShaderNodeMath'); y2.operation = 'MULTIPLY'; nt.links.new(sep.outputs['Y'], y2.inputs[0]); nt.links.new(sep.outputs['Y'], y2.inputs[1])
    r2 = nt.nodes.new('ShaderNodeMath'); r2.operation = 'ADD'; nt.links.new(x2.outputs[0], r2.inputs[0]); nt.links.new(y2.outputs[0], r2.inputs[1])
    r = nt.nodes.new('ShaderNodeMath'); r.operation = 'SQRT'; nt.links.new(r2.outputs[0], r.inputs[0])
    ang = nt.nodes.new('ShaderNodeMath'); ang.operation = 'ARCTAN2'; nt.links.new(sep.outputs['Y'], ang.inputs[0]); nt.links.new(sep.outputs['X'], ang.inputs[1])
    sp = nt.nodes.new('ShaderNodeMath'); sp.operation = 'MULTIPLY'; sp.inputs[1].default_value = spokes; nt.links.new(ang.outputs[0], sp.inputs[0])
    sn = nt.nodes.new('ShaderNodeMath'); sn.operation = 'SINE'; nt.links.new(sp.outputs[0], sn.inputs[0])
    ab = nt.nodes.new('ShaderNodeMath'); ab.operation = 'ABSOLUTE'; nt.links.new(sn.outputs[0], ab.inputs[0])
    crack = nt.nodes.new('ShaderNodeMath'); crack.operation = 'LESS_THAN'; crack.inputs[1].default_value = 0.10; nt.links.new(ab.outputs[0], crack.inputs[0])
    # bowl: opaque dark disk up to r 0.55, then a fading ring; cracks run out to r 1.0
    bowl = nt.nodes.new('ShaderNodeMapRange'); bowl.inputs['From Min'].default_value = 0.55; bowl.inputs['From Max'].default_value = 0.8
    bowl.inputs['To Min'].default_value = 0.95; bowl.inputs['To Max'].default_value = 0.0; nt.links.new(r.outputs[0], bowl.inputs['Value'])
    cr = nt.nodes.new('ShaderNodeMapRange'); cr.inputs['From Min'].default_value = 0.4; cr.inputs['From Max'].default_value = 1.0
    cr.inputs['To Min'].default_value = 0.9; cr.inputs['To Max'].default_value = 0.0; nt.links.new(r.outputs[0], cr.inputs['Value'])
    crk = nt.nodes.new('ShaderNodeMath'); crk.operation = 'MULTIPLY'; nt.links.new(crack.outputs[0], crk.inputs[0]); nt.links.new(cr.outputs['Result'], crk.inputs[1])
    cov = nt.nodes.new('ShaderNodeMath'); cov.operation = 'MAXIMUM'; (None if cracks_only else nt.links.new(bowl.outputs['Result'], cov.inputs[0])); nt.links.new(crk.outputs[0], cov.inputs[1])
    dif = nt.nodes.new('ShaderNodeBsdfDiffuse'); dif.inputs['Color'].default_value = (*rgb, 1)
    tr = nt.nodes.new('ShaderNodeBsdfTransparent'); mix = nt.nodes.new('ShaderNodeMixShader')
    nt.links.new(cov.outputs[0], mix.inputs['Fac']); nt.links.new(tr.outputs[0], mix.inputs[1]); nt.links.new(dif.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    m.diffuse_color = (*rgb, 0.85)
    for attr, val in (('surface_render_method', 'BLENDED'), ('blend_method', 'BLEND')):
        if hasattr(m, attr):
            try: setattr(m, attr, val)
            except Exception: pass
    return m


def _bowl_material():
    """The creator's reference (DBZ crater seen from above): a deep brown bowl with dark radial striations from the rim to a darker
    centre, inside a pale, blown-out ring of sand. Unit-disc decal: bowl r < .62, pale ring .62 - 1.0 fading out. Diffuse + transparent
    (renders the same in Workbench/EEVEE and Cycles)."""
    name = 'VFX crater bowl'
    m = bpy.data.materials.get(name)
    if m: return m
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree
    for n_ in list(nt.nodes):
        if n_.type != 'OUTPUT_MATERIAL': nt.nodes.remove(n_)
    out = next(n_ for n_ in nt.nodes if n_.type == 'OUTPUT_MATERIAL')
    def node(kind, **kw):
        n = nt.nodes.new(kind)
        for k, v in kw.items(): setattr(n, k, v)
        return n
    def link(a, b): nt.links.new(a, b)
    def math_(op, a=None, b=None, clamp=False):
        n = node('ShaderNodeMath', operation=op, use_clamp=clamp)
        for i, v in ((0, a), (1, b)):
            if v is None: continue
            if isinstance(v, (int, float)): n.inputs[i].default_value = v
            else: link(v, n.inputs[i])
        return n.outputs[0]
    def rng(v, a0, a1, b0, b1):
        n = node('ShaderNodeMapRange'); n.inputs['From Min'].default_value = a0; n.inputs['From Max'].default_value = a1
        n.inputs['To Min'].default_value = b0; n.inputs['To Max'].default_value = b1; n.clamp = True; link(v, n.inputs['Value']); return n.outputs['Result']
    tc = node('ShaderNodeTexCoord'); sep = node('ShaderNodeSeparateXYZ'); link(tc.outputs['Object'], sep.inputs[0])
    r = math_('SQRT', math_('ADD', math_('MULTIPLY', sep.outputs['X'], sep.outputs['X']), math_('MULTIPLY', sep.outputs['Y'], sep.outputs['Y'])))
    ang = math_('ARCTAN2', sep.outputs['Y'], sep.outputs['X'])
    # striations: two interleaved frequencies, thin dark streaks running radially, stronger toward the rim of the bowl
    s1 = math_('ABSOLUTE', math_('SINE', math_('MULTIPLY', ang, 31.0))); s2 = math_('ABSOLUTE', math_('SINE', math_('MULTIPLY', ang, 53.0)))
    streak = math_('MAXIMUM', rng(s1, .0, .22, 1, 0), rng(s2, .0, .12, 1, 0))
    streak = math_('MULTIPLY', streak, rng(r, .12, .6, .35, 1.0))
    def col(c): return (*[v for v in c], 1.0)
    mix_wall = node('ShaderNodeMix', data_type='RGBA'); mix_wall.inputs['A'].default_value = col((.11, .055, .025)); mix_wall.inputs['B'].default_value = col((.36, .19, .08))
    link(rng(r, 0.0, .6, 0, 1), mix_wall.inputs['Factor'])                                   # dark centre -> brown wall
    mix_streak = node('ShaderNodeMix', data_type='RGBA'); mix_streak.inputs['B'].default_value = col((.02, .008, .004))
    link(mix_wall.outputs['Result'], mix_streak.inputs['A']); link(math_('MULTIPLY', streak, .92), mix_streak.inputs['Factor'])
    mix_ring = node('ShaderNodeMix', data_type='RGBA'); mix_ring.inputs['B'].default_value = col((.95, .80, .45))   # blown-out pale sand
    link(mix_streak.outputs['Result'], mix_ring.inputs['A']); link(rng(r, .6, .68, 0, 1), mix_ring.inputs['Factor'])
    dif = node('ShaderNodeBsdfDiffuse'); link(mix_ring.outputs['Result'], dif.inputs['Color'])
    tr = node('ShaderNodeBsdfTransparent'); mix = node('ShaderNodeMixShader')
    link(rng(r, .78, 1.0, 1.0, 0.0), mix.inputs['Fac']); link(tr.outputs[0], mix.inputs[1]); link(dif.outputs[0], mix.inputs[2])
    link(mix.outputs[0], out.inputs['Surface'])
    m.diffuse_color = (.3, .15, .06, .9)
    for attr, val in (('surface_render_method', 'BLENDED'), ('blend_method', 'BLEND')):
        if hasattr(m, attr):
            try: setattr(m, attr, val)
            except Exception: pass
    return m


def _decal(name, point, radius, material):
    bpy.ops.mesh.primitive_circle_add(vertices=48, radius=1.0, fill_type='NGON', location=(point[0], point[1], 0.006))
    obj = bpy.context.object; obj.name = name; obj.data.materials.append(material)
    return obj


def _rock(name, point, size, material, rnd):
    """A Roblox-style rock chunk: a slightly squashed, rotated block."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=point)
    obj = bpy.context.object; obj.name = name
    obj.scale = (size * rnd.uniform(0.8, 1.3), size * rnd.uniform(0.7, 1.2), size * rnd.uniform(0.5, 0.9))
    obj.rotation_euler = (rnd.uniform(-.5, .5), rnd.uniform(-.5, .5), rnd.uniform(0, math.tau))
    obj.data.materials.append(material)
    return obj


def crater(sc, point, frame, radius=1.8, color='#3B2A1E', rock='#8A6A4C', seed=11, settled=False, big=False):
    """IMPACT CRATER (DBZ ground damage, creator R172 reference): a scorched bowl decal with radial cracks popping out over 3
    frames, a raised rim of rock chunks pushed up around it, debris thrown out on arcs and landing, a dust burst. Stays for
    the rest of the scene (damage persists). settled=True: it is already there at `frame` (no pop, debris or dust: a scene that
    opens on the aftermath)."""
    import random
    rnd = random.Random(seed + frame); objects = []; P = Vector((point[0], point[1], 0))
    end = sc.frame_end + 60
    if big:   # GROUND DAMAGE upgrade: dark deep centre, long radial cracks (2.6x the radius), bigger rim, a bouncing debris, an expanding dust ring
        cr = _decal('VFX crater cracks', P, radius, _decal_material('VFX crater cracks', '#2A1D14', spokes=26, seed=5, cracks_only=True)); objects.append(cr); _life(cr, frame, end)
        for f, k in (((frame, 2.6),) if settled else ((frame, .6), (frame + 3, 2.7), (frame + 6, 2.6))):
            _key(cr, 'scale', f, (radius * k, radius * k, 1))
        cr.location.z = .004
        bowl = _decal('VFX crater bowl', P, radius, _bowl_material()); objects.append(bowl); _life(bowl, frame, end)
        for f, k in (((frame, 1.6),) if settled else ((frame, .5), (frame + 3, 1.7), (frame + 5, 1.6))):   # radius = the brown bowl; the pale ring reaches 1.6x
            _key(bowl, 'scale', f, (radius * k, radius * k, 1))
        bowl.location.z = .008 + .0006 * (frame % 50 + 1)   # a second crater lies ABOVE the first (same-height decals fought and stacked to black)
        for i in range(8):   # small black pebbles in the outer bowl (the middle stays clean for the body)
            a = rnd.uniform(0, math.tau); rr = radius * rnd.uniform(.62, .95)
            o = _rock('VFX crater pebble', P + Vector((math.cos(a) * rr, math.sin(a) * rr, .03)), rnd.uniform(.03, .06), _material('#1B1511'), rnd); objects.append(o); _life(o, frame, end)
    dec = _decal('VFX crater', P, radius, _decal_material(f'VFX crater {color}', color)); objects.append(dec); _life(dec, frame, end)
    for f, k in (((frame, 1.0),) if settled else ((frame, 0.35), (frame + 2, 1.08), (frame + 4, 1.0))):
        _key(dec, 'scale', f, (radius * k, radius * k, 1))
    rm = _material(rock)
    nrim = 14 if big else 16
    for i in range(nrim):   # rim chunks rise out of the ground at the edge
        a = i * math.tau / nrim + rnd.uniform(-.12, .12); rr = radius * rnd.uniform(0.85, 1.1)
        q = P + Vector((math.cos(a) * rr, math.sin(a) * rr, 0))
        o = _rock('VFX crater rim', q, rnd.uniform(0.16, 0.3) if big else rnd.uniform(0.18, 0.34), rm, rnd); objects.append(o); _life(o, frame, end)
        for f, z in (((frame, 0.14 if big else 0.06),) if settled else ((frame, -0.25), (frame + 3, 0.3 if big else 0.12), (frame + 5, 0.14 if big else 0.06))):
            _key(o, 'location', f, q + Vector((0, 0, z)))
    for i in range(0 if settled else (10 if big else 12)):   # debris thrown out on arcs, landing outside the rim
        a = rnd.uniform(0, math.tau); d = radius * rnd.uniform(1.4, 2.6); h = rnd.uniform(0.6, 1.6); n = 14
        o = _rock('VFX debris', P, rnd.uniform(0.06, 0.12) if big else rnd.uniform(0.07, 0.15), rm, rnd); objects.append(o); _life(o, frame, end + 0)
        for k in range(n + 1):
            t = k / n; q = P + Vector((math.cos(a) * d * t, math.sin(a) * d * t, 4 * h * t * (1 - t) + 0.05))
            _key(o, 'location', frame + k, q); _key(o, 'rotation_euler', frame + k, (t * 6, t * 4, a))
        if big:   # it keeps bouncing ~0.5 s: two smaller hops further out
            d0 = d
            for hop, (dd, hh) in enumerate(((.22, .35 * h), (.12, .15 * h))):
                for k in range(1, 7):
                    t = k / 6; dist = d0 + radius * dd * t; q = P + Vector((math.cos(a) * dist, math.sin(a) * dist, 4 * hh * t * (1 - t) + 0.05))
                    _key(o, 'location', frame + n + hop * 6 + k, q); _key(o, 'rotation_euler', frame + n + hop * 6 + k, (6 + t * 2 + hop, 4 + t, a))
                d0 += radius * dd
    if not settled: objects += dust_burst(sc, P + Vector((0, 0, 0.1)), frame)
    if big and not settled: objects += dust_ring(sc, P, frame, radius)
    return objects


def _dust_ring_v1(sc, point, frame, radius):
    """A ring of dust that expands from the crater edge to ~2.4x the radius over 14 frames and fades."""
    objects = []; P = Vector((point[0], point[1], 0))
    for i in range(20):
        a = i * math.tau / 20; d = Vector((math.cos(a), math.sin(a), 0))
        o = _sphere('Dust ring', P, .3, _material('#BDAA83')); _life(o, frame + 1, frame + 16)
        for dt, r, s in ((1, .9, .15), (6, 1.5, .5), (11, 2.0, .35), (16, 2.4, 0)):   # small soft puffs (big pale discs read as plates)
            _key(o, 'location', frame + dt, P + d * radius * r + Vector((0, 0, .2 + dt * .03)))
            _key(o, 'scale', frame + dt, (s, s, s * .6))
        objects.append(o)
    return objects


def _smoke_column_v1(sc, point, frame, hold=1.0, radius=1.1, fps=24, seed=4):
    """Thick dust that hangs ~`hold` s round a landing figure, so the character is revealed standing in the smoke. SOFT cloud
    sprites (the aura's smoke cards: alpha-textured, additive-looking), NOT opaque spheres: in Cycles HQ the spheres merged into one
    flat beige blob that hid the figure. A few puffs sit on the figure and go in the first 8 frames; the rest ring it, rise, break
    up and fade. Cards face the active shot camera (baked after the cameras)."""
    import random
    if not (AURA_DIR / f'{AURA_CLOUDS[0]}.png').exists():   # no sprite assets: the old spheres
        return _smoke_spheres(sc, point, frame, hold, radius, fps, seed)
    rnd = random.Random(seed + frame); objects = []; P = Vector((point[0], point[1], 0)); n = max(8, int(hold * fps))
    try: sc.cycles.transparent_max_bounces = max(sc.cycles.transparent_max_bounces, 64)
    except AttributeError: pass
    for i in range(10):   # few, translucent cards: 16 overlapping ones summed to one opaque flat blob in Cycles (additive)
        a = i * math.tau / 10 + rnd.uniform(-.2, .2); r = radius * rnd.uniform(.8, 1.7) if i >= 3 else radius * rnd.uniform(0, .3)
        z0 = rnd.uniform(0, .5) if i >= 4 else rnd.uniform(.2, 1.2)
        life = 8 if i < 3 else n + rnd.randint(0, 6); size = rnd.uniform(1.2, 1.9)
        mat = _sprite_material(AURA_CLOUDS[i % len(AURA_CLOUDS)], '#B89E70', .35, .3)
        obj = _card('VFX smoke column', size, size, mat); objects.append(obj); _life(obj, frame, frame + life)
        base = P + Vector((math.cos(a) * r, math.sin(a) * r, z0))
        for f in range(frame, frame + life + 1):
            _at(sc, f); u = (f - frame) / life
            grow = min(1.0, (f - frame + 1) / 4) * (1.0 + .5 * u); fade = max(0.0, min(1.0, (frame + life - f) / (.45 * life)))   # breaks up and fades over the last 45 %
            cam = sc.camera; p = base + Vector((0, 0, .6 * u))
            if cam is not None:
                d = cam.matrix_world.translation - p; d.z = 0
                if d.length > 1e-6: obj.rotation_euler = (0, 0, math.atan2(d.y, d.x) - math.pi / 2)
            _key(obj, 'location', f, p); _key(obj, 'rotation_euler', f, obj.rotation_euler)
            s_ = grow * (.4 + .6 * fade); _key(obj, 'scale', f, (s_, 1, s_))
    return objects


def _smoke_spheres(sc, point, frame, hold, radius, fps, seed):
    import random
    rnd = random.Random(seed + frame); objects = []; P = Vector((point[0], point[1], 0)); n = max(8, int(hold * fps))
    for i in range(18):
        a = i * math.tau / 18 + rnd.uniform(-.2, .2); r = radius * rnd.uniform(.5, 1.5) if i >= 4 else radius * rnd.uniform(0, .35)
        z0 = rnd.uniform(.3, 1.2) if i >= 4 else rnd.uniform(.8, 2.0)
        life = 8 if i < 4 else n + rnd.randint(0, 6)
        size = rnd.uniform(.55, .85)
        obj = _sphere('Dust column', P, 1, _material('#C9B68E')); _life(obj, frame, frame + life)
        q = P + Vector((math.cos(a) * r, math.sin(a) * r, z0))
        for dt, k, rise in ((0, .15, 0), (4, 1.0, .25), (life - 5, .9, .5 + .02 * life), (life, 0, .7 + .02 * life)):
            _key(obj, 'location', frame + dt, q + Vector((0, 0, rise)))
            _key(obj, 'scale', frame + dt, (size * k,) * 3)
        objects.append(obj)
    return objects


def ground_power(sc, ch, f0, f1, seed=5, color='#3B2A1E', rock='#8A6A4C'):
    """POWER-UP GROUND REACTION: cracks spreading out from the feet over the charge, and rock chunks lifting off the ground
    around the fighter, floating up and spinning slowly (the DBZ power-up beat), falling back after f1."""
    import random
    rnd = random.Random(seed + f0); objects = []
    sc.frame_set(f0); P = ch.root.matrix_world.translation.copy(); P.z = 0
    end = sc.frame_end + 60
    dec = _decal('VFX cracks', P, 2.6, _decal_material(f'VFX cracks {color}', color, spokes=9)); objects.append(dec); _life(dec, f0, end)
    for f, k in ((f0, 0.2), (f0 + (f1 - f0) // 2, 1.6), (f1, 2.6)):
        _key(dec, 'scale', f, (k, k, 1))
    rm = _material(rock)
    for i in range(12):
        a = rnd.uniform(0, math.tau); r = rnd.uniform(1.0, 3.0); q = P + Vector((math.cos(a) * r, math.sin(a) * r, 0.05))
        o = _rock('VFX rising rock', q, rnd.uniform(0.1, 0.28), rm, rnd); objects.append(o); _life(o, f0, end)
        top = rnd.uniform(0.8, 2.4); st = f0 + rnd.randrange(max(1, (f1 - f0) // 2)); spin = rnd.uniform(-2, 2)
        for f in range(st, f1 + 1, 2):
            t = (f - st) / max(1, f1 - st)
            _key(o, 'location', f, q + Vector((0, 0, top * (t ** 0.7) + 0.05 * math.sin(f * .7 + i))))
            _key(o, 'rotation_euler', f, (spin * t, spin * .6 * t, a + spin * t))
        for k, f in enumerate(range(f1, f1 + 9)):   # drop back down when the power-up ends
            t = k / 8; _key(o, 'location', f, q + Vector((0, 0, top * (1 - t * t))))
    return objects


def speed_lines(sc, cam, f0, f1):
    if f1 <= f0:
        raise ValueError('speed_lines needs a positive interval')
    objects = []
    for i in range(12):
        angle = i * math.tau / 12
        mesh = bpy.data.meshes.new('Speed streak')
        mesh.from_pydata([(-.012, .0, 0), (.012, .0, 0), (.004, .45, 0), (-.004, .45, 0)], [], [(0, 1, 2, 3)])
        mesh.update()
        obj = bpy.data.objects.new('Speed streak', mesh)
        bpy.context.collection.objects.link(obj)
        obj.parent = cam
        obj.rotation_euler.z = angle - math.pi / 2
        obj.data.materials.append(_material('#D5F3FF'))
        _life(obj, f0, f1)
        for f in range(f0, f1 + 1):
            radius = .8 + .25 * ((f + i) % 5) / 4
            _key(obj, 'location', f, (math.cos(angle) * radius * 1.5, math.sin(angle) * radius, -3))
            _key(obj, 'scale', f, (1, .6 + .4 * math.sin(f + i) ** 2, 1))
        objects.append(obj)
    return objects


def exclaim(sc, ch, frame):
    curve = bpy.data.curves.new('Exclamation', 'FONT')
    curve.body = '!'
    curve.align_x = 'CENTER'
    curve.size = .5
    curve.extrude = .025
    obj = bpy.data.objects.new('Exclamation', curve)
    bpy.context.collection.objects.link(obj)
    curve.materials.append(_material('#FFF19A'))
    _life(obj, frame, frame + 12)
    for f in range(frame, frame + 13):
        _at(sc, f)
        side = sc.camera.matrix_world.to_3x3().col[0].normalized() * .5 if sc.camera else Vector()   # beside the head: a close-up crops the top
        p = ch.head.matrix_world.translation + side + Vector((0, 0, .32 + .05 * math.sin((f - frame) * .6)))
        _key(obj, 'location', f, p)
        rotation = (sc.camera.matrix_world.translation - p).to_track_quat('Z', 'Y').to_euler() if sc.camera else (math.pi / 2, 0, 0)
        _key(obj, 'rotation_euler', f, rotation)
    return [obj]


def sparkles(sc, point, f0, f1):
    if f1 <= f0:
        raise ValueError('sparkles needs a positive interval')
    rnd = random.Random(17)
    objects = []
    for i in range(12):
        p = Vector(point) + Vector((rnd.uniform(-.8, .8), rnd.uniform(-.5, .5), rnd.uniform(0, 1.2)))
        obj = _star('Sparkle', p, .12, _material('#FFFAC4'), rays=4)
        _life(obj, f0, f1)
        for f in range(f0, f1 + 1):
            size = max(0, math.sin((f - f0) * .7 + i)) * min(1, (f1 - f) / 3)
            _key(obj, 'scale', f, (size,) * 3)
            _key(obj, 'location', f, p + Vector((0, 0, (f - f0) * .015)))
        objects.append(obj)
    return objects


# ---------------------------------------------------------------- VFX v2: the sprite toolkit (research/SHOWCASE_FX_HANDOFF.md)
# Fight effects = TEXTURED, ANIMATED glow cards (Kenney Particle Pack, CC0) instead of primitives with flat emission. Every card
# faces the active shot camera (baked per frame, after the cameras), is additive ('add': only ever adds light, blooms in hq) or a
# lit see-through puff ('mix': dust, smoke, dirt), fades to nothing at its border, casts no shadow and has no motion blur.
# VFX_V1=impact_flash,energy_beam,... (env) or the V1 set sends an effect back to its old primitive path (also the A/B switch);
# the old path is used too when the sprite folder is missing.
V1 = set(filter(None, os.environ.get('VFX_V1', '').split(',')))
DUST = ('smoke_04', 'smoke_05', 'smoke_07', 'smoke_08')
SAND = '#EBD5A8'   # paler than sand: dust in the ground's own colour vanished on it


def _v2(effect):
    return effect not in V1 and 'all' not in V1 and (KENNEY / 'circle_05.png').exists()


def _viewer(sc):
    """view(frame) -> (camera position, 3x3 with columns right / up / back) of the ACTIVE shot camera at that frame, cached per effect."""
    cache = {}
    def view(f):
        if f not in cache:
            _at(sc, f); cam = sc.camera
            cache[f] = ((cam.matrix_world.translation.copy(), cam.matrix_world.to_3x3().normalized()) if cam
                        else (Vector((0, -10, 1.5)), Matrix(((1, 0, 0), (0, 0, -1), (0, 1, 0)))))
        return cache[f]
    return view


def _curve(c, u, f):
    """A value over a sprite's life: a number, a callable(frame), or points ((u, value), ...) with u 0..1, linear between."""
    if callable(c): return c(f)
    if isinstance(c, (int, float)): return c
    for (u0, v0), (u1, v1) in zip(c, c[1:]):
        if u <= u1: return v0 + (v1 - v0) * (u - u0) / max(1e-9, u1 - u0)
    return c[-1][1]


def _band(u0=0.0, u1=1.0):
    """UVs of the thin middle band of a sprite: constant along the card's length, the sprite's soft profile across it (beam bodies)."""
    return ((u0, .47), (u1, .47), (u1, .53), (u0, .53))


def sprite(sc, name, tex, point, f0, f1, size, color='#FFFFFF', strength=8.0, scale=1.0, alpha=1.0, roll=0.0, spin=0.0, vel=(0, 0, 0),
           gravity=0.0, axis=None, normal=None, aspect=1.0, toward=0.0, mode='add', alpha_k=1.0, span=None, view=None, uv=None, depth=0.0):
    """ONE animated glow card. tex = a sprite name in assets/vfx/kenney_particles; point = world metres or callable(frame); size =
    width in metres (height = size * aspect); scale / alpha = _curve over the life (scale may return (across, along)); roll rad,
    spin rad/frame; vel m/s, gravity m/s2. Facing: the camera (default), axis = a world direction the card's length follows while
    it turns round it toward the camera (beams, streaks; may be callable(frame)), or normal = a fixed world normal (shock rings).
    toward = metres pulled toward the camera (so a body does not cut the card). span = (first, last) frame it is alive inside the
    f0..f1 visibility window (default all of it). depth = metres the card's MESH sits in front of its origin: cards stacked on one
    point need different depths (Cycles shades only one of several coplanar see-through cards), while every origin stays on the point."""
    view = view or _viewer(sc); t0, t1 = span or (f0, f1); fps = sc.render.fps; V = Vector(vel)
    try: sc.cycles.transparent_max_bounces = max(sc.cycles.transparent_max_bounces, 64)   # stacked see-through cards must not end black
    except AttributeError: pass
    obj = _card(name, 1, 1, _sprite_material(tex, color, strength, alpha_k, mode, soft=True), center=True, uv=uv)
    obj.visible_shadow = obj.visible_diffuse = obj.visible_glossy = False
    for v in obj.data.vertices: v.co.y = -depth   # local -Y looks at the camera (or along the fixed normal)
    try: obj.cycles.use_motion_blur = False   # a respawning / spinning card must not smear
    except AttributeError: pass
    _life(obj, f0, f1)
    for f in range(f0, f1 + 1):
        if not t0 <= f <= t1:
            _key(obj, 'scale', f, (0, 0, 0)); continue
        u = (f - t0) / max(1, t1 - t0); t = (f - t0) / fps
        p = Vector(point(f) if callable(point) else point) + V * t + Vector((0, 0, -.5 * gravity * t * t))
        eye, R = view(f); s = _curve(scale, u, f); sx, sz = s if isinstance(s, tuple) else (s, s)
        ax = axis(f) if callable(axis) else axis
        if normal is not None:
            y = Vector(normal).normalized(); x = y.orthogonal().normalized(); z = x.cross(y)
        elif ax is not None:
            z = Vector(ax).normalized(); v = eye - p; y = v - z * v.dot(z)
            y = -y.normalized() if y.length > 1e-6 else z.orthogonal().normalized(); x = y.cross(z)
        else:
            x, z = R.col[0].copy(), R.col[1].copy(); y = z.cross(x)
        M = Matrix((x, y, z)).transposed() @ Matrix.Rotation(roll + spin * (f - t0), 3, 'Y')
        d = eye - p
        _key(obj, 'location', f, p + (d.normalized() * toward if toward and d.length > 1e-6 else Vector()))
        _key(obj, 'rotation_euler', f, M.to_euler())
        _key(obj, 'scale', f, (size * sx, 1, size * aspect * sz)); _key(obj, 'color', f, (1, 1, 1, max(0.0, _curve(alpha, u, f))))
    return obj


def burst(sc, point, frame, sprites, n=10, speed=4.0, life=8, gravity=9.8, color='#FFFFFF', size=.3, strength=25.0, seed=0, streak=False,
          up=.35, mode='add', alpha_k=1.0, window=None, toward=0.0, scale=((0, .6), (1, 1)), alpha=((0, 1), (.6, 1), (1, 0)), view=None,
          name='VFX burst'):
    """n cards thrown out from a point on ballistic arcs: a random sprite each, speed m/s (x 0.5-1), life frames, gravity m/s2.
    streak=True: each card is a streak stretched along its own flight direction (sparks). window = one shared (first, last)
    visibility for all cards (an effect whose objects must share a lifetime); default each card lives frame..frame+life."""
    view = view or _viewer(sc); rnd = random.Random(seed * 7919 + frame); fps = sc.render.fps; out = []
    for i in range(n):
        v = Vector((rnd.gauss(0, 1), rnd.gauss(0, 1), rnd.gauss(0, 1) + up * 1.5)).normalized() * speed * rnd.uniform(.5, 1.0)
        t0 = frame + rnd.randint(0, 1); w = window or (t0, t0 + life)
        ax = (lambda f, v=v, t0=t0: v + Vector((0, 0, -gravity * (f - t0) / fps + 1e-6))) if streak else None
        out.append(sprite(sc, name, rnd.choice(sprites), point, w[0], w[1], size * rnd.uniform(.6, 1.3), color, strength, scale=scale, alpha=alpha,
                          roll=0 if streak else rnd.uniform(0, math.tau), vel=v, gravity=gravity, axis=ax, aspect=2.0 if streak else 1.0,
                          toward=toward, mode=mode, alpha_k=alpha_k, span=(t0, min(w[1], t0 + life)), view=view))
    return out


def _puff(sc, name, point, f0, f1, size, vel, rnd, view, color=SAND, span=None, peak=.75, hold=.5):
    """One soft dust puff: expands, drifts with vel, turns slowly, fades in fast and out slowly."""
    return sprite(sc, name, rnd.choice(DUST), point, f0, f1, size, color, .3, scale=((0, .35), (.3, .85), (1, 1.35)),
                  alpha=((0, peak * .5), (.12, peak), (hold, peak * .8), (1, 0)), roll=rnd.uniform(0, math.tau), spin=rnd.uniform(-.03, .03), vel=vel,
                  mode='mix', alpha_k=1.0, span=span, view=view)


def _lamp(name, point, color, f0, f1, keys):
    data = bpy.data.lights.new(name, 'POINT'); data.color = _material(color).diffuse_color[:3]; data.shadow_soft_size = .5
    light = bpy.data.objects.new(name, data); bpy.context.collection.objects.link(light); light.location = point; _life(light, f0, f1)
    for f, watts in keys: _key(data, 'energy', f, watts)
    return light


def impact_flash(sc, point, frame, color='#FFF19A', size=1.0):
    """A hit: white-hot flare + coloured glow + shock ring + streaks flying out, over 4 frames, and a light flash."""
    if not _v2('impact_flash'): return _impact_flash_v1(sc, point, frame, color, size)
    view = _viewer(sc); P = Vector(point); w = (frame, frame + 4); rnd = random.Random(frame)
    objects = [sprite(sc, 'Impact glow', 'circle_05', P, *w, 1.7 * size, color, 8, scale=((0, .4), (.3, 1), (1, 1.3)), alpha=((0, 1), (1, 0)), alpha_k=.5, toward=.25, view=view),
               sprite(sc, 'Impact ring', 'circle_02', P, *w, 2.4 * size, color, 6, scale=((0, .2), (1, 1)), alpha=((0, .9), (.4, .45), (1, 0)), toward=.3, view=view),
               sprite(sc, 'Impact burst', 'scorch_01', P, *w, 2.4 * size, color, 40, scale=((0, .35), (.25, 1.15), (1, 1.0)), alpha=((0, 1), (.5, .9), (1, 0)), roll=rnd.uniform(0, math.tau), toward=.32, view=view),
               sprite(sc, 'Impact flare', 'star_07', P, *w, 1.5 * size, '#FFFFFF', 40, scale=((0, .5), (.25, 1.1), (.75, .2), (1, 0)), alpha=((0, 1), (.6, 1), (1, 0)),
                      roll=rnd.uniform(0, math.tau), toward=.35, view=view)]
    objects += burst(sc, P, frame, ('trace_01',), n=6, speed=9 * size, life=4, gravity=0, color=color, size=.55 * size, strength=30, seed=frame, streak=True,
                     up=0, window=w, toward=.3, view=view, name='Impact streak')
    return objects + [_lamp('Impact light', P, color, *w, ((frame - 1, 0), (frame, 300 * size), (frame + 1, 500 * size), (frame + 4, 0)))]


def dust_burst(sc, point, frame, k=1.0):
    """Soft dust kicked out along the ground: puffs that expand, drift outward and up, and fade (10 frames)."""
    if not _v2('dust_burst'): return _dust_burst_v1(sc, point, frame, k)
    view = _viewer(sc); rnd = random.Random(frame); P = Vector(point); objects = []
    for i in range(8):
        a = i * math.tau / 8 + rnd.uniform(-.3, .3); d = Vector((math.cos(a), math.sin(a), 0))
        objects.append(_puff(sc, 'Dust puff', P + d * .25 * k + Vector((0, 0, .2 * k)), frame, frame + 10, rnd.uniform(.7, 1.1) * k,
                             d * 1.8 * k + Vector((0, 0, .5)), rnd, view))
    return objects


def dust_ring(sc, point, frame, radius):
    """A ring of soft dust that rolls out from the crater edge to ~2.2x the radius over 15 frames and fades."""
    if not _v2('dust_ring'): return _dust_ring_v1(sc, point, frame, radius)
    view = _viewer(sc); rnd = random.Random(frame + 3); P = Vector((point[0], point[1], 0)); objects = []
    for i in range(12):
        a = i * math.tau / 12 + rnd.uniform(-.15, .15); d = Vector((math.cos(a), math.sin(a), 0))
        objects.append(_puff(sc, 'Dust ring', P + d * radius * .9 + Vector((0, 0, .3)), frame + 1, frame + 16, rnd.uniform(.9, 1.4),
                             d * radius * 1.3 * sc.render.fps / 15 + Vector((0, 0, .4)), rnd, view, peak=.6))
    return objects


def smoke_column(sc, point, frame, hold=1.0, radius=1.1, fps=24, seed=4):
    """Dust that hangs ~`hold` s round a landing figure (he is revealed standing in it): soft lit puffs in a ring round him, kept
    below chest height, rising a little, breaking up and fading; three on the figure itself are gone in 8 frames."""
    if not _v2('smoke_column'): return _smoke_column_v1(sc, point, frame, hold, radius, fps, seed)
    view = _viewer(sc); rnd = random.Random(seed + frame); objects = []; P = Vector((point[0], point[1], 0)); n = max(8, int(hold * fps))
    for i in range(11):
        a = i * math.tau / 11 + rnd.uniform(-.2, .2); r = radius * rnd.uniform(.9, 1.7) if i >= 3 else radius * rnd.uniform(0, .3)
        life = 8 if i < 3 else n + rnd.randint(0, 6)
        objects.append(_puff(sc, 'VFX smoke column', P + Vector((math.cos(a) * r, math.sin(a) * r, rnd.uniform(.3, .75))), frame, frame + life,
                             rnd.uniform(1.2, 1.8), Vector((math.cos(a) * .25, math.sin(a) * .25, .6 * fps / life)), rnd, view, peak=.65, hold=.7))
    return objects


def charge_ball(sc, ch, hand, f0, f1, color='#49BFFF', k=1.0):
    """A growing energy ball in the hand ('both' = between the cupped hands): soft coloured glow, turning rays, a spinning twirl,
    a thin flare and a white-hot heart, all on the same point, plus its light."""
    if not _v2('charge_ball'): return _charge_ball_v1(sc, ch, hand, f0, f1, color, k)
    if (hand not in rig.SIDE and hand != 'both') or f1 <= f0:
        raise ValueError('charge_ball needs R/L/both and a positive interval')
    hs = 'RL' if hand == 'both' else hand; tips = {h: Vector((rig.SIDE[h] * .5 * S, 0, -1.9 * S)) for h in hs}
    view = _viewer(sc); pos = {}
    for f in range(f0, f1 + 1):
        view(f); pos[f] = sum((ch.arm[h].matrix_world @ tips[h] for h in hs), Vector()) / len(hs)
    P = lambda f: pos[f]
    g = lambda f: (.06 + .30 * (f - f0) / (f1 - f0)) * (1 + .06 * math.sin(f * 2)) * k
    objects = [sprite(sc, name, tex, P, f0, f1, 1, col, st, scale=lambda f, w=w, fl=fl: g(f) * w * (1 + fl * math.sin(f * 3.1)), spin=spin, alpha_k=ak, view=view, depth=.01 * i)
               for i, (name, tex, col, st, w, spin, ak, fl) in enumerate((('Charge halo', 'circle_05', color, 2.5, 7.0, 0, .5, .05), ('Charge ball', 'circle_05', color, 8, 3.4, 0, .5, 0), ('Charge rays', 'scorch_01', color, 8, 7.5, -.12, 1, .12),
                                                           ('Charge twirl', 'twirl_01', color, 14, 3.2, .55, 1, 0), ('Charge flare', 'star_06', '#FFFFFF', 25, 4.2, .02, 1, .2),
                                                           ('Charge core', 'circle_05', '#FFFFFF', 45, 1.3, 0, 1, 0)))]
    light = _lamp('Charge light', pos[f0], color, f0, f1, [(f, 500 * k * (f - f0) / (f1 - f0)) for f in range(f0, f1 + 1, 2)])
    for f in range(f0, f1 + 1): _key(light, 'location', f, pos[f])
    return objects + [light]


def energy_beam(sc, start_point, end_point, f0, f1, color='#49BFFF', size=1.0, style='full'):
    """A beam of light: soft halo + coloured body + white-hot core as streak cards that turn round the beam axis toward the camera
    (no tube, no edge), crackling lightning along it, a muzzle flare, a flare that rides the tip, sparks where it lands.
    style='line' (a deflected segment): the body and its tip only. size > 1.5 = the big beam (wider, flames, its own light)."""
    if not _v2('energy_beam'): return _energy_beam_v1(sc, start_point, end_point, f0, f1, color, size, style)
    S0, S1 = Vector(start_point), Vector(end_point); delta = S1 - S0; L = delta.length
    if L < 1e-6 or f1 - f0 < 3:
        raise ValueError('beam needs distinct endpoints and at least three frames')
    big = size > 1.5; view = _viewer(sc); objects = []   # no sc['big_beam'] (look._bloom glare 1.6 for the whole scene): the cards carry their own halo, and that glare blew the beam and the pale ground out to white
    rc, rg, rh = (.07 * size, .23 * size, .40 * size) if big else (.10 * size, .23 * size, .52 * size)
    grow = lambda f: min(1, (f - f0 + 1) / (4 if big else 3)); fade = lambda f: max(0, min(1, (f1 - f) / 3))
    mid = lambda f: S0 + delta * grow(f) / 2; tip = lambda f: S0 + delta * grow(f)
    def body(w): return lambda f: (w * fade(f) * (1 + .12 * math.sin((f - f0) * 2.4)), L * grow(f))
    # shortcut: one camera-turned card per layer; a beam fired straight down the lens shows only its flares, add crossed planes if a story needs that shot
    for i, (name, tex, w, col, st, ak, band) in enumerate((('Beam halo', 'circle_05', rh * 5, color, 2.5, .8, (0, 1)), ('Beam glow', 'circle_05', rg * 4.6, color, 8, .8, (0, 1)),
                                            ('Beam core', 'trace_07', rc * 6.7, '#FFFFFF', 60 if big else 45, 1.0, (.3, .7)))):
        objects.append(sprite(sc, name, tex, mid, f0, f1, 1, col, st, scale=body(w), axis=delta, alpha_k=ak, uv=_band(*band), view=view, depth=.01 * i))
    if style == 'full':
        n = max(2, min(8, int(L / 1.2))); seg = L / n
        fl = lambda f, i: random.Random(f * 31 + i)
        for i in range(n):   # lightning that crackles along the body: jumps sideways, flips and flickers every frame
            objects.append(sprite(sc, 'Beam crackle', 'spark_07', lambda f, i=i: S0 + delta * ((i + fl(f, i).uniform(.35, .65)) / n), f0, f1, 1, '#DFF6FF', 25,
                                  scale=lambda f, i=i: ((rg * 2.6 * fl(f, i).choice((-1, 1)) * fade(f), seg * 1.3) if grow(f) * n >= i + 1 else (0, 0)),
                                  alpha=lambda f, i=i: fl(f, i + 50).uniform(.2, 1.0), axis=delta, uv=((0, 0), (0, 1), (1, 1), (1, 0)), view=view, depth=.03))
        if big: objects += beam_flames(sc, start_point, end_point, f0, f1, color, size)
    pulse = lambda f: fade(f) * (1 + .15 * math.sin((f - f0) * 2.9))
    settle = lambda f: pulse(f) * (1.0 - .45 * min(1.0, max(0.0, (f - f0 - 4) / 6)))   # the tip flare shrinks once the beam has arrived (it must not hide the pose)
    if style == 'full':
        objects += [sprite(sc, 'Beam muzzle glow', 'circle_05', S0, f0, f1, rg * 6, color, 5, scale=pulse, alpha_k=.5, toward=.05, view=view),
                    sprite(sc, 'Beam muzzle', 'star_09', S0, f0, f1, rg * 4, '#FFFFFF', 20, scale=pulse, spin=.35, toward=.08, view=view)]
    objects += [sprite(sc, 'Beam head glow', 'circle_05', tip, f0, f1, rg * 7, color, 8, scale=settle, alpha_k=.5, toward=.1, view=view),
                sprite(sc, 'Beam head', 'star_07', tip, f0, f1, rg * 6, '#FFFFFF', 30, scale=settle, spin=-.5, toward=.15, view=view)]
    if style == 'full' and not big:   # sparks where it lands (the big beam gets palm_sparks from the fight code)
        for f in range(f0 + 3, f1 - 3, 3):
            objects += burst(sc, S1, f, ('trace_01',), n=3, speed=3, life=6, gravity=6, color='#FFFFFF', size=.35, seed=f, streak=True, window=(f0, f1), view=view, name='Beam spark')
    if big:   # a blue light that rides along the big beam
        lamp = _lamp('Beam light', S0, color, f0, f1, [(f, 6000 * min(1, (f1 - f) / 3)) for f in range(f0, f1 + 1)]); lamp.data.shadow_soft_size = 1.5; objects.append(lamp)
        for f in range(f0, f1 + 1): _key(lamp, 'location', f, S0 + delta * (min(1.0, (f - f0 + 1) / 4) * .5) + Vector((0, 0, .6)))
    return objects


def ring_flash(sc, point, axis, frame, size=1.0, color='#FFFFFF'):
    """Two shock rings that open round the beam axis (the muzzle on fire, the palm that takes the beam) plus a flash."""
    if not _v2('ring_flash'): return _ring_flash_v1(sc, point, axis, frame, size, color)
    view = _viewer(sc)
    objects = [sprite(sc, 'Beam ring', tex, point, frame, frame + 9, d * size, tint, 30, scale=((0, .15), (.35, .6), (1, 1.15)), alpha=((0, 1), (.5, .8), (1, 0)),
                      normal=axis, view=view) for tex, d, tint in (('circle_02', 2.6, color), ('circle_03', 1.7, '#9FE3FF'))]
    return objects + impact_flash(sc, point, frame, '#FFFFFF', size=.8 * size)


def palm_sparks(sc, point, f0, f1, seed=41):
    """Hot streaks flying off the palm that holds a beam: a new burst every 3 frames, on ballistic arcs."""
    if not _v2('palm_sparks'): return _palm_sparks_v1(sc, point, f0, f1, seed)
    view = _viewer(sc); objects = []
    for f in range(f0, f1, 3):
        objects += burst(sc, point, f, ('trace_01',), n=5, speed=4.5, life=8, gravity=7, color='#CFEFFF', size=.5, strength=40, seed=seed + f, streak=True, toward=.1,
                         view=view, name='Palm spark')
    return objects
