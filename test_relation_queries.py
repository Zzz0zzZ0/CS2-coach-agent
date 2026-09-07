"""Independent synthetic development cases; no frozen benchmark inputs."""
import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.graph_rag_service import GraphRAGClient
from app.services.rag_service import Evidence,KnowledgeBaseClient
from app.services.relation_query_service import parse_relation,event_witnesses,search_relations
from app.agentic.nodes.retrieve_node import create_retrieve_node
from app.api.routers import graph as graph_router


NAMES={'Alpha':'a','Bravo':'b','Cedar':'c','Delta':'d'}

def kill(actor,target,tick,first=False):
    team=lambda name:'Red' if name in ('Alpha','Bravo','Delta') else 'Blue'
    return {'kind':'kill','killer':actor,'killer_steamid':NAMES[actor], 'victim':target,
            'victim_steamid':NAMES[target],'killer_team':team(actor),'victim_team':team(target),
            'tick':tick,'is_first_kill':first,'weapon':'ak47'}


@pytest.fixture
def relation_graph(tmp_path):
    client=GraphRAGClient(tmp_path/'relations.sqlite')
    roster=[{'name':name,'steamid':sid,'team':'Blue' if name=='Cedar' else 'Red','side':'T' if name=='Cedar' else 'CT'} for name,sid in NAMES.items()]
    rounds=[{'round_number':n,'participants':roster,'participants_complete':True,'winner':'CT',
             'kills':[kill('Cedar','Bravo',100,True),kill('Delta','Cedar',500)]} for n in range(1,9)]
    for number,kills,plants in [
        (9,[kill('Alpha','Cedar',120)],[{'tick':100,'planter':'Bravo','planter_steamid':'b','site':'A'}]),
        (10,[kill('Cedar','Bravo',100,True),kill('Alpha','Cedar',420)],[]),
        (11,[kill('Cedar','Bravo',100,True),kill('Alpha','Cedar',421)],[]),
        (12,[kill('Cedar','Bravo',100,True),kill('Alpha','Cedar',100)],[]),
        (13,[kill('Alpha','Cedar',100,True)],[])]:
        rounds.append({'round_number':number,'participants':roster,'participants_complete':True,
                       'winner':'CT','kills':kills,'plants':plants})
    with sqlite3.connect(client.db_path) as db:
        client._create_schema(db)
        for match,map_name in [('dev','Mirage'),('other','Ancient')]:
            nodes,edges=client._graph_rows(tmp_path/(match+'.dem'),{'match_id':match,'map_name':map_name,'rounds':rounds})
            db.executemany('INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?,?,?)',nodes)
            db.executemany('INSERT OR IGNORE INTO edges VALUES (?,?,?,?)',edges)
    return client


@pytest.mark.parametrize('query,family',[
    ('Find rounds where Alpha gets the first kill by killing Cedar.','opening'),
    ('Alpha wins the opening kill against Cedar','opening'),
    ('查找 Alpha 击杀 Cedar 并取得本回合首杀的回合。','opening'),
    ('Show rounds where Alpha kills Cedar after a bomb plant in the same round.','after_plant'),
    ('查找 Alpha 击杀 Cedar，且这次击杀严格发生在该回合炸弹安放之后的回合。','after_plant'),
    ('Alpha trades teammate Bravo within 320 ticks','trade'),
    ('Alpha 为队友 Bravo 补枪，在 320 tick 内','trade'),
    ('Alpha trades teammate Bravo: kills the enemy who killed Bravo, more than 0 and at most 320 ticks later in the same round','trade'),
    ('查找 Alpha 为队友 Bravo 补枪的回合：在同一回合中，Bravo 被敌人击杀后，Alpha 在大于 0 且不超过 320 tick 内击杀该敌人。','trade'),
])
def test_bilingual_roles_parse_and_search_before_top_k(relation_graph,query,family):
    rule=parse_relation(query,{'map':'de_mirage','match_id':'dev'})
    assert rule['status']=='parsed' and rule['family']==family
    result=asyncio.run(relation_graph.retrieve_relations(query,{'map':'Mirage','match_id':'dev'},k=1))
    assert result.relation['status']=='found' and result.relation['complete']
    assert result.relation['checked_rounds']==13
    assert result.evidence[0].source_id==f"graph:dev:Mirage:{dict(opening=13,after_plant=9,trade=10)[family]}"
    assert result.evidence[0].metadata['witness_event_ids']
    for global_search in (True,False):
        assert asyncio.run(relation_graph.retrieve(query,{'map':'Mirage','match_id':'dev'},k=1,global_search=global_search))==result.evidence


