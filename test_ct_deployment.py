"""Deployment contract checks use synthetic data, not tactical ground truth."""
import copy

import numpy as np
import pytest

from app.services.ct_deployment_service import deployment_sequence
from app.services.ct_feature_service import feature_sequence
from test_ct_linear import snapshots


def test_original_information_dead_pairs_and_no_static_duty_labels():
    rows = snapshots()
    result = deployment_sequence(rows, [])
    assert result["nodes"].shape == (5, 5, 15)
    assert result["edges"].shape == (5, 5, 5, 3)
    base = feature_sequence(rows)
    np.testing.assert_array_equal(result["nodes"][..., :8], base["nodes"] * base["alive"][..., None])
    assert not result["nodes"][:, 4].any() and not result["edges"][:, 4].any()
    assert not result["pair_mask"][:, np.arange(5), np.arange(5)].any()
    assert {"functional_roles", "functional_role_known"}.isdisjoint(result)
    assert not result["ground_known"].any() and not result["node_feature_mask"][..., 10:12].any()
    assert result["node_feature_mask"][..., 12].sum() == result["node_mask"].sum()
    assert result["raw_places"][0, 0] == rows[0]["players"][0]["place"]


def test_motion_separates_rigid_translation_and_masks_unknown_intervals():
    stationary = snapshots()
    for frame in stationary:
        for i, player in enumerate(frame["players"]):
            player["position"] = [i * 100, i * 40, 20]
    base = deployment_sequence(stationary, [])
    assert not base["nodes"][..., 13:].any()
    assert not base["node_feature_mask"][0, :, 13:].any()
    assert base["node_feature_mask"][1:, :4, 13:].all()
    moving = copy.deepcopy(stationary)
    for frame in moving:
        for player in frame["players"]:
            player["position"][0] += (frame["second"] - 10) * 100
            player["position"][2] -= (frame["second"] - 10) * 20
    result = deployment_sequence(moving, [])
    np.testing.assert_allclose(result["nodes"][1:, :4, 13:], np.broadcast_to([.4, -.08], (4, 4, 2)))
    np.testing.assert_allclose(result["nodes"][..., :13], base["nodes"][..., :13])
    np.testing.assert_allclose(result["edges"], base["edges"])
    for t, frame in enumerate(moving):
        frame["players"] = frame["players"][t:] + frame["players"][:t]
        for player in frame["players"]:
            x, y, z = player["position"]
            player["position"] = [-y + 500, x - 800, z + 200]
    reordered = deployment_sequence(moving, [])
    for t, frame in enumerate(moving):
        order = [int(p["steamid"]) for p in frame["players"]]
        np.testing.assert_allclose(reordered["nodes"][t], result["nodes"][t, order], atol=1e-6)
        np.testing.assert_array_equal(reordered["node_feature_mask"][t], result["node_feature_mask"][t, order])
    stationary[1]["players"][0]["health"] = 0
    masked = deployment_sequence(stationary, [])
    assert not masked["node_feature_mask"][1:3, 0, 13:].any()
    assert not masked["nodes"][1:3, 0, 13:].any()
    assert masked["node_feature_mask"][3:, 0, 13:].all()


def test_same_place_keeps_resource_and_teammate_context_distinguishable():
    rows = snapshots()
    base = deployment_sequence(rows, [])
    resources = copy.deepcopy(rows)
    for frame in resources:
        frame["players"][0]["health"] = 25
        frame["players"][0]["equipment_value"] = 800
    changed = deployment_sequence(resources, [])
    np.testing.assert_array_equal(changed["raw_places"], base["raw_places"])
    assert not np.array_equal(changed["nodes"][:, 0, 5:7], base["nodes"][:, 0, 5:7])
    formation = copy.deepcopy(rows)
    for frame in formation:
        frame["players"][2]["position"][0] += 500
    changed = deployment_sequence(formation, [])
    np.testing.assert_array_equal(changed["nodes"][:, 0], base["nodes"][:, 0])
    assert not np.array_equal(changed["edges"][:, 0, 2], base["edges"][:, 0, 2])


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
    causal = deployment_sequence(rows, context)
    np.testing.assert_array_equal(causal["nodes"][:4], result["nodes"][:4])
    np.testing.assert_array_equal(causal["edges"][:4], result["edges"][:4])


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
