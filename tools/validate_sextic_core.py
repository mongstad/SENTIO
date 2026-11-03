"""Bounded issue #6 core measurements; no application/camera integration.

Run --suite checks, long, and throughput separately. Run throughput without
other numerical workers to measure the standalone solver, not real-time UI.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
from pathlib import Path
import platform
import statistics
import time

import numpy as np

from research.issue_3.model import Potential, ResearchField
from sentio.field import Parameters
from sentio.inputs import synthetic_source
from sentio.sextic import SexticField, SexticParameters


@dataclass(frozen=True)
class Case:
    stimulus: str = "seed"
    n: int = 256
    duration: float = 120.0
    damping: float = 0.0
    coupling: float = 0.0
    model: str = "sextic"
    timestep_factor: float = 1.0
    sponge: bool = True


def make_field(case):
    parameters = Parameters(.3, case.damping, case.coupling)
    if case.model == "sextic":
        field = SexticField(case.n, parameters, sponge=case.sponge)
    elif case.model == "massive":
        field = ResearchField(case.n, parameters, Potential("massive"), timestep_factor=.5, sponge=case.sponge)
    else:
        raise ValueError("unknown comparison model")
    if case.stimulus == "seed":
        axis = np.linspace(-.5, .5, case.n)
        field.u[:] = .12*np.exp(-(axis[:, None]**2+axis[None, :]**2)/.15**2)
        field._edge_zero(field.u)
    if case.model == "sextic":
        field.rebase_energy()
    return field


def measure(field, initial):
    if isinstance(field, SexticField):
        diagnostics = field.diagnostics()
    else:
        diagnostics = dict(energy=field.energy(), peak=float(np.max(np.abs(field.u))),
                           minimum=float(field.u.min()), maximum=float(field.u.max()),
                           input_work=field.input_work, damping_loss=field.damping_loss,
                           balance_residual=field.energy()-initial-field.input_work+field.damping_loss)
    density = field.energy_density()
    axis = np.linspace(-.5, .5, field.n)
    core = axis[:,None]**2+axis[None,:]**2 <= .2**2
    total = float(density.sum())
    return dict(time=field.time, **{k:diagnostics[k] for k in
                ("energy", "peak", "minimum", "maximum", "input_work", "damping_loss", "balance_residual")},
                core_fraction=float(density[core].sum()/total) if total*field.dx**2 > 1e-20 else None,
                participation=total**2/(density.size*float(np.sum(density*density))) if total*field.dx**2 > 1e-20 else None)


def run(case, interval=.5):
    start = time.perf_counter()
    field = make_field(case)
    initial = field.energy()
    records = [measure(field, initial)]
    frame, sample = 0, 1
    source = None
    uniform = np.ones_like(field.u)
    checkerboard = (np.indices(field.u.shape).sum(axis=0)%2*2-1).astype(float)
    status, error = "complete", ""
    while case.duration-field.time > 1e-12:
        if field.time >= frame/30-1e-12:
            stamp = frame/30
            if case.stimulus == "seed":
                source = None
            elif case.stimulus == "uniform":
                source = uniform
            elif case.stimulus == "checkerboard":
                source = checkerboard*(1 if frame%2 else -1)
            elif case.stimulus == "cessation":
                source = synthetic_source(case.n, stamp, "stationary") if stamp < 5 else None
            else:
                source = synthetic_source(case.n, stamp, case.stimulus)
            frame += 1
        target = min(sample*interval, case.duration)
        h = min(field.dt*case.timestep_factor, frame/30-field.time, target-field.time)
        try:
            field.step(source, h)
        except (ValueError, FloatingPointError) as exc:
            status, error = "stopped", str(exc)
            break
        if field.time >= target-1e-12:
            records.append(measure(field, initial))
            sample += 1
    if records[-1]["time"] != field.time:
        records.append(measure(field, initial))
    tail = [r for r in records if r["time"] >= case.duration-20-1e-9]
    scale = max(initial, max(abs(r["input_work"]) for r in records), 1e-30)
    result = dict(case=asdict(case), status=status, error=error, steps=field.step_count,
                  wall_seconds=time.perf_counter()-start, dt_bound=field.dt*case.timestep_factor,
                  initial_energy=initial, final=records[-1], sampled_peak=max(r["peak"] for r in records),
                  max_relative_balance=max(abs(r["balance_residual"]) for r in records)/scale,
                  late_mean_retention=statistics.fmean(r["energy"] for r in tail)/initial if tail and initial else None,
                  late_mean_core=statistics.fmean(r["core_fraction"] for r in tail if r["core_fraction"] is not None)
                      if any(r["core_fraction"] is not None for r in tail) else None,
                  checkpoints=[r for r in records if any(abs(r["time"]-t) < 1e-9 for t in (0,2,5,10,20,40,60,120))],
                  final_u_sha256=hashlib.sha256(field.u.tobytes()).hexdigest(),
                  final_v_sha256=hashlib.sha256(field.v.tobytes()).hexdigest())
    return result, field


def execute(case):
    return run(case)[0]


def state_error(a, b, stride=1):
    u, v = b.u[::stride,::stride], b.v[::stride,::stride]
    return float(np.sqrt(np.mean((a.u-u)**2+((a.v-v)/8)**2)/np.mean(u*u+(v/8)**2)))


def checks():
    temporal = [run(Case(n=65, duration=2, timestep_factor=f, sponge=False)) for f in (1,.5,.25)]
    spatial = [run(Case(n=n, duration=2, timestep_factor=.25, sponge=False)) for n in (64,127,253)]
    if any(r[0]["status"] != "complete" for r in (*temporal,*spatial)):
        raise RuntimeError("refinement run stopped; no convergence result permitted")
    result = {}
    for name, data, stride in (("temporal", temporal, 1), ("spatial", spatial, 2)):
        coarse, fine = state_error(data[0][1],data[1][1],stride), state_error(data[1][1],data[2][1],stride)
        result[name] = dict(coarse_difference=coarse, fine_difference=fine, reduction=coarse/fine,
                            cases=[r[0] for r in data])
    result["balance"] = []
    for stimulus, damping, sponge in (("seed",0,False), ("stationary",.4,True)):
        data = [run(Case(stimulus, n=65, duration=4, damping=damping, coupling=2,
                         timestep_factor=f, sponge=sponge), interval=.1)[0] for f in (1,.5)]
        result["balance"].append(dict(stimulus=stimulus, cases=data,
                                       reduction=data[0]["max_relative_balance"]/data[1]["max_relative_balance"]))
    return result


def throughput():
    field = SexticField()
    source = synthetic_source(256, 0, "stationary")
    for _ in range(100):
        field.step(source)
    windows = []
    for _ in range(3):
        start = time.perf_counter()
        for _ in range(1000):
            field.step(source)
        wall = time.perf_counter()-start
        windows.append(dict(steps=1000, wall_seconds=wall, steps_per_second=1000/wall,
                            model_seconds_per_wall_second=1000*field.dt/wall))
    return dict(configuration=dict(n=256,parameters=asdict(field.parameters),nonlinear=asdict(field.nonlinear)),
                warmup_steps=100, windows=windows, final=field.diagnostics(),
                limitation="Unpaced core only; excludes source conversion, capture, UI, and runtime publication")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=("checks","long","throughput","high_frequency"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=3, choices=range(1,5))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; choose a new path to preserve evidence")
    paths = ("sentio/field.py","sentio/sextic.py","sentio/inputs.py","research/issue_3/model.py",__file__)
    metadata = dict(utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
                    numpy=np.__version__, platform=platform.platform(), random_seed=None,
                    source_rate=30, source_sha256={str(Path(p).relative_to(Path.cwd())) if Path(p).is_absolute() else p:
                        hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths})
    if args.suite == "long":
        cases = [Case(n=n) for n in (65,129,256)]
        cases += [Case(stimulus, damping=.4, coupling=2) for stimulus in ("stationary","moving","recurring","cessation")]
        cases += [Case("checkerboard",duration=60,coupling=20),Case("uniform",duration=60,damping=.4,coupling=20),
                  Case(n=129, model="massive")]
        results = []
        with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            pending = {pool.submit(execute,case):case for case in cases}
            for future in as_completed(pending):
                result = future.result()
                results.append(result)
                print(f"{len(results)}/{len(cases)} {result['case']}: {result['status']}; E={result['final']['energy']:.8g}",flush=True)
        results.sort(key=lambda r:json.dumps(r["case"],sort_keys=True))
    elif args.suite == "high_frequency":
        # Follow-up to the long checkerboard's larger balance residual: isolate
        # time accuracy at the grid scale without changing the production step.
        results = [execute(Case("checkerboard",duration=4,coupling=20,timestep_factor=f))
                   for f in (1,.5,.25)]
    else:
        results = checks() if args.suite == "checks" else throughput()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(schema=1,suite=args.suite,metadata=metadata,results=results),
                                          indent=2,allow_nan=False)+"\n")
    print(f"wrote {args.output}",flush=True)


if __name__ == "__main__":
    main()
