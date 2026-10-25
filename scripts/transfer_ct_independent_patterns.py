"""Apply frozen source centroids/libraries to new embeddings; all rankings are unjudged."""

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
from app.services.ct_retrieval_service import nearest_candidates


def assign_patterns(queries, centers, labels, radii, minimum_support):
    queries,centers=np.asarray(queries),np.asarray(centers)
    assert queries.ndim==centers.ndim==2 and queries.shape[1]==centers.shape[1]
    assert np.isfinite(queries).all() and np.isfinite(centers).all()
    distances=np.linalg.norm(queries[:,None]-centers[None],axis=-1)
    assigned=distances.argmin(1);nearest=distances[np.arange(len(queries)),assigned]
    counts=np.bincount(labels,minlength=len(centers))
    accepted=(nearest<=radii[assigned]) & (counts[assigned]>=minimum_support)
    return assigned,nearest,accepted


def main():
    import psutil
    started=time.monotonic()
    protocol_path=ROOT/'datasets/selections/ct_independent_pattern_transfer.json'
    cfg=json.loads(protocol_path.read_text(encoding='utf-8'))
    for name,expected in cfg['input_sha256'].items():assert digest(ROOT/name)==expected,name
    source_report=json.loads((ROOT/'datasets/evaluation/ct_deployment_pattern_report.json').read_text(encoding='utf-8'))
    old_cfg=json.loads((ROOT/'datasets/selections/ct_deployment_pattern_analysis.json').read_text(encoding='utf-8'))
    reconstruction=json.loads((ROOT/'datasets/evaluation/ct_independent_confirmation_report.json').read_text(encoding='utf-8'))
    old_index=json.loads((ROOT/'output/tagnet/ct_deployment_inputs_p1_v03/sample_index.json').read_text(encoding='utf-8'))
    original=json.loads((ROOT/'datasets/selections/ct_independent_confirmation.json').read_text(encoding='utf-8'))
    out=ROOT/'output/tagnet/ct_independent_pattern_transfer';assert not out.exists();out.mkdir()
    models=[];assignments={};indices={};outputs={};total_rankings=0
    for row in source_report['patterns']:
        if not row['fold'].startswith('G4__'):continue
        assert row['status']=='fitted'
        fold,condition,seed=row['fold'],row['condition'],row['seed'];map_name=fold.removeprefix('G4__')
        name=f'{fold}__{condition}__{seed}.npz';path=ROOT/'output/tagnet/ct_deployment_patterns'/name
        assert digest(path)==source_report['output_sha256'][name]
        prefix=ROOT/f'output/tagnet/ct_reconstruction_matrix/{fold}/{condition}_{seed}'
        library_path=prefix.with_name(prefix.name+'_library.npz')
        assert digest(library_path)==original['source_library_sha256'][library_path.relative_to(ROOT).as_posix()]
        query_path=ROOT/f'output/tagnet/ct_independent_confirmation/{map_name}_{condition}_{seed}.npz'
        assert digest(query_path)==reconstruction['artifacts_sha256'][query_path.name]
        index=json.loads((ROOT/f'output/tagnet/ct_independent_confirmation/{map_name}_index.json').read_text(encoding='utf-8'))
        indices[map_name]=index
        with (np.load(path,allow_pickle=False) as pattern, np.load(library_path,allow_pickle=False) as library,
              np.load(query_path,allow_pickle=False) as query):
            train=library['train_indices'];assert np.array_equal(train,pattern['train_indices'])
            assert all(old_index[i]['map']!=map_name for i in train)
            assert not {r['series'] for r in index}&{old_index[i]['series'] for i in train}
            args=(pattern['centers'],pattern['source_labels'],pattern['source_radii'],old_cfg['clustering']['minimum_cluster_support'])
            assert len(query['embeddings'])==len(index)
            old_query_path=prefix.with_name(prefix.name+'_evaluation.npz')
            old_artifacts={k.replace('\\','/'):v for k,v in source_report['artifact_sha256'].items()}
            assert digest(old_query_path)==old_artifacts[old_query_path.relative_to(ROOT).as_posix()]
            with np.load(old_query_path,allow_pickle=False) as old_query:
                legacy,legacy_distance,legacy_accepted=assign_patterns(old_query['embeddings'],*args)
            np.testing.assert_array_equal(legacy,pattern['query_labels'])
            np.testing.assert_array_equal(legacy_accepted,pattern['query_assigned'])
            np.testing.assert_allclose(legacy_distance,pattern['query_distances'],atol=2e-5,rtol=0)
            labels,distance,accepted=assign_patterns(query['embeddings'],*args)
            ranking,distances=nearest_candidates(query['embeddings'],library['embeddings'],k=5)
            candidates=train[ranking]
            assert candidates.shape==(len(index),5)
            np.savez_compressed(out/name,cluster=labels,accepted=accepted,centroid_distance=distance,
                candidate_indices=candidates,candidate_distances=np.take_along_axis(distances,ranking,axis=1))
        outputs[name]=digest(out/name);assignments[(map_name,condition,seed)]=(labels,accepted)
        total_rankings+=len(index)
        series=[]
        for sid in sorted({r['series'] for r in index}):
            keep=np.asarray([r['series']==sid for r in index]);series.append({'series':sid,'windows':int(keep.sum()),'accepted':int(accepted[keep].sum())})
        models.append({'map':map_name,'condition':condition,'seed':seed,'source_K':row['selected_k'],
            'query_windows':len(index),'accepted':int(accepted.sum()),'series':series})
    stability=[]
    for name,index in indices.items():
        for condition in sorted({r['condition'] for r in models}):
            for first,second in combinations((0,1,42),2):
                a,am=assignments[(name,condition,first)];b,bm=assignments[(name,condition,second)];keep=am&bm
                eligible=keep.sum()>=2 and len(set(a[keep]))>=2 and len(set(b[keep]))>=2
                stability.append({'map':name,'condition':condition,'seeds':[first,second],'common_accepted':int(keep.sum()),
                    'ARI':float(adjusted_rand_score(a[keep],b[keep])) if eligible else None,
                    'missing_reason':None if eligible else 'insufficient_common_or_multiple_clusters'})
    summary={}
    for condition in sorted({r['condition'] for r in models}):
        rows=[r for r in models if r['condition']==condition];values=[r['ARI'] for r in stability if r['condition']==condition and r['ARI'] is not None]
        series_fractions=[]
        for sid in sorted({x['series'] for r in rows for x in r['series']}):
            series_fractions.append(float(np.mean([x['accepted']/x['windows'] for r in rows for x in r['series'] if x['series']==sid])))
        summary[condition]={'pooled_query_seed_coverage':sum(r['accepted'] for r in rows)/sum(r['query_windows'] for r in rows),
            'equal_series_mean_coverage':float(np.mean(series_fractions)),'mean_eligible_seed_ARI':float(np.mean(values)) if values else None,
            'eligible_seed_pairs':len(values),'planned_seed_pairs':18}
    report={'status':'completed_frozen_source_pattern_and_neural_ranking_transfer','protocol_sha256':digest(protocol_path),
        'models':models,'seed_stability':stability,'summary':summary,'unjudged_neural_rankings':total_rankings,
        'candidate_slots':total_rankings*5,'same_map_library_supported':False,'artifacts_sha256':outputs,
        'elapsed_seconds':time.monotonic()-started,'peak_RAM_MiB':psutil.Process().memory_info().peak_wset/2**20,
        'limits':['No new fit, K selection, radius calibration, or relevance labels.',
            'Coverage and ARI are conditional descriptive diagnostics, not tactical correctness.',
            'Source labels are numeric and do not define fixed geographic duties.',
            'This neural-only transfer does not replace direct/statistical/context retrieval controls.']}
    write(out/'report.json',report)


if __name__=='__main__':main()
