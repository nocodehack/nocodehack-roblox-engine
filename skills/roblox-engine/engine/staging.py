"""staging.py - ONE table of standard distances (metres; story JSON stays in studs, 1 stud = 0.5 m).
Centre-to-centre unless the name says gap. These are PREFERENCES: space.World / the reach solver decide feasibility."""
S = 0.5

DIST = {
    'walk_up_stop': 3.0 * S,      # walking up to a character: stop this far from their centre (2.5 left a 0.5-stud gap, R124)
    'give_trigger': 3.4 * S,      # a giver further than this walks up first
    'piece_stop_gap': 1.5 * S,    # walking to a set piece: stop this far in front of its nearest side
    'body_half_depth': 1.0 * S,   # added to piece_stop_gap: R6 body half depth (0.5 stud) + a margin
    'seat_approach_max': 3.2 * S, # stand-in-front distance before sitting (deep sofas need ~3 studs; shortened when furniture is closer)
    'seat_approach_min': 0.7 * S,
    'turn_clearance': 0.6 * S,    # kept free to TURN in (a 2x1 body reaches 1.06 studs at 45 deg, R118)
    'fight_guard': 3.6 * S,       # fighters' centres between strikes
    'handoff_shoulders': 3.6 * S, # nearest shoulders of giver/taker: rigid arms meet near the middle at ~92 % reach
    'min_gap': 0.15,              # minimum free gap between two bodies (edge to edge)
}


def d(key):
    """Distance in metres."""
    return DIST[key]


def studs(key):
    """Distance in studs (for code that still works in studs)."""
    return DIST[key] / S
