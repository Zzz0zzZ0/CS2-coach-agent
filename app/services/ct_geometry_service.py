"""Experimental height/ground descriptors; no tactical roles or walkability claims."""

import numpy as np

from app.services.ct_feature_service import feature_sequence

GEOMETRY_VERSION = "ct-height-ground-v0.1"
NODE_FEATURES = ("height_above_live_min_div512", "height_from_live_mean_div512",
                 "airborne", "grounded", "ground_unknown", "nav_inside_candidate",
                 "nav_snap_candidate", "nav_airborne", "nav_unlocalized", "nav_ray_blocked",
                 "nav_unknown", "nav_xy_residual_div32", "nav_z_residual_div64",
                 "nav_projection_valid", "nav_patch_number_matches")
EDGE_FEATURES = ("horizontal_distance_div5000", "absolute_height_difference_div512")


def geometry_sequence(snapshots, context_rows):
    base = feature_sequence(snapshots)
    contexts = {}
    for row in context_rows:
        key = (row["second"], str(row["steamid"]))
        if key in contexts:
            raise ValueError("Duplicate round context")
        contexts[key] = row
    nodes, edges, masks, pair_masks = [], [], [], []
    for frame, alive in zip(snapshots, base["alive"]):
        xyz = np.asarray([p["position"] for p in frame["players"]], dtype=float)
        z = xyz[:, 2]
        extra = np.zeros((5, len(NODE_FEATURES)), dtype=np.float32)
        extra[:, 0] = (z - z[alive].min()) / 512
        extra[:, 1] = (z - z[alive].mean()) / 512
        for k, player in enumerate(frame["players"]):
            if not alive[k]:
                continue
            row = contexts.get((frame["second"], str(player["steamid"])))
            if row is not None and not np.allclose(row["position"], xyz[k], atol=1e-6, rtol=0):
                raise ValueError("Context coordinate mismatch")
            airborne = row.get("is_airborne") if row else None
            if airborne is not None and type(airborne) is not bool:
                raise ValueError("Ground state must be boolean or unknown")
            extra[k, 2 + (0 if airborne is True else 1 if airborne is False else 2)] = 1
            version = row.get("versions", {}).get("2000883") if row else None
            status, hit = "unknown", None
            patch_match = bool(version and version.get("patch_number_matches") is True)
            extra[k, 14] = patch_match
            if airborne is True:
                status = "airborne"
            elif airborne is False and patch_match:
                raw_status = version["status"]
                hit = version.get("localization")
                if raw_status == "visual_ray_clear_candidate" and hit:
                    status = {"inside": "inside", "bounded_snap": "snap"}.get(hit["status"], "unknown")
                elif raw_status == "grounded_unlocalized":
                    status = "unlocalized"
                elif raw_status == "visual_ray_blocked":
                    status = "ray_blocked"
            extra[k, 5 + ("inside", "snap", "airborne", "unlocalized", "ray_blocked", "unknown").index(status)] = 1
            if status in ("inside", "snap"):
                residuals = np.asarray([hit["xy_residual"], hit["z_residual"]], dtype=float)
                if not np.isfinite(residuals).all() or (residuals < 0).any() or residuals[0] > 32 or residuals[1] > 64:
                    raise ValueError("Invalid bounded NAV residual")
                extra[k, 11:13] = residuals / [32, 64]
                extra[k, 13] = 1
        extra[~alive] = 0
        delta = xyz[:, None] - xyz[None, :]
        pair_mask = alive[:, None] & alive[None, :] & ~np.eye(5, dtype=bool)
        pair = np.stack([np.linalg.norm(delta[..., :2], axis=-1) / 5000,
                         np.abs(delta[..., 2]) / 512], -1) * pair_mask[..., None]
        nodes.append(extra)
        edges.append(pair.astype(np.float32))
        masks.append(alive)
        pair_masks.append(pair_mask)
    return {"nodes": np.stack(nodes), "edges": np.stack(edges),
            "node_mask": np.stack(masks), "pair_mask": np.stack(pair_masks)}
