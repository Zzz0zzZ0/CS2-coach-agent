"""Read saved out-of-fold forecasts; expose horizon/component failures without refitting."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.confirm_ct_generalization import load_records, sha, write
from app.services.ct_evaluation_service import error_totals, paired_series_bootstrap, summarize

FEATURES = ("A_live", "B_live", "CT_spawn_live", "T_spawn_live", "other_live", "dead", "mean_distance", "max_distance")
METHODS = ("persistence", "velocity", "ridge", "prefix_ridge", "static_seed_mean", "gru_seed_mean")


def breakdown(errors, mask):
    if not len(errors):
        return None
    def mse(e, m):
        return float(e.sum() / m.sum()) if m.sum() else None
    return {"rounds": len(errors), "mse": mse(errors, mask),
            "occupancy_mse": mse(errors[..., :6], mask[..., :6]),
            "distance_mse": mse(errors[..., 6:], mask[..., 6:]),
            "by_horizon": {f"{a}_to_{b}": mse(errors[:, k], mask[:, k]) for k, (a, b) in
                           enumerate(zip((10, 12, 15, 18), (12, 15, 18, 20)))},
            "by_feature": {name: mse(errors[..., k], mask[..., k]) for k, name in enumerate(FEATURES)}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--acquisition-protocol", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        p.error("Do not overwrite an existing receipt")
    report = json.loads((a.run_dir / "report.json").read_text(encoding="utf-8"))
    if report["status"] != "completed_grouped_generalization_matrix":
        p.error("A completed real-data matrix is required")
    folders = [ROOT / path for path in report["input_report_sha256"]]
    records, receipts = load_records(folders)
    expected = {str(ROOT / path): digest for path, digest in report["input_report_sha256"].items()}
    assert receipts == expected, "Inputs changed after evaluation"
    index = json.loads((a.run_dir / "sample_index.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in records] == [r["id"] for r in index]
    folds = json.loads((a.run_dir / "folds.json").read_text(encoding="utf-8"))
    seeds = report["training"]["seeds"]
    result = {"status": "completed_forecast_error_audit", "run_report_sha256": sha(a.run_dir / "report.json"),
              "script_sha256": sha(Path(__file__)), "tasks": {}, "physical_constraint_violations": 0,
              "rounds": len(records), "region_coverage": {},
              "dataset_artifact_sha256": {str(path): sha(path) for folder in folders for path in
                  [folder / "sample_index.json", *sorted(folder.glob("*_snapshots.json")), *sorted(folder.glob("*_timing.json"))]},
              "scope": "same fixed out-of-fold predictions; no fitting, selection or human tactical labels",
              "limitations": ["pooled component/horizon MSE for diagnosis, equal-series comparisons in main report",
                              "few series; G2/G3/G4 are different protocols, not a paired model ranking across tasks",
                              "G5 same target test subset must be used for before/after comparisons"]}
    acquisition = json.loads(a.acquisition_protocol.read_text(encoding="utf-8"))
    result["acquisition_protocol_sha256"] = sha(a.acquisition_protocol)
    new_series = {m["match_id"] for m in acquisition["matches"]}
    result["frozen_source_models"] = {"scope": "original source-only frozen models; raw forecasts preserve earlier scoring, not retrained-CV projection",
                                      "inputs": {}, "new_series": {}, "cumulative": {}}
    frozen_scores, frozen_series = {}, []
    for folder in folders:
        previous = json.loads((folder / "report.json").read_text(encoding="utf-8"))
        result["frozen_source_models"]["inputs"][str(folder)] = {"report_sha256": sha(folder / "report.json"),
            "raw_demos": previous["acquisition"], "quality": {k: v for k, v in previous["groups"].items() if "series" in v}}
        with np.load(folder / "predictions.npz") as forecasts:
            for group, metadata in previous["groups"].items():
                if group in ("source_train", "dust2_test"):
                    continue
                rows = [r for r in records if r["series"] == metadata["series"] and r["map"] == metadata["map"]]
                # Preserve the original evaluator's round ordering.
                order = json.loads((folder / "sample_index.json").read_text(encoding="utf-8"))[group]
                by_id = {r["id"]: r for r in rows}; rows = [by_id[r["id"]] for r in order]
                frozen_series.extend([metadata["series"]] * len(rows))
                for method in previous["metrics"][group]:
                    predictions = forecasts[f"{group}__{method}"]
                    totals = [error_totals(pred, r["features"]["targets"][1:], r["features"]["target_mask"][1:])
                              for pred, r in zip(predictions, rows)]
                    assert len(predictions) == len(rows)
                    assert np.isclose(summarize(totals)["mse"], previous["metrics"][group][method]["all"]["mse"], rtol=1e-7)
                    frozen_scores.setdefault(method, []).extend(totals)
    for scope in ("new_series", "cumulative"):
        keep = [i for i, s in enumerate(frozen_series) if scope == "cumulative" or s in new_series]
        labels = [frozen_series[i] for i in keep]
        baseline = [frozen_scores["persistence"][i] for i in keep]
        for method, totals in frozen_scores.items():
            chosen = [totals[i] for i in keep]
            result["frozen_source_models"][scope][method] = {"rounds": len(keep), "all": summarize(chosen),
                "vs_persistence": paired_series_bootstrap(chosen, baseline, labels)}
    for map_name in report["maps"]:
        rows = [r for r in records if r["map"] == map_name]
        result["region_coverage"][map_name] = {"rounds": len(rows), "series": len({r["series"] for r in rows}),
            "other_live_fraction_mean": float(np.mean([r["features"]["targets"][:, 4].mean() for r in rows]))}
    for task in ("G2", "G3", "G4", "G5"):
        selected = [f for f in folds if f["task"] == task]
        if not selected:
            continue
        ids, masks, errors = [], [], {m: [] for m in METHODS}
        for f in selected:
            with np.load(a.run_dir / f["name"] / "predictions.npz") as data:
                np.testing.assert_array_equal(data["test_indices"], f["test"])
                true, mask = data["truth"], data["mask"]
                np.testing.assert_array_equal(true, np.stack([records[i]["features"]["targets"][1:] for i in f["test"]]))
                np.testing.assert_array_equal(mask, np.stack([records[i]["features"]["target_mask"][1:] for i in f["test"]]))
                ids.extend(f["test"]); masks.append(mask)
                for method in METHODS:
                    names = [method] if not method.endswith("_seed_mean") else [method.replace("_seed_mean", f"_{s}") for s in seeds]
                    per_seed = []
                    for name in names:
                        pred = data[name]
                        current = np.stack([records[i]["features"]["targets"][:-1] for i in f["test"]])
                        valid = (np.isfinite(pred).all(-1) & (pred >= -1e-7).all(-1) &
                                 np.isclose(pred[..., :6].sum(-1), 1, atol=1e-6, rtol=0) &
                                 (pred[..., 5] >= current[..., 5] - 1e-7) & (pred[..., 6] <= pred[..., 7] + 1e-7))
                        result["physical_constraint_violations"] += int((~valid).sum())
                        per_seed.append((pred - true) ** 2 * mask)
                    errors[method].append(np.mean(per_seed, axis=0))
        mask = np.concatenate(masks)
        result["tasks"][task] = {}
        for method, values in errors.items():
            error = np.concatenate(values)
            item = breakdown(error, mask)
            item["by_map"] = {m: breakdown(error[keep], mask[keep]) for m in report["maps"]
                              if (keep := np.array([records[i]["map"] == m for i in ids])).any()}
            item["by_series"] = {s: breakdown(error[keep], mask[keep]) for s in report["series"]
                                 if (keep := np.array([records[i]["series"] == s for i in ids])).any()}
            expected = report["tasks"][task]["methods"][method]["all"]["mse"]
            assert np.isclose(item["mse"], expected, rtol=1e-6, atol=1e-10), "Seed aggregation changed"
            result["tasks"][task][method] = item
    assert result["physical_constraint_violations"] == 0
    write(a.output, result)
    print(json.dumps({"saved": str(a.output), "constraint_violations": result["physical_constraint_violations"]}))


if __name__ == "__main__":
    main()
