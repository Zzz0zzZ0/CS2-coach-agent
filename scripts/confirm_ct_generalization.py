"""Offline, series-disjoint CT adaptation matrix; state prediction is not tactical gold."""

import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_feature_service import feature_sequence
from app.services.ct_linear_service import linear_inputs, linear_forecast
from app.services.ct_prediction_service import project_prediction
from app.services.ct_evaluation_service import error_totals, summarize, paired_series_bootstrap


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def make_folds(records):
    """Exclude whole series even when only one map supplies the test targets."""
    series = sorted({r["series"] for r in records})
    maps = sorted({r["map"] for r in records})
    folds, unsupported = [], []

    def add(name, task, train, val, test, support=(), parent=None):
        parts = [sorted(set(x)) for x in (train, val, test)]
        identities = [{records[i]["series"] for i in part} for part in parts]
        if not all(parts) or any(identities[i] & identities[j] for i in range(3) for j in range(i)):
            raise ValueError("Nonempty, series-disjoint train/validation/test partitions required")
        folds.append(dict(name=name, task=task, train=parts[0], validation=parts[1], test=parts[2],
                          support=list(support), parent=parent))

    for map_name in maps:
        available = sorted({r["series"] for r in records if r["map"] == map_name})
        if len(available) < 3:
            unsupported.append({"task": "G2", "map": map_name, "series": available,
                                "reason": "fewer than three series for disjoint train/validation/test"})
        else:
            for k, test in enumerate(available):
                val = available[(k + 1) % len(available)]
                ids = [i for i, r in enumerate(records) if r["map"] == map_name]
                add(f"G2__{map_name}__{test}", "G2", [i for i in ids if records[i]["series"] not in (test, val)],
                    [i for i in ids if records[i]["series"] == val], [i for i in ids if records[i]["series"] == test])
    if len(series) < 3:
        unsupported.append({"task": "G3", "reason": "fewer than three series for disjoint train/validation/test"})
    for k, test in enumerate(series if len(series) >= 3 else []):
        val = series[(k + 1) % len(series)]
        add(f"G3__{test}", "G3", [i for i, r in enumerate(records) if r["series"] not in (test, val)],
            [i for i, r in enumerate(records) if r["series"] == val], [i for i, r in enumerate(records) if r["series"] == test])
    for map_name in maps:
        target_series = sorted({r["series"] for r in records if r["map"] == map_name})
        remaining = [s for s in series if s not in target_series]
        if len(remaining) < 2:
            unsupported.append({"task": "G4/G5", "map": map_name, "reason": "fewer than two source series after excluding all test-map series"})
            continue
        val = [i for i, r in enumerate(records) if r["series"] == remaining[0]]
        train = [i for i, r in enumerate(records) if r["series"] in remaining[1:]]
        test = [i for i, r in enumerate(records) if r["map"] == map_name]
        parent = f"G4__{map_name}"
        add(parent, "G4", train, val, test)
        if len(target_series) >= 2:
            support = [i for i in test if records[i]["series"] == target_series[0]]
            add(f"G5__{map_name}", "G5", train + support, val, [i for i in test if i not in support], support, parent)
        else:
            unsupported.append({"task": "G5", "map": map_name, "reason": "only one target series; support would consume all test data"})
    return folds, unsupported


def prefix_inputs(inputs):
    """Four causal prefixes, padded after the last available observation, plus time index."""
    if inputs.ndim != 3 or inputs.shape[1:] != (5, 10) or not np.isfinite(inputs).all():
        raise ValueError("Finite five-frame ten-feature observations required")
    out = np.zeros((len(inputs), 4, 44), dtype=np.float64)
    for k in range(4):
        out[:, k, :10 * (k + 1)] = inputs[:, :k + 1].reshape(len(inputs), -1)
        out[:, k, 40 + k] = 1
    return out


def fit_ridge(x, current, target, mask, validation, penalties):
    mean, std = x.mean((0, 1)), x.std((0, 1)).clip(1e-6)
    design = np.concatenate([(x - mean) / std, np.ones_like(x[..., :1])], -1).reshape(-1, x.shape[-1] + 1)
    delta, weights = (target - current).reshape(-1, 8), mask.reshape(-1, 8)
    best = None
    for penalty in penalties:
        coefficients = np.zeros((design.shape[-1], 8))
        for k in range(8):
            w = weights[:, k]
            if not w.any():
                continue
            regularizer = np.diag([penalty * w.sum()] * (design.shape[-1] - 1) + [0])
            coefficients[:, k] = np.linalg.solve(design.T @ (design * w[:, None]) + regularizer,
                                                 design.T @ (delta[:, k] * w))
        vx, vc, vt, vm = validation
        forecast = linear_forecast(vx, vc, mean, std, coefficients)
        mse = float((((forecast - vt) ** 2) * vm).sum() / vm.sum())
        if best is None or mse < best[0]:
            best = (mse, penalty, coefficients)
    return mean, std, best


