"""Reduce scalar runs to bounded review evidence and optional static figures.

NumPy is sufficient for the JSON summary. --figures uses optional Matplotlib
(exercised version 3.10.8), never imported by the application or research solver.
"""

import argparse
import hashlib
import json
from pathlib import Path
import statistics

from .model import MODELS


SUITES = ("screen", "long", "stress", "robustness", "parameters", "full-grid", "followup")
LABELS = dict(linear="Accepted linear", massive="Massive linear", quartic="Hard quartic",
              sextic="Soft sextic", sine_gordon="Sine-Gordon")
COLORS = dict(linear="#747d8c", massive="#2e66ba", quartic="#be701d",
              sextic="#008675", sine_gordon="#8d4aa2")


def average(records, key):
    values = [r[key] for r in records if r[key] is not None]
    return statistics.fmean(values) if values else None


def compact(result):
    records = result["records"]
    duration = result["case"]["duration"]
    tail = [r for r in records if r["time"] >= duration-min(20, duration/2)-1e-9]
    initial = result["initial_energy"]
    scale = max(initial, max(abs(r["input_work"]) for r in records), 1e-30)
    cessation = next((r["energy"] for r in records if abs(r["time"]-5) < 1e-9), None)
    ref_energy = cessation if result["case"]["stimulus"] == "cessation" else initial
    late_energy = average(tail, "energy")
    checkpoints = [r for r in records if any(abs(r["time"]-t) < 1e-9 for t in (0, 2, 5, 10, 20, 40, 60, 120))]
    return dict(name=result["name"], case=result["case"], status=result["status"], error=result["error"],
                steps=result["steps"], dt_bound=result["fixed_dt_bound"], initial_energy=initial,
                sampled_peak=max(r["peak"] for r in records), final=records[-1],
                max_relative_balance_residual=max(abs(r["balance_residual"]) for r in records)/scale,
                retention_reference_energy=ref_energy,
                late_mean_energy=late_energy,
                late_mean_retention=late_energy/ref_energy if ref_energy and late_energy is not None else None,
                late_mean_core_fraction=average(tail, "core_fraction"),
                late_mean_participation=average(tail, "participation"),
                late_mean_cycles_rms=average(tail, "cycles_rms"),
                late_mean_spectral_high=average(tail, "spectral_high"),
                checkpoints=[{k:r[k] for k in ("time", "peak", "energy", "core_fraction", "participation")}
                             for r in checkpoints],
                final_u_sha256=result["final_u_sha256"], final_v_sha256=result["final_v_sha256"])


def load_all(directory):
    return {name:json.loads((directory/(name+".json")).read_text())
            for name in (*SUITES, "checks", "mechanism")}


def pick(data, suite, model, **where):
    candidates = [r for r in data[suite]["results"] if r["case"]["model"] == model
                  and all(r["case"][key] == value for key,value in where.items())]
    if len(candidates) != 1:
        raise ValueError(f"expected one case: {suite}, {model}, {where}; found {len(candidates)}")
    return candidates[0]


def save_svg(figure, path):
    figure.savefig(path, metadata={"Date":None})
    # Matplotlib's path formatting leaves trailing spaces on coordinate lines.
    path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines())+"\n")


