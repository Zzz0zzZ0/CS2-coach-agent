"""Evaluate frozen CT models on one newly acquired series without updates or ingestion."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--demo-dir", type=Path, required=True)
    p.add_argument("--upstream-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    if a.output_dir.exists():
        p.error("use a new output directory")
    protocol = json.loads(a.protocol.read_text())
    for path, checksum in protocol["frozen_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == checksum, f"Frozen input changed: {path}"
    files = sorted(a.demo_dir.glob("*.dem"))
    assert 1 <= len(files) <= protocol["limits"]["demos_max"]
    from app.services.parser_service import TacticalDemoParser
    from app.services.ct_feature_service import feature_sequence, FEATURE_VERSION
    from demoparser2 import DemoParser
    import numpy as np
    target, skipped, source_info = [], [], []
    for path in files:
        map_name = DemoParser(str(path)).parse_header().get("map_name")
        with path.open("rb") as f:
            digest = hashlib.file_digest(f, "sha256").hexdigest()
        source_info.append({"file": path.name, "map": map_name, "sha256": digest, "bytes": path.stat().st_size})
        if map_name != protocol["target_map"]:
            continue
        observed = TacticalDemoParser(str(path)).parse_opening_snapshots()
        for r in observed["rounds"]:
            if r["side"] != "CT":
                continue
            if r["status"] != "ok":
                skipped.append({"round": r["round_number"], "reason": r["reason"]}); continue
            try:
                features = feature_sequence(r["snapshots"])
            except ValueError as e:
                skipped.append({"round": r["round_number"], "reason": str(e)}); continue
            target.append({"round_number": r["round_number"], "features": features})
    assert target, "No eligible CT rounds on the selected map"
    import psutil
    assert psutil.virtual_memory().available > 2 * 2**30
    import torch
    import run_ct_generalization as experiment
    torch.set_num_threads(1)
    assert torch.cuda.is_available()
    torch.cuda.set_per_process_memory_fraction(.2)
    torch.backends.fp32_precision = "ieee"
    torch.backends.cudnn.fp32_precision = "ieee"
    torch.backends.cuda.matmul.fp32_precision = "ieee"
    torch.backends.cudnn.rnn.fp32_precision = "tf32"
    sys.path.insert(0, str(a.upstream_dir.resolve() / "scripts"))
    import train_tagnet as trainer
    d = {k: np.stack([r["features"][k] for r in target]) for k in target[0]["features"]}
    truth, mask = d["targets"][:, 1:], d["target_mask"][:, 1:]
    def score(pred):
        errors = ((pred - truth) ** 2) * mask
        return {"mse": float(errors.sum() / mask.sum()),
                "occupancy_mse": float(errors[..., :6].sum() / mask[..., :6].sum()),
                "distance_mse": float(errors[..., 6:].sum() / max(mask[..., 6:].sum(), 1))}
    report = {"status": "frozen_single_series_evaluated", "scope": protocol["scope"],
        "series": protocol["matches"][0]["match_id"], "map": protocol["target_map"], "rounds": len(target),
        "protocol_sha256": hashlib.sha256(a.protocol.read_bytes()).hexdigest(), "frozen_sha256": protocol["frozen_sha256"],
        "source_files": source_info, "skipped": skipped, "persistence": score(d["targets"][:, :-1]), "models": {},
        "limitations": ["one series only", "known repository series, not project-wide blind evaluation",
                        "no tactical or retrieval quality labels", "64 Hz and pause alignment not independently verified"],
        "precision": {"matmul": "ieee", "rnn": "tf32"}}
    for model_name in (protocol["primary_model"], protocol["secondary_model"]):
        weight_file = next(ROOT / path for path in protocol["frozen_sha256"] if path.endswith(model_name + ".pt"))
        ck = torch.load(weight_file, weights_only=True, map_location="cpu")
        assert ck["feature_version"] == FEATURE_VERSION
        m = experiment.CTModel(trainer, residual=ck["residual"])
        m.load_state_dict(ck["model_state_dict"], strict=True)
        m = m.cuda().eval().requires_grad_(False)
        predictions = []
        with torch.no_grad():
            for start in range(0, len(target), 64):
                predictions.append(m(experiment.batch(d, start, start + 64), ck["temporal"])[1].cpu().numpy())
        result = score(np.concatenate(predictions))
        result["improvement_vs_persistence_pct"] = 100 * (1 - result["mse"] / report["persistence"]["mse"])
        report["models"][model_name] = result
        del m
        torch.cuda.empty_cache()
    # Recheck after inference so source edits cannot silently invalidate the freeze.
    for path, checksum in protocol["frozen_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == checksum
    a.output_dir.mkdir(parents=True, exist_ok=False)
    (a.output_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
