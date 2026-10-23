"""Synthetic checks of richer controls; no tactical labels."""
import copy

import numpy as np
import pytest

from app.services.ct_feature_service import feature_sequence
from scripts.evaluate_ct_pooled_ridge import pooled_inputs
from test_ct_linear import snapshots


def test_features_preserve_permutation_causality_and_do_not_read_targets():
    data = {k: v[None] for k, v in feature_sequence(snapshots()).items()}
    original, _ = pooled_inputs(data)
    assert {k: v.shape[-1] for k, v in original.items()} == {"ridge": 10, "node_ridge": 22, "pair_ridge": 30, "pooled_ridge": 42}
    permutation = [4, 1, 3, 0, 2]
    changed = copy.deepcopy(data)
    changed["nodes"] = changed["nodes"][:, :, permutation]
    changed["alive"] = changed["alive"][:, :, permutation]
    changed["edges"] = changed["edges"][:, :, permutation][:, :, :, permutation]
    changed["targets"][:] = 999
    reordered, _ = pooled_inputs(changed)
    for name in original:
        np.testing.assert_allclose(original[name], reordered[name], atol=1e-6, rtol=0)
    changed["nodes"][:, 4, :, 5] = .1
    future, _ = pooled_inputs(changed)
    for name in original:
        np.testing.assert_allclose(original[name][:, :4], future[name][:, :4], atol=1e-6, rtol=0)


def test_one_survivor_and_invalid_distance():
    rows = snapshots()
    for frame in rows:
        for player in frame["players"][1:]:
            player["health"] = 0
    data = {k: v[None] for k, v in feature_sequence(rows).items()}
    features, _ = pooled_inputs(data)
    assert np.isfinite(features["pooled_ridge"]).all()
    assert not features["pair_ridge"][..., 10:].any()
    data["edges"][..., 0, 1] = -1
    with pytest.raises(ValueError):
        pooled_inputs(data)