def figures(data, output):
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size":10, "svg.hashsalt":"sentio-issue-3", "svg.fonttype":"none"})
    fig, axes = plt.subplots(3, 3, figsize=(13, 9), constrained_layout=True)
    for column, (suite, damping, duration) in enumerate((("screen", .4, 40), ("long", .02, 120), ("followup", 0, 120))):
        for model in MODELS:
            run = pick(data, suite, model, stimulus="seed", n=65, length=1, sponge=True, timestep_factor=1)
            records = run["records"]
            t = np.array([r["time"] for r in records])
            retention = np.array([r["energy"]/run["initial_energy"] for r in records])
            kw = dict(color=COLORS[model], label=LABELS[model], lw=1.5)
            axes[0, column].semilogy(t, retention, **kw)
            visible = retention >= 1e-6
            for row, key in ((1,"core_fraction"), (2,"participation")):
                values = np.array([r[key] if r[key] is not None else np.nan for r in records])
                axes[row, column].plot(t, np.where(visible, values, np.nan), **kw)
        axes[0, column].set_title(f"Uniform damping γ={damping:g}; sponge retained")
        axes[0, column].set_ylim(1e-12, 1.2)
        for row in range(3):
            axes[row, column].set_xlim(0, duration)
            axes[row, column].grid(alpha=.2)
        axes[1, column].set_ylim(0, 1.02)
        axes[2, column].set_ylim(0, 1.02)
        axes[2, column].set_xlabel("Model time (s)")
    for row, label in enumerate(("Total energy / initial energy", "Energy fraction inside r≤0.2", "Energy participation fraction")):
        axes[row,0].set_ylabel(label)
    handles, labels = axes[0,0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=5)
    fig.suptitle("Identical imposed Gaussian seed; N=65, c=0.3, ω=8, A=0.1\n"
                 "No forcing. Organization curves omitted when E/E₀ < 10⁻⁶; no lifetime extrapolation.", fontsize=12)
    save_svg(fig, output/"seed-comparison.svg")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), constrained_layout=True)
    for result in data["mechanism"]["results"]:
        model, rate = result["model"], result["rate"]
        values = np.asarray(result["center"])
        t = np.arange(len(values))/rate
        select = t >= 117
        axes[0].plot(t[select], values[select], label=LABELS[model], color=COLORS[model])
        axes[1].semilogy(result["spectrum_frequency"], result["spectrum_power"], color=COLORS[model], label=LABELS[model])
    axes[0].set(xlabel="Model time (s)", ylabel="Actual signed u at domain center", ylim=(-.16,.16))
    axes[1].axvline(8/(2*np.pi), color="#333333", ls="--", label="Linear radiation threshold")
    axes[1].set(xlabel="Frequency (cycles / model second)", ylabel="Power / each curve's maximum", xlim=(0,5), ylim=(1e-10,2))
    for ax in axes:
        ax.grid(alpha=.2)
        ax.legend(fontsize=8)
    fig.suptitle("Seeded N=129, γ=0, h≤1/480; center sampled at 120 Hz\n"
                 "Spectrum: last 60 s, mean removed and Hann windowed; field itself is unfiltered.", fontsize=11)
    save_svg(fig, output/"temporal-mechanism.svg")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("runs/issue3"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--figures", action="store_true")
    args = parser.parse_args()
    target = args.output/"summary.json"
    if target.exists():
        parser.error("summary already exists; choose a new output directory")
    data = load_all(args.input)
    summary = dict(schema=1, issue=3, baseline_commit="46f90e22dcb75b7f8a6db268b22038c882f3277b",
                   input_sha256={name:hashlib.sha256((args.input/(name+".json")).read_bytes()).hexdigest() for name in data},
                   suites={name:dict(metadata=data[name]["metadata"], cases=[compact(r) for r in data[name]["results"]]) for name in SUITES},
                   convergence=data["checks"], refined_spatial=data["followup"]["spatial"],
                   mechanism=[{k:v for k,v in r.items() if k not in ("center", "spectrum_frequency", "spectrum_power")}
                              for r in data["mechanism"]["results"]],
                   mechanism_metadata=data["mechanism"]["metadata"])
    summary["total_comparison_cases"] = sum(len(data[name]["results"]) for name in SUITES)
    summary["noncomplete_cases"] = [r["name"] for name in SUITES for r in data[name]["results"] if r["status"] != "complete"]
    args.output.mkdir(parents=True, exist_ok=True)
    # Compact records keep the committed scalar evidence below a few hundred KB.
    target.write_text(json.dumps(summary, allow_nan=False, separators=(",", ":"))+"\n")
    if args.figures:
        figures(data, args.output)
    print(f"{summary['total_comparison_cases']} comparisons; {len(summary['noncomplete_cases'])} stopped; summary {target.stat().st_size} bytes")


if __name__ == "__main__":
    main()
