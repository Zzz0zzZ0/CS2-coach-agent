"""模拟示例：区分导航区域重编号、几何改变和连接改变。"""

import pytest

from scripts.prepare_ct_map_review import navigation_signature


def graph(first, second):
    return {first: {"hull_index": 0, "corners": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "connections": [second]},
            second: {"hull_index": 0, "corners": [[1, 0, 0], [2, 0, 0], [1, 1, 0]], "connections": []}}


def test_renumbered_areas_and_reordered_corners_are_not_geometry_changes():
    changed = graph(100, 200)
    changed[100]["corners"].reverse()
    assert navigation_signature(graph(1, 2)) == navigation_signature(changed)


def test_geometry_and_directed_connections_are_checked_separately():
    changed = graph(1, 2)
    changed[1]["connections"] = []
    assert navigation_signature(changed)[0] == navigation_signature(graph(1, 2))[0]
    assert navigation_signature(changed)[1] != navigation_signature(graph(1, 2))[1]
    changed[1]["corners"][0][2] = 100
    assert navigation_signature(changed)[0] != navigation_signature(graph(1, 2))[0]


def test_dangling_connections_fail_closed():
    changed = graph(1, 2)
    changed[1]["connections"] = [999]
    with pytest.raises(ValueError):
        navigation_signature(changed)
