"""Post-hoc explanation of stable context clusters; never select a weight or fit a model."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np
from sklearn.metrics import adjusted_rand_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.confirm_ct_generalization import sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    source = json.loads((args.pattern_dir / "report.json").read_text(encoding="utf-8"))
    if source["status"] != "completed":
        raise ValueError("Complete frozen contextual patterns required")
    models = [row for row in source["models"] if row["status"] == "fitted"]
    controls = {row["fold"]: row for row in models if row["variant"] == "context_only"}
    arrays = {}
    for row in models:
        path = args.pattern_dir / row["output_file"]
        if sha(path) != row["output_sha256"]:
            raise ValueError("Pattern output changed")
        with np.load(path, allow_pickle=False) as archive:
            arrays[row["output_file"]] = {key: archive[key] for key in archive.files}
    result = {"status": "completed", "scope": "post-hoc development cluster dominance diagnostic",
              "pattern_report_sha256": sha(args.pattern_dir / "report.json"), "script_sha256": sha(Path(__file__)),
              "definition": "Mean squared separation over all unordered source-centroid pairs, partitioned into concatenated coordinate blocks; normalized shares sum to one.",
              "limits": ["Shares describe the chosen normalized embedding and K, not causal importance or tactical responsibility.",
                         "Agreement with context-only clusters uses common accepted queries and requires at least two clusters on each side.",
                         "High seed stability can reflect resource groups; it does not establish useful deployment patterns."],
              "models": [], "summary": {}}
    grouped = defaultdict(list)
    for row in models:
        if "+context" not in row["variant"]:
            continue
        data = arrays[row["output_file"]]
        centers = data["centers"].astype(float)
        first, second = np.triu_indices(len(centers), 1)
        separation = ((centers[first] - centers[second]) ** 2).mean(0)
        width = centers.shape[1] - 37
        blocks = np.asarray([separation[:width].sum(), separation[width:width + 5].sum(),
                             separation[width + 5:width + 7].sum(), separation[width + 7:].sum()])
        if width not in (64, 120) or not np.isfinite(blocks).all() or blocks.sum() <= 0:
            raise ValueError("Unexpected fused coordinate blocks")
        shares = blocks / blocks.sum()
        np.testing.assert_allclose(shares.sum(), 1, atol=1e-12)
        reference = arrays[controls[row["fold"]]["output_file"]]
        np.testing.assert_array_equal(data["query_indices"], reference["query_indices"])
        common = data["query_assigned"] & reference["query_assigned"]
        ari = None
        if common.sum() >= 2 and len(set(data["query_labels"][common])) >= 2 and len(set(reference["query_labels"][common])) >= 2:
            ari = float(adjusted_rand_score(data["query_labels"][common], reference["query_labels"][common]))
        item = {"fold": row["fold"], "task": row["task"], "variant": row["variant"], "seed": row["seed"],
                "centroid_separation_shares": dict(zip(("state", "equipment", "score", "utility"), shares.tolist())),
                "common_accepted_queries": int(common.sum()), "ARI_with_context_only": ari}
        result["models"].append(item)
        grouped[(row["task"], row["variant"])].append(item)
    for (task, variant), rows in grouped.items():
        aris = [r["ARI_with_context_only"] for r in rows if r["ARI_with_context_only"] is not None]
        result["summary"].setdefault(task, {})[variant] = {
            "fits": len(rows), "mean_centroid_separation_shares": {name: float(np.mean([r["centroid_separation_shares"][name] for r in rows])) for name in ("state", "equipment", "score", "utility")},
            "computed_context_only_comparisons": len(aris), "mean_ARI_with_context_only": float(np.mean(aris)) if aris else None}
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "report.json", result)
    print(json.dumps({"audited_fused_fits": len(result["models"]), "status": result["status"]}))


if __name__ == "__main__":
    main()
