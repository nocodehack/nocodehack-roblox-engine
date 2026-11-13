"""release.py: launch a prop from the speed of the limb that strikes it (uses interact.drop_object).
USAGE
    import release
    v  = release.contact_velocity(sc, pivot, side, frame)            # world m/s Vector of the limb tip (central diff f-1, f+1)
    release.strike_release(sc, pivot, +1, box, strike_frame, (xmin, xmax, ymin, ymax), end_frame, gain=1.0, min_speed=0.3)
    # call after the pivot's swing is keyed; extra kwargs (floor_z, friction_s, ...) go to interact.drop_object.
"""
import bpy
from mathutils import Vector
import interact

S = interact.S


def _tip(sc, pivot, side, frame, tip_studs, offset_studs):
    sc.frame_set(frame); bpy.context.view_layer.update()
    return pivot.matrix_world @ Vector((side * offset_studs * S, 0, -tip_studs * S))


def contact_velocity(sc, pivot, side, frame, tip_studs=1.9, offset_studs=0.5, fps=24):
    a = _tip(sc, pivot, side, frame - 1, tip_studs, offset_studs)
    b = _tip(sc, pivot, side, frame + 1, tip_studs, offset_studs)
    return (b - a) * (fps / 2.0)


def strike_release(sc, pivot, side, obj, strike_frame, support_rect, end_frame, gain=1.0, min_speed=0.3, **drop_kwargs):
    v = contact_velocity(sc, pivot, side, strike_frame, fps=drop_kwargs.get('fps', 24))
    v = Vector((v.x, v.y, 0)) * gain
    if v.length < min_speed:  # too slow/vertical: push along the tip direction (default +x if none)
        d = Vector((v.x, v.y, 0)).normalized() if v.length > 1e-6 else Vector((1, 0, 0))
        v = d * min_speed
    interact.drop_object(obj, strike_frame, (v.x, v.y), support_rect, end_frame, **drop_kwargs)
    return v


# ---------------------------------------------------------------- THROW (build.py beat "throw"): ballistic flight keys
G = 9.81


def arc(obj, f0, f1, p0, p1, fps=24, g=G):
    """Key obj.location on frames f0+1..f1 along the ballistic arc that leaves p0 at f0 and is exactly at p1 on f1 (constant
    horizontal speed, g downward). Returns the velocity (m/s, Vector) at f1."""
    p0, p1 = Vector(p0), Vector(p1); T = (f1 - f0) / fps
    v0 = (p1 - p0) / T + Vector((0, 0, 0.5 * g * T))
    for f in range(f0 + 1, f1 + 1):
        t = (f - f0) / fps
        obj.location = p0 + v0 * t - Vector((0, 0, 0.5 * g * t * t)); obj.keyframe_insert('location', frame=f)
    return v0 - Vector((0, 0, g * T))


def fall(obj, f0, p0, v0, z_rest, f_max, fps=24, g=G, bounce=0.4, drag=0.5, upright=True):
    """Free flight from p0 with velocity v0 (after an impact / a missed catch) down to the height z_rest of obj's origin, ONE
    bounce (vertical speed x bounce, horizontal x drag), then rest; the tilt eases upright on the way. Keys f0+1.. and
    returns (end frame, rest position).
    shortcut: z_rest is one height (the support under the first landing); a bounce off a table edge is not modelled."""
    p, v, f = Vector(p0), Vector(v0), f0; r0 = obj.rotation_euler.copy()
    for leg in (0, 1):
        disc = v.z * v.z + 2 * g * max(0.0, p.z - z_rest)
        T = (v.z + disc ** 0.5) / g
        k = max(1, round(T * fps))
        for i in range(1, k + 1):
            if f + i > f_max: break
            t = min(T, i / fps)
            obj.location = (p.x + v.x * t, p.y + v.y * t, max(z_rest, p.z + v.z * t - 0.5 * g * t * t))
            obj.keyframe_insert('location', frame=f + i)
            if upright and leg == 0:
                u = i / k; obj.rotation_euler = (r0.x * (1 - u), r0.y * (1 - u), r0.z); obj.keyframe_insert('rotation_euler', frame=f + i)
        f = min(f_max, f + k)
        p = Vector((p.x + v.x * T, p.y + v.y * T, z_rest)); v = Vector((v.x * drag, v.y * drag, bounce * (v.z - g * T) * -1))
        if v.z < 0.3 or f >= f_max: break
    obj.location = p; obj.keyframe_insert('location', frame=min(f_max, f + 1))
    return min(f_max, f + 1), p