@pytest.mark.parametrize('query',[
    'Alpha kills Cedar after a bomb plant and before a flash',
    'Alpha kills Cedar after a bomb plant with an awp',
    'Alpha kills Cedar before a bomb plant',
    'Alpha did not kill Cedar after a bomb plant',
    'Alpha 未击杀 Cedar，发生在下包之后',
    'Alpha trades teammate Bravo within 5 seconds',
    'Alpha trades teammate Bravo within 0 ticks',
    'Alpha trades teammate Bravo within 6401 ticks',
    'Alpha trades teammate Bravo within 320 ticks or Delta trades teammate Bravo within 320 ticks',
    'Alpha trades teammate Bravo: kills the enemy who killed Delta, more than 0 and at most 320 ticks later in the same round',
])
def test_unsupported_conditions_do_not_broaden_into_generic_evidence(relation_graph,query):
    result=asyncio.run(relation_graph.retrieve_relations(query,{'map':'Mirage'}))
    assert result is not None and not result.evidence and result.relation['status']=='unsupported'
    assert not asyncio.run(relation_graph.retrieve(query,{'map':'Mirage'},global_search=True))


@pytest.mark.parametrize('query,metadata,status,reason',[
    ('Alpha gets the first kill by killing Cedar',{},'unsupported','explicit_scope_required'),
    ('Map Mirage. Alpha gets the first kill by killing Cedar',{'map':'Ancient'},'unsupported','conflicting_scope'),
    ('Match dev, map Mirage. Alpha gets the first kill by killing Cedar',{'match_id':'other'},'unsupported','conflicting_scope'),
    ('Alpha gets the first kill by killing Cedar',{'map':'Mirage','side':'T'},'unsupported','unsupported_scope_filter'),
    ('Alpha gets the first kill by killing Ghost',{'map':'Mirage'},'unknown','unknown_or_ambiguous_player'),
    ('Alpha gets the first kill by killing Cedar',{'map':'Nuke'},'unknown','empty_scope'),
    ('Alpha gets the first kill by killing Cedar',{'map':'Mirage','round':0},'unsupported','invalid_round'),
])
def test_scope_and_identity_uncertainty_is_not_absence(relation_graph,query,metadata,status,reason):
    result=asyncio.run(relation_graph.retrieve_relations(query,metadata))
    assert not result.evidence and result.relation['status']==status and result.relation['reason']==reason


def test_absence_exhaustive_scope_and_case_insensitive_identity(relation_graph):
    query='Match dev, map de_mirage. Alpha gets the first kill by killing Bravo.'
    result=asyncio.run(relation_graph.retrieve_relations(query))
    assert result.relation['status']=='not_found' and result.relation['checked_rounds']==13
    assert result.relation['complete'] and not result.evidence and '已核查' in result.context
    query='比赛 dev，地图 Mirage。查找 aLpHa 击杀 cEdAr 并拿到本回合首杀的回合。'
    assert asyncio.run(relation_graph.retrieve_relations(query)).evidence[0].source_id=='graph:dev:Mirage:13'


@pytest.mark.parametrize('mutation',["missing_roster","missing_tick","missing_team","missing_flag"])
def test_missing_source_facts_cannot_prove_no_answer(relation_graph,mutation):
    with sqlite3.connect(relation_graph.db_path) as db:
        if mutation=='missing_roster':
            db.execute("UPDATE nodes SET properties=json_set(properties,'$.participants_complete',0) WHERE node_type='round'")
        else:
            key={'missing_tick':'tick','missing_team':'victim_team','missing_flag':'is_first_kill'}[mutation]
            db.execute("UPDATE nodes SET properties=json_remove(properties,?) WHERE node_type='event'",('$.'+key,))
    query='Alpha gets the first kill by killing Bravo' if mutation=='missing_flag' else 'Cedar trades teammate Alpha within 320 ticks'
    result=asyncio.run(relation_graph.retrieve_relations(query,{'map':'Mirage'}))
    assert not result.evidence and result.relation['status']=='unknown' and not result.relation['complete']


@pytest.mark.parametrize('delay,valid',[(-1,False),(0,False),(1,True),(320,True),(321,False)])
def test_trade_time_boundaries(delay,valid):
    events=[kill('Cedar','Bravo',1000),kill('Alpha','Cedar',1000+delay)]
    rule={'family':'trade','actor_id':'a','target_id':'b','window_ticks':320}
    assert bool(event_witnesses(events,rule)[0])==valid
    events[1]['killer_team']='Blue'
    assert not event_witnesses(events,rule)[0]


