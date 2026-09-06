import asyncio
from pathlib import Path

from langchain_core.documents import Document

from app.services.rag_service import KnowledgeBaseClient
from app.services.rag_service import Evidence
from scripts.evaluate_retrieval import load_cases, retrieval_checks, summarize


class FakeVectorStore:
    def __init__(self):
        self.calls = []

    def similarity_search_with_score(self, query, k=4, expr=None):
        self.calls.append((query, k, expr))
        return [
            (
                Document(
                    page_content="Dust2 opening duel and first kill evidence",
                    metadata={
                        "map": "Dust2",
                        "match_id": "2396021",
                        "round_number": "4",
                        "tactic_type": "Opening Duel Evidence",
                        "source": "hltv_demo:2396021",
                    },
                ),
                0.1,
            )
        ]


def test_retrieve_normalizes_map_filter_and_preserves_citations():
    store = FakeVectorStore()
    client = KnowledgeBaseClient(store, llm=None)

    result = asyncio.run(
        client.retrieve(
            "Dust2 opening duel",
            metadata_filter={"map": "de_dust2"},
            query_variants=["Dust2 first kill trade"],
        )
    )

    assert result.filters == {"map": "Dust2"}
    assert len(result.evidence) == 1
    assert "[E1]" in result.context
    assert "2396021" in result.context
    assert all(call[2] == "map == 'Dust2'" for call in store.calls)


def test_retrieve_adds_parent_context_and_corrective_trace():
    class LowSignalStore(FakeVectorStore):
        def similarity_search_with_score(self, query, k=4, expr=None):
            return [
                (
                    Document(
                        page_content="Observed round event.",
                        metadata={
                            "map": "Dust2",
                            "parent_content": "Professional match summary for Dust2.",
                            "tactic_type": "Round Event Evidence",
                        },
                    ),
                    0.1,
                )
            ]

    result = asyncio.run(
        KnowledgeBaseClient(LowSignalStore(), llm=None).retrieve("CS2 tactical unknown")
    )

    assert result.corrected is True
    assert result.strategy == "dense_lexical"
    assert "Parent context" in result.context


def test_retrieve_expands_chinese_team_alias_before_search():
    store = FakeVectorStore()

    asyncio.run(KnowledgeBaseClient(store, llm=None).retrieve("猎鹰 Dust2 首杀"))

    assert any("falcons" in query.lower() for query, _, _ in store.calls)


def test_retrieve_abstains_from_unrelated_evidence():
    result = asyncio.run(
        KnowledgeBaseClient(FakeVectorStore(), llm=None).retrieve(
            "Mars rover battery telemetry"
        )
    )

    assert result.evidence == []


def test_retrieve_rejects_evidence_missing_an_explicit_player():
    result = asyncio.run(
        KnowledgeBaseClient(FakeVectorStore(), llm=None).retrieve(
            "s1mple 在 Ancient 的首杀", metadata_filter={"map": "Ancient"}
        )
    )

    assert result.evidence == []


def test_benchmark_retrieval_score_uses_explicit_checks():
    case = {
        "expected": {
            "retrieve": True,
            "map": "Mirage",
            "vector_types": ["Round Event Evidence"],
            "graph_topic": "utility",
        },
    }
    evidence = [
        Evidence(
            content="utility sequence",
            metadata={"map": "Mirage", "tactic_type": "Round Event Evidence"},
            score=1.0,
            source_id="round:1",
        )
    ]

    checks = retrieval_checks(evidence, case, graph=False)
    summary = summarize([{"category": "map_topic", "checks": checks}])

    assert checks == {"retrieved": True, "map_match": True, "intent_match": True}
    assert summary["checks_passed"] == 3
    assert summary["quality_pct"] == 100.0


def test_retrieval_dataset_has_fixed_coverage_and_unique_ids():
    cases = load_cases()

    assert len(cases) == 50
    assert len({case["id"] for case in cases}) == 50
    assert sum(case["category"] == "negative" for case in cases) == 4
    assert retrieval_checks([], next(case for case in cases if case["category"] == "negative"), graph=False) == {"abstained": True}

    holdout = load_cases(Path("datasets/evaluation/retrieval_queries_holdout_v1.json"))
    assert len(holdout) == 30
    assert {case["id"] for case in cases}.isdisjoint(case["id"] for case in holdout)


def test_chinese_utility_query_matches_plural_round_document_vocabulary():
    store = FakeVectorStore()
    asyncio.run(KnowledgeBaseClient(store, llm=None).retrieve('Ancient 道具协同'))
    assert any('grenade' in query.split() and 'grenades' in query.split() for query, _, _ in store.calls)
