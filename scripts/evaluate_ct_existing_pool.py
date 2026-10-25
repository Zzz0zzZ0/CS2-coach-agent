"""Replay frozen encoders on exact previously rated candidates, with no new labels."""

import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_context_retrieval_service import context_embedding, normalize_source, squared_distance
from app.services.ct_retrieval_service import nearest_candidates
from scripts.confirm_ct_generalization import sha, write
from scripts.evaluate_ct_context_retrieval import load_experiment, model_inputs
from scripts.evaluate_ct_reconstruction import statistics_sequence


def rated_pool_ndcg(distances, grades, candidate_indices):
    distances, grades = np.asarray(distances, dtype=float), np.asarray(grades, dtype=float)
    candidate_indices = np.asarray(candidate_indices)
    if (distances.ndim != 1 or distances.shape != grades.shape or distances.shape != candidate_indices.shape
            or not np.isfinite(distances).all() or not np.isfinite(grades).all()
            or (grades < 0).any() or (grades > 3).any() or len(set(candidate_indices)) != len(candidate_indices)):
        raise ValueError("Finite distinct rated candidates and original 0-3 grades required")
    if len(grades) < 2:
        return None
    k = min(5, len(grades))
    discounts = 1 / np.log2(np.arange(k) + 2)
    gains = 2.0 ** grades - 1
    ideal = float(np.dot(np.sort(gains)[::-1][:k], discounts))
    if ideal <= 0:
        return None
    order = np.lexsort((candidate_indices, distances))[:k]
    return {"ndcg5_within_rated_pool": float(np.dot(gains[order], discounts) / ideal),
            "expected_uniform_random_ndcg5": float(gains.mean() * discounts.sum() / ideal),
            "rated_candidates": len(grades), "effective_k": k}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    cfg = json.loads(args.protocol.read_text(encoding="utf-8"))
    for name, digest in cfg["input_sha256"].items():
        if sha(ROOT / name.replace("\\", "/")) != digest:
            raise ValueError("Frozen bounded-pool input changed")
    audit = json.loads((ROOT / cfg["audit_report"]).read_text(encoding="utf-8"))
    path = ROOT / cfg["local_scores"]
    if audit["status"] != "verified_exact_old_stimuli_not_new_labels" or sha(path) != audit["local_scores_sha256"]:
        raise ValueError("Verified exact-stimulus audit required")
    ratings = json.loads(path.read_text(encoding="utf-8"))
    recipe, index, folds, context, evidence, data = load_experiment(ROOT / cfg["retrieval_protocol"])
    stats = statistics_sequence(data)
    with np.load(ROOT / recipe["observation_distances"], allow_pickle=False) as archive:
        direct = archive["distances"]
    panels = defaultdict(list)
    for subset in cfg["subsets"]:
        for field in ("tactical", "structural"):
            for row in ratings:
                if (row["in_current_training_library"] and row["grades"][field] is not None
                        and (subset == "all_numeric" or (row["protocol_complete"] and row["reason_present"]))):
                    panels[(subset, field, row["query_id"])].append(row)
    needed = sorted({row["fold"] for rows in panels.values() for row in rows})
    output = []
    for fold_name in needed:
        fold = folds[fold_name]
        tr, te = np.asarray(fold["train"]), np.asarray(fold["test"])
        tr_position, te_position = {int(v): i for i, v in enumerate(tr)}, {int(v): i for i, v in enumerate(te)}
        source_context, query_context = ({name: values[ids] for name, values in context.items()} for ids in (tr, te))
        contexts = {tuple(p["groups"]): context_embedding(source_context, query_context, tuple(p["groups"]))
                    for p in recipe["policies"].values() if p["groups"]}
        ctx_distance = {}
        for groups, ctx in contexts.items():
            distance = np.full((len(te), len(tr)), np.inf)
            if ctx["source_supported"]:
                keep = ctx["query_supported"]
                distance[keep] = squared_distance(ctx["queries"][keep], ctx["source"])
            ctx_distance[groups] = distance
        mean, std = stats[tr].mean(0), stats[tr].std(0).clip(1e-6)
        import itertools
        controls = [("statistics_sequence", None, (stats[tr] - mean) / std, (stats[te] - mean) / std, {}),
                    ("full_input_matching", None, None, None, {}), ("context_only", None, None, None, {})]
        for method, seed, source_z, query_z, receipts in itertools.chain(model_inputs(recipe, fold, te, evidence, data, False), controls):
            if method == "full_input_matching":
                source_distance = direct[np.ix_(tr, tr)]
                scale = float((source_distance.sum() - source_distance.trace()) / (len(tr) * (len(tr) - 1)))
                base = direct[np.ix_(te, tr)] / (scale if scale > 1e-12 else 1)
            elif method != "context_only":
                _, _, metadata = normalize_source(source_z, query_z)
                base = nearest_candidates(query_z, source_z)[1] / metadata["scale"]
            policies = {"context_only": {"groups": ["equipment", "score", "utility"], "weight": 1}} if method == "context_only" else recipe["policies"]
            for policy_name, policy in policies.items():
                groups, weight = tuple(policy["groups"]), policy["weight"]
                distance = ctx_distance[groups] if method == "context_only" else base if not groups else (1 - weight) * base + weight * ctx_distance[groups]
                for (subset, field, qid), rows in panels.items():
                    if rows[0]["fold"] != fold_name:
                        continue
                    by_candidate = defaultdict(list)
                    for row in rows:
                        if row["query_index"] != rows[0]["query_index"] or row["candidate_index"] not in tr_position:
                            raise ValueError("Rated pool violates verified source/query identities")
                        by_candidate[row["candidate_index"]].append(row["grades"][field])
                    ids = sorted(by_candidate)
                    grades = [float(np.mean(by_candidate[i])) for i in ids]
                    values = distance[te_position[rows[0]["query_index"]], [tr_position[i] for i in ids]]
                    metric = rated_pool_ndcg(values, grades, ids) if np.isfinite(values).all() else None
                    output.append({"subset": subset, "field": field, "query_id": qid, "method": method,
                                   "policy": policy_name, "seed": seed, "metric": metric})
    grouped = defaultdict(list)
    for row in output:
        if row["metric"] is not None:
            grouped[(row["subset"], row["field"], row["method"], row["policy"], row["query_id"])].append(row["metric"])
    per_query = [{"subset": subset, "field": field, "method": method, "policy": policy, "query_id": qid,
                  "seeds_averaged": len(rows), "ndcg5_within_rated_pool": float(np.mean([r["ndcg5_within_rated_pool"] for r in rows])),
                  "expected_uniform_random_ndcg5": rows[0]["expected_uniform_random_ndcg5"], "rated_candidates": rows[0]["rated_candidates"]}
                 for (subset, field, method, policy, qid), rows in grouped.items()]
    grouped = defaultdict(list)
    for row in per_query:
        grouped[(row["subset"], row["field"], row["method"], row["policy"])].append(row)
    summary = [{"subset": subset, "field": field, "method": method, "policy": policy,
                "queries": len(rows), "macro_query_ndcg5": float(np.mean([r["ndcg5_within_rated_pool"] for r in rows])),
                "macro_expected_uniform_random_ndcg5": float(np.mean([r["expected_uniform_random_ndcg5"] for r in rows]))}
               for (subset, field, method, policy), rows in grouped.items()]
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "report.json", {"status": "completed_exploratory_old_pool_replay", "protocol_sha256": sha(args.protocol),
          "script_sha256": sha(Path(__file__)), "summary": summary, "per_query": per_query,
          "undefined_or_unsupported_cells": sum(row["metric"] is None for row in output), "limits": cfg["limits"]})
    print(json.dumps({"macro_condition_rows": len(summary), "per_query_condition_rows": len(per_query), "no_new_annotations": True}))


if __name__ == "__main__":
    main()
