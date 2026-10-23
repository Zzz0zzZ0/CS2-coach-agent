"""模拟示例：腾空、未知和遮挡状态边界，不是比赛走位真值。"""

import pytest

from app.services.ct_ground_navigation_service import grounded_candidate


class Locator:
    def locate(self, point):
        return {"area_id": 1, "surface_position": [1, 2, 3], "status": "bounded_snap"}


@pytest.mark.parametrize("airborne,status", [(True, "airborne"), (None, "ground_state_unknown")])
def test_ungrounded_state_does_not_assume_surface_below_player(airborne, status):
    def forbidden(*args):
        raise AssertionError("No ray or locator should be called")
    assert grounded_candidate(None, [1, 2, 3], airborne, forbidden) == {"status": status, "localization": None}


def test_ray_veto_retains_candidate_for_audit_and_uses_feet_offset():
    calls = []
    def blocked(a, b):
        calls.append((a, b))
        return True
    result = grounded_candidate(Locator(), [0, 0, 0], False, blocked)
    assert result["status"] == "visual_ray_blocked"
    assert result["localization"]["area_id"] == 1
    assert calls == [((0, 0, 16), (1, 2, 19))]
    assert grounded_candidate(Locator(), [0, 0, 0], False, lambda a, b: False)["status"] == "visual_ray_clear_candidate"


def test_bad_state_fails_closed():
    with pytest.raises(ValueError):
        grounded_candidate(Locator(), [0, 0, 0], "false", lambda a, b: False)
    with pytest.raises(ValueError):
        grounded_candidate(Locator(), [0, 0, float("nan")], False, lambda a, b: False)
    with pytest.raises(ValueError):
        grounded_candidate(Locator(), [0, 0, 0], False, lambda a, b: None)


def test_no_grounded_area_remains_unknown():
    class Empty:
        def locate(self, point):
            return None
    assert grounded_candidate(Empty(), [0, 0, 0], False, None) == {"status": "grounded_unlocalized", "localization": None}
