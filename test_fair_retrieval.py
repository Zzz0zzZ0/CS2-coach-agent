import copy
import json
import math
import sqlite3

import numpy as np
import pytest

from scripts.evaluate_fair_retrieval import (
    build_index, digest, export_corpus, metrics, ranks, reviewed_qrels, validate_inputs,
)


def sample():
    docs = []
    for i, (map_name, entity) in enumerate((("Nuke", "alpha"), ("Nuke", "bravo"), ("Mirage", "alpha"))):
        docs.append({"id": f"r{i}", "match_id": "m1", "map": map_name, "round": i + 1,
                     "entities": [entity], "text": f"{entity} opening kill on {map_name}",
                     "events": [{"id": f"e{i}", "kind": "kill", "properties": {}}], "links": [["KILL", f"e{i}"]]})
    queries = {"cases": [{"id": "q1", "query": "alpha opening kill", "filters": {"map": "Nuke"}, "entities": ["alpha"], "event_kind": "kill"}]}
    return docs, queries


def test_same_prefilters_apply_before_top_k_to_every_method():
    docs, queries = sample()
    validate_inputs(docs, queries)
    db = build_index(docs)
    # The two out-of-scope rows have larger dense scores than the valid row.
    vectors = np.array([[0.1, 1], [0.8, 1], [1, 1]])
    on, _ = ranks(db, docs, queries["cases"][0], True, np.array([1, 0]), vectors, 1)
    assert all(values == [0] for values in on.values())
    off, _ = ranks(db, docs, queries["cases"][0], False, np.array([1, 0]), vectors, 5)
    assert all(set(values) == {0, 1} for values in off.values())
    missing = {**queries["cases"][0], "entities": ["not-present"]}
    rejected, _ = ranks(db, docs, missing, True, np.array([1, 0]), vectors, 5)
    assert all(values == [] for values in rejected.values())
    db.close()


def test_metrics_use_all_relevant_documents_and_graded_discount():
    result = metrics(["wrong", "a"], {"a": 3, "b": 1, "c": 1}, k=2)
    assert result["recall_at_k"] == 1 / 3
    assert result["ndcg_at_k"] == pytest.approx((7 / math.log2(3)) / (7 + 1 / math.log2(3)))
    assert metrics([], {"a": 1})["false_abstention"] is True
    assert metrics(["wrong"], {})["false_retrieval"] is True
    assert metrics([], {})["recall_at_k"] is None
    with pytest.raises(ValueError, match="Duplicate"):
        metrics(["a", "a"], {"a": 1})


def test_unreviewed_or_incomplete_labels_cannot_publish_quality_metrics():
    docs, queries = sample()
    packet = {"corpus_sha256": "c", "queries_sha256": "q", "judgments": [
        {"query_id": "q1", "status": "pending_review", "exhaustive": False, "relevance": []}]}
    assert reviewed_qrels(packet, docs, queries, "c", "q") is None
    item = packet["judgments"][0]
    item.update(status="approved", reviewer="independent-reviewer", reviewed_at="2026-09-06", exhaustive=True,
                scope_basis="Checked all eligible rounds", relevance=[{"source_round_id": "r0", "grade": 2, "basis": "Original kill event e0"}])
    assert reviewed_qrels(packet, docs, queries, "c", "q") == {"q1": {"r0": 2}}
    with pytest.raises(ValueError, match="hashes"):
        reviewed_qrels(packet, docs, queries, "changed", "q")
    item["relevance"].append(copy.deepcopy(item["relevance"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        reviewed_qrels(packet, docs, queries, "c", "q")


def test_graph_missing_evidence_fails_instead_of_becoming_a_weaker_baseline():
    docs, queries = sample()
    docs[0]["links"] = []
    with pytest.raises(ValueError, match="mismatch"):
        validate_inputs(docs, queries)


def test_corpus_export_preserves_sources_and_never_overwrites(tmp_path):
    source, destination = tmp_path / "graph.sqlite", tmp_path / "corpus.jsonl"
    db = sqlite3.connect(source)
    db.executescript("CREATE TABLE nodes(node_id,node_type,map_name,match_id,round_number,properties); CREATE TABLE edges(source_id,relation,target_id);")
    roster = [{"name": "alpha", "steamid": "111", "team": "A", "side": "T"}]
    db.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?)", [
        ("r1", "round", "Nuke", "m1", "1", json.dumps({"participants_complete": True, "participants": roster, "winner": "T"})),
        ("e1", "event", "Nuke", "m1", "1", json.dumps({"kind": "plant", "planter": "alpha", "site": "B"})),
    ])
    db.execute("INSERT INTO edges VALUES ('r1','PLANTS_BOMB','e1')")
    db.commit()
    db.close()
    before = digest(source)
    result = export_corpus(source, destination)
    assert result["rounds"] == 1 and digest(source) == before
    doc = json.loads(destination.read_text())
    assert "alpha bomb plant site B" in doc["text"]
    assert doc["events"][0]["id"] == "e1" and doc["links"] == [["PLANTS_BOMB", "e1"]]
    with pytest.raises(FileExistsError):
        export_corpus(source, destination)
