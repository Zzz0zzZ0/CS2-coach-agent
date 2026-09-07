"""Interleaved player-context performance and exact-output parity; no production writes."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time
from scripts.evaluate_fair_retrieval import digest,write_json


def run(protocol_path):
    from app.services.graph_rag_service import GraphRAGClient
    p=json.loads(protocol_path.read_text())
    def verify():
        for path,sha in p['input_sha256'].items():
            if digest(path)!=sha:raise ValueError('Frozen input changed')
    verify()
    spec=importlib.util.spec_from_file_location('player_context_baseline',p['baseline_source'])
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    before=module.GraphRAGClient(p['graph']);after=GraphRAGClient(p['graph'])
    players=before.players();after.players()
    if len(players)!=p['expected_players']:raise ValueError('Player inventory changed')
    rows=[]
    for player in players:
        for scope in p['scopes']:
            outputs={};timings={}
            for name,client in ([('before',before),('after',after)] if len(rows)%2==0 else [('after',after),('before',before)]):
                start=time.perf_counter();value=client.player_context(player['player_id'],**scope)
                timings[name]=(time.perf_counter()-start)*1000
                outputs[name]=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            rows.append({'player_id':player['player_id'],'scope':scope,'ms':timings,'sha256':outputs,'equal':outputs['before']==outputs['after']})
    verify()
    return {'protocol_sha256':digest(protocol_path),'passed':sum(r['equal'] for r in rows),'total':len(rows),
            'median_ms':{k:statistics.median(r['ms'][k] for r in rows) for k in ('before','after')},
            'median_paired_speedup':statistics.median(r['ms']['before']/r['ms']['after'] for r in rows),
            'interpretation':'One interleaved read-only run, both analytics caches warm; exact full JSON parity. Hardware/load dependent; not an API concurrency or cold-start claim.',
            'cases':rows}


if __name__=='__main__':
    import socket
    def denied(*args,**kwargs):raise RuntimeError('Offline performance check')
    socket.socket.connect=socket.socket.connect_ex=denied
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--protocol',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():p.error('Output exists')
    r=run(a.protocol);write_json(a.output,r)
    print(json.dumps({k:v for k,v in r.items() if k!='cases'},indent=2))
    raise SystemExit(0 if r['passed']==r['total'] else 1)
