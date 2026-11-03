"""Quantitative space/time consistency and energy-balance checks."""

import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from .experiments import Case, provenance, run_case
from .model import MODELS


def state_error(a, b, stride=1):
    u, v = b.u[::stride, ::stride], b.v[::stride, ::stride]
    scale = a.potential.omega
    numerator = np.mean((a.u-u)**2 + ((a.v-v)/scale)**2)
    denominator = np.mean(u*u + (v/scale)**2)
    return float(np.sqrt(numerator/max(denominator, 1e-30)))


def checks():
    result = dict(schema=1, metadata=provenance(), temporal=[], spatial=[], balance=[])
    for model in MODELS:
        base = Case(model, "seed", duration=2, n=65, damping=0, sponge=False)
        fields = [run_case(replace(base, timestep_factor=factor))[1] for factor in (1, .5, .25)]
        coarse, fine = state_error(fields[0], fields[1]), state_error(fields[1], fields[2])
        result["temporal"].append(dict(model=model, n=65, duration=2, coarse_difference=coarse,
                                       fine_difference=fine, reduction=coarse/fine,
                                       dt=[field.dt for field in fields]))
        fields = [run_case(replace(base, n=n, timestep_factor=.25))[1] for n in (33, 65, 129)]
        coarse, fine = state_error(fields[0], fields[1], 2), state_error(fields[1], fields[2], 2)
        result["spatial"].append(dict(model=model, n=[33, 65, 129], duration=2, dt=fields[0].dt,
                                      coarse_difference=coarse, fine_difference=fine, reduction=coarse/fine))
        for stimulus, damping, sponge in (("seed", 0, False), ("stationary", .4, True)):
            entries = []
            for factor in (1, .5):
                r, _, _ = run_case(Case(model, stimulus, duration=4, n=65, damping=damping,
                                         sponge=sponge, timestep_factor=factor), sample_interval=.1)
                max_residual = max(abs(s["balance_residual"]) for s in r["records"])
                scale = max(r["initial_energy"], max(abs(s["input_work"]) for s in r["records"]), 1e-30)
                entries.append(dict(timestep_factor=factor, max_residual=max_residual,
                                    relative_residual=max_residual/scale, status=r["status"]))
            result["balance"].append(dict(model=model, stimulus=stimulus, duration=4, entries=entries,
                                          reduction=entries[0]["max_residual"]/entries[1]["max_residual"]))
        print(f"checked {model}", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; preserve prior evidence by using a new path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(checks(), indent=2, allow_nan=False)+"\n")
