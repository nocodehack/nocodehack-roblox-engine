"""poses.py - named R6 poses + beat timing (anticipation -> overshoot -> settle -> hold), all in degrees.
Pose = dict of channels (missing channels = neutral):
  'R'/'L'       arm (raise, out)            raise + = forward/up, out + = away from the body
  'legR'/'legL' leg (raise, out)
  'head'        (down, left, roll)          left + = turn to the character's own left
  'body'        (forward, twist_left, lean_left)   upper body about the hips
Sides are the character's own (rig.py)."""
import math
import bpy
from mathutils import Vector
import rig

D = math.radians
NEUTRAL = {'R': (0, 3), 'L': (0, 3), 'legR': (0, 0), 'legL': (0, 0), 'head': (0, 0, 0), 'body': (0, 0, 0)}

# POSE LIBRARY v2 (critic R195: 'stiff square poses, arm slabs'): no pose is symmetric. Every one has a LINE OF ACTION (torso
# lean + twist), a head that counters or follows it, and two arms doing different jobs (one acts, one balances, often BEHIND
# the body: raise < 0). Rigid R6 arms read as slabs when both hang half-out sideways at the same angle, so an arm is either
# clearly up, clearly forward, or back/down. Contact poses (facepalm, think, cover_mouth, hands_head) keep their arm angles:
# the hand is solved onto the face by build.contact_pose.
LIB = {
    'idle':        {},
    'proud':       {'R': (-10, 14), 'L': (-5, 9), 'head': (-10, 0, 4), 'body': (-8, 6, -2)},     # chest out, arms back
    'point_R':     {'R': (80, 18), 'L': (-10, 9), 'body': (5, -12, -3), 'head': (-3, 0, 4)},     # up + out: the arm never crosses the face
    'point_L':     {'L': (80, 18), 'R': (-10, 9), 'body': (5, 12, 3), 'head': (-3, 0, -4)},
    # raised arms go up through the SIDE (out), never forward through the camera
    'shrug':       {'R': (14, 60), 'L': (4, 44), 'head': (-4, 0, 13), 'body': (-4, 4, -4)},      # hands stay below the chin
    'cheer':       {'R': (10, 130), 'L': (16, 106), 'head': (-16, 0, 5), 'body': (-9, 5, -4)},
    'fist_pump_R': {'R': (20, 152), 'L': (-12, 12), 'head': (-12, 0, -5), 'body': (-7, -8, 5)},
    'facepalm_R':  {'R': (150, -32), 'head': (24, 0, 0), 'body': (12, 0, 0)},
    'shock':       {'R': (34, 78), 'L': (12, 60), 'head': (-14, 0, 5), 'body': (-15, 5, -3)},    # thrown back, arms flung unevenly; both stay
    # under the horizontal: at 96-114 the near arm covered the turned face in a close-up (blind2_store s01 'hidden Dana face')
    'cower':       {'R': (118, -24), 'L': (104, -20), 'head': (22, 0, 7), 'body': (20, 7, 4)},
    'think_R':     {'R': (128, -36), 'L': (22, -12), 'head': (-10, 0, 12)},
    'wave_R':      {'R': (20, 150), 'L': (-6, 8), 'head': (0, 0, 8), 'body': (-3, -6, 5)},
    'talk_a':      {'R': (46, 14), 'L': (-6, 8), 'head': (0, 0, 5), 'body': (5, -7, -2)},
    'talk_b':      {'R': (4, 8), 'L': (50, 20), 'head': (0, 0, -5), 'body': (3, 8, 3)},
    'angry':       {'R': (-16, 24), 'L': (-9, 17), 'head': (10, 0, -4), 'body': (13, 5, 0)},     # leaning in, fists back
    'sad':         {'R': (7, 0), 'L': (3, 1), 'head': (34, 0, 7), 'body': (18, 0, 4)},
    'hands_up':    {'R': (10, 142), 'L': (12, 126), 'head': (-12, 0, 4), 'body': (-6, 3, -2)},
    'facepalm_L':  {'L': (150, -32), 'head': (24, 0, 0), 'body': (12, 0, 0)},
    'cover_mouth_R': {'R': (140, -35), 'head': (5, 0, 0), 'body': (-4, 0, 0)},
    'cover_mouth_L': {'L': (140, -35), 'head': (5, 0, 0), 'body': (-4, 0, 0)},
    'think_L':     {'L': (128, -36), 'R': (22, -12), 'head': (-10, 0, -12)},
    'hands_head':  {'R': (160, 40), 'L': (160, 40), 'head': (6, 0, 0), 'body': (4, 0, 0)},
    'reach_R':     {'R': (92, 10), 'body': (12, -10, 0)},
    'reach_L':     {'L': (92, 10), 'body': (12, 10, 0)},
    'carry_R':     {'R': (48, 4), 'L': (10, 6)},   # held prop at chest height, clear of the face
    'carry_L':     {'L': (48, 4), 'R': (10, 6)},
    'hold_out':    {'R': (72, 2), 'L': (72, 2)},
    'arms_crossed': {'R': (78, -38), 'L': (78, -38), 'head': (-5, 0, 7), 'body': (-5, 4, -3)},
    'look_down':   {'head': (32, 0, 5), 'body': (9, 0, 3), 'R': (4, 2), 'L': (-3, 4)},
    'look_up':     {'head': (-30, 0, -4), 'body': (-7, 0, -2), 'R': (-6, 8), 'L': (-2, 5)},
    'lean_in':     {'R': (-8, 9), 'L': (14, 6), 'head': (4, 0, 6), 'body': (18, 6, 0)},
    'kick_R':      {'legR': (70, 0), 'R': (-20, 8), 'L': (40, 10), 'body': (-12, 0, 0)},
    # v2: new silhouettes
    'recoil':      {'R': (52, 38), 'L': (30, 30), 'head': (-8, 0, -5), 'body': (-17, -6, 4)},    # pulled back, hands half up
    'gloat':       {'R': (-8, 18), 'L': (-4, 12), 'head': (-14, 0, 9), 'body': (-11, 8, 3)},
    'slump':       {'R': (9, 0), 'L': (6, 0), 'head': (26, 0, -6), 'body': (22, 0, -3)},
    'curious':     {'R': (5, 6), 'L': (-5, 5), 'head': (-2, 0, 13), 'body': (9, 0, -4)},         # head cocked, leaning toward it
    # standing stances (contrapposto: the chest leans one way, the head the other, one arm forward, one back)
    'stand_a':     {'R': (5, 8), 'L': (-6, 5), 'head': (0, 0, -4), 'body': (1.5, 5, 3.5)},
    'stand_b':     {'R': (-6, 5), 'L': (5, 8), 'head': (0, 0, 4), 'body': (1.5, -5, -3.5)},
    'stand_c':     {'R': (-7, 8), 'L': (-5, 6), 'head': (-4, 0, 3), 'body': (-3, 3, 0)},         # hands behind, chest up
    # talk gestures (TALK below picks them per line; '_s' = compact, for a seated speaker or a listener within arm's reach).
    # Forward raise stays <= 54: the hand stops at chest height, under the chin from any camera (raise 64-72 hid Dana's face in a
    # close-up: blind2_store s01)
    'explain_R':   {'R': (48, 14), 'L': (-6, 8), 'body': (5, -7, -2)},
    'open_palms':  {'R': (40, 30), 'L': (26, 20), 'body': (-3, 3, 3)},
    'insist_R':    {'R': (52, 6), 'L': (-14, 10), 'body': (12, -10, 0)},                          # jab toward the listener
    'both_down':   {'R': (30, 9), 'L': (22, 7), 'body': (9, 0, -2)},                             # two hands, the point lands
    'count_R':     {'R': (54, 24), 'L': (16, 4), 'body': (2, -6, -3)},
    'dismiss_R':   {'R': (26, 50), 'L': (-4, 6), 'body': (-6, 7, 4)},                            # flick away, leaning off
    'plead':       {'R': (50, 12), 'L': (40, 9), 'body': (10, 0, 3)},
    'ask':         {'R': (24, 50), 'L': (8, 34), 'body': (-3, 0, -5)},                           # one-sided half shrug
    'explain_s':   {'R': (34, 10), 'L': (-3, 5), 'body': (3, -4, -1)},
    'ask_s':       {'R': (18, 30), 'L': (6, 16), 'body': (-2, 0, -3)},
    'both_s':      {'R': (24, 8), 'L': (16, 6), 'body': (4, 0, -1)},
}
# TALK GESTURES per line mood: build.py walks one list in an order fixed per speaker + line (no two lines alike), alternating
# sides, so a speaker never repeats the gesture before.
TALK = {'plain': ('explain_R', 'open_palms', 'count_R', 'both_down', 'dismiss_R'),
        'hot':   ('insist_R', 'both_down', 'count_R', 'explain_R'),                              # angry / shouted / '!'
        'ask':   ('ask', 'open_palms', 'explain_R'),
        'low':   ('plead', 'explain_s', 'both_s'),                                               # sad / worried / sheepish
        'smug':  ('dismiss_R', 'explain_R', 'open_palms'),
        'small': ('explain_s', 'ask_s', 'both_s')}


