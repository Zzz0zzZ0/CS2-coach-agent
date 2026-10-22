"""Offline CT observation neighbors; train-only library and conservative same-team-pair exclusion."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_feature_service import FEATURE_VERSION, feature_sequence
from app.services.ct_linear_service import linear_inputs
from app.services.ct_retrieval_service import nearest_common_candidates
from app.services.team_identity_service import canonical_team
from scripts.ct_experiment_data import canonical_pair, load_source


def retrieve(document, library):
    teams = {canonical_team(row["team"]) for row in document["rounds"] if row.get("team")}
    pair = tuple(sorted(teams)) if len(teams) == 2 else None
    if pair is None:
        raise ValueError("Exactly two known teams required for candidate-library isolation")
    filtered = [row for row in library if canonical_pair(row["series"]) != pair]
    if not filtered:
        raise ValueError("No isolated training-library candidates")
    features = {key: np.stack([r["features"][key] for r in filtered]) for key in filtered[0]["features"]}
    _, current = linear_inputs(features)
    library_states = current.reshape(len(filtered), 40)
    library_mask = features["target_mask"].reshape(len(filtered), 40)
    result = {"status": "experimental_CT_observation_neighbors", "feature_version": FEATURE_VERSION,
        "retriever_version": "ct-common-masked-v0.1", "map": document["map_name"],
        "source_demo_sha256": document["source_demo_sha256"], "library_split": "Dust2 train only",
        "library_size": len(filtered), "excluded_same_team_pair": len(library) - len(filtered),
        "isolation": "All source matches with the query team pair excluded conservatively; series aliases remain unknown",
        "limitations": ["unreviewed structural similarity, not a tactical label or recommendation",
                        "all five snapshots must be available; this is post-opening replay analysis",
                        "no navigation geometry; timing must be audited separately"], "rounds": [], "skipped": []}
    for row in document["rounds"]:
        if row["side"] != "CT":
            continue
        if row["status"] != "ok":
            result["skipped"].append({"round_number": row["round_number"], "reason": row["reason"]}); continue
        feature = feature_sequence(row["snapshots"])
        _, state = linear_inputs({key: value[None] for key, value in feature.items()})
        ranking, distance = nearest_common_candidates(state.reshape(1, 40), library_states,
            feature["target_mask"].reshape(1, 40), library_mask)
        result["rounds"].append({"round_number": row["round_number"], "side": "CT",
            "candidates": [{"id": filtered[int(i)]["id"], "match_label": filtered[int(i)]["series"],
                            "map": "de_dust2", "masked_state_mse": float(distance[0, i]),
                            "relevance_status": "unreviewed"} for i in ranking[0]]})
    if not result["rounds"]:
        raise ValueError("No eligible CT queries")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=ROOT / "output/tagnet/upstream/data/processed/dust2_ct_5snap/ct_snapshot_nodes.parquet")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output path")
    groups, audit = load_source(args.source)
    if audit["exact_cross_split_duplicate_groups"]:
        parser.error("Source content leakage detected")
    result = retrieve(json.loads(args.snapshots.read_text(encoding="utf-8")), groups["train"])
    result["source_sha256"] = hashlib.sha256(args.source.read_bytes()).hexdigest()
    result["source_alias_warnings"] = audit["cross_split_pair_aliases"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({"rounds": len(result["rounds"]), "library_size": result["library_size"],
                      "excluded_same_team_pair": result["excluded_same_team_pair"]}))


if __name__ == "__main__":
    main()
