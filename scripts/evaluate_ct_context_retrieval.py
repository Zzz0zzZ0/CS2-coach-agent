"""Frozen-encoder context controls; rankings are unjudged, not tactical accuracy."""

import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
import gc
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_context_retrieval_service import (
    CONTEXT_VERSION, context_groups, context_embedding, normalize_source, squared_distance,
)
from app.services.ct_retrieval_service import nearest_candidates
from scripts.confirm_ct_generalization import sha, write
from scripts.evaluate_ct_reconstruction import statistics_sequence


def load_experiment(protocol):
    cfg = json.loads(protocol.read_text(encoding="utf-8"))
    for name, digest in cfg["input_sha256"].items():
        if sha(ROOT / name.replace("\\", "/")) != digest:
            raise ValueError(f"Frozen context input changed: {name}")
    matrix = json.loads((ROOT / cfg["matrix_protocol"]).read_text(encoding="utf-8"))
    for name, digest in matrix["input_sha256"].items():
        if sha(ROOT / name.replace("\\", "/")) != digest:
            raise ValueError(f"Frozen matrix input changed: {name}")
    index = json.loads((ROOT / cfg["sample_index"]).read_text(encoding="utf-8"))
    rows = json.loads((ROOT / cfg["context_dir"] / "context.json").read_text(encoding="utf-8"))
    report = json.loads((ROOT / cfg["context_dir"] / "report.json").read_text(encoding="utf-8"))
    if [row["id"] for row in rows] != [row["id"] for row in index] or report["context_sha256"] != sha(ROOT / cfg["context_dir"] / "context.json"):
        raise ValueError("Context order or content changed")
    folds = {f["name"]: f for f in json.loads((ROOT / cfg["folds"]).read_text(encoding="utf-8"))}
    evidence = json.loads((ROOT / cfg["matrix_analysis_report"]).read_text(encoding="utf-8"))
    with np.load(ROOT / cfg["features"], allow_pickle=False) as archive:
        data = {key: archive[key] for key in ("nodes", "edges", "node_mask", "node_feature_mask", "pair_mask")}
    return cfg, index, folds, context_groups(rows), evidence, data


def checked_archive(path, expected):
    if sha(path) != expected:
        raise ValueError(f"Frozen model artifact changed: {path.name}")
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key] for key in archive.files}


def model_inputs(cfg, fold, query_indices, evidence, data, pilot):
    folder = ROOT / cfg["model_dir"] / fold["name"]
    artifacts = {key.replace("\\", "/"): value for key, value in evidence["input_artifact_sha256"].items()}
    for condition in cfg["conditions"]:
        for seed in ([cfg["pilot"]["seed"]] if pilot else cfg["seeds"]):
            prefix = f"{condition}_{seed}"
            path = folder / (prefix + "_library.npz")
            library = checked_archive(path, artifacts[path.relative_to(ROOT).as_posix()])
            np.testing.assert_array_equal(library["train_indices"], fold["train"])
            receipt = {path.relative_to(ROOT).as_posix(): sha(path)}
            if pilot:
                import torch
                from scripts.run_ct_reconstruction import ReconstructionModel
                import psutil
                if psutil.virtual_memory().available < 1536 * 2**20:
                    raise RuntimeError("Need 1.5 GiB available RAM for source-only inference")
                torch.set_num_threads(2)
                if not torch.cuda.is_available():
                    raise RuntimeError("The source-only resource pilot requires the existing CUDA environment")
                free, _ = torch.cuda.mem_get_info()
                if free < 1024 * 2**20:
                    raise RuntimeError("Need 1 GiB free VRAM")
                torch.cuda.set_per_process_memory_fraction(0.2)
                checkpoint = folder / (prefix + ".pt")
                selected = next(row for row in evidence["model_selection"]
                                if row["fold"] == fold["name"] and row["condition"] == condition and row["seed"] == seed)
                if sha(checkpoint) != selected["checkpoint_sha256"]:
                    raise ValueError("Checkpoint changed")
                saved = torch.load(checkpoint, map_location="cuda", weights_only=True)
                if saved["protocol_sha256"] != sha(ROOT / cfg["matrix_protocol"]) or saved["selected_epoch"] != selected["selected_epoch"]:
                    raise ValueError("Checkpoint selection changed")
                model = ReconstructionModel(condition).cuda().eval()
                model.load_state_dict(saved["state_dict"])
                def encode(ids):
                    result = []
                    with torch.inference_mode():
                        for start in range(0, len(ids), 16):
                            batch = {key: torch.from_numpy(value[ids[start:start + 16]]).cuda() for key, value in data.items()}
                            result.append(model.encode(batch)[0].cpu().numpy())
                    return np.concatenate(result)
                z = encode(np.asarray(query_indices))
                np.testing.assert_allclose(encode(np.asarray(fold["train"][:2])), library["embeddings"][:2], rtol=2e-5, atol=2e-5)
                receipt[checkpoint.relative_to(ROOT).as_posix()] = sha(checkpoint)
                del model, saved
                gc.collect()
                torch.cuda.empty_cache()
            else:
                path = folder / (prefix + "_evaluation.npz")
                evaluation = checked_archive(path, artifacts[path.relative_to(ROOT).as_posix()])
                np.testing.assert_array_equal(evaluation["test_indices"], query_indices)
                z = evaluation["embeddings"]
                receipt[path.relative_to(ROOT).as_posix()] = sha(path)
            yield condition, seed, library["embeddings"], z, receipt


