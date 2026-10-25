"""Verify old human stimuli against raw windows before any bounded-pool model comparison."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.confirm_ct_generalization import sha, write
from scripts.shorten_ct_semantic_pilot import payload_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    key_path = ROOT / "output/tagnet/ct_semantic_pilot_v9_distributed_r3_zh/analyst_key.json"
    index_path = ROOT / "output/tagnet/ct_deployment_inputs_p1_v03/sample_index.json"
    fold_path = ROOT / "output/tagnet/ct_grouped_confirmation_v7/folds.json"
    inventory_path = ROOT / "datasets/evaluation/ct_map_semantics_v8_report.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    lookup = {row["id"]: i for i, row in enumerate(index)}
    key = json.loads(key_path.read_text(encoding="utf-8"))["queries"]
    folds = {f["name"]: f for f in json.loads(fold_path.read_text(encoding="utf-8"))}
    source_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in (key_path, index_path, fold_path, inventory_path)}
    raw = {}
    for name, digest in json.loads(inventory_path.read_text(encoding="utf-8"))["dataset_sha256"].items():
        if name.endswith("_snapshots.json"):
            path = ROOT / name.replace("\\", "/")
            if sha(path) != digest:
                raise ValueError("Frozen snapshot changed")
            doc = json.loads(path.read_text(encoding="utf-8"))
            for row in doc["rounds"]:
                if row["side"] == "CT" and row["status"] == "ok":
                    raw[f"{doc['source_demo_sha256']}:{row['round_number']}:CT"] = row
    packets = {}
    for folder in ("ct_semantic_pilot_v9_distributed_r2", "ct_semantic_pilot_v9_distributed_r3_zh", "ct_human_micro_v13", "ct_remaining_v16"):
        for path in (ROOT / "output/tagnet" / folder).rglob("*.html"):
            match = re.search(r'<script id="data" type="application/json">(.*?)</script>', path.read_text(encoding="utf-8-sig"), re.S)
            if match:
                payload = json.loads(match[1])
                if payload_hash(payload) != payload["payload_sha256"]:
                    raise ValueError("Original human packet payload changed")
                packets[(payload["version"], payload["payload_sha256"])] = (payload, path)

    def verify_view(view, metadata):
        number = lookup[metadata["id"]]
        if any(index[number][field] != metadata[field] for field in ("map", "series", "round_number")) or view["map"] != metadata["map"]:
            raise ValueError("Old case identity differs from current frozen cohort")
        snapshots = raw[metadata["id"]]["snapshots"]
        if [frame["second"] for frame in view["frames"]] != [frame["second"] for frame in snapshots]:
            raise ValueError("Stimulus observation times differ")
        for shown, actual in zip(view["frames"], snapshots):
            if len(shown["players"]) != 5:
                raise ValueError("Stimulus roster is incomplete")
            for rendered, player in zip(shown["players"], actual["players"]):
                np.testing.assert_allclose(rendered["position"], player["position"], rtol=0, atol=1e-5)
                np.testing.assert_allclose([rendered["health"], rendered["equipment"]], [player["health"], player["equipment_value"]], rtol=0, atol=1e-5)
                if rendered["place"] != player["place"]:
                    raise ValueError("Stimulus place differs from frozen raw place")
        return number

    records, returned_versions, checked_pairs = [], [], set()
    for folder in sorted((ROOT / "output/tagnet/ct_human_feedback_v11").glob("participant_*")):
        original, intake_path = folder / "original_export.json", folder / "intake.json"
        response = json.loads(original.read_text(encoding="utf-8-sig"))
        intake = json.loads(intake_path.read_text(encoding="utf-8-sig"))
        if sha(original) != intake["source_export_sha256"]:
            raise ValueError("Original human response changed")
        payload, path = packets[(response["version"], response["payload_sha256"])]
        source_hashes[original.relative_to(ROOT).as_posix()] = sha(original)
        source_hashes[path.relative_to(ROOT).as_posix()] = sha(path)
        packet_queries = {q["id"]: q for q in payload["queries"]}
        returned_versions.append(response["version"])
        for rating in response["ratings"]:
            qid, cid = rating["query_id"], rating["candidate_id"]
            case, packet_query = key[qid], packet_queries[qid]
            query = verify_view(packet_query["query"], case["query"])
            candidate_view = next(c["record"] for c in packet_query["candidates"] if c["id"] == cid)
            candidate = verify_view(candidate_view, case["candidates"][cid])
            checked_pairs.add((qid, cid))
            fold = folds["G4__" + index[query]["map"]]
            if query not in fold["test"]:
                raise ValueError("Old query outside current test partition")
            grades = {}
            for field in ("tactical", "structural"):
                grade, unknown = rating[field + "_grade"], rating[field + "_unjudgeable"]
                if grade is not None and (type(grade) is not int or grade not in range(4) or unknown):
                    raise ValueError("Contradictory or invalid original grade")
                grades[field] = grade
            records.append({"query_id": qid, "candidate_id": cid, "query_index": query, "candidate_index": candidate,
                            "fold": fold["name"], "in_current_training_library": candidate in fold["train"],
                            "protocol_complete": bool(rating["complete"]), "reason_present": bool(rating.get("reason", "").strip()),
                            "grades": grades, "explicit_unjudgeable": {f: rating[f + "_unjudgeable"] for f in grades}})
    counts = {}
    for subset in ("protocol_complete_numeric", "all_numeric"):
        counts[subset] = {}
        for field in ("tactical", "structural"):
            selected = [r for r in records if r["grades"][field] is not None and
                        (subset == "all_numeric" or (r["protocol_complete"] and r["reason_present"]))]
            eligible = [r for r in selected if r["in_current_training_library"]]
            counts[subset][field] = {"original_numeric_records": len(selected), "eligible_records": len(eligible),
                                    "excluded_outside_current_source_train": len(selected) - len(eligible),
                                    "eligible_by_query": dict(Counter(r["query_id"] for r in eligible))}
    result = {"status": "verified_exact_old_stimuli_not_new_labels", "script_sha256": sha(Path(__file__)),
              "source_sha256": source_hashes, "returns": len(returned_versions), "checked_old_pairs": len(checked_pairs),
              "counts": counts, "returner_identity_independence_verified": False,
              "limits": ["Raw responses/reasons remain local; only aggregate audit is public.",
                         "Only exact old cases are eligible, and current source-training membership is required. Excluded old labels are retained, not edited.",
                         "Old views did not show new utility/score facets; comparisons against these judgments remain information-limited development diagnostics.",
                         "No new candidate receives an old score. Missing and unjudgeable remain missing, never grade zero.",
                         "Pool selection, few queries and unverified grader independence prohibit a new independent tactical-validation claim."]}
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "reusable_scores.json", records)
    result["local_scores_sha256"] = sha(args.output_dir / "reusable_scores.json")
    write(args.output_dir / "report.json", result)
    print(json.dumps({"verified_old_pairs": len(checked_pairs), "counts": counts}))


if __name__ == "__main__":
    main()
