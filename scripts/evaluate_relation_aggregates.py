"""Observed relation aggregate audit against frozen qrels and direct roster/outcome SQL."""
import argparse
import json
from pathlib import Path
import sqlite3

from app.services.relation_query_service import search_relations
from scripts.evaluate_fair_retrieval import digest,write_json


def run(protocol_path):
    protocol=json.loads(protocol_path.read_text())
    def verify():
        for item in protocol['inputs'].values():
            if digest(item['path'])!=item['sha256']: raise ValueError('Input changed')
        for path,sha in protocol['implementation_sha256'].items():
            if digest(path)!=sha: raise ValueError('Implementation changed')
    verify()
    paths={k:v['path'] for k,v in protocol['inputs'].items()}
    cases=json.loads(Path(paths['queries']).read_text())['cases']
    labels={j['query_id']:j for j in json.loads(Path(paths['qrels']).read_text())['judgments']}
    rows=[]
    with sqlite3.connect(Path(paths['graph']).resolve().as_uri()+'?mode=ro',uri=True) as db:
        for case in cases:
            qrel=labels[case['id']]
            expected_sources=sorted(r['source_round_id'].replace('round:','graph:',1) for r in qrel['relevance'])
            wins=known=0
            for item in qrel['relevance']:
                # Gold actor ID is used only for the independent expected value, never passed to production.
                pairs=db.execute("""SELECT json_extract(n.properties,'$.winner'),json_extract(p.value,'$.side')
                    FROM nodes n,json_each(n.properties,'$.participants') p
                    WHERE n.node_id=? AND json_extract(p.value,'$.steamid')=?""",
                    (item['source_round_id'],case['relation']['actor'])).fetchall()
                if len(pairs)!=1: raise ValueError('Ambiguous source actor')
                winner,side=pairs[0]
                if winner in ('T','CT') and side in ('T','CT'):
                    known+=1;wins+=int(winner==side)
            for lang,text in case['texts'].items():
                for mode in ('count','win_rate'):
                    prefix={'en':{'count':'Count rounds where','win_rate':'Round win rate when'},
                            'zh':{'count':'统计回合数：','win_rate':'回合胜率：'}}[lang][mode]
                    query=text.replace('Find rounds where',prefix) if lang=='en' else text.replace('查找',prefix)
                    result=search_relations(paths['graph'],query,k=1)
                    a=result.relation.get('aggregation',{}) if result else {}
                    checks={'exact_count':a.get('exact_matched_rounds')==len(expected_sources),
                        'sources':sorted(a.get('matched_source_ids',[]))==expected_sources,
                        'denominator':a.get('co_present_rounds')==len(qrel['eligible_round_ids']),
                        'wins':a.get('won_rounds')==wins,'known_outcomes':a.get('known_outcome_rounds')==known,
                        'win_rate':a.get('observed_win_rate')==(wins/known if known else None),
                        'sample_limit':len(result.evidence)==min(1,len(expected_sources)) if result else False,
                        'mode':a.get('mode')==mode}
                    rows.append({'query_id':case['id'],'language':lang,'query':query,'mode':mode,
                                 'aggregation':a,'checks':checks,'passed':all(checks.values())})
    verify()
    return {'protocol_sha256':digest(protocol_path),'interpretation':'Observed-query aggregate regression, AI source facts; no independent gold or generalization claim.',
            'remote_model_calls':0,'passed':sum(r['passed'] for r in rows),'total':len(rows),'cases':rows}


if __name__=='__main__':
    import socket
    def denied(*args,**kwargs): raise RuntimeError('Offline audit')
    socket.socket.connect=socket.socket.connect_ex=denied
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--protocol',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists(): p.error('Output exists')
    report=run(args.protocol);write_json(args.output,report)
    print(json.dumps({k:report[k] for k in ('passed','total','remote_model_calls')}))
    raise SystemExit(0 if report['passed']==report['total'] else 1)
