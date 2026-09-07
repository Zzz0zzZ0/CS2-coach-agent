"""Frozen development expressions plus independent numeric failure boundaries."""
import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routers import graph as graph_router
from app.services.relation_query_service import parse_relation, search_relations
from app.services.rag_service import KnowledgeBaseClient
from app.agentic.nodes.retrieve_node import create_retrieve_node
from test_relation_queries import relation_graph, ForbiddenStore

CASE_PATH=Path('datasets/evaluation/relation_expression_v2_cases.json')
CASES=json.loads(CASE_PATH.read_text())['cases']


def test_frozen_expression_manifest():
    design=json.loads(Path('datasets/evaluation/relation_expression_v2_design.json').read_text())
    assert hashlib.sha256(CASE_PATH.read_bytes()).hexdigest()==design['cases_sha256']


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_new_expressions(case,relation_graph):
    rule=parse_relation(case['query'],case['metadata'])
    expected=case['expected']
    if expected['status']=='ordinary':
        assert rule is None
        return
    assert rule is not None
    assert all(rule.get(k)==v for k,v in expected.items())
    result=search_relations(relation_graph.db_path,case['query'],case['metadata'],k=1)
    if expected['status']=='unsupported':
        assert not result.evidence and result.relation['status']=='unsupported'
    else:
        assert result.relation['complete']
        if expected['actor']=='alpha':
            assert result.evidence[0].source_id==f"graph:dev:Mirage:{dict(opening=13,after_plant=9,trade=10)[expected['family']]}"
        else:
            assert result.relation['status']=='not_found'


@pytest.fixture
def aggregate_graph(relation_graph):
    with sqlite3.connect(relation_graph.db_path) as db:
        plant=db.execute("SELECT * FROM nodes WHERE node_type='event' AND match_id='dev' AND json_extract(properties,'$.kind')='plant'").fetchone()
        for n in (10,11):
            row=list(plant);row[0]+=f'-copy-{n}';row[5]=str(n)
            db.execute('INSERT INTO nodes VALUES (?,?,?,?,?,?,?)',row)
        db.execute("UPDATE nodes SET properties=json_set(properties,'$.winner','T') WHERE node_type='round' AND round_number='10'")
        db.execute("UPDATE nodes SET properties=json_remove(properties,'$.winner') WHERE node_type='round' AND round_number='11'")
    return relation_graph


QUERY='Round win rate when Cedar was killed by Alpha after the bomb was planted'
SCOPE={'map':'Mirage','match_id':'dev'}


def test_full_denominator_not_top_k_and_shared_api_hybrid(aggregate_graph,monkeypatch):
    result=search_relations(aggregate_graph.db_path,QUERY,SCOPE,k=1)
    a=result.relation['aggregation']
    assert len(result.evidence)==1 and a['exact_matched_rounds']==3
    assert a['co_present_rounds']==13 and a['match_rate']==3/13
    assert a['known_outcome_rounds']==2 and a['won_rounds']==1
    assert a['observed_win_rate']==.5 and a['unknown_outcome_rounds']==1
    assert result.relation['complete'] and not a['outcome_complete']
    assert a['matched_source_ids']==[f'graph:dev:Mirage:{n}' for n in (9,10,11)]
    assert a['outcome_source_ids']['unknown']==['graph:dev:Mirage:11']
    assert '50.0%' in result.context and '匹配回合数：3' in result.context
    app=FastAPI();app.include_router(graph_router.router)
    monkeypatch.setattr(graph_router,'get_graph_client',lambda:aggregate_graph)
    with TestClient(app) as api:
        payload=api.get('/graph/search',params={'q':QUERY,'map_name':'Mirage','match_id':'dev','limit':1}).json()
    assert payload['relation']==result.relation and '50.0%' in payload['message']
    node=create_retrieve_node(KnowledgeBaseClient(ForbiddenStore(),None),aggregate_graph)
    state=asyncio.run(node({'analysis_plan':[{'id':'stats','query':QUERY}],'retrieval_metadata':SCOPE}))
    assert '50.0%' in state['rag_context'] and '匹配回合数：3' in state['rag_context']
    assert state['retrieval_task_results'][0]['relation']==result.relation


@pytest.mark.parametrize('mutation',['roster','event_tick','outcome','actor_side'])
def test_incomplete_scope_or_outcomes_do_not_become_exact(aggregate_graph,mutation):
    with sqlite3.connect(aggregate_graph.db_path) as db:
        if mutation=='roster':
            db.execute("UPDATE nodes SET properties=json_set(properties,'$.participants_complete',0) WHERE node_type='round' AND round_number='13'")
        elif mutation=='event_tick':
            db.execute("UPDATE nodes SET properties=json_remove(properties,'$.tick') WHERE node_type='event' AND round_number='13'")
        elif mutation=='outcome':
            db.execute("UPDATE nodes SET properties=json_remove(properties,'$.winner') WHERE node_type='round'")
        else:
            db.execute("UPDATE nodes SET properties=json_remove(properties,'$.participants[0].side') WHERE node_type='round'")
    result=search_relations(aggregate_graph.db_path,QUERY,SCOPE,k=1)
    a=result.relation['aggregation']
    if mutation in ('roster','event_tick'):
        assert not result.relation['complete'] and a['exact_matched_rounds'] is None
        assert a['match_rate'] is None and a['observed_matched_rounds']==3
        assert '至少 3' in result.context
    else:
        assert a['exact_matched_rounds']==3 and a['observed_win_rate'] is None
        assert a['known_outcome_rounds']==0 and a['unknown_outcome_rounds']==3


def test_zero_matches_is_zero_count_but_null_win_rate(relation_graph):
    r=search_relations(relation_graph.db_path,'回合胜率：下包后 Cedar 击杀 Alpha',SCOPE)
    assert r.relation['status']=='not_found'
    assert r.relation['aggregation']['exact_matched_rounds']==0
    assert r.relation['aggregation']['observed_win_rate'] is None


def test_multiple_witnesses_do_not_duplicate_rounds(aggregate_graph):
    with sqlite3.connect(aggregate_graph.db_path) as db:
        row=list(db.execute("SELECT * FROM nodes WHERE node_type='event' AND match_id='dev' AND round_number='9' AND json_extract(properties,'$.kind')='kill'").fetchone())
        row[0]+='duplicate-proof';db.execute('INSERT INTO nodes VALUES (?,?,?,?,?,?,?)',row)
    r=search_relations(aggregate_graph.db_path,QUERY,SCOPE,k=1)
    assert r.relation['aggregation']['exact_matched_rounds']==3
    assert len(r.evidence[0].metadata['witnesses'])==2