def mirror(pose):
    """The same pose on the other side (R and L arms and legs swap; twist, lean, head turn and roll flip sign)."""
    src = LIB[pose] if isinstance(pose, str) else pose; sw = {'R': 'L', 'L': 'R', 'legR': 'legL', 'legL': 'legR'}
    return {sw.get(c, c): (v if c in sw else (v[0], -v[1], -v[2])) for c, v in src.items()}


def talk_mood(face, say):
    """Which TALK list a line uses, from the beat's own face and text (data the story already has)."""
    m = str(face or '').lower(); say = str(say or '')
    if any(w in m for w in ('angry', 'furious', 'scream', 'evil')) or say.endswith('!') or (say.isupper() and len(say) > 3): return 'hot'
    if any(w in m for w in ('sad', 'cry', 'worry', 'sheepish', 'scared')): return 'low'
    if '?' in say: return 'ask'
    if any(w in m for w in ('smug', 'grin', 'cool', 'silly')): return 'smug'
    return 'plain'


def talk_gestures(mood, k, seed, compact=False):
    """k (name, pose dict) gestures for one line: the mood's list in an order fixed by the seed, alternating sides."""
    import random
    names = list(TALK['small' if compact else mood]); rng = random.Random(seed); rng.shuffle(names); flip = rng.random() < 0.5
    pick = [names[i % len(names)] for i in range(k)]
    return [(n + ' (mirrored)', mirror(n)) if (i % 2 == 0) == flip else (n, dict(LIB[n])) for i, n in enumerate(pick)]


