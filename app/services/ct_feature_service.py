"""Map-independent CT observations; Euclidean geometry is not navigation connectivity."""

import math

import numpy as np

FEATURE_VERSION = "ct-common-v0.1"
REGIONS = ("BombsiteA", "BombsiteB", "CTSpawn", "TSpawn", "other")
DISTANCE_SCALE = 5000.0  # Fixed game units; never estimated from a held-out map.


def feature_sequence(snapshots: list[dict]) -> dict[str, np.ndarray]:
    if [s["second"] for s in snapshots] != [10, 12, 15, 18, 20]:
        raise ValueError("Five ordered opening snapshots are required")
    nodes, edges, alive_masks, targets, masks = [], [], [], [], []
    identities = None
    for snapshot in snapshots:
        players = snapshot["players"]
        ids = {str(p["steamid"]) for p in players}
        if len(players) != 5 or len(ids) != 5 or (identities is not None and ids != identities):
            raise ValueError("Five distinct, consistent CT identities are required")
        identities = ids
        xyz = np.array([p["position"] for p in players], dtype=np.float32)
        health = np.array([p["health"] for p in players], dtype=np.float32)
        equipment = np.array([p["equipment_value"] for p in players], dtype=np.float32)
        if xyz.shape != (5, 3) or not all(np.isfinite(x).all() for x in (xyz, health, equipment)):
            raise ValueError("Non-finite or malformed player state")
        if ((health < 0) | (health > 100)).any() or (equipment < 0).any():
            raise ValueError("Invalid health or equipment")
        alive = health > 0
        if not alive.any():
            raise ValueError("No live CT players at snapshot")
        roles = np.zeros((5, 5), dtype=np.float32)
        for i, player in enumerate(players):
            place = player.get("place")
            if not isinstance(place, str) or not place.strip():
                raise ValueError("Missing named place")
            roles[i, REGIONS.index(place) if place in REGIONS else 4] = 1
        distance = np.linalg.norm(xyz[:, None] - xyz[None, :], axis=-1) / DISTANCE_SCALE
        live_pairs = distance[np.triu(alive[:, None] & alive[None, :], 1)]
        occupancy = np.concatenate([(roles * alive[:, None]).sum(0) / 5, [(~alive).sum() / 5]])
        pair_valid = len(live_pairs) > 0
        statistics = [float(live_pairs.mean()), float(live_pairs.max())] if pair_valid else [0, 0]
        nodes.append(np.column_stack([roles, health / 100, np.log1p(equipment) / math.log1p(10000), alive]))
        edges.append(distance)
        alive_masks.append(alive)
        targets.append(np.concatenate([occupancy, statistics]))
        masks.append([1] * 6 + [int(pair_valid)] * 2)
    return {"nodes": np.asarray(nodes, dtype=np.float32), "edges": np.asarray(edges, dtype=np.float32),
            "alive": np.asarray(alive_masks), "targets": np.asarray(targets, dtype=np.float32),
            "target_mask": np.asarray(masks, dtype=np.float32)}
