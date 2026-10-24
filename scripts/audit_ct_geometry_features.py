"""Build separate geometric descriptors from frozen v7 snapshots and v9 context."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_geometry_service import geometry_sequence, GEOMETRY_VERSION, NODE_FEATURES, EDGE_FEATURES
from scripts.confirm_ct_generalization import load_records, sha, write


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--context-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    if a.output_dir.exists():
        p.error("Use a new output directory")
    import psutil
    if psutil.virtual_memory().available < 2 * 2**30:
        raise RuntimeError("RAM guard")
    started = time.monotonic()
    inventory = json.loads(a.inventory.read_text(encoding="utf-8"))
    context_report = json.loads((a.context_dir / "report.json").read_text(encoding="utf-8"))
    if sha(a.run_dir / "report.json") != inventory["run_report_sha256"] or sha(a.inventory) != context_report["inventory_sha256"]:
        raise ValueError("Frozen report or inventory changed")
    if sha(a.context_dir / "ground_navigation.jsonl") != context_report["sidecar_sha256"]:
        raise ValueError("Ground context changed")
    source = json.loads((a.run_dir / "report.json").read_text(encoding="utf-8"))
    records, receipts = load_records([ROOT / path for path in source["input_report_sha256"]])
    if receipts != {str(ROOT / path): value for path, value in source["input_report_sha256"].items()}:
        raise ValueError("Input receipts changed")
    raw = {}
    for path, expected in inventory["dataset_sha256"].items():
        f = ROOT / path
        if sha(f) != expected:
            raise ValueError("Frozen dataset changed")
        if path.endswith("_snapshots.json"):
            doc = json.loads(f.read_text(encoding="utf-8"))
            for row in doc["rounds"]:
                if row["side"] == "CT":
                    raw[f"{doc['source_demo_sha256']}:{row['round_number']}:CT"] = row["snapshots"]
    contexts = defaultdict(list)
    for line in (a.context_dir / "ground_navigation.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        contexts[row["id"]].append(row)
    arrays, by_map = [], defaultdict(Counter)
    for record in records:
        features = geometry_sequence(raw[record["id"]], contexts[record["id"]])
        if not np.isfinite(features["nodes"]).all() or not np.isfinite(features["edges"]).all():
            raise ValueError("Nonfinite descriptors")
        alive, nodes = features["node_mask"], features["nodes"]
        counts = by_map[record["map"]]
        counts.update({"live_observations": int(alive.sum()), "nav_projection_valid": int(nodes[..., 13].sum()),
                       "nav_patch_number_matches": int(nodes[..., 14].sum()), "ground_unknown": int(nodes[..., 4].sum()),
                       "airborne": int(nodes[..., 2].sum()), "nav_unknown": int(nodes[..., 10].sum()),
                       "nonzero_relative_height": int(((np.abs(nodes[..., 1]) > 1e-6) & alive).sum())})
        arrays.append(features)
    a.output_dir.mkdir(parents=True)
    np.savez_compressed(a.output_dir / "geometry.npz", **{k: np.stack([r[k] for r in arrays]) for k in arrays[0]})
    report = {"status": "implemented_and_audited_experimental_geometry_not_trained", "feature_version": GEOMETRY_VERSION,
              "rounds": len(records), "node_features": NODE_FEATURES, "edge_features": EDGE_FEATURES,
              "shape": {k: list(np.stack([r[k] for r in arrays]).shape) for k in arrays[0]},
              "by_map": {k: dict(v) for k, v in by_map.items()}, "context_report_sha256": sha(a.context_dir / "report.json"),
              "inventory_sha256": sha(a.inventory), "output_sha256": sha(a.output_dir / "geometry.npz"),
              "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__), ROOT / "app/services/ct_geometry_service.py")},
              "elapsed_seconds": time.monotonic() - started, "process_peak_RAM_MiB": psutil.Process().memory_info().peak_wset / 2**20,
              "limits": ["NAV residuals masked unless historical patch number matches; exact map compatibility still unverified.",
                         "Height and ground state are geometry, not tactical roles, line of sight or traversability.",
                         "No change to v7 common features, no new training or claimed performance gain.",
                         "No target-match-fitted scaling; 512/5000/32/64 are fixed descriptive scales."]}
    write(a.output_dir / "report.json", report)
    print(json.dumps({"rounds": report["rounds"], "shape": report["shape"], "elapsed_seconds": report["elapsed_seconds"]}))


if __name__ == "__main__":
    main()
