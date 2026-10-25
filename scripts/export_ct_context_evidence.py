"""Annotate the existing six fixed cases with CT context; keep every ranking unchanged."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.confirm_ct_generalization import sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    case_path = ROOT / "docs/paper/manuscript/figures/evidence.json"
    index_path = ROOT / "output/tagnet/ct_deployment_inputs_p1_v03/sample_index.json"
    fold_path = ROOT / "output/tagnet/ct_grouped_confirmation_v7/folds.json"
    context_path, report_path = args.context_dir / "context.json", args.context_dir / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (report["status"] != "completed" or sha(context_path) != report["context_sha256"]
            or sha(index_path) != report["sample_index_sha256"]
            or sha(ROOT / "scripts/audit_ct_context_availability.py") != report["script_sha256"]):
        raise ValueError("Exact completed context audit required")
    contexts = {row["id"]: row for row in json.loads(context_path.read_text(encoding="utf-8"))}
    index = json.loads(index_path.read_text(encoding="utf-8"))
    folds = {row["name"]: row for row in json.loads(fold_path.read_text(encoding="utf-8"))}
    fixed = json.loads(case_path.read_text(encoding="utf-8"))
    if len(fixed["examples"]) != 6:
        raise ValueError("Expected the unchanged six fixed cases")
    result = {"status": "completed_unjudged", "script_sha256": sha(Path(__file__)),
              "source_sha256": {str(case_path.relative_to(ROOT)): sha(case_path),
                                str(index_path.relative_to(ROOT)): sha(index_path),
                                str(fold_path.relative_to(ROOT)): sha(fold_path),
                                str(report_path): sha(report_path), str(context_path): sha(context_path)},
              "limits": ["No new selection, reranking, relevance score or tactical-duty label.",
                         "Only CT equipment, score and recorded CT throws are shown; opponent equipment and raw angles are omitted.",
                         "Different utility counts can be compatible with useful analogies; count agreement is not tactical relevance."],
              "examples": []}
    lines = ["# 固定案例的情境补充（未评分）", "",
             "沿用既有六图查询及两种模型的首位跨图候选，不改变任何排名。道具为截至20秒的已记录投掷数，火包含燃烧瓶和燃烧弹；不表示仍在生效的数量。装备为CT当前总装备价值。不同情境不自动代表候选错误，相同数量也不自动代表战术相似。", "",
             "| 查询地图 | 项目 | 片段地图/回合 | 回合开始前CT:T比分 | CT装备 | 烟/火/闪/雷/诱 |",
             "| --- | --- | --- | --- | ---: | --- |"]
    for case in fixed["examples"]:
        if case["methods"] != ["query", "graph_gru", "mlp_gru"] or len(case["records"]) != 3:
            raise ValueError("Fixed case order changed")
        annotated = {"map": case["map"], "tactical_relevance": None, "records": []}
        for method, selected in zip(case["methods"], case["records"]):
            record = selected["record"]
            if record != index[selected["index"]]:
                raise ValueError("Fixed case no longer matches sample index")
            if method != "query" and selected["index"] not in folds["G4__" + case["map"]]["train"]:
                raise ValueError("Candidate outside frozen source-training library")
            context = contexts[record["id"]]
            if [s["second"] for s in context["snapshots"]] != [10, 12, 15, 18, 20]:
                raise ValueError("Wrong context window")
            snapshots = [{"second": s["second"], "tick": s["tick"], "CT_equipment_total": s["equipment_total"]["CT"],
                          "utility": s["utility"]} for s in context["snapshots"]]
            annotated["records"].append({"method": method, "record": record,
                                         "score_before": context["score_before"], "snapshots": snapshots})
            counts = snapshots[-1]["utility"]["recorded_ct_throws"]
            tally = [counts.get("smokegrenade", 0), counts.get("incgrenade", 0) + counts.get("molotov", 0),
                     counts.get("flashbang", 0), counts.get("hegrenade", 0), counts.get("decoy", 0)]
            assert sum(tally) == sum(counts.values()) and snapshots[-1]["utility"]["unattributed_recorded_throws"] == 0
            score = context["score_before"]
            label = {"query": "查询", "graph_gru": "图模型候选", "mlp_gru": "非图模型候选"}[method]
            lines.append(f"| {case['map']} | {label} | {record['map']}/{record['round_number']} | {score['CT']}:{score['T']} | {snapshots[-1]['CT_equipment_total']:.0f} | {'/'.join(map(str, tally))} |")
        result["examples"].append(annotated)
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "evidence_context.json", result)
    (args.output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"fixed_cases": len(result["examples"]), "role_entries": sum(len(c["records"]) for c in result["examples"])}))


if __name__ == "__main__":
    main()