def _objs(ch):
    return {'R': ch.arm['R'], 'L': ch.arm['L'], 'legR': ch.leg['R'], 'legL': ch.leg['L'], 'head': ch.head, 'body': ch.upper}


def euler(ch, chan, v):
    """Channel values (degrees) -> rotation_euler (radians) for that pivot."""
    if chan in ('R', 'L', 'legR', 'legL'):
        s = rig.SIDE[chan[-1]]
        raise_, out = v
        return (-D(raise_), D(-s * out), 0.0)
    if chan == 'head':
        down, left, roll = v
        return (D(down), D(roll), D(left))
    fwd, twist, lean = v                       # body
    return (D(fwd), D(lean), D(twist))


def full(pose):
    src = LIB[pose] if isinstance(pose, str) else pose
    p = dict(NEUTRAL); p.update(src)
    if 'body' not in src:   # SPINE: the torso joins every arm pose (reference acting is never arms-only)
        rR, oR = p['R']; rL, oL = p['L']
        up_ = max(0.0, (max(rR, oR) - 90)) + max(0.0, (max(rL, oL) - 90))       # arms going overhead -> lean back
        fwd_ = max(0.0, min(rR, 100) - 40) * 0.08 + max(0.0, min(rL, 100) - 40) * 0.08   # reaching forward -> lean in
        twist = (max(rR, oR * 0.6) - max(rL, oL * 0.6)) * -0.08                  # one-arm action -> chest turns into it
        p['body'] = (round(fwd_ - up_ * 0.12, 1), round(max(-14, min(14, twist)), 1), 0.0)
    return p


def _value_at(sc, obj, f):
    sc.frame_set(int(f)); return Vector(obj.rotation_euler)


LEAD = {'body': -1, 'head': 1}   # FOLLOW-THROUGH: the chest leads an acted move by a frame, the head drags a frame behind the arms
CONTACT = ('facepalm_R', 'facepalm_L', 'think_R', 'think_L', 'cover_mouth_R', 'cover_mouth_L', 'hands_head')   # hand solved onto the face at t: exact timing


def beat(sc, ch, pose, t, move=4, antic=0.2, over=0.15, settle=4, skip=(), plain=()):   # snappy reference timing
    """Key `pose` so it is REACHED at frame t: hold -> anticipation (opposite, antic x delta) -> overshoot (over x delta)
    at t -> a small rebound past the pose (0.35 x the overshoot, the other way) -> settle at t+settle. With an overshoot the
    channels are offset by LEAD (overlapping action: nothing arrives on the same frame). Small moves (< 8 deg) go straight.
    over=0 or a CONTACT pose = an exact move (grabs, fight contacts, a hand on the face): no rebound, no offsets. `skip` = channels not to touch (e.g. 'head' under
    gaze). `plain` = channels that keep the overshoot but get no rebound and no offset: an arm that holds or has just let go
    of a prop (the rebound swung Jake's arm back into the crate he had dropped 3 frames earlier, blind4_gym s02). Legs are keyed ONLY when the pose names them (kick, fly, fall pose, an explicit straighten); otherwise they stay
    with whatever walks/steps/sits/lies. All keys stay inside [t - move - 3, t + settle + 1]."""
    p = full(pose); o = _objs(ch)
    src = LIB[pose] if isinstance(pose, str) else pose
    soft = bool(over) and settle >= 4 and not (isinstance(pose, str) and pose in CONTACT) and not any(c in src for c in ('legR', 'legL'))   # a pose with legs is a fall / kick / flight: the floor rest is solved on the plain keys (school s02: Zed 5 cm under the floor)
    legs_free = {c for c in ('legR', 'legL') if c not in src}   # LEGS belong to locomotion/seating/lying unless the pose sets
    for chan, val in p.items():                                  # them (acting reset them to neutral mid-walk: R135 Codex #1)
        if chan in skip or chan in legs_free: continue
        obj = o[chan]; v1 = Vector(euler(ch, chan, val))
        soft_c = soft and chan not in plain; tc = t + (LEAD.get(chan, 0) if soft_c else 0)
        f0 = tc - move
        v0 = _value_at(sc, obj, f0 - 2)
        d = v1 - v0
        obj.rotation_euler = v0; obj.keyframe_insert('rotation_euler', frame=f0 - 2)     # end of the previous hold
        if max(abs(c) for c in d) < D(8):
            obj.rotation_euler = v1; obj.keyframe_insert('rotation_euler', frame=tc)
            continue
        obj.rotation_euler = v0 - d * antic; obj.keyframe_insert('rotation_euler', frame=f0)
        obj.rotation_euler = v1 + d * over; obj.keyframe_insert('rotation_euler', frame=tc)
        if soft_c:
            obj.rotation_euler = v1 - d * over * 0.35; obj.keyframe_insert('rotation_euler', frame=tc + settle - 2)
        obj.rotation_euler = v1; obj.keyframe_insert('rotation_euler', frame=tc + settle)


