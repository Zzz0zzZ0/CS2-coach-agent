"""Retrospective fair-horizon geometry diagnostics on frozen CT encoders, without training."""

import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import psutil
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_feature_service import feature_sequence
from app.services.ct_linear_service import linear_inputs
from app.services.ct_retrieval_service import nearest_candidates, geometry_signature, geometry_diagnostic
from app.services.team_identity_service import canonical_team
from scripts.ct_experiment_data import load_source, canonical_pair
from scripts.run_ct_generalization import CTModel, arrays, batch


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expansion-dirs", type=Path, nargs="+", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    assert psutil.virtual_memory().available > 2 * 2**30
    protocol = json.loads((ROOT / "datasets/selections/ct_expansion_v3.json").read_text())
    for path, checksum in protocol["frozen_sha256"].items():
        assert digest(ROOT / path) == checksum, path
    source, audit = load_source(ROOT / "output/tagnet/upstream/data/processed/dust2_ct_5snap/ct_snapshot_nodes.parquet")
    groups = {"source_train": source["train"]}
    pairs, input_reports = {}, {}
    for folder in args.expansion_dirs:
        index = json.loads((folder / "sample_index.json").read_text())
        input_reports[str(folder.relative_to(ROOT) if folder.is_absolute() else folder)] = digest(folder / "report.json")
        for name, records in index.items():
            if name in ("source_train", "dust2_test"):
                continue
            assert name not in groups, "Duplicate target group"
            document = json.loads((folder / f"{name}_snapshots.json").read_text())
            teams = {canonical_team(r["team"]) for r in document["rounds"] if r.get("team")}
            assert len(teams) == 2
            pairs[name] = tuple(sorted(teams))
            rows = {r["round_number"]: r for r in document["rounds"] if r["side"] == "CT"}
            groups[name] = [{**r, "features": feature_sequence(rows[r["round_number"]]["snapshots"])} for r in records]
    data = {name: arrays(rows) for name, rows in groups.items()}
    vectors, geometries, eligible = {}, {}, {}
    for name, values in data.items():
        eligible[name], geometries[name] = geometry_signature(values)
        inputs, states = linear_inputs(values)
        vectors[name] = {"common_last": states[eligible[name], -1],
                         "common_sequence": states[eligible[name]].reshape(int(eligible[name].sum()), 40),
                         "full_inputs_last": inputs[eligible[name], -1],
                         "full_inputs_sequence": inputs[eligible[name]].reshape(int(eligible[name].sum()), 50)}
    assert torch.cuda.is_available()
    torch.set_num_threads(1)
    torch.cuda.set_per_process_memory_fraction(.2)
    assert torch.cuda.mem_get_info()[0] > 1024 * 2**20
    torch.backends.fp32_precision = "ieee"
    torch.backends.cudnn.fp32_precision = "ieee"
    torch.backends.cuda.matmul.fp32_precision = "ieee"
    torch.backends.cudnn.rnn.fp32_precision = "tf32"
    sys.path.insert(0, str(ROOT / "output/tagnet/upstream/scripts"))
    import train_tagnet as trainer
    for label, temporal in (("static_snapshot_42", False), ("prefix_gru_42", True)):
        path = ROOT / f"output/tagnet/ct_generalization_residual_v1/{label}.pt"
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        model = CTModel(trainer, residual=True)
        model.load_state_dict(checkpoint["model_state_dict"], strict=True)
        model = model.cuda().eval().requires_grad_(False)
        captured = {}
        def graph_hook(module, inputs):
            captured["graph"] = inputs[0].detach()
        def gru_hook(module, inputs, outputs):
            captured["sequence"] = outputs[0].detach()
        graph_handle = model.reconstruct.register_forward_pre_hook(graph_hook)
        gru_handle = model.gru.register_forward_hook(gru_hook) if temporal else None
        prefix = "gru" if temporal else "static"
        with torch.no_grad():
            for name, values in data.items():
                last, sequence = [], []
                for start in range(0, len(values["nodes"]), 64):
                    captured.clear()
                    inputs = {k: v for k, v in batch(values, start, start + 64).items() if k in ("nodes", "edges", "alive")}
                    embedding = model(inputs, temporal)[2]
                    states = captured["sequence"] if temporal else captured["graph"]
                    assert states.shape[1:] == (5, 64)
                    assert torch.equal(states[:, -1], embedding), "Hook must preserve original embedding exactly"
                    assert torch.isfinite(states).all()
                    last.append(embedding.cpu().numpy())
                    sequence.append(states.cpu().numpy().reshape(len(states), 320))
                vectors[name][f"{prefix}_last"] = np.concatenate(last)[eligible[name]]
                vectors[name][f"{prefix}_sequence"] = np.concatenate(sequence)[eligible[name]]
        assert all(p.grad is None and not p.requires_grad for p in model.parameters())
        graph_handle.remove()
        if gru_handle:
            gru_handle.remove()
        del model
    tasks = {"snapshot20": (slice(-10, None), ("common_last", "full_inputs_last", "static_last", "gru_last")),
             "opening5": (slice(None), ("common_sequence", "full_inputs_sequence", "static_sequence", "gru_sequence", "gru_last", "static_last"))}
    source_pairs = [canonical_pair(row["series"]) for row, keep in zip(groups["source_train"], eligible["source_train"]) if keep]
    report = {"status": "completed_retrospective_horizon_diagnostic", "scope": "frozen encoders, no training or metric fitting; existing target results observed",
        "tasks": {"snapshot20": "10 pair distances at 20 seconds; common/static use last snapshot, GRU has earlier context",
                  "opening5": "50 pair distances; sequence methods use identical five observed frames; last-state controls retain original compact representations"},
        "candidate_scope": "Dust2 train, all five alive throughout, exclude query team pair conservatively for every method and reference",
        "geometry_only": True, "human_judgments": 0, "input_report_sha256": input_reports,
        "frozen_sha256": protocol["frozen_sha256"], "script_sha256": digest(Path(__file__)),
        "source_audit": audit, "groups": {}, "aggregate": {},
        "limitations": ["constructed geometry reference, not independent tactical relevance", "queries with deaths excluded from this diagnostic",
                        "health/equipment enter graph models; full-input controls make this preference explicit", "source series aliases unresolved"]}
    review, method_key = [], {}
    library_records = [row for row, keep in zip(groups["source_train"], eligible["source_train"]) if keep]
    rng = np.random.default_rng(20261023)
    review_methods = ("common_sequence", "full_inputs_sequence", "static_sequence", "gru_last")
    for name in groups:
        if name == "source_train":
            continue
        keep = np.array([pair != pairs[name] for pair in source_pairs])
        assert keep.sum() >= 5
        result = {"eligible_queries": int(eligible[name].sum()), "excluded_with_deaths": int((~eligible[name]).sum()),
                  "candidate_count": int(keep.sum()), "same_pair_excluded": int((~keep).sum()), "tasks": {}}
        selected_rankings = {}
        for task, (dimensions, methods) in tasks.items():
            ideal, distances = nearest_candidates(geometries[name][:, dimensions], geometries["source_train"][keep][:, dimensions])
            result["tasks"][task] = {}
            for method in methods:
                ranking, _ = nearest_candidates(vectors[name][method], vectors["source_train"][method][keep])
                result["tasks"][task][method] = geometry_diagnostic(ranking, distances, ideal)
                if task == "opening5" and method in review_methods:
                    selected_rankings[method] = ranking[0]
        report["groups"][name] = result
        union = sorted({int(i) for row in selected_rankings.values() for i in row})
        blind_order = rng.permutation(union)
        mapping = {int(i): f"C{k+1:02d}" for k, i in enumerate(blind_order)}
        case = f"Q{len(review)+1:03d}"
        candidate_positions = np.flatnonzero(keep)
        first_query = int(np.flatnonzero(eligible[name])[0])
        review.append({"query": case, "group": name,
            "observations": vectors[name]["full_inputs_sequence"][0].reshape(5, 10).tolist(),
            "pair_distances": geometries[name][0].reshape(5, 10).tolist(),
            "candidates": [{"candidate": mapping[int(i)],
                "observations": vectors["source_train"]["full_inputs_sequence"][candidate_positions[i]].reshape(5, 10).tolist(),
                "pair_distances": geometries["source_train"][candidate_positions[i]].reshape(5, 10).tolist(),
                "structural_relevance": None, "reviewer": None, "reason": None} for i in blind_order]})
        method_key[case] = {"query": groups[name][first_query]["id"],
            "candidates": {mapping[int(i)]: library_records[candidate_positions[i]]["id"] for i in blind_order},
            "methods": {method: [mapping[int(i)] for i in ranking] for method, ranking in selected_rankings.items()}}
    for task, (_, methods) in tasks.items():
        report["aggregate"][task] = {}
        for method in methods:
            parts = [g["tasks"][task][method] for g in report["groups"].values()]
            count = sum(p["query_count"] for p in parts)
            report["aggregate"][task][method] = {"queries": count,
                "top5_geometry_mse": sum(p["query_count"] * p["top5_geometry_mse"] for p in parts) / count,
                "neighbor_overlap": sum(p["query_count"] * p["top5_geometry_neighbor_overlap"] for p in parts) / count}
    for path, checksum in protocol["frozen_sha256"].items():
        assert digest(ROOT / path) == checksum, path
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    packet = {"status": "unreviewed", "judgment_count": 0, "methods_hidden": True,
        "scope": "structural observations only; tactical intent cannot be judged from these summaries alone",
        "selection": "first eligible all-five-alive query per map-series; same-pair candidates excluded",
        "seconds": [10, 12, 15, 18, 20],
        "feature_order": ["A_live_fraction", "B_live_fraction", "CTSpawn_live_fraction", "TSpawn_live_fraction",
                          "other_live_fraction", "dead_fraction", "pair_mean_distance_div5000", "pair_max_distance_div5000",
                          "mean_normalized_health", "mean_log_normalized_equipment"],
        "rubric": "0 dissimilar, 1 partial structural similarity, 2 close structural similarity, null unreviewed",
        "cases": review}
    (args.output_dir / "review_cases.json").write_text(json.dumps(packet, indent=2, allow_nan=False) + "\n")
    (args.output_dir / "method_key.json").write_text(json.dumps(method_key, indent=2) + "\n")
    print(json.dumps({"groups": len(report["groups"]), "aggregate": report["aggregate"]}, indent=2))


if __name__ == "__main__":
    main()