def rank_arrays(distances, query_indices, source_indices, index, k):
    query_maps = np.asarray([index[i]["map"] for i in query_indices])
    source_maps = np.asarray([index[i]["map"] for i in source_indices])
    candidates = np.full((len(query_indices), 3, k), -1, dtype=np.int32)
    values = np.full(candidates.shape, np.inf)
    for q in range(len(query_indices)):
        for j, keep in enumerate((np.ones(len(source_indices), dtype=bool), source_maps == query_maps[q], source_maps != query_maps[q])):
            eligible = np.flatnonzero(keep & np.isfinite(distances[q]))
            order = eligible[np.argsort(distances[q, eligible], kind="stable")[:k]]
            candidates[q, j, :len(order)] = source_indices[order]
            values[q, j, :len(order)] = distances[q, order]
    return candidates, values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    import psutil
    if psutil.virtual_memory().available < 2 * 2**30:
        raise RuntimeError("Need 2 GiB available RAM")
    cfg, index, folds, context, evidence, data = load_experiment(args.protocol)
    expected_scope = "source_context_pilot" if args.pilot else "development_context_matrix"
    if cfg["scope"] != expected_scope or next(iter(cfg["policies"])) != "base":
        raise ValueError("Protocol scope or base-policy order mismatch")
    if not args.pilot:
        pilot = json.loads((ROOT / cfg["pilot_report"]).read_text(encoding="utf-8"))
        if (pilot["status"] != "completed" or pilot["scope"] != "source_validation_resource_pilot"
                or pilot["protocol_sha256"] != sha(ROOT / cfg["source_pilot_protocol"])):
            raise ValueError("Successful frozen source-only pilot required")
    if args.pilot:
        # Validate the unchanged encoder's complete input contract once before inference.
        from scripts.run_ct_reconstruction import load_inputs
        load_inputs((ROOT / cfg["features"]).parent, (ROOT / cfg["folds"]).parent)
    statistics = statistics_sequence(data)
    with np.load(ROOT / cfg["observation_distances"], allow_pickle=False) as archive:
        direct = archive["distances"]
    if direct.shape != (len(index), len(index)) or not np.isfinite(direct).all():
        raise ValueError("Invalid frozen observation-distance cache")
    series = np.asarray([row["series"] for row in index])
    args.output_dir.mkdir(parents=True)
    started = time.monotonic()
    result = {"status": "running", "scope": "source_validation_resource_pilot" if args.pilot else "development_unjudged_context_controls",
              "context_version": CONTEXT_VERSION, "protocol_sha256": sha(args.protocol), "script_sha256": sha(Path(__file__)),
              "runtime": {"python": sys.version, "numpy": np.__version__},
              "fits": [], "input_artifact_sha256": {}, "limits": cfg["interpretation_limits"]}
    for fold_name in ([cfg["pilot"]["fold"]] if args.pilot else cfg["fold_names"]):
        fold = folds[fold_name]
        tr = np.asarray(fold["train"])
        queries = np.asarray(fold["validation"] if args.pilot else fold["test"])
        if set(series[tr]) & set(series[queries]):
            raise ValueError("Query series occurs in the retrieval library")
        source_context, query_context = ({name: values[ids] for name, values in context.items()} for ids in (tr, queries))
        contexts = {tuple(policy["groups"]): context_embedding(source_context, query_context, tuple(policy["groups"]))
                    for policy in cfg["policies"].values() if policy["groups"]}
        mean, std = statistics[tr].mean(0), statistics[tr].std(0).clip(1e-6)
        methods = model_inputs(cfg, fold, queries, evidence, data, args.pilot)
        import itertools
        direct_methods = [("statistics_sequence", None, (statistics[tr] - mean) / std, (statistics[queries] - mean) / std, {}),
                          ("full_input_matching", None, None, None, {})]
        for method, seed, source_z, query_z, receipts in itertools.chain(methods, direct_methods):
            if psutil.virtual_memory().available < 1536 * 2**20 or time.monotonic() - started > cfg["max_seconds"]:
                raise RuntimeError("RAM/time guard reached; no further method started")
            if method == "full_input_matching":
                source_distance = direct[np.ix_(tr, tr)]
                base_scale = float((source_distance.sum() - source_distance.trace()) / (len(tr) * (len(tr) - 1)))
                base_scale = base_scale if base_scale > 1e-12 else 1.0
                base_raw = direct[np.ix_(queries, tr)]
            else:
                _, _, scale = normalize_source(source_z, query_z)
                base_scale = scale["scale"]
                base_raw = nearest_candidates(query_z, source_z)[1]
            base = base_raw / base_scale
            arrays, metrics, normalized = [], {}, {}
            for policy_name, policy in cfg["policies"].items():
                groups, weight = tuple(policy["groups"]), policy["weight"]
                supported = np.ones(len(queries), dtype=bool)
                if not groups:
                    distance = base
                else:
                    ctx = contexts[groups]
                    supported = ctx["query_supported"]
                    if groups not in normalized:
                        normalized[groups] = np.full(base.shape, np.inf)
                        if ctx["source_supported"]:
                            normalized[groups][supported] = squared_distance(ctx["queries"][supported], ctx["source"])
                    distance = (1 - weight) * base + weight * normalized[groups]
                rank, rank_distance = rank_arrays(distance, queries, tr, index, cfg["ranking_k"])
                arrays.append((rank, rank_distance))
                if not groups:
                    np.testing.assert_array_equal(rank, rank_arrays(base_raw, queries, tr, index, cfg["ranking_k"])[0])
                    baseline = rank
                valid = (rank[:, :, 0] >= 0) & (baseline[:, :, 0] >= 0)
                metrics[policy_name] = {"supported_context_queries": int(supported.sum()),
                    "eligible_top1_comparisons_by_stratum": valid.sum(0).tolist(),
                    "top1_changed_by_stratum": ((rank[:, :, 0] != baseline[:, :, 0]) & valid).sum(0).tolist()}
            path = args.output_dir / f"{fold_name}__{method}_{seed}.npz"
            np.savez_compressed(path, policies=np.asarray(list(cfg["policies"])), query_indices=queries, source_indices=tr,
                                candidate_indices=np.stack([a[0] for a in arrays]), distances=np.stack([a[1] for a in arrays]))
            result["input_artifact_sha256"].update(receipts)
            result["fits"].append({"fold": fold_name, "method": method, "seed": seed, "queries": len(queries),
                                   "library": len(tr), "base_scale": base_scale,
                                   "context_scales": {"+".join(g): c["scales"] for g, c in contexts.items()},
                                   "policies": metrics, "output_file": path.name, "output_sha256": sha(path)})
        own = contexts[tuple(cfg["policies"]["own_context_050"]["groups"])]
        distance = np.full((len(queries), len(tr)), np.inf)
        if own["source_supported"]:
            valid = own["query_supported"]
            distance[valid] = squared_distance(own["queries"][valid], own["source"])
        rank, rank_distance = rank_arrays(distance, queries, tr, index, cfg["ranking_k"])
        path = args.output_dir / f"{fold_name}__context_only.npz"
        np.savez_compressed(path, policies=np.asarray(["context_only"]), query_indices=queries, source_indices=tr,
                            candidate_indices=rank[None], distances=rank_distance[None])
        result["fits"].append({"fold": fold_name, "method": "context_only", "seed": None, "queries": len(queries),
                               "library": len(tr), "output_file": path.name, "output_sha256": sha(path),
                               "supported_context_queries": int(own["query_supported"].sum())})
        write(args.output_dir / "report.json", result)
        print(json.dumps({"fold": fold_name, "completed_method_fits": len(result["fits"])}), flush=True)
    result.update(status="completed", elapsed_seconds=time.monotonic() - started,
                  peak_RAM_MiB=getattr(psutil.Process().memory_info(), "peak_wset", psutil.Process().memory_info().rss) / 2**20,
                  output_bytes=sum(p.stat().st_size for p in args.output_dir.glob("*.npz")))
    if args.pilot:
        import torch
        result["CUDA_peak_allocated_MiB"] = torch.cuda.max_memory_allocated() / 2**20
    write(args.output_dir / "report.json", result)
    print(json.dumps({key: result[key] for key in ("status", "scope", "elapsed_seconds", "peak_RAM_MiB", "output_bytes")}))


if __name__ == "__main__":
    main()
