"""CT-only common-feature development transfer probe, with static and recurrent controls."""

import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import psutil
import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_feature_service import FEATURE_VERSION, feature_sequence


class CTModel(nn.Module):
    def __init__(self, trainer, residual=False):
        super().__init__()
        self.graph = trainer.SnapshotEncoder(8, 64, num_layers=3)
        self.gru = nn.GRU(64, 64, batch_first=True)
        self.reconstruct = nn.Linear(64, 8)
        self.predict = nn.Linear(64, 8)
        self.residual = residual
        if residual:
            nn.init.zeros_(self.predict.weight)
            nn.init.zeros_(self.predict.bias)

    @staticmethod
    def observed(b):
        alive = b["alive"]
        occupancy = torch.cat([(b["nodes"][..., :5] * alive[..., None]).sum(2) / 5,
                               (~alive).sum(2, keepdim=True) / 5], -1)
        pairs = torch.triu(alive[..., :, None] & alive[..., None, :], diagonal=1)
        distances = b["edges"] * pairs
        statistics = torch.stack([distances.sum((2, 3)) / pairs.sum((2, 3)).clamp_min(1),
                                  distances.amax((2, 3))], -1)
        return torch.cat([occupancy, statistics], -1)

    @staticmethod
    def decode(head, x):
        p = head(x)
        return torch.cat([torch.softmax(p[..., :6], -1), torch.nn.functional.softplus(p[..., 6:])], -1)

    def forward(self, b, temporal):
        sequence = []
        for k in range(5):
            x, distance, alive = b["nodes"][:, k], b["edges"][:, k], b["alive"][:, k]
            for layer, ffn, norm in zip(self.graph.layers, self.graph.ffns, self.graph.norms):
                logits = layer.query(x) @ layer.key(x).transpose(-1, -2) / 8
                logits = logits + layer.edge_bias(distance.unsqueeze(-1)).squeeze(-1)
                logits = torch.nn.functional.leaky_relu(logits, .2).masked_fill(~alive[:, None, :], -torch.inf)
                x = layer.norm(torch.softmax(logits, -1) @ layer.value(x))
                x = norm(x + ffn(x))
            sequence.append((x * alive[..., None]).sum(1) / alive.sum(1, keepdim=True))
        g = torch.stack(sequence, 1)
        h = self.gru(g)[0] if temporal else g
        if self.residual:
            changed = self.observed(b)[:, :-1] + .1 * torch.tanh(self.predict(h[:, :-1]))
            occupancy = changed[..., :6].clamp_min(0)
            occupancy = occupancy / occupancy.sum(-1, keepdim=True).clamp_min(1e-8)
            prediction = torch.cat([occupancy, changed[..., 6:].clamp_min(0).sort(-1).values], -1)
        else:
            prediction = self.decode(self.predict, h[:, :-1])
        return self.decode(self.reconstruct, g), prediction, h[:, -1]


def arrays(records):
    return {k: np.stack([r["features"][k] for r in records]) for k in records[0]["features"]}


