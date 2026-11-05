"""Predeclared deterministic histories and state-matched probes; model-time input."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
from pathlib import Path
import platform
import time

import numpy as np

from .model import ReinforcedField, Reinforcement


SCHEDULES = {
    "repeated": ((0, .5), (1.5, 2), (3, 3.5), (4.5, 5)),
    "single_recent": ((3, 5),), "single_early": ((0, 2),),
    "clustered": ((2, 2.5), (2.75, 3.25), (3.5, 4), (4.5, 5)),
    "zero": (),
}


@dataclass(frozen=True)
class Case:
    model: str = "linear"
    activity: str = "source"
    enabled: bool = True
    history: str = "repeated"
    shape: str = "familiar"
    n: int = 65
    timestep_factor: float = 1.0
    sponge: bool = True
    eta: float = 2.0
    decay: float = .02
    alpha: float = 9.0
    gamma_min: float = .02
    duration: float = 13.0

    @property
    def name(self):
        return (f"{self.model}-{self.activity if self.enabled else 'fixed'}-{self.history}-{self.shape}"
                f"-n{self.n}-h{self.timestep_factor:g}-s{int(self.sponge)}-eta{self.eta:g}"
                f"-lambda{self.decay:g}-alpha{self.alpha:g}-min{self.gamma_min:g}-T{self.duration:g}")


def make_field(case):
    return ReinforcedField(case.n, case.model,
        Reinforcement(case.activity, case.eta, case.decay, case.alpha, case.gamma_min),
        case.enabled, sponge=case.sponge, timestep_factor=case.timestep_factor)


def patterns(n):
    y, x = np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, n), indexing="ij")
    def spot(cx, cy):
        a = np.exp(-((x-cx)**2+(y-cy)**2)/(2*.07**2))
        a[[0, -1], :] = 0
        a[:, [0, -1]] = 0
        return a
    familiar = spot(.35, .5)
    displaced = familiar[:, ::-1].copy()
    novel = spot(.35, .43)-spot(.35, .57)
    novel *= np.sqrt(np.sum(familiar**2)/np.sum(novel**2))
    probe = familiar+displaced
    assert max(np.max(np.abs(a)) for a in (familiar, displaced, novel, probe)) <= 1.01
    return dict(familiar=familiar, displaced=displaced, novel=novel, probe=probe), (
        (x-.35)**2+(y-.5)**2 <= .14**2, (x-.65)**2+(y-.5)**2 <= .14**2)


def source_at(case, t, shape):
    return .5*shape if any(start <= t < end for start, end in SCHEDULES[case.history]) else None


def measure(field, masks):
    density = field.density()
    d = field.diagnostics()
    total_m = float(field.m.sum())
    d["m_participation"] = (total_m**2/(field.m.size*float(np.sum(field.m**2)))
                             if total_m > 1e-20 else None)
    for label, mask in zip(("left", "right"), masks):
        d[f"{label}_energy"] = field.wave.dx**2*float(density[mask].sum())
        d[f"{label}_m_fraction"] = float(field.m[mask].sum())/total_m if total_m > 1e-20 else None
        d[f"{label}_m_mean"] = float(field.m[mask].mean())
    return d


def integrate(field, shape, intervals, duration, masks, sample_interval=.1):
    """Align every discontinuity and diagnostic sample exactly in model time."""
    boundaries = sorted({0.0, duration, *(t for pair in intervals for t in pair)})
    records = [measure(field, masks)]
    index = 1
    while field.wave.time < duration-1e-12:
        t = field.wave.time
        # The tolerance identifies an aligned boundary after roundoff, never
        # shifts the pulse schedule by an entire time step.
        source = .5*shape if any(a-1e-12 <= t < b-1e-12 for a, b in intervals) else None
        next_sample = min(index*sample_interval, duration)
        next_event = min(b for b in boundaries if b > t+1e-12)
        field.step(source, min(field.dt, next_sample-t, next_event-t))
        if field.wave.time >= next_sample-1e-12:
            records.append(measure(field, masks))
            index += 1
    return records


def summarize(records, off=5):
    post = [d for d in records if d["time"] >= off-1e-9]
    e0 = post[0]["energy"] if post else 0
    half = next((d["time"]-off for i,d in enumerate(post)
                 if e0 > 1e-20 and all(r["energy"] <= .5*e0 for r in post[i:])), None)
    scale = max(max(abs(d["input_work"]) for d in records), records[0]["energy"], 1e-30)
    return dict(off_energy=e0, retention=post[-1]["energy"]/e0 if e0 > 1e-20 else None,
                half_crossing=half,
                max_relative_balance_residual=max(abs(d["balance_residual"]) for d in records)/scale,
                max_source_off_energy_increase=max((max(0,b["energy"]-a["energy"]) for a,b in zip(post,post[1:])), default=0),
                energy_integral=float(np.trapezoid([d["energy"] for d in records], [d["time"] for d in records])),
                regional_integrals={side:float(np.trapezoid([d[f"{side}_energy"] for d in records],
                                                             [d["time"] for d in records])) for side in ("left", "right")})


def run_case(case, keep_maps=False):
    if case.history not in SCHEDULES or case.shape not in ("familiar", "displaced", "novel"):
        raise ValueError("unknown research history/shape")
    if not 5 <= case.duration <= 60:
        raise ValueError("research duration must be 5..60 model seconds")
    start = time.monotonic()
    field = make_field(case)
    shapes, masks = patterns(case.n)
    result = dict(name=case.name, case=asdict(case), status="complete", error="", probes={})
    maps = {}
    try:
        records = integrate(field, shapes[case.shape], SCHEDULES[case.history], case.duration, masks)
        result.update(records=records, summary=summarize(records))
        if keep_maps:
            maps = dict(u=field.wave.u.copy(), m=field.m.copy())
        for label in ("retained", "erased"):
            probe = make_field(case)
            if label == "retained":
                probe.m[:] = field.m
            probe.rebase()  # u/v are explicitly zero in both probe interventions.
            probe_records = integrate(probe, shapes["probe"], ((0, .5),), 4, masks)
            result["probes"][label] = dict(records=probe_records, summary=summarize(probe_records, .5))
        result["probe_gain"] = {
            region: result["probes"]["retained"]["summary"]["regional_integrals"][region] /
                    result["probes"]["erased"]["summary"]["regional_integrals"][region]
            for region in ("left", "right")}
    except (ValueError, FloatingPointError, OverflowError) as exc:
        result.update(status="stopped", error=str(exc))
    result.update(final=measure(field, masks), steps=field.wave.step_count, dt_bound=field.dt,
                  final_sha256={name:hashlib.sha256(a.tobytes()).hexdigest()
                                for name,a in (("u",field.wave.u),("v",field.wave.v),("m",field.m))},
                  wall_seconds=time.monotonic()-start)
    return result, maps


def cases_for(suite):
    nominal = [Case(model=model, activity=activity, enabled=enabled)
               for model in ("linear", "sextic")
               for activity, enabled in (("source", False), ("source", True), ("wave", True))]
    if suite == "matrix":
        return [replace(base, history=history, shape=shape) for base in nominal for history,shape in (
            ("repeated","familiar"), ("single_recent","familiar"), ("single_early","familiar"),
            ("clustered","familiar"), ("repeated","displaced"), ("repeated","novel"), ("zero","familiar"))]
    if suite == "sweep":
        return [replace(base, **change) for base in nominal if base.enabled for change in (
            {"eta":0}, {"eta":.5}, {"eta":4}, {"decay":0}, {"decay":.2},
            {"alpha":0}, {"alpha":4}, {"alpha":32}, {"gamma_min":0}, {"gamma_min":.4})]
    if suite == "refine":
        return [replace(base, **change) for base in nominal for change in (
            {"n":33}, {"n":129}, {"timestep_factor":.5}, {"sponge":False})]
    if suite == "full_grid":
        return [replace(base, n=256) for base in nominal]
    if suite == "long":
        return [replace(base, duration=60) for base in nominal if base.enabled]
    if suite == "slow":
        # Explicit follow-up after the first matrix: a separated slower map,
        # without changing the nominal runs or selecting a more favorable shape.
        return [replace(base, eta=eta) for base in nominal if base.enabled for eta in (.05,.2)]
    if suite == "slow_refine":
        return [replace(base, eta=.05, **change) for base in nominal if base.enabled
                for change in ({"n":129}, {"timestep_factor":.5})]
    raise ValueError("unknown suite")


def provenance():
    paths = [Path("sentio/field.py"), Path("sentio/sextic.py"), *Path("research/issue_10").glob("*.py"),
             Path("research/issue_10/README.md")]
    return dict(utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(), numpy=np.__version__,
                platform=platform.platform(), random_seed=None, sample_interval=.1,
                baseline_commit="2e7ecd7ff72b7dda9e89abbf93e3c31f0d92d6d0",
                source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


def execute(case):
    return run_case(case)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("matrix", "sweep", "refine", "full_grid", "long", "slow", "slow_refine"), required=True)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; choose a new evidence path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cases, results, metadata = cases_for(args.suite), [], provenance()
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(execute, c) for c in cases]):
            result = future.result()
            results.append(result)
            print(f"{len(results)}/{len(cases)} {result['name']}: {result['status']}", flush=True)
    results.sort(key=lambda r:r["name"])
    args.output.write_text(json.dumps(dict(schema=1, suite=args.suite, metadata=metadata, results=results),
                                      allow_nan=False, separators=(",", ":"))+"\n")
    return int(any(r["status"] != "complete" for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
