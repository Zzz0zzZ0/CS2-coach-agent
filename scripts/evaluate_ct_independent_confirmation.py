"""Frozen-checkpoint technical confirmation; reconstruction is not tactical relevance."""

import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[key]='1'
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.acquire_ct_independent_demos import digest
from scripts.confirm_ct_generalization import write


def confirmation_interval(rows):
    from scipy.stats import t
    assert len(rows)==12 and len({r['series'] for r in rows})==12
    maps=sorted({r['map'] for r in rows});assert len(maps)==6
    groups=[]
    for name in maps:
        selected=[r for r in rows if r['map']==name];assert len(selected)==2
        losses=np.asarray([[r['graph_gru'],r['mlp_gru']] for r in selected],dtype=float)
        assert np.isfinite(losses).all() and (losses>0).all()
        groups.append(np.log(losses[:,0]/losses[:,1]))
    means=np.asarray([g.mean() for g in groups]);variances=np.asarray([g.var(ddof=1) for g in groups])
    estimate=float(means.mean());df=6
    se=float(np.sqrt(variances.sum()/72))
    pooled_half=float(t.ppf(.975,df)*se)
    contributions=variances/2
    welch_df=float(contributions.sum()**2/(contributions**2).sum()) if contributions.sum()>0 else None
    welch_half=float(t.ppf(.975,welch_df)*se) if welch_df else 0.0
    return {'log_ratio':estimate,'geometric_loss_ratio':float(np.exp(estimate)),'SE':se,'pooled_df':df,
        'pooled_log_CI95':[estimate-pooled_half,estimate+pooled_half],
        'pooled_ratio_CI95':np.exp([estimate-pooled_half,estimate+pooled_half]).tolist(),
        'Welch_Satterthwaite_df':welch_df,'heteroscedastic_log_CI95':[estimate-welch_half,estimate+welch_half],
        'degenerate_observed_residual_variance':bool(se==0),'per_map':[
            {'map':name,'series_log_ratios':g.tolist(),'mean_log_ratio':float(g.mean()),'SD':float(g.std(ddof=1))}
            for name,g in zip(maps,groups)],
        'assumptions':'Independent normal series residuals, six fixed map means; pooled interval assumes common variance. Shared teams/events remain a limitation. No diagnostic screen proves these assumptions.'}


