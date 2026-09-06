"""AI-reviewed semantics, exhaustive source predicates, and post-hoc scoring of frozen rankings."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import statistics

from scripts.evaluate_fair_retrieval import digest, metrics, reviewed_qrels, write_json


def audit(corpus, queries, graph_db, manifest, criteria):
    frozen = json.loads(manifest.read_text())
    spec = json.loads(criteria.read_text())
    for path, expected in ((corpus, frozen['corpus_sha256']), (queries, frozen['queries_sha256']),
                           (graph_db, frozen['source_graph_sha256']), (queries, spec['queries_sha256'])):
        if digest(path) != expected:
            raise ValueError('Audit input hash mismatch')
    dataset = json.loads(queries.read_text())
    cases = {c['id']:c for c in dataset['cases']}
    if len(spec['cases']) != len(cases) or {c['query_id'] for c in spec['cases']} != set(cases):
        raise ValueError('Criteria must cover every query once')
    if spec['reviewer_kind'] != 'ai_assisted' or spec['independent_human_review'] is not False:
        raise ValueError('This audit cannot claim human review')
    docs = [json.loads(line) for line in corpus.read_text().splitlines()]
    aliases = spec['team_aliases']
    with sqlite3.connect(graph_db.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.execute('BEGIN')
        raw_rounds = {row[0]:json.loads(row[1]) for row in db.execute("SELECT node_id,properties FROM nodes WHERE node_type='round'")}
        raw_events = {row[0]:json.loads(row[1]) for row in db.execute("SELECT node_id,properties FROM nodes WHERE node_type='event'")}
        if set(raw_rounds) != {d['id'] for d in docs}:
            raise ValueError('Source round coverage differs')
        for doc in docs:
            for event in doc['events']:
                if event['properties'] != raw_events[event['id']]:
                    raise ValueError('Exported event differs from source')
        judgments, counts = [], []
        for rule in spec['cases']:
            q = cases[rule['query_id']]
            if any(rule[key] != q[key] for key in ('filters','entities','event_kind')):
                raise ValueError('Review criteria disagree with frozen query slots')
            scoped = [d for d in docs if all(d[key] == value for key,value in rule['filters'].items())]
            supports, literal_supports = {}, set()
            for doc in scoped:
                roster = raw_rounds[doc['id']]['participants']
                names = {str(p[key]).casefold() for p in roster for key in ('name','team','steamid')}
                if not all(names.intersection(aliases.get(e.casefold(),[e.casefold()])) for e in rule['entities']):
                    continue
                events = [e['id'] for e in doc['events'] if e['kind'] == rule['event_kind']
                          and all(e['properties'].get(k) == v for k,v in rule['event_properties'].items())]
                if events:
                    supports[doc['id']] = sorted(events)
                    if all(e.casefold() in names for e in rule['entities']):
                        literal_supports.add(doc['id'])
            # Second implementation reads raw nodes with JSON SQL, never retrieval rankings.
            where = ["r.node_type='round'", "e.node_type='event'", "json_extract(e.properties,'$.kind')=?"]
            params = [rule['event_kind']]
            columns = {'map':'map_name','match_id':'match_id','round':'round_number'}
            for key,value in rule['filters'].items():
                where.append(f'r.{columns[key]}=?'); params.append(value)
            for entity in rule['entities']:
                names = aliases.get(entity.casefold(),[entity.casefold()])
                slots = ','.join('?' for _ in names)
                terms = [f"lower(CAST(json_extract(p.value,'$.{key}') AS TEXT)) IN ({slots})" for key in ('name','team','steamid')]
                where.append("EXISTS (SELECT 1 FROM json_each(r.properties,'$.participants') p WHERE "+' OR '.join(terms)+')')
                params.extend(names*3)
            for key,value in rule['event_properties'].items():
                where.append('json_extract(e.properties,?)=?'); params.extend(['$.'+key,value])
            reference = defaultdict(list)
            sql = '''SELECT r.node_id,e.node_id FROM nodes r JOIN nodes e
                     ON r.match_id=e.match_id AND r.map_name=e.map_name AND r.round_number=e.round_number WHERE '''+' AND '.join(where)
            for round_id,event_id in db.execute(sql,params):
                reference[round_id].append(event_id)
            if supports != {key:sorted(value) for key,value in reference.items()}:
                raise ValueError('Python/SQL source audit disagreement')
            counts.append({'query_id':q['id'],'language':q['language'],'scope_rounds':len(scoped),
                           'relevant_rounds':len(supports),'relevant_with_literal_entity':len(literal_supports),
                           'alias_only_rounds':len(set(supports)-literal_supports)})
            judgments.append({'query_id':q['id'],'status':'approved','reviewer':'Codex (AI-assisted source audit)',
                              'reviewed_at':datetime.now(timezone.utc).isoformat(),'exhaustive':True,
                              'scope_basis':{'criteria':rule,'team_aliases':aliases,'scope_rounds':len(scoped),
                                             'source_check':'Full frozen scope; Python predicates agree with raw-node JSON SQL. Shared parser errors remain possible.'},
                              'relevance':[{'source_round_id':key,'grade':3,'source_event_ids':value,
                                            'basis':'Roster participation and requested event predicates satisfied in frozen source.'}
                                           for key,value in sorted(supports.items())]})
    if digest(graph_db) != frozen['source_graph_sha256']:
        raise ValueError('Source graph changed during audit')
    return {'version':'fair-ai-qrels-v1','reviewer_kind':'ai_assisted','independent_human_review':False,
            'corpus_sha256':digest(corpus),'queries_sha256':digest(queries),'source_graph_sha256':digest(graph_db),
            'criteria_sha256':digest(criteria),'audit_source_sha256':digest(__file__),
            'label_basis':'AI interpretation plus exhaustive predicates over parsed events; not raw-video human gold labels',
            'judgments':judgments,'counts':counts}


def score_cached(corpus, queries, qrels, ranking):
    original = json.loads(ranking.read_text())
    packet = json.loads(qrels.read_text())
    dataset = json.loads(queries.read_text())
    docs = [json.loads(line) for line in corpus.read_text().splitlines()]
    hashes = {'corpus_sha256':digest(corpus),'queries_sha256':digest(queries)}
    if any(original[key] != value for key,value in hashes.items()):
        raise ValueError('Frozen ranking hashes differ')
    labels = reviewed_qrels(packet,docs,dataset,**{'corpus_hash':hashes['corpus_sha256'],'query_hash':hashes['queries_sha256']})
    if labels is None or packet.get('reviewer_kind') != 'ai_assisted':
        raise ValueError('Complete AI source audit required')
    cases = {c['id']:c for c in dataset['cases']}
    methods = original['contract']['text_methods']+original['contract']['structured_references']
    expected = {(q,m,c) for q in cases for m in methods for c in (False,True)}
    actual = [(r['query_id'],r['method'],r['entity_constraint']) for r in original['cases']]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError('Frozen rankings have missing or duplicate cases')
    rows=[]
    known_ids = {doc['id'] for doc in docs}
    for row in original['cases']:
        if len(set(row['source_ids'])) != len(row['source_ids']) or not set(row['source_ids']) <= known_ids:
            raise ValueError('Frozen ranking has duplicate or unknown source IDs')
        q = row['query_id']
        rows.append({key:row[key] for key in ('query_id','method','entity_constraint','source_ids')} |
                    {'language':cases[q]['language'],'metrics':metrics(row['source_ids'],labels[q],original['contract']['k'])})
    summaries=[]
    for method in methods:
        for constraint in (False,True):
            for language in ('all','en','zh'):
                subset=[r for r in rows if r['method']==method and r['entity_constraint']==constraint and (language=='all' or r['language']==language)]
                scores={}
                for name in ('recall_at_k','ndcg_at_k','false_retrieval','false_abstention'):
                    values=[r['metrics'][name] for r in subset if r['metrics'][name] is not None]
                    scores[name]={'mean':statistics.mean(values) if values else None,'n':len(values)}
                summaries.append({'method':method,'entity_constraint':constraint,'language':language,'quality':scores})
    return {'version':'fair-ai-posthoc-v1','status':'ai_assisted_posthoc_evaluation','created_at':datetime.now(timezone.utc).isoformat(),
            **hashes,'qrels_sha256':digest(qrels),'ranking_sha256':digest(ranking),'scoring_source_sha256':digest(__file__),
            'metric_source_sha256':digest(Path(__file__).with_name('evaluate_fair_retrieval.py')),
            'independent_human_review':False,'fresh_retrieval_run':False,'remote_model_calls':0,
            'k':original['contract']['k'],'queries':len(cases),'positive_queries':sum(bool(v) for v in labels.values()),
            'negative_queries':sum(not v for v in labels.values()),'summary':summaries,'cases':rows,
            'limitations':['Post-hoc AI review of already-used development queries; no blind or unseen generalization claim.',
                           'Same parsed events underpin labels and retrieval; video/parser truth not independently validated.',
                           'Team aliases count as relevant; frozen exact entity filtering can miss these rounds.',
                           'Chinese BM25 and chunk-averaged MiniLM are pilot baselines; no production GraphRAG superiority claim.',
                           'Timings remain in original frozen smoke report; no timing rerun or confidence intervals claimed.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=False)
    corpus=Path('data/evaluation/fair_v1/corpus.jsonl')
    queries=Path('datasets/evaluation/fair_queries_v1.json')
    packet=audit(corpus,queries,Path('data/graph/cs2_graph.sqlite'),Path('datasets/evaluation/fair_corpus_manifest_v1.json'),
                 Path('datasets/evaluation/fair_ai_review_criteria_v1.json'))
    labels=args.output_dir/'qrels.json'
    write_json(labels,packet)
    report=score_cached(corpus,queries,labels,Path('datasets/evaluation/fair_retrieval_smoke_v2_report.json'))
    write_json(args.output_dir/'report.json',report)
    print(json.dumps({'status':report['status'],'counts':packet['counts']},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
