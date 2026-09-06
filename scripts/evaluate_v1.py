"""Run the unified tactical, player, provenance, and GraphRAG ablation evaluation."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.providers import get_kb_client
from app.services.graph_rag_service import GraphRAGClient
from scripts.evaluate_player_queries import DEFAULT_DATASET as PLAYER_DATASET, evaluate as evaluate_players
from scripts.evaluate_retrieval import (
    DEFAULT_DATASET as RETRIEVAL_DATASET,
    load_cases,
    retrieval_checks,
    summarize as summarize_retrieval,
)
from scripts.evaluate_tactical_queries import DEFAULT_DATASET as TACTICAL_DATASET, evaluate as evaluate_tactics


def _pct(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 2) if denominator else 0.0


async def _evaluate_retrieval_modes(
    graph: GraphRAGClient, dataset: Path = RETRIEVAL_DATASET,
) -> tuple[dict, bool]:
    cases = load_cases(dataset)
    kb = get_kb_client()
    vector_available = kb is not None
    if kb:
        # Benchmark retrieval only; never spend remote LLM tokens on query rewriting.
        kb.llm = None

    vector_rows = []
    graph_rows = []
    community_rows = []
    hybrid_rows = []
    no_rag_rows = []
    for case in cases:
        vector_evidence = []
        if kb:
            result = await kb.retrieve(
                case["query"], metadata_filter=case.get("metadata_filter", {}), k=5
            )
            vector_evidence = result.evidence
        graph_evidence = await graph.retrieve(
            case["query"],
            metadata_filter=case.get("metadata_filter", {}),
            task_id=case["task_id"],
            k=5,
            global_search=case.get("global_search", case["task_id"] == "map_context"),
        )
        community_evidence = [
            item
            for item in await graph.retrieve(
                case["query"],
                metadata_filter=case.get("metadata_filter", {}),
                k=5,
                global_search=True,
            )
            if item.metadata.get("context_level") == "community_summary"
        ]
        vector_checks = retrieval_checks(vector_evidence, case, graph=False)
        graph_checks = retrieval_checks(graph_evidence, case, graph=True)
        community_checks = retrieval_checks(community_evidence, case, graph=True)
        if case["expected"]["retrieve"]:
            hybrid_checks = {
                name: vector_checks[name] or graph_checks[name]
                for name in vector_checks
            }
        else:
            hybrid_checks = {"abstained": not vector_evidence and not graph_evidence}
        base = {
            "id": case["id"],
            "category": case["category"],
            "query": case["query"],
        }
        no_rag_rows.append({
            **base,
            "checks": retrieval_checks([], case, graph=False),
        })
        vector_rows.append({**base, "checks": vector_checks})
        graph_rows.append({**base, "checks": graph_checks})
        community_rows.append({**base, "checks": community_checks})
        hybrid_rows.append({**base, "checks": hybrid_checks})

    return {
        "no_rag": summarize_retrieval(no_rag_rows),
        "community_only": summarize_retrieval(community_rows),
        "vector_only": summarize_retrieval(vector_rows),
        "graph_only": summarize_retrieval(graph_rows),
        "hybrid": summarize_retrieval(hybrid_rows),
    }, vector_available


async def evaluate(
    graph_db: Path, retrieval_dataset: Path = RETRIEVAL_DATASET,
) -> dict:
    tactical = await evaluate_tactics(TACTICAL_DATASET, graph_db)
    player = await evaluate_players(PLAYER_DATASET, graph_db)
    client = GraphRAGClient(graph_db)
    datasets = [
        json.loads(TACTICAL_DATASET.read_text(encoding="utf-8")),
        json.loads(PLAYER_DATASET.read_text(encoding="utf-8")),
    ]
    baseline_answers = 0
    negative_cases = 0
    for case in (case for dataset in datasets for case in dataset["cases"]):
        negative_cases += int(case.get("category") == "negative")
        evidence = await client.retrieve(case["query"], k=3, global_search=True)
        community_only = [item for item in evidence if item.metadata.get("context_level") == "community_summary"]
        baseline_answers += int(bool(client.player_brief(case["query"], community_only) or client.coach_brief(case["query"], community_only)))
    total = tactical["summary"]["cases"] + player["summary"]["cases"]
    passed = tactical["summary"]["passed"] + player["summary"]["passed"]
    retrieval, vector_available = await _evaluate_retrieval_modes(client, retrieval_dataset)
    retrieval_points = retrieval["no_rag"]["checks_total"]
    total_points = total + retrieval_points
    contract_passes = {
        "no_rag": negative_cases,
        "community_only": negative_cases,
        "vector_only": negative_cases,
        "graph_only": passed,
        "hybrid": passed,
    }
    modes = {}
    for name, contract_passed in contract_passes.items():
        available = vector_available or name not in {"vector_only", "hybrid"}
        earned = contract_passed + retrieval[name]["checks_passed"]
        modes[name] = {
            "available": available,
            "contract": {
                "passed": contract_passed,
                "total": total,
                "pass_rate_pct": _pct(contract_passed, total),
            },
            "retrieval": retrieval[name],
            "score": {
                "earned_points": earned if available else None,
                "total_points": total_points,
                "pct": _pct(earned, total_points) if available else None,
            },
        }
    return {
        "version": "cs2-coach-v1",
        "summary": {"cases": total, "passed": passed, "failed": total - passed, "pass_rate_pct": round(100 * passed / total, 2)},
        "benchmark": {
            "dataset": str(retrieval_dataset),
            "formula": f"(structured contract cases passed + retrieval checks passed) / ({total} contract cases + {retrieval_points} retrieval checks)",
            "max_points": total_points,
            "modes": modes,
            "interpretation": "The score measures reproducible engineering behavior. It is not an expert rating of tactical insight or player quality.",
        },
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
    parser.add_argument("--retrieval-dataset", type=Path, default=RETRIEVAL_DATASET)
    parser.add_argument("--output", type=Path, default=Path("datasets/evaluation/cs2_coach_v1_report.json"))
    args = parser.parse_args()
    report = asyncio.run(evaluate(args.graph_db, args.retrieval_dataset))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    # Weaker ablations remain measurements; production graph/hybrid must regress red.
    modes = report["benchmark"]["modes"]
    retrieval_passed = all(
        modes[name]["available"]
        and modes[name]["retrieval"]["queries_passed"] == modes[name]["retrieval"]["queries"]
        for name in ("graph_only", "hybrid")
    )
    return 0 if report["summary"]["failed"] == 0 and retrieval_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
