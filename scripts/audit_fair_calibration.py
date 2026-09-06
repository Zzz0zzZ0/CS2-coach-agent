"""Audit paired calibration invariants and describe its small development sample."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics

from scripts.evaluate_fair_retrieval import digest, write_json


def audit(report_path, protocol_path):
    report=json.loads(report_path.read_text()); protocol=json.loads(protocol_path.read_text())
    assert digest(protocol_path)==report['protocol_sha256']
    assert all(digest(x['path'])==x['sha256'] for x in protocol['inputs'].values())
    paths={k:Path(v['path']) for k,v in protocol['inputs'].items()}
    queries={q['id']:q for q in json.loads(paths['queries'].read_text())['cases']}
    docs=[json.loads(x) for x in paths['corpus'].read_text().splitlines()]
    labels={q['query_id']:{r['source_round_id'] for r in q['relevance'] if r['grade']>0}
            for q in json.loads(paths['qrels'].read_text())['judgments']}
    aliases=json.loads(paths['adapters'].read_text())['entity_aliases']
    configs={c['name']:c for c in protocol['configurations']}
    rows={(r['configuration'],r['query_id'],r['method'],r['entity_constraint']):r for r in report['cases']}
    assert len(rows)==len(report['cases'])==len(queries)*len(configs)*5*2
    counters=defaultdict(int)
    for (cfg,qid,method,constraint),r in rows.items():
        q=queries[qid];allowed=set()
        for d in docs:
            names=set(d['entities'])
            if configs[cfg]['aliases']:
                for group in aliases.values():
                    if names.intersection(group): names.update(group)
            if all(d[k]==v for k,v in q['filters'].items()) and (not constraint or all(e.casefold() in names for e in q['entities'])):
                allowed.add(d['id'])
        assert len(r['source_ids'])<=report['k'] and len(r['source_ids'])==len(set(r['source_ids']))
        assert set(r['source_ids'])<=allowed
        assert r['allowed_rounds']==len(allowed) and r['relevant_rounds_available']==len(allowed & labels[qid])
        counters['scope_and_candidate_counts']+=1
        exact='glossary_exact' if configs[cfg]['glossary'] else 'raw_exact'
        raw='raw_alias' if configs[cfg]['aliases'] else 'raw_exact'
        if configs[cfg]['aliases'] and not constraint:
            assert r['source_ids']==rows[(exact,qid,method,constraint)]['source_ids']
            counters['aliases_no_effect_when_disabled']+=1
        if configs[cfg]['glossary'] and q['language']=='en':
            assert r['source_ids']==rows[(raw,qid,method,constraint)]['source_ids']
            counters['english_unchanged_by_zh_glossary']+=1
        if configs[cfg]['glossary'] and method in ('sql_reference','graph_path_reference'):
            assert r['source_ids']==rows[(raw,qid,method,constraint)]['source_ids']
            counters['structured_references_unchanged_by_glossary']+=1
    groups=defaultdict(dict)
    for q in queries.values():groups[q['semantic_group']][q['language']]=q['id']
    difficulty=[]; coverage=[]; gaps=[]; drops=[]
    for group,languages in groups.items():
        qid=languages['en']
        raw=rows[('raw_exact',qid,'dense',True)];adapted=rows[('raw_alias',qid,'dense',True)]
        relevant=adapted['relevant_rounds_total'];available=adapted['allowed_rounds']
        difficulty.append({'semantic_group':group,'eligible_rounds':available,'relevant_rounds':relevant,
            'relevant_fraction':relevant/available if available else None,
            'recall_at_5_ceiling':min(report['k'],relevant)/relevant if relevant else None})
        if raw['relevant_rounds_available']!=adapted['relevant_rounds_available']:
            coverage.append({'semantic_group':group,'before':raw['relevant_rounds_available'],
                             'after':adapted['relevant_rounds_available'],'total_relevant':relevant})
    for cfg in configs:
        for method in ('bm25','dense','dense_bm25_rrf'):
            differences=[]
            for group,languages in groups.items():
                en=rows[(cfg,languages['en'],method,True)]['metrics']['ndcg_at_k']
                zh=rows[(cfg,languages['zh'],method,True)]['metrics']['ndcg_at_k']
                if en is not None:differences.append(zh-en)
            gaps.append({'configuration':cfg,'method':method,'positive_semantic_groups':len(differences),
                'mean_zh_minus_en_ndcg':statistics.mean(differences),'mean_absolute_paired_gap':statistics.mean(map(abs,differences))})
    for (cfg,qid,method,constraint),r in rows.items():
        if cfg=='glossary_alias' and constraint and method in ('bm25','dense','dense_bm25_rrf'):
            current=r['metrics']['ndcg_at_k'];before=rows[('raw_exact',qid,method,True)]['metrics']['ndcg_at_k']
            if current is not None and current<before:
                drops.append({'query_id':qid,'method':method,'before':before,'after':current})
    return {'version':'fair-calibration-audit-v1','report_sha256':digest(report_path),
        'audit_source_sha256':digest(__file__),'passed':True,'checks':dict(counters),
        'alias_relevance_recovered':coverage,'question_difficulty':difficulty,'language_gaps':gaps,
        'combined_vs_raw_per_query_drops':drops,'limitations':'Descriptive development audit; translations are grouped and no independent-sample or causal claim is made.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--protocol',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result=audit(args.report,args.protocol);write_json(args.output,result)
    print(json.dumps({k:result[k] for k in ('passed','checks','alias_relevance_recovered','combined_vs_raw_per_query_drops')},ensure_ascii=False,indent=2))
