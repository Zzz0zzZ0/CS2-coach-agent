"""Recheck every frozen relation label, near miss, scope and result from raw source events."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
import statistics

from scripts.benchmark_relations import source_index, sql_witnesses, relation_text
from scripts.evaluate_fair_retrieval import digest, metrics, write_json


def audit(protocol_path, report_path=None):
    protocol=json.loads(protocol_path.read_text())
    for item in protocol['inputs'].values():
        if digest(item['path'])!=item['sha256']: raise ValueError('Input changed')
    for path,expected in protocol['implementation_sha256'].items():
        if digest(path)!=expected: raise ValueError('Implementation changed')
    paths={k:Path(v['path']) for k,v in protocol['inputs'].items()}
    docs=[json.loads(s) for s in paths['corpus'].read_text().splitlines()]
    base=[json.loads(s) for s in paths['base_corpus'].read_text().splitlines()]
    assert len(docs)==len(base)==1019
    for doc,old in zip(docs,base):
        assert {k:v for k,v in doc.items() if k!='text'}=={k:v for k,v in old.items() if k!='text'}
        assert doc['text']==relation_text(old)
    with sqlite3.connect(paths['graph'].resolve().as_uri()+'?mode=ro',uri=True) as db:
        raw={r[0]:json.loads(r[1]) for r in db.execute("SELECT node_id,properties FROM nodes WHERE node_type='event'")}
        rosters={r[0]:json.loads(r[1]) for r in db.execute("SELECT node_id,properties FROM nodes WHERE node_type='round'")}
    assert raw=={e['id']:e['properties'] for d in docs for e in d['events']}
    queries=json.loads(paths['queries'].read_text())['cases']
    packet=json.loads(paths['qrels'].read_text()); judgments={j['query_id']:j for j in packet['judgments']}
    assert len(queries)==len(judgments)==24
    assert packet['corpus_sha256']==digest(paths['corpus']) and packet['queries_sha256']==digest(paths['queries'])
    db=source_index(docs); checked=[]; all_labels={}; all_scopes={}
    for q in queries:
        # Reconstruct scope from raw round rosters, not exported entity metadata.
        scope=[]
        for d in docs:
            if d['map']!=q['filters']['map'] or d['match_id']!=q['filters']['match_id']: continue
            roster=rosters[d['id']]; assert roster['participants_complete']
            names={p['name']:p['steamid'] for p in roster['participants']}
            if all(name in names for name in q['entities']):
                assert names[q['entities'][0]]==q['relation']['actor']
                assert names[q['entities'][1]]==q['relation']['target']
                scope.append(d['id'])
        j=judgments[q['id']]; assert j['exhaustive'] and scope==j['eligible_round_ids']
        exact={rid:sql_witnesses(db,rid,q) for rid in scope}
        exact={rid:v for rid,v in exact.items() if v}
        near={rid:sql_witnesses(db,rid,q,True) for rid in scope if rid not in exact}
        near={rid:v for rid,v in near.items() if v}
        assert exact=={r['source_round_id']:r['witness_event_ids'] for r in j['relevance']}
        assert near=={r['source_round_id']:r['witness_event_ids'] for r in j['near_misses']}
        assert len(scope)>=12 and near and len(exact)<len(scope)/2
        assert bool(exact)==(q['construction_polarity']=='positive')
        examples={}
        for name,items in [('positive',exact),('near_miss',near)]:
            if items:
                rid=next(iter(items)); ids=items[rid][0]
                examples[name]={'round_id':rid,'events':[{'id':eid,**{key:raw[eid][key] for key in
                    ('tick','killer','victim','killer_team','victim_team','is_first_kill','planter') if key in raw[eid]}} for eid in ids]}
        checked.append({'query_id':q['id'],'eligible':len(scope),'relevant':len(exact),'near_miss_rounds':len(near),
                        'relevant_fraction':len(exact)/len(scope),'source_examples':examples})
        all_labels[q['id']]={rid:1 for rid in exact}; all_scopes[q['id']]=set(scope)
    db.close()
    result={'protocol_sha256':digest(protocol_path),'raw_event_parity':len(raw),'source_queries_checked':len(checked),
        'scope_round_evaluations':sum(r['eligible'] for r in checked),'distinct_scoped_rounds':len(set.union(*all_scopes.values())),
        'families':dict(Counter(q['relation']['family'] for q in queries)),
        'positive_groups':sum(bool(r['relevant']) for r in checked),'negative_groups':sum(not r['relevant'] for r in checked),
        'all_negative_scopes_nonempty':True,'all_queries_have_near_misses':True,'cases':checked}
    if report_path:
        report=json.loads(report_path.read_text()); assert report['protocol_sha256']==digest(protocol_path)
        rows=report['cases']; combinations=set()
        expected={(q['id'],lang,method) for q in queries for lang in ('en','zh') for method in
                  ('bm25','dense','dense_bm25_rrf','relation_sql_oracle')}
        grouped=defaultdict(list); failures=[]
        for r in rows:
            key=(r['query_id'],r['language'],r['method']); assert key not in combinations; combinations.add(key)
            q=next(q for q in queries if q['id']==r['query_id']); labels=all_labels[q['id']]
            assert r['input_query']==q['texts'][r['language']]
            assert len(r['source_ids'])<=protocol['k'] and set(r['source_ids'])<=all_scopes[q['id']]
            assert r['eligible_rounds']==len(all_scopes[q['id']]) and r['relevant_rounds']==len(labels)
            assert r['metrics']==metrics(r['source_ids'],labels,protocol['k'])
            grouped[(r['method'],r['family'],bool(labels))].append(r)
            if r['metrics']['false_retrieval'] or (labels and r['metrics']['ndcg_at_k']<1):
                failures.append({'query_id':q['id'],'language':r['language'],'method':r['method'],'source_ids':r['source_ids'],'metrics':r['metrics']})
        assert combinations==expected and len(rows)==192
        for summary in report['summary']:
            subset=[r for r in rows if r['method']==summary['method'] and (summary['language']=='paired_macro' or r['language']==summary['language'])]
            for metric,summary_value in summary['metrics'].items():
                values=defaultdict(list)
                for r in subset:
                    if r['metrics'][metric] is not None: values[r['query_id']].append(r['metrics'][metric])
                assert summary_value['semantic_groups']==len(values)
                assert summary_value['mean']==statistics.mean(statistics.mean(v) for v in values.values())
        result['retrieval']={'rows_checked':len(rows),'report_sha256':digest(report_path),'failures':failures,
            'family_summary':[{'method':m,'family':f,'answerable':positive,'semantic_groups':len({r['query_id'] for r in rs}),
                'mean_ndcg_at_5':statistics.mean(r['metrics']['ndcg_at_k'] for r in rs) if positive else None,
                'false_retrieval_rate':None if positive else statistics.mean(r['metrics']['false_retrieval'] for r in rs)}
                for (m,f,positive),rs in grouped.items()]}
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path); p.add_argument('--output',type=Path,required=True); args=p.parse_args()
    write_json(args.output,audit(Path('datasets/evaluation/relation_v1_protocol.json'),args.report))
