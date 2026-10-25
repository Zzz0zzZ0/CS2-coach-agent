"""Common-window reconstruction controls; reconstruction is not tactical relevance."""

import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
from itertools import permutations
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_deployment_service import DEPLOYMENT_VERSION
from scripts.confirm_ct_generalization import sha, write

GROUPS = ("survival", "region", "resources", "height", "ground", "motion", "pairs")
CONDITIONS = {
    "mlp_static": ("mlp", False, 15, 3),
    "mlp_gru": ("mlp", True, 15, 3),
    "graph_static": ("graph", False, 15, 3),
    "graph_gru": ("graph", True, 15, 3),
    "graph_gru_no_motion": ("graph", True, 13, 3),
    "graph_gru_common": ("graph", True, 8, 1),
}


class ReconstructionModel(nn.Module):
    def __init__(self, condition):
        super().__init__()
        self.family, temporal, self.node_dim, self.edge_dim = CONDITIONS[condition]
        self.register_buffer("permutations", torch.tensor(list(permutations(range(5)))))
        self.register_buffer("pair_indices", torch.triu_indices(5, 5, offset=1))
        width = 2 * self.node_dim + 1
        if self.family == "mlp":
            self.encoder = nn.Sequential(nn.Linear(5 * width + 25 * self.edge_dim, 128),
                                         nn.GELU(), nn.Linear(128, 64), nn.LayerNorm(64))
        else:
            self.encoder = nn.Linear(width, 64)
            self.layers = nn.ModuleList([nn.ModuleDict({
                "query": nn.Linear(64, 64), "key": nn.Linear(64, 64),
                "value": nn.Linear(64, 64), "edge": nn.Linear(self.edge_dim, 1),
                "norm": nn.LayerNorm(64),
                "ffn": nn.Sequential(nn.Linear(64, 128), nn.GELU(), nn.Linear(128, 64)),
                "ffn_norm": nn.LayerNorm(64),
            }) for _ in range(2)])
        self.decoder = nn.Sequential(nn.Linear(64, 128), nn.GELU(), nn.Linear(128, 525))
        self.gru = nn.GRU(64, 64, batch_first=True) if temporal else None

    def encode(self, batch):
        alive = batch["node_mask"]
        mask = batch["node_feature_mask"][..., :self.node_dim] & alive[..., None]
        x = torch.cat([batch["nodes"][..., :self.node_dim] * mask, mask.float(), alive[..., None].float()], -1)
        edge = batch["edges"][..., :self.edge_dim] * batch["pair_mask"][..., None]
        n = len(x)
        x, edge, alive = x.flatten(0, 1), edge.flatten(0, 1), alive.flatten(0, 1)
        if self.family == "mlp":
            p = self.permutations
            joint = torch.cat([x[:, p].flatten(2), edge[:, p[:, :, None], p[:, None, :]].flatten(2)], -1)
            tracks = self.encoder(joint).reshape(n, 5, len(p), 64).transpose(1, 2)
        else:
            x = self.encoder(x) * alive[..., None]
            for layer in self.layers:
                logits = layer["query"](x) @ layer["key"](x).transpose(-1, -2) / 8
                logits = logits + layer["edge"](edge).squeeze(-1)
                attention = logits.masked_fill(~alive[:, None, :], -torch.inf).softmax(-1)
                x = layer["norm"](x + attention @ layer["value"](x))
                x = layer["ffn_norm"](x + layer["ffn"](x)) * alive[..., None]
            tracks = x.reshape(n, 5, 5, 64).transpose(1, 2)
        # Pool after temporal encoding so only a consistent whole-window relabeling is invariant.
        h = self.gru(tracks.flatten(0, 1))[0].reshape(n, -1, 5, 64).mean(1) if self.gru is not None else tracks.mean(1)
        z = h[:, -1] if self.gru is not None else h.mean(1)
        return z, h

    def forward(self, batch):
        z, _ = self.encode(batch)
        decoded = self.decoder(z)
        nodes = decoded[:, :375].reshape(-1, 5, 5, 15)
        pairs = decoded[:, 375:].reshape(-1, 5, 10, 3)
        edges = pairs.new_zeros((len(z), 5, 5, 5, 3))
        i, j = self.pair_indices
        edges[:, :, i, j] = pairs
        edges[:, :, j, i] = pairs
        return {"nodes": nodes, "edges": edges}, z


