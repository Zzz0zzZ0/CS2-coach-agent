"""Retrospective sensitivity: drop ambiguous source team pairs from both train and validation."""

import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_evaluation_service import error_totals, summarize, paired_series_bootstrap
from app.services.ct_feature_service import feature_sequence
from app.services.ct_linear_service import linear_inputs, linear_forecast
from scripts.ct_experiment_data import load_source, canonical_pair


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expansion-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    groups, audit = load_source(ROOT / "output/tagnet/upstream/data/processed/dust2_ct_5snap/ct_snapshot_nodes.parquet")
    ambiguous = {tuple(row["canonical_pair"]) for row in audit["cross_split_pair_aliases"]}
    filtered = {name: [row for row in rows if canonical_pair(row["series"]) not in ambiguous] for name, rows in groups.items()}
    assert all(canonical_pair(row["series"]) not in ambiguous for rows in filtered.values() for row in rows)
    arrays = lambda rows: {key: np.stack([r["features"][key] for r in rows]) for key in rows[0]["features"]}
    train, val = (arrays(filtered[name]) for name in ("train", "val"))
    x, current = linear_inputs(train)
    xv, cv = linear_inputs(val)
    mean, std = x[:, :-1].mean((0, 1)), x[:, :-1].std((0, 1)).clip(1e-6)
    standardized = (x[:, :-1] - mean) / std
    design = np.concatenate([standardized, np.ones_like(standardized[..., :1])], -1).reshape(-1, 11)
    delta = (train["targets"][:, 1:] - current[:, :-1]).reshape(-1, 8)
    mask = train["target_mask"][:, 1:].reshape(-1, 8)
    trials = []
    for penalty in (1e-4, .001, .01, .1, 1, 10, 100):
        coefficients = np.empty((11, 8))
        for k in range(8):
            weight = mask[:, k]
            regularizer = np.diag([penalty * weight.sum()] * 10 + [0])
            coefficients[:, k] = np.linalg.solve(design.T @ (design * weight[:, None]) + regularizer, design.T @ (delta[:, k] * weight))
        pred = linear_forecast(xv[:, :-1], cv[:, :-1], mean, std, coefficients)
        score = summarize([error_totals(pred, val["targets"][:, 1:], val["target_mask"][:, 1:])])["mse"]
        trials.append((score, penalty, coefficients))
    score, penalty, coefficients = min(trials, key=lambda trial: trial[0])
    assert np.isfinite(coefficients).all()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    np.savez(args.output_dir / "alias_excluded_weights.npz", mean=mean, std=std, coefficients=coefficients)
    selection = {"scope": "retrospective sensitivity control, not a new blind experiment or replacement model",
        "excluded_pairs": [list(pair) for pair in sorted(ambiguous)],
        "rounds_before": {name: len(rows) for name, rows in groups.items()},
        "rounds_after": {name: len(rows) for name, rows in filtered.items()}, "penalty": penalty,
        "validation_mse": score, "selection": "same seven penalties on filtered source validation only",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.output_dir / "selection.json").write_text(json.dumps(selection, indent=2) + "\n")
    index = json.loads((args.expansion_dir / "sample_index.json").read_text())
    original = json.loads((args.expansion_dir / "report.json").read_text())
    report = {**selection, "groups": {}, "paired_series": {}}
    totals, persistence, series, fresh = [], [], [], []
    for name, records in index.items():
        if name in ("source_train", "dust2_test"):
            continue
        doc = json.loads((args.expansion_dir / f"{name}_snapshots.json").read_text())
        rows = {row["round_number"]: row for row in doc["rounds"] if row["side"] == "CT"}
        data = arrays([{"features": feature_sequence(rows[r["round_number"]]["snapshots"])} for r in records])
        inputs, observed = linear_inputs(data)
        pred = linear_forecast(inputs[:, :-1], observed[:, :-1], mean, std, coefficients)
        assert (pred[..., 5] >= observed[:, :-1, 5] - 1e-7).all()
        model_rows = [error_totals(p, t, mask) for p, t, mask in zip(pred, data["targets"][:, 1:], data["target_mask"][:, 1:])]
        base_rows = [error_totals(p, t, mask) for p, t, mask in zip(observed[:, :-1], data["targets"][:, 1:], data["target_mask"][:, 1:])]
        report["groups"][name] = {"sensitivity_model": summarize(model_rows), "persistence": summarize(base_rows),
            "original_model": original["metrics"][name]["ct_linear_v1"]["all"]}
        totals.extend(model_rows); persistence.extend(base_rows)
        series.extend([original["groups"][name]["series"]] * len(records))
        fresh.extend([original["groups"][name]["scope"] == "frozen_new_acquisition"] * len(records))
    report["paired_series"]["all_targets"] = paired_series_bootstrap(totals, persistence, series)
    report["paired_series"]["new_series"] = paired_series_bootstrap(
        [row for row, keep in zip(totals, fresh) if keep], [row for row, keep in zip(persistence, fresh) if keep],
        [name for name, keep in zip(series, fresh) if keep])
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"rounds_after": selection["rounds_after"], "paired_series": report["paired_series"]}))


if __name__ == "__main__":
    main()
