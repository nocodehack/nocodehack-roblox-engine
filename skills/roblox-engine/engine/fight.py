"""Keyframed R6 combat. Frames name the contact; paths use studs, contacts metres.

Author actions in timeline order and bake following VFX after character animation.
"""
import math

import bpy
from mathutils import Vector

import faces
import interact
import locomotion as lo
import poses
import rig
import staging
import space

S = rig.S
D = math.radians
GUARD = staging.studs('fight_guard')   # studs between fighters' centres when not striking
MOVES = {
    'punch_R': {'R': (92, -12), 'L': (65, 15), 'body': (8, -18, 0)},
    'punch_L': {'L': (92, -12), 'R': (65, 15), 'body': (8, 18, 0)},
    'kick_R': {'legR': (100, 0), 'R': (45, 20), 'L': (70, 15), 'body': (-12, 0, 0)},
    'uppercut_R': {'R': (145, -15), 'L': (65, 15), 'body': (-8, -15, 0)},
    'tap_R': {'R': (105, -5), 'L': (15, 15), 'body': (4, -8, 0)},   # flat-hand tap on the forehead
    'block': {'R': (125, -28), 'L': (125, -28), 'body': (6, 0, 0), 'head': (12, 0, 0)},
    'dodge_back': {'R': (60, 15), 'L': (60, 15), 'body': (-30, 0, 0)},
    'dodge_side': {'R': (55, 15), 'L': (70, 15), 'body': (0, 0, 32)},
    'hit_head': {'R': (25, 40), 'L': (20, 35), 'head': (-24, 18, -16), 'body': (-16, 8, 8)},
    'hit_body': {'R': (65, -15), 'L': (65, -15), 'head': (25, 0, 0), 'body': (25, 0, 0)},
    'taunt': {'R': (85, 25), 'L': (15, 15), 'head': (-12, -16, 0), 'body': (-5, -10, 0)},
    'power_up': {'R': (18, 32), 'L': (18, 32), 'head': (-18, 0, 0), 'body': (-8, 0, 0)},
    'fly_pose': {'R': (155, 8), 'L': (155, 8), 'legR': (-22, 5), 'legL': (-28, 5), 'body': (22, 0, 0)},
}
poses.LIB.update(MOVES)
FACE = faces.set   # story builds route faces through their face schedule instead (story_beat)


def _at(sc, frame):
    sc.frame_set(int(frame))
    bpy.context.view_layer.update()


def _key(obj, path, frame, value):
    setattr(obj, path, value)
    obj.keyframe_insert(path, frame=frame)


def _pose(ch, pose, frame, legs=True):
    for channel, value in poses.full(pose).items():
        if not legs and channel.startswith('leg'): continue   # an attacker's legs belong to its planted footwork
        _key(poses._objs(ch)[channel], 'rotation_euler', frame, poses.euler(ch, channel, value))


def _floor_clear(sc, ch, frames):
    """Support the real body through tilted poses; hair accessories do not support its weight."""
    parts = [ch.torso, ch.head_mesh] + list(ch.legs) + list(ch.arms)
    for f in frames:
        _at(sc, f)
        low = min((o.matrix_world @ Vector(c)).z for o in parts for c in o.bound_box)
        if low < 0:
            p = ch.root.location.copy(); p.z -= low
            _key(ch.root, 'location', f, p)


def _direction(xy):
    v = Vector((xy[0], xy[1], 0))
    if v.length < 1e-8:
        raise ValueError('direction_xy must be nonzero')
    return v.normalized()


def _surface(obj, origin, drop=0.0, cheek=0.0, offset=0.0):
    """Ray onto the actual mesh, including its evaluated bevel and transforms. drop = aim that far (local) below the centre."""
    mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    inv = mesh.matrix_world.inverted()
    start = inv @ origin
    center = sum((Vector(p) for p in mesh.bound_box), Vector()) / 8 + Vector((cheek, 0, -drop))
    hit, point, normal, _ = mesh.ray_cast(start, (center - start).normalized())
    if not hit:
        raise ValueError(f'Cannot find strike surface on {obj.name}')
    normal = (mesh.matrix_world.to_3x3().inverted().transposed() @ normal).normalized()
    return mesh.matrix_world @ point + normal * offset


def _snap(objs):
    return [(fc, [(tuple(k.co), tuple(k.handle_left), tuple(k.handle_right), k.interpolation, k.handle_left_type, k.handle_right_type)
                  for k in fc.keyframe_points]) for o in objs for fc in space.fcurves_of(o)]


def _restore(snap):
    """Put these curves back exactly (a rejected strike candidate must not eat the animation before `start`, e.g. a stagger)."""
    for fc, keys in snap:
        while len(fc.keyframe_points): fc.keyframe_points.remove(fc.keyframe_points[-1])
        fc.keyframe_points.add(len(keys))
        for k, (co, hl, hr, ip, tl, tr) in zip(fc.keyframe_points, keys):
            k.co = co; k.interpolation = ip; k.handle_left_type = tl; k.handle_right_type = tr; k.handle_left = hl; k.handle_right = hr
        fc.update()


