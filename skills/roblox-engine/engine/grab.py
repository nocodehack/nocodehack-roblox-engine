"""grab.py: prop-in-hand attachment for R6 characters, without constraints (everything is baked as keyframes).

Units: world metres, STUD = 0.5 m, frames are integers. All functions assume: the prop is an UNPARENTED object with
rotation_mode 'XYZ'; for grab() the character's arm (pivot rotation_euler) is ALREADY keyed over the hold interval
(use drive_hand, or key_tip yourself) because the prop is baked FROM the hand: the hand drives, the prop follows.
Run interact.depenetrate BEFORE grab (depenetrate moves the arm; a later grab then re-bakes the prop from the final arm).
Hand = limb tip point on the rigid limb: pivot-local (side*0.5, 0, -1.9) studs (interact.TIP), or `anchor_local` (studs).
Every hold frame is registered in interact.CONTACTS so interact.depenetrate keeps the hand where it holds the prop.

  grab(sc, pivot, side, prop, f_acquire, f_release, anchor_local=None)  prop rigidly follows the hand, offset kept
  drive_hand(sc, pivot, side, frames, path_fn)                          arm solved so the hand follows path_fn(f) (world m)
  drive_pose / tip_fk                                                   key the arm from (rx, ry[, rz]) poses / forward kinematics
  two_hand_hold(sc, pivots_sides, prop, frames, prop_path)              prop path keyed, both hands solved onto 2 anchors
  handoff(sc, giver, taker, prop, f_acquire, f_meet, f_release, taker_path) pass the prop from one character to another

USAGE
    import interact, grab
    interact.reset()
    interact.key_tip(sc, piv, +1, 10, box_face_point)                    # hand on the box at f10
    grab.drive_hand(sc, piv, +1, range(11, 41), lambda f: p0 + (p1 - p0) * smooth((f - 10) / 30))   # carry
    rep = grab.grab(sc, piv, +1, box, 10, 50)                            # box follows hand f10..f50, stays at f50
    rep2 = grab.two_hand_hold(sc, [(pivL, -1), (pivR, +1)], crate, range(10, 41), lambda f: (centre(f), (0, 0, yaw(f))))
    rep3 = grab.handoff(sc, (pivA, +1), (pivB, -1), ball, 10, 30, 50, lambda f: tray_point(f))
    interact.depenetrate(sc, piv, [], range(10, 51))                     # optional; contacts are registered and kept
"""
import math
import bpy
from mathutils import Vector, Matrix
import interact
from interact import S, TIP, CONTACTS, LIMB_HALF


def _hand_local(side, anchor_local):
    """Hand point in pivot-local metres. anchor_local is in studs (x, y, z) or None for the limb tip."""
    return Vector((side * 0.5 * S, 0, -TIP * S)) if anchor_local is None else Vector(anchor_local) * S


def _at(sc, f):
    sc.frame_set(int(f)); bpy.context.view_layer.update()


def _register(pivot, side, f, point, anchor_local):
    if anchor_local is None:  # custom anchors do not match depenetrate's tip model, so only the default is registered
        CONTACTS.setdefault(pivot.name, {})[f] = (Vector(point), TIP, side)


def grab(sc, pivot, side, prop, f_acquire, f_release, anchor_local=None):
    """Bake prop world transform every frame f_acquire..f_release from the hand; the prop keeps the offset it had at
    f_acquire (no jump) and is left exactly where it is at f_release. Before f_acquire it keeps its pose (Blender holds
    the first key). Returns {'max_dev_m': drift of the prop-in-hand offset, 'frames': n}."""
    assert prop.parent is None and prop.rotation_mode == 'XYZ', 'prop must be unparented, XYZ euler'
    assert f_release > f_acquire
    if prop.animation_data and prop.animation_data.action:
        late = prop.animation_data.action.frame_range[1]  # Blender 5 slotted actions have no .fcurves
        assert late <= f_release, f'prop has keys after f_release {f_release}: up to {late}'
    h = Matrix.Translation(_hand_local(side, anchor_local))
    _at(sc, f_acquire)
    off = (pivot.matrix_world @ h).inverted() @ prop.matrix_world.copy()
    prev = prop.rotation_euler.copy(); worst = 0.0
    for f in range(f_acquire, f_release + 1):
        _at(sc, f)
        H = pivot.matrix_world @ h
        prop.matrix_world = H @ off
        prop.rotation_euler = (H @ off).to_3x3().to_euler('XYZ', prev); prev = prop.rotation_euler.copy()
        prop.keyframe_insert('location', frame=f); prop.keyframe_insert('rotation_euler', frame=f)
        _register(pivot, side, f, H.translation, anchor_local)
        worst = max(worst, ((H.inverted() @ prop.matrix_world) - off).translation.length)
    assert worst < 1e-3, f'grab drift {worst}'
    return {'max_dev_m': worst, 'frames': f_release - f_acquire + 1}


def drive_hand(sc, pivot, side, frames, path_fn, tol=0.03, label='drive'):
    """Key the arm every frame so the hand tip follows path_fn(f) -> world point (m). Returns worst residual (m)."""
    worst = 0.0
    for f in frames:
        _at(sc, f)
        worst = max(worst, interact.key_tip(sc, pivot, side, f, path_fn(f), tol, label)[2])
    return worst


