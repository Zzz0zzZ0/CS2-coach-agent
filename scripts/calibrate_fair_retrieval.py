"""Frozen paired-language development calibration; no production stores or remote models."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import statistics
import time

from scripts.evaluate_fair_retrieval import (
    MODEL, METHODS, build_index, digest, eligible, encode, metrics, ranks,
    reviewed_qrels, validate_inputs, write_json,
)


def alias_entities(docs, groups):
    lookup = {}
    for canonical, names in groups.items():
        values = {name.casefold() for name in names}
        if canonical.casefold() not in values or len(values) < 2:
            raise ValueError('Alias group must include its canonical name and an alternative')
        for name in values:
            if name in lookup:
                raise ValueError('Overlapping alias groups')
            lookup[name] = values
    return [{**doc, 'entities': sorted({alias for name in doc['entities']
                                      for alias in lookup.get(name.casefold(), {name.casefold()})})} for doc in docs]


def expand_query(query, glossary):
    # ponytail: bounded domain glossary, not general translation/negation parsing.
    terms = dict.fromkeys(word for phrase, expansion in glossary.items() if phrase in query
                          for word in expansion.split())
    return ' '.join([query, *terms])


def check_pairs(dataset, labels):
    groups = defaultdict(list)
    for q in dataset['cases']:
        groups[q['semantic_group']].append(q)
    for queries in groups.values():
        if len(queries) != 2 or {q['language'] for q in queries} != {'en','zh'}:
            raise ValueError('Each semantic group needs exactly one English and Chinese query')
        left, right = queries
        if any(left[key] != right[key] for key in ('filters','entities','event_kind')) or labels[left['id']] != labels[right['id']]:
            raise ValueError('Paired scope or relevance differs')
    return groups


def summarize(rows):
    summaries = []
    for config in dict.fromkeys(r['configuration'] for r in rows):
        for method in METHODS:
            for constraint in (False, True):
                candidates = [r for r in rows if r['configuration']==config and r['method']==method and r['entity_constraint']==constraint]
                for language in ('en','zh','paired_macro'):
                    subset = [r for r in candidates if language=='paired_macro' or r['language']==language]
                    quality = {}
                    for key in ('ndcg_at_k','recall_at_k','false_retrieval','false_abstention'):
                        grouped=defaultdict(list)
                        for r in subset:
                            if r['metrics'][key] is not None:
                                grouped[r['semantic_group']].append(r['metrics'][key])
                        values=[statistics.mean(v) for v in grouped.values()]
                        quality[key]={'mean':statistics.mean(values) if values else None,'n_semantic_groups':len(values)}
                    summaries.append({'configuration':config,'method':method,'entity_constraint':constraint,
                                      'language':language,'quality':quality})
    return summaries


def run(protocol_path, model_dir):
    import numpy as np
    from fastembed import TextEmbedding
    protocol=json.loads(protocol_path.read_text())
    for name, item in protocol['inputs'].items():
        if digest(item['path']) != item['sha256']:
            raise ValueError(f'Frozen input changed: {name}')
    for path, expected in protocol['implementation_sha256'].items():
        if digest(path) != expected:
            raise ValueError(f'Frozen implementation changed: {path}')
    artifacts={str(p.relative_to(model_dir)):digest(p) for p in sorted(model_dir.rglob('*')) if p.is_file()}
    if artifacts != protocol['model_files_sha256']:
        raise ValueError('Frozen local model changed')
    paths={k:Path(v['path']) for k,v in protocol['inputs'].items()}
    docs=[json.loads(line) for line in paths['corpus'].read_text().splitlines()]
    dataset=json.loads(paths['queries'].read_text()); validate_inputs(docs,dataset)
    packet=json.loads(paths['qrels'].read_text())
    if packet.get('reviewer_kind') != 'ai_assisted' or packet.get('independent_human_review') is not False:
        raise ValueError('This run requires explicit AI label provenance')
    labels=reviewed_qrels(packet,docs,dataset,digest(paths['corpus']),digest(paths['queries']))
    if labels is None:
        raise ValueError('Complete source audit required')
    groups=check_pairs(dataset,labels)
    config=json.loads(paths['adapters'].read_text())
    adapted=alias_entities(docs,config['entity_aliases'])
    model=TextEmbedding(MODEL,local_files_only=True,threads=2,specific_model_path=str(model_dir))
    started=time.perf_counter()
    vectors,chunks=encode(model,[d['text'] for d in docs])
    embedding_ms=(time.perf_counter()-started)*1000
    vector_hash=hashlib.sha256(vectors.tobytes()).hexdigest()
    original=json.loads(paths['previous_rankings'].read_text())
    if vector_hash != original['index']['vector_sha256']:
        raise ValueError('Common corpus embedding differs from the previous frozen run')
    encoded={}
    for q in dataset['cases']:
        for glossary in (False,True):
            text=expand_query(q['query'],config['zh_glossary']) if glossary else q['query']
            if text not in encoded:
                started=time.perf_counter(); v, _=encode(model,[text])
                encoded[text]=(v[0],(time.perf_counter()-started)*1000)
    db=build_index(docs)
    rows=[]
    for configuration in protocol['configurations']:
        source_docs=adapted if configuration['aliases'] else docs
        for constraint in (False,True):
            for q in dataset['cases']:
                text=expand_query(q['query'],config['zh_glossary']) if configuration['glossary'] else q['query']
                case={**q,'query':text}
                durations=defaultdict(list); found=None
                for _ in range(protocol['repeats']):
                    current,elapsed=ranks(db,source_docs,case,constraint,encoded[text][0],vectors,protocol['k'])
                    if found is not None and current!=found:
                        raise ValueError('Nondeterministic ranking')
                    found=current
                    for method,ms in elapsed.items():durations[method].append(ms)
                allowed={d['id'] for d in source_docs if eligible(d,case,constraint)}
                relevant=labels[q['id']]
                for method, ranked in found.items():
                    ids=[docs[i]['id'] for i in ranked]
                    rows.append({'configuration':configuration['name'],'query_id':q['id'],
                        'semantic_group':q['semantic_group'],'language':q['language'],
                        'input_query':q['query'],'effective_query':text,'method':method,'entity_constraint':constraint,
                        'allowed_rounds':len(allowed),'relevant_rounds_available':len(allowed & relevant.keys()),
                        'relevant_rounds_total':len(relevant),'source_ids':ids,
                        'metrics':metrics(ids,relevant,protocol['k']),
                        'query_encoding_ms':encoded[text][1] if method in ('dense','dense_bm25_rrf') else 0,
                        'first_search_ms':durations[method][0],'warm_search_ms':durations[method][1:]})
        print('Completed '+configuration['name'],flush=True)
    db.close()
    old={(r['query_id'],r['method'],r['entity_constraint']):r['source_ids'] for r in original['cases']}
    baseline=[r for r in rows if r['configuration']=='raw_exact' and r['query_id'] in {q['id'] for q in dataset['cases'] if q['variant']=='original'}]
    parity=sum(r['source_ids']==old[(r['query_id'],r['method'],r['entity_constraint'])] for r in baseline)
    if len(baseline)!=len(old) or parity!=len(old):
        raise ValueError('Raw original-query rankings drifted from frozen baseline')
    if any(digest(item['path']) != item['sha256'] for item in protocol['inputs'].values()):
        raise ValueError('Frozen inputs changed during run')
    return {'version':'fair-calibration-v1','created_at':datetime.now(timezone.utc).isoformat(),
        'protocol_sha256':digest(protocol_path),'inputs':protocol['inputs'],
        'reviewer_kind':'ai_assisted','independent_human_review':False,'remote_model_calls':0,
        'semantic_groups':len(groups),'surface_queries':len(dataset['cases']),'result_rows':len(rows),
        'baseline_parity':{'passed':parity,'total':len(old)},'k':protocol['k'],
        'corpus_embedding':{'sha256':vector_hash,'chunks':chunks,'ms':embedding_ms},
        'summary':summarize(rows),'cases':rows,
        'limitations':protocol['limitations']}


if __name__=='__main__':
    import socket
    def denied(*args,**kwargs):raise RuntimeError('Calibration is offline')
    socket.socket.connect=socket.socket.connect_ex=denied
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--protocol',type=Path,required=True)
    p.add_argument('--model-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():p.error('Output exists; choose a new path')
    write_json(args.output,run(args.protocol,args.model_dir))
