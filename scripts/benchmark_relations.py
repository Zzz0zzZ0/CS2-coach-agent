"""Source-selected relation development benchmark. Freeze before retrieval, never tune on rankings."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import statistics
import time

from scripts.evaluate_fair_retrieval import (
    MODEL, build_index, digest, eligible, encode, metrics, ranks, write_json,
)

ROOT = Path('datasets/evaluation')
BASE = Path('data/evaluation/fair_v2/corpus.jsonl')
CORPUS = Path('data/evaluation/relations_v1/corpus.jsonl')
PREFIX = 'relation_v1'
# Chosen from event-count inventory, before retrieval. No ranking-based selection.
SELECTION = [
    ('2396949', 'Nuke', [('kyousuke','tN1R'),('m0NESY','magixx')], [('NiKo','zont1x'),('TeSeS','tN1R')], [('donk','zont1x'),('karrigan','kyousuke')]),
    ('2396948', 'Dust2', [('molodoy','jL'),('ropz','yuurih')], [('ropz','yuurih'),('flameZ','FalleN')], [('jL','apEX'),('KSCERATO','YEKINDAR')]),
    ('2396614', 'Ancient', [('donk','xfl0ud'),('dem0n','donk')], [('dem0n','donk'),('dem0n','zont1x')], [('zont1x','donk'),('cmtry','dziugss')]),
    ('2396609', 'Mirage', [('m0NESY','dumau'),('latto','m0NESY')], [('dumau','NiKo'),('try','kyousuke')], [('arT','n1ssim'),('NiKo','kyousuke')]),
]
FAMILIES = ('opening', 'after_plant', 'trade')
TEXT_METHODS = ('bm25', 'dense', 'dense_bm25_rrf')


def witnesses(doc, query, relaxed=False):
    """Exact source predicates; relaxed witnesses expose plausible near misses, not qrels."""
    rule = query['relation']; actor, target = rule['actor'], rule['target']
    kills = [e for e in doc['events'] if e['kind']=='kill']
    plants = [e for e in doc['events'] if e['kind']=='plant']
    found = []
    for e in kills:
        p = e['properties']
        if rule['family'] in ('opening', 'after_plant'):
            if p['killer_steamid'] != actor or p['victim_steamid'] != target:
                continue
            if rule['family']=='opening':
                if relaxed or p['is_first_kill'] is True: found.append([e['id']])
            else:
                for plant in plants:
                    if relaxed or plant['properties']['tick'] < p['tick']:
                        found.append([plant['id'], e['id']])
        elif rule['family']=='trade':
            if p['victim_steamid'] != target: continue
            for response in kills:
                r = response['properties']; delay = r['tick'] - p['tick']
                if (r['killer_steamid']==actor and r['victim_steamid']==p['killer_steamid']
                    and len({actor,target,p['killer_steamid']})==3
                    and r['killer_team']==p['victim_team'] and r['killer_team']!=p['killer_team']
                    and 0 < delay and (relaxed or delay <= rule['window_ticks'])):
                    found.append([e['id'], response['id']])
        else:
            raise ValueError('Unsupported relation family')
    return sorted(found)


def source_index(docs):
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE events(doc TEXT,id TEXT,kind TEXT,p TEXT)')
    db.executemany('INSERT INTO events VALUES (?,?,?,?)',
                   [(d['id'],e['id'],e['kind'],json.dumps(e['properties'])) for d in docs for e in d['events']])
    db.execute('CREATE INDEX event_doc ON events(doc,kind)')
    return db


def sql_witnesses(db, doc_id, query, relaxed=False):
    """Independent relational joins over raw JSON fields; no Python predicate or qrel lookup."""
    rule=query['relation']; args={'doc':doc_id,'actor':rule['actor'],'target':rule['target'], 'window':rule.get('window_ticks',320)}
    if rule['family']=='opening':
        sql="""SELECT id FROM events WHERE doc=:doc AND kind='kill'
        AND json_extract(p,'$.killer_steamid')=:actor AND json_extract(p,'$.victim_steamid')=:target"""
        if not relaxed: sql += " AND json_extract(p,'$.is_first_kill')=1"
    elif rule['family']=='after_plant':
        sql="""SELECT b.id,k.id FROM events b JOIN events k ON b.doc=k.doc
        WHERE b.doc=:doc AND b.kind='plant' AND k.kind='kill'
        AND json_extract(k.p,'$.killer_steamid')=:actor AND json_extract(k.p,'$.victim_steamid')=:target"""
        if not relaxed: sql += " AND json_extract(b.p,'$.tick') < json_extract(k.p,'$.tick')"
    elif rule['family']=='trade':
        sql="""SELECT d.id,r.id FROM events d JOIN events r ON d.doc=r.doc
        WHERE d.doc=:doc AND d.kind='kill' AND r.kind='kill'
        AND json_extract(d.p,'$.victim_steamid')=:target AND json_extract(r.p,'$.killer_steamid')=:actor
        AND json_extract(r.p,'$.victim_steamid')=json_extract(d.p,'$.killer_steamid')
        AND :actor != :target AND :actor != json_extract(d.p,'$.killer_steamid')
        AND :target != json_extract(d.p,'$.killer_steamid')
        AND json_extract(r.p,'$.killer_team')=json_extract(d.p,'$.victim_team')
        AND json_extract(r.p,'$.killer_team')!=json_extract(d.p,'$.killer_team')
        AND json_extract(r.p,'$.tick') > json_extract(d.p,'$.tick')"""
        if not relaxed: sql += " AND json_extract(r.p,'$.tick')-json_extract(d.p,'$.tick') <= :window"
    else: raise ValueError('Unsupported relation family')
    return sorted([list(row) for row in db.execute(sql,args)])


def relation_text(doc):
    # Share observable role/team/time facts with every text method; no relation labels.
    lines = [line for i, line in enumerate(doc['text'].splitlines()) if i == 0 or line.startswith('Participant ')]
    for e in sorted(doc['events'],key=lambda e:(e['properties']['tick'],e['id'])):
        p=e['properties']
        if e['kind']=='kill':
            detail=(f"{p['killer']} team {p['killer_team']} side {p['killer_side']} kills "
                    f"{p['victim']} team {p['victim_team']} side {p['victim_side']} weapon {p.get('weapon')}"
                    + (' opening first kill' if p['is_first_kill'] else ''))
        elif e['kind']=='plant':
            detail=f"{p['planter']} team {p['planter_team']} side {p['planter_side']} bomb plant site {p['site']}"
        elif e['kind']=='grenade':
            detail=f"{p.get('thrower')} grenade {p.get('grenade_type',p.get('type','utility'))}"
        else:
            detail=f"{p.get('attacker')} flash blinded {p.get('victim')} attribution {p.get('attribution','unspecified')}"
        lines.append(f"Tick {p['tick']}: {detail}.")
    return '\n'.join(lines)


def prepare():
    """One-time dataset preparation; refuses to overwrite frozen artifacts."""
    if any((ROOT/f'{PREFIX}_{name}.json').exists() for name in ('queries','qrels','protocol')) or CORPUS.exists():
        raise ValueError('Existing experiment; choose a new version')
    docs=[json.loads(s) for s in BASE.read_text().splitlines()]
    graph=Path('data/graph/cs2_graph.sqlite')
    with sqlite3.connect(graph.resolve().as_uri()+'?mode=ro',uri=True) as db:
        raw={r[0]:json.loads(r[1]) for r in db.execute("SELECT node_id,properties FROM nodes WHERE node_type='event'")}
    packet_events={e['id']:e['properties'] for d in docs for e in d['events']}
    if raw != packet_events: raise ValueError('Raw graph/corpus event mismatch')
    for d in docs:
        for e in d['events']:
            p=e['properties']
            if type(p.get('tick')) is not int: raise ValueError('Unknown timestamp')
            if e['kind']=='kill':
                for key in ('killer_steamid','victim_steamid','killer_team','victim_team'):
                    if not isinstance(p.get(key),str) or not p[key]: raise ValueError('Unknown kill identity/team')
                if type(p.get('is_first_kill')) is not bool: raise ValueError('Unknown opening flag')
    docs=[{**d,'text':relation_text(d)} for d in docs]
    CORPUS.parent.mkdir(parents=True,exist_ok=True)
    with CORPUS.open('x') as stream:
        for d in docs: stream.write(json.dumps(d,ensure_ascii=False,sort_keys=True)+'\n')
    queries=[]
    for index,(match,map_name,*pairs) in enumerate(SELECTION,1):
        scoped=[d for d in docs if d['match_id']==match and d['map']==map_name]
        identities=defaultdict(set)
        for d in scoped:
            for e in d['events']:
                if e['kind']=='kill':
                    p=e['properties']
                    identities[p['killer']].add(p['killer_steamid']); identities[p['victim']].add(p['victim_steamid'])
        for family,chosen in zip(FAMILIES,pairs):
            for polarity,(actor,target) in zip(('positive','negative'),chosen):
                if len(identities[actor])!=1 or len(identities[target])!=1: raise ValueError('Ambiguous actor')
                en={
                    'opening':f'Find rounds where {actor} makes the opening first kill by killing {target}.',
                    'after_plant':f'Find rounds where {actor} kills {target} strictly after a bomb plant in that round.',
                    'trade':f'Find rounds where {actor} trades teammate {target}: kills the enemy who killed {target}, more than 0 and at most 320 ticks later in the same round.',
                }[family]
                zh={
                    'opening':f'查找 {actor} 击杀 {target} 并拿到本回合首杀的回合。',
                    'after_plant':f'查找 {actor} 击杀 {target}，且这次击杀严格发生在该回合炸弹安放之后的回合。',
                    'trade':f'查找 {actor} 为队友 {target} 补枪的回合：在同一回合中，{target} 被敌人击杀后，{actor} 在大于 0 且不超过 320 tick 内击杀该敌人。',
                }[family]
                qid=f'{family}_{index}_{polarity}'
                relation={'family':family,'actor':next(iter(identities[actor])),'target':next(iter(identities[target]))}
                if family=='trade': relation['window_ticks']=320
                queries.append({'id':qid,'filters':{'match_id':match,'map':map_name},'entities':[actor,target],
                                'relation':relation,'construction_polarity':polarity,
                                'texts':{'en':f'Match {match}, map {map_name}. '+en,'zh':f'比赛 {match}，地图 {map_name}。'+zh}})
    query_path=ROOT/f'{PREFIX}_queries.json'
    write_json(query_path,{'version':PREFIX,'reviewer_kind':'ai_assisted','independent_human_review':False,'cases':queries})
    db=source_index(docs); judgments=[]
    for q in queries:
        scoped=[d for d in docs if eligible(d,q,True)]; relevant=[]; near=[]
        for d in scoped:
            exact=witnesses(d,q); relaxed=witnesses(d,q,True)
            if exact!=sql_witnesses(db,d['id'],q) or relaxed!=sql_witnesses(db,d['id'],q,True):
                raise ValueError('Python/SQL label disagreement')
            if exact: relevant.append({'source_round_id':d['id'],'grade':1,'witness_event_ids':exact})
            elif relaxed: near.append({'source_round_id':d['id'],'witness_event_ids':relaxed})
        if len(scoped)<12 or not near: raise ValueError('Insufficient valid scope/near misses')
        if (bool(relevant)!=(q['construction_polarity']=='positive') or len(relevant)>len(scoped)/2):
            raise ValueError('Dataset balance/difficulty mismatch')
        judgments.append({'query_id':q['id'],'eligible_round_ids':[d['id'] for d in scoped],
                          'relevance':relevant,'near_misses':near,'exhaustive':True})
    db.close()
    qrels_path=ROOT/f'{PREFIX}_qrels.json'
    write_json(qrels_path,{'reviewer_kind':'ai_assisted','independent_human_review':False,
        'corpus_sha256':digest(CORPUS),'queries_sha256':digest(query_path),'judgments':judgments,
        'source_audit':{'all_raw_events_equal_graph':len(raw),'python_sql_agreement':True,
                        'unknown_kill_identity_team_tick_or_opening':0}})
    model_protocol=json.loads((ROOT/'fair_calibration_v1_protocol.json').read_text())
    input_paths={'corpus':CORPUS,'queries':query_path,'qrels':qrels_path,'base_corpus':BASE,'graph':graph}
    write_json(ROOT/f'{PREFIX}_protocol.json',{
        'version':PREFIX,'created_at':datetime.now(timezone.utc).isoformat(),
        'inputs':{k:{'path':str(p),'sha256':digest(p)} for k,p in input_paths.items()},
        'implementation_sha256':{p:digest(p) for p in ['scripts/benchmark_relations.py','scripts/audit_relation_benchmark.py','scripts/evaluate_fair_retrieval.py','test_relation_benchmark.py']},
        'model_files_sha256':model_protocol['model_files_sha256'],'k':5,'repeats':3,
        'configuration':'Raw bilingual queries; shared exact roster and match/map scope; no glossary or relation slots in text ranking',
        'selection':'AI selected 4 matches / 4 maps using raw event counts before retrieval; 4 positive and 4 negative per family, each with near-miss rounds; intentionally source-selected development set.',
        'semantics':{'opening':'Exact named killer/victim and source is_first_kill=true.',
                     'after_plant':'Named killer/victim kill tick strictly greater than any bomb plant tick in same round.',
                     'trade':'Three distinct players: named teammate dies to enemy, named trader on teammate team kills same enemy; 0 < delay <= 320 ticks. Teams must match and differ from enemy team.'},
        'limitations':['AI-assisted labels and translations, no independent human gold.',
            'Same observed historical corpus; source-selected questions, no unseen/OOD or confidence interval claim.',
            'Python and SQL share parser facts; agreement is not independent demo validation.',
            'Explicit correct scope filters bypass natural-language entity resolution.',
            'SQL oracle gets relation slots, is a label sanity reference, not production GraphRAG.',
            'Text baselines return top-k without calibrated abstention; negative errors measure this pipeline, not inherent model inability.',
            'Timestamp-enriched corpus differs from old fair v2 representation; no cross-dataset score delta claims.']})
    print(json.dumps([{'id':j['query_id'],'eligible':len(j['eligible_round_ids']),'relevant':len(j['relevance']),'near':len(j['near_misses'])} for j in judgments],indent=2))


def run(protocol_path,model_dir):
    from fastembed import TextEmbedding
    protocol=json.loads(protocol_path.read_text())
    def verify():
        for item in protocol['inputs'].values():
            if digest(item['path'])!=item['sha256']: raise ValueError('Frozen input changed')
        for path,expected in protocol['implementation_sha256'].items():
            if digest(path)!=expected: raise ValueError('Frozen implementation changed')
    verify()
    if {str(p.relative_to(model_dir)):digest(p) for p in sorted(model_dir.rglob('*')) if p.is_file()} != protocol['model_files_sha256']:
        raise ValueError('Frozen model changed')
    paths={k:Path(v['path']) for k,v in protocol['inputs'].items()}
    docs=[json.loads(s) for s in paths['corpus'].read_text().splitlines()]
    queries=json.loads(paths['queries'].read_text())['cases']; packet=json.loads(paths['qrels'].read_text())
    if packet['corpus_sha256']!=digest(paths['corpus']) or packet['queries_sha256']!=digest(paths['queries']): raise ValueError('Label provenance mismatch')
    if packet['reviewer_kind']!='ai_assisted' or packet['independent_human_review'] is not False: raise ValueError('Review provenance changed')
    judgments={j['query_id']:j for j in packet['judgments']}
    oracle=source_index(docs); labels={}; oracle_ranks={}
    for q in queries:
        scoped=[d for d in docs if eligible(d,q,True)]
        if [d['id'] for d in scoped]!=judgments[q['id']]['eligible_round_ids']: raise ValueError('Scope drift')
        audited={}
        for d in scoped:
            events=sql_witnesses(oracle,d['id'],q)
            if events: audited[d['id']]=events
        expected={r['source_round_id']:r['witness_event_ids'] for r in judgments[q['id']]['relevance']}
        if audited!=expected: raise ValueError('Oracle/source label drift')
        labels[q['id']]={key:1 for key in audited}; oracle_ranks[q['id']]=list(audited)[:protocol['k']]
    oracle.close()
    model=TextEmbedding(MODEL,local_files_only=True,threads=2,specific_model_path=str(model_dir))
    started=time.perf_counter(); vectors,chunks=encode(model,[d['text'] for d in docs]); embedding_ms=(time.perf_counter()-started)*1000
    print('Corpus embedded',flush=True)
    db=build_index(docs); rows=[]
    for q in queries:
        for language,text in q['texts'].items():
            started=time.perf_counter(); query_vectors,_=encode(model,[text]); encoding_ms=(time.perf_counter()-started)*1000
            # Never pass relation slots, polarity, or qrels into a text ranking method.
            case={'query':text,'filters':q['filters'],'entities':q['entities'],'event_kind':'kill'}
            previous=None; durations=defaultdict(list)
            for _ in range(protocol['repeats']):
                found,elapsed=ranks(db,docs,case,True,query_vectors[0],vectors,protocol['k'])
                current={m:[docs[i]['id'] for i in found[m]] for m in TEXT_METHODS}
                if previous is not None and previous!=current: raise ValueError('Ranking nondeterminism')
                previous=current
                for m in TEXT_METHODS: durations[m].append(elapsed[m])
            current['relation_sql_oracle']=oracle_ranks[q['id']]
            for method,ids in current.items():
                allowed=set(judgments[q['id']]['eligible_round_ids'])
                if not set(ids)<=allowed: raise ValueError('Retrieval outside scope')
                rows.append({'query_id':q['id'],'family':q['relation']['family'],'language':language,
                    'method':method,'input_query':text,'source_ids':ids,'eligible_rounds':len(allowed),
                    'relevant_rounds':len(labels[q['id']]),'metrics':metrics(ids,labels[q['id']],protocol['k']),
                    'search_ms':durations.get(method), 'query_encoding_ms':encoding_ms if method in ('dense','dense_bm25_rrf') else 0})
        print('Completed '+q['id'],flush=True)
    db.close(); verify(); summaries=[]
    for method in (*TEXT_METHODS,'relation_sql_oracle'):
        for language in ('en','zh','paired_macro'):
            subset=[r for r in rows if r['method']==method and (language=='paired_macro' or r['language']==language)]
            scores={}
            for key in ('ndcg_at_k','recall_at_k','false_retrieval','false_abstention'):
                groups=defaultdict(list)
                for r in subset:
                    if r['metrics'][key] is not None: groups[r['query_id']].append(r['metrics'][key])
                scores[key]={'mean':statistics.mean(statistics.mean(v) for v in groups.values()),'semantic_groups':len(groups)}
            summaries.append({'method':method,'language':language,'metrics':scores})
    import hashlib
    return {'version':PREFIX,'protocol_sha256':digest(protocol_path),'created_at':datetime.now(timezone.utc).isoformat(),
        'remote_model_calls':0,'semantic_groups':len(queries),'surface_queries':2*len(queries),
        'corpus_embedding':{'sha256':hashlib.sha256(vectors.tobytes()).hexdigest(),'chunks':chunks,'ms':embedding_ms},
        'summary':summaries,'cases':rows,'limitations':protocol['limitations']}


if __name__=='__main__':
    import socket
    def denied(*args,**kwargs): raise RuntimeError('Relation benchmark is offline')
    socket.socket.connect=socket.socket.connect_ex=denied
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','run']); p.add_argument('--model-dir',type=Path)
    p.add_argument('--output',type=Path); args=p.parse_args()
    if args.action=='prepare': prepare()
    else:
        if not args.model_dir or not args.output or args.output.exists(): p.error('Model directory and a new output path required')
        write_json(args.output,run(ROOT/f'{PREFIX}_protocol.json',args.model_dir))