def _footwork(sc, ch, start, arrive, frame, position, yaw, back, back_yaw, snap):
    """Attacker's legs: PLANTED lunge from its pose at `start` that lands on `position` at `arrive`, feet held through the strike,
    planted steps back to `back` from frame + 6. Replaces root glides (lunge + recovery slid the soles 80 cm).
    Returns (first frame, end frame)."""
    STEP = 1.0 * S   # longer planted steps tilt the box leg > 15 deg and its contact edge creeps (1 m step: 3 cm)
    _restore(snap)
    def go(f_ref, goal, goal_yaw, f_end=None):
        _at(sc, f_ref)
        turn = abs((goal_yaw - ch.root.rotation_euler.z + math.pi) % math.tau - math.pi)
        n = lo._step_count((goal.xy - ch.root.location.xy).length, turn, STEP)
        f0 = f_ref if f_end is None else max(min(f_ref, f_end - 4 * n), min(f_ref, 0))   # a long lunge starts before `start`
        _at(sc, f0); lo._hold(ch, f0)
        lo.clear_keys([ch.root] + list(ch.hips), f0 + 1)   # a rejected candidate or an older move (previous recovery, a walk)
        n = max(1, (f_end - f0) // 4) if f_end is not None else n
        d = (goal.xy - ch.root.location.xy).length   # arrive on time even if it stood further away at f0
        return f0, lo.step_to(sc, ch, goal.xy, f0, goal_yaw=goal_yaw, step_m=max(STEP, d / n + 1e-3),
                              step_deg=max(35.0, math.degrees(turn) / n + .1), frames_per_step=4)
    f0, _ = go(start, position, yaw, f_end=arrive)
    _at(sc, arrive)
    for f in (frame, frame + 6): lo._hold(ch, f)
    return f0, go(frame + 6, back, back_yaw)[1]


def _kick_clear(sc, ch, hip, z0, frames, floor):
    """Carry the kicking leg: lift its hip so the sole stays 2 cm clear of the floor (airborne, never a dragged toe)."""
    leg = ch.legs[list(ch.hips).index(hip)]
    for f in frames:
        _at(sc, f); hip.location.z = z0; bpy.context.view_layer.update()
        low = min((leg.matrix_world @ Vector(c)).z for c in leg.bound_box)
        hip.location.z = z0 + max(0.0, floor + .02 - low); hip.keyframe_insert('location', frame=f)


TAP_WINDUP = (70, 10)
NO_LOOK_WINDUP = (20, 60)   # backhand: the arm swings out wide (larger swings changed the solved twist and failed the contact gate)
TAP_HIT = {'head': (-14, 0, 0), 'body': (-10, 4, 4)}   # the defender's small recoil
TAP_AIMS = ((0, 0), (.06, 0), (.12, 0), (0, .12), (0, -.12), (0, .2), (0, -.2), (.1, .2), (.1, -.2), (.2, 0))   # (drop, cheek) on the head
_CATCH = {}   # defender name -> the hand it stops strikes with (the same hand every time)


def _catch_pose(sc, target, toward, hand, frame, foot, hold=0):
    """The defender raises ONE hand at the attacker (palm out) by frame - 2 and holds it past the contact; the other arm hangs
    relaxed. Earlier keys of that arm after frame - 6 (a previous catch's release) are replaced, so strikes in a row keep the hand up."""
    arm = target.arm[hand]; other = 'L' if hand == 'R' else 'R'
    _at(sc, frame - 7); lo.clear_keys([arm], frame - 6); arm.keyframe_insert('rotation_euler', frame=frame - 7)
    for fr in (frame - 2, frame + 6 + hold):
        _at(sc, fr)
        sh = arm.matrix_world.translation
        c = target.root.matrix_world.translation   # parallel to the body's axis toward the attacker: an arm angled in across the chest cut its own torso 12.8 cm
        d = Vector((toward.x - c.x, toward.y - c.y, 0)).normalized(); d.z = -.45 if foot else -.05
        interact.key_tip(sc, arm, rig.SIDE[hand], fr, sh + d.normalized() * math.hypot(interact.TIP, .5) * S * .85,
                         tol=.2, label=f'{target.name} catch', rx_rng=(-200, 40), ry_rng=(-130, 130))
    poses.beat(sc, target, {other: (0, 3)}, frame - 3, move=3, over=0, settle=0)
    poses.beat(sc, target, {hand: (0, 3)}, frame + 22 + hold, move=8, over=0, settle=0)   # lowers slowly unless the next strike re-keys it


def _keep_head(sc, ch, f0, f1):
    """NO-LOOK strike: the head keeps its world heading while the body turns into the strike (head yaw counter-rotated each frame,
    within 70 deg)."""
    heading = lambda: (lambda v: math.atan2(v.x, -v.y))(ch.head.matrix_world.to_3x3() @ Vector((0, -1, 0)))
    _at(sc, f0); z0 = ch.head.rotation_euler.z; h0 = heading()
    for f in range(f0, f1 + 1):   # measured: the body twist of the strike pose turns the head too
        _at(sc, f); ch.head.rotation_euler.z = z0; bpy.context.view_layer.update()
        err = (heading() - h0 + math.pi) % math.tau - math.pi
        ch.head.rotation_euler.z = z0 - max(-1.2, min(1.2, err))
        ch.head.keyframe_insert('rotation_euler', frame=f)


def attack(sc, attacker, target, move, frame, log, blocked=False, catch_hand=None, no_look=False, hold=0):
    """Contact at frame: retract, step into windup, three-frame strike, six-frame recovery.

    Appends a contact record with a target-local anchor for final-timeline validation.
    A rigid limb can also need a short step OUT when the opponent is too close.
    blocked: the defender stops the strike with one raised palm (no reaction, no push, face kept). tap_R: a flat-hand tap on the
    forehead (tiny reaction). no_look: the attacker's head keeps its heading (backhand-style swat).
    """
    if move not in ('punch_R', 'punch_L', 'kick_R', 'uppercut_R', 'tap_R'):
        raise ValueError(f'Not a strike: {move}')
    if attacker is target:
        raise ValueError('A strike needs two different characters')
    if catch_hand not in (None, 'R', 'L'):
        raise ValueError(f'catch hand must be R or L, not {catch_hand!r}')
    foot = move == 'kick_R'
    tap = move == 'tap_R'
    side = 'L' if move == 'punch_L' else 'R'
    pivot = attacker.leg[side] if foot else attacker.arm[side]
    mesh = target.torso if foot else target.head_mesh
    if blocked:   # the fist meets the defender's raised hand
        catch = catch_hand or _CATCH.setdefault(target.name, 'L' if side == 'R' else 'R')
        _CATCH[target.name] = catch
        mesh = interact.limb_mesh(target.arm[catch])
    start, ready = frame - 13, frame - 8
    arrive = frame - (5 if foot else 3)   # the lunge lands here; a kick then has two frames to cock its leg
    _at(sc, start)
    base, rot = attacker.root.location.copy(), attacker.root.rotation_euler.copy()
    floor_z = min((l.matrix_world @ Vector(c)).z for l in attacker.legs for c in l.bound_box)   # where step_to stands it
    lo._hold(attacker, start)
    lo.clear_keys([attacker.root] + list(attacker.hips), start + 1)
    snap = _snap([attacker.root] + list(attacker.hips))   # after the hold: every curve exists
    if blocked: _catch_pose(sc, target, base, catch, frame, foot, hold)
    _at(sc, frame)
    heading = mesh.matrix_world.translation - base
    yaw = math.atan2(heading.x, -heading.y)
    yaw += math.tau * round((rot.z - yaw) / math.tau)
    for f in (ready, frame, frame + 6):
        _key(attacker.root, 'rotation_euler', f, (0, 0, yaw))
    windup = dict(MOVES[move])
    windup['legR' if foot else side] = (-24, 8) if foot else ((55, 20) if move == 'uppercut_R' else TAP_WINDUP if tap else NO_LOOK_WINDUP if no_look else (25, 25))
    _pose(attacker, windup, frame - 3, legs=False)
    _pose(attacker, windup, ready, legs=False)   # retract before arriving: an extended guard sweeps into the opponent's hair
    _pose(attacker, windup, start, legs=False)
    # Direct keys preserve the full three-frame strike and six-frame recovery.
    _pose(attacker, MOVES[move], frame, legs=False)
    _pose(attacker, FIGHT_STANCE, frame + 6, legs=False)

    # Reaction starts at contact so the target cannot recoil before the fist arrives.
    reaction = 'hit_body' if foot else 'hit_head'
    if tap:   # a flick of the head, nothing more
        poses.beat(sc, target, TAP_HIT, frame + 2, move=2, antic=0, over=0, settle=0)   # leaning back with the tap also clears the arm
        poses.beat(sc, target, {'head': (0, 0, 0), 'body': (0, 0, 0)}, frame + 12, move=7, antic=0, over=0, settle=0)
    elif not blocked:
        poses.beat(sc, target, MOVES[reaction], frame + 2, move=2, antic=0, over=0, settle=0)
        poses.beat(sc, target, FIGHT_STANCE, frame + 8, move=4, antic=0, over=0, settle=0)
    _at(sc, frame)
    target_base = target.root.location.copy()
    direction = _direction(target_base - base)
    # STAGGER STEP back (planted feet), not a root shove: the 0.22 m push in 4 frames dragged the soles 11 cm (Goku vs
    # Vegeta s02, R169). A knockback that starts on this hit simply overrides the root from its own frame.
    # A target hit mid-walk stops walking: its later root/leg keys fought the stagger (Dave 7 cm, t_fight_glide).
    lo._hold(target, frame - 1); _at(sc, frame); lo._hold(target, frame)
    lo.clear_keys([target.root] + list(target.hips), frame + 1)
    g_ = target_base + direction * .22
    if not (blocked or tap):   # a stopped strike or a tap does not push the defender
        lo.step_to(sc, target, (g_.x, g_.y), frame, frames_per_step=4)
        FACE(target.name, 'angry' if foot else 'scream', frame)
        FACE(target.name, 'angry', frame + 8)
    elif tap:
        FACE(target.name, 'o', frame)

    # Contact belongs to the distal limb VOLUME, rather than a point buried inside the fist.
    limb = interact.limb_mesh(pivot)
    cap = [limb.matrix_local @ Vector(c) for c in limb.bound_box if c[2] == min(v[2] for v in limb.bound_box)]
    tips = sorted(cap, key=lambda p: -p.length) + [sum(cap, Vector()) / len(cap)]
    world = space.World(sc, rig.CAST)
    accepted = False
    last_hit = None
    stages = {'reach': 0, 'contact': 0, 'body': 0, 'recovery': 0}   # why candidates were rejected (error message)
    drop = .40 if foot else (.14 if move == 'uppercut_R' else 0.0 if tap else .20)
    aims = [(mesh, drop, 0), (mesh, .45 if foot else 0, 0),
            (mesh, drop, .15), (mesh, drop, -.15)]
    if blocked:   # toward the hand end of the raised arm
        aims = [(mesh, d, c) for d in (.40, .30, .45, .20) for c in (0, .12, -.12)]
    elif tap:     # the brow: at the head's centre or just below (hair accessories stand above it and block a higher aim)
        aims = [(mesh, d, c) for d, c in TAP_AIMS] + [(target.torso, d, 0) for d in (-.25, -.1, 0)]   # else the upper chest (a high head contact can be blocked by the defender's own shoulders)
    if not foot and not blocked and not tap:
        aims.extend((target.torso, drop, 0) for drop in (-.25, 0, .25))
    # Retry from a flank when the head/hair or the recovery blocks a frontal strike.
    for angle in (0, -25, 25, -45, 45):
        a = D(angle); delta = base - target_base
        staged = target_base + Vector((math.cos(a) * delta.x - math.sin(a) * delta.y,
                                       math.sin(a) * delta.x + math.cos(a) * delta.y, 0))
        staged.z = floor_z
        for mesh, drop, cheek in aims:
            for local_tip in tips:
                position = staged.copy(); yaw_hit = yaw
                for _ in range(12):
                    _key(attacker.root, 'location', frame, position)
                    _key(attacker.root, 'rotation_euler', frame, (0, 0, yaw_hit))
                    _at(sc, frame)
                    lat = (attacker.root.matrix_world.inverted() @ pivot.matrix_world.translation).x + local_tip.x
                    tgt = mesh.matrix_world.translation
                    fl = Vector((tgt.x - position.x, tgt.y - position.y, 0))
                    dd = max(fl.length, abs(lat) + 1e-3)
                    psi = math.atan2(fl.x, -fl.y); phi = math.asin(min(.95, abs(lat) / dd))
                    yaw_hit = min((psi + phi, psi - phi),
                                  key=lambda y: abs(math.cos(y) * fl.x + math.sin(y) * fl.y - lat))
                    yaw_hit += math.tau * round((yaw - yaw_hit) / math.tau)
                    _key(attacker.root, 'rotation_euler', frame, (0, 0, yaw_hit))
                    _at(sc, frame)
                    shoulder = pivot.matrix_world.translation
                    point = _surface(mesh, shoulder, drop, cheek, offset=.003)
                    delta = point - shoulder
                    reach = (pivot.parent.matrix_world.to_3x3() @ local_tip).length
                    if abs(delta.z) >= reach:
                        break
                    flat = Vector((delta.x, delta.y, 0))
                    if flat.length < 1e-6:
                        break
                    position += flat.normalized() * (flat.length - math.sqrt(reach * reach - delta.z * delta.z))
                else:
                    away = Vector((position.x - target_base.x, position.y - target_base.y, 0))
                    back = target_base.copy(); back.z = position.z
                    back += away.normalized() * max(GUARD * S, away.length)
                    guard_yaw = math.atan2(-away.x, away.y)
                    guard_yaw += math.tau * round((yaw_hit - guard_yaw) / math.tau)
                    first, end = _footwork(sc, attacker, start, arrive, frame, position, yaw_hit, back, guard_yaw, snap)
                    if foot:
                        _at(sc, arrive); hip_z = pivot.location.z
                        _key(pivot, 'rotation_euler', frame - 3, poses.euler(attacker, 'legR', (-24, 8)))
                    _at(sc, frame)
                    point = _surface(mesh, pivot.matrix_world.translation, drop, cheek, offset=.003)
                    # Different free-axis twists can put the same knuckle on the surface with a clear forearm.
                    for roll in (None, -60, -30, 30, 60):
                        _at(sc, frame)   # a rejected recovery leaves the scene on a different body pose
                        limits = dict(interact.REACH_LIMITS)
                        if roll is not None: limits['rz'] = (roll, roll)
                        rx, ry, rz, error, _ = interact.solve_tip(pivot.parent.matrix_world, pivot.location,
                                                                 rig.SIDE[side], point, limits=limits, h=local_tip)
                        if error > .005:
                            stages['reach'] += 1; continue
                        _key(pivot, 'rotation_euler', frame, (D(rx), D(ry), D(rz)))
                        if foot: _kick_clear(sc, attacker, pivot, hip_z, [f for f in range(arrive + 1, frame + 6) if f != frame], floor_z)
                        _at(sc, frame)
                        last_hit = world.limb_hits(limb, limb.matrix_world.copy(), frame, owner=attacker, tol=0)
                        if last_hit.depth_m > 0:
                            stages['contact'] += 1; continue
                        world.invalidate()
                        body_hit = world.motion_hit(attacker, range(min(first, start), max(end, frame + 12) + 1))
                        if body_hit:
                            stages['body'] += 1; continue
                        for fr in range(start, frame + 13):
                            _at(sc, fr)
                            last_hit = world.limb_hits(limb, limb.matrix_world.copy(), fr, owner=attacker)
                            if last_hit.depth_m > 0:
                                stages['recovery'] += 1; break
                        else:
                            accepted = True
                            break
                    if accepted: break
            if accepted: break
        if accepted: break
    if not accepted:
        raise ValueError(f'{move}: no volume-clear contact/recovery ({last_hit}) rejected {stages}')
    _floor_clear(sc, attacker, range(min(first, start), max(end, frame + 12) + 1))
    if no_look: _keep_head(sc, attacker, min(first, start), max(end, frame + 12))
    _at(sc, frame)
    error = (pivot.matrix_world @ local_tip - point).length
    assert error < .005, f'{move} f{frame}: contact error {error:.6f} m'
    log.append({'move': move, 'attacker': attacker.name, 'frame': frame, 'pivot': pivot,
                'tip_local': local_tip, 'target': mesh, 'target_local': mesh.matrix_world.inverted() @ point,
                'error_m': error, 'step_m': (position - base).length})
    return {'contact_frame': frame, 'contact_point': point.copy(), 'ok': error < .03, 'end': max(end, frame + 12)}


def block(sc, ch, frame):
    poses.beat(sc, ch, MOVES['block'], frame, move=4, over=0, settle=0)
    FACE(ch.name, 'angry', frame)
    return frame + 6


def dodge(sc, ch, frame, side='back', distance_studs=1.5):
    """Reach a back/right/left dodge at frame, then return over six frames."""
    if side not in ('back', 'R', 'L') or distance_studs < 0:
        raise ValueError('dodge needs back/R/L and a nonnegative distance')
    import locomotion
    from build import motion_trial
    _at(sc, frame - 4)
    base = ch.root.location.copy()
    local = Vector((0, 1, 0)) if side == 'back' else Vector((rig.SIDE[side], 0, 0))
    direction = ch.root.rotation_euler.to_matrix() @ local
    world = space.World(sc, rig.CAST)
    distance = distance_studs * S
    for scale in (1, .75, .5, .25, 0):
        end = base + direction * distance * scale
        def key():
            locomotion.step_to(sc, ch, end.xy, frame - 4, step_m=max(distance, .25), frames_per_step=4)
            locomotion.step_to(sc, ch, base.xy, frame + 2, step_m=max(distance, .25), frames_per_step=6)
            pose = dict(MOVES['dodge_back' if side == 'back' else 'dodge_side'])
            pose['body'] = (-30 * scale, 0, 0) if side == 'back' else (0, 0, 32 * scale * (1 if side == 'L' else -1))
            poses.beat(sc, ch, pose, frame, move=3, antic=0, over=0, settle=0)
            poses.beat(sc, ch, MOVES['block'], frame + 8, move=4, antic=0, over=0, settle=0)
            return frame + 8
        last, hit = motion_trial(sc, world, ch, key, frame - 5, frame + 8)
        if last is not None: return last
    raise ValueError(f'dodge: no clear planted step ({hit})')


# MEME LANDING ("defeated in a crater"): lying on its side, knees drawn up, one arm tucked under the chest, the other draped,
# head down with the face toward the floor. R6 boxes cannot lie flat on a side (the 2-stud torso props on its arm: ~20 cm), so
# this is the lowest pose found by a numeric sweep (torso centre 1.4 studs, was 2.1+). side 'R' = the right side is down.
CURL = {'R': (60, -90), 'L': (20, -70), 'legR': (60, 0), 'legL': (80, 0), 'head': (35, -50, 0), 'body': (35, 0, 0)}
CURL_CRATER = 3.4
# Between strikes a fighter is in a fighting stance (fists forward at chest height, slightly down, a lean): the old guard pose held both arms
# straight up (125 deg) after every strike, 'hands stuck up'. LOW_ARMS = panting, fists low.
FIGHT_STANCE = {'R': (36, 12), 'L': (30, 14), 'body': (6, 0, 0), 'head': (6, 0, 0)}
LOW_ARMS = {'R': (12, 8), 'L': (12, 8), 'body': (8, 0, 0), 'head': (14, 0, 0)}
BOTH_HIP = {'R': (-35, 5), 'L': (-35, -35), 'body': (0, -20, 0), 'head': (0, 0, 0)}   # two-hand wave charge: both arms to one hip
LYING_IDLE = {'R': (0, 3), 'L': (0, 3), 'legR': (0, 0), 'legL': (0, 0), 'head': (0, 0, 0), 'body': (0, 0, 0)}


def _curl_pose(side):
    if side not in ('R', 'L'):
        raise ValueError(f'curl side must be R or L, not {side!r}')
    return CURL if side == 'R' else poses.mirror(CURL)


def _curl_euler(direction, side, ref_z):
    """Root rotation of the curl: on its back (-90 deg), rolled onto `side`, head toward `direction`; yaw unwrapped near ref_z."""
    z = math.atan2(-direction.x, direction.y)
    z += math.tau * round((ref_z - z) / math.tau)
    return (-math.pi / 2, (-1 if side == 'R' else 1) * math.pi / 2, z)


def body_center(sc, ch, frame):
    """Ground point under the torso (the crater of a lying body is centred here, not on the feet)."""
    _at(sc, frame); p = ch.torso.matrix_world.translation
    return Vector((p.x, p.y, 0))


def down(sc, ch, frame, centre_xy, direction_xy=None, side='R'):
    """Lie curled (the meme pose) from `frame` on, with the torso over centre_xy (metres). Returns the frame it is settled."""
    pose = _curl_pose(side)
    _at(sc, frame)
    heading = ch.root.rotation_euler.to_matrix() @ Vector((0, 1, 0))   # head behind him (as if hit from the front)
    d = _direction(direction_xy) if direction_xy is not None else Vector((heading.x, heading.y, 0)).normalized()
    for chan, val in poses.full(pose).items():
        _key(poses._objs(ch)[chan], 'rotation_euler', frame, poses.euler(ch, chan, val))
    _key(ch.root, 'rotation_euler', frame, _curl_euler(d, side, ch.root.rotation_euler.z))
    _key(ch.root, 'location', frame, (ch.root.location.x, ch.root.location.y, ch.root.location.z))
    _at(sc, frame)
    c = ch.torso.matrix_world.translation
    p = ch.root.location + Vector((centre_xy[0] - c.x, centre_xy[1] - c.y, 0))
    _key(ch.root, 'location', frame, (p.x, p.y, p.z))
    _floor_rest(sc, ch, [frame])
    return frame


def _floor_rest(sc, ch, frames):
    """Exact rest: the lowest body corner touches the floor (no sinking, no floating)."""
    lo._rest_on_floor(sc, ch, frames)


def uncurl(sc, ch, frame):
    """Roll the curled body back onto its back and relax the limbs over 8 frames (then lo.get_up works as after any knockback)."""
    _at(sc, frame); r = ch.root; e = r.rotation_euler
    _key(r, 'rotation_euler', frame, (e.x, e.y, e.z))
    _key(r, 'rotation_euler', frame + 8, (-math.pi / 2, 0, e.z))
    poses.beat(sc, ch, LYING_IDLE, frame + 8, move=8, over=0, settle=0)
    _floor_rest(sc, ch, range(frame, frame + 9))
    return frame + 8


def get_up_curled(sc, ch, frame):
    """uncurl + the ordinary get_up, with the body kept exactly ON the floor throughout (the heel-edge pivot ends ~5 cm up). Returns the end frame."""
    g = uncurl(sc, ch, frame); e = lo.get_up(sc, ch, g, back=True)
    _floor_rest(sc, ch, range(g, e + 1))
    return e


def knockback(sc, ch, direction_xy, frame, distance_studs=8, height_studs=2, pose=None, side='R'):
    """24-frame sampled parabola, back landing and six-frame bounce; returns impact frame.
    pose='curl': lands curled on its side (CURL) instead of flat on its back."""
    direction = _direction(direction_xy)
    if distance_studs < 0 or height_studs < 0:
        raise ValueError('knockback distances must be nonnegative')
    if pose not in (None, 'curl'):
        raise ValueError(f'knockback pose {pose!r} is not supported (curl)')
    curl = _curl_pose(side) if pose == 'curl' else None
    _at(sc, frame)
    base, rotation = ch.root.location.copy(), ch.root.rotation_euler.copy()
    end = frame + 24
    poses.beat(sc, ch, MOVES['hit_head'], frame + 6, move=4, over=0, settle=0)
    if curl:
        poses.beat(sc, ch, curl, end, move=10, over=0, settle=0)   # the pose is complete when the body lands
        fin = _curl_euler(direction, side, rotation.z)
    else:
        fin = (-math.pi / 2, 0, rotation.z + D(25))
    destination = base + direction * distance_studs * S
    _key(ch.root, 'rotation_euler', end, fin)
    _key(ch.root, 'location', end, (destination.x, destination.y, 0))
    _at(sc, end)
    # The back rests on the floor rather than rotating the root through it.
    floor = -min((o.matrix_world @ Vector(c)).z for o in
                 [ch.torso, ch.head_mesh] + list(ch.legs) + list(ch.arms) for c in o.bound_box)
    for f in range(frame, end + 1):
        t = (f - frame) / 24
        p = base + direction * distance_studs * S * t
        p.z = base.z * (1 - t) + floor * t + 4 * height_studs * S * t * (1 - t)
        _key(ch.root, 'location', f, p)
        _key(ch.root, 'rotation_euler', f, tuple(a * (1 - t) + b * t for a, b in zip(rotation, fin)))
    for f, z in ((end + 3, floor + .14), (end + 6, floor)):
        _key(ch.root, 'location', f, (destination.x, destination.y, z))
        _key(ch.root, 'rotation_euler', f, fin)
    _floor_clear(sc, ch, range(frame, end + 7))
    return end


def fly(sc, ch, path_points_studs, f0, f1, height_studs=4):
    """Bake constant-speed flight: XY points use height_studs; XYZ points supply altitude."""
    if f1 <= f0 or len(path_points_studs) < 2 or any(len(p) not in (2, 3) for p in path_points_studs):
        raise ValueError('fly needs a positive interval and at least two XY/XYZ points')
    points = [Vector((p[0], p[1], p[2] if len(p) == 3 else height_studs)) * S for p in path_points_studs]
    lengths = [(b - a).length for a, b in zip(points, points[1:])]
    if min(lengths) < 1e-8:
        raise ValueError('fly waypoints must be distinct')
    _at(sc, f0 - 4)
    ch.root.keyframe_insert('location', frame=f0 - 4)
    ch.root.keyframe_insert('rotation_euler', frame=f0 - 4)
    # TAKEOFF from the ground: the soles must not move while they touch it (swinging the legs back or turning on the spot dragged
    # them 20-38 cm). Hold still, pop straight up over 2 frames (xy and yaw unchanged), and only then swing the legs, turn and travel.
    low = min((l.matrix_world @ Vector(c)).z for l in ch.legs for c in l.bound_box)
    grounded = low < .02
    yaw0 = ch.root.rotation_euler.z
    if grounded:
        pop = min(.6, max(.25, max(p.z for p in points[1:]) / S)) * S
        points[0].z += pop
        lengths = [(b - a).length for a, b in zip(points, points[1:])]
        ch.root.keyframe_insert('location', frame=f0 - 2); ch.root.keyframe_insert('rotation_euler', frame=f0 - 2)
        poses.beat(sc, ch, MOVES['fly_pose'], f0 + 6, move=4, antic=0, over=0, settle=0)
    else:
        poses.beat(sc, ch, MOVES['fly_pose'], f0 + 4, move=4, over=0, settle=0)
    for f in range(f0, f1 + 1):
        t = (f - f0) / (f1 - f0)
        remaining, index = sum(lengths) * t, 0
        while index < len(lengths) - 1 and remaining > lengths[index]:
            remaining -= lengths[index]
            index += 1
        motion = points[index + 1] - points[index]
        p = points[index].lerp(points[index + 1], remaining / lengths[index])
        p.z += .10 * math.sin(4 * math.pi * t)
        yaw = math.atan2(motion.x, -motion.y) if motion.xy.length > 1e-8 else ch.root.rotation_euler.z
        if grounded and f < f0 + 3:   # turn toward the flight while already airborne
            d_ = (yaw - yaw0 + math.pi) % math.tau - math.pi
            yaw = yaw0 + d_ * (f - f0) / 3
            p = Vector((points[0].x, points[0].y, p.z)) if f == f0 else p
        _key(ch.root, 'location', f, p)
        _key(ch.root, 'rotation_euler', f, (0, 0, yaw))
    _floor_clear(sc, ch, range(f0, f1 + 1))
    return f1


def land(sc, ch, frame):
    """Descend or stand from a back landing, with a small settling bounce."""
    _at(sc, frame)
    base, rot = ch.root.location.copy(), ch.root.rotation_euler.copy()
    ch.root.keyframe_insert('location', frame=frame)
    ch.root.keyframe_insert('rotation_euler', frame=frame)
    for f, z in ((frame + 6, 0), (frame + 8, .04), (frame + 10, 0)):
        _key(ch.root, 'location', f, (base.x, base.y, z))
        _key(ch.root, 'rotation_euler', f, (0, 0, rot.z))
    poses.beat(sc, ch, dict(MOVES['block'], legR=(0, 0), legL=(0, 0)), frame + 6, move=4, over=0, settle=0)
    _floor_clear(sc, ch, range(frame, frame + 11))
    return frame + 10


# ---------------- story-file glue (short.schema.md section 6, fight keys) ----------------
FIGHT_KEYS = ('attack', 'block', 'dodge', 'knockback', 'fly', 'land', 'power_up', 'aura', 'beam', 'exclaim', 'transform', 'down')


def _ground(ch, sc, frame):
    sc.frame_set(frame); p = ch.root.matrix_world.translation.copy(); p.z = 0
    return p


def story_beat(sc, b, ch, f, fps, cast, face_sched, fallen, settle, vfx_jobs, log):
    """One story beat's fight keys -> fight/vfx calls. Effects that follow a body are queued in vfx_jobs (build.py bakes them
    after the cameras, on the final motion). Bad input is reported in log['errors'], never a crash."""
    import vfx
    global FACE
    FACE = lambda n, k, fr: face_sched[n].__setitem__(max(0, fr), k)
    who = b['who']
    sec = lambda x: max(1, int(round(x * fps)))
    def err(m): log.setdefault('errors', []).append(f"t{b['t']} {who} {m}")
    def foe(name):
        if name not in cast or cast[name] is ch: err(f'fight target {name!r} not in cast'); return None
        return cast[name]
    try:
        if b.get('power_up'):   # seconds: brace pose + aura
            d = sec(b['power_up'] if isinstance(b['power_up'], (int, float)) else 1.5)
            poses.beat(sc, ch, MOVES['power_up'], f + 4, move=4, over=0, settle=0)
            col = b.get('aura_color', '#FFD23F')
            vfx_jobs.append(lambda: vfx.aura(sc, ch, f, f + d, col)); settle[who] = f + d
            vfx_jobs.append(lambda: vfx.ground_power(sc, ch, f, f + d))   # cracks + rising rocks on every power-up (R172)
        if 'transform' in b:   # SUPER SAIYAN-style transformation: {"hair": "lib:super_saiyan1", "hair_color": "#FFD23F",
            # "s": 2.0 charge seconds, "aura": "#FFE15A", "hold": 2.0 aura seconds after}. Power-up stance + scream face, aura
            # growing over the charge, a WHITE FLASH at 70 % of the charge that covers the HAIR SWAP (new hair shown, old hidden
            # on that exact frame), camera shake, then the aura stays (R165, creator idea 'Goku vs Vegeta with transformation').
            import rig as rig_   # aliased: a bare 'import rig' made rig LOCAL to story_beat and crashed every other beat
            tr = b['transform'] if isinstance(b['transform'], dict) else {'hair': str(b['transform'])}
            d = sec(tr.get('s', 2.0)); fx = f + int(0.7 * d); col = tr.get('aura', '#FFE15A')
            poses.beat(sc, ch, MOVES['power_up'], f + 4, move=4, over=0, settle=0)
            FACE(who, tr.get('face', 'scream'), f + 2); FACE(who, tr.get('face_after', 'smug'), fx + 6)
            old = [o for o in ch.hair_pivot.children_recursive if o.type == 'MESH']
            before = set(ch.hair_pivot.children_recursive)
            key = tr.get('hair', 'lib:super_saiyan1')
            try:
                rig_.lib_hair(ch.hair_pivot, tr.get('hair_color', '#FFD23F'), key, f'{who} hair ssj', ch.torso)
            except KeyError as e:
                err(f'transform hair {key!r} not in the library ({e})'); return
            new = [o for o in ch.hair_pivot.children_recursive if o not in before and o.type == 'MESH']
            # HAIR FLICKER (the DBZ moment): gold flashes in 3 times (2 frames each) before it locks gold on the flash frame
            flick = [fx - 12, fx - 11, fx - 7, fx - 6, fx - 3, fx - 2]
            for o, is_new in [(o, True) for o in new] + [(o, False) for o in old]:
                keys = [(0, is_new)] + [(fr_, (not is_new) if fr_ in flick else is_new) for fr_ in range(fx - 13, fx)] + [(fx, not is_new)]
                for fr_, h_ in keys:   # h_ = hidden
                    o.hide_render = o.hide_viewport = h_
                    o.keyframe_insert('hide_render', frame=fr_); o.keyframe_insert('hide_viewport', frame=fr_)
            vfx_jobs.append(lambda: vfx.ground_power(sc, ch, f, fx + 4))
            sc.frame_set(fx); hp_ = ch.head_mesh.matrix_world.translation.copy()
            vfx_jobs.append(lambda: vfx.aura(sc, ch, f + d // 3, fx + sec(tr.get('hold', 2.0)), col))
            vfx_jobs.append(lambda: vfx.impact_flash(sc, ch.head_mesh.matrix_world.translation.copy(), fx, '#FFFFFF'))
            log.setdefault('impact_frames', []).extend([fx, fx + 3])
            settle[who] = fx + 8
        if 'aura' in b:
            a = b['aura'] if isinstance(b['aura'], dict) else {'s': b['aura']}
            d2 = sec(a.get('s', 2)); col2 = a.get('color', b.get('aura_color', '#FFD23F'))
            vfx_jobs.append(lambda: vfx.aura(sc, ch, f, f + d2, col2))
        if 'fly' in b:   # {"to": [[x, y], ...] or a cast name, "height": studs, "s": seconds}
            fl = b['fly']; d = sec(fl.get('s', 1.0)); sc.frame_set(f); p0 = ch.root.matrix_world.translation / S
            to = fl.get('to')
            if isinstance(to, str):
                t_ = foe(to)
                if t_ is None: return
                q = t_.root.matrix_world.translation / S; v = (p0 - q).xy
                v = v.normalized() if v.length > 1e-6 else Vector((0, 1))
                pts = [(q.x + v.x * GUARD, q.y + v.y * GUARD)]
            else:
                pts = [tuple(p) for p in to]
            h = fl.get('height', 4)
            fly(sc, ch, [(p0.x, p0.y, max(p0.z, 0.0))] + [(p[0], p[1], h) for p in pts], f, f + d, height_studs=h)
            settle[who] = f + d
        if 'down' in b:   # {"pose": "curl", "crater": true, "side": "R", "yaw": deg}: already lying curled from t on (scene continuity)
            dn = b['down'] if isinstance(b['down'], dict) else {'pose': 'curl'}
            if dn.get('pose', 'curl') != 'curl': err(f"down pose {dn.get('pose')!r} is not supported (curl)"); return
            side_ = dn.get('side', 'R'); sc.frame_set(f)
            if 'yaw' in dn:
                ch.root.rotation_euler.z = math.radians(dn['yaw']); ch.root.keyframe_insert('rotation_euler', frame=f)
            c0 = ch.root.matrix_world.translation.copy()
            down(sc, ch, f, (c0.x, c0.y), side=side_)
            fallen[who] = -1; settle[who] = f; log.setdefault('curled', {})[who] = side_
            log.setdefault('fall_spans', []).append([who, f, 10 ** 9, 'forward'])
            if dn.get('crater', True):
                vfx_jobs.append(lambda: vfx.crater(sc, body_center(sc, ch, f), f - 1, radius=CURL_CRATER, settled=True, big=True))
        if b.get('land'):
            settle[who] = land(sc, ch, f)
            for sp_ in log.get('fall_spans', []):
                if sp_[0] == who and sp_[2] > f: sp_[2] = f
            if isinstance(b['land'], dict) and b['land'].get('crater'):   # lands in a crater with a smoke column that hangs ~1 s
                vfx_jobs.append(lambda: vfx.crater(sc, _ground(ch, sc, f + 6), f + 6, radius=2.0))
                vfx_jobs.append(lambda: vfx.smoke_column(sc, _ground(ch, sc, f + 6), f + 6))
            else:
                vfx_jobs.append(lambda: vfx.dust_burst(sc, _ground(ch, sc, f + 6), f + 6))
        if 'attack' in b:   # {"move": punch_R|punch_L|kick_R|uppercut_R, "target": name}; contact AT t
            a = b['attack'] if isinstance(b['attack'], dict) else {'move': b['attack']}
            tgt = foe(a.get('target') or b.get('target'))
            if tgt is None: return
            if 'flurry' in a:   # {"flurry": [moves], "target", "blocked": true, "s": seconds first to last contact}: strikes that come faster and faster
                mv_ = a['flurry']
                if not (isinstance(mv_, list) and len(mv_) >= 2 and all(m_ in ('punch_R', 'punch_L', 'kick_R', 'uppercut_R', 'tap_R') for m_ in mv_)):
                    err('flurry must be a list of 2+ strikes (punch_R, punch_L, kick_R, uppercut_R, tap_R)'); return
                n_ = len(mv_); tot = sec(a['s']) if isinstance(a.get('s'), (int, float)) and a['s'] > 0 else int(round(.3 * fps * (n_ - 1)))
                w_ = [1.4 - i / max(1, n_ - 2) * .8 for i in range(n_ - 1)] if n_ > 2 else [1.0]; gaps = [max(4, int(round(tot * x / sum(w_)))) for x in w_]
                gaps = [g_ + (1 if g_ in (3, 8, 13) else 0) for g_ in gaps]   # a wind-up key must never land on the previous contact frame
                fr_ = f; first_fr = f
                for i_, m_ in enumerate(mv_):
                    sub_ = {'move': m_, 'target': tgt.name, 'blocked': bool(a.get('blocked')), **({'catch': a['catch']} if 'catch' in a else {}), **({'relax': True} if i_ == n_ - 1 and a.get('relax', True) else {})}
                    story_beat(sc, {'t': round(fr_ / fps, 2), 'who': who, 'attack': sub_}, ch, fr_, fps, cast, face_sched, fallen, settle, vfx_jobs, log)
                    log.setdefault('impact_frames', []).append(fr_)   # a camera shake tick per stop
                    vfx_jobs.append(lambda fr0=fr_: vfx.dust_burst(sc, _ground(ch, sc, fr0), fr0, .45))   # a small puff at his feet
                    if i_ < n_ - 1: fr_ += gaps[i_]
                col_ = a.get('aura', '#5AC8FF')
                vfx_jobs.append(lambda: vfx.aura(sc, ch, first_fr + (fr_ - first_fr) // 2, fr_ + 8, col_))   # his aura flares as he gets desperate
                settle[who] = max(settle.get(who, 0), fr_ + 12); return
            sc.frame_set(f - 13); gap = (ch.root.matrix_world.translation - tgt.root.matrix_world.translation).xy.length / S
            if gap > GUARD + 3: err(f'attack: {tgt.name} is {gap:.1f} studs away (> {GUARD + 3:.1f}); walk/fly closer first')
            rec = []
            blk = bool(a.get('blocked'))
            r = attack(sc, ch, tgt, a['move'], f, rec, blocked=blk, catch_hand=a.get('catch'), no_look=bool(a.get('no_look')),
                       hold=sec(a['hold']) if isinstance(a.get('hold'), (int, float)) and a['hold'] > 0 and blk else 0)
            log.setdefault('fight', []).append({'t': b['t'], 'who': who, 'move': a['move'], 'target': tgt.name,
                                                'error_cm': round(rec[-1]['error_m'] * 100, 2), 'step_studs': round(rec[-1]['step_m'] / S, 2), **({'blocked': True} if blk else {})})
            quiet = blk or a['move'] == 'tap_R'   # stopped / tapped: a small flash, no impact frame (no camera shake)
            if not quiet: log.setdefault('impact_frames', []).append(f)
            p = r['contact_point'].copy(); col3 = '#FFFFFF' if blk else a.get('color', '#FFF6B0')
            vfx_jobs.append(lambda: vfx.impact_flash(sc, p, f, col3, size=.4 if quiet else 1.0))
            settle[who] = r['end']; settle[tgt.name] = max(settle.get(tgt.name, 0), f + 8)
            if a.get('relax'):   # after the last strike of a series: arms come down, fists low
                poses.beat(sc, ch, LOW_ARMS, r['end'] + 8, move=10, over=0, settle=0); settle[who] = r['end'] + 8
        if b.get('block'):
            settle[who] = block(sc, ch, f)
        if 'dodge' in b:
            settle[who] = dodge(sc, ch, f, side=b['dodge'] if b['dodge'] in ('back', 'R', 'L') else 'back')
        if 'knockback' in b:   # {"from": name, "distance": studs, "height": studs}; lands on the back (get_up works)
            k = b['knockback'] if isinstance(b['knockback'], dict) else {'from': b['knockback']}
            src = foe(k['from']) if isinstance(k.get('from'), str) else None
            sc.frame_set(f); p0 = ch.root.matrix_world.translation
            dv = (p0 - src.root.matrix_world.translation) if src else ch.root.matrix_world.to_3x3() @ Vector((0, 1, 0))
            dist = k.get('distance', 8); u = Vector((dv.x, dv.y, 0)).normalized()
            if k.get('to') is not None:   # {"to": [x, y]}: the root lands on this spot (studs); direction and distance follow from it
                tt = k['to']
                if not (isinstance(tt, (list, tuple)) and len(tt) == 2 and all(isinstance(v_, (int, float)) for v_ in tt)): err(f'knockback.to must be [x, y] studs, not {tt!r}'); return
                tv = Vector((tt[0] * S - p0.x, tt[1] * S - p0.y, 0))
                if tv.length < .5 * S: err('knockback.to is on the spot he stands on'); return
                u = tv.normalized(); dv = u; dist = tv.length / S
            import assets   # shorten the flight before solid set pieces: the body lands on its back ~5 studs long (R119 pillars)
            solids = [q['rect'] for q in assets.PLACED if q['top'] > 0.3]   # R227 chairs/seats are not 'solid' but a body cannot land in them (p8 librarian 40 cm)
            sp_ = src.root.matrix_world.translation.copy() if src else None
            # OTHER ACTORS: a landing body (a curl is ~1.7 studs wide round its centre, a back landing ~2.6) must not touch anyone's
            # footprint (standing ~1.4; lying ~1.7 / 2.6 round the torso) and the flight must not skim through a standing actor
            curl_ = k.get('pose') == 'curl'; RL = 1.7 if curl_ else 2.6; hgt_ = k.get('height', 2); people = []
            for n_, c_ in cast.items():
                if c_ is ch or c_ is src: continue
                sc.frame_set(f); t_ = c_.torso.matrix_world.translation; lying_ = n_ in fallen or abs((c_.torso.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized().z) < .6
                people.append((n_, Vector((t_.x, t_.y, 0)), (1.7 if n_ in log.get('curled', {}) else 2.6) if lying_ else 1.4))
            def person_(q, uu):   # name of the actor the landing at root q (or the flight to it) runs into, else None
                c = q + uu * (2.2 * S)
                for n_, o, ro in people:
                    if (c.xy - o.xy).length < (RL + ro) * S: return n_
                    d_ = q - p0; L_ = d_.xy.length
                    if L_ > 1e-6 and 0 < ((o - p0).xy.dot(d_.xy) / L_) < L_ + ro * S:   # the arc over a standing actor
                        t_ = ((o - p0).xy.dot(d_.xy) / L_) / L_; lat_ = abs((o - p0).xy.cross(d_.xy)) / L_
                        if lat_ < (ro + 1.0) * S and 4 * hgt_ * t_ * (1 - t_) < 5.5 and ro == 1.4: return n_
                return None
            def free_(uu):   # studs of clear floor along uu (the body lands on its back ~5 studs long)
                for s_ in range(1, int((dist + 5.5) * 4) + 1):
                    q = p0 + uu * (s_ * .25 * S)
                    if people and person_(q, uu): return s_ * .25 + 6.0   # (the caller takes 6 studs off a blocked distance: the footprints above already include the body)
                    if sp_ is not None and (q - sp_).xy.length < min(2.5 * S, (p0 - sp_).xy.length - 1e-4): return s_ * .25   # never back over the attacker (saiyan s02: a turned blast flew Vegeta through Goku's head)
                    if any(x0 - 1.8 * S < q.x < x1 + 1.8 * S and y0 - 1.8 * S < q.y < y1 + 1.8 * S for x0, x1, y0, y1 in solids): return s_ * .25   # lands rotated 25 deg, arms out
                return dist + 5.5
            if free_(u) < min(dist, 3.0) + 6.0:   # R227 no room to land this way (p8 librarian beside the chairs): turn the blast
                rot_ = lambda a_: Vector((u.x * math.cos(a_) - u.y * math.sin(a_), u.x * math.sin(a_) + u.y * math.cos(a_), 0))
                best_ = max((rot_(math.radians(a_)) for a_ in (0, 30, -30, 60, -60, 90, -90, 180)), key=lambda v_: free_(v_) - 0.01 * abs(v_.angle(u)))
                if best_ != u:
                    log.setdefault('notes', []).append(f"t{b['t']} {who} knockback from {p0.x / S:.1f},{p0.y / S:.1f} toward {u.x:.2f},{u.y:.2f} turned {math.degrees(best_.angle(u)):.0f} deg toward open floor"
                                                       f" (blocked by {next((n_ for n_ in [person_(p0 + u * (s_ * .25 * S), u) for s_ in range(1, int((dist + 5.5) * 4) + 1)] if n_), 'a set piece')})")
                    u = best_; dv = Vector((u.x, u.y, 0))
            fr_ = free_(u)
            if fr_ < dist + 5.5:
                new = max(1.5, fr_ - 6.0)
                if new < dist: log.setdefault('notes', []).append(f"t{b['t']} {who} knockback {dist} -> {new:.1f} studs (set piece behind)")
                dist = min(dist, new)
            pose_ = k.get('pose'); side_ = k.get('side', 'R')
            end = knockback(sc, ch, (dv.x, dv.y), f, dist, k.get('height', 2), pose=pose_, side=side_)
            fallen[who] = -1; settle[who] = end + 6
            log.setdefault('fall_spans', []).append([who, f, 10 ** 9, 'forward' if pose_ == 'curl' else 'backward'])   # lying: build re-rests it on the floor after the head/arm passes (Dave's head 4 cm under)
            log.setdefault('impact_frames', []).append(end)
            if pose_ == 'curl':   # always a (bigger) crater, centred under the body, which lies inside it
                log.setdefault('curled', {})[who] = side_
                bc_ = body_center(sc, ch, end); log.setdefault('notes', []).append(f"t{b['t']} {who} lands curled, body centre {bc_.x / S:.1f},{bc_.y / S:.1f} studs")
                vfx_jobs.append(lambda: vfx.crater(sc, body_center(sc, ch, end), end, radius=CURL_CRATER, big=True))
            elif k.get('height', 2) >= 1.5 or dist >= 6:   # a real blast: the landing leaves a CRATER (DBZ ground damage, R172)
                vfx_jobs.append(lambda: vfx.crater(sc, _ground(ch, sc, end), end))
            else:
                vfx_jobs.append(lambda: vfx.dust_burst(sc, _ground(ch, sc, end), end))
        if 'beam' in b:   # {"to": name, "s": beam seconds, "charge": seconds before t, "color", "hand", "hands": "both",
            # "deflect": {"after": s, "to": [x, y, z] studs, "hand": "R"}}; beam fires AT t
            bm = b['beam']; tgt = foe(bm.get('to'))
            if tgt is None: return
            both = bm.get('hands') == 'both'; hs = ('R', 'L') if both else (bm.get('hand', 'R'),)
            hand = hs[0]; piv = ch.arm[hand]; f0 = f - sec(bm.get('charge', 0.6)); f1 = f + sec(bm.get('s', 1.0))
            col4 = bm.get('color', '#49BFFF'); bsz = float(bm.get('size', 1.0)) if isinstance(bm.get('size', 1.0), (int, float)) and bm.get('size', 1.0) > 0 else 1.0
            dfl = bm.get('deflect')
            if dfl is not None and not isinstance(dfl, dict): dfl = {}
            if dfl is not None and 'to' in dfl and not (isinstance(dfl['to'], (list, tuple)) and len(dfl['to']) == 3):
                err(f"beam deflect.to must be [x, y, z] studs, not {dfl['to']!r}"); return
            fd = f + sec(dfl.get('after', 0.5)) if dfl is not None else None
            if fd is not None and not f < fd < f1 - 2: err('beam deflect.after must fall inside the beam (0 < after < s - 0.1)'); return
            sc.frame_set(f0); p0 = ch.root.matrix_world.translation.copy(); q = tgt.torso.matrix_world.translation
            yaw_b = math.atan2(q.x - p0.x, -(q.y - p0.y))
            sole = min((l.matrix_world @ Vector(c)).z for l in ch.legs for c in l.bound_box)
            try:   # face the target with PLANTED turn steps that end at f0 (the root spin slid the soles: saiyan s03 Vegeta 7 cm)
                if sole > .05: raise ValueError('airborne')
                turn = (yaw_b - ch.root.rotation_euler.z + math.pi) % math.tau - math.pi
                lo.step_to(sc, ch, p0.xy, max(0, f0 - 6 * lo._step_count(0, turn)), goal_yaw=ch.root.rotation_euler.z + turn)
                sc.frame_set(f0); lo._hold(ch, f1)
            except ValueError:   # flying or lying: no soles on the floor, the root may spin
                for fr in (f0, f1):
                    sc.frame_set(fr); p0 = ch.root.matrix_world.translation; q = tgt.torso.matrix_world.translation
                    ch.root.rotation_euler.z = math.atan2(q.x - p0.x, -(q.y - p0.y)); ch.root.keyframe_insert('rotation_euler', frame=fr)
            if both:   # the classic two-hand wave: both arms pulled back to one hip while the ball grows, thrust forward AT t
                for fr in (f0 + 6, f - 3):
                    poses.beat(sc, ch, BOTH_HIP, fr, move=6 if fr == f0 + 6 else 2, over=0, settle=0)
                poses.beat(sc, ch, {'body': (6, 0, 0)}, f, move=3, over=0, settle=0)   # chest square to the target for the thrust
            for fr in ((f, f1) if both else (f0, f, f1)):   # arms straight at the target's chest (both: parallel, from the mid-shoulder)
                sc.frame_set(fr); bpy.context.view_layer.update()
                q = tgt.torso.matrix_world.translation
                mid = sum((ch.arm[h].matrix_world.translation for h in hs), Vector()) / len(hs)
                side_x = ch.root.matrix_world.to_3x3() @ Vector((1, 0, 0))   # the character's own left
                for h in hs:
                    sh = ch.arm[h].matrix_world.translation; reach = math.hypot(interact.TIP, .5) * S * .9
                    # both hands: near-parallel arms (the arm joint stops at 35 deg inward: hands together cut the torso 14 cm or are unreachable)
                    pt = (mid + (q - mid).normalized() * reach + side_x * rig.SIDE[h] * .75) if both else sh + (q - mid).normalized() * reach
                    interact.key_tip(sc, ch.arm[h], rig.SIDE[h], fr, pt, tol=.2, label=f'{who} beam', rx_rng=(-200, 40), ry_rng=(-130, 130))
            FACE(who, 'angry', f0)
            tip = lambda h: Vector((rig.SIDE[h] * .5 * S, 0, -interact.TIP * S))
            hold = {}   # deflect: the defender's raised palm, solved now (arm keys), read when the beam is baked
            if dfl is not None:
                dh = dfl.get('hand', 'R'); dp = tgt.arm[dh] if dh in ('R', 'L') else None
                if dp is None: err(f"beam deflect.hand must be R or L, not {dfl.get('hand')!r}"); return
                for fr in (f - 6, f, fd):   # raise the palm at the attacker's hand, hold it, then flick it up and out
                    sc.frame_set(fr); bpy.context.view_layer.update()
                    sh = dp.matrix_world.translation; src_ = sum((ch.arm[h].matrix_world.translation for h in hs), Vector()) / len(hs)
                    cc_ = tgt.root.matrix_world.translation; aim = Vector((src_.x - cc_.x, src_.y - cc_.y, 0)).normalized(); aim.z = -.05   # parallel to the body axis (an arm angled across the chest cuts the torso)
                    interact.key_tip(sc, dp, rig.SIDE[dh], fr, sh + aim.normalized() * math.hypot(interact.TIP, .5) * S * .8,
                                     tol=.2, label=f'{tgt.name} catch', rx_rng=(-200, 40), ry_rng=(-130, 130))
                poses.beat(sc, tgt, {dh: (150, 55)}, fd + 4, move=3, over=0, settle=0)   # the flick: up and out
                poses.beat(sc, tgt, {dh: (0, 3)}, f1 + 8, move=8, over=0, settle=0)
                other = 'L' if dh == 'R' else 'R'
                poses.beat(sc, tgt, {other: (0, 3)}, max(1, f - 6), move=4, over=0, settle=0)   # the other arm hangs relaxed
                hold['dp'] = dp; hold['dh'] = dh
                settle[tgt.name] = max(settle.get(tgt.name, 0), f1 + 8)
            def big_extras(st_, en_):   # size > 1.5: blown dust and rocks along the path, cracks under the caster while he fires
                if bsz <= 1.5: return []
                return vfx.beam_debris(sc, st_, en_, f, f1) + vfx.ground_power(sc, ch, f, f1)
            if bsz > 1.5: log.setdefault('impact_frames', []).extend(range(f, f1, 4))   # camera shake for the whole beam
            def _beam():
                out = vfx.charge_ball(sc, ch, 'both' if both else hand, f0, f, col4, max(1.0, bsz / 2))
                sc.frame_set(f); bpy.context.view_layer.update(); st = sum((ch.arm[h].matrix_world @ tip(h) for h in hs), Vector()) / len(hs)
                if dfl is None:
                    en = _surface(tgt.torso, st)
                    return (out + vfx.energy_beam(sc, st, en, f, f1, col4, bsz) + (vfx.ring_flash(sc, st, en - st, f, bsz / 1.8) if bsz > 1.5 else []) + vfx.impact_flash(sc, en, f + 2, '#E6FBFF')
                            + vfx.sparkles(sc, en, f + 4, f1 + 6) + big_extras(st, en))
                sc.frame_set(f + 2); bpy.context.view_layer.update(); palm = hold['dp'].matrix_world @ tip(hold['dh'])
                if dfl.get('to') is not None: goal = Vector(dfl['to']) * S
                else:   # default: up into the sky, a little further along the beam
                    d_ = (palm - st); d_.z = 0; d_ = d_.normalized() if d_.length > 1e-6 else Vector((0, 1, 0))
                    goal = palm + d_ * 10 * S + Vector((0, 0, 60 * S))
                if (goal - palm).length < .5: raise ValueError('deflect.to is on the defenders hand')
                return (out + vfx.energy_beam(sc, st, palm, f, f1, col4, bsz) + big_extras(st, palm) + vfx.impact_flash(sc, palm, f + 2, '#E6FBFF')
                        + vfx.sparkles(sc, palm, f + 3, fd) + vfx.impact_flash(sc, palm, fd, '#FFFFFF')
                        + vfx.energy_beam(sc, palm, goal, fd, f1, col4, bsz * .45 if bsz > 1.5 else bsz, 'line')
                        + (vfx.ring_flash(sc, st, palm - st, f, bsz / 1.8) + vfx.ring_flash(sc, palm, palm - st, f + 2, bsz / 1.8) + vfx.palm_sparks(sc, palm, f + 2, fd + 4) if bsz > 1.5 else []))
            vfx_jobs.append(_beam); log.setdefault('impact_frames', []).append(f + 2); settle[who] = f1
        if b.get('exclaim'):
            vfx_jobs.append(lambda: vfx.exclaim(sc, ch, f))
    except (ValueError, AssertionError) as e:
        err(f'fight: {str(e)[:260]}')
