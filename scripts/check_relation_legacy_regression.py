"""Run unchanged development/observed-holdout checks with a local frozen embedding model."""
import argparse
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
from fastembed import TextEmbedding
from langchain_community.embeddings import FastEmbedEmbeddings
from app.core import providers
from app.services.graph_rag_service import GraphRAGClient
from scripts.evaluate_v1 import evaluate, _evaluate_retrieval_modes
from scripts.evaluate_fair_retrieval import MODEL,digest,write_json


async def run(model_dir,output_dir):
    if not providers.settings.EMBEDDING_BACKEND=='fastembed' or providers.settings.LLM_AUXILIARY_CALLS_ENABLED:
        raise ValueError('Local FastEmbed with auxiliary model calls disabled is required')
    if providers.settings.MILVUS_URI not in ('http://localhost:19530','http://127.0.0.1:19530'):
        raise ValueError('This regression only uses the local Milvus store')
    if output_dir.exists(): raise ValueError('Choose a new output directory')
    frozen=json.loads(Path('datasets/evaluation/fair_calibration_v1_protocol.json').read_text())
    if {str(p.relative_to(model_dir)):digest(p) for p in sorted(model_dir.rglob('*')) if p.is_file()}!=frozen['model_files_sha256']:
        raise ValueError('Local model does not match frozen baseline')
    model=TextEmbedding(MODEL,local_files_only=True,specific_model_path=str(model_dir),threads=2,max_length=512)
    # Reuse the production query_embed adapter, bypassing only remote model discovery.
    providers._embeddings_instance=FastEmbedEmbeddings.model_construct(model=model,model_name=MODEL,max_length=512,threads=2)
    graph_path=Path('data/graph/cs2_graph.sqlite'); before=digest(graph_path)
    dev=await evaluate(graph_path,Path('datasets/evaluation/retrieval_queries_v2.json'))
    write_json(output_dir/'development.json',dev)
    modes,available=await _evaluate_retrieval_modes(GraphRAGClient(graph_path),Path('datasets/evaluation/retrieval_queries_holdout_v1.json'))
    write_json(output_dir/'holdout.json',{'vector_available':available,'modes':modes})
    counts=lambda x:{k:x[k]['queries_passed'] for k in ('vector_only','graph_only','hybrid')}
    summary={'created_at':datetime.now(timezone.utc).isoformat(),'remote_model_calls':0,'structured_contracts':dev['summary'],
        'development':counts({k:v['retrieval'] for k,v in dev['benchmark']['modes'].items()}),'holdout':counts(modes),
        'graph_unchanged':before==digest(graph_path),'graph_sha256':before,
        'model_files_sha256':frozen['model_files_sha256'],
        'implementation_sha256':digest(__file__),
        'interpretation':'Unchanged 50-query development and previously observed 30-query holdout. Existing vector failures remain regression limitations.'}
    write_json(output_dir/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model-dir',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    a=p.parse_args();s=asyncio.run(run(a.model_dir,a.output_dir))
    raise SystemExit(0 if s['graph_unchanged'] and s['structured_contracts']['failed']==0 and
        s['development']=={'vector_only':50,'graph_only':50,'hybrid':50} and
        s['holdout']=={'vector_only':28,'graph_only':30,'hybrid':30} else 1)
