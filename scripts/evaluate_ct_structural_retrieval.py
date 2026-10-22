"""Compare frozen representations against a common-state control; export unjudged review cases."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_feature_service import feature_sequence
from app.services.ct_retrieval_service import nearest_candidates, geometry_signature, geometry_diagnostic
from scripts.ct_experiment_data import load_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expansion-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    index = json.loads((args.expansion_dir / "sample_index.json").read_text())
    representations = np.load(args.expansion_dir / "representations.npz", allow_pickle=False)
    source, _ = load_source(ROOT / "output/tagnet/upstream/data/processed/dust2_ct_5snap/ct_snapshot_nodes.parquet")
    library = source["train"]
    assert [row["id"] for row in library] == [row["id"] for row in index["source_train"]]
    arrays = lambda rows: {key: np.stack([r["features"][key] for r in rows]) for key in rows[0]["features"]}
    lib_mask, lib_geometry = geometry_signature(arrays(library))
    lib_records = [r for r, keep in zip(library, lib_mask) if keep]
    methods = ("common", "static_snapshot_42", "prefix_gru_42")
    report = {"status": "structural_diagnostics_only", "candidate_library_split": "Dust2 train only",
              "library_size": len(library), "five_alive_library_size": len(lib_records), "groups": {},
              "geometry_reference": "50 sorted within-frame pair distances (five snapshots, ten pairs each); all five alive at every frame",
              "limitations": ["geometry reference is a constructed proxy, not expert tactical relevance",
                              "no navigation geometry", "all observed query series remain outside candidate library",
                              "common-state control and graph encoders share input geometry; no independent gold labels"],
              "source_expansion_report_sha256": hashlib.sha256((args.expansion_dir / "report.json").read_bytes()).hexdigest(),
              "helper_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                                [ROOT / "app/services/ct_retrieval_service.py", ROOT / "scripts/ct_experiment_data.py"]},
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    review, method_key = [], {}
    for name, records in index.items():
        if name == "source_train":
            continue
        if name == "dust2_test":
            rows = source["test"]
        else:
            document = json.loads((args.expansion_dir / f"{name}_snapshots.json").read_text())
            rounds = {row["round_number"]: row for row in document["rounds"] if row["side"] == "CT"}
            rows = [{"features": feature_sequence(rounds[r["round_number"]]["snapshots"])} for r in records]
        mask, geometry = geometry_signature(arrays(rows))
        if not mask.any():
            report["groups"][name] = {"eligible": 0}; continue
        ideal, distances = nearest_candidates(geometry, lib_geometry)
        rankings = {}
        results = {"eligible": int(mask.sum()), "excluded_with_deaths": int((~mask).sum()), "methods": {}}
        for method in methods:
            ranking, _ = nearest_candidates(representations[f"{name}__{method}"][mask], representations[f"source_train__{method}"][lib_mask])
            rankings[method] = ranking
            results["methods"][method] = geometry_diagnostic(ranking, distances, ideal)
        rng = np.random.default_rng(20261023)
        random = np.stack([rng.permutation(len(lib_records))[:5] for _ in range(len(geometry))])
        results["methods"]["random_control"] = geometry_diagnostic(random, distances, ideal)
        report["groups"][name] = results
        first_query = int(np.flatnonzero(mask)[0])
        case_id = f"Q{len(review)+1:03d}"
        union = sorted({int(i) for ranking in rankings.values() for i in ranking[0]})
        blind_order = rng.permutation(union)
        mapping = {int(value): f"C{k+1:02d}" for k, value in enumerate(blind_order)}
        review.append({"query": case_id, "query_group": name,
            "scope": "structural observation relevance only; tactical intent remains unknown",
            "query_observations": representations[f"{name}__common"][first_query].reshape(5, 8).tolist(),
            "query_pair_distances": geometry[0].reshape(5, 10).tolist(),
            "candidates": [{"candidate": mapping[int(i)],
                "observations": representations["source_train__common"][lib_mask][i].reshape(5, 8).tolist(),
                "pair_distances": lib_geometry[i].reshape(5, 10).tolist(),
                "structural_relevance": None, "tactical_relevance": None, "reviewer": None, "reason": None}
                for i in blind_order]})
        method_key[case_id] = {"query": records[first_query]["id"],
            "candidate_ids": {mapping[i]: lib_records[i]["id"] for i in mapping},
            "methods": {method: [mapping[int(i)] for i in ranking[0]] for method, ranking in rankings.items()}}
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for filename, data in (("report.json", report), ("review_cases.json", {"status": "unreviewed", "judgment_count": 0,
         "selection": "first all-five-alive eligible query per map-series, plus published source test; methods hidden in separate key",
         "rubric": "structural_relevance: 0 dissimilar, 1 partial observation similarity, 2 close observation similarity, null unreviewed; do not infer tactical intent",
         "cases": review}), ("method_key.json", method_key)):
        (args.output_dir / filename).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"groups": len(report["groups"]), "review_cases": len(review), "human_judgments": 0}))


if __name__ == "__main__":
    main()
