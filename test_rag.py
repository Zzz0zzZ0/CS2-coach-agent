import asyncio

from langchain_core.documents import Document

from app.services.rag_service import KnowledgeBaseClient


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

    result = asyncio.run(KnowledgeBaseClient(LowSignalStore(), llm=None).retrieve("unknown"))

    assert result.corrected is True
    assert result.strategy == "dense_lexical"
    assert "Parent context" in result.context
