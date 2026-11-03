"""Deterministic matched comparisons. All output is local scalar evidence.

python3 -m research.issue_3.experiments --suite screen --output runs/issue3/screen.json --workers 4
"""

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

from sentio.field import Parameters
from sentio.inputs import synthetic_source
from .model import MODELS, Potential, ResearchField, measure


@dataclass(frozen=True)
class Case:
    model: str
    stimulus: str
    duration: float = 40.0
    n: int = 65
    damping: float = .4
    coupling: float = 2.0
    speed: float = .3
    omega: float = 8.0
    amplitude: float = .1
    length: float = 1.0
    timestep_factor: float = 1.0
    sponge: bool = True
    seed_ratio: float = 1.2
    seed_width: float = .15

    @property
    def name(self):
        return (f"{self.model}-{self.stimulus}-n{self.n}-g{self.damping:g}-k{self.coupling:g}"
                f"-L{self.length:g}-dt{self.timestep_factor:g}-sponge{int(self.sponge)}"
                f"-w{self.omega:g}-A{self.amplitude:g}-seed{self.seed_ratio:g}"
                f"-width{self.seed_width:g}-T{self.duration:g}")


def make_field(case):
    field = ResearchField(case.n, Parameters(case.speed, case.damping, case.coupling),
                          Potential(case.model, case.omega, case.amplitude),
                          case.length, case.timestep_factor, case.sponge)
    axis = np.linspace(-case.length/2, case.length/2, case.n)
    radius2 = axis[:, None]**2 + axis[None, :]**2
    if case.stimulus == "seed":
        field.u[:] = case.seed_ratio*case.amplitude*np.exp(-radius2/case.seed_width**2)
    elif case.stimulus == "impulse":
        field.v[:] = case.omega*case.amplitude*np.exp(-radius2/.06**2)
    field._edge_zero(field.u)
    field._edge_zero(field.v)
    return field


def source_at(case, t):
    if case.stimulus in ("zero", "seed", "impulse"):
        return None
    if case.stimulus == "uniform":
        return np.ones((case.n, case.n))
    if case.stimulus == "resonant":
        axis = np.linspace(0, 1, case.n)
        spatial = np.outer(np.sin(np.pi*axis), np.sin(np.pi*axis))
        frequency = np.sqrt(case.omega**2 + 2*(np.pi*case.speed/case.length)**2)
        return spatial*np.sin(frequency*t)
    if case.length != 1:
        raise ValueError("shared camera-like sources are defined on the unit square")
    if case.stimulus == "cessation":
        return synthetic_source(case.n, t, "stationary") if t < 5 else None
    return synthetic_source(case.n, t, case.stimulus)


def run_case(case, sample_interval=.5, keep_snapshots=False):
    if not 0 < case.duration <= 240 or not 0 < sample_interval <= case.duration:
        raise ValueError("invalid bounded duration/sample interval")
    start = time.monotonic()
    field = make_field(case)
    initial_energy = field.energy()
    records = [measure(field, initial_energy)]
    snapshots = {0.0: field.u.copy()} if keep_snapshots else {}
    frame_index, sample_index = 0, 1
    status, error, source = "complete", "", None
    while field.time < case.duration-1e-12:
        if field.time >= frame_index/30-1e-12:
            source = source_at(case, frame_index/30)
            frame_index += 1
        next_sample = min(sample_index*sample_interval, case.duration)
        h = min(field.dt, frame_index/30-field.time, next_sample-field.time)
        try:
            field.step(source, h)
        except (FloatingPointError, ValueError) as exc:
            status, error = "stopped", str(exc)
            break
        if field.time >= next_sample-1e-12:
            records.append(measure(field, initial_energy))
            if keep_snapshots and any(abs(field.time-t) < 1e-9 for t in (2, 10, 40, 60, 120)):
                snapshots[round(field.time, 8)] = field.u.copy()
            sample_index += 1
    if abs(records[-1]["time"]-field.time) > 1e-9:
        records.append(measure(field, initial_energy))
    result = dict(name=case.name, case=asdict(case), status=status, error=error,
                  steps=field.step_count, fixed_dt_bound=field.dt,
                  initial_energy=initial_energy, records=records,
                  final_u_sha256=hashlib.sha256(field.u.tobytes()).hexdigest(),
                  final_v_sha256=hashlib.sha256(field.v.tobytes()).hexdigest(),
                  wall_seconds=time.monotonic()-start)
    return result, field, snapshots


def execute(case):
    return run_case(case)[0]


def cases_for(suite):
    if suite == "screen":
        return [Case(model, stimulus) for model in MODELS
                for stimulus in ("zero", "impulse", "seed", "stationary", "moving", "viewpoint", "recurring", "cessation")]
    if suite == "long":
        return [Case(model, stimulus, duration=120, damping=.02) for model in MODELS
                for stimulus in ("seed", "impulse", "resonant")]
    if suite == "stress":
        return [Case(model, "uniform", duration=40, coupling=20) for model in MODELS]
    if suite == "robustness":
        cases = []
        for model in MODELS:
            base = Case(model, "seed", duration=120, damping=.02)
            cases.append(replace(base, n=129))
            cases.append(replace(base, n=129, length=2))  # Same dx as N=65, L=1.
        for model in ("massive", "sextic", "sine_gordon"):
            cases.append(Case(model, "seed", duration=120, n=129, damping=.02, timestep_factor=.5))
            cases.append(Case(model, "seed", duration=120, damping=.02, sponge=False))
        return cases
    if suite == "parameters":
        # One-factor variations, never presented as a Cartesian safe range.
        base = Case("sextic", "seed", duration=60, damping=.02)
        return [replace(base, **change) for change in (
            {"omega":6}, {"omega":10}, {"amplitude":.075}, {"amplitude":.15},
            {"seed_ratio":.8}, {"seed_ratio":1.6}, {"seed_width":.12}, {"seed_width":.18})]
    if suite == "full_grid":
        return [Case(model, "cessation", duration=10, n=256) for model in MODELS]
    raise ValueError("unknown suite")


def provenance():
    paths = ("sentio/field.py", "sentio/inputs.py", "research/issue_3/model.py",
             "research/issue_3/experiments.py")
    return dict(utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
                numpy=np.__version__, platform=platform.platform(), random_seed=None,
                source_rate=30, sample_interval=.5,
                source_sha256={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("screen", "long", "stress", "robustness", "parameters", "full_grid"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1, choices=range(1, 5))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; use a new path to preserve prior evidence")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cases = cases_for(args.suite)
    results = []
    metadata = provenance()
    # Explicit spawn avoids Python-version-dependent forkserver behavior and
    # does not require a local listening socket in restricted environments.
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        pending = {pool.submit(execute, case):case for case in cases}
        for future in as_completed(pending):
            result = future.result()
            results.append(result)
            print(f"{len(results)}/{len(cases)} {result['name']}: {result['status']} "
                  f"t={result['records'][-1]['time']:.3f} E={result['records'][-1]['energy']:.6g}", flush=True)
    results.sort(key=lambda r:r["name"])
    args.output.write_text(json.dumps(dict(schema=1, suite=args.suite, metadata=metadata,
                                          results=results), allow_nan=False, indent=2)+"\n")


if __name__ == "__main__":
    main()
