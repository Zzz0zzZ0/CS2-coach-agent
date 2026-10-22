"""Small CT forecast control using current observations; experimental, not tactical intent."""

import hashlib
import json
from pathlib import Path

import numpy as np

from app.services.ct_feature_service import FEATURE_VERSION, feature_sequence
from app.services.ct_prediction_service import project_prediction

MODEL_VERSION = "ct-linear-v0.1"


def linear_inputs(data):
    """Build per-snapshot inputs without reading labels, IDs, map identity or future frames."""
    nodes, edges, alive = (np.asarray(data[k]) for k in ("nodes", "edges", "alive"))
    if nodes.ndim != 4 or nodes.shape[1:] != (5, 5, 8):
        raise ValueError("Batched five-frame CT features required")
    if edges.shape != nodes.shape[:3] + (5,) or alive.shape != nodes.shape[:3] or alive.dtype != np.bool_:
        raise ValueError("Matching distances and alive masks required")
    if not np.isfinite(nodes).all() or not np.isfinite(edges).all() or not alive.any(-1).all():
        raise ValueError("Finite states with live CTs required")
    occupancy = np.concatenate([(nodes[..., :5] * alive[..., None]).sum(2) / 5,
                                 (~alive).sum(2, keepdims=True) / 5], -1)
    pairs = np.triu(alive[..., :, None] & alive[..., None, :], 1)
    distance = edges * pairs
    statistics = np.stack([distance.sum((2, 3)) / pairs.sum((2, 3)).clip(1),
                           distance.max((2, 3))], -1)
    current = np.concatenate([occupancy, statistics], -1)
    pooled = (nodes[..., 5:7] * alive[..., None]).sum(2) / alive.sum(2, keepdims=True)
    return np.concatenate([current, pooled], -1), current


def linear_forecast(inputs, current, mean, std, coefficients):
    normalized = (inputs - mean) / std
    design = np.concatenate([normalized, np.ones_like(normalized[..., :1])], -1)
    return project_prediction(current, current + design @ coefficients)


class CTLinearPredictor:
    def __init__(self, model_path):
        payload = Path(model_path).read_bytes()
        self.sha256 = hashlib.sha256(payload).hexdigest()
        model = json.loads(payload)
        if model["model_version"] != MODEL_VERSION or model["feature_version"] != FEATURE_VERSION:
            raise ValueError("Unsupported CT model/feature version")
        self.mean = np.asarray(model["mean"], dtype=np.float64)
        self.std = np.asarray(model["std"], dtype=np.float64)
        self.coefficients = np.asarray(model["coefficients"], dtype=np.float64)
        if self.mean.shape != (10,) or self.std.shape != (10,) or self.coefficients.shape != (11, 8):
            raise ValueError("Malformed CT linear weights")
        if not all(np.isfinite(x).all() for x in (self.mean, self.std, self.coefficients)) or (self.std <= 0).any():
            raise ValueError("Finite weights and positive input scales required")
        self.model_version = model["model_version"]

    def predict(self, snapshots):
        features = feature_sequence(snapshots)
        inputs, current = linear_inputs({k: value[None] for k, value in features.items()})
        prediction = linear_forecast(inputs[:, :-1], current[:, :-1], self.mean, self.std, self.coefficients)[0]
        return {"status": "experimental_state_forecast", "model_version": self.model_version,
                "model_sha256": self.sha256, "feature_version": FEATURE_VERSION,
                "features": ["BombsiteA_live_fraction", "BombsiteB_live_fraction", "CTSpawn_live_fraction",
                             "TSpawn_live_fraction", "other_live_fraction", "dead_fraction",
                             "live_pair_mean_distance_div_5000", "live_pair_max_distance_div_5000"],
                "forecasts": [{"observed_second": start, "predicted_second": end,
                               "observed": current[0, k].tolist(), "prediction": prediction[k].tolist()}
                              for k, (start, end) in enumerate(zip((10, 12, 15, 18), (12, 15, 18, 20)))],
                "limitations": ["CT only; no tactical intent or action recommendation",
                                "coarse regions; Euclidean distance is not navigation connectivity",
                                "64 Hz and pause alignment require independent validation"]}
