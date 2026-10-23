"""Development-only richer invariant ridge controls on the frozen v7 G3/G4 splits."""

import os
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[name] = "1"
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_linear_service import linear_inputs, linear_forecast
from app.services.ct_evaluation_service import error_totals, paired_series_bootstrap, summarize
from scripts.confirm_ct_generalization import fit_ridge, load_records, sha, write


def pooled_inputs(data):
    base, current = linear_inputs(data)
    nodes, edges, alive = (np.asarray(data[k]) for k in ("nodes", "edges", "alive"))
    if (edges < 0).any():
        raise ValueError("Distances must be nonnegative")
    role_state = (nodes[..., :5, None] * nodes[..., None, 5:7] * alive[..., None, None]).sum(2) / 5
    variance = (((nodes[..., 5:7] - base[..., None, 8:10]) ** 2) * alive[..., None]).sum(2)
    spread = np.sqrt(variance / alive.sum(2, keepdims=True))
    node_summary = np.concatenate([role_state.reshape(*base.shape[:2], 10), spread], -1)
    i, j = np.triu_indices(5, 1)
    valid = alive[..., i] & alive[..., j]
    ordered = np.sort(np.where(valid, edges[..., i, j], np.inf), axis=-1)
    valid = np.isfinite(ordered)
    pair_summary = np.concatenate([np.where(valid, ordered, 0), valid.astype(float)], -1)
    return {"ridge": base, "node_ridge": np.concatenate([base, node_summary], -1),
            "pair_ridge": np.concatenate([base, pair_summary], -1),
            "pooled_ridge": np.concatenate([base, node_summary, pair_summary], -1)}, current


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    if a.output_dir.exists():
        p.error("Use a new output directory")
    import psutil
    if psutil.virtual_memory().available < 2 * 2**30:
        raise RuntimeError("At least 2 GiB available RAM required")
    started = time.monotonic()
    protocol = json.loads(a.protocol.read_text(encoding="utf-8"))
    for path, expected in protocol["implementation_sha256"].items():
        if sha(ROOT / path) != expected:
            raise ValueError(f"Implementation changed: {path}")
    run = json.loads((a.run_dir / "report.json").read_text(encoding="utf-8"))
    if sha(a.run_dir / "report.json") != protocol["source_run_report_sha256"]:
        raise ValueError("Frozen source run changed")
    records, receipts = load_records([ROOT / path for path in run["input_report_sha256"]])
    if receipts != {str(ROOT / path): digest for path, digest in run["input_report_sha256"].items()}:
        raise ValueError("Input receipts changed")
    sample_index = json.loads((a.run_dir / "sample_index.json").read_text(encoding="utf-8"))
    if [{k: v for k, v in r.items() if k != "features"} for r in records] != sample_index:
        raise ValueError("Frozen record order changed")
    folds = json.loads((a.run_dir / "folds.json").read_text(encoding="utf-8"))
    data = {k: np.stack([r["features"][k] for r in records]) for k in records[0]["features"]}
    inputs, current = pooled_inputs(data)
    np.testing.assert_allclose(current, data["targets"], atol=1e-6, rtol=0)
    a.output_dir.mkdir(parents=True)
    results = []
    for f in (f for f in folds if f["task"] in protocol["tasks"]):
        if psutil.virtual_memory().available < 1536 * 2**20:
            raise RuntimeError("RAM guard during fitting")
        tr, va, te = (np.array(f[k]) for k in ("train", "validation", "test"))
        series_parts = [{records[i]["series"] for i in ids} for ids in (tr, va, te)]
        if any(series_parts[i] & series_parts[j] for i in range(3) for j in range(i)):
            raise ValueError("Series leakage")
        if f["task"] == "G4" and {records[i]["map"] for i in tr.tolist() + va.tolist()} & {records[i]["map"] for i in te}:
            raise ValueError("Map leakage")
        truth, mask = data["targets"][te, 1:], data["target_mask"][te, 1:]
        predictions, selected, weights = {}, {}, {}
        for method, x in inputs.items():
            mean, std, (score, penalty, coef) = fit_ridge(x[tr, :-1], current[tr, :-1], data["targets"][tr, 1:],
                data["target_mask"][tr, 1:], (x[va, :-1], current[va, :-1], data["targets"][va, 1:],
                data["target_mask"][va, 1:]), protocol["ridge_penalties"])
            predictions[method] = linear_forecast(x[te, :-1], current[te, :-1], mean, std, coef)
            selected[method] = {"penalty": penalty, "validation_mse": score, "coefficients": int(coef.size)}
            weights.update({method + "_mean": mean, method + "_std": std, method + "_coef": coef})
        with np.load(a.run_dir / f["name"] / "predictions.npz", allow_pickle=False) as old:
            np.testing.assert_array_equal(old["test_indices"], te)
            np.testing.assert_array_equal(old["truth"], truth)
            np.testing.assert_array_equal(old["mask"], mask)
            delta = float(np.abs(old["ridge"] - predictions["ridge"]).max())
            np.testing.assert_allclose(old["ridge"], predictions["ridge"], atol=1e-6, rtol=0)
            predictions["persistence"] = old["persistence"].copy()
        totals = {m: [error_totals(y, t, w) for y, t, w in zip(pred, truth, mask)] for m, pred in predictions.items()}
        folder = a.output_dir / f["name"]
        folder.mkdir()
        np.savez_compressed(folder / "predictions.npz", test_indices=te, truth=truth, mask=mask, **predictions)
        np.savez_compressed(folder / "weights.npz", **weights)
        entry = {"name": f["name"], "task": f["task"], "test_indices": te.tolist(),
                 "selected": selected, "original_ridge_max_prediction_difference": delta, "totals": totals}
        results.append(entry)
        print(json.dumps({"completed": f["name"]}), flush=True)
    tasks = {}
    for task in protocol["tasks"]:
        selected = [r for r in results if r["task"] == task]
        ids = [i for r in selected for i in r["test_indices"]]
        assert len(ids) == len(set(ids)) == len(records)
        labels = [records[i]["series"] for i in ids]
        scores = {m: [t for r in selected for t in r["totals"][m]] for m in selected[0]["totals"]}
        tasks[task] = {"folds": len(selected), "test_rounds": len(ids), "methods": {}}
        for method, totals in scores.items():
            tasks[task]["methods"][method] = {"all": summarize(totals),
                "vs_persistence": paired_series_bootstrap(totals, scores["persistence"], labels),
                "vs_ridge": paired_series_bootstrap(totals, scores["ridge"], labels),
                "by_map": {m: summarize([v for v, i in zip(totals, ids) if records[i]["map"] == m]) for m in run["maps"]}}
    report = {"status": "completed_development_pooled_ridge_controls", "tasks": tasks,
              "protocol_sha256": sha(a.protocol), "input_report_sha256": receipts,
              "input_dimensions": {m: x.shape[-1] for m, x in inputs.items()},
              "folds": [{k: v for k, v in r.items() if k != "totals"} for r in results],
              "elapsed_seconds": time.monotonic() - started,
              "process_peak_RAM_MiB": psutil.Process().memory_info().peak_wset / 2**20,
              "uses_gpu": False, "limits": protocol["limits"]}
    write(a.output_dir / "report.json", report)
    print(json.dumps({"elapsed_seconds": report["elapsed_seconds"], "peak_RAM_MiB": report["process_peak_RAM_MiB"]}))


if __name__ == "__main__":
    main()