def wiggle(sc, ch, chan, t0, t1, axis=1, amp_deg=14, period=8):
    """Oscillate one channel axis (e.g. a wave) between t0 and t1 around its value at t0."""
    obj = _objs(ch)[chan]; base = _value_at(sc, obj, t0)
    for i, f in enumerate(range(t0, t1 + 1, period // 2)):
        v = base.copy(); v[axis] += D(amp_deg) * (1 if i % 2 else -1) * (0 if f in (t0, t1) else 1)
        obj.rotation_euler = v; obj.keyframe_insert('rotation_euler', frame=f)


def jump(sc, ch, t, height=0.9, crouch=4, air=8, tuck=1.0):
    """Roblox R6 hop (rigid parts: no squash/stretch - scaling the root spread the feet 3 cm, R134): feet planted until
    takeoff at t, legs tuck in the air (one forward, one back), straight again at the landing so the soles land where they
    left. Height in studs. Returns the settle frame."""
    root = ch.root
    sc.frame_set(t - crouch - 2); base = root.location.copy()
    S = rig.S; hips = list(ch.hips)
    h0 = [h.rotation_euler.copy() for h in hips]
    def k(f, dz, tk):
        root.location = base + Vector((0, 0, dz * S)); root.keyframe_insert('location', frame=f)
        for h, e0, sg in zip(hips, h0, (1, -1)):
            h.rotation_euler = (e0.x + D(tk) * tuck * sg, e0.y, e0.z); h.keyframe_insert('rotation_euler', frame=f)
    k(t - crouch - 2, 0, 0); k(t, 0, 0); k(t + 2, 0.35 * height, 12)
    k(t + air // 2, height, 22); k(t + air - 2, 0.25 * height, 8); k(t + air, 0, 0); k(t + air + 4, 0, 0)
    return t + air + 4

def breathe(sc, ch, f0, f1, period=72, amp_deg=1.2):
    """Idle life on the upper body (adds a tiny forward/back sway on X) where nothing else keys it."""
    obj = ch.upper
    for i, f in enumerate(range(f0, f1, period // 2)):
        sc.frame_set(f); v = Vector(obj.rotation_euler); v[0] += D(amp_deg) * (1 if i % 2 else -1)
        obj.rotation_euler = v; obj.keyframe_insert('rotation_euler', frame=f)


def breathe(sc, ch, n, period_s=3.2, amp=0.015, phase=0.0):
    """Idle life on every frame 0..n-1 using ONLY location/scale channels (poses, walks, gaze and aims key rotations, so nothing
    fights): chest rises by amp (fraction of the 1 m torso), head + shoulders ride on it. Call right after the cast is built,
    before any reach/grab is solved, so contacts are computed on the breathing body."""
    fps = sc.render.fps / sc.render.fps_base; S = 0.5
    t0, h0, s0 = ch.torso.location.z, ch.head.location.z, [o.location.z for o in ch.shoulders]
    for f in range(n):
        b = amp * (0.5 - 0.5 * math.cos(2 * math.pi * f / (period_s * fps) + phase))
        ch.torso.scale.z = 1 + b; ch.torso.location.z = t0 + b * S; ch.torso.keyframe_insert('scale', frame=f)
        ch.torso.keyframe_insert('location', frame=f)
        ch.head.location.z = h0 + 2 * b * S; ch.head.keyframe_insert('location', frame=f)
        for o, z in zip(ch.shoulders, s0):
            o.location.z = z + 2 * b * S; o.keyframe_insert('location', frame=f)
