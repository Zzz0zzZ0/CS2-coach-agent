"""Offline structural retrieval diagnostics; distances are not tactical relevance labels."""

import numpy as np


def nearest_candidates(queries, library, k=5):
    queries, library = np.asarray(queries, dtype=float), np.asarray(library, dtype=float)
    if queries.ndim != 2 or library.ndim != 2 or queries.shape[1] != library.shape[1] or not len(library):
        raise ValueError("Matching query/library feature widths and a nonempty library required")
    if not np.isfinite(queries).all() or not np.isfinite(library).all() or not isinstance(k, int) or k < 1:
        raise ValueError("Finite vectors and positive integer k required")
    distances = np.mean((queries[:, None] - library[None]) ** 2, axis=-1)
    return np.argsort(distances, axis=1, kind="stable")[:, :k], distances


def nearest_common_candidates(queries, library, query_mask, library_mask, k=5):
    queries, library, query_mask, library_mask = (np.asarray(x, dtype=float) for x in (queries, library, query_mask, library_mask))
    if queries.ndim != 2 or library.ndim != 2 or queries.shape[1] != 40 or library.shape[1] != 40 or not len(library):
        raise ValueError("Nonempty forty-feature common-state library required")
    if queries.shape != query_mask.shape or library.shape != library_mask.shape:
        raise ValueError("Matching observation validity masks required")
    if not all(np.isfinite(x).all() for x in (queries, library, query_mask, library_mask)):
        raise ValueError("Finite common states and masks required")
    if not np.isin(query_mask, [0, 1]).all() or not np.isin(library_mask, [0, 1]).all() or not isinstance(k, int) or k < 1:
        raise ValueError("Binary validity masks and positive integer k required")
    shared = query_mask[:, None] * library_mask[None]
    denominator = shared.sum(-1)
    if (denominator == 0).any():
        raise ValueError("Every query-candidate pair needs shared valid observations")
    distance = (((queries[:, None] - library[None]) ** 2) * shared).sum(-1) / denominator
    return np.argsort(distance, axis=1, kind="stable")[:, :k], distance


def geometry_signature(features):
    alive, edges = features["alive"], features["edges"]
    eligible = np.asarray(alive).all((1, 2))
    first, second = np.triu_indices(5, 1)
    # Equal live counts avoid treating nonexistent pairs as zero distance.
    signatures = np.sort(edges[eligible][:, :, first, second], axis=-1).reshape(int(eligible.sum()), 50)
    return eligible, signatures


def geometry_diagnostic(ranking, geometry_distances, ideal):
    if ranking.shape != ideal.shape or len(ranking) != len(geometry_distances):
        raise ValueError("Matching query rankings required")
    selected = np.take_along_axis(geometry_distances, ranking, axis=1)
    reference = np.take_along_axis(geometry_distances, ideal, axis=1)
    return {"query_count": len(ranking), "top5_geometry_mse": float(selected.mean()),
            "ideal_top5_geometry_mse": float(reference.mean()),
            "top5_geometry_neighbor_overlap": float(np.mean([len(set(a) & set(b)) / len(a) for a, b in zip(ranking, ideal)])),
            "claim": "label-free Euclidean geometry diagnostic, not tactical Recall or nDCG"}
