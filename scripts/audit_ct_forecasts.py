"""GPU self-checks on every saved CT checkpoint, without training or network services."""

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.confirm_ct_generalization import load_records, sha, write


def main():
    import json
    import psutil
    import torch
    from scripts.run_ct_generalization import CTModel, arrays, batch
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        p.error("Use a new audit output")
    report = json.loads((a.run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "completed_grouped_generalization_matrix"
    assert psutil.virtual_memory().available > 2 * 2**30
    torch.set_num_threads(1)
    torch.cuda.set_per_process_memory_fraction(.2)
    torch.backends.fp32_precision = "ieee"
    torch.backends.cudnn.fp32_precision = "ieee"
    torch.backends.cuda.matmul.fp32_precision = "ieee"
    torch.backends.cudnn.rnn.fp32_precision = "tf32"
    upstream = ROOT / "output/tagnet/upstream"
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip()
    assert head == "1a7ac7cf817ba5ba476e94b3bee36046f4fef56c"
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=upstream, text=True).strip()
    sys.path.insert(0, str(upstream / "scripts"))
    import train_tagnet as trainer
    records, _ = load_records([ROOT / path for path in report["input_report_sha256"]])
    folds = json.loads((a.run_dir / "folds.json").read_text(encoding="utf-8"))
    expected_counts = {f["name"]: len(f["neural"]) for f in report["folds"]}
    result = {"status": "checked_all_saved_weights", "report_sha256": sha(a.run_dir / "report.json"),
              "script_sha256": sha(Path(__file__)), "checkpoints": [], "max_permutation_error": 0,
              "upstream_commit": head, "upstream_trainer_sha256": sha(upstream / "scripts/train_tagnet.py"),
              "future_leakage_failures": 0, "scope": "first test observation per fold, each saved weight; no semantic or tactical relevance judgment"}
    for fold in folds:
        b = batch(arrays([records[fold["test"][0]]]), 0, 1)
        b = {k: b[k] for k in ("nodes", "edges", "alive")}
        checkpoints = sorted((a.run_dir / fold["name"]).glob("*.pt"))
        assert len(checkpoints) == expected_counts[fold["name"]], "Saved checkpoint missing"
        for path in checkpoints:
            assert psutil.virtual_memory().available > 1536 * 2**20
            temporal = path.name.startswith("gru_")
            model = CTModel(trainer, residual=True)
            model.load_state_dict(torch.load(path, weights_only=True, map_location="cpu"), strict=True)
            model = model.cuda().eval().requires_grad_(False)
            with torch.no_grad():
                _, original, embedding = model(b, temporal)
                for cut in range(1, 5):
                    changed = {k: v.clone() for k, v in b.items()}
                    changed["nodes"][:, cut:] *= .123
                    changed["edges"][:, cut:] *= 2
                    changed["alive"][:, cut:] = False
                    changed["alive"][:, cut:, 0] = True
                    changed["nodes"][:, cut:, :, 7] = changed["alive"][:, cut:]
                    changed["nodes"][:, cut:, :, 5] *= changed["alive"][:, cut:]
                    alternative = model(changed, temporal)[1]
                    assert torch.equal(original[:, :cut], alternative[:, :cut]), "Future observation changed an earlier prediction"
                permutation = torch.tensor([4, 2, 0, 3, 1], device="cuda")
                moved = {"nodes": b["nodes"][:, :, permutation], "alive": b["alive"][:, :, permutation],
                         "edges": b["edges"][:, :, permutation][:, :, :, permutation]}
                _, pred, vector = model(moved, temporal)
                error = max((pred - original).abs().max().item(), (vector - embedding).abs().max().item())
                assert error <= 1e-5, "Player ordering changed the representation"
                result["max_permutation_error"] = max(result["max_permutation_error"], error)
            result["checkpoints"].append({"path": str(path), "sha256": sha(path)})
            del model
    result["peak_allocated_VRAM_MiB"] = torch.cuda.max_memory_allocated() / 2**20
    write(a.output, result)
    print(json.dumps({"checked_checkpoints": len(result["checkpoints"]), "max_permutation_error": result["max_permutation_error"]}))


if __name__ == "__main__":
    main()
