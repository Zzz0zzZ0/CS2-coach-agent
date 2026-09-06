"""Run the fixed retrieval benchmark against the local vector knowledge base."""
import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.providers import get_kb_client


DEFAULT_DATASET = Path("datasets/evaluation/retrieval_queries_v2.json")


def load_cases(path: Path = DEFAULT_DATASET) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def evidence_text(evidence) -> str:
    return " ".join(
        f"{item.content} {json.dumps(item.metadata, ensure_ascii=False)}"
        for item in evidence
    ).lower()


def retrieval_checks(evidence, case: dict, *, graph: bool) -> dict[str, bool]:
    expected = case["expected"]
    if not expected["retrieve"]:
        return {"abstained": not evidence}

    metadata = [item.metadata for item in evidence]
    checks = {
        "retrieved": bool(evidence),
        "map_match": any(item.get("map") == expected["map"] for item in metadata),
        "intent_match": (
            any(item.get("topic") == expected["graph_topic"] for item in metadata)
            if graph
            else any(item.get("tactic_type") in expected["vector_types"] for item in metadata)
        ),
    }
    entity_terms = expected.get("entity_terms", [])
    if entity_terms:
        text = evidence_text(evidence)
        checks["entity_match"] = any(term.lower() in text for term in entity_terms)
    return checks


def summarize(rows: list[dict]) -> dict:
    checks = [passed for row in rows for passed in row["checks"].values()]
    categories = Counter(row["category"] for row in rows)
    category_passes = Counter(
        row["category"] for row in rows if all(row["checks"].values())
    )
    return {
        "queries": len(rows),
        "queries_passed": sum(all(row["checks"].values()) for row in rows),
        "checks_passed": sum(checks),
        "checks_total": len(checks),
        "quality_pct": round(100 * sum(checks) / len(checks), 2) if checks else 0.0,
        "categories": {
            name: {"passed": category_passes[name], "cases": count}
            for name, count in sorted(categories.items())
        },
        "cases": rows,
    }


async def evaluate(dataset: Path = DEFAULT_DATASET) -> dict:
    client = get_kb_client()
    if not client:
        raise RuntimeError("Knowledge base is unavailable; check Milvus.")
    # Measure local retrieval only; do not consume a remote query-rewrite call.
    client.llm = None
    rows = []
    for case in load_cases(dataset):
        result = await client.retrieve(
            case["query"], metadata_filter=case.get("metadata_filter", {}), k=5
        )
        checks = retrieval_checks(result.evidence, case, graph=False)
        rows.append({
            "id": case["id"],
            "category": case["category"],
            "query": case["query"],
            "passed": all(checks.values()),
            "checks": checks,
            "evidence_count": len(result.evidence),
            "strategy": result.strategy,
            "confidence": round(result.confidence, 3),
            "corrected": result.corrected,
            "warnings": result.warnings,
        })
    return {"dataset_version": json.loads(dataset.read_text())["version"], **summarize(rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(evaluate(args.dataset))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["queries_passed"] == report["queries"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
