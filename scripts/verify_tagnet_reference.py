"""CPU-only checks of the pinned upstream checkpoint, embeddings and gradient boundary."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"

PINNED_COMMIT = "1a7ac7cf817ba5ba476e94b3bee36046f4fef56c"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-dir", required=True, type=Path)
    parser.add_argument("--output-file", required=True, type=Path)
    args = parser.parse_args()
    if args.output_file.exists():
        parser.error("output already exists; preserve earlier evidence")
    root = args.upstream_dir.resolve()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if commit != PINNED_COMMIT:
        parser.error("upstream commit differs from the verified source version")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip():
        parser.error("upstream checkout must have no local source modifications")

    import numpy as np
    import pandas as pd
    import torch

    torch.set_num_threads(1)
    sys.path.insert(0, str(root / "scripts"))
    import train_tagnet as trainer

    data_dir = root / "data/processed/dust2_ct_5snap"
    run_dir = root / "results/tagnet_main/run"
    checkpoint_path = run_dir / "method_c_model.pt"
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    splits, metadata = trainer.load_split_data(data_dir)
    config = checkpoint["args"]
    model = trainer.MethodCModel(
        node_feature_dim=metadata["node_feat_dim"], context_dim=metadata["context_dim"],
        place_dim=metadata["place_dim"], hidden_dim=config["hidden_dim"],
        embedding_dim=config["embedding_dim"], gat_layers=config["gat_layers"],
        gru_layers=config["gru_layers"], use_context=not config["no_context"],
        use_graph=not config["no_graph"], use_temporal=config["single_snapshot"] is None,
        legacy_baseline_encoder=config.get("legacy_baseline_encoder", False),
    )
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    saved = pd.read_parquet(run_dir / "round_embeddings.parquet").set_index("sample_id")
    embedding_columns = sorted(c for c in saved.columns if c.startswith("emb_"))
    ids, computed = [], []
    for split in splits.values():
        ids.extend(split.sample_ids)
        computed.append(trainer.encode_split(model, split, torch.device("cpu"), 64).numpy())
    actual = np.concatenate(computed)
    assert len(ids) == len(set(ids)) == len(saved), "sample identity mismatch"
    expected = saved.loc[ids, embedding_columns].to_numpy()
    assert actual.shape == expected.shape == (697, 64), "release shape mismatch"
    assert np.isfinite(actual).all(), "non-finite embeddings"
    maximum_error = float(np.abs(actual - expected).max())

    batch = splits["train"].subset([0, 1])
    model.zero_grad(set_to_none=True)
    prediction = model(batch.node_features, batch.edge_distances, batch.context_features)
    loss, _ = trainer.compute_losses(prediction, batch, 1.0, 0.5, 1.0)
    loss.backward()
    gradient_counts = {}
    for name in ("snapshot_encoder", "context_encoder", "temporal_encoder"):
        module = getattr(model, name)
        gradient_counts[name] = sum(p.grad is not None for p in module.parameters())
    assert gradient_counts["snapshot_encoder"] > 0, "snapshot encoder is disconnected"
    assert gradient_counts["context_encoder"] == gradient_counts["temporal_encoder"] == 0, "source gradient behavior changed"
    receipt = {
        "status": "pass" if maximum_error <= 1e-5 else "embedding_drift_detected", "upstream_commit": commit,
        "checkpoint_sha256": hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
        "versions": {p: importlib.metadata.version(p) for p in ("torch", "numpy", "pandas", "pyarrow")},
        "device": "cpu", "threads": 1, "shape": list(actual.shape),
        "max_embedding_absolute_error": maximum_error,
        "embedding_tolerance": 1e-5, "parameters_with_gradients": gradient_counts,
        "claim": "published checkpoint inference and source gradient boundary only; no new training or generalization test",
    }
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    with args.output_file.open("x", encoding="utf-8") as output:
        output.write(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    assert maximum_error <= 1e-5, f"checkpoint embedding drift: {maximum_error}; receipt saved"


if __name__ == "__main__":
    main()
