"""Exercise abstention at the public vector and graph retrieval boundaries."""
import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.services.graph_rag_service import GraphRAGClient
from app.services.rag_service import KnowledgeBaseClient

CASES = json.loads(Path('datasets/evaluation/retrieval_negatives_dev_v1.json').read_text())['cases']

@pytest.fixture
def graph(tmp_path):
    client = GraphRAGClient(tmp_path / 'graph.sqlite')
    with sqlite3.connect(client.db_path) as connection:
        connection.row_factory = sqlite3.Row
        client._create_schema(connection)
        for map_name in ('Mirage', 'Ancient', 'Dust2'):
            nodes, edges = client._graph_rows(tmp_path / f'{map_name}.dem', {
                'match_id': f'fixture-{map_name}', 'map_name': map_name,
                'rounds': [{'round_number': 1, 'winner': 'T', 'kills': [{
                    'tick': 100, 'killer': 'donk', 'killer_steamid': '111',
                    'killer_team': 'Spirit', 'killer_side': 'T',
                    'victim': 'NiKo', 'victim_steamid': '222',
                    'victim_team': 'Falcons', 'victim_side': 'CT',
                    'is_first_kill': True, 'weapon': 'ak47',
                }]}],
            })
            connection.executemany('INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?,?,?)', nodes)
            connection.executemany('INSERT OR IGNORE INTO edges VALUES (?,?,?,?)', edges)
        client._build_communities(connection)
    return client

class Store:
    def similarity_search_with_score(self, query, **kwargs):
        return [(Document(page_content='Spirit donk killed Falcons NiKo. Opening duel utility round.',
            metadata={'map':'Ancient','match_id':'fixture-Ancient','tactic_type':'Opening Duel Evidence'}), 1.0)]

@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_unknown_or_unrelated_query_abstains(graph, case):
    async def check():
        vector = await KnowledgeBaseClient(Store(), None).retrieve(case['query'], case['metadata_filter'])
        local = await graph.retrieve(case['query'], case['metadata_filter'], task_id='map_context')
        global_hits = await graph.retrieve(case['query'], case['metadata_filter'], global_search=True)
        assert not vector.evidence and not local and not global_hits, {
            'vector': len(vector.evidence), 'local': len(local), 'global': len(global_hits)}
    asyncio.run(check())

@pytest.mark.parametrize('query', [
    'Review donk performance on Ancient',
    'donk 在 Ancient 的首杀',
    'Spirit Ancient opening duel',
    '绿龙 Ancient 的首杀',
    'Compare donk and NiKo on Ancient',
    'Ancient opening duel first kill',
])
def test_supported_queries_keep_evidence(graph, query):
    async def check():
        assert (await KnowledgeBaseClient(Store(), None).retrieve(query)).evidence
        assert await graph.retrieve(query, {'map': 'Ancient'}, task_id='opening_duel')
        assert await graph.retrieve(query, {'map': 'Ancient'}, global_search=True)
    asyncio.run(check())


def test_match_filter_still_applies_to_both_graph_routes(graph):
    async def check():
        for global_search in (False, True):
            assert not await graph.retrieve('donk Ancient opening duel',
                {'map': 'Ancient', 'match_id': 'absent-match'}, global_search=global_search)
    asyncio.run(check())


def test_handle_substring_is_not_identity_evidence():
    class SimilarNameStore(Store):
        def similarity_search_with_score(self, query, **kwargs):
            return [(Document(page_content='donkClone opening duel on Ancient', metadata={}), 1.0)]
    result = asyncio.run(KnowledgeBaseClient(SimilarNameStore(), None).retrieve('donk 在 Ancient 的首杀'))
    assert not result.evidence


def test_comparison_cannot_drop_unknown_second_player(graph):
    async def check():
        query = 'Compare donk and GhostAim'
        assert not (await KnowledgeBaseClient(Store(), None).retrieve(query)).evidence
        assert not await graph.retrieve(query, global_search=True)
    asyncio.run(check())


def test_named_global_query_contains_matching_round_topic(graph):
    result = asyncio.run(graph.retrieve('donk Ancient opening duel', global_search=True))
    paths = [item for item in result if item.metadata.get('topic') == 'opening']
    assert paths and all('donk' in item.content for item in paths)


def test_entity_filter_precedes_graph_top_k(graph):
    with sqlite3.connect(graph.db_path) as connection:
        # A later round is the only round containing the requested player.
        nodes, edges = graph._graph_rows(Path('later.dem'), {
            'match_id': 'z-later', 'map_name': 'Ancient',
            'rounds': [{'round_number': 1, 'winner': 'T', 'kills': [{
                'tick': 100, 'killer': 'JL', 'killer_steamid': '999',
                'victim': 'NiKo', 'victim_steamid': '222',
                'is_first_kill': True, 'weapon': 'ak47',
            }]}],
        })
        connection.executemany('INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?,?,?)', nodes)
        connection.executemany('INSERT OR IGNORE INTO edges VALUES (?,?,?,?)', edges)
    result = asyncio.run(graph.retrieve('JL Ancient opening duel', {'map':'Ancient'}, k=1))
    assert result and 'JL' in result[0].content


@pytest.mark.parametrize('failed,available,exit_code', [(False, True, 0), (True, True, 1), (False, False, 1)])
def test_unified_benchmark_exit_reflects_retrieval(monkeypatch, tmp_path, failed, available, exit_code):
    from scripts import evaluate_v1
    async def evaluate(*args):
        return {'summary': {'failed': 0}, 'benchmark': {'modes': {
            name: {'available': available, 'retrieval': {'queries': 1, 'queries_passed': int(not failed)}}
            for name in ('graph_only', 'hybrid')
        }}}
    monkeypatch.setattr(evaluate_v1, 'evaluate', evaluate)
    monkeypatch.setattr('sys.argv', ['evaluate_v1', '--output', str(tmp_path / 'report.json')])
    assert evaluate_v1.main() == exit_code


def test_vector_benchmark_failure_returns_nonzero(monkeypatch):
    from scripts import evaluate_retrieval
    async def evaluate(*args):
        return {'queries': 2, 'queries_passed': 1}
    monkeypatch.setattr(evaluate_retrieval, 'evaluate', evaluate)
    monkeypatch.setattr('sys.argv', ['evaluate_retrieval'])
    assert evaluate_retrieval.main() == 1


@pytest.mark.parametrize('query,metadata', [
    ('Who made the first contact on Ancient', {}),
    ('Review the opening pick on Ancient', {}),
    ('哪一方先建立人数优势', {'map':'Ancient'}),
    ('投掷物协同的回合证据', {'map':'de_ancient'}),
])
def test_descriptions_and_explicit_map_context_are_not_unknown_entities(graph, query, metadata):
    async def check():
        assert (await KnowledgeBaseClient(Store(), None).retrieve(query, metadata)).evidence
        assert await graph.retrieve(query, metadata, task_id='map_context')
        if not metadata:  # Global search has no caller-supplied task topic.
            assert await graph.retrieve(query, metadata, global_search=True)
    asyncio.run(check())
