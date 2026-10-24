"""Synthetic masks and invariant geometry checks, not semantic-map validation."""
import copy

import numpy as np
import pytest

from app.services.ct_geometry_service import geometry_sequence
from test_ct_linear import snapshots


def test_translation_permutation_unknown_masks_and_causality():
    rows = snapshots()
    for frame in rows:
        frame["players"][0]["position"][2] += 256
    base = geometry_sequence(rows, [])
    assert base["nodes"].shape == (5, 5, 15)
    assert base["nodes"][..., 4].sum() == 20
    assert not base["nodes"][..., 13].any()
    assert not base["node_mask"][:, 4].any() and not base["edges"][:, 4].any()
    moved = copy.deepcopy(rows)
    for frame in moved:
        frame["players"] = frame["players"][::-1]
        for player in frame["players"]:
            player["position"] = [v + 1200 for v in player["position"]]
    other = geometry_sequence(moved, [])
    np.testing.assert_allclose(other["nodes"][:, ::-1], base["nodes"], atol=1e-6)
    np.testing.assert_allclose(other["edges"][:, ::-1, ::-1], base["edges"], atol=1e-6)
    rows[-1]["players"][0]["position"][2] += 1000
    np.testing.assert_array_equal(geometry_sequence(rows, [])["nodes"][:4], base["nodes"][:4])


def test_patch_mismatch_airborne_and_bad_context():
    rows = snapshots()
    row = {"second": 10, "steamid": "0", "position": rows[0]["players"][0]["position"], "is_airborne": False,
           "versions": {"2000883": {"patch_number_matches": False, "status": "visual_ray_clear_candidate",
            "localization": {"status": "inside", "xy_residual": 0, "z_residual": 0}}}}
    assert geometry_sequence(rows, [row])["nodes"][0, 0, 10] == 1
    row["versions"]["2000883"]["patch_number_matches"] = True
    assert geometry_sequence(rows, [row])["nodes"][0, 0, 13] == 1
    row["is_airborne"] = True
    assert geometry_sequence(rows, [row])["nodes"][0, 0, 13] == 0
    with pytest.raises(ValueError):
        geometry_sequence(rows, [row, row])
    row["position"] = [999, 999, 999]
    with pytest.raises(ValueError):
        geometry_sequence(rows, [row])
