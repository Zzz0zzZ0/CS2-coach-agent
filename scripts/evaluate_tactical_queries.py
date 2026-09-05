"""Evaluate natural-language tactical GraphRAG queries without manual labels."""
import argparse
import asyncio
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.services.graph_rag_service import GraphRAGClient


DEFAULT_DATASET = Path("datasets/evaluation/tactical_queries_v1.json")
TACTICAL_LEVELS = {"team_tactical_profile", "team_tactical_comparison"}


def _percent(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 2) if denominator else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(percentile * len(ordered)) - 1)], 2)


def _canonical_profile(client: GraphRAGClient, expected: dict) -> dict | None:
    map_name = None if expected.get("map") in {None, "All"} else expected["map"]
    side = None if expected.get("side") in {None, "Both"} else expected["side"]
    return client.team_tactics(
        expected["team"],
        map_name=map_name,
        side=side,
        opponent=expected.get("opponent"),
    )


def _score_positive(client: GraphRAGClient, evidence, expected: dict) -> dict[str, bool]:
    metadata = evidence.metadata
    checks = {
        "context": metadata.get("context_level") == expected["context_level"],
        "map": metadata.get("map") == expected.get("map", "All"),
        "side": metadata.get("side") == expected.get("side", "Both"),
    }
    if expected["context_level"] == "team_tactical_profile":
        canonical = _canonical_profile(client, expected)
        checks.update({
            "team": metadata.get("team") == expected["team"],
            "opponent": metadata.get("opponent") == expected.get("opponent"),
            "minimum_sample": metadata.get("sample_size", {}).get("rounds", 0) >= expected.get("min_rounds", 0),
            "numeric_consistency": bool(canonical) and all(
                metadata.get(key) == canonical.get(key)
                for key in ("sample_size", "outcomes", "conversions")
            ),
            "source_coverage": metadata.get("source_round_count", 0) > 0,
        })
        return checks

    expected_teams = expected["teams"]
    profiles = metadata.get("profiles", [])
    profile_by_team = {profile.get("team"): profile for profile in profiles}
    numeric_consistency = True
    enough_rounds = True
    for team in expected_teams:
        canonical = _canonical_profile(client, {**expected, "team": team, "opponent": None})
        actual = profile_by_team.get(team, {})
        numeric_consistency = numeric_consistency and bool(canonical) and all(
            actual.get(key) == canonical.get(key)
            for key in ("sample_size", "outcomes", "conversions")
        )
        enough_rounds = enough_rounds and actual.get("sample_size", {}).get("rounds", 0) >= expected.get("min_rounds", 0)
    checks.update({
        "teams": metadata.get("teams") == expected_teams,
        "minimum_sample": enough_rounds,
        "numeric_consistency": numeric_consistency,
        "source_coverage": metadata.get("source_round_count", 0) > 0,
    })
    return checks


async def evaluate(dataset_path: Path, graph_db: Path) -> dict:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    client = GraphRAGClient(graph_db)
    if not client.available():
        raise RuntimeError(f"Graph database is unavailable: {graph_db}")

    rows = []
    for case in dataset["cases"]:
        started = time.perf_counter()
        evidence = await client.retrieve(case["query"], k=3, global_search=True)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        brief = client.coach_brief(case["query"], evidence)
        tactical = next(
            (item for item in evidence if item.metadata.get("context_level") in TACTICAL_LEVELS),
            None,
        )
        expected = case["expected"]
        if expected["structured"]:
            first_source = brief.get("sources", [{}])[0].get("round_id") if brief and brief.get("sources") else None
            checks = {
                "structured_result": tactical is not None,
                "coach_brief": brief is not None,
                "coach_sources": bool(brief and brief.get("sources")),
                "coach_caveat": bool(brief and "因果" in brief.get("caveat", "")),
                "round_drilldown": bool(first_source and client.round_detail(first_source)),
                "key_round_filters": bool(brief and brief.get("round_groups")),
            }
            if tactical:
                checks.update(_score_positive(client, tactical, expected))
        else:
            checks = {
                "structured_rejection": tactical is None,
                "coach_rejection": brief is None,
            }
        failures = [name for name, passed in checks.items() if not passed]
        rows.append({
            "id": case["id"],
            "category": case["category"],
            "query": case["query"],
            "passed": not failures,
            "checks": checks,
            "failures": failures,
            "latency_ms": latency_ms,
            "result_type": tactical.metadata.get("context_level") if tactical else None,
            "source_id": tactical.source_id if tactical else None,
            "coach_brief_kind": brief.get("kind") if brief else None,
        })

    positive_rows = [row for row in rows if row["category"] != "negative"]
    latencies = [row["latency_ms"] for row in rows]
    category_counts = Counter(row["category"] for row in rows)
    category_passes = Counter(row["category"] for row in rows if row["passed"])
    return {
        "dataset_version": dataset["version"],
        "graph": client.stats(),
        "summary": {
            "cases": len(rows),
            "passed": sum(row["passed"] for row in rows),
            "failed": sum(not row["passed"] for row in rows),
            "pass_rate_pct": _percent(sum(row["passed"] for row in rows), len(rows)),
            "context_accuracy_pct": _percent(
                sum(row["checks"].get("context", row["checks"].get("structured_rejection", False)) for row in rows),
                len(rows),
            ),
            "numeric_consistency_pct": _percent(
                sum(row["checks"].get("numeric_consistency", False) for row in positive_rows),
                len(positive_rows),
            ),
            "source_coverage_pct": _percent(
                sum(row["checks"].get("source_coverage", False) for row in positive_rows),
                len(positive_rows),
            ),
            "coach_brief_coverage_pct": _percent(
                sum(row["checks"].get("coach_brief", row["checks"].get("coach_rejection", False)) for row in rows),
                len(rows),
            ),
            "round_drilldown_coverage_pct": _percent(
                sum(row["checks"].get("round_drilldown", False) for row in positive_rows),
                len(positive_rows),
            ),
            "key_round_filter_coverage_pct": _percent(
                sum(row["checks"].get("key_round_filters", False) for row in positive_rows),
                len(positive_rows),
            ),
            "latency_ms": {
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
            },
            "categories": {
                name: {"passed": category_passes[name], "cases": count}
                for name, count in sorted(category_counts.items())
            },
        },
        "cases": rows,
        "limitations": [
            "Silver-standard contract evaluation, not expert tactical ground truth.",
            "Numeric checks validate query routing against deterministic graph aggregation; they do not prove tactical causality.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--graph-db", type=Path, default=Path(settings.GRAPH_DB_PATH))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(evaluate(args.dataset, args.graph_db))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
