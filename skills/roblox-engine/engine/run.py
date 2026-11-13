"""R6 run: planted starts/stops and heel/toe contacts, with flight between supports.

build.walk_to can keep calling run.run; it routes through run_path. The contact
geometry and step transitions are shared with the planted walk, without changing it.
"""
import math
import bpy
import locomotion as lo


def run_planted(sc, ch, path, f_start, speed_studs_s=14, amp_deg=48, bounce_studs=0.35,
                arm_ratio=1.25, lean_deg=14, lead=4, corner_r=2.0):
    """Bake a planted step into the run, alternating support/flight, then a planted stop.

    Flight occupies the transfer between stances; the sole keeps its landing heading
    throughout ground contact, including corners. lead controls the torso lean ramp,
    rather than blending loaded legs while the body is stationary. Returns measured
    max_plant_drift over the entire start/run/stop span.
    """
    assert math.isfinite(speed_studs_s) and speed_studs_s > 0, 'run speed must be positive and finite'
    assert 0 < amp_deg < 57, 'run amplitude must be between 0 and 57 degrees'
    assert math.isfinite(bounce_studs) and bounce_studs > 0, 'run flight lift must be positive and finite'
    sc.frame_set(f_start); bpy.context.view_layer.update()
    upper = getattr(ch, 'upper', None)
    up0 = upper.rotation_euler.copy() if upper else None
    info = lo.walk_planted(sc, ch, path, f_start, speed_studs_s=speed_studs_s,
                           stride_deg=amp_deg, corner_r=corner_r, _hip_step_deg=35)
    f_run = info['f_start']; n = info['n']; N = info['N']
    # Snapshot before editing: evaluating later frames must not see interpolated new keys.
    rows = []
    for f in range(f_start, info['f_end'] + 1):
        sc.frame_set(f)
        rows.append((f, ch.root.location.copy(), [h.location.copy() for h in ch.hips],
                     [h.rotation_euler.x for h in ch.hips]))
    for f, pos, hips, angles in rows:
        i = f - f_run
        if 0 <= i <= N:
            u = (i % n) / n
            ramp = lo._sm(min(1.0, i / n, (N - i) / n))
            pos.z += bounce_studs * lo.S * max(0.0, math.cos(2 * math.pi * u)) ** 2 * ramp
            swing = 1 if info['contact'][i][0] == -1 else 0
            hips[swing].z += 0.10 * math.sin(math.pi * u) ** 2 * ramp
            ch.root.location = pos; ch.root.keyframe_insert('location', frame=f)
            for k, hp in enumerate(ch.hips):
                hp.location = hips[k]; hp.keyframe_insert('location', frame=f)
        for k, shoulder in enumerate(ch.shoulders):
            shoulder.rotation_euler = (-arm_ratio * angles[k], 0, 0)
            shoulder.keyframe_insert('rotation_euler', frame=f)
        if upper:
            ramp = lo._sm(min(1.0, (f - f_start) / max(1, lead), (info['f_end'] - f) / max(1, lead)))
            upper.rotation_euler = up0
            upper.rotation_euler.x += math.radians(lean_deg) * ramp
            upper.keyframe_insert('rotation_euler', frame=f)
    info.update(f_start=f_start, f_run_start=f_run, steps_per_s=sc.render.fps / sc.render.fps_base / n)
    info['max_plant_drift'] = lo.foot_slide(sc, ch, range(f_start, info['f_end'] + 1))[0]
    return info


def run_path(sc, ch, path, f_start, speed_studs_s=14, **kwargs):
    """Build-facing run route; use planted steps for short legs and sharp step-turns."""
    assert math.isfinite(speed_studs_s) and speed_studs_s > 0, 'run speed must be positive and finite'
    seg = min(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]))
    amp = kwargs.pop('amp_deg', 48)
    for cr, am in ((1.0, 1.0), (0.6, 1.0), (1.0, 0.85), (0.6, 0.85), (0.35, 1.0), (0.35, 0.85)):   # same retries as lo.walk_path
        try:
            return run_planted(sc, ch, path, f_start, speed_studs_s=speed_studs_s, amp_deg=amp * am,
                               corner_r=cr * min(0.8, 0.45 * seg), **kwargs)
        except AssertionError as e:
            err = e
    kwargs['amp_deg'] = amp
    print('RUN FALLBACK', ch.root.name, str(err))
    f = f_start
    for p, q in zip(path, path[1:]):
        d = math.hypot(q[0] - p[0], q[1] - p[1])
        if d < 1e-4: continue
        f = lo.step_to(sc, ch, p, f, goal_yaw=math.atan2(q[0] - p[0], -(q[1] - p[1])))
        if d < 1.5 * lo.S:
            f = lo.step_to(sc, ch, q, f)
        else:
            f = run_planted(sc, ch, [p, q], f, speed_studs_s=speed_studs_s, **kwargs)['f_end']
    return dict(f_start=f_start, f_end=f, segmented=True,
                max_plant_drift=lo.foot_slide(sc, ch, range(f_start, f + 1))[0])


def run(sc, ch, path_points, f_start, speed_studs_s=14, amp_deg=48, bounce_studs=0.35,
        arm_ratio=1.25, lean_deg=14, lead=4):
    """Compatibility entry point used by build.walk_to; returns the settled stop frame."""
    return run_path(sc, ch, path_points, f_start, speed_studs_s=speed_studs_s, amp_deg=amp_deg,
                    bounce_studs=bounce_studs, arm_ratio=arm_ratio, lean_deg=lean_deg, lead=lead)
