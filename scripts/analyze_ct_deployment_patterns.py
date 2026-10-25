"""Source-fitted, unnamed deployment patterns; cluster IDs are not tactical duties."""

import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
from itertools import combinations
import json
from pathlib import Path
import sys

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score, silhouette_score
import sklearn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.confirm_ct_generalization import sha, write


def fit_patterns(source, queries, cfg):
    if source.ndim != 2 or queries.ndim != 2 or source.shape[1] != queries.shape[1] or not np.isfinite(source).all() or not np.isfinite(queries).all():
        raise ValueError("Finite source/query embeddings with matching widths required")
    unique = len(np.unique(source, axis=0))
    best, candidates = None, []
    for k in sorted(cfg["k_candidates"]):
        if not 2 <= k < len(source) or k > unique:
            candidates.append({"k": k, "status": "unsupported"})
            continue
        model = KMeans(n_clusters=k, n_init=cfg["n_init"], max_iter=cfg["max_iter"], random_state=cfg["seed"], algorithm="lloyd").fit(source)
        if len(set(model.labels_)) != k:
            candidates.append({"k": k, "status": "collapsed"})
            continue
        score = float(silhouette_score(source, model.labels_))
        candidates.append({"k": k, "status": "fitted", "source_silhouette": score})
        if best is None or score > best[0] + 1e-12:
            best = score, model
    if best is None:
        return {"status": "unsupported", "candidates": candidates}
    score, model = best
    labels, query_labels = model.labels_, model.predict(queries)
    source_distance = np.linalg.norm(source - model.cluster_centers_[labels], axis=-1)
    query_distance = np.linalg.norm(queries - model.cluster_centers_[query_labels], axis=-1)
    counts = np.bincount(labels, minlength=model.n_clusters)
    radii = np.asarray([np.quantile(source_distance[labels == c], cfg["source_radius_quantile"]) for c in range(model.n_clusters)])
    assigned = (query_distance <= radii[query_labels]) & (counts[query_labels] >= cfg["minimum_cluster_support"])
    return {"status": "fitted", "k": model.n_clusters, "source_silhouette": score,
            "candidates": candidates, "centers": model.cluster_centers_, "source_labels": labels,
            "query_labels": query_labels, "query_assigned": assigned,
            "source_distances": source_distance, "query_distances": query_distance,
            "source_radii": radii, "source_counts": counts}