def reconstruction_loss(prediction, target, player_permutations):
    """Choose one endpoint-consistent player matching across the entire window."""
    p = player_permutations
    nodes = target["nodes"][:, :, p].transpose(1, 2)
    alive = target["node_mask"][:, :, p].transpose(1, 2)
    mask = target["node_feature_mask"][:, :, p].transpose(1, 2)
    edges = target["edges"][:, :, p[:, :, None], p[:, None, :]].transpose(1, 2)
    pairs = target["pair_mask"][:, :, p[:, :, None], p[:, None, :]].transpose(1, 2).triu(1)
    estimate = prediction["nodes"][:, None]

    def average(values, valid):
        valid = valid.expand_as(values)
        axes = tuple(range(2, values.ndim))
        return (values * valid).sum(axes) / valid.sum(axes).clamp_min(1)

    def mse(columns):
        return average((estimate[..., columns] - nodes[..., columns]).square(), mask[..., columns])

    survival = F.binary_cross_entropy_with_logits(estimate[..., 7].expand_as(alive), alive.float(), reduction="none").mean((-1, -2))
    region = average(-(estimate[..., :5].log_softmax(-1) * nodes[..., :5]).sum(-1), alive)
    ground = average(-(estimate[..., 10:13].log_softmax(-1) * nodes[..., 10:13]).sum(-1), alive)
    pair_loss = average((prediction["edges"][:, None] - edges).square(), pairs[..., None])
    components = torch.stack([survival, region, mse(slice(5, 7)), mse(slice(8, 10)),
                              ground, mse(slice(13, 15)), pair_loss], -1)
    assignment = components.mean(-1).argmin(1)
    selected = components[torch.arange(len(nodes), device=nodes.device), assignment]
    return selected.mean(-1), selected


def load_inputs(input_dir, run_dir):
    report = json.loads((input_dir / "report.json").read_text(encoding="utf-8"))
    if report["feature_version"] != DEPLOYMENT_VERSION:
        raise ValueError("Deployment input version mismatch")
    for group in ("source_sha256", "raw_input_sha256"):
        for name, expected in report[group].items():
            if sha(ROOT / name) != expected:
                raise ValueError(f"Input source changed: {name}")
    for name, expected in report["output_sha256"].items():
        if sha(input_dir / name) != expected:
            raise ValueError(f"Export changed: {name}")
    index = json.loads((input_dir / "sample_index.json").read_text(encoding="utf-8"))
    if index != json.loads((run_dir / "sample_index.json").read_text(encoding="utf-8")):
        raise ValueError("Cohort order changed")
    order_by_id = {}
    for name in report["raw_input_sha256"]:
        if name.endswith("_snapshots.json"):
            doc = json.loads((ROOT / name).read_text(encoding="utf-8"))
            for row in doc["rounds"]:
                if row["side"] == "CT":
                    order_by_id[f"{doc['source_demo_sha256']}:{row['round_number']}:CT"] = [
                        [str(p["steamid"]) for p in frame["players"]] for frame in row["snapshots"]]
    for row in index:
        ids = order_by_id[row["id"]]
        # shortcut: this export has stable slots; changing frame order requires an identity-aligned re-export.
        if len(ids) != 5 or len(set(ids[0])) != 5 or any(current != ids[0] for current in ids):
            raise ValueError("Re-export targets with consistent player slots before joint-window matching")
    with np.load(input_dir / "features.npz", allow_pickle=False) as data:
        arrays = {key: data[key].copy() for key in ("nodes", "edges", "node_mask", "node_feature_mask", "pair_mask")}
    validate_inputs(arrays)
    return arrays, index


def validate_inputs(data):
    n = len(data["nodes"])
    for key, shape in {"nodes": (n, 5, 5, 15), "edges": (n, 5, 5, 5, 3),
                       "node_mask": (n, 5, 5), "node_feature_mask": (n, 5, 5, 15), "pair_mask": (n, 5, 5, 5)}.items():
        if data[key].shape != shape or not np.isfinite(data[key]).all():
            raise ValueError(f"Invalid shape or values: {key}")
        if "mask" in key and data[key].dtype != np.bool_:
            raise ValueError(f"Boolean mask required: {key}")
    alive = data["node_mask"]
    if n == 0 or not alive.any(-1).all() or not np.array_equal(data["nodes"][..., 7], alive):
        raise ValueError("Alive observations required in each frame")
    pairs = alive[..., :, None] & alive[..., None, :] & ~np.eye(5, dtype=bool)
    if not np.array_equal(data["pair_mask"], pairs) or (data["node_feature_mask"] & ~alive[..., None]).any():
        raise ValueError("Mask alignment mismatch")
    if data["nodes"][~alive].any() or data["edges"][~pairs].any():
        raise ValueError("Dead node/pair values must be zero")
    motion = np.zeros_like(alive)
    motion[:, 1:] = alive[:, 1:] & alive[:, :-1]
    if not np.array_equal(data["node_feature_mask"][..., 13:], np.repeat(motion[..., None], 2, -1)):
        raise ValueError("Motion validity mismatch")


