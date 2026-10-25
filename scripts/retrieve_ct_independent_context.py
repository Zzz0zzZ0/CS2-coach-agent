"""Transfer all existing context policies and same-library controls without relevance labels."""

import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from itertools import permutations
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.acquire_ct_independent_demos import digest
from scripts.confirm_ct_generalization import write
from scripts.evaluate_ct_reconstruction import statistics_sequence, observation_vector
from scripts.evaluate_ct_context_retrieval import rank_arrays
from app.services.ct_retrieval_service import nearest_candidates
from app.services.ct_context_retrieval_service import context_groups, context_embedding, normalize_source, squared_distance


def cross_observation_distances(queries, source):
    base=observation_vector(queries,range(5));norm=(base*base).sum(1)
    result=np.full((len(base),len(source['nodes'])),np.inf)
    for p in permutations(range(5)):
        other=observation_vector(source,p)
        distance=norm[:,None]+(other*other).sum(1)[None]-2*base@other.T
        np.minimum(result,distance.clip(0),out=result)
    return result


def load_transfer_inputs():
    keys=('nodes','edges','node_mask','node_feature_mask','pair_mask')
    root=ROOT/'output/tagnet/ct_independent_inputs'
    qa=json.loads((root/'report.json').read_text(encoding='utf-8'))
    assert qa['status']=='complete_inputs_pending_inference' and not qa['unresolved_team_identities']
    old_index=json.loads((ROOT/'output/tagnet/ct_deployment_inputs_p1_v03/sample_index.json').read_text(encoding='utf-8'))
    with np.load(ROOT/'output/tagnet/ct_deployment_inputs_p1_v03/features.npz',allow_pickle=False) as archive:
        old_data={k:archive[k].copy() for k in keys}
    pieces=[];new_index=[]
    for row in qa['demos']:
        folder=root/row['match_id']
        for name in ('features.npz','sample_index.json'):assert digest(folder/name)==row['output_sha256'][name]
        with np.load(folder/'features.npz',allow_pickle=False) as archive:pieces.append({k:archive[k].copy() for k in keys})
        new_index.extend(json.loads((folder/'sample_index.json').read_text(encoding='utf-8')))
    new_data={k:np.concatenate([p[k] for p in pieces]) for k in keys}
    old_context=json.loads((ROOT/'output/tagnet/ct_context_availability_v2/context.json').read_text(encoding='utf-8'))
    new_context=json.loads((ROOT/'output/tagnet/ct_independent_context_v2/context.json').read_text(encoding='utf-8'))
    assert [r['id'] for r in old_context]==[r['id'] for r in old_index]
    assert [r['id'] for r in new_context]==[r['id'] for r in new_index]
    folds={r['name']:r for r in json.loads((ROOT/'output/tagnet/ct_grouped_confirmation_v7/folds.json').read_text(encoding='utf-8')) if r['task']=='G4'}
    return old_index,new_index,old_data,new_data,context_groups(old_context),context_groups(new_context),folds


