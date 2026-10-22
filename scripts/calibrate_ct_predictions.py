"""Calibrate frozen CT forecasts using Dust2 validation only; retrospective target checks."""

import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import psutil
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_feature_service import FEATURE_VERSION, feature_sequence
from app.services.ct_prediction_service import (
    CALIBRATION_VERSION, calibrate_prediction, constrain_prediction, fit_shrinkage, project_prediction,
)
from app.services.ct_linear_service import MODEL_VERSION, CTLinearPredictor, linear_inputs, linear_forecast
from run_ct_generalization import CTModel, arrays, batch


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def metrics(prediction, data):
    mask = data["target_mask"][:, 1:]
    errors = (prediction - data["targets"][:, 1:]) ** 2 * mask
    return {"mse": float(errors.sum() / mask.sum()),
            "occupancy_mse": float(errors[..., :6].sum() / mask[..., :6].sum()),
            "distance_mse": float(errors[..., 6:].sum() / max(mask[..., 6:].sum(), 1))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    assert psutil.virtual_memory().available > 2 * 2**30, "RAM guard"
    assert torch.cuda.is_available()
    torch.set_num_threads(1)
    torch.cuda.set_per_process_memory_fraction(.2)
    assert torch.cuda.mem_get_info()[0] > 1024 * 2**20, "VRAM guard"
    torch.backends.fp32_precision = "ieee"
    torch.backends.cudnn.fp32_precision = "ieee"
    torch.backends.cuda.matmul.fp32_precision = "ieee"
    torch.backends.cudnn.rnn.fp32_precision = "tf32"
    sys.path.insert(0, str(args.upstream_dir.resolve() / "scripts"))
    import train_tagnet as trainer

    frozen = json.loads((ROOT / "output/tagnet/ct_frozen_acquisition_protocol_v1.json").read_text())
    for path, digest in frozen["frozen_sha256"].items():
        assert checksum(ROOT / path) == digest, f"Frozen input changed: {path}"
    source = args.upstream_dir / "data/processed/dust2_ct_5snap/ct_snapshot_nodes.parquet"
    frame = pd.read_parquet(source)
    source_groups = {"train": [], "val": [], "test": []}
    identities = {name: sorted(part["match_id"].unique().tolist()) for name, part in frame.groupby("split")}
    assert not set(identities["val"]) & set(identities["test"])
    assert not set(identities["val"]) & set(identities["train"])
    for sid, rows in frame[frame["split"].isin(source_groups)].groupby("sample_id", sort=True):
        snapshots = [{"second": int(second), "players": [
            {"steamid": r.player_id, "position": [r.X, r.Y, r.Z], "health": r.health,
             "equipment_value": r.current_equip_value, "place": r.place}
            for r in time.sort_values("player_slot").itertuples()]}
            for second, time in rows.groupby("second", sort=True)]
        source_groups[rows.iloc[0]["split"]].append({"id": sid, "features": feature_sequence(snapshots)})
    validation = arrays(source_groups["val"])
    assert len(validation["nodes"]) == 95
    args.output_dir.mkdir(parents=True, exist_ok=False)
    weight_dir = ROOT / "output/tagnet/ct_generalization_residual_v1"
    checkpoints = sorted(weight_dir.glob("*.pt"))
    assert len(checkpoints) == 10
    code = [Path(__file__), ROOT / "app/services/ct_prediction_service.py", ROOT / "app/services/ct_linear_service.py"]
    protocol = {"status": "source_validation_fitted_before_target_evaluation",
                "calibration_version": CALIBRATION_VERSION, "feature_version": FEATURE_VERSION,
                "method": "death-floor Euclidean projection; per-component gains in [0,2], nine-point grid plus least-squares candidate, Dust2 val only",
                "fit_split": "Dust2 val only, 95 rounds; existing checkpoint selection reused this split",
                "source_sha256": checksum(source), "validation_match_ids": identities["val"],
                "code_sha256": {str(p.relative_to(ROOT)): checksum(p) for p in code},
                "frozen_sha256": frozen["frozen_sha256"], "models": {}}

    def load_model(path):
        assert psutil.virtual_memory().available > 1536 * 2**20, "RAM guard"
        checkpoint = torch.load(path, weights_only=True, map_location="cpu")
        assert checkpoint["feature_version"] == FEATURE_VERSION and checkpoint["residual"]
        model = CTModel(trainer, residual=True)
        model.load_state_dict(checkpoint["model_state_dict"], strict=True)
        return model.cuda().eval().requires_grad_(False), checkpoint["temporal"]

    def predict(model, temporal, data):
        current, forecast = [], []
        with torch.no_grad():
            for start in range(0, len(data["nodes"]), 64):
                inputs = batch(data, start, start + 64)
                # Forecasts and fallback observations never read supervision arrays.
                inputs = {k: inputs[k] for k in ("nodes", "edges", "alive")}
                current.append(model.observed(inputs)[:, :-1].cpu().numpy())
                forecast.append(model(inputs, temporal)[1].cpu().numpy())
        return np.concatenate(current), np.concatenate(forecast)

    for path in checkpoints:
        model, temporal = load_model(path)
        current, predicted = predict(model, temporal, validation)
        np.testing.assert_allclose(current, validation["targets"][:, :-1], atol=1e-6, rtol=0)
        scales = fit_shrinkage(current, predicted, validation["targets"][:, 1:], validation["target_mask"][:, 1:])
        calibrated = calibrate_prediction(current, predicted, scales)
        constrained = constrain_prediction(current, predicted)
        assert metrics(calibrated, validation)["mse"] <= metrics(constrained, validation)["mse"] + 1e-10
        np.savez_compressed(args.output_dir / f"{path.stem}_validation_predictions.npz",
                            current=current, raw=predicted, truth=validation["targets"][:, 1:], mask=validation["target_mask"][:, 1:])
        protocol["models"][path.stem] = {"checkpoint": str(path.relative_to(ROOT)),
            "checkpoint_sha256": checksum(path), "scales": scales,
            "validation": {"raw": metrics(predicted, validation), "constrained": metrics(constrained, validation),
                           "calibrated": metrics(calibrated, validation)}}
        del model
    def baseline_input(data):
        inputs, current = linear_inputs(data)
        np.testing.assert_allclose(current, data["targets"], atol=1e-6, rtol=0)
        return inputs[:, :-1], current[:, :-1]

    train = arrays(source_groups["train"])
    x_train, past_train = baseline_input(train)
    x_val, past_val = baseline_input(validation)
    # Only past observations form inputs; future labels and masks are supervision.
    changed = dict(validation); changed["targets"] = np.zeros_like(validation["targets"])
    np.testing.assert_array_equal(linear_inputs(changed)[0][:, :-1], x_val)
    mean, std = x_train.mean((0, 1)), x_train.std((0, 1)).clip(1e-6)

    def design(inputs):
        normalized = (inputs - mean) / std
        return np.concatenate([normalized, np.ones_like(normalized[..., :1])], -1)

    x = design(x_train).reshape(-1, 11)
    y = (train["targets"][:, 1:] - past_train).reshape(-1, 8)
    mask = train["target_mask"][:, 1:].reshape(-1, 8)
    trials = []
    for penalty in (1e-4, 1e-3, .01, .1, 1, 10, 100):
        coefficients = np.empty((11, 8))
        for k in range(8):
            weights = mask[:, k]
            regularizer = np.diag([penalty * weights.sum()] * 10 + [0])
            coefficients[:, k] = np.linalg.solve(x.T @ (x * weights[:, None]) + regularizer, x.T @ (y[:, k] * weights))
        predicted = project_prediction(past_val, past_val + design(x_val) @ coefficients)
        trials.append((metrics(predicted, validation)["mse"], penalty, coefficients))
    val_mse, penalty, coefficients = min(trials, key=lambda row: row[0])
    assert np.isfinite(coefficients).all()
    np.savez(args.output_dir / "ridge_baseline.npz", mean=mean, std=std, coefficients=coefficients)
    protocol["ridge_baseline"] = {"inputs": "current 8 state summaries plus alive CT mean normalized health/equipment; no time or map ID",
        "train_rounds": len(train["nodes"]), "penalty": penalty, "validation_mse": val_mse,
        "trials": [{"penalty": p, "validation_mse": s} for s, p, _ in trials],
        "parameters": int(coefficients.size), "weights_sha256": checksum(args.output_dir / "ridge_baseline.npz")}
    model_file = args.output_dir / "ct_linear_v1.json"
    model_file.write_text(json.dumps({"model_version": MODEL_VERSION, "feature_version": FEATURE_VERSION,
        "status": "experimental; source validation selected, target results retrospective",
        "training": {"source_sha256": checksum(source), "rounds": len(train["nodes"]),
                     "validation_rounds": len(validation["nodes"]), "ridge_penalty": penalty,
                     "code_sha256": protocol["code_sha256"]},
        "mean": mean.tolist(), "std": std.tolist(), "coefficients": coefficients.tolist()}, indent=2, allow_nan=False) + "\n")
    protocol["ridge_baseline"]["json_model_sha256"] = checksum(model_file)
    loaded = CTLinearPredictor(model_file)
    np.testing.assert_allclose(linear_forecast(x_val, past_val, loaded.mean, loaded.std, loaded.coefficients),
                               project_prediction(past_val, past_val + design(x_val) @ coefficients), atol=1e-12, rtol=0)
    protocol_file = args.output_dir / "calibration.json"
    protocol_file.write_text(json.dumps(protocol, indent=2, allow_nan=False) + "\n")
    protocol_hash = checksum(protocol_file)
    print("Source-only calibration frozen; reading retrospective evaluation inputs", flush=True)

    groups = {"dust2_test": source_groups["test"]}
    target_paths = [ROOT / f"output/tagnet/{name}/snapshots.json" for name in (
        "mirage_opening_full_v1", "anubis_opening_full_v1", "inferno_opening_full_v1",
        "2396940_map1_opening_v1", "2396940_map2_opening_v1")]
    raw = ROOT / "output/tagnet/new_demos_2396949/BLAST_Open_Porto_2026_Spirit_vs_Falcons_2396949_map2.dem"
    from app.services.parser_service import TacticalDemoParser
    raw_data = TacticalDemoParser(str(raw)).parse_opening_snapshots()
    target_hashes = {str(raw.relative_to(ROOT)): checksum(raw)}
    skipped = []

    def add_rounds(name, observed, prefix):
        for row in observed["rounds"]:
            if row["side"] != "CT":
                continue
            if row["status"] != "ok":
                skipped.append({"group": name, "round": row["round_number"], "reason": row["reason"]})
                continue
            groups.setdefault(name, []).append({"id": f"{prefix}:{row['round_number']}:CT",
                "features": feature_sequence(row["snapshots"])})

    assert raw_data["map_name"] == "de_ancient"
    add_rounds("de_ancient_2396949", raw_data, "2396949")
    for path in target_paths:
        document = json.loads(path.read_text())
        target_hashes[str(path.relative_to(ROOT))] = checksum(path)
        add_rounds(document["map_name"], document, document["source_demo_sha256"])
    datasets = {name: arrays(rows) for name, rows in groups.items()}
    report = {"status": "completed_retrospective_calibration_check", "calibration_sha256": protocol_hash,
        "feature_version": FEATURE_VERSION, "calibration_version": CALIBRATION_VERSION,
        "scope": "Calibration fit on Dust2 validation only; target results previously observed, not a new blind test",
        "primary_model": "static_snapshot_42", "source_hashes": target_hashes,
        "groups": {name: {"rounds": len(rows), "sample_ids": [r["id"] for r in rows]} for name, rows in groups.items()},
        "skipped": skipped, "models": {}, "persistence": {},
        "limitations": ["calibration and checkpoint selection share the same 95 validation rounds",
                        "target maps and series previously observed", "match aliases not independently audited",
                        "timing/pause calibration pending", "no tactical or retrieval quality labels"]}
    for name, data in datasets.items():
        report["persistence"][name] = metrics(data["targets"][:, :-1], data)
    report["ridge_baseline"] = {}
    for name, data in datasets.items():
        inputs, current = baseline_input(data)
        prediction = linear_forecast(inputs, current, mean, std, coefficients)
        report["ridge_baseline"][name] = metrics(prediction, data)
    for path in checkpoints:
        model, temporal = load_model(path)
        config = protocol["models"][path.stem]
        assert checksum(path) == config["checkpoint_sha256"]
        results, cached = {}, {}
        for name, data in datasets.items():
            current, predicted = predict(model, temporal, data)
            constrained = constrain_prediction(current, predicted)
            calibrated = calibrate_prediction(current, predicted, config["scales"])
            assert (calibrated[..., 5] >= current[..., 5] - 1e-7).all()
            results[name] = {"raw": metrics(predicted, data), "constrained": metrics(constrained, data),
                "calibrated": metrics(calibrated, data),
                "raw_resurrection_fraction": float((predicted[..., 5] < current[..., 5] - 1e-7).mean()),
                "per_transition": [{"from_second": a, "to_second": b,
                    "raw_mse": float((((predicted - data['targets'][:, 1:]) ** 2 * data['target_mask'][:, 1:])[:, k]).sum() / data['target_mask'][:, k+1].sum()),
                    "calibrated_mse": float((((calibrated - data['targets'][:, 1:]) ** 2 * data['target_mask'][:, 1:])[:, k]).sum() / data['target_mask'][:, k+1].sum())}
                    for k, (a, b) in enumerate(zip((10, 12, 15, 18), (12, 15, 18, 20)))]}
            for key, value in {"current": current, "raw": predicted, "calibrated": calibrated,
                               "truth": data["targets"][:, 1:], "mask": data["target_mask"][:, 1:]}.items():
                cached[f"{name}__{key}"] = value
        np.savez_compressed(args.output_dir / f"{path.stem}_predictions.npz", **cached)
        report["models"][path.stem] = results
        print(json.dumps({"model": path.stem, "scales": config["scales"], "mse": {
            name: {kind: value[kind]["mse"] for kind in ("raw", "calibrated")} for name, value in results.items()}}), flush=True)
        del model
    assert checksum(protocol_file) == protocol_hash
    for path, digest in frozen["frozen_sha256"].items():
        assert checksum(ROOT / path) == digest
    report["resources"] = {"peak_allocated_VRAM_MiB": torch.cuda.max_memory_allocated() / 2**20,
                           "process_RSS_MiB": psutil.Process().memory_info().rss / 2**20}
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
