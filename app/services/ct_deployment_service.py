"""Experimental deployment inputs with unreviewed functional roles kept separate."""

import numpy as np

from app.services.ct_feature_service import REGIONS, feature_sequence
from app.services.ct_geometry_service import (
    EDGE_FEATURES as GEOMETRY_EDGES, NODE_FEATURES as GEOMETRY_NODES, geometry_sequence,
)

DEPLOYMENT_VERSION = "ct-deployment-input-v0.1"
NODE_FEATURES = (*[f"coarse_{name}" for name in REGIONS], "health_div100",
                 "equipment_log1p_div_log10001", "alive", *GEOMETRY_NODES[:5])
EDGE_FEATURES = ("euclidean_distance_div5000", *GEOMETRY_EDGES)
FUNCTIONAL_ROLES = ("site_a", "site_b", "a_approach", "b_approach", "connector",
                    "ct_spawn", "t_spawn", "other_known", "unknown")


def deployment_sequence(snapshots, context_rows):
    base = feature_sequence(snapshots)
    context_rows = list(context_rows)
    expected = {(frame["second"], str(p["steamid"])) for frame in snapshots for p in frame["players"]}
    if any((row["second"], str(row["steamid"])) not in expected for row in context_rows):
        raise ValueError("Context outside the supplied deployment window")
    geometry = geometry_sequence(snapshots, context_rows)
    alive, pairs = geometry["node_mask"], geometry["pair_mask"]
    nodes = np.concatenate([base["nodes"], geometry["nodes"][..., :5]], -1)
    nodes *= alive[..., None]
    edges = np.concatenate([base["edges"][..., None], geometry["edges"]], -1)
    edges *= pairs[..., None]
    ground_known = alive & (geometry["nodes"][..., 4] == 0)
    feature_mask = np.broadcast_to(alive[..., None], nodes.shape).copy()
    feature_mask[..., 10:12] &= ground_known[..., None]
    # shortcut: no functional mapping is accepted yet; bind reviewed mappings in a new schema version.
    roles = np.zeros((*alive.shape, len(FUNCTIONAL_ROLES)), dtype=np.float32)
    roles[..., -1] = alive
    return {
        "nodes": nodes.astype(np.float32), "edges": edges.astype(np.float32),
        "node_mask": alive, "node_feature_mask": feature_mask, "pair_mask": pairs,
        "ground_known": ground_known, "functional_roles": roles,
        "functional_role_known": np.zeros_like(alive),
        "raw_places": np.asarray([[p["place"] for p in frame["players"]] for frame in snapshots]),
        "nav_diagnostic_valid": geometry["nodes"][..., 13].astype(bool),
    }