def main():
    import psutil
    protocol_path=ROOT/'datasets/selections/ct_independent_retrieval_transfer_v2.json'
    cfg=json.loads(protocol_path.read_text(encoding='utf-8'))
    for name,expected in cfg['input_sha256'].items():assert digest(ROOT/name)==expected,name
    original=json.loads((ROOT/'datasets/selections/ct_independent_confirmation.json').read_text(encoding='utf-8'))
    source_cfg=json.loads((ROOT/'datasets/selections/ct_context_retrieval_matrix.json').read_text(encoding='utf-8'))
    policies=source_cfg['policies']
    prediction=json.loads((ROOT/'datasets/evaluation/ct_independent_confirmation_report.json').read_text(encoding='utf-8'))
    old_index,new_index,old_data,new_data,old_context,new_context,folds=load_transfer_inputs()
    index=old_index+new_index
    with np.load(ROOT/'output/tagnet/ct_reconstruction_analysis/observation_distances.npz',allow_pickle=False) as archive:source_direct=archive['distances']
    started=time.monotonic()
    parity=cross_observation_distances({k:v[:4] for k,v in old_data.items()},old_data)
    np.testing.assert_allclose(parity,source_direct[:4],atol=1e-8,rtol=0)
    direct=cross_observation_distances(new_data,old_data)
    source_stats=statistics_sequence(old_data);query_stats=statistics_sequence(new_data)
    out=ROOT/'output/tagnet/ct_independent_retrieval_v2';assert not out.exists();out.mkdir()
    np.savez_compressed(out/'observation_distances.npz',distances=direct)
    entries=[];artifacts={'observation_distances.npz':digest(out/'observation_distances.npz')}
    for fold_name,fold in sorted(folds.items()):
        map_name=fold_name.removeprefix('G4__');tr=np.asarray(fold['train'])
        q=np.asarray([i for i,r in enumerate(new_index) if r['map']==map_name]);queries=q+len(old_index)
        assert [new_index[i] for i in q]==json.loads((ROOT/f'output/tagnet/ct_independent_confirmation/{map_name}_index.json').read_text(encoding='utf-8'))
        assert all(old_index[i]['map']!=map_name for i in tr)
        contexts={tuple(p['groups']):context_embedding({k:v[tr] for k,v in old_context.items()},
                  {k:v[q] for k,v in new_context.items()},tuple(p['groups'])) for p in policies.values() if p['groups']}
        mean,std=source_stats[tr].mean(0),source_stats[tr].std(0).clip(1e-6)
        methods=[]
        for condition in source_cfg['conditions']:
            for seed in original['seeds']:
                path=ROOT/f'output/tagnet/ct_reconstruction_matrix/{fold_name}/{condition}_{seed}_library.npz'
                assert digest(path)==original['source_library_sha256'][path.relative_to(ROOT).as_posix()]
                target=ROOT/f'output/tagnet/ct_independent_confirmation/{map_name}_{condition}_{seed}.npz'
                assert digest(target)==prediction['artifacts_sha256'][target.name]
                with np.load(path,allow_pickle=False) as library,np.load(target,allow_pickle=False) as query:
                    np.testing.assert_array_equal(tr,library['train_indices'])
                    methods.append((condition,seed,library['embeddings'].copy(),query['embeddings'].copy()))
        methods.extend([('statistics_sequence',None,(source_stats[tr]-mean)/std,(query_stats[q]-mean)/std),
                        ('full_input_matching',None,None,None)])
        for method,seed,source_z,query_z in methods:
            assert psutil.virtual_memory().available>1536*2**20
            if method=='full_input_matching':
                pair=source_direct[np.ix_(tr,tr)];scale=float((pair.sum()-pair.trace())/(len(tr)*(len(tr)-1)))
                raw=direct[np.ix_(q,tr)];scale=scale if scale>1e-12 else 1.0
            else:
                _,_,normalized=normalize_source(source_z,query_z);scale=normalized['scale']
                raw=nearest_candidates(query_z,source_z)[1]
            base=raw/scale;rankings=[];values=[];metrics={}
            for policy_name,policy in policies.items():
                groups=tuple(policy['groups']);weight=policy['weight'];supported=np.ones(len(q),dtype=bool)
                if not groups:distance=base
                else:
                    context=contexts[groups];supported=context['query_supported'];context_distance=np.full(base.shape,np.inf)
                    if context['source_supported']:context_distance[supported]=squared_distance(context['queries'][supported],context['source'])
                    distance=(1-weight)*base+weight*context_distance
                rank,rank_distance=rank_arrays(distance,queries,tr,index,5)
                if not groups:
                    baseline=rank
                    if seed is not None:
                        previous=ROOT/f'output/tagnet/ct_independent_pattern_transfer/{fold_name}__{method}__{seed}.npz'
                        with np.load(previous,allow_pickle=False) as old_ranking:
                            np.testing.assert_array_equal(rank[:,0],old_ranking['candidate_indices'])
                valid=(rank[:,:,0]>=0)&(baseline[:,:,0]>=0)
                metrics[policy_name]={'supported_queries':int(supported.sum()),'eligible_top1_by_stratum':valid.sum(0).tolist(),
                    'top1_changed_by_stratum':((rank[:,:,0]!=baseline[:,:,0])&valid).sum(0).tolist()}
                rankings.append(rank);values.append(rank_distance)
            name=f'{fold_name}__{method}_{seed}.npz'
            np.savez_compressed(out/name,policies=np.asarray(list(policies)),query_indices=q,source_indices=tr,
                                candidate_indices=np.stack(rankings),distances=np.stack(values))
            artifacts[name]=digest(out/name)
            entries.append({'map':map_name,'method':method,'seed':seed,'query_windows':len(q),'policies':metrics,'file':name})
        own=contexts[tuple(policies['own_context_050']['groups'])]
        distance=np.full((len(q),len(tr)),np.inf);valid=own['query_supported']
        if own['source_supported']:distance[valid]=squared_distance(own['queries'][valid],own['source'])
        rank,rank_distance=rank_arrays(distance,queries,tr,index,5)
        name=f'{fold_name}__context_only_None.npz'
        np.savez_compressed(out/name,policies=np.asarray(['context_only']),query_indices=q,source_indices=tr,
                            candidate_indices=rank[None],distances=rank_distance[None]);artifacts[name]=digest(out/name)
        entries.append({'map':map_name,'method':'context_only','seed':None,'query_windows':len(q),'supported_queries':int(valid.sum()),'file':name})
        print(json.dumps({'completed_maps':sum(e['method']=='context_only' for e in entries),'method_entries':len(entries)}),flush=True)
    summary={}
    for policy in policies:
        rows=[e['policies'][policy] for e in entries if 'policies' in e]
        eligible=sum(r['eligible_top1_by_stratum'][0] for r in rows);changed=sum(r['top1_changed_by_stratum'][0] for r in rows)
        summary[policy]={'supported_query_method_records':sum(r['supported_queries'] for r in rows),
            'eligible_top1_records':eligible,'top1_changed_records':changed,'fraction_top1_changed':changed/eligible if eligible else None}
    report={'status':'complete_frozen_context_policy_transfer','protocol_sha256':digest(protocol_path),'entries':entries,
        'summary':summary,'artifacts_sha256':artifacts,'elapsed_seconds':time.monotonic()-started,
        'peak_RAM_MiB':psutil.Process().memory_info().peak_wset/2**20,
        'limits':['All rankings unjudged; turnover is not a relevance improvement.','Missing utility stays unsupported, not zero; no target-side fitting or policy selection.',
                  'Same-map libraries are empty by G4 design; source and other-map strata coincide.']}
    write(out/'report.json',report)


if __name__=='__main__':main()
