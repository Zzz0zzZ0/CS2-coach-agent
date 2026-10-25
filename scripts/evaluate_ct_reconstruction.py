"""Summarize fixed reconstruction controls and export unjudged, same-library rankings."""

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_linear_service import linear_inputs
from app.services.ct_retrieval_service import nearest_candidates
from scripts.confirm_ct_generalization import sha, write


def statistics_sequence(data):
    nodes, alive, mask = (data[key] for key in ("nodes", "node_mask", "node_feature_mask"))
    base = linear_inputs({"nodes": nodes[..., :8], "edges": data["edges"][..., 0], "alive": alive})[0]
    count = alive.sum(2, keepdims=True).clip(1)
    height = np.stack([nodes[..., 8].max(2), np.sqrt((nodes[..., 9] ** 2).sum(2) / count[..., 0])], -1)
    ground = nodes[..., 10:13].sum(2) / count
    known = mask[..., 13]
    motion = np.concatenate([(nodes[..., 13:15] * known[..., None]).sum(2) / known.sum(2, keepdims=True).clip(1),
                              (np.abs(nodes[..., 14]) * known).sum(2, keepdims=True) / known.sum(2, keepdims=True).clip(1),
                              known.sum(2, keepdims=True) / count], -1)
    pairs = np.triu(data["pair_mask"], 1)
    pair_count = pairs.sum((2, 3), keepdims=False)[..., None]
    edge = data["edges"][..., 1:3] * pairs[..., None]
    extra = np.concatenate([edge.sum((2, 3)) / pair_count.clip(1), edge.max((2, 3)), pair_count > 0], -1)
    result = np.concatenate([base, height, ground, motion, extra], -1)
    if result.shape[1:] != (5, 24) or not np.isfinite(result).all():
        raise ValueError("Finite 24-field statistics required")
    return result.reshape(len(nodes), 120)


def observation_vector(data, permutation):
    p = list(permutation)
    first, second = np.triu_indices(5, 1)
    mask = data["node_feature_mask"][:, :, p]
    nodes = data["nodes"][:, :, p] * mask
    pairs = data["pair_mask"][:, :, p][:, :, :, p][:, :, first, second]
    edges = data["edges"][:, :, p][:, :, :, p][:, :, first, second]
    alive = data["node_mask"][:, :, p]
    blocks = [nodes, mask, edges * pairs[..., None], pairs, alive]
    return np.concatenate([block.reshape(len(nodes), -1).astype(float) / np.sqrt(5 * np.prod(block.shape[1:]))
                           for block in blocks], -1)


def observation_distances(data):
    base = observation_vector(data, range(5))
    norm = (base ** 2).sum(1)
    result = np.full((len(base), len(base)), np.inf)
    for p in permutations(range(5)):
        other = observation_vector(data, p)
        distance = norm[:, None] + norm[None] - 2 * base @ other.T
        np.minimum(result, distance.clip(0), out=result)
    return result


def equal_series(values, series):
    if len(values) != len(series) or not len(series) or not np.isfinite(values).all():
        raise ValueError("Finite paired window values and series required")
    return np.stack([values[np.asarray(series) == name].mean(0) for name in sorted(set(series))]).mean(0)


