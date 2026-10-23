"""模拟示例：地图核查的解析与分母边界，不是专家标注。"""

import copy

import pytest

from scripts.audit_ct_map_semantics import audit_map, live_players, lower_altitude, named_places


def snapshots():
    players = [{"steamid": str(i), "position": [0, 0, -400 if i < 2 else -640],
                "health": 100 if i < 4 else 0, "alive": i < 4, "place": "BombsiteA" if i < 2 else "Ramp"} for i in range(5)]
    return [{"second": t, "players": copy.deepcopy(players)} for t in (10, 12, 15, 18, 20)]


def test_place_dump_requires_real_place_entities_and_names():
    text = '====1====\nclassname "env_cs_place"\nplace_name "Ramp"\n====2====\nclassname "prop_static"\nplace_name "Fake"\n'
    assert named_places(text) == {"Ramp": 1}
    with pytest.raises(ValueError):
        named_places('====1====\nclassname "env_cs_place"\nplace_name ""\n')
    with pytest.raises(ValueError):
        named_places('classname "prop_static"')


def test_radar_floor_reads_lower_section_not_default_section():
    text = '"verticalsections" { "default" { "AltitudeMax" "10000" } "lower" // comment\n { "AltitudeMax" "-495" } }'
    assert lower_altitude(text) == -495
    assert lower_altitude('"map" { "scale" "7" }') is None
    with pytest.raises(ValueError):
        lower_altitude('"lower" { "AltitudeMax" "oops" }')


@pytest.mark.parametrize("change", ["nan", "ids", "order", "alive"])
def test_bad_snapshots_fail_closed(change):
    frames = snapshots()
    if change == "nan":
        frames[0]["players"][0]["position"][0] = float("nan")
    elif change == "ids":
        frames[-1]["players"][0]["steamid"] = "changed"
    elif change == "order":
        frames.reverse()
    else:
        frames[0]["players"][0]["alive"] = False
    with pytest.raises(ValueError):
        live_players(frames)


def test_inventory_excludes_dead_and_keeps_unknown_semantics():
    class Nav:
        version, sub_version, area_count = 36, 1, 2

        def find_area(self, point):
            return 1 if point[2] > -495 else None

        def area(self, area):
            return {"centroid": [0, 0, -400]}

    result = audit_map([({"id": "test", "series": "A"}, {"snapshots": snapshots()})], Nav(), {"BombsiteA": 1, "Ramp": 1}, -495)
    assert result["live_player_snapshots"] == 20
    assert result["baseline_other_fraction"] == .5
    assert result["current_nav_probe"]["assigned"] == 10
    assert result["current_nav_probe"]["no_xy_area"] == 10
    assert result["vertical_diagnostic"]["live_pair_snapshots"] == 30
    assert result["vertical_diagnostic"]["close_xy_large_dz_pairs"] == 20
    ramp = next(p for p in result["place_inventory"] if p["place"] == "Ramp")
    assert ramp["label_role_candidate"] is None
    assert ramp["semantic_review_status"] == "unreviewed"
    assert ramp["current_radar_lower_observations"] == 10
