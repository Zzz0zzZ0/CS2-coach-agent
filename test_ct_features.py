"""模拟示例: feature contracts only, not evidence of tactical model quality."""

import copy

import numpy as np
import pytest

from app.services.ct_feature_service import feature_sequence


def snapshots():
    return [{"second": second, "players": [
        {"steamid": str(i), "position": [i * 100, i * 50, 20], "health": 100,
         "equipment_value": 3000, "place": "BombsiteA" if i < 2 else "Middle"}
        for i in range(5)]} for second in (10, 12, 15, 18, 20)]


def test_permutation_translation_and_identity_free_features():
    original = snapshots()
    a = feature_sequence(original)
    changed = copy.deepcopy(original)
    permutation = [4, 1, 3, 0, 2]
    for s in changed:
        s["winner"] = "future outcome must be ignored"
        s["players"] = [s["players"][i] for i in permutation]
        for p in s["players"]:
            p["position"] = [v + 1000 for v in p["position"]]
    b = feature_sequence(changed)
    np.testing.assert_allclose(b["nodes"], a["nodes"][:, permutation])
    np.testing.assert_allclose(b["edges"], a["edges"][:, permutation][:, :, permutation], atol=1e-6)
    np.testing.assert_allclose(b["targets"], a["targets"], atol=1e-6)
    assert a["nodes"].shape == (5, 5, 8)


def test_dead_players_and_undefined_pair_statistics_are_separate():
    rows = snapshots()
    for s in rows:
        for p in s["players"][1:]:
            p["health"] = 0
    result = feature_sequence(rows)
    assert result["targets"][0, 5] == pytest.approx(.8)
    assert result["target_mask"][0, -2:].tolist() == [0, 0]
    assert result["alive"][0].sum() == 1


@pytest.mark.parametrize("problem", ["duplicate", "nan", "missing_place", "all_dead"])
def test_invalid_input_is_rejected(problem):
    rows = snapshots()
    if problem == "duplicate":
        rows[0]["players"][1]["steamid"] = "0"
    elif problem == "nan":
        rows[0]["players"][0]["position"][0] = float("nan")
    elif problem == "missing_place":
        rows[0]["players"][0]["place"] = None
    else:
        for p in rows[0]["players"]:
            p["health"] = 0
    with pytest.raises(ValueError):
        feature_sequence(rows)
