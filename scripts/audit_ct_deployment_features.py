"""Export aligned deployment inputs; unreviewed functional semantics remain unknown."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_deployment_service import (
    DEPLOYMENT_VERSION, EDGE_FEATURES, FUNCTIONAL_ROLES, NODE_FEATURES, deployment_sequence,
)
from scripts.confirm_ct_generalization import load_records, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--context-dir", type=Path, required=True)
    parser.add_argument("--role-review", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).items():
        resolved = value.resolve()
        if not resolved.is_relative_to(ROOT):
            parser.error("Keep source and export paths inside this workspace")
        setattr(args, name, resolved)
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    import psutil
    if psutil.virtual_memory().available < 2 * 2**30:
        raise RuntimeError("Available RAM below 2 GiB")
    started = time.monotonic()
    source = json.loads((args.run_dir / "report.json").read_text(encoding="utf-8"))
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    context_report = json.loads((args.context_dir / "report.json").read_text(encoding="utf-8"))
    review = json.loads(args.role_review.read_text(encoding="utf-8"))
    if sha(args.run_dir / "report.json") != inventory["run_report_sha256"] or sha(args.inventory) != context_report["inventory_sha256"]:
        raise ValueError("Frozen cohort/inventory changed")
    if sha(args.context_dir / "report.json") != review["context_report_sha256"]:
        raise ValueError("Role queue refers to different context")
    sidecar = args.context_dir / "ground_navigation.jsonl"
    if sha(sidecar) != context_report["sidecar_sha256"]:
        raise ValueError("Ground context changed")
    if tuple(review["roles"]) != FUNCTIONAL_ROLES or any(row["review_status"] != "unreviewed" or row["approved_roles"] is not None for row in review["items"]):
        raise ValueError("New semantic review requires an explicitly versioned mapping")
    records, receipts = load_records([ROOT / p for p in source["input_report_sha256"]])
    if receipts != {str(ROOT / p): digest for p, digest in source["input_report_sha256"].items()}:
        raise ValueError("Frozen dataset report changed")
    index = [{k: v for k, v in record.items() if k != "features"} for record in records]
    if index != json.loads((args.run_dir / "sample_index.json").read_text(encoding="utf-8")):
        raise ValueError("Window order or metadata changed")
    raw = {}
    for name, expected in inventory["dataset_sha256"].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f"Frozen raw input changed: {name}")
        if name.endswith("_snapshots.json"):
            doc = json.loads((ROOT / name).read_text(encoding="utf-8"))
            for row in doc["rounds"]:
                if row["side"] == "CT":
                    identity = f"{doc['source_demo_sha256']}:{row['round_number']}:CT"
                    if identity in raw:
                        raise ValueError("Duplicate raw CT window")
                    raw[identity] = row["snapshots"]
    contexts = defaultdict(list)
    for line in sidecar.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        contexts[row["id"]].append(row)
    arrays, maps, places = [], defaultdict(Counter), defaultdict(Counter)
    for record in records:
        frames, context = raw[record["id"]], contexts[record["id"]]
        if any(row["map"] != record["map"] for row in context):
            raise ValueError("Context belongs to another map")
        result = deployment_sequence(frames, context)
        alive, pair = result["node_mask"], result["pair_mask"]
        if not np.isfinite(result["nodes"]).all() or not np.isfinite(result["edges"]).all():
            raise ValueError("Nonfinite model input")
        name = record["map"]
        places[name].update(result["raw_places"][alive].tolist())
        maps[name].update({"rounds": 1, "live_observations": int(alive.sum()),
            "coarse_other": int(result["nodes"][..., 4].sum()),
            "airborne": int(result["nodes"][..., 10].sum()),
            "grounded": int(result["nodes"][..., 11].sum()),
            "ground_unknown": int(result["nodes"][..., 12].sum()),
            "functional_role_unknown": int((alive & ~result["functional_role_known"]).sum()),
            "nav_diagnostic_valid": int(result["nav_diagnostic_valid"].sum()),
            "live_unordered_pairs": int(np.triu(pair, 1).sum()),
            "close_xy_large_height_pairs": int((np.triu(pair, 1) & (result["edges"][..., 1] * 5000 <= 200)
                                                  & (result["edges"][..., 2] * 512 >= 160)).sum())})
        arrays.append(result)
    queued = {(row["map"], row["place"]) for row in review["items"]}
    observed = {(name, place) for name, counts in places.items() for place in counts}
    if len(queued) != len(review["items"]) or queued != observed:
        raise ValueError("Semantic queue and observed places differ")
    for name, counts in maps.items():
        original = inventory["maps"][name]
        if counts["live_observations"] != original["live_player_snapshots"] or counts["coarse_other"] != original["baseline_other_count"]:
            raise ValueError("Inventory denominator or coarse mapping differs")
    args.output_dir.mkdir(parents=True)
    np.savez_compressed(args.output_dir / "features.npz", **{k: np.stack([row[k] for row in arrays]) for k in arrays[0]})
    write(args.output_dir / "sample_index.json", index)
    for name, expected in inventory["dataset_sha256"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("Input changed during export")
    report = {"status": "geometry_input_exported_functional_semantics_unreviewed", "feature_version": DEPLOYMENT_VERSION,
        "rounds": len(records), "series": len({r["series"] for r in records}), "node_features": NODE_FEATURES,
        "edge_features": EDGE_FEATURES, "functional_role_metadata": FUNCTIONAL_ROLES,
        "model_input_keys": ["nodes", "edges", "node_mask", "node_feature_mask", "pair_mask", "ground_known"],
        "excluded_from_model": ["raw_places", "functional_roles", "functional_role_known", "nav_diagnostic_valid"],
        "shape": {k: list(np.stack([r[k] for r in arrays]).shape) for k in arrays[0]},
        "by_map": {name: {**dict(counts), "coarse_other_fraction": counts["coarse_other"] / counts["live_observations"],
                           "place_counts": dict(sorted(places[name].items()))} for name, counts in sorted(maps.items())},
        "semantic_queue_items": len(queued), "semantic_reviewed_items": 0,
        "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in [args.inventory, args.role_review, sidecar,
            args.context_dir / "report.json", args.run_dir / "report.json", args.run_dir / "sample_index.json",
            ROOT / "app/services/ct_feature_service.py", ROOT / "app/services/ct_geometry_service.py",
            ROOT / "app/services/ct_deployment_service.py", Path(__file__)]},
        "raw_input_sha256": inventory["dataset_sha256"],
        "output_sha256": {p.name: sha(p) for p in args.output_dir.iterdir() if p.is_file()},
        "elapsed_seconds": time.monotonic() - started,
        "process_peak_RAM_MiB": psutil.Process().memory_info().peak_wset / 2**20,
        "limits": ["No new training, no tactical-role acceptance or efficacy result.",
                   "Original coarse categories remain separate from the unreviewed nine-role vocabulary.",
                   "NAV projection validity is diagnostic only and is excluded from model input.",
                   "Only current-frame observations; fixed scales; no map/team identity or outcome input.",
                   "All existing series are development data; expert semantics and independent evaluation remain pending."],
        "human_verification": {"status": "pending", "verified_by": None}}
    write(args.output_dir / "report.json", report)
    print(json.dumps({"rounds": report["rounds"], "semantic_queue_items": len(queued),
                      "elapsed_seconds": report["elapsed_seconds"], "shape": report["shape"]}))


if __name__ == "__main__":
    main()
