"""Controlled development pilot on released Dust2 CT data; not a generalization benchmark."""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"


def sequence_loss(model, head, batch, trainer, temporal):
    import torch
    outputs = model(batch.node_features, batch.edge_distances, batch.context_features)
    reconstruction, _ = trainer.compute_losses(outputs, batch, 1.0, 0.5, 1.0)
    if not temporal:
        return reconstruction, reconstruction, None
    context = model.context_encoder(batch.context_features)
    sequence, _ = model.temporal_encoder(torch.cat([outputs["snapshot_embeddings"], context], -1))
    prediction = torch.softmax(head(sequence[:, :-1]), -1)
    future = torch.nn.functional.mse_loss(prediction, batch.area_targets[:, 1:])
    return reconstruction + future, reconstruction, future


def self_check(model, head, batch, trainer):
    import torch
    for module in (model, head):
        module.zero_grad(set_to_none=True)
    sequence_loss(model, head, batch, trainer, False)[0].backward()
    assert all(p.grad is None for p in model.temporal_encoder.parameters())
    assert all(p.grad is None for p in model.context_encoder.parameters())
    for module in (model, head):
        module.zero_grad(set_to_none=True)
    sequence_loss(model, head, batch, trainer, True)[0].backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all()
               for module in (model.temporal_encoder, model.context_encoder, head) for p in module.parameters())
    assert sum(p.grad.abs().sum().item() for p in model.temporal_encoder.parameters()) > 0
    with torch.no_grad():
        outputs = model(batch.node_features, batch.edge_distances, batch.context_features)
        x = torch.cat([outputs["snapshot_embeddings"], model.context_encoder(batch.context_features)], -1)
        h, _ = model.temporal_encoder(x)
        changed = x.clone()
        changed[:, -1] += 10
        other, _ = model.temporal_encoder(changed)
        assert torch.allclose(h[:, :-1], other[:, :-1], atol=1e-5, rtol=0), "future input leaked into prefix"
        permutation = torch.tensor([4, 2, 0, 3, 1], device=x.device)
        shuffled = model(batch.node_features[:, :, permutation],
                         batch.edge_distances[:, :, permutation][:, :, :, permutation], batch.context_features)
        assert torch.allclose(outputs["round_embedding"], shuffled["round_embedding"], atol=1e-5, rtol=0)
    model.zero_grad(set_to_none=True)
    head.zero_grad(set_to_none=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.output_dir.exists() or args.epochs < 1:
        parser.error("use a new output directory and positive epoch count")
    import psutil
    if psutil.virtual_memory().available < 2 * 2**30:
        raise RuntimeError("Less than 2 GiB system memory available")
    import numpy as np
    import torch
    torch.set_num_threads(1)
    assert torch.cuda.is_available(), "CUDA required for this pilot"
    torch.cuda.set_per_process_memory_fraction(.2)
    assert torch.cuda.mem_get_info()[0] > 1024 * 2**20, "Less than 1 GiB free VRAM"
    torch.backends.fp32_precision = "ieee"
    torch.backends.cudnn.fp32_precision = "ieee"
    torch.backends.cuda.matmul.fp32_precision = "ieee"
    torch.backends.cudnn.rnn.fp32_precision = "tf32"
    root = args.upstream_dir.resolve()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    assert commit == "1a7ac7cf817ba5ba476e94b3bee36046f4fef56c"
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()
    sys.path.insert(0, str(root / "scripts"))
    import train_tagnet as trainer
    data_dir = root / "data/processed/dust2_ct_5snap"
    splits, meta = trainer.load_split_data(data_dir)
    assert meta["snapshot_seconds"] == [10, 12, 15, 18, 20]
    match_sets = {n: set(s.match_ids) for n, s in splits.items()}
    for name, split in splits.items():
        for other in splits:
            if name != other:
                assert not match_sets[name] & match_sets[other], "match leakage"
        for tensor in (split.node_features, split.edge_distances, split.context_features, split.area_targets):
            assert torch.isfinite(tensor).all()
        assert split.node_features.shape[1:3] == (5, 5)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "status": "running", "scope": "development pilot, published Dust2 CT data only",
        "not_evaluated": ["series identity beyond published match IDs", "retrieval relevance", "T models", "unseen maps"],
        "seed": args.seed, "epochs": args.epochs, "upstream_commit": commit,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "data_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(data_dir.glob("*.parquet"))},
        "versions": {"torch": torch.__version__, "cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version()},
        "precision": {"matmul": "ieee", "rnn": "tf32"}, "models": {},
        "splits": {n: {"rounds": len(s.sample_ids), "match_ids": sorted(match_sets[n])} for n, s in splits.items()},
    }
    receipt = args.output_dir / "report.json"
    def save():
        receipt.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    save()

    def handcrafted(split):
        alive = (split.node_features[..., -2] > 0).float().mean(-1, keepdim=True)
        distances = split.distance_targets
        return torch.cat([split.area_targets, alive, distances.mean(-1, keepdim=True),
                          distances.max(-1, keepdim=True).values], -1).flatten(1).numpy()
    features = {n: handcrafted(s) for n, s in splits.items()}
    mean, std = features["train"].mean(0), features["train"].std(0).clip(1e-8)
    scaled = {n: (x - mean) / std for n, x in features.items()}
    np.savez(args.output_dir / "b0_features.npz", **scaled, mean=mean, std=std)
    b0 = {}
    for name in ("val", "test"):
        distances = np.linalg.norm(scaled[name][:, None] - scaled["train"][None, :], axis=-1)
        order = np.argsort(distances, axis=1)[:, :5]
        b0[name] = [{"query": sid, "candidates": [splits["train"].sample_ids[i] for i in row]}
                    for sid, row in zip(splits[name].sample_ids, order)]
    (args.output_dir / "b0_candidates.json").write_text(json.dumps(b0, indent=2) + "\n")

    trainer.set_seed(args.seed)
    initial = trainer.MethodCModel(meta["node_feat_dim"], meta["context_dim"], meta["place_dim"], gat_layers=3)
    initial_head = torch.nn.Linear(64, 4)
    for temporal in (False, True):
        label = "snapshot_only" if not temporal else "next_area_prediction"
        model, head = copy.deepcopy(initial).cuda(), copy.deepcopy(initial_head).cuda()
        self_check(model, head, trainer.move_split_to_device(splits["train"].subset([0, 1]), "cuda"), trainer)
        train_data = splits["train"]
        optimizer = torch.optim.AdamW(list(model.parameters()) + list(head.parameters()), lr=1e-3, weight_decay=1e-4)
        best, best_state, history = float("inf"), None, []
        start_time = time.perf_counter()
        torch.cuda.reset_peak_memory_stats()
        def evaluate(split):
            model.eval(); head.eval()
            total = np.zeros(3)
            with torch.no_grad():
                for start in range(0, len(split.sample_ids), 64):
                    batch = trainer.move_split_to_device(split.subset(list(range(start, min(start + 64, len(split.sample_ids))))), "cuda")
                    losses = sequence_loss(model, head, batch, trainer, temporal)
                    total += np.array([x.item() if x is not None else 0 for x in losses]) * len(batch.sample_ids)
            return (total / len(split.sample_ids)).tolist()
        for epoch in range(args.epochs):
            if psutil.virtual_memory().available < 1536 * 2**20:
                report["status"] = "resource_stop"; save()
                raise RuntimeError("RAM below 1.5 GiB; partial progress saved")
            model.train(); head.train()
            for start in range(0, len(train_data.sample_ids), 64):
                batch = trainer.move_split_to_device(train_data.subset(list(range(start, min(start + 64, len(train_data.sample_ids))))), "cuda")
                optimizer.zero_grad(set_to_none=True)
                loss = sequence_loss(model, head, batch, trainer, temporal)[0]
                assert torch.isfinite(loss), "non-finite training loss"
                loss.backward()
                torch.nn.utils.clip_grad_norm_(list(model.parameters()) + list(head.parameters()), 5)
                optimizer.step()
            validation = evaluate(splits["val"])
            history.append({"epoch": epoch + 1, "val_objective": validation[0], "val_reconstruction": validation[1],
                            "val_next_area_mse": validation[2] if temporal else None})
            if validation[0] < best:
                best = validation[0]
                best_state = ({k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
                              {k: v.detach().cpu().clone() for k, v in head.state_dict().items()}, epoch + 1)
            if (epoch + 1) % 10 == 0:
                print(json.dumps({"model": label, **history[-1]}), flush=True)
        model.load_state_dict(best_state[0]); head.load_state_dict(best_state[1])
        test = evaluate(splits["test"])
        report["models"][label] = {"selected_epoch": best_state[2], "selection": "minimum validation objective",
            "test_reconstruction": test[1], "test_next_area_mse": test[2] if temporal else None,
            "test_persistence_area_mse": float(torch.nn.functional.mse_loss(splits["test"].area_targets[:, :-1], splits["test"].area_targets[:, 1:])),
            "seconds": time.perf_counter() - start_time, "history": history,
            "peak_allocated_VRAM_MiB": torch.cuda.max_memory_allocated() / 2**20,
            "peak_reserved_VRAM_MiB": torch.cuda.max_memory_reserved() / 2**20}
        torch.save({"model_state_dict": best_state[0], "next_area_head": best_state[1], "metadata": meta,
                    "precision": report["precision"], "seed": args.seed}, args.output_dir / f"{label}.pt")
        save()
        del model, head, optimizer, best_state
        torch.cuda.empty_cache()
    report["status"] = "completed_development_pilot"
    report["self_checks"] = ["gradient boundary", "prefix causality", "player permutation", "match split disjointness", "finite input/output"]
    info = psutil.Process().memory_info()
    report["process_peak_RAM_MiB"] = getattr(info, "peak_wset", info.rss) / 2**20
    save()
    print(json.dumps({"status": report["status"], "models": {n: {k: v for k, v in r.items() if k != "history"}
                      for n, r in report["models"].items()}}, indent=2), flush=True)


if __name__ == "__main__":
    main()
