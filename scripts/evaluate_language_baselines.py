"""Development-only lexical tokenization and bilingual dense controls on identical raw facts."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sqlite3
import statistics
import time

from scripts.evaluate_fair_retrieval import digest,eligible,encode,metrics,write_json
from scripts.calibrate_fair_retrieval import expand_query


def lexical_tokens(text,tokenizer=None):
    if tokenizer is None: return re.findall(r'[^\W_]+',text.casefold())
    # Stable pretrained subword IDs preserve Chinese boundaries without a new runtime dependency.
    return [f'v{i}' for i in tokenizer.encode(text,add_special_tokens=False).ids]


def lexical_index(texts,tokenizer=None):
    db=sqlite3.connect(':memory:')
    db.execute("CREATE VIRTUAL TABLE texts USING fts5(text,tokenize='unicode61')")
    for i,text in enumerate(texts):
        db.execute('INSERT INTO texts(rowid,text) VALUES (?,?)',(i,' '.join(lexical_tokens(text,tokenizer))))
    return db


def lexical_rank(db,text,allowed,tokenizer=None):
    tokens=lexical_tokens(text,tokenizer)
    if not tokens or not allowed:return []
    expression=' OR '.join('"'+t+'"' for t in tokens)
    marks=','.join('?' for _ in allowed)
    return [r[0] for r in db.execute(f'SELECT rowid FROM texts WHERE texts MATCH ? AND rowid IN ({marks}) ORDER BY bm25(texts),rowid',(expression,*allowed))]


def rrf(*rankings):
    scores=defaultdict(float)
    for ranking in rankings:
        for rank,i in enumerate(ranking,1):scores[i]+=1/(60+rank)
    return sorted(scores,key=lambda i:(-scores[i],i))


def summarize(rows):
    result=[]
    for config in sorted({r['configuration'] for r in rows}):
        for method in sorted({r['method'] for r in rows}):
            for language in ('en','zh','paired_macro'):
                subset=[r for r in rows if r['configuration']==config and r['method']==method and (language=='paired_macro' or r['language']==language)]
                quality={}
                for key in ('ndcg_at_k','recall_at_k','false_retrieval','false_abstention'):
                    groups=defaultdict(list)
                    for r in subset:
                        if r['metrics'][key] is not None:groups[r['query_id']].append(r['metrics'][key])
                    values=[statistics.mean(v) for v in groups.values()]
                    quality[key]={'mean':statistics.mean(values) if values else None,'semantic_groups':len(values)}
                result.append({'configuration':config,'method':method,'language':language,'metrics':quality})
    return result


def run(protocol_path):
    import numpy as np
    from fastembed import TextEmbedding
    from tokenizers import Tokenizer
    protocol=json.loads(protocol_path.read_text())
    def verify():
        for item in protocol['inputs'].values():
            if digest(item['path'])!=item['sha256']:raise ValueError('Input changed')
        for path,sha in protocol['implementation_sha256'].items():
            if digest(path)!=sha:raise ValueError('Implementation changed')
        for config in protocol['models'].values():
            for path,sha in config['files_sha256'].items():
                if digest(Path(config['path'])/path)!=sha:raise ValueError('Model changed')
    verify()
    paths={k:Path(v['path']) for k,v in protocol['inputs'].items()}
    docs=[json.loads(line) for line in paths['corpus'].read_text().splitlines()]
    cases=json.loads(paths['queries'].read_text())['cases']
    packet=json.loads(paths['qrels'].read_text())
    if packet['corpus_sha256']!=digest(paths['corpus']) or packet['queries_sha256']!=digest(paths['queries']):raise ValueError('Label provenance mismatch')
    if packet['independent_human_review'] is not False:raise ValueError('Unexpected review identity')
    judgments={j['query_id']:j for j in packet['judgments']}
    allowed={q['id']:[i for i,d in enumerate(docs) if eligible(d,q,True)] for q in cases}
    for q in cases:
        if [docs[i]['id'] for i in allowed[q['id']]]!=judgments[q['id']]['eligible_round_ids']:raise ValueError('Scope drift')
    # Dense vectors are document independent. Encode only the union of explicitly eligible scopes;
    # retain the full 1019-document corpus for BM25 IDF. No qrels used for candidate selection.
    needed=sorted({i for scope in allowed.values() for i in scope})
    local={i:j for j,i in enumerate(needed)}
    glossary=json.loads(paths['adapters'].read_text())['zh_glossary']
    texts={(q['id'],lang,config):(expand_query(text,glossary) if config=='glossary' else text)
           for q in cases for lang,text in q['texts'].items() for config in ('raw','glossary')}
    unique=list(dict.fromkeys(texts.values()));query_index={text:i for i,text in enumerate(unique)}
    dense={};encodings={}
    for name,config in protocol['models'].items():
        model=TextEmbedding(config['model'],specific_model_path=config['path'],local_files_only=True,threads=2)
        actual=model.model.tokenizer.truncation['max_length']
        if actual!=config['expected_max_length']:raise ValueError('Actual tokenizer limit differs')
        encoded_docs=list(range(len(docs))) if name=='minilm' else needed
        started=time.perf_counter();all_vectors,chunk_info=encode(model,[docs[i]['text'] for i in encoded_docs]);ms=(time.perf_counter()-started)*1000
        dv=all_vectors[needed] if name=='minilm' else all_vectors
        # Preserve original quantized MiniLM batch boundaries for the baseline parity check.
        started=time.perf_counter();query_results=[encode(model,[text]) for text in unique]
        qv=np.stack([v[0] for v,_ in query_results]);qms=(time.perf_counter()-started)*1000
        qchunks={'chunks':sum(info['chunks'] for _,info in query_results),'batching':'one query at a time'}
        dense[name]=(dv,qv)
        encodings[name]={'document_count':len(encoded_docs),'eligible_document_count':len(needed),'corpus_count':len(docs),'document_chunks':chunk_info,'document_encoding_ms':ms,
                         'unique_query_count':len(unique),'query_chunks':qchunks,'query_encoding_ms':qms,
                         'document_vector_sha256':__import__('hashlib').sha256(dv.tobytes()).hexdigest()}
        print('Embedded '+name,flush=True)
        del model
    tokenizer=Tokenizer.from_file(str(Path(protocol['models']['jina']['path'])/'tokenizer.json'))
    tokenizer.no_truncation();tokenizer.no_padding()
    dbs={'unicode':lexical_index([d['text'] for d in docs]),'subword':lexical_index([d['text'] for d in docs],tokenizer)}
    rows=[]
    for q in cases:
        scope=allowed[q['id']]
        labels={r['source_round_id']:r['grade'] for r in judgments[q['id']]['relevance']}
        for lang in q['texts']:
            for config in ('raw','glossary'):
                text=texts[q['id'],lang,config];rankings={};durations={}
                for lex,db in dbs.items():
                    name='bm25_'+lex;start=time.perf_counter()
                    rankings[name]=lexical_rank(db,text,scope,tokenizer if lex=='subword' else None)
                    durations[name]=(time.perf_counter()-start)*1000
                for name,(dv,qv) in dense.items():
                    start=time.perf_counter();scores=dv@qv[query_index[text]]
                    rankings['dense_'+name]=sorted(scope,key=lambda i:(-float(scores[local[i]]),i))
                    durations['dense_'+name]=(time.perf_counter()-start)*1000
                for lex in dbs:
                    for name in dense:
                        method=f'rrf_{lex}_{name}';start=time.perf_counter()
                        rankings[method]=rrf(rankings['bm25_'+lex],rankings['dense_'+name])
                        durations[method]=durations['bm25_'+lex]+durations['dense_'+name]+(time.perf_counter()-start)*1000
                for method,ranked in rankings.items():
                    ids=[docs[i]['id'] for i in ranked[:protocol['k']]]
                    if not set(ranked)<=set(scope):raise ValueError('Outside scope')
                    rows.append({'query_id':q['id'],'family':q['relation']['family'],'language':lang,'configuration':config,'method':method,
                        'effective_query':text,'source_ids':ids,'eligible_rounds':len(scope),'relevant_rounds':len(labels),
                        'metrics':metrics(ids,labels,protocol['k']),'search_ms_excluding_encoding':durations[method]})
    for db in dbs.values():db.close()
    old=json.loads(paths['previous_rankings'].read_text())['cases']
    lookup={(r['query_id'],r['language'],r['method']):r['source_ids'] for r in old}
    mapping={'bm25_unicode':'bm25','dense_minilm':'dense','rrf_unicode_minilm':'dense_bm25_rrf'}
    baseline=[r for r in rows if r['configuration']=='raw' and r['method'] in mapping]
    parity=sum(r['source_ids']==lookup[r['query_id'],r['language'],mapping[r['method']]] for r in baseline)
    verify()
    return {'protocol_sha256':digest(protocol_path),'rows':len(rows),'remote_model_calls':0,'encodings':encodings,
            'baseline_parity':{'passed':parity,'total':len(baseline)},'summary':summarize(rows),'cases':rows,'limitations':protocol['limitations']}


if __name__=='__main__':
    import socket
    def denied(*args,**kwargs):raise RuntimeError('Benchmark is offline')
    socket.socket.connect=socket.socket.connect_ex=denied
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--protocol',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():p.error('Output exists')
    report=run(args.protocol);write_json(args.output,report)
    print(json.dumps({'rows':report['rows'],'baseline_parity':report['baseline_parity'],'paired':[r for r in report['summary'] if r['language']=='paired_macro']},indent=2))
    raise SystemExit(0 if report['baseline_parity']['passed']==report['baseline_parity']['total'] else 1)