def batch(data, start, stop):
    return {k: torch.from_numpy(v[start:stop]).cuda() for k, v in data.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--upstream-dir", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 42])
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--residual", action="store_true", help="Predict bounded changes to current observable state")
    args = ap.parse_args()
    if args.output_dir.exists() or args.epochs < 1 or len(set(args.seeds)) != len(args.seeds):
        ap.error("new output directory, positive epochs and distinct seeds required")
    assert psutil.virtual_memory().available > 2 * 2**30
    assert torch.cuda.is_available()
    torch.set_num_threads(1)
    torch.cuda.set_per_process_memory_fraction(.2)
    assert torch.cuda.mem_get_info()[0] > 1024 * 2**20
    torch.backends.fp32_precision = "ieee"
    torch.backends.cudnn.fp32_precision = "ieee"
    torch.backends.cuda.matmul.fp32_precision = "ieee"
    torch.backends.cudnn.rnn.fp32_precision = "tf32"
    upstream = args.upstream_dir.resolve()
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip() == "1a7ac7cf817ba5ba476e94b3bee36046f4fef56c"
    sys.path.insert(0, str(upstream / "scripts"))
    import train_tagnet as trainer
    folder = upstream / "data/processed/dust2_ct_5snap"
    nodes = pd.read_parquet(folder / "ct_snapshot_nodes.parquet")
    groups = {"train": [], "val": [], "test": []}
    skipped = Counter()
    for sid, frame in nodes.groupby("sample_id", sort=True):
        snapshots = [{"second": int(second), "players": [
            {"steamid": r.player_id, "position": [r.X, r.Y, r.Z], "health": r.health,
             "equipment_value": r.current_equip_value, "place": r.place}
            for r in rows.sort_values("player_slot").itertuples()]}
            for second, rows in frame.groupby("second", sort=True)]
        try:
            f = feature_sequence(snapshots)
        except ValueError as e:
            skipped[f"Dust2: {e}"] += 1
            continue
        groups[frame.iloc[0]["split"]].append({"id": sid, "series": frame.iloc[0]["match_id"], "features": f})
    sources = [ROOT / f"output/tagnet/{name}/snapshots.json" for name in (
        "mirage_opening_full_v1", "anubis_opening_full_v1", "inferno_opening_full_v1",
        "2396940_map1_opening_v1", "2396940_map2_opening_v1")]
    for source in sources:
        d = json.loads(source.read_text())
        name = d["map_name"]
        series = "2396940" if "2396940" in str(source) else "furia_falcons_existing_local"
        for r in d["rounds"]:
            if r["side"] != "CT" or r["status"] != "ok":
                continue
            try:
                f = feature_sequence(r["snapshots"])
            except ValueError as e:
                skipped[f"{name}: {e}"] += 1
                continue
            groups.setdefault(name, []).append({"id": f"{d['source_demo_sha256']}:{r['round_number']}:CT", "series": series, "features": f})
    for a in ("train", "val", "test"):
        for b in ("train", "val", "test"):
            if a != b:
                assert not {r["series"] for r in groups[a]} & {r["series"] for r in groups[b]}
    data = {n: arrays(r) for n, r in groups.items()}
    for values in data.values():
        assert all(np.isfinite(v).all() for v in values.values())
    args.output_dir.mkdir(parents=True, exist_ok=False)
    report = {"status": "running", "feature_version": FEATURE_VERSION, "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "seeds": args.seeds, "epochs": args.epochs, "residual": args.residual, "precision": {"matmul": "ieee", "rnn": "tf32"},
        "scope": "CT development transfer probe; only Dust2 training/validation; known target samples, not blind",
        "limitations": ["no audited retrieval labels", "only one Ancient series", "source series identity beyond match IDs unknown", "tick/pause calibration pending", "coarse regions, no navigation geometry"],
        "sources": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "groups": {n: {"rounds": len(r), "series": sorted({x["series"] for x in r})} for n, r in groups.items()},
        "skipped": dict(skipped), "runs": [], "persistence": {}}
    def metrics(pred, target, mask):
        squared = ((pred - target) ** 2) * mask
        num = squared.sum((0, 1)); den = mask.sum((0, 1))
        return {"mse": float(num.sum() / den.sum()), "occupancy_mse": float(num[:6].sum() / den[:6].sum()),
                "distance_mse": float(num[6:].sum() / max(den[6:].sum(), 1))}
    for n, d in data.items():
        report["persistence"][n] = metrics(d["targets"][:, :-1], d["targets"][:, 1:], d["target_mask"][:, 1:])
    receipt = args.output_dir / "report.json"
    def save():
        receipt.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    save()
    for seed in args.seeds:
        trainer.set_seed(seed)
        initial = CTModel(trainer, residual=args.residual)
        for temporal in (False, True):
            name = "prefix_gru" if temporal else "static_snapshot"
            m = copy.deepcopy(initial).cuda()
            opt = torch.optim.AdamW(m.parameters(), lr=.001, weight_decay=.0001)
            def losses(b):
                rec, pred, _ = m(b, temporal)
                a = (((rec - b["targets"]) ** 2) * b["target_mask"]).sum() / b["target_mask"].sum()
                mask = b["target_mask"][:, 1:]
                return a + (((pred - b["targets"][:, 1:]) ** 2) * mask).sum() / mask.sum()
            def evaluate(d, embeddings=False):
                m.eval(); predictions, representations = [], []
                with torch.no_grad():
                    for start in range(0, len(d["nodes"]), 64):
                        _, pred, z = m(batch(d, start, start + 64), temporal)
                        predictions.append(pred.cpu().numpy()); representations.append(z.cpu().numpy())
                result = metrics(np.concatenate(predictions), d["targets"][:, 1:], d["target_mask"][:, 1:])
                return (result, np.concatenate(representations)) if embeddings else result
            b = batch(data["train"], 0, 2)
            with torch.no_grad():
                rec, prediction, embedding = m(b, temporal)
                assert torch.allclose(m.observed(b), b["targets"], atol=1e-6, rtol=0)
                if args.residual:
                    assert torch.allclose(prediction, b["targets"][:, :-1], atol=1e-6, rtol=0)
                permutation = torch.tensor([4, 2, 0, 3, 1], device="cuda")
                permuted = dict(b)
                permuted["nodes"] = b["nodes"][:, :, permutation]
                permuted["alive"] = b["alive"][:, :, permutation]
                permuted["edges"] = b["edges"][:, :, permutation][:, :, :, permutation]
                assert torch.allclose(m(permuted, temporal)[2], embedding, atol=1e-5, rtol=0)
                future = {k: v.clone() for k, v in b.items()}
                future["nodes"][:, -1] *= 0
                future["edges"][:, -1] *= 0
                assert torch.allclose(m(future, temporal)[1], prediction, atol=1e-5, rtol=0)
            losses(b).backward()
            assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in m.graph.parameters())
            assert (any(p.grad is not None for p in m.gru.parameters())) == temporal
            m.zero_grad(set_to_none=True)
            best, state, chosen = float("inf"), None, None
            torch.cuda.reset_peak_memory_stats()
            for epoch in range(args.epochs):
                if psutil.virtual_memory().available < 1536 * 2**20:
                    report["status"] = "resource_stop"; save(); raise RuntimeError("RAM guard")
                m.train()
                for start in range(0, len(data["train"]["nodes"]), 64):
                    opt.zero_grad(set_to_none=True)
                    loss = losses(batch(data["train"], start, start + 64))
                    assert torch.isfinite(loss)
                    loss.backward(); nn.utils.clip_grad_norm_(m.parameters(), 5); opt.step()
                score = evaluate(data["val"])["mse"]
                if score < best:
                    best = score; chosen = epoch + 1
                    state = {k: v.detach().cpu().clone() for k, v in m.state_dict().items()}
            m.load_state_dict(state)
            results, embeddings = {}, {}
            for n, d in data.items():
                results[n], embeddings[n] = evaluate(d, True)
            record = {"seed": seed, "model": name, "selected_epoch": chosen, "metrics": results,
                      "peak_allocated_VRAM_MiB": torch.cuda.max_memory_allocated() / 2**20}
            report["runs"].append(record); save()
            torch.save({"model_state_dict": state, "feature_version": FEATURE_VERSION, "seed": seed,
                        "temporal": temporal, "residual": args.residual, "precision": report["precision"]}, args.output_dir / f"{name}_{seed}.pt")
            np.savez(args.output_dir / f"{name}_{seed}_embeddings.npz", **embeddings)
            candidates = {}
            for n in groups:
                if n in ("train", "val", "test"):
                    continue
                order = np.argsort(np.linalg.norm(embeddings[n][:, None] - embeddings["train"][None, :], axis=-1), axis=1)[:, :5]
                candidates[n] = [{"query": r["id"], "history": [groups["train"][i]["id"] for i in row]}
                                 for r, row in zip(groups[n], order)]
            (args.output_dir / f"{name}_{seed}_candidates.json").write_text(json.dumps(candidates, indent=2) + "\n")
            print(json.dumps({"seed": seed, "model": name, "metrics": {n: r["mse"] for n, r in results.items()}}), flush=True)
            del m, opt, state
            torch.cuda.empty_cache()
    report["status"] = "completed_development_transfer_probe"
    report["process_peak_RAM_MiB"] = psutil.Process().memory_info().peak_wset / 2**20
    save()


if __name__ == "__main__":
    main()
