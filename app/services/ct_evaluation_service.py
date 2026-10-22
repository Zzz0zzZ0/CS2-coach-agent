"""Masked state error and paired, equal-series uncertainty summaries."""

import numpy as np


def error_totals(prediction, truth, mask):
    prediction, truth, mask = (np.asarray(x, dtype=float) for x in (prediction, truth, mask))
    if prediction.shape != truth.shape or mask.shape != truth.shape or truth.shape[-1] != 8:
        raise ValueError("Matching eight-feature predictions, targets and masks required")
    if not all(np.isfinite(x).all() for x in (prediction, truth, mask)) or not np.isin(mask, [0, 1]).all():
        raise ValueError("Finite arrays and binary masks required")
    errors = (prediction - truth) ** 2 * mask
    return {"sse": float(errors.sum()), "count": int(mask.sum()),
            "occupancy_sse": float(errors[..., :6].sum()), "occupancy_count": int(mask[..., :6].sum()),
            "distance_sse": float(errors[..., 6:].sum()), "distance_count": int(mask[..., 6:].sum())}


def summarize(totals):
    if not totals:
        return None
    result = {key: sum(row[key] for row in totals) for key in totals[0]}
    for label, prefix in (("mse", ""), ("occupancy_mse", "occupancy_"), ("distance_mse", "distance_")):
        denominator = result[prefix + "count"]
        result[label] = result[prefix + "sse"] / denominator if denominator else None
    return result


def paired_series_bootstrap(model, baseline, series):
    if not (len(model) == len(baseline) == len(series)) or not series:
        raise ValueError("Paired nonempty round totals and series labels required")
    scores = []
    for name in sorted(set(series)):
        selected = [i for i, value in enumerate(series) if value == name]
        a, b = (summarize([rows[i] for i in selected]) for rows in (model, baseline))
        if a["count"] != b["count"] or not a["count"]:
            raise ValueError("Paired valid target counts required")
        scores.append([a["mse"], b["mse"]])
    values = np.asarray(scores)
    result = {"series_count": len(values), "weighting": "equal series, never independent rounds",
              "improvement_pct": float(100 * (1 - values[:, 0].mean() / values[:, 1].mean())) if values[:, 1].mean() else None,
              "descriptive_95pct_interval": None, "resamples": 2000, "seed": 20261023}
    if len(values) > 1 and values[:, 1].min() > 0:
        indices = np.random.default_rng(20261023).integers(0, len(values), (2000, len(values)))
        resampled = values[indices].mean(1)
        interval = np.percentile(100 * (1 - resampled[:, 0] / resampled[:, 1]), [2.5, 97.5])
        result["descriptive_95pct_interval"] = interval.tolist()
    return result
