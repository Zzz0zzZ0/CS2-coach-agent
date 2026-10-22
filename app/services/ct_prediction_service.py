"""Source-validated shrinkage for experimental CT state forecasts (not tactical labels)."""

import numpy as np

CALIBRATION_VERSION = "ct-gain-v0.2"


def _states(observed, predicted):
    current = np.asarray(observed, dtype=np.float64)
    future = np.asarray(predicted, dtype=np.float64)
    if current.shape != future.shape or current.ndim < 2 or current.shape[-1] != 8 or not current.size:
        raise ValueError("Matching nonempty state arrays ending in 8 features required")
    for value in (current, future):
        if not np.isfinite(value).all() or (value < -1e-7).any():
            raise ValueError("Finite nonnegative state values required")
        if not np.allclose(value[..., :6].sum(-1), 1, atol=1e-6, rtol=0):
            raise ValueError("Occupancy and death fractions must sum to one")
        if (value[..., 6] > value[..., 7] + 1e-7).any():
            raise ValueError("Mean distance cannot exceed maximum distance")
    return current, future


def project_prediction(observed, predicted):
    """Euclidean projection onto valid occupancies, no revival, and ordered distances."""
    current, _ = _states(observed, observed)
    future = np.asarray(predicted, dtype=np.float64)
    if future.shape != current.shape or not np.isfinite(future).all():
        raise ValueError("Matching finite forecast shape required")
    result = future.copy()
    lower = np.zeros_like(future[..., :6]); lower[..., 5] = current[..., 5]
    shifted = future[..., :6] - lower
    mass = (1 - current[..., 5]).clip(0, 1)
    ordered = np.sort(shifted, axis=-1)[..., ::-1]
    thresholds = (np.cumsum(ordered, axis=-1) - mass[..., None]) / np.arange(1, 7)
    count = (ordered > thresholds).sum(-1).clip(1, 6)
    threshold = np.take_along_axis(thresholds, (count - 1)[..., None], axis=-1)
    result[..., :6] = np.maximum(shifted - threshold, 0) + lower
    distances = future[..., 6:].copy()
    invalid = distances[..., 0] > distances[..., 1]
    distances[invalid] = distances[invalid].mean(-1, keepdims=True)
    result[..., 6:] = distances.clip(0)
    return result


def constrain_prediction(observed, predicted):
    _states(observed, predicted)
    return project_prediction(observed, predicted)


def calibrate_prediction(observed, predicted, scales):
    """Scale forecast changes and enforce physical constraints, without future labels."""
    scale = np.asarray(scales, dtype=np.float64)
    if scale.shape != (2,) or not np.isfinite(scale).all() or ((scale < 0) | (scale > 2)).any():
        raise ValueError("Two forecast gains in [0, 2] required")
    current, future = _states(observed, predicted)
    constrained = constrain_prediction(current, future)
    return project_prediction(current, current + np.repeat(scale, [6, 2]) * (constrained - current))


def fit_shrinkage(observed, predicted, validation_target, validation_mask):
    """Constrained gain selection; caller must supply source validation data only."""
    current, _ = _states(observed, predicted)
    constrained = constrain_prediction(current, predicted)
    truth = np.asarray(validation_target, dtype=np.float64)
    mask = np.asarray(validation_mask, dtype=np.float64)
    if truth.shape != current.shape or mask.shape != current.shape:
        raise ValueError("Validation targets and masks must match forecast shape")
    if not np.isfinite(truth).all() or not np.isfinite(mask).all() or not np.isin(mask, [0, 1]).all():
        raise ValueError("Finite validation targets and binary masks required")
    if (truth[..., 5] < current[..., 5] - 1e-6).any():
        raise ValueError("Validation sequence contains CT resurrection")
    scales = []
    for start, end in ((0, 6), (6, 8)):
        delta = (constrained - current)[..., start:end]
        weight = mask[..., start:end]
        denominator = (delta ** 2 * weight).sum()
        numerator = (delta * (truth - current)[..., start:end] * weight).sum()
        if denominator == 0:
            scales.append(0.0)
            continue
        candidates = sorted(set(np.linspace(0, 2, 9).tolist() + [float(np.clip(numerator / denominator, 0, 2))]))
        def error(gain):
            pair = [1.0, 1.0]; pair[int(start == 6)] = gain
            forecast = calibrate_prediction(current, predicted, pair)
            return float(((forecast - truth)[..., start:end] ** 2 * weight).sum())
        scales.append(min(candidates, key=error))
    return scales
