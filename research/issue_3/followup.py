"""Two bounded follow-ups prompted by the initial matrix, not a parameter hunt.

1. Remove uniform damping to distinguish nonlinear confinement from a slowly
   decaying massive linear mode; retain the outgoing sponge and domain checks.
2. Refine the sextic spatial check beyond the under-resolved N=33 result.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
import hashlib
import json
import multiprocessing
from pathlib import Path

from .checks import state_error
from .experiments import Case, execute, provenance, run_case
from .model import MODELS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 5))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; choose a new path")
    cases = []
    for model in MODELS:
        base = Case(model, "seed", duration=120, damping=0)
        cases.extend((base, replace(base, n=129), replace(base, n=129, length=2)))
    cases.extend((Case("sextic", "seed", duration=120, damping=0, n=129, timestep_factor=.5),
                  Case("sextic", "seed", duration=120, damping=0, n=253, timestep_factor=.5)))
    results = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        pending = {pool.submit(execute, c):c for c in cases}
        for future in as_completed(pending):
            result = future.result()
            results.append(result)
            print(f"{len(results)}/{len(cases)} {result['name']}: {result['status']} "
                  f"E={result['records'][-1]['energy']:.6g}", flush=True)
    fields = [run_case(Case("sextic", "seed", duration=2, n=n, damping=0,
                            sponge=False, timestep_factor=.25))[1] for n in (64, 127, 253)]
    coarse, fine = state_error(fields[0], fields[1], 2), state_error(fields[1], fields[2], 2)
    metadata = provenance()
    metadata["source_sha256"]["research/issue_3/followup.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report = dict(schema=1, suite="followup", metadata=metadata,
                  rationale="Separate uniform damping from confinement; refine N=33 sextic spatial result",
                  spatial=dict(n=[64, 127, 253], duration=2, dt=fields[0].dt,
                               coarse_difference=coarse, fine_difference=fine, reduction=coarse/fine),
                  results=sorted(results, key=lambda r:r["name"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")


if __name__ == "__main__":
    main()