def main():
    import psutil
    import torch
    from scripts.run_ct_reconstruction import ReconstructionModel, reconstruction_loss, validate_inputs, validate_fold, CONDITIONS

    protocol_path=ROOT/'datasets/selections/ct_independent_confirmation.json'
    protocol=json.loads(protocol_path.read_text(encoding='utf-8'))
    execution_path=ROOT/'datasets/selections/ct_independent_analysis.json'
    execution=json.loads(execution_path.read_text(encoding='utf-8'))
    assert digest(Path(__file__))==execution['evaluator_sha256']
    assert digest(protocol_path)==execution['confirmation_protocol_sha256']
    for name,expected in protocol['inputs_sha256'].items():assert digest(ROOT/name)==expected,name
    input_root=ROOT/'output/tagnet/ct_independent_inputs'
    qa=json.loads((input_root/'report.json').read_text(encoding='utf-8'))
    assert qa['status']=='complete_inputs_pending_inference' and not qa['unresolved_team_identities']
    lexical_mismatches={r['match_id'] for r in qa['demos'] if not r['teams_match']}
    if lexical_mismatches:
        proof_path=input_root/'identity_checks.json'
        assert digest(proof_path)==qa['identity_checks_sha256']
        proof=json.loads(proof_path.read_text(encoding='utf-8'))
        assert {r['match_id'] for r in proof['proofs']}==lexical_mismatches
        assert proof['script_sha256']==execution['identity_verifier_sha256']
        assert digest(ROOT/'scripts/verify_ct_independent_identities.py')==execution['identity_verifier_sha256']
    for name,expected in qa['source_sha256'].items():assert digest(ROOT/name)==expected,name
    old_index=json.loads((ROOT/'output/tagnet/ct_deployment_inputs_p1_v03/sample_index.json').read_text(encoding='utf-8'))
    folds=json.loads((ROOT/'output/tagnet/ct_grouped_confirmation_v7/folds.json').read_text(encoding='utf-8'))
    out=ROOT/'output/tagnet/ct_independent_confirmation';assert not out.exists();out.mkdir()
    assert psutil.virtual_memory().available>2*2**30
    assert torch.cuda.is_available() and torch.cuda.mem_get_info()[0]>1024*2**20
    torch.set_num_threads(1);torch.cuda.set_per_process_memory_fraction(.2)
    torch.backends.fp32_precision='ieee';torch.backends.cudnn.fp32_precision='ieee'
    torch.backends.cuda.matmul.fp32_precision='ieee';torch.backends.cudnn.rnn.fp32_precision='tf32'
    started=time.monotonic();results=[];artifacts={}
    for map_name in sorted({r['map'] for r in qa['demos']}):
        fold=next(r for r in folds if r['name']=='G4__'+map_name);validate_fold(fold,old_index)
        arrays=[];index=[]
        for receipt in qa['demos']:
            if receipt['map']!=map_name:continue
            folder=input_root/receipt['match_id']
            for name,expected in receipt['output_sha256'].items():assert digest(folder/name)==expected,name
            with np.load(folder/'features.npz',allow_pickle=False) as data:arrays.append({k:data[k].copy() for k in data.files})
            index.extend(json.loads((folder/'sample_index.json').read_text(encoding='utf-8')))
        data={key:np.concatenate([r[key] for r in arrays]) for key in arrays[0]};validate_inputs(data)
        assert not {r['series'] for r in index}&{r['series'] for r in old_index}
        write(out/(map_name+'_index.json'),index)
        for condition in CONDITIONS:
            for seed in protocol['seeds']:
                checkpoint=ROOT/f'output/tagnet/ct_reconstruction_matrix/G4__{map_name}/{condition}_{seed}.pt'
                assert digest(checkpoint)==protocol['checkpoint_sha256'][checkpoint.relative_to(ROOT).as_posix()]
                state=torch.load(checkpoint,map_location='cpu',weights_only=True)
                assert state['condition']==condition and state['feature_version']=='ct-deployment-input-v0.3'
                model=ReconstructionModel(condition).cuda().eval();model.load_state_dict(state['state_dict'])
                losses=[];components=[];embeddings=[]
                with torch.no_grad():
                    for start in range(0,len(index),16):
                        batch={k:torch.from_numpy(v[start:start+16]).cuda() for k,v in data.items()}
                        prediction,z=model(batch);loss,detail=reconstruction_loss(prediction,batch,model.permutations)
                        losses.append(loss.cpu().numpy());components.append(detail.cpu().numpy());embeddings.append(z.cpu().numpy())
                loss=np.concatenate(losses);detail=np.concatenate(components);z=np.concatenate(embeddings)
                assert np.isfinite(loss).all() and np.isfinite(z).all()
                path=out/f'{map_name}_{condition}_{seed}.npz'
                np.savez_compressed(path,loss=loss,components=detail,embeddings=z);artifacts[path.name]=digest(path)
                for series in sorted({r['series'] for r in index}):
                    selected=np.asarray([r['series']==series for r in index])
                    results.append({'series':series,'map':map_name,'condition':condition,'seed':seed,
                        'windows':int(selected.sum()),'loss':float(loss[selected].mean()),'components':detail[selected].mean(0).tolist()})
                del model,batch,prediction,z;torch.cuda.empty_cache()
        print(json.dumps({'map':map_name,'query_windows':len(index),'model_fits_completed':len(artifacts)}),flush=True)
    series_rows=[]
    for series in sorted({r['series'] for r in results}):
        rows=[r for r in results if r['series']==series]
        series_rows.append({'series':series,'map':rows[0]['map'],'windows':rows[0]['windows'],**{
            name:float(np.mean([r['loss'] for r in rows if r['condition']==name])) for name in CONDITIONS}})
    report={'status':'completed_inference_pending_statistics','protocol_sha256':digest(protocol_path),
        'execution_protocol_sha256':digest(execution_path),'input_QA_sha256':digest(input_root/'report.json'),
        'per_seed_series':results,'per_series':series_rows,
        'artifacts_sha256':artifacts,'elapsed_seconds':time.monotonic()-started,
        'peak_RAM_MiB':psutil.Process().memory_info().peak_wset/2**20,
        'peak_allocated_VRAM_MiB':torch.cuda.max_memory_allocated()/2**20,
        'limits':['Reconstruction is a technical proxy, not new tactical relevance or coach efficacy.',
                  'No new model training, model choice, context tuning or human labels.',
                  'Twelve series across three events share teams; normality and independence are assumptions, not established by a numerical screen.']}
    write(out/'report.json',report)


def summarize():
    path=ROOT/'output/tagnet/ct_independent_confirmation/report.json'
    report=json.loads(path.read_text(encoding='utf-8'))
    assert report['status']=='completed_inference_pending_statistics'
    execution=ROOT/'datasets/selections/ct_independent_analysis.json'
    assert report['execution_protocol_sha256']==digest(execution)
    assert json.loads(execution.read_text(encoding='utf-8'))['evaluator_sha256']==digest(Path(__file__))
    report['primary']=confirmation_interval(report['per_series']);report['status']='completed_technical_confirmation'
    write(path,report)


if __name__=='__main__':
    if sys.argv[1:]==['--summarize']:summarize()
    else:
        assert not sys.argv[1:]
        main()
