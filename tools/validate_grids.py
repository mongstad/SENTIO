"""Bounded resolution controls and isolated CPU throughput; scalar output only."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np

from sentio.field import Field, Parameters
from sentio.grid import GRID_SIZES
from sentio.inputs import synthetic_source
from sentio.metrics import process_memory
from sentio.models import MODEL_LABELS, create_field
from sentio.sextic import SexticField


def advance(f, duration, source=None, step=None):
    target = f.time+duration
    while target-f.time > 1e-12:
        f.step(source, min(f.dt if step is None else step, target-f.time))


def initialized(cls, n, damping=0, sponge=False, xcenter=.5):
    f = cls(n, Parameters(damping=damping, coupling=0), sponge=sponge)
    axis = np.linspace(0, 1, n)
    x, y = axis[:, None], axis[None, :]
    f.u[:] = .03*np.sin(np.pi*x)*np.sin(np.pi*y)*np.exp(-((x-xcenter)**2+(y-.5)**2)/.025**2)
    f._edge_zero(f.u)
    if isinstance(f, SexticField):
        f.rebase_energy()
    return f


def projected(f):
    # Compare at fixed physical coordinates; do not compare equal array indices.
    axis, target = np.linspace(0, 1, f.n), np.linspace(0, 1, 129)
    result = []
    for a in (f.u, f.v/8):
        rows = np.array([np.interp(target, axis, row) for row in a])
        result.append(np.array([np.interp(target, axis, col) for col in rows.T]).T)
    return np.array(result)


def resolution_case(cls, n):
    f = cls(n)
    f.step()
    assert not np.any(f.u) and not np.any(f.v)
    source = synthetic_source(n, 0, "stationary")
    advance(f, .08, source)
    forced_energy = f.diagnostics()["energy"]
    before = f.u.copy()
    advance(f, .08)
    assert np.any(f.u != before) and forced_energy > 0
    forcing = dict(on_seconds=.08, off_seconds=.08, energy_at_cutoff=forced_energy,
                   final=f.diagnostics())
    # Outward spread of a physically matched central velocity pulse.
    f = cls(n, Parameters(damping=0, coupling=0))
    axis = np.linspace(-.5, .5, n)
    radius2 = axis[:, None]**2+axis[None, :]**2
    f.v[:] = .02*np.exp(-radius2/.05**2)
    f._edge_zero(f.v)
    initial_radius2 = float(np.sum(radius2*f.v**2)/np.sum(f.v**2))
    if isinstance(f, SexticField):
        f.rebase_energy()
    advance(f, .12)
    final_radius2 = float(np.sum(radius2*f.u**2)/np.sum(f.u**2))
    assert final_radius2 > initial_radius2
    assert not np.any(f.u[[0, -1], :]) and not np.any(f.u[:, [0, -1]])
    # Initially edge-compatible data in the sponge, compared with the same
    # physical profile under a fixed wall and under uniform damping alone.
    energy_ratios = {}
    for name, damping, sponge in (("wall", 0, False), ("sponge", 0, True), ("damped", 2, False)):
        f = initialized(cls, n, damping, sponge, xcenter=.06)
        initial = f.diagnostics()["energy"]
        advance(f, .12)
        energy_ratios[name] = f.diagnostics()["energy"]/initial
    assert energy_ratios["sponge"] < energy_ratios["wall"]
    assert energy_ratios["damped"] < energy_ratios["wall"]
    # Grid-scale stress, intentionally NOT a matched physical wavelength.
    f = cls(n, Parameters(speed=2, damping=0, coupling=20))
    checker = (2*((np.arange(n)[:, None]+np.arange(n)[None, :]) % 2)-1).astype(float)
    f.u[:] = .001*checker
    f._edge_zero(f.u)
    if isinstance(f, SexticField):
        f.rebase_energy()
    for _ in range(32):
        f.step(checker)
    assert f.diagnostics()["finite"]
    return dict(grid=n, model=cls.__name__, zero_passed=True, forcing_cessation=forcing,
                propagation=dict(seconds=.12, initial_velocity_radius2=initial_radius2,
                                 final_amplitude_radius2=final_radius2),
                boundary_damping_energy_ratios_at_012s=energy_ratios,
                high_frequency_32_steps=f.diagnostics())


def numerical():
    results, convergence = [], {}
    for cls in (Field, SexticField):
        projected_states, exact_errors = [], []
        for n in GRID_SIZES:
            result = resolution_case(cls, n)
            f = cls(n, Parameters(damping=0, coupling=0), sponge=False)
            axis = np.linspace(0, 1, n)
            mode = .02*np.sin(8*np.pi*axis[:, None])*np.sin(6*np.pi*axis[None, :])
            f.u[:] = mode
            f._edge_zero(f.u)
            if cls is SexticField:
                f.rebase_energy()
            advance(f, .15, step=1/1200)
            projected_states.append(projected(f))
            result["convergence_final"] = f.diagnostics()
            if cls is Field:
                exact = mode*np.cos(.3*np.pi*10*.15)
                exact_errors.append(float(np.sqrt(np.mean((f.u-exact)**2))))
                a, b, total = (Field(n, Parameters(damping=0)) for _ in range(3))
                a.v[:] = .02*np.exp(-((axis[:, None]-.47)**2+(axis[None, :]-.5)**2)/.05**2)
                b.v[:] = -.02*np.exp(-((axis[:, None]-.53)**2+(axis[None, :]-.5)**2)/.05**2)
                a._edge_zero(a.v)
                b._edge_zero(b.v)
                total.v[:] = a.v+b.v
                for field in (a, b, total):
                    advance(field, .06)
                error = max(float(np.max(np.abs(total.u-a.u-b.u))), float(np.max(np.abs(total.v-a.v-b.v))))
                assert error < 1e-12
                result["linear_superposition_max_error"] = error
            results.append(result)
            print(f"completed {cls.__name__} {n}", flush=True)
        differences = [float(np.sqrt(np.mean((a-b)**2))) for a, b in zip(projected_states, projected_states[1:])]
        assert differences[1] < differences[0]/2
        convergence[cls.__name__] = dict(common_step=1/1200, model_seconds=.15,
                                       comparison="129x129 fixed physical coordinates; bilinear u and v/8",
                                       consecutive_rms_differences=differences,
                                       reduction=differences[0]/differences[1], linear_exact_rms_errors=exact_errors)
        if exact_errors:
            assert exact_errors[0] > 3*exact_errors[1] > 9*exact_errors[2]
    return dict(cases=results, spatial_convergence=convergence)


def throughput(grid, model):
    f = create_field(model, grid)
    source = synthetic_source(grid, 0, "stationary")
    for _ in range(10):
        f.step(source)
    start, old_steps, old_time = time.perf_counter(), f.step_count, f.time
    while time.perf_counter()-start < 3:
        f.step(source)
    wall = time.perf_counter()-start
    return dict(grid=grid, model=model, wall_seconds=wall, measured_steps=f.step_count-old_steps,
                steps_per_second=(f.step_count-old_steps)/wall,
                model_seconds_per_wall_second=(f.time-old_time)/wall, memory=process_memory(),
                physical_parameters=asdict(f.parameters), final=f.diagnostics(),
                includes="solver only, fixed source; no capture, GUI or diagnostic publication")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("numerical", "throughput"), default="numerical")
    parser.add_argument("--grid", type=int, choices=GRID_SIZES, default=256)
    parser.add_argument("--model", choices=tuple(MODEL_LABELS), default="linear")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path; evidence is not overwritten")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    report = dict(utc=datetime.now(timezone.utc).isoformat(), suite=args.suite,
                  python=platform.python_version(), numpy=np.__version__, platform=platform.platform(), seed=None,
                  source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in [*Path("sentio").glob("*.py"), Path("tools/validate_grids.py")]})
    try:
        report["results"] = numerical() if args.suite == "numerical" else throughput(args.grid, args.model)
        report["failure"] = ""
    except Exception as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
    report["wall_seconds"] = time.monotonic()-start
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps(dict(output=str(args.output), failure=report["failure"], wall_seconds=report["wall_seconds"])))
    return int(bool(report["failure"]))


if __name__ == "__main__":
    raise SystemExit(main())
