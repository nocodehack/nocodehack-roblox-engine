"""lookat: head look-at, tracked looks and glances for R6 head pivots (face = local -Y).
Units: world metres, rotations in degrees at the API, radians in Blender. Keys euler XYZ on the head pivot.
Assumptions: key parent leans/targets BEFORE calling (they are sampled via sc.frame_set); the pivot's own
location is unaffected by its rotation; base_rot (Euler radians, parent space) is the neutral pose, None = identity.
yaw>0 turns toward +X of the base frame, pitch>0 looks up."""
import bpy, math
from mathutils import Vector, Euler, Matrix

def _eval(sc, frame):
    sc.frame_set(int(frame)); bpy.context.view_layer.update()

def _pt(target):  # world point of an object or a Vector/tuple
    return target.matrix_world.translation.copy() if hasattr(target, 'matrix_world') else Vector(target)

def _base(base_rot):
    return Matrix.Identity(3) if base_rot is None else Euler(base_rot, 'XYZ').to_matrix()

def _aim_angles(head, target, base_rot, max_yaw, max_pitch):
    """(yaw, pitch, clamped) in degrees of the target in the head's base frame; scene must be evaluated."""
    P = (head.parent.matrix_world.to_quaternion().to_matrix() @ head.matrix_parent_inverse.to_quaternion().to_matrix()) if head.parent else Matrix.Identity(3)  # Ctrl+P parent inverse counts
    d = _base(base_rot).inverted() @ (P.inverted() @ (_pt(target) - head.matrix_world.translation))
    assert d.length > 1e-6, 'target coincides with head pivot'
    yaw = 0.0 if math.hypot(d.x, d.y) < 1e-9 else math.degrees(math.atan2(d.x, -d.y))  # straight up/down: no yaw flip
    pit = math.degrees(math.atan2(d.z, math.hypot(d.x, d.y)))
    cy, cp = max(-max_yaw, min(max_yaw, yaw)), max(-max_pitch, min(max_pitch, pit))
    return cy, cp, (cy != yaw or cp != pit)

def _euler(yaw, pitch, base_rot, ref):
    """Euler for local rotation base @ Rz(yaw) @ Rx(-pitch), unwrapped near ref."""
    m = _base(base_rot) @ Euler((0, 0, math.radians(yaw)), 'XYZ').to_matrix() @ Euler((-math.radians(pitch), 0, 0), 'XYZ').to_matrix()
    return m.to_euler('XYZ', ref)

def _key(head, eul, frame):
    head.rotation_mode = 'XYZ'; head.rotation_euler = eul
    head.keyframe_insert('rotation_euler', frame=int(frame))

def look_at(sc, head_pivot, target, frame, max_yaw=70, max_pitch=35, base_rot=None):
    """Key head_pivot at frame so its face (-Y) points at target (object or world point), clamped to
    +-max_yaw / +-max_pitch degrees about base_rot. Honours the animated parent chain at that frame.
    Returns (yaw, pitch, was_clamped) in degrees."""
    _eval(sc, frame)
    yaw, pit, clamped = _aim_angles(head_pivot, target, base_rot, max_yaw, max_pitch)
    _key(head_pivot, _euler(yaw, pit, base_rot, head_pivot.rotation_euler), frame)
    return yaw, pit, clamped

def look_track(sc, head_pivot, target, frames, lead=3, hold=6, lag_frames=2, deadband=3.0,
               max_yaw=70, max_pitch=35, base_rot=None):
    """Bake a natural look over `frames` (ints, ascending). Goal = target as seen `lead` frames ahead
    (anticipation); goal only re-picked when it moved > deadband deg AND `hold` frames passed since the last
    re-pick (head dwells, saccade-like); head follows the goal by a critically damped spring with time
    constant lag_frames (lags fast targets). Returns list of (frame, yaw, pitch)."""
    frames = list(frames); goals = []
    for f in frames:  # shortcut: head position sampled at f+lead too; fine unless the head itself translates fast
        _eval(sc, f + lead)
        goals.append(_aim_angles(head_pivot, target, base_rot, max_yaw, max_pitch)[:2])
    w = 2.0 / max(lag_frames, 1e-3); pos = list(goals[0]); vel = [0.0, 0.0]
    goal = goals[0]; since = hold; out = []
    for f, g in zip(frames, goals):
        since += 1
        if since >= hold and max(abs(g[0] - goal[0]), abs(g[1] - goal[1])) > deadband:
            goal, since = g, 0
        h = 1 / 8
        for _ in range(8):  # substeps of 1/8 frame
            for i in (0, 1):
                vel[i] += (w * w * (goal[i] - pos[i]) - 2 * w * vel[i]) * h; pos[i] += vel[i] * h
        out.append((f, pos[0], pos[1]))
    ref = head_pivot.rotation_euler.copy()
    for f, y, p in out:
        ref = _euler(y, p, base_rot, ref); _key(head_pivot, ref, f)
    return out

def glance(sc, head_pivot, target, f_start, f_hold, f_return, dwell=None, max_yaw=70, max_pitch=35, base_rot=None):
    """Out-and-back: pose at f_start (as currently animated) -> looking at target at f_hold -> dwell frames
    -> back to the f_start pose at f_return. Bezier ease. Returns (yaw, pitch, clamped) of the peak."""
    assert f_start < f_hold < f_return
    _eval(sc, f_start); rest = head_pivot.rotation_euler.copy()
    dwell = max(0, min((f_return - f_hold) // 2, 4)) if dwell is None else dwell
    _key(head_pivot, rest, f_start)
    res = look_at(sc, head_pivot, target, f_hold, max_yaw, max_pitch, base_rot)
    peak = head_pivot.rotation_euler.copy()
    if dwell: _key(head_pivot, peak, f_hold + dwell)
    _key(head_pivot, rest, f_return)
    return res

def face_error(sc, head_pivot, target, frame):
    """Degrees between the head's face direction (-Y world) and the direction to target at frame."""
    _eval(sc, frame)
    face = head_pivot.matrix_world.to_quaternion() @ Vector((0, -1, 0))
    return math.degrees(face.angle(_pt(target) - head_pivot.matrix_world.translation))

"""USAGE
    import lookat
    head = bpy.data.objects['Claude head']; ball = bpy.data.objects['ball']
    # key leans/torso first, then:
    lookat.look_at(sc, head, ball, 10)                       # snap-aim at frame 10, clamped 70/35 deg
    lookat.look_track(sc, head, ball, range(20, 80), lead=3, hold=6, lag_frames=2)
    lookat.glance(sc, head, (0, 3, 2), 90, 96, 110)          # peek at a point and come back
    print(lookat.face_error(sc, head, ball, 50))             # degrees off target
    # base_rot=(math.radians(-4), 0, math.radians(-5)) keeps r6's resting head tilt as neutral.
"""
