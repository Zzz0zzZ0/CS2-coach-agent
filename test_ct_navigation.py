"""模拟示例：导航定位边界和楼层案例；不是历史地图兼容性真值。"""

import numpy as np
import pytest

from app.services.ct_navigation_service import NavigationLocator


def area(number, x1, y1, x2, y2, z):
    return {"area_id": number, "hull_index": 0, "corners": [[x1, y1, z], [x2, y1, z], [x2, y2, z], [x1, y2, z]]}


def test_upper_walkway_beats_lower_floor_beneath_xy_gap():
    locator = NavigationLocator([area(1, 0, 0, 20, 20, -764), area(2, 0, 0, 10, 20, -124)])
    hit = locator.locate((14, 10, -128))
    assert hit["area_id"] == 2 and hit["status"] == "bounded_snap"
    assert hit["xy_residual"] == 4 and hit["z_residual"] == 4
    assert locator.locate((14, 10, -128), max_xy=0) is None
    assert locator.locate((14, 10, -128), max_xy=3) is None


def test_sloped_surface_uses_local_height_instead_of_centroid():
    locator = NavigationLocator([{"area_id": 1, "hull_index": 0,
        "corners": [[0, 0, 0], [100, 0, 100], [100, 100, 100], [0, 100, 0]]}])
    hit = locator.locate((90, 50, 90), max_xy=0, max_z=1)
    assert hit["area_id"] == 1 and hit["status"] == "inside"
    assert hit["z_residual"] == pytest.approx(0)


def test_valid_inside_match_is_not_overridden_by_snap_across_boundary():
    locator = NavigationLocator([area(1, 0, 0, 10, 10, 40), area(2, 11, 0, 20, 10, 0)])
    hit = locator.locate((9, 5, 0))
    assert hit["area_id"] == 1 and hit["status"] == "inside"


def test_far_and_unsupported_points_stay_unknown():
    locator = NavigationLocator([area(1, 0, 0, 10, 10, 0)])
    assert locator.locate((5, 5, 65)) is None
    assert locator.locate((43, 5, 0)) is None
    assert locator.locate((5, 5, 5000)) is None
    for point in [(float("nan"), 0, 0), (0, 0), (0, 0, float("inf"))]:
        with pytest.raises(ValueError):
            locator.locate(point)
    with pytest.raises(ValueError):
        locator.locate((0, 0, 0), max_xy=-1)


def test_rigid_xy_transform_and_input_order_preserve_surface_assignment():
    polygons = [area(1, 0, 0, 10, 10, 0), area(2, 0, 0, 10, 10, -200)]
    point = np.array([12, 5, 4.0])
    before = NavigationLocator(polygons).locate(point)
    angle = .7
    rotation = np.array([[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
    shift = np.array([1000, -2000, 50])
    transformed = [{**a, "corners": (np.asarray(a["corners"]) @ rotation.T + shift).tolist()} for a in reversed(polygons)]
    after = NavigationLocator(transformed).locate(point @ rotation.T + shift)
    assert before["area_id"] == after["area_id"]
    assert before["xy_residual"] == pytest.approx(after["xy_residual"])
    assert before["z_residual"] == pytest.approx(after["z_residual"])


def test_non_player_hulls_and_degenerate_faces_are_not_candidates():
    wrong = {**area(1, 0, 0, 10, 10, 0), "hull_index": 1}
    degenerate = {"area_id": 2, "hull_index": 0, "corners": [[0, 0, 0], [1, 0, 0], [2, 0, 0]]}
    locator = NavigationLocator([wrong, degenerate])
    assert locator.locate((1, 0, 0)) is None
    with pytest.raises(ValueError):
        NavigationLocator([wrong])
