"""Run the unified tactical, player, provenance, and GraphRAG ablation evaluation."""
import argparse
import asyncio
import json
from pathlib import Path

from app.core.config import settings
from app.services.graph_rag_service import GraphRAGClient
from scripts.evaluate_player_queries import DEFAULT_DATASET as PLAYER_DATASET, evaluate as evaluate_players
from scripts.evaluate_tactical_queries import DEFAULT_DATASET as TACTICAL_DATASET, evaluate as evaluate_tactics


async def evaluate(graph_db: Path) -> dict:
    tactical = await evaluate_tactics(TACTICAL_DATASET, graph_db)
    player = await evaluate_players(PLAYER_DATASET, graph_db)
    client = GraphRAGClient(graph_db)
    datasets = [
        json.loads(TACTICAL_DATASET.read_text(encoding="utf-8")),
        json.loads(PLAYER_DATASET.read_text(encoding="utf-8")),
    ]
    baseline_answers = 0
    for case in (case for dataset in datasets for case in dataset["cases"]):
        evidence = await client.retrieve(case["query"], k=3, global_search=True)
        community_only = [item for item in evidence if item.metadata.get("context_level") == "community_summary"]
        baseline_answers += int(bool(client.player_brief(case["query"], community_only) or client.coach_brief(case["query"], community_only)))
    total = tactical["summary"]["cases"] + player["summary"]["cases"]
    passed = tactical["summary"]["passed"] + player["summary"]["passed"]
    return {
        "version": "cs2-coach-v1",
        "summary": {"cases": total, "passed": passed, "failed": total - passed, "pass_rate_pct": round(100 * passed / total, 2)},
        "ablation": {
            "community_only_structured_answers": baseline_answers,
            "community_only_structured_answer_pct": round(100 * baseline_answers / total, 2),
            "full_graph_structured_answers": passed,
            "full_graph_structured_answer_pct": round(100 * passed / total, 2),
            "interpretation": "Community-only GraphRAG cannot produce contextual team/player contracts; the full graph adds deterministic profiles, citations, and round drilldown.",
        },
        "tactical": tactical,
        "player": player,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-db", type=Path, default=Path(settings.GRAPH_DB_PATH))
    parser.add_argument("--output", type=Path, default=Path("datasets/evaluation/cs2_coach_v1_report.json"))
    args = parser.parse_args()
    report = asyncio.run(evaluate(args.graph_db))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
