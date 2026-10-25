"""Explicit CT context for offline retrieval, without tactical-role labels or refitting encoders."""

import numpy as np

CONTEXT_VERSION = "ct-context-observation-v0.1"
WEAPONS = ("smokegrenade", "incgrenade", "molotov", "flashbang", "hegrenade", "decoy")
GROUPS = ("equipment", "score", "utility")


def observed_number(value, integer=False):
    if value is None:
        return np.nan
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or value < 0:
        raise ValueError("Observed context values must be finite nonnegative numbers or unknown")
    if integer and value != int(value):
        raise ValueError("Score and throw counts must be integers")
    return float(value)


def context_groups(records):
    equipment, scores, utility = [], [], []
    if len({row["id"] for row in records}) != len(records):
        raise ValueError("Duplicate context window")
    for row in records:
        snapshots = row["snapshots"]
        if [s["second"] for s in snapshots] != [10, 12, 15, 18, 20]:
            raise ValueError("The five frozen observation times are required")
        score = row["score_before"]
        scores.append([observed_number(score[side], True) if score is not None else np.nan for side in ("CT", "T")])
        equipment.append([np.log1p(observed_number(s["equipment_total"]["CT"])) for s in snapshots])
        counts = []
        for snapshot in snapshots:
            if snapshot["tick"] < row["freeze_end_tick"]:
                raise ValueError("Context query before freeze end")
            observed = snapshot["utility"]
            if set(observed["recorded_ct_throws"]) - set(WEAPONS):
                raise ValueError("Unreviewed grenade token")
            complete = observed_number(observed["unattributed_recorded_throws"], True) == 0
            counts.extend([np.log1p(observed_number(observed["recorded_ct_throws"].get(weapon, 0), True))
                           if complete else np.nan for weapon in WEAPONS])
        utility.append(counts)
    return {"equipment": np.asarray(equipment, dtype=float).reshape(-1, 5),
            "score": np.asarray(scores, dtype=float).reshape(-1, 2),
            "utility": np.asarray(utility, dtype=float).reshape(-1, 30)}


def normalize_source(source, queries):
    """Scale mean squared distance by the source-only mean off-diagonal pair distance."""
    source, queries = np.asarray(source, dtype=float), np.asarray(queries, dtype=float)
    if (source.ndim != 2 or queries.ndim != 2 or source.shape[1] != queries.shape[1]
            or len(source) < 2 or not source.shape[1] or not np.isfinite(source).all()
            or np.isinf(queries).any()):
        raise ValueError("Two finite source vectors and matching query widths required")
    mean = source.mean(0)
    scale = float(2 * len(source) / (len(source) - 1) * source.var(0).mean())
    constant = scale <= 1e-12
    scale = 1.0 if constant else scale
    denominator = np.sqrt(source.shape[1] * scale)
    return (source - mean) / denominator, (queries - mean) / denominator, {"scale": scale, "constant_source": constant}


def context_embedding(source, queries, groups=GROUPS):
    if not groups or len(set(groups)) != len(groups) or set(groups) - set(GROUPS):
        raise ValueError("Distinct known context groups required")
    if any(len(source[name]) != len(source[groups[0]]) or len(queries[name]) != len(queries[groups[0]]) for name in groups):
        raise ValueError("Context group row counts differ")
    supported = np.ones(len(queries[groups[0]]), dtype=bool)
    if any(not np.isfinite(source[name]).all() for name in groups):
        return {"source_supported": False, "query_supported": np.zeros_like(supported),
                "source": None, "queries": None, "scales": {}}
    source_vectors, query_vectors, scales = [], [], {}
    for name in groups:
        s, q, scales[name] = normalize_source(source[name], queries[name])
        supported &= np.isfinite(q).all(1)
        source_vectors.append(s / np.sqrt(len(groups)))
        query_vectors.append(q / np.sqrt(len(groups)))
    return {"source_supported": True, "query_supported": supported,
            "source": np.concatenate(source_vectors, 1), "queries": np.concatenate(query_vectors, 1), "scales": scales}


def squared_distance(queries, source):
    queries, source = np.asarray(queries, dtype=float), np.asarray(source, dtype=float)
    if (queries.ndim != 2 or source.ndim != 2 or queries.shape[1] != source.shape[1]
            or not np.isfinite(queries).all() or not np.isfinite(source).all()):
        raise ValueError("Finite matching vectors required")
    return ((queries * queries).sum(1)[:, None] + (source * source).sum(1)[None]
            - 2 * queries @ source.T).clip(0)


def fused_embedding(source, queries, context, weight):
    if not 0 <= weight <= 1 or not context["source_supported"]:
        raise ValueError("Supported source context and a weight in [0,1] required")
    s, q, scale = normalize_source(source, queries)
    return (np.concatenate([np.sqrt(1 - weight) * s, np.sqrt(weight) * context["source"]], 1),
            np.concatenate([np.sqrt(1 - weight) * q, np.sqrt(weight) * context["queries"]], 1), scale)