def validate_fold(fold, index):
    parts = [fold[key] for key in ("train", "validation", "test")]
    for part in parts:
        if not part or len(part) != len(set(part)) or any(type(i) is not int or not 0 <= i < len(index) for i in part):
            raise ValueError("Nonempty distinct in-range fold indices required")
    series = [{index[i]["series"] for i in part} for part in parts]
    if any(series[i] & series[j] for i in range(3) for j in range(i)):
        raise ValueError("Series overlap")
    if fold["task"] == "G4" and {index[i]["map"] for i in parts[0] + parts[1]} & {index[i]["map"] for i in parts[2]}:
        raise ValueError("Map leakage")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "input-dir", "run-dir", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for key, value in vars(args).items():
        resolved = value.resolve()
        if not resolved.is_relative_to(ROOT):
            parser.error("Keep experiment paths inside this workspace")
        setattr(args, key, resolved)
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    cfg = json.loads(args.protocol.read_text(encoding="utf-8"))
    if cfg["scope"] not in ("source_only_resource_pilot", "development_matrix"):
        raise ValueError("Explicit experiment scope required")
    for name, expected in cfg["input_sha256"].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f"Protocol input changed: {name}")
    training = cfg["training"]
    if training["epochs_max"] < 1 or training["batch_size"] < 1 or not cfg["conditions"] or not training["seeds"]:
        raise ValueError("Positive training budget required")
    if len(set(cfg["conditions"])) != len(cfg["conditions"]) or set(cfg["conditions"]) - CONDITIONS.keys():
        raise ValueError("Distinct supported conditions required")
    if len(set(training["seeds"])) != len(training["seeds"]):
        raise ValueError("Distinct seeds required")
    import psutil
    if psutil.virtual_memory().available < 2 * 2**30 or psutil.disk_usage(str(ROOT)).free < 2 * 2**30:
        raise RuntimeError("Need 2 GiB available RAM and disk")
    if not torch.cuda.is_available() or torch.cuda.mem_get_info()[0] < 1024 * 2**20:
        raise RuntimeError("Need CUDA and 1 GiB free VRAM")
    torch.set_num_threads(1)
    torch.cuda.set_per_process_memory_fraction(.2)
    torch.backends.fp32_precision = "ieee"
    torch.backends.cuda.matmul.fp32_precision = "ieee"
    torch.backends.cudnn.fp32_precision = "ieee"
    torch.backends.cudnn.rnn.fp32_precision = "tf32"
    arrays, index = load_inputs(args.input_dir, args.run_dir)
    all_folds = {fold["name"]: fold for fold in json.loads((args.run_dir / "folds.json").read_text(encoding="utf-8"))}
    if not cfg["folds"] or len(set(cfg["folds"])) != len(cfg["folds"]) or set(cfg["folds"]) - all_folds.keys():
        raise ValueError("Distinct existing folds required")
    folds = [all_folds[name] for name in cfg["folds"]]
    for fold in folds:
        validate_fold(fold, index)
    data = {key: torch.from_numpy(value).cuda() for key, value in arrays.items()}
    args.output_dir.mkdir(parents=True)
    started = time.monotonic()
    report = {"status": "running", "scope": cfg["scope"], "protocol_sha256": sha(args.protocol),
              "input_sha256": cfg["input_sha256"], "feature_version": DEPLOYMENT_VERSION,
              "training": training, "loss_groups": GROUPS, "models": [],
              "planned_models": len(folds) * len(cfg["conditions"]) * len(training["seeds"]),
              "target_alignment": "All indexed raw windows checked for consistent identity slots across five frames; IDs never fed to encoder",
              "versions": {"torch": torch.__version__, "cuda": torch.version.cuda, "numpy": np.__version__},
              "device": torch.cuda.get_device_name(0), "precision": {"matmul": "ieee", "rnn": "tf32"},
              "limits": ["Development reconstruction only, not tactical relevance or independent generalization.",
                         "Raw regression outputs do not enforce realizable navigation or full geometric constraints.",
                         "Direct retrieval controls and pattern analysis are separate evaluations."],
              "human_verification": {"status": "pending", "verified_by": None}}

    def save():
        report["elapsed_seconds"] = time.monotonic() - started
        report["process_peak_RAM_MiB"] = psutil.Process().memory_info().peak_wset / 2**20
        write(args.output_dir / "report.json", report)

    def guard():
        if psutil.virtual_memory().available < 1536 * 2**20 or time.monotonic() - started > cfg["max_seconds"]:
            raise RuntimeError("RAM/time guard: partial progress preserved")

    def batch(ids):
        return {key: value[ids] for key, value in data.items()}

    def evaluate(model, ids):
        model.eval()
        losses, components, embeddings = [], [], []
        with torch.no_grad():
            for start in range(0, len(ids), training["batch_size"]):
                b = batch(ids[start:start + training["batch_size"]])
                prediction, z = model(b)
                loss, detail = reconstruction_loss(prediction, b, model.permutations)
                losses.append(loss.cpu().numpy())
                components.append(detail.cpu().numpy())
                embeddings.append(z.cpu().numpy())
        return np.concatenate(losses), np.concatenate(components), np.concatenate(embeddings)

    save()
    try:
        for fold in folds:
            tr, va, te = (np.asarray(fold[key]) for key in ("train", "validation", "test"))
            folder = args.output_dir / fold["name"]
            folder.mkdir()
            for seed in training["seeds"]:
                for condition in cfg["conditions"]:
                    guard()
                    torch.manual_seed(seed)
                    torch.cuda.manual_seed_all(seed)
                    model = ReconstructionModel(condition).cuda()
                    optimizer = torch.optim.AdamW(model.parameters(), lr=training["lr"], weight_decay=training["weight_decay"])
                    generator = np.random.default_rng(seed)
                    initial = evaluate(model, va)[0].mean()
                    entry = {"fold": fold["name"], "condition": condition, "seed": seed,
                             "parameter_count": sum(p.numel() for p in model.parameters()),
                             "train_windows": len(tr), "validation_windows": len(va),
                             "initial_validation_loss": float(initial), "history": []}
                    report["models"].append(entry)
                    model_started = time.monotonic()
                    torch.cuda.reset_peak_memory_stats()
                    best, best_state = float("inf"), None
                    for epoch in range(training["epochs_max"]):
                        guard()
                        model.train()
                        order = generator.permutation(tr)
                        total = 0.0
                        for start in range(0, len(tr), training["batch_size"]):
                            guard()
                            b = batch(order[start:start + training["batch_size"]])
                            optimizer.zero_grad(set_to_none=True)
                            prediction, _ = model(b)
                            loss = reconstruction_loss(prediction, b, model.permutations)[0].mean()
                            if not torch.isfinite(loss):
                                raise RuntimeError("Nonfinite training loss")
                            loss.backward()
                            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), training["gradient_clip"])
                            if not torch.isfinite(norm):
                                raise RuntimeError("Nonfinite gradient")
                            optimizer.step()
                            total += loss.item() * len(b["nodes"])
                        val_loss, details, _ = evaluate(model, va)
                        # Equal-series validation; rounds and seeds are not independent series.
                        score = float(np.mean([val_loss[[j for j, i in enumerate(va) if index[i]["series"] == s]].mean()
                                               for s in sorted({index[i]["series"] for i in va})]))
                        if not np.isfinite(score):
                            raise RuntimeError("Nonfinite validation loss")
                        entry["history"].append({"epoch": epoch + 1, "training_loss": total / len(tr), "validation_loss": score})
                        if score < best:
                            best = score
                            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
                            entry.update(selected_epoch=epoch + 1, validation_loss=best,
                                         validation_components=dict(zip(GROUPS, details.mean(0).tolist())))
                        if (epoch + 1) % 10 == 0:
                            save()
                            print(json.dumps({"fold": fold["name"], "condition": condition, "seed": seed,
                                              **entry["history"][-1]}), flush=True)
                    model.load_state_dict(best_state)
                    checkpoint = folder / f"{condition}_{seed}.pt"
                    torch.save({"condition": condition, "state_dict": best_state, "feature_version": DEPLOYMENT_VERSION,
                                "protocol_sha256": sha(args.protocol), "selected_epoch": entry["selected_epoch"]}, checkpoint)
                    entry["checkpoint_sha256"] = sha(checkpoint)
                    if cfg["scope"] == "development_matrix":
                        losses, details, z = evaluate(model, te)
                        np.savez_compressed(folder / f"{condition}_{seed}_evaluation.npz", test_indices=te,
                                            loss=losses, components=details, embeddings=z)
                        _, _, source_z = evaluate(model, tr)
                        np.savez_compressed(folder / f"{condition}_{seed}_library.npz", train_indices=tr, embeddings=source_z)
                        entry.update(test_loss_window_mean=float(losses.mean()), test_components=dict(zip(GROUPS, details.mean(0).tolist())))
                    entry.update(status="completed", seconds=time.monotonic() - model_started,
                                 peak_allocated_VRAM_MiB=torch.cuda.max_memory_allocated() / 2**20,
                                 peak_reserved_VRAM_MiB=torch.cuda.max_memory_reserved() / 2**20)
                    save()
                    print(json.dumps({key: value for key, value in entry.items() if key != "history"}), flush=True)
                    del model, optimizer, best_state
                    torch.cuda.empty_cache()
        for name, expected in cfg["input_sha256"].items():
            if sha(ROOT / name) != expected:
                raise ValueError(f"Protocol input changed during run: {name}")
        report["status"] = "completed"
        save()
    except Exception as error:
        report.update(status="stopped", error=str(error))
        save()
        raise


if __name__ == "__main__":
    main()
