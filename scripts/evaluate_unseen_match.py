"""Evaluate a preselected complete series without adding it to historical retrieval data."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.evaluate_fair_retrieval import digest, write_json


def preflight(selection, graph_db):
    with sqlite3.connect(graph_db.resolve().as_uri() + "?mode=ro", uri=True) as db:
        historical = {row[0] for row in db.execute("SELECT DISTINCT match_id FROM nodes WHERE node_type='match'")}
    selected = [m["match_id"] for m in selection["matches"]]
    if not selected or len(set(selected)) != len(selected) or historical & set(selected):
        raise ValueError("New series must be nonempty, unique and disjoint from historical matches")
    if historical != set(selection["historical_match_ids"]) or digest(graph_db) != selection["historical_graph_sha256"]:
        raise ValueError("Historical corpus changed after selection freeze")
    for name, expected in selection["implementation_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError(f"Implementation changed after selection freeze: {name}")
    return historical


def score_checks(parsed, result, expected_scores):
    rounds = parsed["rounds"]
    return {"round_count": len(rounds) == sum(expected_scores.values()),
            "public_team_score": result.metrics.rounds_won_by_team == expected_scores,
            "complete_rosters": all(r.get("participants_complete") for r in rounds),
            "metric_round_count": result.metrics.rounds_total == len(rounds),
            "current_sources": len(result.current_evidence) == len(rounds) + 1,
            "verification": result.verification_report.get("status") == "pass",
            "no_model_usage": result.model_usage == {}}


async def evaluate(args):
    # No model/provider constructors, services, task queue or knowledge ingestion.
    os.environ.update(PYTHON_DOTENV_DISABLED="1", DASHSCOPE_API_KEY="", DASHSCOPE_KEY_FILE="/nonexistent/cs2-evaluation-key",
                      LLM_AUXILIARY_CALLS_ENABLED="false", AUTO_INGEST_ENABLED="false")
    from app.domain.match_models import MatchWebhookPayload
    from app.services.analysis_pipeline import AnalysisPipeline
    from app.services.graph_rag_service import GraphRAGClient, _map_name
    from app.services.parser_service import TacticalDemoParser
    selection = json.loads(args.selection.read_text())
    historical = preflight(selection, args.graph_db)
    demo_dir = args.demo_dir.resolve()
    historical_dir = args.historical_demo_dir.resolve()
    if demo_dir == historical_dir or historical_dir in demo_dir.parents or demo_dir in historical_dir.parents:
        raise ValueError("New demo directory must be isolated from historical demos")
    files = sorted(demo_dir.glob("*.dem"))
    if not files:
        raise ValueError("No new Demo files; refusing an empty successful evaluation")
    selected = {m["match_id"]: m for m in selection["matches"]}
    assignments, fingerprints = [], set()
    old_by_size = {}
    for old in historical_dir.glob("*.dem"):
        old_by_size.setdefault(old.stat().st_size, []).append(old)
    for path in files:
        matches = [mid for mid in selected if re.search(rf"(?:^|_){re.escape(mid)}(?:_|\.)", path.name)]
        if len(matches) != 1:
            raise ValueError(f"Demo filename must identify exactly one selected match: {path.name}")
        checksum = digest(path)
        if checksum in fingerprints or any(digest(old) == checksum for old in old_by_size.get(path.stat().st_size, [])):
            raise ValueError(f"Duplicate Demo content: {path.name}")
        fingerprints.add(checksum)
        assignments.append((path, selected[matches[0]], checksum))
    graph = GraphRAGClient(args.graph_db)
    rows, observed = [], Counter()
    for path, match, checksum in assignments:
        start = time.perf_counter()
        print(f"Parsing isolated Demo {path.name}", flush=True)
        parsed = TacticalDemoParser(str(path)).parse_to_dict()
        if not parsed or not parsed.get("rounds"):
            rows.append({"file": path.name, "sha256": checksum, "passed": False, "error": "parser_returned_no_rounds"})
            continue
        map_name = _map_name(parsed["map_name"])
        mid = match["match_id"]
        observed[(mid, map_name)] += 1
        if map_name not in match["maps_played"]:
            rows.append({"file": path.name, "sha256": checksum, "passed": False, "error": "unexpected_map", "map": map_name})
            continue
        payload = MatchWebhookPayload(**{**parsed, "match_id": mid, "map_name": map_name})
        result = await AnalysisPipeline(None, None, graph).analyze(payload)
        checks = score_checks(parsed, result, match["public_map_scores"][map_name])
        # Current match facts must stay in C sources; historical retrieval must
        # not quietly cite the held-out series as an indexed prior observation.
        checks["historical_sources_disjoint"] = all(str(e.get("metadata", {}).get("match_id", "")) != mid for e in result.retrieval_evidence)
        checks["historical_evidence_present"] = bool(result.retrieval_evidence)
        artifact = args.output.parent / (args.output.stem + f"_{mid}_{map_name}.json")
        write_json(artifact, result.model_dump())
        rows.append({"file": path.name, "sha256": checksum, "match_id": mid, "map": map_name,
                     "rounds": len(parsed["rounds"]), "complete_rosters": sum(bool(r.get("participants_complete")) for r in parsed["rounds"]),
                     "team_score": result.metrics.rounds_won_by_team, "kills": result.metrics.kills_total,
                     "grenades": result.metrics.grenades_total, "flash_blinds": result.metrics.flash_blinds_total,
                     "plants": result.metrics.plants_total, "checks": checks, "passed": all(checks.values()),
                     "latency_ms": (time.perf_counter() - start) * 1000, "result": str(artifact)})
    required = Counter({(m["match_id"], map_name): 1 for m in selection["matches"] for map_name in m["maps_played"]})
    complete = observed == required
    unchanged = digest(args.graph_db) == selection["historical_graph_sha256"]
    return {"version": "unseen-pipeline-pilot-v1", "created_at": datetime.now(timezone.utc).isoformat(),
            "selection_sha256": digest(args.selection), "evaluator_sha256": digest(__file__),
            "historical_match_ids": sorted(historical), "historical_graph_unchanged": unchanged,
            "complete_series": complete, "series_count": len(selected), "maps": rows,
            "passed": complete and unchanged and all(r["passed"] for r in rows),
            "scope": "Single-series deterministic pipeline engineering check; not retrieval generalization, expert coaching validation or an estimate across independent matches.",
            "model_calls": 0, "historical_vector_store": "not connected or modified"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--demo-dir", type=Path, required=True)
    parser.add_argument("--historical-demo-dir", type=Path, default=Path("data/demos"))
    parser.add_argument("--graph-db", type=Path, default=Path("data/graph/cs2_graph.sqlite"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; preserve previous attempts and choose a new path")
    def denied(*args, **kwargs):
        raise RuntimeError("Network access forbidden during isolated evaluation")
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    report = asyncio.run(evaluate(args))
    write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
