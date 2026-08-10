"""Run a small, repeatable retrieval smoke evaluation against the local KB."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.providers import get_kb_client


CASES = [
    {"query": "Dust2 opening duel first kill", "map": "Dust2", "types": ["Opening Duel Evidence", "Round Event Evidence"]},
    {"query": "Mirage smoke flash molotov utility sequence", "map": "Mirage", "types": ["Round Event Evidence"]},
    {"query": "Ancient bomb plant retake round outcome", "map": "Ancient", "types": ["Round Event Evidence"]},
    {"query": "Nuke professional demo round events", "map": "Nuke", "types": ["Professional Match Summary", "Round Event Evidence"]},
]


async def evaluate() -> dict:
    client = get_kb_client()
    if not client:
        raise RuntimeError("Knowledge base is unavailable; check Milvus and DASHSCOPE_API_KEY.")
    # Evaluation must measure retrieval, not consume a remote query-rewrite call.
    client.llm = None
    rows = []
    for case in CASES:
        result = await client.retrieve(case["query"], metadata_filter={"map": case["map"]}, k=5)
        maps = {item.metadata.get("map") for item in result.evidence}
        types = {item.metadata.get("tactic_type") for item in result.evidence}
        rows.append(
            {
                "query": case["query"],
                "hit_at_5": bool(result.evidence),
                "map_match": case["map"] in maps,
                "type_match": bool(types.intersection(case["types"])),
                "evidence_count": len(result.evidence),
                "strategy": result.strategy,
                "confidence": round(result.confidence, 3),
                "corrected": result.corrected,
                "warnings": result.warnings,
            }
        )
    return {
        "cases": rows,
        "hit_at_5": sum(row["hit_at_5"] for row in rows) / len(rows),
        "map_accuracy": sum(row["map_match"] for row in rows) / len(rows),
        "type_accuracy": sum(row["type_match"] for row in rows) / len(rows),
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(evaluate()), ensure_ascii=False, indent=2))
