"""模拟示例: leakage boundaries for the CT re-training matrix."""

import numpy as np
import pytest

from scripts.confirm_ct_generalization import make_folds, prefix_inputs, fit_ridge
from app.services.ct_linear_service import linear_forecast
from scripts.summarize_ct_confirmation import breakdown


def test_grouped_folds_keep_series_and_held_out_maps_out():
    records = [{"series": s, "map": m} for s, maps in {"A": ["x", "y"], "B": ["x"],
        "C": ["x", "z"], "D": ["y", "z"], "E": ["y"], "F": ["z"]}.items() for m in maps]
    folds, unsupported = make_folds(records)
    assert not unsupported
    for f in folds:
        sets = [{records[i]["series"] for i in f[k]} for k in ("train", "validation", "test")]
        assert all(sets) and not any(sets[i] & sets[j] for i in range(3) for j in range(i))
        if f["task"] in ("G4", "G5"):
            target_map = records[f["test"][0]]["map"]
            for i in f["train"] + f["validation"]:
                assert records[i]["map"] != target_map or i in f["support"]
            if f["task"] == "G5":
                assert len({records[i]["series"] for i in f["support"]}) == 1
    _, skipped = make_folds([{"series": "A", "map": "x"}, {"series": "B", "map": "y"}])
    assert any(x["task"] == "G2" for x in skipped)


def test_prefix_inputs_do_not_read_future_observations():
    original = np.arange(100, dtype=float).reshape(2, 5, 10)
    before = prefix_inputs(original)
    changed = original.copy(); changed[:, -1] = 999999
    np.testing.assert_array_equal(prefix_inputs(changed), before)
    changed[:, 2:] = -999999
    np.testing.assert_array_equal(prefix_inputs(changed)[:, :2], before[:, :2])
    assert (before[:, 0, 10:40] == 0).all()
    with pytest.raises(ValueError):
        prefix_inputs(np.zeros((2, 4, 10)))


def test_ridge_training_statistics_ignore_validation_distribution():
    x = np.arange(40, dtype=float).reshape(2, 2, 10)
    current = np.zeros((2, 2, 8)); current[..., 4] = 1
    target = current.copy(); target[..., 6:] = .2
    mask = np.ones_like(target)
    mean, std, (score, penalty, coef) = fit_ridge(x, current, target, mask,
        (x + 10000, current, target, mask), [.01, 1])
    np.testing.assert_array_equal(mean, x.mean((0, 1)))
    np.testing.assert_allclose(std, x.std((0, 1)))
    assert np.isfinite(score) and penalty in (.01, 1)
    prediction = linear_forecast(x, current, mean, std, coef)
    np.testing.assert_allclose(prediction[..., :6].sum(-1), 1)


def test_breakdown_keeps_undefined_distances_out_of_denominators():
    mask = np.ones((2, 4, 8)); mask[1, :, 6:] = 0
    errors = np.zeros_like(mask); errors[0, :, 6:] = 1
    result = breakdown(errors, mask)
    assert result["distance_mse"] == 1 and result["occupancy_mse"] == 0
    assert result["by_feature"]["mean_distance"] == 1
    assert result["by_horizon"]["10_to_12"] == pytest.approx(2 / 14)
