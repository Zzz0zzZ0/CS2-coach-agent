"""Plot audited development results. Requires optional matplotlib==3.10.6, not a service dependency."""
import csv
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'docs/portfolio'
METHODS=[('bm25_unicode','Unicode BM25'),('bm25_subword','Subword BM25'),('dense_minilm','MiniLM dense'),('dense_jina','Jina bilingual dense'),('rrf_subword_jina','Subword + Jina RRF')]
SOURCES=[('Historical development','12 positive semantic groups','language_baselines_v2_report.json'),
         ('Isolated observed-series pilot','15 positive semantic groups · 2 series','isolated_relation_v1_text_report.json')]
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'svg.fonttype':'none','svg.hashsalt':'cs2-benchmark-v1'})
fig,axes=plt.subplots(1,2,figsize=(12,5.6),sharex=True,sharey=True)
fig.patch.set_facecolor('#f8fafc');rows=[];manifest={}
for ax,(title,subtitle,filename) in zip(axes,SOURCES):
    path=ROOT/'datasets/evaluation'/filename
    data=json.loads(path.read_text());manifest[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    summary={r['method']:r['metrics'] for r in data['summary'] if r['configuration']=='raw' and r['language']=='paired_macro'}
    values=[summary[m]['ndcg_at_k']['mean'] for m,_ in METHODS]
    ax.set_facecolor('#f8fafc')
    bars=ax.barh(range(len(METHODS)),values,color=['#64748b','#64748b','#2563eb','#0f766e','#a16207'],height=.58)
    for bar,value in zip(bars,values):ax.text(value+.017,bar.get_y()+bar.get_height()/2,f'{value:.3f}',va='center',fontsize=11,fontweight='bold')
    ax.set_title(title+'\n'+subtitle,loc='left',fontsize=11,pad=16)
    ax.set_yticks(range(len(METHODS)),[label for _,label in METHODS]);ax.set_xlim(0,1)
    ax.set_xticks([0,.25,.5,.75,1]);ax.set_xlabel('Paired English–Chinese mean nDCG@5')
    ax.grid(axis='x',color='#cbd5e1',alpha=.6);ax.set_axisbelow(True);ax.tick_params(axis='y',length=0)
    for spine in ax.spines.values():spine.set_visible(False)
    for m,label in METHODS:rows.append({'dataset':title,'method':label,'ndcg_at_5':summary[m]['ndcg_at_k']['mean'],'recall_at_5':summary[m]['recall_at_k']['mean'],'unanswerable_false_retrieval':summary[m]['false_retrieval']['mean']})
axes[0].invert_yaxis()
fig.suptitle('CS2 retrieval: gains depend on the sample',x=.03,y=.975,ha='left',fontsize=19,fontweight='bold',color='#0f172a')
fig.text(.03,.075,'Same raw facts and explicit candidate scopes within each experiment. Raw questions; no glossary expansion.',fontsize=9,color='#475569')
fig.text(.03,.039,'AI-assisted source labels; observed development data. All plotted top-k methods retrieve on every unanswerable query.',fontsize=9,color='#475569')
fig.subplots_adjust(left=.20,right=.965,top=.79,bottom=.22,wspace=.16)
OUT.mkdir(parents=True,exist_ok=True)
for suffix in ('svg','png'):fig.savefig(OUT/f'benchmark-results.{suffix}',dpi=180,metadata={'Creator':'CS2 Coach Agent benchmark plotting script'} if suffix=='svg' else None)
with (OUT/'benchmark-results.csv').open('w') as out:
    writer=csv.DictWriter(out,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
(OUT/'benchmark-figure-manifest.json').write_text(json.dumps({'inputs_sha256':manifest,'plot_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'matplotlib':matplotlib.__version__,'interpretation':'Development pipeline comparison; model and actual chunk capacity differ. Not independent generalization or expert coaching quality.'},indent=2)+'\n')
