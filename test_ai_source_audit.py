import json
import sqlite3
from types import SimpleNamespace

import pytest

from scripts.audit_fair_labels import audit, score_cached
from scripts.evaluate_fair_retrieval import digest, export_corpus, run


def setup_sources(tmp_path):
    graph=tmp_path/'graph.sqlite'
    with sqlite3.connect(graph) as db:
        db.executescript('CREATE TABLE nodes(node_id,node_type,map_name,match_id,round_number,properties); CREATE TABLE edges(source_id,relation,target_id);')
        for i,team in enumerate(('Spirit','Team Spirit','Other')):
            props={'participants_complete':True,'participants':[{'name':'player','steamid':str(i),'team':team,'side':'T'}]}
            db.execute('INSERT INTO nodes VALUES (?,?,?,?,?,?)',(f'r{i}','round','Nuke','m1',i+1,json.dumps(props)))
            props={'kind':'kill','is_first_kill':i != 2}
            db.execute('INSERT INTO nodes VALUES (?,?,?,?,?,?)',(f'e{i}','event','Nuke','m1',i+1,json.dumps(props)))
            db.execute('INSERT INTO edges VALUES (?,?,?)',(f'r{i}','KILL',f'e{i}'))
    corpus,queries,manifest,criteria=[tmp_path/name for name in ('corpus.jsonl','queries.json','manifest.json','criteria.json')]
    export_corpus(graph,corpus)
    rule={'query_id':'q','filters':{'map':'Nuke'},'entities':['Spirit'],'event_kind':'kill','event_properties':{'is_first_kill':True}}
    queries.write_text(json.dumps({'cases':[{'id':'q','query':'Spirit participating with opening kills','language':'en',**{k:rule[k] for k in ('filters','entities','event_kind')}}]}))
    manifest.write_text(json.dumps({'corpus_sha256':digest(corpus),'queries_sha256':digest(queries),'source_graph_sha256':digest(graph)}))
    criteria.write_text(json.dumps({'queries_sha256':digest(queries),'reviewer_kind':'ai_assisted','independent_human_review':False,
                                   'team_aliases':{'spirit':['spirit','team spirit']},'cases':[rule]}))
    return corpus,queries,graph,manifest,criteria


def test_source_audit_checks_aliases_and_preserves_evidence(tmp_path):
    inputs=setup_sources(tmp_path)
    before=digest(inputs[2])
    packet=audit(*inputs)
    assert packet['independent_human_review'] is False
    assert packet['counts'][0]['relevant_rounds']==2
    assert packet['counts'][0]['alias_only_rounds']==1
    assert [r['source_event_ids'] for r in packet['judgments'][0]['relevance']]==[['e0'],['e1']]
    assert digest(inputs[2])==before
    inputs[1].write_text('{}')
    with pytest.raises(ValueError,match='hash'):
        audit(*inputs)


def test_ai_packet_cannot_claim_human_review(tmp_path):
    inputs=setup_sources(tmp_path)
    spec=json.loads(inputs[4].read_text())
    spec['independent_human_review']=True
    inputs[4].write_text(json.dumps(spec))
    with pytest.raises(ValueError,match='human'):
        audit(*inputs)


def test_cached_scores_do_not_retrieve_and_reject_duplicate_rows(tmp_path):
    inputs=setup_sources(tmp_path)
    packet=audit(*inputs)
    qrels=tmp_path/'qrels.json'
    qrels.write_text(json.dumps(packet))
    ranking=tmp_path/'ranking.json'
    frozen={'corpus_sha256':digest(inputs[0]),'queries_sha256':digest(inputs[1]),
            'contract':{'k':1,'text_methods':['bm25'],'structured_references':[]},
            'cases':[{'query_id':'q','method':'bm25','entity_constraint':flag,'source_ids':['r1']} for flag in (False,True)]}
    ranking.write_text(json.dumps(frozen))
    report=score_cached(inputs[0],inputs[1],qrels,ranking)
    assert report['remote_model_calls']==0 and not report['fresh_retrieval_run']
    assert report['status']=='ai_assisted_posthoc_evaluation'
    assert report['cases'][0]['metrics']['recall_at_k']==0.5
    assert report['cases'][0]['metrics']['ndcg_at_k']==1
    frozen['cases'][1]=frozen['cases'][0]
    ranking.write_text(json.dumps(frozen))
    with pytest.raises(ValueError,match='duplicate'):
        score_cached(inputs[0],inputs[1],qrels,ranking)


def test_normal_evaluator_requires_explicit_ai_mode_before_model_load(tmp_path,monkeypatch):
    import fastembed
    inputs=setup_sources(tmp_path)
    qrels=tmp_path/'qrels.json'
    qrels.write_text(json.dumps(audit(*inputs)))
    monkeypatch.setattr(fastembed,'TextEmbedding',lambda *a,**k:pytest.fail('No model load before reviewer provenance gate'))
    with pytest.raises(ValueError,match='allow-ai-reviewed'):
        run(SimpleNamespace(corpus=inputs[0],queries=inputs[1],qrels=qrels,allow_unreviewed=False))
