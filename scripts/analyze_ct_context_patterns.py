"""Source-only pattern diagnostics for explicit CT context; clusters are unnamed."""

import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
from collections import Counter, defaultdict
from itertools import chain, combinations
import json
from pathlib import Path
import sys
import time

import numpy as np
import sklearn
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_context_retrieval_service import context_embedding, fused_embedding, squared_distance, normalize_source
from app.services.ct_retrieval_service import nearest_candidates
from scripts.analyze_ct_deployment_patterns import fit_patterns, bootstrap_stability
from scripts.confirm_ct_generalization import sha, write
from scripts.evaluate_ct_context_retrieval import load_experiment, model_inputs
from scripts.evaluate_ct_reconstruction import statistics_sequence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    import psutil
    cfg = json.loads(args.protocol.read_text(encoding="utf-8"))
    for name, digest in cfg["input_sha256"].items():
        if sha(ROOT / name.replace("\\", "/")) != digest:
            raise ValueError(f"Frozen pattern input changed: {name}")
    recipe, index, folds, context, evidence, data = load_experiment(ROOT / cfg["retrieval_protocol"])
    if psutil.virtual_memory().available < 2 * 2**30:
        raise RuntimeError("Need 2 GiB available RAM")
    stats = statistics_sequence(data)
    series, maps = (np.asarray([row[key] for row in index]) for key in ("series", "map"))
    result = {"status": "running", "scope": "development_context_pattern_diagnostics",
              "protocol_sha256": sha(args.protocol), "script_sha256": sha(Path(__file__)),
              "runtime": {"python": sys.version, "numpy": np.__version__, "sklearn": sklearn.__version__},
              "models": [], "input_artifact_sha256": {}, "limits": cfg["limits"]}
    grouped = defaultdict(list)
    args.output_dir.mkdir(parents=True)
    started = time.monotonic()
    for fold_name in recipe["fold_names"]:
        fold = folds[fold_name]
        tr, te = np.asarray(fold["train"]), np.asarray(fold["test"])
        if set(series[tr]) & set(series[te]):
            raise ValueError("Query series in source")
        ctx = context_embedding({name: values[tr] for name, values in context.items()},
                                {name: values[te] for name, values in context.items()})
        mean, std = stats[tr].mean(0), stats[tr].std(0).clip(1e-6)
        controls = [("statistics_sequence", None, (stats[tr] - mean) / std, (stats[te] - mean) / std, {}),
                    ("context_only", None, None, None, {})]
        for method, seed, source_z, query_z, receipts in chain(model_inputs(recipe, fold, te, evidence, data, False), controls):
            result["input_artifact_sha256"].update(receipts)
            modes = ["base", "context"] if method == "statistics_sequence" else ["context"]
            for mode in modes:
                if time.monotonic() - started > cfg["max_seconds"] or psutil.virtual_memory().available < 1536 * 2**20:
                    raise RuntimeError("Pattern RAM/time guard; no further model started")
                variant = method if mode == "base" or method == "context_only" else method + "+context"
                row = {"fold": fold_name, "task": fold["task"], "variant": variant, "seed": seed,
                       "queries": len(te), "source_windows": len(tr)}
                known = np.ones(len(te), dtype=bool)
                if mode == "base":
                    source, queries = source_z, query_z
                elif not ctx["source_supported"] or not ctx["query_supported"].any():
                    row.update(status="unsupported_context", reason="Missing source context or no fully known queries")
                    result["models"].append(row)
                    continue
                elif method == "context_only":
                    source, queries = ctx["source"], ctx["queries"]
                    known = ctx["query_supported"]
                else:
                    source, queries, scale = fused_embedding(source_z, query_z, ctx, cfg["weight"])
                    known = ctx["query_supported"]
                    reference = ((1 - cfg["weight"]) * nearest_candidates(query_z[known][:3], source_z[:5])[1] / scale["scale"]
                                 + cfg["weight"] * squared_distance(ctx["queries"][known][:3], ctx["source"][:5]))
                    np.testing.assert_allclose(squared_distance(queries[known][:3], source[:5]), reference, rtol=1e-6, atol=1e-6)
                source, queries = source.astype(np.float32), queries.astype(np.float32)
                fitted = fit_patterns(source, queries[known], cfg["clustering"])
                if fitted["status"] != "fitted":
                    row.update(status="unsupported_clustering", candidates=fitted["candidates"])
                    result["models"].append(row)
                    continue
                labels = np.full(len(te), -1, dtype=np.int32)
                assigned = np.zeros(len(te), dtype=bool)
                distances = np.full(len(te), np.inf)
                labels[known], assigned[known], distances[known] = fitted["query_labels"], fitted["query_assigned"], fitted["query_distances"]
                row.update(status="fitted", k=fitted["k"], source_silhouette=fitted["source_silhouette"],
                           assigned_queries=int(assigned.sum()), context_known_queries=int(known.sum()),
                           source_map_NMI=float(normalized_mutual_info_score(maps[tr], fitted["source_labels"])),
                           source_series_NMI=float(normalized_mutual_info_score(series[tr], fitted["source_labels"])))
                if seed is None or seed == cfg["bootstrap_model_seed"]:
                    row["conditional_bootstrap"] = bootstrap_stability(source, fitted["source_labels"], series[tr], fitted["k"], cfg["clustering"])
                path = args.output_dir / f"{fold_name}__{variant}_{seed}.npz"
                np.savez_compressed(path, query_indices=te, source_indices=tr, query_labels=labels, query_assigned=assigned,
                    query_context_known=known, query_distances=distances, centers=fitted["centers"],
                    source_labels=fitted["source_labels"], source_radii=fitted["source_radii"], source_counts=fitted["source_counts"])
                row.update(output_file=path.name, output_sha256=sha(path))
                result["models"].append(row)
                grouped[(fold["task"], variant)].append((fold_name, seed, labels, assigned, row))
        write(args.output_dir / "report.json", result)
        print(json.dumps({"fold": fold_name, "completed_pattern_fits": len(result["models"])}), flush=True)
    result["summary"] = {}
    for (task, variant), rows in grouped.items():
        comparisons = []
        for fold_name in sorted({r[0] for r in rows}):
            matches = [r for r in rows if r[0] == fold_name and r[1] is not None]
            for a, b in combinations(matches, 2):
                common = a[3] & b[3]
                item = {"fold": fold_name, "seeds": [a[1], b[1]], "common_accepted_queries": int(common.sum()), "ARI": None}
                if common.sum() < 2:
                    item["reason"] = "fewer than two common accepted queries"
                elif len(set(a[2][common])) < 2 or len(set(b[2][common])) < 2:
                    item["reason"] = "fewer than two assigned clusters in a comparison"
                else:
                    item["ARI"] = float(adjusted_rand_score(a[2][common], b[2][common]))
                comparisons.append(item)
        values = [r["ARI"] for r in comparisons if r["ARI"] is not None]
        bootstrap = [v for row in rows for v in row[4].get("conditional_bootstrap", {}).get("ARI_values", [])]
        summary = {"fits": len(rows), "K_counts": dict(Counter(str(r[4]["k"]) for r in rows)),
                   "query_seed_assignments": sum(r[4]["queries"] for r in rows),
                   "accepted_query_seed_assignments": sum(r[4]["assigned_queries"] for r in rows),
                   "seed_comparisons": comparisons, "computed_seed_pairs": len(values),
                   "mean_seed_ARI": float(np.mean(values)) if values else None,
                   "mean_source_map_NMI": float(np.mean([r[4]["source_map_NMI"] for r in rows])),
                   "mean_source_series_NMI": float(np.mean([r[4]["source_series_NMI"] for r in rows])),
                   "mean_conditional_bootstrap_ARI": float(np.mean(bootstrap)) if bootstrap else None}
        summary["coverage"] = summary["accepted_query_seed_assignments"] / summary["query_seed_assignments"]
        result["summary"].setdefault(task, {})[variant] = summary
    result.update(status="completed", elapsed_seconds=time.monotonic() - started,
                  peak_RAM_MiB=getattr(psutil.Process().memory_info(), "peak_wset", psutil.Process().memory_info().rss) / 2**20,
                  output_bytes=sum(p.stat().st_size for p in args.output_dir.glob("*.npz")))
    write(args.output_dir / "report.json", result)
    print(json.dumps({k: result[k] for k in ("status", "elapsed_seconds", "peak_RAM_MiB", "output_bytes")}))


if __name__ == "__main__":
    main()
