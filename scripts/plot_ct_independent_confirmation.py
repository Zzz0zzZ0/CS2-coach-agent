"""All external-series ratios and the two prespecified model-based intervals."""

import csv
import json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.acquire_ct_independent_demos import digest
from scripts.confirm_ct_generalization import write


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    source=ROOT/'datasets/evaluation/ct_independent_confirmation_report.json'
    report=json.loads(source.read_text(encoding='utf-8'))
    acquisition=json.loads((ROOT/'output/tagnet/ct_independent_demos/acquisition.json').read_text(encoding='utf-8'))
    events={r['match_id']:r['event_id'] for r in acquisition['files']}
    markers={8263:'o',8244:'s',8932:'^'}
    labels={8263:'CS Asia, May',8244:'EPL 24, October',8932:'Thunderpick, October'}
    maps=sorted({r['map'] for r in report['per_series']});assert len(maps)==6 and len(report['per_series'])==12
    out=ROOT/'docs/paper/manuscript/figures'
    stem=out/'independent_confirmation'
    assert not any(stem.with_suffix('.'+ext).exists() for ext in ('pdf','svg','png'))
    table=[]
    with plt.rc_context({'font.family':'DejaVu Sans','font.size':9,'pdf.fonttype':42,'ps.fonttype':42,
                         'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False}):
        fig,ax=plt.subplots(figsize=(181.9/25.4,108/25.4),layout='constrained')
        for y,name in enumerate(maps):
            rows=sorted([r for r in report['per_series'] if r['map']==name],key=lambda r:r['series'])
            assert len(rows)==2
            for offset,row in zip((-.17,.17),rows):
                ratio=row['graph_gru']/row['mlp_gru'];assert np.isfinite(ratio) and ratio>0
                event=events[row['series']]
                ax.scatter(ratio,y+offset,marker=markers[event],s=26,facecolor='white',edgecolor='black',linewidth=.9,zorder=3)
                ax.annotate(row['series'],(ratio,y+offset),xytext=(5,0),textcoords='offset points',fontsize=9,va='center')
                table.append({**row,'event_id':event,'graph_MLP_ratio':ratio,'log_ratio':float(np.log(ratio))})
        primary=report['primary'];mean=primary['geometric_loss_ratio']
        for y,key in ((7,'pooled_log_CI95'),(8,'heteroscedastic_log_CI95')):
            lower,upper=np.exp(primary[key])
            ax.errorbar(mean,y,xerr=[[mean-lower],[upper-mean]],fmt='D',color='black',capsize=3,markersize=5)
        ax.axvline(1,color='0.4',linestyle='--',linewidth=.8,zorder=0)
        ax.axhline(6.1,color='0.7',linewidth=.6)
        ax.set(yticks=[*range(6),7,8],yticklabels=[*[m.removeprefix('de_').title() for m in maps],
            'Pooled 95% CI (df = 6)','Variance sensitivity 95% CI'],xlim=(.94,1.10),ylim=(8.6,-.7),
            xlabel='Reconstruction loss ratio: Graph+GRU / MLP+GRU (1 = equal loss)')
        ax.grid(axis='x',color='0.9',linewidth=.5)
        ax.legend(handles=[Line2D([],[],marker=markers[e],label=labels[e],linestyle='None',
                      markerfacecolor='white',markeredgecolor='black',color='black') for e in markers],
                  loc='lower left',bbox_to_anchor=(0,1.01),ncol=3,frameon=False,fontsize=9,columnspacing=1.1)
        for ext in ('pdf','svg','png'):
            fig.savefig(stem.with_suffix('.'+ext),dpi=600,facecolor='white',transparent=False)
        plt.close(fig)
    csv_path=out/'independent_confirmation_source_data.csv'
    with csv_path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
    write(out/'independent_confirmation_manifest.json',{'source_report_sha256':digest(source),
        'plot_script_sha256':digest(Path(__file__)),'phase':'IEEE ToG full-paper working draft, not submission certification',
        'width_mm':181.9,'height_mm':108,'raster_DPI':600,'unit':'12 series; seed/window means within series, two series per map',
        'uncertainty':'Prespecified pooled normal-residual t CI, df6; Welch-Satterthwaite variance sensitivity, df '+str(primary['Welch_Satterthwaite_df']),
        'transformations':['Arithmetic averaging over windows and seeds within series','Graph/MLP series loss ratio','Equal-map mean of series log ratios, then exponentiation for the summary'],
        'missing_data':'No selected series omitted; one prelisted format replacement and one early-window exclusion are recorded upstream',
        'alt_text':'Twelve series-level Graph+GRU to MLP+GRU reconstruction loss ratios across six maps. Both model-based 95% summary intervals include one; Anubis has the largest within-map separation.',
        'guidelines_checked_date':'2026-10-26','guidelines':['https://transactions.games/submit/submission-guidelines',
            'https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/resolution-and-size/'],
        'outputs_sha256':{p.name:digest(p) for p in [*(stem.with_suffix('.'+e) for e in ('pdf','svg','png')),csv_path]}})


if __name__=='__main__':main()
