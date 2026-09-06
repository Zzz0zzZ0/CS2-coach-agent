import json
import sqlite3
from types import SimpleNamespace

import pytest

from scripts.evaluate_fair_retrieval import digest
from scripts.evaluate_unseen_match import preflight, score_checks


def test_unseen_preflight_rejects_match_overlap_and_changed_corpus(tmp_path):
    path = tmp_path / "graph.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE nodes(match_id TEXT,node_type TEXT)")
        db.execute("INSERT INTO nodes VALUES ('old','match')")
    selection = {"historical_match_ids": ["old"], "historical_graph_sha256": digest(path),
                 "matches": [{"match_id": "new"}], "implementation_sha256": {}}
    assert preflight(selection, path) == {"old"}
    selection["matches"] = [{"match_id": "old"}]
    with pytest.raises(ValueError, match="disjoint"):
        preflight(selection, path)
    selection["matches"] = [{"match_id": "new"}]
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO nodes VALUES ('leaked','match')")
    with pytest.raises(ValueError, match="changed"):
        preflight(selection, path)


def test_public_score_is_independent_of_internal_metric_consistency():
    parsed = {"rounds": [{"participants_complete": True}, {"participants_complete": True}]}
    result = SimpleNamespace(metrics=SimpleNamespace(rounds_total=2, rounds_won_by_team={"A": 1, "B": 1}),
                             current_evidence=[{}, {}, {}], verification_report={"status": "pass"}, model_usage={})
    checks = score_checks(parsed, result, {"A": 2, "B": 0})
    assert checks["metric_round_count"] and checks["round_count"]
    assert not checks["public_team_score"]
    result.metrics.rounds_won_by_team = {"A": 2, "B": 0}
    assert all(score_checks(parsed, result, {"A": 2, "B": 0}).values())
