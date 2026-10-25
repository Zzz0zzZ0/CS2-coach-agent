"""Deployment contract checks use synthetic data, not tactical ground truth."""
import copy

import numpy as np
import pytest

from app.services.ct_deployment_service import deployment_sequence
from app.services.ct_feature_service import feature_sequence
from test_ct_linear import snapshots


def test_original_information_dead_pairs_and_unknown_semantics():
    rows = snapshots()
    result = deployment_sequence(rows, [])
    assert result["nodes"].shape == (5, 5, 13)
    assert result["edges"].shape == (5, 5, 5, 3)
    base = feature_sequence(rows)
    np.testing.assert_array_equal(result["nodes"][..., :8], base["nodes"] * base["alive"][..., None])
    assert not result["nodes"][:, 4].any() and not result["edges"][:, 4].any()
    assert not result["pair_mask"][:, np.arange(5), np.arange(5)].any()
    assert not result["functional_role_known"].any()
    np.testing.assert_array_equal(result["functional_roles"][..., -1], result["node_mask"])
    assert not result["functional_roles"][..., :-1].any()
    assert not result["ground_known"].any() and not result["node_feature_mask"][..., 10:12].any()
    assert result["node_feature_mask"][..., 12].sum() == result["node_mask"].sum()
    assert result["raw_places"][0, 0] == rows[0]["players"][0]["place"]


def test_ground_alignment_permutation_translation_and_causality():
    rows = snapshots()
    context = [{"second": 10, "steamid": "0", "position": rows[0]["players"][0]["position"],
                "is_airborne": False}]
    result = deployment_sequence(rows, context)
    assert result["ground_known"].sum() == 1 and not result["nav_diagnostic_valid"].any()
    moved, moved_context = copy.deepcopy(rows), copy.deepcopy(context)
    for frame in moved:
        frame["players"] = frame["players"][::-1]
        for player in frame["players"]:
            player["position"] = [value + 1200 for value in player["position"]]
    moved_context[0]["position"] = [value + 1200 for value in context[0]["position"]]
    after = deployment_sequence(moved, moved_context)
    np.testing.assert_allclose(after["nodes"][:, ::-1], result["nodes"], atol=1e-6)
    np.testing.assert_allclose(after["edges"][:, ::-1, ::-1], result["edges"], atol=1e-6)
    np.testing.assert_array_equal(after["node_feature_mask"][:, ::-1], result["node_feature_mask"])
    rows[-1]["players"][0]["position"][2] += 1000
    np.testing.assert_array_equal(deployment_sequence(rows, context)["nodes"][:4], result["nodes"][:4])


def test_unrelated_duplicate_or_misaligned_context_is_rejected():
    rows = snapshots()
    context = {"second": 10, "steamid": "0", "position": [999, 999, 999], "is_airborne": False}
    with pytest.raises(ValueError):
        deployment_sequence(rows, [context])
    context["second"] = 21
    with pytest.raises(ValueError):
        deployment_sequence(rows, [context])
    context["second"], context["position"] = 10, rows[0]["players"][0]["position"]
    with pytest.raises(ValueError):
        deployment_sequence(rows, [context, context])
