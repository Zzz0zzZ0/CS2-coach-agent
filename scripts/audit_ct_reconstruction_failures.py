"""Decompose the completed development matrix; never train or choose a new model."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.confirm_ct_generalization import sha, write
from scripts.evaluate_ct_reconstruction import equal_series


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    public = ROOT / "datasets/evaluation/ct_reconstruction_development_report.json"
    matrix = ROOT / "output/tagnet/ct_reconstruction_matrix"
    protocol = ROOT / "datasets/selections/ct_reconstruction_matrix.json"
    evidence = json.loads(public.read_text(encoding="utf-8"))
    config = json.loads(protocol.read_text(encoding="utf-8"))
    trained = json.loads((matrix / "report.json").read_text(encoding="utf-8"))
    if (evidence["status"] != "completed" or sha(matrix / "report.json") != evidence["matrix_report_sha256"]
            or sha(protocol) != evidence["protocol_sha256"]):
        raise ValueError("Frozen completed matrix required")
    for name, digest in config["input_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ValueError(f"Frozen input changed: {name}")
    input_dir = ROOT / "output/tagnet/ct_deployment_inputs_p1_v03"
    index = json.loads((input_dir / "sample_index.json").read_text(encoding="utf-8"))
    series, maps = (np.asarray([row[key] for row in index]) for key in ("series", "map"))
    seeds, groups = config["training"]["seeds"], trained["loss_groups"]
    values, receipts = {}, {}
    for entry in trained["models"]:
        task, method, seed = entry["fold"].split("__")[0], entry["condition"], entry["seed"]
        path = matrix / entry["fold"] / f"{method}_{seed}_evaluation.npz"
        relative = str(path.relative_to(ROOT))
        if sha(path) != evidence["input_artifact_sha256"][relative]:
            raise ValueError(f"Evaluation changed: {relative}")
        receipts[relative] = sha(path)
        with np.load(path, allow_pickle=False) as archive:
            indices, components = archive["test_indices"], archive["components"].astype(float)
            np.testing.assert_allclose(components.mean(-1), archive["loss"], rtol=1e-5, atol=1e-7)
        destination = values.setdefault((task, method, seed), np.full((len(index), 7), np.nan))
        if np.isfinite(destination[indices]).any():
            raise ValueError("Duplicate query assignment")
        destination[indices] = components
    result = {"status": "completed", "scope": "post-hoc descriptive development failure decomposition",
              "source_sha256": {str(public.relative_to(ROOT)): sha(public),
                                str(protocol.relative_to(ROOT)): sha(protocol),
                                str((input_dir / "sample_index.json").relative_to(ROOT)): sha(input_dir / "sample_index.json")},
              "script_sha256": sha(Path(__file__)), "evaluation_sha256": receipts,
              "loss_groups": groups, "tasks": {},
              "interpretation": ["Positive contribution means lower loss for graph_gru; seven contributions sum to the total loss reduction.",
                                 "Contributions use fixed training-loss scales; magnitudes across CE/MSE groups are not comparable physical error rates.",
                                 "Loss matching can choose different global player permutations for different models.",
                                 "No causal attribution to an input field, tactical judgment, new training, or independent test is performed."]}
    for task, reference in evidence["tasks"].items():
        averaged = {method: np.stack([values[(task, method, seed)] for seed in seeds]).mean(0)
                    for method in config["conditions"]}
        if not all(np.isfinite(x).all() for x in averaged.values()):
            raise ValueError("Incomplete coverage")
        result["tasks"][task] = {}
        for map_name in ["all", *sorted(set(maps))]:
            keep = np.ones(len(index), dtype=bool) if map_name == "all" else maps == map_name
            means = {method: equal_series(x[keep], series[keep]) for method, x in averaged.items()}
            row = {"windows": int(keep.sum()), "series": len(set(series[keep])), "methods": {}, "contrasts": {}}
            for method, components in means.items():
                expected = reference["methods"][method] if map_name == "all" else reference["methods"][method]["by_map"][map_name]
                np.testing.assert_allclose(components.mean(), expected["loss_equal_series"], rtol=1e-5)
                row["methods"][method] = dict(zip(groups, components.tolist()))
            for baseline in ("mlp_gru", "graph_static", "graph_gru_no_motion", "graph_gru_common"):
                contributions = (means[baseline] - means["graph_gru"]) / 7
                reduction = float(means[baseline].mean() - means["graph_gru"].mean())
                np.testing.assert_allclose(contributions.sum(), reduction, atol=1e-12)
                row["contrasts"][baseline] = {"loss_reduction": reduction,
                    "relative_reduction_percent": 100 * reduction / float(means[baseline].mean()),
                    "component_contributions": dict(zip(groups, contributions.tolist()))}
            result["tasks"][task][map_name] = row
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "report.json", result)
    print(json.dumps({"status": result["status"], "verified_evaluations": len(receipts),
                      "Nuke_G4": result["tasks"]["G4"]["de_nuke"]["contrasts"]}))


if __name__ == "__main__":
    main()
