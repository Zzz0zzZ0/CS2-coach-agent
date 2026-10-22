"""模拟示例: forecasting constraints and source-only calibration contracts."""

import numpy as np
import pytest

from app.services.ct_prediction_service import calibrate_prediction, constrain_prediction, fit_shrinkage, project_prediction


def states():
    current = np.array([[[.2, .2, .1, .1, 0, .4, .1, .2],
                         [.2, .2, .1, .1, 0, .4, .1, .2]]])
    predicted = np.array([[[.3, .2, .1, .1, .1, .2, .2, .4],
                           [.1, .2, .1, .1, 0, .5, .2, .4]]])
    return current, predicted


def test_no_resurrection_projection_is_feasible_and_nonexpansive():
    current, predicted = states()
    frozen = predicted.copy()
    result = constrain_prediction(current, predicted)
    truth = np.array([[[.1, .2, .1, .1, 0, .5, .15, .3],
                       [.1, .1, .1, .1, 0, .6, .15, .3]]])
    np.testing.assert_allclose(result[..., :6].sum(-1), 1)
    assert (result[..., 5] >= current[..., 5]).all()
    assert (result >= 0).all()
    assert ((result - truth) ** 2).sum() <= ((predicted - truth) ** 2).sum()
    np.testing.assert_array_equal(predicted, frozen)
    np.testing.assert_allclose(result[:, 1], predicted[:, 1], atol=1e-15)
    dead = current.copy(); dead[..., :5] = 0; dead[..., 5] = 1
    np.testing.assert_allclose(constrain_prediction(dead, predicted)[..., :6], dead[..., :6])


def test_shrinkage_optimum_masks_and_persistence_fallback():
    current, predicted = states()
    constrained = constrain_prediction(current, predicted)
    truth = current + (constrained - current) * np.array([.25] * 6 + [.5] * 2)
    mask = np.ones_like(truth)
    scales = fit_shrinkage(current, predicted, truth, mask)
    np.testing.assert_allclose(scales, [.25, .5])
    np.testing.assert_allclose(calibrate_prediction(current, predicted, scales), truth)
    np.testing.assert_allclose(calibrate_prediction(current, predicted, [0, 0]), current, atol=1e-15)
    mask[..., 6:] = 0
    changed_truth = truth.copy(); changed_truth[..., 6:] = 999
    assert fit_shrinkage(current, predicted, changed_truth, mask)[1] == 0
    assert fit_shrinkage(current, current, current, np.ones_like(current)) == [0, 0]


@pytest.mark.parametrize("problem", ["nan", "shape", "sum", "distance", "scale", "revive", "mask"])
def test_malformed_calibration_input_rejected(problem):
    current, predicted = states()
    if problem == "scale":
        with pytest.raises(ValueError):
            calibrate_prediction(current, predicted, [2.01, .5])
        return
    if problem in ("revive", "mask"):
        truth, mask = current.copy(), np.ones_like(current)
        if problem == "revive":
            truth[..., 5] = 0
        else:
            mask[..., 0] = -.1
        with pytest.raises(ValueError):
            fit_shrinkage(current, predicted, truth, mask)
        return
    if problem == "nan":
        predicted[..., 0] = np.nan
    elif problem == "shape":
        predicted = predicted[..., :7]
    elif problem == "sum":
        predicted[..., 0] += .2
    elif problem == "distance":
        predicted[..., 6] = 2
    with pytest.raises(ValueError):
        constrain_prediction(current, predicted)


def test_extrapolation_keeps_constraints_and_can_fit_larger_changes():
    current, predicted = states()
    truth = calibrate_prediction(current, predicted, [1.5, 2])
    scales = fit_shrinkage(current, predicted, truth, np.ones_like(truth))
    np.testing.assert_allclose(calibrate_prediction(current, predicted, scales), truth, atol=1e-12)
    assert scales[0] > 1 and scales[1] == 2
    malformed = predicted.copy(); malformed[..., 0] = -2; malformed[..., 6:] = [.4, -.2]
    result = project_prediction(current, malformed)
    assert (result >= 0).all() and (result[..., 5] >= current[..., 5]).all()
    np.testing.assert_allclose(result[..., :6].sum(-1), 1)
    np.testing.assert_allclose(result[..., 6:], .1)