def test_no_cross_round_trade(relation_graph):
    with sqlite3.connect(relation_graph.db_path) as db:
        db.execute("DELETE FROM nodes WHERE node_type='event' AND round_number != '10'")
        db.execute("UPDATE nodes SET round_number='11' WHERE node_type='event' AND json_extract(properties,'$.killer')='Alpha'")
    result=asyncio.run(relation_graph.retrieve_relations('Alpha trades teammate Bravo within 320 ticks',{'map':'Mirage'}))
    assert result.relation['status']=='not_found' and not result.evidence


class ForbiddenStore:
    def similarity_search_with_score(self,*args,**kwargs): raise AssertionError('No unverified vector fallback')


def test_vector_alone_cannot_call_a_relation_absent_or_rewrite_it():
    result=asyncio.run(KnowledgeBaseClient(ForbiddenStore(),object()).retrieve('Alpha kills Cedar after a bomb plant',{'map':'Mirage'}))
    assert not result.evidence and result.relation['status']=='unknown'
    assert result.strategy=='relation_requires_source'


def test_hybrid_uses_proofs_and_removes_stale_evidence_on_retry(relation_graph):
    node=create_retrieve_node(KnowledgeBaseClient(ForbiddenStore(),object()),relation_graph)
    state={'retrieval_metadata':{'map':'Mirage'},'analysis_plan':[{'id':'relation','query':'Alpha gets the first kill by killing Bravo'}],
           'retrieval_evidence':[Evidence('old unrelated',{},1,'old').as_dict()],
           'critique_feedback':'use other rounds','retrieval_retry_tasks':['relation']}
    result=asyncio.run(node(state))
    assert not result['retrieval_evidence'] and result['retrieval_task_results'][0]['relation']['status']=='not_found'
    assert '已核查限定范围' in result['rag_context']
    assert result['retrieval_task_results'][0]['covered']
    state['analysis_plan'][0]['query']='Alpha trades teammate Bravo within 320 ticks'
    result=asyncio.run(node(state))
    assert len(result['retrieval_evidence'])==1
    summary=result['retrieval_task_results'][0]
    assert summary['milvus_count']==0 and summary['graph_count']==1


def test_api_distinguishes_found_absent_unsupported_and_unavailable(relation_graph,monkeypatch,tmp_path):
    app=FastAPI();app.include_router(graph_router.router)
    monkeypatch.setattr(graph_router,'get_graph_client',lambda:relation_graph)
    with TestClient(app) as client:
        for query,status in [('Alpha trades teammate Bravo within 320 ticks','found'),
                             ('Alpha gets the first kill by killing Bravo','not_found'),
                             ('Alpha kills Cedar after a bomb plant with an awp','unsupported')]:
            response=client.get('/graph/search',params={'q':query,'map_name':'Mirage','match_id':'dev'})
            assert response.status_code==200
            assert response.json()['relation']['status']==status and response.json()['message']
        monkeypatch.setattr(graph_router,'get_graph_client',lambda:GraphRAGClient(tmp_path/'missing.sqlite'))
        response=client.get('/graph/search',params={'q':'Alpha trades teammate Bravo within 320 ticks','map_name':'Mirage'})
        assert response.json()['relation']['status']=='unknown' and not response.json()['available']


def test_partial_proof_is_found_but_cannot_claim_exhaustive_count(relation_graph):
    with sqlite3.connect(relation_graph.db_path) as db:
        db.execute("UPDATE nodes SET properties=json_set(properties,'$.participants_complete',0) WHERE node_type='round' AND round_number='1'")
    result=asyncio.run(relation_graph.retrieve_relations('Alpha gets the first kill by killing Cedar',{'map':'Mirage'}))
    assert result.evidence and result.relation['status']=='found'
    assert not result.relation['complete'] and result.relation['unknown_rounds']==1
    assert '无法确认' in result.warnings[0]


@pytest.mark.parametrize('k',[0,-1,101])
def test_invalid_limit_cannot_turn_positive_into_absence(relation_graph,k):
    with pytest.raises(ValueError):
        asyncio.run(relation_graph.retrieve_relations('Alpha gets the first kill by killing Cedar',{'map':'Mirage'},k))


def test_missing_graph_never_falls_back_to_unverified_vectors():
    node=create_retrieve_node(KnowledgeBaseClient(ForbiddenStore(),object()),None)
    result=asyncio.run(node({'retrieval_query':'Alpha trades teammate Bravo within 320 ticks',
                            'retrieval_metadata':{'map':'Mirage'},'retrieval_evidence':[Evidence('old',{},1,'old').as_dict()]}))
    assert not result['retrieval_evidence']
    assert result['retrieval_task_results'][0]['relation']['status']=='unknown'