def paired_summary(model, baseline, series):
    a, b = (np.asarray([values[np.asarray(series) == name].mean() for name in sorted(set(series))])
            for values in (model, baseline))
    if not len(a) or not np.isfinite(a).all() or not np.isfinite(b).all() or (b <= 0).any():
        raise ValueError("Positive finite reference losses required")
    indices = np.random.default_rng(20261025).integers(0, len(a), (2000, len(a)))
    samples = 100 * (1 - a[indices].mean(1) / b[indices].mean(1))
    return {"equal_series_reduction_pct": float(100 * (1 - a.mean() / b.mean())),
            "descriptive_95pct_interval": np.percentile(samples, [2.5, 97.5]).tolist(),
            "series_count": len(a), "resamples": 2000, "seed": 20261025,
            "limits": "Conditional series resampling; shared teams and overlapping training folds are not independent; no hypothesis test."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "input-dir", "run-dir", "model-dir", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for key, value in vars(args).items():
        resolved = value.resolve()
        if not resolved.is_relative_to(ROOT):
            parser.error("Keep experiment paths inside workspace")
        setattr(args, key, resolved)
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    cfg = json.loads(args.protocol.read_text(encoding="utf-8"))
    source = json.loads((args.model_dir / "report.json").read_text(encoding="utf-8"))
    if source["status"] != "completed" or source["scope"] != "development_matrix" or source["protocol_sha256"] != sha(args.protocol):
        raise ValueError("Complete matrix under this exact protocol required")
    for name, digest in cfg["input_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ValueError(f"Frozen input changed: {name}")
    expected = {(fold, condition, seed) for fold in cfg["folds"] for condition in cfg["conditions"] for seed in cfg["training"]["seeds"]}
    actual = [(row["fold"], row["condition"], row["seed"]) for row in source["models"]]
    if len(actual) != len(set(actual)) or set(actual) != expected or any(m.get("status") != "completed" for m in source["models"]):
        raise ValueError("Missing or duplicate matrix cells")
    index = json.loads((args.input_dir / "sample_index.json").read_text(encoding="utf-8"))
    if index != json.loads((args.run_dir / "sample_index.json").read_text(encoding="utf-8")):
        raise ValueError("Sample order changed")
    folds = {f["name"]: f for f in json.loads((args.run_dir / "folds.json").read_text(encoding="utf-8")) if f["name"] in cfg["folds"]}
    with np.load(args.input_dir / "features.npz", allow_pickle=False) as archive:
        data = {key: archive[key] for key in ("nodes", "edges", "node_mask", "node_feature_mask", "pair_mask")}
    import psutil
    if psutil.virtual_memory().available < 1024 * 2**20:
        raise RuntimeError("Need 1 GiB available RAM")
    started = time.monotonic()
    direct = observation_distances(data)
    statistics = statistics_sequence(data)
    args.output_dir.mkdir(parents=True)
    np.savez_compressed(args.output_dir / "observation_distances.npz", distances=direct)
    report = {"status": "running", "scope": "development_reconstruction_and_unjudged_rankings",
              "protocol_sha256": sha(args.protocol), "matrix_report_sha256": sha(args.model_dir / "report.json"),
              "script_sha256": sha(Path(__file__)), "models": len(actual), "tasks": {},
              "direct_controls": cfg["direct_controls"], "input_artifact_sha256": {},
              "limits": ["Reconstruction loss is not tactical relevance or real-world coaching benefit.",
                         "All series and maps remain development data; independent new-series test is pending.",
                         "Rankings are unjudged. No tactical nDCG/recall is computed.",
                         "Seeds averaged within each window; windows averaged within series; series weighted equally.",
                         "Graph/non-graph parameter counts differ; temporal contrasts also preserve track correspondence."],
              "human_verification": {"status": "pending", "verified_by": None}}
    grouped = {}
    series = np.asarray([row["series"] for row in index])
    maps = np.asarray([row["map"] for row in index])

    def rankings(stream, fold, method, seed, distance):
        tr, te = np.asarray(fold["train"]), np.asarray(fold["test"])
        for j, query in enumerate(te):
            if series[query] in set(series[tr]):
                raise ValueError("Query series in retrieval library")
            strata = {"all_source": np.ones(len(tr), dtype=bool), "same_map": maps[tr] == maps[query], "cross_map": maps[tr] != maps[query]}
            ranked = {}
            for name, keep in strata.items():
                ids = np.flatnonzero(keep)
                order = ids[np.argsort(distance[j, ids], kind="stable")[:cfg["direct_controls"]["ranking_k"]]]
                ranked[name] = {"library_size": len(ids), "candidate_indices": tr[order].tolist(), "distances": distance[j, order].tolist()}
            stream.write(json.dumps({"fold": fold["name"], "method": method, "seed": seed,
                                      "query_index": int(query), "strata": ranked}) + "\n")

    with (args.output_dir / "rankings.jsonl").open("w", encoding="utf-8") as stream:
        for fold in folds.values():
            tr, te = np.asarray(fold["train"]), np.asarray(fold["test"])
            mean, std = statistics[tr].mean(0), statistics[tr].std(0).clip(1e-6)
            _, stat_distance = nearest_candidates((statistics[te] - mean) / std, (statistics[tr] - mean) / std)
            rankings(stream, fold, "statistics_sequence", None, stat_distance)
            rankings(stream, fold, "full_input_matching", None, direct[np.ix_(te, tr)])
        for entry in source["models"]:
            fold = folds[entry["fold"]]
            condition, seed = entry["condition"], entry["seed"]
            folder = args.model_dir / fold["name"]
            prefix = f"{condition}_{seed}"
            checkpoint = folder / (prefix + ".pt")
            if sha(checkpoint) != entry["checkpoint_sha256"]:
                raise ValueError("Checkpoint changed")
            history = entry["history"]
            if len(history) != cfg["training"]["epochs_max"] or int(np.argmin([row["validation_loss"] for row in history])) + 1 != entry["selected_epoch"]:
                raise ValueError("Selection differs from frozen rule")
            paths = [folder / (prefix + suffix) for suffix in ("_evaluation.npz", "_library.npz")]
            with np.load(paths[0], allow_pickle=False) as evaluation, np.load(paths[1], allow_pickle=False) as library:
                np.testing.assert_array_equal(evaluation["test_indices"], fold["test"])
                np.testing.assert_array_equal(library["train_indices"], fold["train"])
                components = evaluation["components"]
                z, source_z = evaluation["embeddings"], library["embeddings"]
                if components.shape != (len(fold["test"]), 7) or z.shape != (len(fold["test"]), 64) or source_z.shape != (len(fold["train"]), 64):
                    raise ValueError("Result shape mismatch")
                if not all(np.isfinite(x).all() for x in (components, z, source_z)):
                    raise ValueError("Nonfinite result")
                np.testing.assert_allclose(evaluation["loss"], components.mean(-1), rtol=1e-5, atol=1e-7)
                key = (fold["task"], condition, seed)
                values = grouped.setdefault(key, np.full((len(index), 7), np.nan))
                te = np.asarray(fold["test"])
                if np.isfinite(values[te]).any():
                    raise ValueError("Repeated query in a task/seed")
                values[te] = components
                rankings(stream, fold, condition, seed, nearest_candidates(z, source_z)[1])
            for path in paths:
                report["input_artifact_sha256"][str(path.relative_to(ROOT))] = sha(path)
    for task in sorted({key[0] for key in grouped}):
        result = {"windows": len(index), "series": len(set(series)), "methods": {}, "contrasts": {}}
        methods = {}
        for method in cfg["conditions"]:
            values = np.stack([grouped[(task, method, seed)] for seed in cfg["training"]["seeds"]]).mean(0)
            if not np.isfinite(values).all():
                raise ValueError("Incomplete out-of-fold coverage")
            loss = values.mean(-1)
            methods[method] = loss
            result["methods"][method] = {"loss_equal_series": float(equal_series(loss, series)),
                "components_equal_series": dict(zip(source["loss_groups"], equal_series(values, series).tolist())),
                "by_map": {name: {"windows": int((maps == name).sum()), "series": len(set(series[maps == name])),
                                   "loss_equal_series": float(equal_series(loss[maps == name], series[maps == name]))}
                           for name in sorted(set(maps))}}
        for contrast in cfg["planned_contrasts"]:
            a, b = contrast.split(" vs ")
            b = b.split(" at ")[0]
            result["contrasts"][contrast] = paired_summary(methods[a], methods[b], series)
        report["tasks"][task] = result
    report.update(status="completed", elapsed_seconds=time.monotonic() - started,
                  process_peak_RAM_MiB=psutil.Process().memory_info().peak_wset / 2**20)
    report["output_sha256"] = {p.name: sha(p) for p in args.output_dir.iterdir() if p.is_file()}
    write(args.output_dir / "report.json", report)
    print(json.dumps({"status": report["status"], "models": report["models"], "elapsed_seconds": report["elapsed_seconds"]}))


if __name__ == "__main__":
    main()