def load_records(folders):
    records, receipts, demos = [], {}, set()
    for folder in folders:
        receipts[str(folder)] = sha(folder / "report.json")
        index = json.loads((folder / "sample_index.json").read_text(encoding="utf-8"))
        for name, entries in sorted(index.items()):
            if name in ("source_train", "dust2_test"):
                continue
            document = json.loads((folder / f"{name}_snapshots.json").read_text(encoding="utf-8"))
            digest = document["source_demo_sha256"]
            if digest in demos:
                raise ValueError("Duplicate raw demo across datasets")
            demos.add(digest)
            rows = {r["round_number"]: r for r in document["rounds"] if r["side"] == "CT"}
            for entry in entries:
                if not entry.get("timing_passed"):
                    raise ValueError("Only independently clock-verified CT windows allowed")
                records.append({**entry, "features": feature_sequence(rows[entry["round_number"]]["snapshots"])})
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("Duplicate CT round identity")
    return records, receipts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expansion-dirs", type=Path, nargs="+", required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory; do not overwrite previous attempts")
    import psutil
    import torch
    from scripts.run_ct_generalization import CTModel, arrays, batch
    assert psutil.virtual_memory().available > 2 * 2**30, "RAM guard"
    assert torch.cuda.is_available()
    torch.set_num_threads(1)
    torch.cuda.set_per_process_memory_fraction(.2)
    assert torch.cuda.mem_get_info()[0] > 1024 * 2**20, "VRAM guard"
    torch.backends.fp32_precision = "ieee"
    torch.backends.cudnn.fp32_precision = "ieee"
    torch.backends.cuda.matmul.fp32_precision = "ieee"
    torch.backends.cudnn.rnn.fp32_precision = "tf32"
    sys.path.insert(0, str(ROOT / "output/tagnet/upstream/scripts"))
    import train_tagnet as trainer
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    frozen = protocol["frozen_sha256"]
    for path, digest in frozen.items():
        assert sha(ROOT / path) == digest, path
    records, receipts = load_records(args.expansion_dirs)
    folds, unsupported = make_folds(records)
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "sample_index.json", [{k: v for k, v in r.items() if k != "features"} for r in records])
    write(args.output_dir / "folds.json", folds)
    all_data = arrays(records)
    all_x, all_current = linear_inputs(all_data)
    np.testing.assert_allclose(all_current, all_data["targets"], atol=1e-6, rtol=0)
    all_prefix = prefix_inputs(all_x)
    cfg = protocol["training"]
    report = {"status": "running", "scope": protocol["scope"], "protocol_sha256": sha(args.protocol),
              "evaluator_sha256": sha(Path(__file__)), "input_report_sha256": receipts,
              "rounds": len(records), "series": sorted({r["series"] for r in records}),
              "maps": sorted({r["map"] for r in records}), "unsupported": unsupported,
              "training": cfg, "folds": [], "tasks": {}, "frozen_sha256": frozen,
              "limitations": ["retrospective grouped CV under a frozen recipe; not untouched project-wide evaluation",
                              "few professional series with shared teams; bootstrap intervals descriptive",
                              "no upstream samples in re-training, avoiding uncertified source series identities",
                              "state forecasts and Euclidean geometry are proxies, not tactical relevance or coaching benefit",
                              "G5 has one deterministic support selection per map, not a support-seed population estimate"]}
    receipt = args.output_dir / "report.json"
    started = time.monotonic()
    outputs = {}

    def predict(model, temporal, data):
        result = []
        model.eval()
        with torch.no_grad():
            for start in range(0, len(data["nodes"]), cfg["batch_size"]):
                b = batch(data, start, start + cfg["batch_size"])
                result.append(model({k: b[k] for k in ("nodes", "edges", "alive")}, temporal)[1].cpu().numpy())
        current = linear_inputs(data)[1][:, :-1]
        return project_prediction(current, np.concatenate(result))

    for fold in folds:
        folder = args.output_dir / fold["name"]
        folder.mkdir()
        tr, va, te = (np.array(fold[k]) for k in ("train", "validation", "test"))
        data = [{k: v[ids] for k, v in all_data.items()} for ids in (tr, va, te)]
        truth, mask, current = all_data["targets"][te, 1:], all_data["target_mask"][te, 1:], all_current[te, :-1]
        previous = np.concatenate([all_current[te, :1], all_current[te, :3]], axis=1)
        predictions = {"persistence": current.copy(), "velocity": project_prediction(current, current +
                        (current - previous) * np.array([0, 1.5, 1, 2 / 3])[None, :, None])}
        entry = {k: v for k, v in fold.items() if k not in ("train", "validation", "test", "support")}
        entry.update({k + "_rounds": len(fold[k]) for k in ("train", "validation", "test", "support")})
        entry["ridge"] = {}
        for name, x in (("ridge", all_x[:, :-1]), ("prefix_ridge", all_prefix)):
            mean, std, (score, penalty, coef) = fit_ridge(x[tr], all_current[tr, :-1], all_data["targets"][tr, 1:],
                all_data["target_mask"][tr, 1:], (x[va], all_current[va, :-1], all_data["targets"][va, 1:], all_data["target_mask"][va, 1:]), cfg["ridge_penalties"])
            predictions[name] = linear_forecast(x[te], current, mean, std, coef)
            np.savez(folder / f"{name}.npz", mean=mean, std=std, coefficients=coef)
            entry["ridge"][name] = {"penalty": penalty, "validation_mse": score, "coefficients": int(coef.size)}
        entry["neural"] = []
        for seed in cfg["seeds"]:
            trainer.set_seed(seed)
            initial = CTModel(trainer, residual=True).state_dict()
            for temporal in (False, True):
                name = "gru" if temporal else "static"
                variants = (name, name + "_continued_without_support") if fold["task"] == "G5" else (name,)
                for variant in variants:
                    assert psutil.virtual_memory().available > 1536 * 2**20, "RAM guard"
                    model = CTModel(trainer, residual=True)
                    if fold["parent"]:
                        parent = args.output_dir / fold["parent"] / f"{name}_{seed}.pt"
                        model.load_state_dict(torch.load(parent, weights_only=True, map_location="cpu"))
                    else:
                        model.load_state_dict(initial)
                    model = model.cuda()
                    train_data = data[0]
                    if variant.endswith("without_support"):
                        ids = np.array([i for i in tr if i not in fold["support"]])
                        train_data = {k: v[ids] for k, v in all_data.items()}
                    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["lr"], weight_decay=cfg["weight_decay"])
                    best, best_state, epoch_chosen = float("inf"), None, None
                    for epoch in range(cfg["epochs_max"]):
                        assert psutil.virtual_memory().available > 1536 * 2**20, "RAM guard during training"
                        model.train()
                        # Continuation controls get the same optimizer-step budget as adaptation.
                        steps = (len(data[0]["nodes"]) + cfg["batch_size"] - 1) // cfg["batch_size"]
                        batches = (len(train_data["nodes"]) + cfg["batch_size"] - 1) // cfg["batch_size"]
                        for step in range(steps):
                            start = (step % batches) * cfg["batch_size"]
                            b = batch(train_data, start, start + cfg["batch_size"])
                            optimizer.zero_grad(set_to_none=True)
                            rec, pred, _ = model({k: b[k] for k in ("nodes", "edges", "alive")}, temporal)
                            loss = (((rec - b["targets"]) ** 2) * b["target_mask"]).sum() / b["target_mask"].sum()
                            m = b["target_mask"][:, 1:]
                            loss = loss + (((pred - b["targets"][:, 1:]) ** 2) * m).sum() / m.sum()
                            assert torch.isfinite(loss), "Nonfinite training loss"
                            loss.backward()
                            torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
                            optimizer.step()
                        p = predict(model, temporal, data[1])
                        vm = data[1]["target_mask"][:, 1:]
                        score = float((((p - data[1]["targets"][:, 1:]) ** 2) * vm).sum() / vm.sum())
                        if score < best:
                            best, epoch_chosen = score, epoch + 1
                            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                    model.load_state_dict(best_state)
                    predictions[f"{variant}_{seed}"] = predict(model, temporal, data[2])
                    torch.save(best_state, folder / f"{variant}_{seed}.pt")
                    entry["neural"].append({"method": variant, "seed": seed, "selected_epoch": epoch_chosen,
                        "validation_mse": best, "optimizer_steps_run": cfg["epochs_max"] * steps,
                        "selected_optimizer_step": epoch_chosen * steps})
                    del model, optimizer, best_state
                    torch.cuda.empty_cache()
        # Average metrics across seeds, not a selected seed or an ensemble forecast.
        totals = {name: [error_totals(p, t, m) for p, t, m in zip(pred, truth, mask)] for name, pred in predictions.items()}
        for method in ("static", "gru", "static_continued_without_support", "gru_continued_without_support"):
            names = [f"{method}_{seed}" for seed in cfg["seeds"]]
            if all(n in totals for n in names):
                totals[method + "_seed_mean"] = [{key: float(np.mean([totals[n][i][key] for n in names]))
                                                 for key in totals[names[0]][i]} for i in range(len(te))]
        entry["metrics"] = {name: summarize(rows) for name, rows in totals.items()}
        np.savez_compressed(folder / "predictions.npz", test_indices=te, truth=truth, mask=mask, **predictions)
        write(folder / "report.json", entry)
        outputs[fold["name"]] = (fold, totals)
        report["folds"].append(entry)
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        write(receipt, report)
        print(json.dumps({"completed_fold": fold["name"], "folds_done": len(outputs), "folds_total": len(folds),
                          "minutes": round(report["elapsed_seconds"] / 60, 2)}), flush=True)

    for task in ("G2", "G3", "G4", "G5"):
        chosen = [x for x in outputs.values() if x[0]["task"] == task]
        if not chosen:
            continue
        methods = sorted(set.intersection(*(set(rows) for _, rows in chosen)))
        all_ids = [i for f, _ in chosen for i in f["test"]]
        assert len(all_ids) == len(set(all_ids)), "Repeated test round within task"
        series = [records[i]["series"] for i in all_ids]
        scores = {n: [r for _, totals in chosen for r in totals[n]] for n in methods}
        result = {"folds": len(chosen), "test_rounds": len(all_ids), "series": len(set(series)), "methods": {}}
        for name, totals in scores.items():
            item = {"all": summarize(totals), "vs_persistence": paired_series_bootstrap(totals, scores["persistence"], series)}
            for baseline in ("ridge", "prefix_ridge", "velocity"):
                item["vs_" + baseline] = paired_series_bootstrap(totals, scores[baseline], series)
            item["by_map"] = {m: summarize([r for r, i in zip(totals, all_ids) if records[i]["map"] == m]) for m in report["maps"]}
            item["death_in_window"] = summarize([r for r, i in zip(totals, all_ids) if (~all_data["alive"][i]).any()])
            item["all_alive"] = summarize([r for r, i in zip(totals, all_ids) if all_data["alive"][i].all()])
            item["by_equipment_at_10"] = {label: summarize([r for r, i in zip(totals, all_ids) if
                (float(np.expm1(all_data["nodes"][i, 0, :, 6] * np.log1p(10000)).mean()) < 3000) == low])
                for label, low in (("mean_below_3000", True), ("mean_at_least_3000", False))}
            if task == "G5":
                parent_rows = []
                for fold, _ in chosen:
                    pf, pt = outputs[fold["parent"]]
                    parent_rows.extend(pt[name][pf["test"].index(i)] for i in fold["test"] if name in pt)
                if len(parent_rows) == len(totals):
                    item["vs_G4_same_test"] = paired_series_bootstrap(totals, parent_rows, series)
                if name in ("static_seed_mean", "gru_seed_mean"):
                    control = name.replace("_seed_mean", "_continued_without_support_seed_mean")
                    item["vs_continued_without_support"] = paired_series_bootstrap(totals, scores[control], series)
            result["methods"][name] = item
        report["tasks"][task] = result
    report["status"] = "completed_grouped_generalization_matrix"
    report["resources"] = {"peak_allocated_VRAM_MiB": torch.cuda.max_memory_allocated() / 2**20,
                           "process_peak_RAM_MiB": psutil.Process().memory_info().peak_wset / 2**20}
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    for path, digest in frozen.items():
        assert sha(ROOT / path) == digest, path
    write(receipt, report)
    print(json.dumps({"completed": str(receipt), "minutes": report["elapsed_seconds"] / 60}), flush=True)


if __name__ == "__main__":
    main()