def tip_fk(sc, pivot, side, rx_deg, ry_deg, frame, rz_deg=0.0):
    """World position (m) of the hand tip at (rx, ry, rz) degrees, without changing the pivot."""
    PW, T = interact._pivot_frame(sc, pivot, frame)
    e = interact.Euler(tuple(math.radians(a) for a in (rx_deg, ry_deg, rz_deg)))
    return (PW @ T @ e.to_matrix().to_4x4()) @ _hand_local(side, None)


def drive_pose(sc, pivot, side, frames, pose_fn):
    """Key the arm directly from pose_fn(f) -> (rx_deg, ry_deg[, rz_deg]). Always reachable (a tip only reaches a thin shell around
    the shoulder: use this to swing/lift a prop along that shell). Registers the contact. Returns nothing."""
    for f in frames:
        pose = tuple(pose_fn(f))
        if len(pose) == 2: pose += (0.0,)
        rx, ry, rz = pose
        interact._key(pivot, 'rotation_euler', f, tuple(math.radians(a) for a in pose))
        interact.LAST_POSE[pivot.name] = pose
        _register(pivot, side, f, tip_fk(sc, pivot, side, rx, ry, f, rz), None)


def two_hand_hold(sc, pivots_sides, prop, frames, prop_path, anchors_local=None, tol=0.03):
    """Prop path is keyed (prop_path(f) -> (loc_m, euler_xyz_rad)); both hands are solved onto two OPPOSITE prop-local
    anchors every frame (each hand takes the anchor nearer its shoulder). Default anchors: the +-x faces of the prop,
    standing off half a limb thickness (metres, prop-local). Returns {'residual_m': measured worst hand-to-anchor error
    after keying, 'solver_residual_m', 'anchors_local'}."""
    (pa, sa), (pb, sb) = pivots_sides
    frames = list(frames)
    assert prop.parent is None and prop.rotation_mode == 'XYZ'
    if anchors_local is None:
        hx = prop.dimensions.x / 2 + LIMB_HALF
        anchors_local = (Vector((-hx, 0, 0)), Vector((hx, 0, 0)))
    for f in frames:
        loc, eul = prop_path(f)
        prop.location = loc; prop.rotation_euler = eul
        prop.keyframe_insert('location', frame=f); prop.keyframe_insert('rotation_euler', frame=f)
    worst = 0.0
    for f in frames:
        _at(sc, f)
        M = prop.matrix_world.copy(); pts = [M @ Vector(a) for a in anchors_local]
        sa_p, sb_p = pa.matrix_world.translation, pb.matrix_world.translation
        if (sa_p - pts[0]).length + (sb_p - pts[1]).length > (sa_p - pts[1]).length + (sb_p - pts[0]).length:
            pts.reverse()
        for piv, sd, p in ((pa, sa, pts[0]), (pb, sb, pts[1])):
            worst = max(worst, interact.key_tip(sc, piv, sd, f, p, tol, 'two-hand')[2])
    chk = 0.0  # independent check from the final keys
    for f in frames:
        _at(sc, f)
        M = prop.matrix_world.copy(); pts = [M @ Vector(a) for a in anchors_local]
        for piv, sd in ((pa, sa), (pb, sb)):
            hp = piv.matrix_world @ _hand_local(sd, None)
            chk = max(chk, min((hp - p).length for p in pts))
    assert chk < tol, f'two-hand residual {chk:.3f} m'
    return {'residual_m': chk, 'solver_residual_m': worst, 'anchors_local': anchors_local}


def handoff(sc, giver, taker, prop, f_acquire, f_meet, f_release, taker_path, tol=0.03):
    """giver=(pivot, side) holds the prop f_acquire..f_meet (its arm must already be keyed). At f_meet the taker's hand
    lands on the prop face that looks at the taker (axis-aligned prop faces); the taker's hand then follows
    taker_path(f) -> world m for f_meet+1..f_release and the prop follows it. The prop pose is continuous across the
    transfer. Returns {'giver': rep, 'taker': rep, 'jump_m': prop position change at f_meet}."""
    (gp, gs), (tp, ts) = giver, taker
    r1 = grab(sc, gp, gs, prop, f_acquire, f_meet)
    _at(sc, f_meet)
    c = prop.matrix_world.translation.copy(); d = tp.matrix_world.translation - c; d.z = 0
    ax = 0 if abs(d.x) >= abs(d.y) else 1
    n = Vector((0, 0, 0)); n[ax] = math.copysign(1, d[ax])
    interact.key_tip(sc, tp, ts, f_meet, c + n * (prop.dimensions[ax] / 2 + LIMB_HALF), tol, 'handoff-meet')
    drive_hand(sc, tp, ts, range(f_meet + 1, f_release + 1), taker_path, tol, 'handoff-take')
    r2 = grab(sc, tp, ts, prop, f_meet, f_release)
    _at(sc, f_meet)
    return {'giver': r1, 'taker': r2, 'jump_m': (prop.matrix_world.translation - c).length}
