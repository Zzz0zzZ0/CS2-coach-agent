"""Observed deployment state; a map location does not determine tactical duty."""

import numpy as np

from app.services.ct_feature_service import REGIONS, feature_sequence
from app.services.ct_geometry_service import (
    EDGE_FEATURES as GEOMETRY_EDGES, NODE_FEATURES as GEOMETRY_NODES, geometry_sequence,
)

DEPLOYMENT_VERSION = "ct-deployment-input-v0.3"
MOTION_SCALE = 250.0  # Fixed game units per second, not a speed limit.
NODE_FEATURES = (*[f"coarse_{name}" for name in REGIONS], "health_div100",
                 "equipment_log1p_div_log10001", "alive", *GEOMETRY_NODES[:5],
                 "horizontal_displacement_rate_div250", "vertical_displacement_rate_div250")
EDGE_FEATURES = ("euclidean_distance_div5000", *GEOMETRY_EDGES)


def deployment_sequence(snapshots, context_rows):
    base = feature_sequence(snapshots)
    context_rows = list(context_rows)
    expected = {(frame["second"], str(p["steamid"])) for frame in snapshots for p in frame["players"]}
    if any((row["second"], str(row["steamid"])) not in expected for row in context_rows):
        raise ValueError("Context outside the supplied deployment window")
    geometry = geometry_sequence(snapshots, context_rows)
    alive, pairs = geometry["node_mask"], geometry["pair_mask"]
    motion = np.zeros((*alive.shape, 2), dtype=np.float32)
    motion_known = np.zeros_like(alive)
    previous = {}
    previous_second = None
    for t, frame in enumerate(snapshots):
        for i, player in enumerate(frame["players"]):
            prior = previous.get(str(player["steamid"]))
            if alive[t, i] and prior is not None and prior["health"] > 0:
                delta = (np.asarray(player["position"], dtype=float) - prior["position"]) / (
                    (frame["second"] - previous_second) * MOTION_SCALE)
                # shortcut: sampled endpoints omit intervening paths; use dense traces for route claims.
                motion[t, i] = np.linalg.norm(delta[:2]), delta[2]
                motion_known[t, i] = True
        previous = {str(p["steamid"]): p for p in frame["players"]}
        previous_second = frame["second"]
    nodes = np.concatenate([base["nodes"], geometry["nodes"][..., :5], motion], -1)
    nodes *= alive[..., None]
    edges = np.concatenate([base["edges"][..., None], geometry["edges"]], -1)
    edges *= pairs[..., None]
    ground_known = alive & (geometry["nodes"][..., 4] == 0)
    feature_mask = np.broadcast_to(alive[..., None], nodes.shape).copy()
    feature_mask[..., 10:12] &= ground_known[..., None]
    feature_mask[..., 13:] &= motion_known[..., None]
    return {
        "nodes": nodes.astype(np.float32), "edges": edges.astype(np.float32),
        "node_mask": alive, "node_feature_mask": feature_mask, "pair_mask": pairs,
        "ground_known": ground_known,
        "raw_places": np.asarray([[p["place"] for p in frame["players"]] for frame in snapshots]),
        "nav_diagnostic_valid": geometry["nodes"][..., 13].astype(bool),
    }
