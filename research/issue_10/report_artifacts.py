"""Compact review evidence and fixed-scale scientific figures from actual runs."""

import argparse
import hashlib
import json
from pathlib import Path

from .experiments import Case, run_case


SUITES = ("matrix", "sweep", "refine", "full_grid", "long")


def pick(data, suite="matrix", **where):
    found = [r for r in data[suite]["results"] if all(r["case"][k] == v for k,v in where.items())]
    if len(found) != 1:
        raise ValueError(f"expected one case, found {len(found)}: {suite}, {where}")
    return found[0]


def compact(r):
    keys=("name","case","status","error","final","steps","dt_bound","final_sha256","summary","probe_gain")
    result={k:r[k] for k in keys if k in r}
    result["probes"]={key:dict(summary=p["summary"],final={k:p["records"][-1][k] for k in
        ("time","energy","input_work","source_action","m_mean","m_max","coverage")})
        for key,p in r["probes"].items()}
    return result


def save_figure(fig, path):
    fig.savefig(path,metadata={"Date":None})
    path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines())+"\n")


def figures(data, directory):
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Circle
    plt.rcParams.update({"font.size":10,"svg.hashsalt":"sentio-issue-10","svg.fonttype":"none"})
    colors={"fixed":"#737b89","source":"#087d8c","wave":"#a95b1b"}
    fig,axes=plt.subplots(2,2,figsize=(11,7.5),constrained_layout=True)
    for col,model in enumerate(("linear","sextic")):
        for activity,enabled in (("source",False),("source",True),("wave",True)):
            key=activity if enabled else "fixed"
            r=pick(data,model=model,activity=activity,enabled=enabled,history="repeated",shape="familiar")
            off=[d for d in r["records"] if d["time"]>=5-1e-9]
            axes[0,col].semilogy([d["time"]-5 for d in off],
                                 [d["energy"]/off[0]["energy"] for d in off],label=key,color=colors[key])
            axes[1,col].plot([d["time"] for d in r["records"]],
                            [100*d["coverage"] for d in r["records"]],label=key,color=colors[key])
        axes[0,col].set(title=model,xlabel="Model seconds since source off",ylabel="E(t) / E(5)",ylim=(1e-4,1.1))
        axes[1,col].set(xlabel="Model seconds",ylabel="Domain coverage with m ≥ 0.1 (%)",ylim=(-2,102))
        axes[1,col].axvline(5,color="#555",ls="--",lw=1,label="source off")
        for row in range(2):
            axes[row,col].grid(alpha=.2)
            axes[row,col].legend()
    fig.suptitle("Matched repeated input, N=65, c=.3, γ₀=.4, κ=2\n"
                 "Energy retention and reinforcement spread are distinct measurements",fontsize=12)
    save_figure(fig,directory/"decay-and-coverage.svg")
    fig.savefig(directory/"decay-and-coverage.png",dpi=130)
    plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(11,4.3),constrained_layout=True)
    for ax,model in zip(axes,("linear","sextic")):
        labels,values,bar_colors=[],[],[]
        for activity,enabled in (("source",False),("source",True),("wave",True)):
            key=activity if enabled else "fixed"
            r=pick(data,model=model,activity=activity,enabled=enabled,history="repeated",shape="familiar")
            for region in ("left","right"):
                labels.append(key+"\n"+region)
                values.append(100*(r["probe_gain"][region]-1))
                bar_colors.append(colors[key])
        ax.bar(labels,values,color=bar_colors,width=.65)
        ax.axhline(0,color="#222",ls="--")
        ax.set(title=model,ylim=(0,11),ylabel="Change in regional ∫E dt vs erased m (%)")
        ax.grid(axis="y",alpha=.2)
    fig.suptitle("Same two-spot probe after explicitly zeroing u/v in both conditions\n"
                 "Left region was exposed; m continues to evolve during the 4 s probe",fontsize=12)
    save_figure(fig,directory/"matched-probe.svg")
    fig.savefig(directory/"matched-probe.png",dpi=130)
    plt.close(fig)

    palette=LinearSegmentedColormap.from_list("signed",["#419bff","#181818","#ff7f33"])
    fig,axes=plt.subplots(4,2,figsize=(9,12),constrained_layout=True)
    replay=[]
    for row,(model,activity) in enumerate((m,a) for m in ("linear","sextic") for a in ("source","wave")):
        prior=pick(data,model=model,activity=activity,enabled=True,history="repeated",shape="familiar")
        result,maps=run_case(Case(**prior["case"]),keep_maps=True)
        if result["status"]!="complete" or result["final_sha256"]!=prior["final_sha256"]:
            raise AssertionError("figure replay does not match recorded numerical state")
        replay.append(dict(name=prior["name"],final_sha256=result["final_sha256"]))
        u=axes[row,0].imshow(maps["u"],origin="lower",extent=(0,1,0,1),vmin=-.025,vmax=.025,cmap=palette)
        m=axes[row,1].imshow(maps["m"],origin="lower",extent=(0,1,0,1),vmin=0,vmax=1,cmap="cividis")
        axes[row,0].set_title(f"{model}, {activity}: signed u")
        axes[row,1].set_title(f"{model}, {activity}: reinforcement m")
        for ax in axes[row]:
            ax.add_patch(Circle((.35,.5),.14,fill=False,edgecolor="white",ls="--",lw=.8))
            ax.add_patch(Circle((.65,.5),.14,fill=False,edgecolor="white",ls=":",lw=.8))
            ax.set(xlabel="x",ylabel="y")
    fig.colorbar(u,ax=axes[:,0],label="Field units; fixed ±0.025")
    fig.colorbar(m,ax=axes[:,1],label="Reinforcement; fixed 0..1")
    fig.suptitle("Actual states at t=13: eight model seconds after input removal\n"
                 "Identical color limits across every row; disks mark measurement regions",fontsize=12)
    save_figure(fig,directory/"wave-and-map.svg")
    fig.savefig(directory/"wave-and-map.png",dpi=130)
    plt.close(fig)
    return replay


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--figures",action="store_true")
    args=parser.parse_args()
    if args.output.exists():
        parser.error("output directory exists; choose a new review-artifact path")
    data={name:json.loads((args.input/(name+".json")).read_text()) for name in (*SUITES,"checks")}
    args.output.mkdir(parents=True)
    summary=dict(schema=1,issue=10,
        input_sha256={name:hashlib.sha256((args.input/(name+".json")).read_bytes()).hexdigest() for name in data},
        suites={name:dict(metadata=data[name]["metadata"],cases=[compact(r) for r in data[name]["results"]]) for name in SUITES},
        checks=data["checks"],nominal_curves=[])
    for r in data["matrix"]["results"]:
        if r["case"]["history"]=="repeated" and r["case"]["shape"]=="familiar":
            summary["nominal_curves"].append(dict(name=r["name"],status=r["status"],
                records=[{k:d[k] for k in ("time","energy","m_mean","coverage","balance_residual")}
                         for d in r.get("records",[])]))
    summary["comparison_cases"]=sum(len(data[s]["results"]) for s in SUITES)
    summary["stopped_cases"]=[r["name"] for s in SUITES for r in data[s]["results"] if r["status"]!="complete"]
    if args.figures and not summary["stopped_cases"]:
        summary["figure_replay"]=figures(data,args.output)
    elif args.figures:
        summary["figures_omitted"]="Stopped cases retained; inspect their reported stop states before plotting complete-case comparisons."
    (args.output/"summary.json").write_text(json.dumps(summary,allow_nan=False,separators=(",", ":"))+"\n")
    print(json.dumps(dict(cases=summary["comparison_cases"],stopped=summary["stopped_cases"],
                          summary_bytes=(args.output/"summary.json").stat().st_size)))


if __name__ == "__main__":
    main()
