"""Preserve compact scalar evidence and optional scientific SVG figures."""
import argparse
import hashlib
import json
from pathlib import Path

from .experiments import Case, run_case


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--figures',action='store_true',help='requires optional Matplotlib; not an application dependency')
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    destination=args.output/'summary.json'
    if destination.exists():
        p.error('choose a fresh output directory')
    sources={}
    results=[]
    suites=('primary','controls-final','refinement','strong-shock','full-grid')
    for name in suites:
        path=args.input/(name+'.json')
        data=json.loads(path.read_text())
        sources[name]=dict(provenance=data['provenance'],file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                           cases=len(data['results']),wall_seconds=data['wall_seconds'])
        for r in data['results']:
            if r['status']!='complete':
                results.append(r);continue
            tr=r['training']
            curves=tr['curves']
            row=dict(case=r['case'],parameters=r['parameters'],dt=r['dt'],status=r['status'],wall_seconds=r['wall_seconds'],
                     source_off=r['source_off'],source_action=tr['source_action'],relative_balance=tr['relative_balance'],
                     final=tr['final'],retention=tr['retention'],source_off_max_energy_increase=tr['source_off_max_energy_increase'],
                     state_sha256=tr['state_sha256'],map_sha256=tr['map_sha256'],probe_gain=r['probe_gain'])
            row['source_off_curves']=[{k:x[k] for k in ('t','energy','left_energy','right_energy','maximum','events_max')}
                                      for x in curves if x['t']>=r['source_off']-1e-10]
            row['probes']={}
            for label,pr in r['probes'].items():
                row['probes'][label]={k:v for k,v in pr.items() if k!='curves'}
                row['probes'][label]['curves']=[{k:x[k] for k in ('t','energy','left_energy','right_energy','gamma_min','maximum')}
                                                for x in pr['curves']]
            results.append(row)
    json.dump(dict(sources=sources,results=results),destination.open('x'),indent=2,allow_nan=False)
    for name, source in (('checks','checks-final'), ('gui-synthetic','gui-synthetic'),
                         ('gui-camera','gui-camera'), ('throughput','throughput-final')):
        (args.output/(name+'.json')).write_bytes((args.input/(source+'.json')).read_bytes())
    if not args.figures:
        return
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    plt.rcParams.update({'svg.fonttype':'none','font.size':10})
    primary=json.loads((args.input/'primary.json').read_text())['results']
    regular=[r for r in primary if r['case']['kind']=='repeated' and r['case']['enabled'] and r['case']['detector']=='envelope']
    cmap=LinearSegmentedColormap.from_list('strength',['#181818','#ffc846'])
    fig,axes=plt.subplots(2,2,figsize=(9,8),layout='constrained')
    replay=[]
    for i,model in enumerate(('linear','sextic')):
        for j,kind in enumerate(('repeated','shock')):
            r=next(r for r in primary if r['case']['model']==model and r['case']['kind']==kind and r['case']['detector']=='envelope' and r['case']['enabled'])
            actual=run_case(Case(**r['case']),include_map=True)
            assert actual['training']['map_sha256']==r['training']['map_sha256']
            assert actual['training']['state_sha256']==r['training']['state_sha256']
            replay.append(dict(case=r['case'],arrays_exact=True))
            ax=axes[i,j]
            im=ax.imshow(actual['map'],origin='lower',extent=(0,1,0,1),vmin=0,vmax=1,cmap=cmap,interpolation='nearest')
            ax.set(title=f"{model} · {kind}\nmax m={r['training']['final']['maximum']:.3f}",xlabel='x',ylabel='y')
            for center,label in ((.35,'forced region'),(.65,'comparison')):
                ax.add_patch(plt.Circle((center,.5),.14,fill=False,color='white',linewidth=.8))
    fig.colorbar(im,ax=axes,label='Actual m at t=68 model s; same fixed scale')
    fig.suptitle('Sixteen moderate pulses versus one matched squared-input pulse\nPropagation can reinforce regions away from the source')
    fig.savefig(args.output/'strength.svg');fig.savefig(args.input/'strength.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(10,7),layout='constrained')
    for i,r in enumerate(regular):
        for label,style in (('retained','-'),('erased','--')):
            rows=r['probes'][label]['curves'];times=[x['t'] for x in rows];initial=rows[0]['energy']
            axes[i,0].plot(times,[x['energy']/initial for x in rows],style,label=label+' m')
            axes[i,1].plot(times,[x['left_energy']/initial for x in rows],style,color='tab:blue',label=label+' left region')
            axes[i,1].plot(times,[x['right_energy']/initial for x in rows],style,color='tab:orange',label=label+' right region')
        for j in (0,1):
            axes[i,j].set(xlabel='Probe time (model s)',ylabel='Energy / initial total energy',
                          title=r['case']['model']+(' · total' if j==0 else ' · local regions'),ylim=(0,1 if j==0 else .55))
            axes[i,j].legend(fontsize=8);axes[i,j].grid(alpha=.2)
    fig.suptitle('Identical initial velocity probes, no forcing; event gain zero\nLocal energy also changes through propagation across region boundaries')
    fig.savefig(args.output/'probe-decay.svg');fig.savefig(args.input/'probe-decay.png',dpi=150);plt.close(fig)
    (args.output/'figure-replay.json').write_text(json.dumps(dict(matplotlib=matplotlib.__version__,runs=replay),indent=2)+'\n')
    print(json.dumps(dict(cases=len(results),summary_bytes=destination.stat().st_size,figure_replays=len(replay))))


if __name__=='__main__':
    main()
