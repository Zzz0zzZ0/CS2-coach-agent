"""Reuse the frozen context-cluster prototypes; unavailable facets remain unknown."""

from itertools import combinations
import json
from pathlib import Path
import sys
import time

import numpy as np
from sklearn.metrics import adjusted_rand_score

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.acquire_ct_independent_demos import digest
from scripts.confirm_ct_generalization import write
from scripts.retrieve_ct_independent_context import load_transfer_inputs
from scripts.transfer_ct_independent_patterns import assign_patterns
from scripts.evaluate_ct_reconstruction import statistics_sequence
from app.services.ct_context_retrieval_service import context_embedding, fused_embedding


def main():
    import psutil
    protocol=ROOT/'datasets/selections/ct_independent_context_patterns_v3.json'
    cfg=json.loads(protocol.read_text(encoding='utf-8'))
    for name,expected in cfg['input_sha256'].items():assert digest(ROOT/name)==expected,name
    old_index,new_index,old_data,new_data,old_context,new_context,folds=load_transfer_inputs()
    legacy=json.loads((ROOT/'datasets/evaluation/ct_context_pattern_report.json').read_text(encoding='utf-8'))
    original=json.loads((ROOT/'datasets/selections/ct_independent_confirmation.json').read_text(encoding='utf-8'))
    parameters=json.loads((ROOT/'datasets/selections/ct_context_pattern_analysis.json').read_text(encoding='utf-8'))
    source_stats=statistics_sequence(old_data);query_stats=statistics_sequence(new_data)
    out=ROOT/'output/tagnet/ct_independent_context_patterns_v3';assert not out.exists();out.mkdir()
    started=time.monotonic();models=[];saved={};assignments={}
    for row in legacy['models']:
        if row['task']!='G4':continue
        assert row['status']=='fitted'
        fold=folds[row['fold']];tr,old_q=np.asarray(fold['train']),np.asarray(fold['test'])
        map_name=row['fold'].removeprefix('G4__');q=np.asarray([i for i,r in enumerate(new_index) if r['map']==map_name])
        source_group={k:v[tr] for k,v in old_context.items()}
        old_ctx=context_embedding(source_group,{k:v[old_q] for k,v in old_context.items()})
        new_ctx=context_embedding(source_group,{k:v[q] for k,v in new_context.items()})
        variant,seed=row['variant'],row['seed'];method=variant.removesuffix('+context')
        if method=='context_only':
            old_vectors,new_vectors=old_ctx['queries'],new_ctx['queries'];known=new_ctx['query_supported']
        else:
            if method=='statistics_sequence':
                mean,std=source_stats[tr].mean(0),source_stats[tr].std(0).clip(1e-6)
                source_z=(source_stats[tr]-mean)/std;old_z=(source_stats[old_q]-mean)/std;new_z=(query_stats[q]-mean)/std
            else:
                prefix=ROOT/f"output/tagnet/ct_reconstruction_matrix/{row['fold']}/{method}_{seed}"
                lib=prefix.with_name(prefix.name+'_library.npz');old_file=prefix.with_name(prefix.name+'_evaluation.npz')
                assert digest(lib)==original['source_library_sha256'][lib.relative_to(ROOT).as_posix()]
                new_file=ROOT/f'output/tagnet/ct_independent_confirmation/{map_name}_{method}_{seed}.npz'
                with np.load(lib,allow_pickle=False) as a,np.load(old_file,allow_pickle=False) as b,np.load(new_file,allow_pickle=False) as c:
                    source_z,old_z,new_z=a['embeddings'],b['embeddings'],c['embeddings']
            if variant.endswith('+context'):
                _,old_vectors,_=fused_embedding(source_z,old_z,old_ctx,parameters['weight'])
                _,new_vectors,_=fused_embedding(source_z,new_z,new_ctx,parameters['weight'])
                known=new_ctx['query_supported']
            else:old_vectors,new_vectors,known=old_z,new_z,np.ones(len(q),dtype=bool)
        old_vectors,new_vectors=old_vectors.astype(np.float32),new_vectors.astype(np.float32)
        path=ROOT/'output/tagnet/ct_context_patterns'/row['output_file'];assert digest(path)==row['output_sha256']
        with np.load(path,allow_pickle=False) as prototype:
            np.testing.assert_array_equal(prototype['source_indices'],tr)
            args=(prototype['centers'],prototype['source_labels'],prototype['source_radii'],parameters['clustering']['minimum_cluster_support'])
            check,check_distance,check_accept=assign_patterns(old_vectors,*args)
            np.testing.assert_array_equal(check,prototype['query_labels'])
            np.testing.assert_array_equal(check_accept,prototype['query_assigned'])
            np.testing.assert_allclose(check_distance,prototype['query_distances'],atol=2e-5,rtol=0)
            labels=np.full(len(q),-1,dtype=np.int32);accepted=np.zeros(len(q),dtype=bool);distance=np.full(len(q),np.inf)
            labels[known],distance[known],accepted[known]=assign_patterns(new_vectors[known],*args)
        name=row['output_file'];np.savez_compressed(out/name,query_indices=q,cluster=labels,accepted=accepted,
                                                   context_known=known,centroid_distance=distance)
        saved[name]=digest(out/name);assignments[(map_name,variant,seed)]=(labels,accepted)
        models.append({'map':map_name,'variant':variant,'seed':seed,'source_K':row['k'],'queries':len(q),
                       'context_known_queries':int(known.sum()),'accepted':int(accepted.sum())})
    summary={};comparisons=[]
    for variant in sorted({r['variant'] for r in models}):
        rows=[r for r in models if r['variant']==variant];values=[];context_agreement=[]
        for map_name in sorted({r['map'] for r in rows}):
            available=[r['seed'] for r in rows if r['map']==map_name and r['seed'] is not None]
            for first,second in combinations(available,2):
                a,am=assignments[(map_name,variant,first)];b,bm=assignments[(map_name,variant,second)];keep=am&bm
                eligible=keep.sum()>=2 and len(set(a[keep]))>=2 and len(set(b[keep]))>=2
                score=float(adjusted_rand_score(a[keep],b[keep])) if eligible else None
                if score is not None:values.append(score)
                comparisons.append({'map':map_name,'variant':variant,'seeds':[first,second],
                                    'common_accepted':int(keep.sum()),'ARI':score})
            if variant.endswith('+context'):
                b,bm=assignments[(map_name,'context_only',None)]
                for seed in available or [None]:
                    a,am=assignments[(map_name,variant,seed)];keep=am&bm
                    if keep.sum()>=2 and len(set(a[keep]))>=2 and len(set(b[keep]))>=2:
                        context_agreement.append(float(adjusted_rand_score(a[keep],b[keep])))
        queries=sum(r['queries'] for r in rows);known=sum(r['context_known_queries'] for r in rows);accepted=sum(r['accepted'] for r in rows)
        summary[variant]={'coverage_all_queries':accepted/queries,'coverage_known_queries':accepted/known if known else None,
            'queries':queries,'known_queries':known,'accepted':accepted,'mean_seed_ARI':float(np.mean(values)) if values else None,
            'eligible_seed_pairs':len(values),'mean_ARI_vs_context_only':float(np.mean(context_agreement)) if context_agreement else None,
            'context_only_comparisons':len(context_agreement)}
    report={'status':'complete_frozen_context_prototype_transfer','protocol_sha256':digest(protocol),'models':models,
        'seed_comparisons':comparisons,'summary':summary,'artifacts_sha256':saved,'elapsed_seconds':time.monotonic()-started,
        'peak_RAM_MiB':psutil.Process().memory_info().peak_wset/2**20,'limits':[
            'Unknown utility is not zero and is not silently dropped from the denominator.',
            'The source joint prototypes remain resource-dominated; stability is not tactical validity.',
            'No source clustering, encoder, threshold or context weight was refitted on these queries.']}
    write(out/'report.json',report)


if __name__=='__main__':main()