def bootstrap_stability(source, reference, series, k, cfg):
    names = sorted(set(series))
    if len(names) < 2:
        return {"replicates": cfg["series_bootstrap_replicates"], "unsupported": cfg["series_bootstrap_replicates"],
                "ARI_values": [], "mean_ARI": None, "scope": "At least two source series required"}
    rng = np.random.default_rng(cfg["seed"])
    scores, unsupported = [], 0
    for _ in range(cfg["series_bootstrap_replicates"]):
        chosen = rng.choice(names, len(names), replace=True)
        ids = np.concatenate([np.flatnonzero(np.asarray(series) == name) for name in chosen])
        if len(np.unique(source[ids], axis=0)) < k:
            unsupported += 1
            continue
        model = KMeans(n_clusters=k, n_init=cfg["n_init"], max_iter=cfg["max_iter"], random_state=cfg["seed"], algorithm="lloyd").fit(source[ids])
        if len(set(model.labels_)) != k:
            unsupported += 1
            continue
        scores.append(float(adjusted_rand_score(reference, model.predict(source))))
    return {"replicates": cfg["series_bootstrap_replicates"], "unsupported": unsupported,
            "ARI_values": scores, "mean_ARI": float(np.mean(scores)) if scores else None,
            "scope": "Series-resampled source clustering at fixed K and fixed neural embedding; not full-pipeline uncertainty."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "matrix-protocol", "model-dir", "run-dir", "output-dir"):
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
    matrix_cfg = json.loads(args.matrix_protocol.read_text(encoding="utf-8"))
    source = json.loads((args.model_dir / "report.json").read_text(encoding="utf-8"))
    if source["status"] != "completed" or source["protocol_sha256"] != sha(args.matrix_protocol):
        raise ValueError("Complete frozen reconstruction matrix required")
    for name, expected in cfg["input_sha256"].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f"Analysis input changed: {name}")
    expected = {(fold, method, seed) for fold in matrix_cfg["folds"] for method in matrix_cfg["conditions"] for seed in matrix_cfg["training"]["seeds"]}
    actual = [(m["fold"], m["condition"], m["seed"]) for m in source["models"]]
    if len(actual) != len(expected) or set(actual) != expected or any(m.get("status") != "completed" for m in source["models"]):
        raise ValueError("Incomplete model matrix")
    import psutil
    if psutil.virtual_memory().available < 1536 * 2**20:
        raise RuntimeError("Need 1.5 GiB available RAM")
    index = json.loads((args.run_dir / "sample_index.json").read_text(encoding="utf-8"))
    folds = {f["name"]: f for f in json.loads((args.run_dir / "folds.json").read_text(encoding="utf-8"))}
    args.output_dir.mkdir(parents=True)
    report = {"status": "running", "scope": "source_fitted_development_patterns", "analysis_protocol_sha256": sha(args.protocol),
              "matrix_protocol_sha256": sha(args.matrix_protocol), "matrix_report_sha256": sha(args.model_dir / "report.json"),
              "versions": {"numpy": np.__version__, "scikit_learn": sklearn.__version__},
              "patterns": [], "cross_seed_stability": [], "artifact_sha256": {},
              "limits": ["Clusters have numeric IDs only; no map-place duty assignments or validated tactical names.",
                         "Source silhouette selects K, not tactical correctness; every model retains its own source-fitted clusters.",
                         "Source-radius acceptance is an uncalibrated diagnostic; report all rejected queries.",
                         "Stability across seeds is not independent dataset replication; bootstrap fixes the neural encoder.",
                         "No new independent series, no human judgments and no test-driven K selection."],
              "human_verification": {"status": "pending", "verified_by": None}}
    assignments = {}
    for entry in source["models"]:
        if psutil.virtual_memory().available < 1024 * 2**20:
            write(args.output_dir / "report.json", {**report, "status": "resource_stop"})
            raise RuntimeError("Pattern-analysis RAM guard")
        fold, method, seed = folds[entry["fold"]], entry["condition"], entry["seed"]
        prefix = args.model_dir / entry["fold"] / f"{method}_{seed}"
        paths = [prefix.with_name(prefix.name + suffix) for suffix in ("_library.npz", "_evaluation.npz")]
        with np.load(paths[0], allow_pickle=False) as library, np.load(paths[1], allow_pickle=False) as evaluation:
            np.testing.assert_array_equal(library["train_indices"], fold["train"])
            np.testing.assert_array_equal(evaluation["test_indices"], fold["test"])
            z, queries = library["embeddings"], evaluation["embeddings"]
            fitted = fit_patterns(z, queries, cfg["clustering"])
            result = {"fold": entry["fold"], "condition": method, "seed": seed,
                      "status": fitted["status"], "candidates": fitted["candidates"]}
            if fitted["status"] == "fitted":
                labels, query_labels, assigned = fitted["source_labels"], fitted["query_labels"], fitted["query_assigned"]
                result.update(selected_k=fitted["k"], source_silhouette=fitted["source_silhouette"],
                              query_windows=len(queries), assigned_queries=int(assigned.sum()),
                              source_map_NMI=float(normalized_mutual_info_score([index[i]["map"] for i in fold["train"]], labels)),
                              source_series_NMI=float(normalized_mutual_info_score([index[i]["series"] for i in fold["train"]], labels)),
                              clusters=[])
                for c in range(fitted["k"]):
                    members = np.flatnonzero(labels == c)
                    examples = members[np.argsort(fitted["source_distances"][members], kind="stable")[:3]]
                    result["clusters"].append({"cluster": c, "source_windows": len(members),
                        "source_radius": float(fitted["source_radii"][c]),
                        "source_examples": [fold["train"][i] for i in examples],
                        "map_counts": {name: sum(index[fold["train"][i]]["map"] == name for i in members)
                                       for name in sorted({index[i]["map"] for i in fold["train"]})}})
                if seed == cfg["bootstrap_model_seed"]:
                    result["source_series_bootstrap"] = bootstrap_stability(z, labels, [index[i]["series"] for i in fold["train"]], fitted["k"], cfg["clustering"])
                assignments[(entry["fold"], method, seed)] = (query_labels, assigned)
                np.savez_compressed(args.output_dir / f"{entry['fold']}__{method}__{seed}.npz",
                                    train_indices=fold["train"], test_indices=fold["test"], centers=fitted["centers"],
                                    source_labels=labels, query_labels=query_labels, query_assigned=assigned,
                                    query_distances=fitted["query_distances"], source_radii=fitted["source_radii"])
        report["patterns"].append(result)
        for path in paths:
            report["artifact_sha256"][str(path.relative_to(ROOT))] = sha(path)
        if len(report["patterns"]) % 18 == 0:
            write(args.output_dir / "report.json", report)
            print(json.dumps({"patterns_completed": len(report["patterns"]), "planned": len(actual)}), flush=True)
    for fold in matrix_cfg["folds"]:
        for method in matrix_cfg["conditions"]:
            for first, second in combinations(matrix_cfg["training"]["seeds"], 2):
                keys = [(fold, method, seed) for seed in (first, second)]
                if any(key not in assignments for key in keys):
                    report["cross_seed_stability"].append({"fold": fold, "condition": method, "seeds": [first, second], "status": "unsupported_model"})
                    continue
                (a, ma), (b, mb) = [assignments[key] for key in keys]
                common = ma & mb
                valid = common.sum() >= 2 and len(set(a[common])) >= 2 and len(set(b[common])) >= 2
                report["cross_seed_stability"].append({"fold": fold, "condition": method, "seeds": [first, second],
                    "common_assigned": int(common.sum()), "queries": len(a),
                    "status": "computed" if valid else "insufficient_common_cluster_variation",
                    "ARI": float(adjusted_rand_score(a[common], b[common])) if valid else None})
    report.update(status="completed", process_peak_RAM_MiB=psutil.Process().memory_info().peak_wset / 2**20)
    report["output_sha256"] = {p.name: sha(p) for p in args.output_dir.glob("*.npz")}
    write(args.output_dir / "report.json", report)
    print(json.dumps({"status": "completed", "models": len(actual)}))


if __name__ == "__main__":
    main()
