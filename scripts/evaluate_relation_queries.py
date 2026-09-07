"""Observed-query regression of the production relation path; no oracle slots supplied."""
import argparse
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import statistics
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routers import graph as graph_router
from app.services.graph_rag_service import GraphRAGClient
from app.services.rag_service import KnowledgeBaseClient
from app.agentic.nodes.retrieve_node import create_retrieve_node
from scripts.evaluate_fair_retrieval import digest,metrics,write_json


class ForbiddenVector:
    def similarity_search_with_score(self,*args,**kwargs):
        raise AssertionError('Relation route must not fall back to vector evidence')


def run(protocol_path):
    protocol=json.loads(protocol_path.read_text())
    def verify():
        for item in protocol['inputs'].values():
            if digest(item['path'])!=item['sha256']: raise ValueError('Frozen regression input changed')
        for path,sha in protocol['implementation_sha256'].items():
            if digest(path)!=sha: raise ValueError('Frozen implementation changed')
    verify(); paths={k:Path(v['path']) for k,v in protocol['inputs'].items()}
    queries=json.loads(paths['queries'].read_text())['cases']
    qrels=json.loads(paths['qrels'].read_text()); judgments={j['query_id']:j for j in qrels['judgments']}
    if qrels['queries_sha256']!=digest(paths['queries']): raise ValueError('Query/qrel mismatch')
    graph=GraphRAGClient(paths['graph']); app=FastAPI(); app.include_router(graph_router.router)
    original=graph_router.get_graph_client; graph_router.get_graph_client=lambda:graph
    hybrid=create_retrieve_node(KnowledgeBaseClient(ForbiddenVector(),None),graph)
    rows=[]
    try:
        with TestClient(app) as api:
            for case in queries:
                for language,query in case['texts'].items():
                    started=time.perf_counter()
                    # Query text alone supplies scope/roles. The expected relation is only read below for checks.
                    result=asyncio.run(graph.retrieve_relations(query,k=protocol['k']))
                    ms=(time.perf_counter()-started)*1000
                    if result is None: raise ValueError('Relation intent was not handled')
                    public=asyncio.run(graph.retrieve(query,k=protocol['k'],global_search=True))
                    response=api.get('/graph/search',params={'q':query,'limit':protocol['k']}); response.raise_for_status()
                    payload=response.json()
                    # Hybrid caller carries the ordinary explicit metadata, never gold relation slots.
                    state=asyncio.run(hybrid({'analysis_plan':[{'id':'relation','query':query}],
                        'retrieval_metadata':case['filters']}))
                    labels={r['source_round_id']:r['grade'] for r in judgments[case['id']]['relevance']}
                    ids=[e.source_id.replace('graph:','round:',1) for e in result.evidence]
                    expected_status='found' if labels else 'not_found'
                    spec=case['relation']; relation=result.relation
                    expected_proofs={r['source_round_id']:{tuple(ids) for ids in r['witness_event_ids']} for r in judgments[case['id']]['relevance']}
                    proof_ok=all({tuple(w['event_id'] for w in proof) for proof in e.metadata['witnesses']}==expected_proofs.get(e.source_id.replace('graph:','round:',1),set()) for e in result.evidence)
                    status=state['retrieval_task_results'][0]['relation']
                    checks={'status':relation['status']==expected_status,'complete':relation['complete'],
                        'scope':result.filters==case['filters'],'scope_count':relation['checked_rounds']==len(judgments[case['id']]['eligible_round_ids']),
                        'roles':relation.get('actor_id')==spec['actor'] and relation.get('target_id')==spec['target'],
                        'family':relation.get('family')==spec['family'],'window':relation.get('window_ticks')==spec.get('window_ticks'),
                        'total_matches':relation['matched_rounds']==len(labels),'proofs':proof_ok,
                        'public_graph_parity':public==result.evidence,
                        'api_parity':payload.get('relation')==relation and payload['results']==[e.as_dict() for e in result.evidence],
                        'hybrid_status':status==relation,
                        'hybrid_evidence':{e['source_id'] for e in state['retrieval_evidence']}=={e.source_id for e in result.evidence}}
                    # All positives here have <= 4 relevant rounds; hybrid's fixed k=4 is sufficient.
                    if len(labels)>4: raise ValueError('Explicit hybrid comparison k contract changed')
                    rows.append({'query_id':case['id'],'language':language,'query':query,'relation':relation,
                        'source_ids':ids,'evidence':[e.as_dict() for e in result.evidence],
                        'metrics':metrics(ids,labels,protocol['k']),'checks':checks,'passed':all(checks.values()),'search_ms':ms})
    finally: graph_router.get_graph_client=original
    verify(); groups={q['id'] for q in queries}; summary={}
    for key in ('ndcg_at_k','recall_at_k','false_retrieval','false_abstention'):
        values=[]
        for group in groups:
            v=[r['metrics'][key] for r in rows if r['query_id']==group and r['metrics'][key] is not None]
            if v: values.append(statistics.mean(v))
        summary[key]={'mean':statistics.mean(values),'semantic_groups':len(values)}
    return {'created_at':datetime.now(timezone.utc).isoformat(),'protocol_sha256':digest(protocol_path),
        'method':'production_bounded_nl_relation_engine','semantic_groups':len(groups),'surface_queries':len(rows),
        'passed':sum(r['passed'] for r in rows),'remote_model_calls':0,'summary':summary,'cases':rows,
        'limitations':protocol['limitations']}


if __name__=='__main__':
    import socket
    def denied(*args,**kwargs): raise RuntimeError('Relation regression is offline')
    socket.socket.connect=socket.socket.connect_ex=denied
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--protocol',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists(): p.error('Output exists')
    report=run(args.protocol);write_json(args.output,report)
    print(json.dumps({k:report[k] for k in ('semantic_groups','surface_queries','passed','summary')},indent=2))
    raise SystemExit(0 if report['passed']==report['surface_queries'] else 1)
