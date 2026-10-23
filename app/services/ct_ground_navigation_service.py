"""Ground-state and visual-ray gates for experimental NAV candidates, not walkability truth."""

import math


def grounded_candidate(locator, point, airborne, is_occluded):
    if len(point) != 3 or not all(math.isfinite(x) for x in point):
        raise ValueError("Finite XYZ required")
    if airborne is not None and type(airborne) is not bool:
        raise ValueError("Airborne must be bool or unknown")
    if airborne is None or airborne:
        return {"status": "ground_state_unknown" if airborne is None else "airborne", "localization": None}
    hit = locator.locate(point)
    if hit is None:
        return {"status": "grounded_unlocalized", "localization": None}
    start = (point[0], point[1], point[2] + 16)
    end = tuple(x + (16 if k == 2 else 0) for k, x in enumerate(hit["surface_position"]))
    blocked = is_occluded(start, end)
    if type(blocked) is not bool:
        raise ValueError("Ray result must be bool")
    # shortcut: a clear visual ray does not test a player hull or omitted clips; keep it a candidate until those are verified.
    return {"status": "visual_ray_blocked" if blocked else "visual_ray_clear_candidate", "localization": hit}
