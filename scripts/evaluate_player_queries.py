"""Evaluate contextual player GraphRAG queries without manual labels."""
import argparse
import asyncio
import json
import hashlib
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.services.graph_rag_service import GraphRAGClient

DEFAULT_DATASET = Path("datasets/evaluation/player_queries_v1.json")


def _percent(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 2) if denominator else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(percentile * len(ordered)) - 1)], 2)


def check_grounded_claims(brief: dict | None, profiles: list[dict]) -> tuple[bool, bool]:
    if not brief or not brief.get("claims"):
        return False, False
    by_player = {profile["player_id"]: profile for profile in profiles}
    by_source = {source["id"]: source for source in brief["sources"]}
    metrics_ok = {scope["player_id"] for scope in brief.get("sample_scopes", [])} == set(by_player)
    for scope in brief.get("sample_scopes", []):
        profile = by_player.get(scope["player_id"], {})
        metrics_ok &= all(scope.get(key) == profile.get(key) for key in ("filters", "sample_size", "data_quality", "combat", "rates_per_100_rounds"))
        metrics_ok &= scope.get("match_ids") == profile.get("sample_scope", {}).get("match_ids")
    citations_ok = len(by_source) == len(brief["sources"])
    for claim in brief["claims"]:
        profile = by_player.get(claim["player_id"])
        group = next((row for row in (profile or {}).get("behavior_outcomes", {}).get("groups", [])
                      if row["key"] == claim["metric"]), None)
        if not group:
            return False, False
        metrics_ok &= claim["scope"] == profile["filters"] and claim["sample_size"] == profile["sample_size"]
        metrics_ok &= all(claim[key] == {field:value for field,value in group[key].items() if field != "examples"}
                          for key in ("observed", "not_observed"))
        citations_ok &= set(claim["citation_ids"]) == {ref["citation_id"] for ref in claim["evidence_refs"]}
        expected_outcomes = {(cohort, sample["outcome"]) for cohort in ("observed", "not_observed") for sample in group[cohort]["examples"]}
        citations_ok &= {(ref["cohort"], ref["outcome"]) for ref in claim["evidence_refs"]} == expected_outcomes
        for ref in claim["evidence_refs"]:
            source = by_source.get(ref["citation_id"])
            allowed = group.get(ref["cohort"], {}).get("examples", [])
            citations_ok &= bool(source and source["player_id"] == claim["player_id"] and any(
                sample["source_id"] == source["round_id"] and sample["team"] == source["team"]
                and sample["outcome"] == ref["outcome"] == source["outcome"] for sample in allowed))
    return bool(metrics_ok), bool(citations_ok)


async def evaluate(dataset_path: Path, graph_db: Path) -> dict:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    client = GraphRAGClient(graph_db)
    rows = []
    for case in dataset["cases"]:
        started = time.perf_counter()
        evidence = await client.retrieve(case["query"], k=3, global_search=True)
        latency = round((time.perf_counter() - started) * 1000, 2)
        player_evidence = next((item for item in evidence if item.metadata.get("context_level", "").startswith("player_")), None)
        brief = client.player_brief(case["query"], evidence)
        expected = case["expected"]
        profiles = player_evidence.metadata.get("profiles", []) if player_evidence else []
        expected_names = expected["players"]
        canonical = [
            client.player_context(
                name,
                map_name=None if expected["map"] == "All" else expected["map"],
                side=None if expected["side"] == "Both" else expected["side"],
                opponent=expected.get("opponent"),
            )
            for name in expected_names
        ]
        first_source = brief.get("sources", [{}])[0].get("round_id") if brief and brief.get("sources") else None
        grounded, citations = check_grounded_claims(brief, profiles)
        checks = {
            "context": bool(player_evidence and player_evidence.metadata.get("context_level") == expected["context_level"]),
            "players": [profile.get("name") for profile in profiles] == expected_names,
            "map": bool(player_evidence and player_evidence.metadata.get("map") == expected["map"]),
            "side": bool(player_evidence and player_evidence.metadata.get("side") == expected["side"]),
            "opponent": bool(player_evidence and player_evidence.metadata.get("opponent") == expected.get("opponent")),
            "minimum_sample": len(profiles) == len(expected_names) and all(profile["sample_size"]["rounds"] >= expected["min_rounds"] for profile in profiles),
            "numeric_consistency": len(profiles) == len(canonical) and all(
                expected_profile is not None
                and actual.get("sample_size") == expected_profile.get("sample_size")
                and actual.get("combat") == expected_profile.get("combat")
                and actual.get("rates_per_100_rounds") == expected_profile.get("rates_per_100_rounds")
                for actual, expected_profile in zip(profiles, canonical)
            ),
            "coach_brief": bool(brief),
            "grounded_claims": grounded,
            "citation_grounding": citations,
            "requested_behavior": "focus" not in expected or bool(brief and all(claim["metric"] == expected["focus"] for claim in brief["claims"])),
            "source_coverage": bool(brief and brief.get("sources")),
            "round_drilldown": bool(first_source and client.round_detail(first_source)),
        }
        failures = [name for name, passed in checks.items() if not passed]
        rows.append({"id": case["id"], "category": case["category"], "query": case["query"], "passed": not failures, "checks": checks, "failures": failures, "latency_ms": latency})
    passed = sum(row["passed"] for row in rows)
    latencies = [row["latency_ms"] for row in rows]
    return {
        "dataset_version": dataset["version"],
        "artifact_hashes": {"dataset": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                            "evaluator": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                            "graph_service": hashlib.sha256(Path(GraphRAGClient.__module__.replace(".", "/") + ".py").read_bytes()).hexdigest()},
        "summary": {
            "cases": len(rows),
            "passed": passed,
            "failed": len(rows) - passed,
            "pass_rate_pct": _percent(passed, len(rows)),
            "context_accuracy_pct": _percent(sum(row["checks"]["context"] for row in rows), len(rows)),
            "numeric_consistency_pct": _percent(sum(row["checks"]["numeric_consistency"] for row in rows), len(rows)),
            "source_coverage_pct": _percent(sum(row["checks"]["source_coverage"] for row in rows), len(rows)),
            "round_drilldown_coverage_pct": _percent(sum(row["checks"]["round_drilldown"] for row in rows), len(rows)),
            "latency_ms": {
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
            },
        },
        "cases": rows,
        "limitations": ["Deterministic contract evaluation, not an expert rating of player decision quality. Claim grounding checks structured metrics and cohort citations, not independent label correctness."],
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
