"""Permutation-averaged full-input MLP controls on frozen development splits."""

import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
import copy
from itertools import permutations
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_evaluation_service import error_totals, paired_series_bootstrap, summarize
from app.services.ct_linear_service import linear_inputs
from app.services.ct_prediction_service import project_prediction
from scripts.confirm_ct_generalization import load_records, sha, write
from scripts.run_ct_generalization import CTModel


class PermutationMLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.register_buffer("permutations", torch.tensor(list(permutations(range(5)))))
        self.encoder = nn.Sequential(nn.Linear(70, 128), nn.GELU(), nn.Linear(128, 128),
                                     nn.GELU(), nn.Linear(128, 64), nn.LayerNorm(64))
        self.gru = nn.GRU(64, 64, batch_first=True)
        self.reconstruct = nn.Linear(64, 8)
        self.predict = nn.Linear(64, 8)
        nn.init.zeros_(self.predict.weight)
        nn.init.zeros_(self.predict.bias)

    def snapshot(self, nodes, edges, alive):
        p = self.permutations
        x = nodes * alive[..., None]
        d = edges * (alive[..., :, None] & alive[..., None, :])
        full = torch.cat([x[:, p].flatten(2), d[:, p[:, :, None], p[:, None, :]].flatten(2),
                          alive[:, p].float()], -1)
        return self.encoder(full).mean(1)

    def forward(self, b, temporal):
        nodes, edges, alive = (b[k] for k in ("nodes", "edges", "alive"))
        if nodes.ndim != 4 or nodes.shape[1:] != (5, 5, 8) or edges.shape != (*nodes.shape[:3], 5) or alive.shape != nodes.shape[:3] or alive.dtype != torch.bool:
            raise ValueError("Five-frame node/edge tensors and boolean live masks required")
        g = torch.stack([self.snapshot(nodes[:, k], edges[:, k], alive[:, k]) for k in range(5)], 1)
        h = self.gru(g)[0] if temporal else g
        changed = CTModel.observed(b)[:, :-1] + .1 * torch.tanh(self.predict(h[:, :-1]))
        occupancy = changed[..., :6].clamp_min(0)
        occupancy = occupancy / occupancy.sum(-1, keepdim=True).clamp_min(1e-8)
        prediction = torch.cat([occupancy, changed[..., 6:].clamp_min(0).sort(-1).values], -1)
        return CTModel.decode(self.reconstruct, g), prediction, h[:, -1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    if a.output_dir.exists():
        p.error("Use a new output directory")
    import psutil
    cfg = json.loads(a.protocol.read_text(encoding="utf-8"))
    if psutil.virtual_memory().available < 2 * 2**30:
        raise RuntimeError("RAM start guard")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required for this fixed recipe")
    torch.set_num_threads(1)
    torch.cuda.set_per_process_memory_fraction(.2)
    if torch.cuda.mem_get_info()[0] < 1024 * 2**20:
        raise RuntimeError("VRAM start guard")
    torch.backends.fp32_precision = "ieee"
    torch.backends.cuda.matmul.fp32_precision = "ieee"
    torch.backends.cudnn.fp32_precision = "ieee"
    torch.backends.cudnn.rnn.fp32_precision = "tf32"
    for path, expected in cfg["input_sha256"].items():
        if sha(ROOT / path) != expected:
            raise ValueError(f"Frozen input changed: {path}")
    source = json.loads((a.run_dir / "report.json").read_text(encoding="utf-8"))
    records, receipts = load_records([ROOT / path for path in source["input_report_sha256"]])
    if receipts != {str(ROOT / path): digest for path, digest in source["input_report_sha256"].items()}:
        raise ValueError("Source receipts changed")
    index = json.loads((a.run_dir / "sample_index.json").read_text(encoding="utf-8"))
    if [{k: v for k, v in r.items() if k != "features"} for r in records] != index:
        raise ValueError("Source ordering changed")
    data = {k: np.stack([r["features"][k] for r in records]) for k in records[0]["features"]}
    current = linear_inputs(data)[1]
    folds = [f for f in json.loads((a.run_dir / "folds.json").read_text(encoding="utf-8")) if f["task"] in cfg["tasks"]]
    training = cfg["training"]
    a.output_dir.mkdir(parents=True)
    report = {"status": "running", "protocol_sha256": sha(a.protocol), "folds": [], "tasks": {},
              "input_report_sha256": receipts, "parameter_count": sum(p.numel() for p in PermutationMLP().parameters()),
              "limits": cfg["limits"], "training": training}
    started = time.monotonic()
    all_results = []

    def resource_guard():
        if psutil.virtual_memory().available < 1536 * 2**20:
            raise RuntimeError("RAM guard: preserve partial output and stop")

    def tensor_batch(ids):
        return {k: torch.from_numpy(v[ids]).cuda() for k, v in data.items()}

    def predict(model, temporal, ids):
        outputs = []
        model.eval()
        with torch.no_grad():
            for start in range(0, len(ids), training["batch_size"]):
                chosen = ids[start:start + training["batch_size"]]
                outputs.append(model(tensor_batch(chosen), temporal)[1].cpu().numpy())
        return project_prediction(current[ids, :-1], np.concatenate(outputs))

    for fold in folds:
        tr, va, te = (np.asarray(fold[k]) for k in ("train", "validation", "test"))
        parts = [{records[i]["series"] for i in ids} for ids in (tr, va, te)]
        if any(parts[i] & parts[j] for i in range(3) for j in range(i)):
            raise ValueError("Series overlap")
        if fold["task"] == "G4" and {records[i]["map"] for i in tr.tolist() + va.tolist()} & {records[i]["map"] for i in te}:
            raise ValueError("Map leakage")
        folder = a.output_dir / fold["name"]
        folder.mkdir()
        truth, mask = data["targets"][te, 1:], data["target_mask"][te, 1:]
        with np.load(a.run_dir / fold["name"] / "predictions.npz", allow_pickle=False) as old:
            np.testing.assert_array_equal(old["test_indices"], te)
            np.testing.assert_array_equal(old["truth"], truth)
            np.testing.assert_array_equal(old["mask"], mask)
            predictions = {k: old[k].copy() for k in old.files if k in ["ridge", "persistence"] or k.startswith("static_") or k.startswith("gru_")}
        selected = []
        for seed in training["seeds"]:
            torch.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)
            initial = copy.deepcopy(PermutationMLP().state_dict())
            for temporal in (False, True):
                resource_guard()
                name = "perm_gru" if temporal else "perm_static"
                model = PermutationMLP().cuda()
                model.load_state_dict(initial)
                optimizer = torch.optim.AdamW(model.parameters(), lr=training["lr"], weight_decay=training["weight_decay"])
                best, best_state, epoch_chosen = float("inf"), None, None
                for epoch in range(training["epochs_max"]):
                    resource_guard()
                    model.train()
                    for start in range(0, len(tr), training["batch_size"]):
                        b = tensor_batch(tr[start:start + training["batch_size"]])
                        optimizer.zero_grad(set_to_none=True)
                        rec, pred, _ = model(b, temporal)
                        loss = (((rec - b["targets"]) ** 2) * b["target_mask"]).sum() / b["target_mask"].sum()
                        m = b["target_mask"][:, 1:]
                        loss = loss + (((pred - b["targets"][:, 1:]) ** 2) * m).sum() / m.sum()
                        if not torch.isfinite(loss):
                            raise RuntimeError("Nonfinite loss")
                        loss.backward()
                        torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
                        optimizer.step()
                    forecast = predict(model, temporal, va)
                    vm = data["target_mask"][va, 1:]
                    score = float((((forecast - data["targets"][va, 1:]) ** 2) * vm).sum() / vm.sum())
                    if score < best:
                        best, epoch_chosen = score, epoch + 1
                        best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                model.load_state_dict(best_state)
                predictions[f"{name}_{seed}"] = predict(model, temporal, te)
                path = folder / f"{name}_{seed}.pt"
                torch.save(best_state, path)
                selected.append({"method": name, "seed": seed, "selected_epoch": epoch_chosen,
                                 "validation_mse": best, "sha256": sha(path),
                                 "optimizer_steps": training["epochs_max"] * ((len(tr) + training["batch_size"] - 1) // training["batch_size"])})
                del model, optimizer, best_state
                torch.cuda.empty_cache()
                print(json.dumps({"fold": fold["name"], "method": name, "seed": seed,
                                  "elapsed_minutes": round((time.monotonic() - started) / 60, 2)}), flush=True)
        totals = {method: [error_totals(y, t, m) for y, t, m in zip(pred, truth, mask)] for method, pred in predictions.items()}
        for method in ("static", "gru", "perm_static", "perm_gru"):
            keys = [f"{method}_{seed}" for seed in training["seeds"]]
            if not all(k in totals for k in keys):
                raise ValueError("Missing seed predictions")
            totals[method + "_seed_mean"] = [{k: float(np.mean([totals[n][i][k] for n in keys])) for k in totals[keys[0]][i]} for i in range(len(te))]
        np.savez_compressed(folder / "predictions.npz", test_indices=te, truth=truth, mask=mask, **predictions)
        entry = {"name": fold["name"], "task": fold["task"], "test_indices": te.tolist(), "selected": selected}
        report["folds"].append(entry)
        all_results.append((entry, totals))
        report["elapsed_seconds"] = time.monotonic() - started
        write(a.output_dir / "report.json", report)
    methods = ["persistence", "ridge", "static_seed_mean", "gru_seed_mean", "perm_static_seed_mean", "perm_gru_seed_mean"]
    for task in cfg["tasks"]:
        chosen = [(f, t) for f, t in all_results if f["task"] == task]
        ids = [i for f, _ in chosen for i in f["test_indices"]]
        if len(ids) != len(set(ids)) or len(ids) != len(records):
            raise ValueError("Task coverage differs")
        series = [records[i]["series"] for i in ids]
        scores = {method: [row for _, totals in chosen for row in totals[method]] for method in methods}
        report["tasks"][task] = {"test_rounds": len(ids), "folds": len(chosen), "methods": {}}
        for method, totals in scores.items():
            report["tasks"][task]["methods"][method] = {"all": summarize(totals),
                "vs_persistence": paired_series_bootstrap(totals, scores["persistence"], series),
                "vs_ridge": paired_series_bootstrap(totals, scores["ridge"], series),
                "vs_static_graph": paired_series_bootstrap(totals, scores["static_seed_mean"], series),
                "vs_graph_gru": paired_series_bootstrap(totals, scores["gru_seed_mean"], series),
                "by_map": {m: summarize([r for r, i in zip(totals, ids) if records[i]["map"] == m]) for m in source["maps"]}}
    report.update(status="completed_development_information_control", elapsed_seconds=time.monotonic() - started,
                  peak_tensor_VRAM_MiB=torch.cuda.max_memory_allocated() / 2**20,
                  process_peak_RAM_MiB=psutil.Process().memory_info().peak_wset / 2**20)
    for path, expected in cfg["input_sha256"].items():
        if sha(ROOT / path) != expected:
            raise ValueError(f"Input changed during experiment: {path}")
    write(a.output_dir / "report.json", report)
    print(json.dumps({"complete": True, "minutes": report["elapsed_seconds"] / 60,
                      "peak_tensor_VRAM_MiB": report["peak_tensor_VRAM_MiB"]}), flush=True)


if __name__ == "__main__":
    main()
