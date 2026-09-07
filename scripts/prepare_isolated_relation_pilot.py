"""Source-selected AI development pilot on previously observed, isolated complete series."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3

from scripts.evaluate_fair_retrieval import digest,export_corpus,write_json
from scripts.benchmark_relations import relation_text,witnesses,source_index,sql_witnesses


def choose(scoped,identities,match,map_name):
    cases=[];missing=[]
    for family in ('opening','after_plant','trade'):
        pools={'positive':[],'negative':[]}
        for actor,actor_id in sorted(identities.items()):
            for target,target_id in sorted(identities.items()):
                if actor_id==target_id:continue
                rule={'family':family,'actor':actor_id,'target':target_id}
                if family=='trade':rule['window_ticks']=320
                q={'relation':rule}
                exact={d['id']:witnesses(d,q) for d in scoped};relaxed={d['id']:witnesses(d,q,True) for d in scoped}
                near=[d for d in scoped if relaxed[d['id']] and not exact[d['id']]]
                if not near:continue
                polarity='positive' if any(exact.values()) else 'negative'
                key=hashlib.sha256(f'isolated-v1|{match}|{map_name}|{family}|{actor_id}|{target_id}'.encode()).hexdigest()
                pools[polarity].append((key,actor,target,rule))
        for polarity,candidates in pools.items():
            if not candidates:
                missing.append({'match_id':match,'map':map_name,'family':family,'polarity':polarity});continue
            _,actor,target,rule=min(candidates)
            en={'opening':f'{actor} gets the opening kill against {target}',
                'after_plant':f'{actor} kills {target} after the bomb was planted',
                'trade':f'{actor} trades teammate {target} within 320 ticks'}[family]
            zh={'opening':f'{actor} 首杀 {target}',
                'after_plant':f'下包后 {actor} 击杀 {target}',
                'trade':f'{actor} 为队友 {target} 补枪，在 320 tick 内'}[family]
            cases.append({'id':f'{match}_{map_name}_{family}_{polarity}','filters':{'match_id':match,'map':map_name},
                          'entities':[actor,target],'relation':rule,'construction_polarity':polarity,
                          'texts':{'en':f'Match {match}, map {map_name}. '+en,'zh':f'比赛 {match}，地图 {map_name}。'+zh}})
    return cases,missing


def prepare(protocol_path):
    from app.services.graph_rag_service import GraphRAGClient
    protocol=json.loads(protocol_path.read_text())
    def verify():
        for path,sha in {**protocol['inputs_sha256'],**protocol['implementation_sha256']}.items():
            if digest(path)!=sha:raise ValueError('Frozen source changed: '+path)
    verify()
    root=Path(protocol['output_directory'])
    if root.exists():raise ValueError('Refuse overwriting pilot directory')
    root.mkdir(parents=True)
    graph=root/'graph.sqlite'
    stats=GraphRAGClient(graph).build_from_demo_dir(protocol['demo_directory'])
    export_corpus(graph,root/'raw_corpus.jsonl')
    docs=[json.loads(line) for line in (root/'raw_corpus.jsonl').read_text().splitlines()]
    selected={(m['match_id'],map_name):sum(scores.values()) for m in protocol['matches'] for map_name,scores in m['public_map_scores'].items()}
    observed=defaultdict(int)
    for d in docs:observed[d['match_id'],d['map']]+=1
    if dict(observed)!=selected:raise ValueError('Complete-series round inventory differs')
    with sqlite3.connect(Path(protocol['historical_graph']).resolve().as_uri()+'?mode=ro',uri=True) as db:
        historical={r[0] for r in db.execute("SELECT DISTINCT match_id FROM nodes WHERE node_type='match'")}
    if {d['match_id'] for d in docs}&historical:raise ValueError('Historical overlap')
    docs=[{**d,'text':relation_text(d)} for d in docs]
    with (root/'corpus.jsonl').open('x') as out:
        for d in docs:out.write(json.dumps(d,ensure_ascii=False,sort_keys=True)+'\n')
    cases=[];missing=[]
    with sqlite3.connect(graph.resolve().as_uri()+'?mode=ro',uri=True) as db:
        for match,map_name in sorted(selected):
            scoped=[d for d in docs if d['match_id']==match and d['map']==map_name]
            pairs=db.execute("""SELECT DISTINCT json_extract(p.value,'$.name'),json_extract(p.value,'$.steamid')
                FROM nodes n,json_each(n.properties,'$.participants') p
                WHERE n.node_type='round' AND n.match_id=? AND n.map_name=?""",(match,map_name)).fetchall()
            identities=dict(pairs)
            if len(identities)!=len(pairs) or len(set(identities.values()))!=len(pairs):raise ValueError('Ambiguous roster identities')
            chosen,absent=choose(scoped,identities,match,map_name);cases+=chosen;missing+=absent
    prefix=Path('datasets/evaluation/isolated_relation_v1')
    query_path=Path(str(prefix)+'_queries.json');qrel_path=Path(str(prefix)+'_qrels.json')
    write_json(query_path,{'reviewer_kind':'ai_assisted','independent_human_review':False,'cases':cases})
    oracle=source_index(docs);judgments=[]
    for q in cases:
        scope=[d for d in docs if all(d[k]==v for k,v in q['filters'].items())];relevant=[];near=[]
        for d in scope:
            exact=witnesses(d,q);relaxed=witnesses(d,q,True)
            if exact!=sql_witnesses(oracle,d['id'],q) or relaxed!=sql_witnesses(oracle,d['id'],q,True):raise ValueError('Python and SQL disagree')
            if exact:relevant.append({'source_round_id':d['id'],'grade':1,'witness_event_ids':exact})
            elif relaxed:near.append({'source_round_id':d['id'],'witness_event_ids':relaxed})
        judgments.append({'query_id':q['id'],'eligible_round_ids':[d['id'] for d in scope],'relevance':relevant,'near_misses':near,'exhaustive':True})
    oracle.close()
    write_json(qrel_path,{'reviewer_kind':'ai_assisted','independent_human_review':False,'corpus_sha256':digest(root/'corpus.jsonl'),'queries_sha256':digest(query_path),'judgments':judgments})
    verify()
    report={'preparation_protocol_sha256':digest(protocol_path),'graph_sha256':digest(graph),'rounds':len(docs),'matches':sorted({d['match_id'] for d in docs}),
            'maps':len(selected),'semantic_queries':len(cases),'missing_quotas':missing,'graph_build':stats,'historical_unchanged':True,
            'identity':'Previously observed pipeline-validation matches, AI source-selected development pilot; not unseen or independent human gold.',
            'labels':'Full-scope Python and separate SQL joins agree for positives and near misses; shared parser source.'}
    write_json(Path(str(prefix)+'_preparation_report.json'),report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    import socket
    def denied(*args,**kwargs):raise RuntimeError('Offline preparation')
    socket.socket.connect=socket.socket.connect_ex=denied
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--protocol',type=Path,required=True)
    prepare(p.parse_args().protocol)
