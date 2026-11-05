"""Deterministic issue #4 controls evidence, without camera or display input."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

from sentio.field import Field, Parameters
from sentio.inputs import synthetic_source
from sentio.sextic import SexticField


def advance(field, duration, source, fraction=1):
    target = field.time+duration
    while target-field.time > 1e-12:
        field.step(source, min(field.dt*fraction, target-field.time))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path; existing evidence is preserved")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    runs = []
    for cls in (Field, SexticField):
        for speed in (.001, 3):
            field = cls(256, Parameters(speed, 11, 21))
            source = np.ones_like(field.u)
            began = time.monotonic()
            advance(field, 2, source)
            forced = field.diagnostics()
            advance(field, .5, None)
            assert field.diagnostics()["finite"]
            assert forced["cfl"] <= .8/np.sqrt(2)+1e-14
            runs.append(dict(model=cls.__name__, speed=speed, damping=11, coupling=21,
                             source="uniform +1 for 2 model s, then none for 0.5 model s",
                             wall_seconds=time.monotonic()-began,
                             forced=forced, final=field.diagnostics()))

    # Exact forced, damped eigenmode of the discrete spatial operator: isolates
    # time error at values beyond all three old physical upper bounds.
    errors = []
    for fraction in (1, .5):
        field = Field(65, Parameters(3, 11, 21), sponge=False)
        axis = np.sin(np.pi*np.linspace(0, 1, field.n))
        mode = np.outer(axis, axis)
        field._edge_zero(mode)
        advance(field, .5, mode, fraction)
        frequency = 3*np.sqrt(8)*np.sin(np.pi/(2*64))/field.dx
        damped = np.sqrt(frequency**2-(11/2)**2)
        exact = (21/frequency**2)*(1-np.exp(-11*.5/2)*(
            np.cos(damped*.5)+11/(2*damped)*np.sin(damped*.5)))
        errors.append(float(np.max(np.abs(field.u-exact*mode))))
    assert 3.8 < errors[0]/errors[1] < 4.2

    # Immutable accepted baseline, loaded as a sibling module without modifying
    # the checkout. Compare actual arrays and clocks under identical stimuli.
    baseline_commit = "4bf7a98"
    baseline_source = subprocess.check_output(
        ["git", "show", f"{baseline_commit}:sentio/field.py"])
    baseline_path = args.output.parent/"baseline_field.py"
    baseline_path.write_bytes(baseline_source)
    spec = importlib.util.spec_from_file_location("sentio._issue4_baseline", baseline_path)
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)
    regression = []
    for n in (33, 256):
        old, current = baseline.Field(n), Field(n)
        for step in range(240):
            source = synthetic_source(n, step/240, "moving")
            old.step(source)
            current.step(source)
        np.testing.assert_array_equal(current.u, old.u)
        np.testing.assert_array_equal(current.v, old.v)
        assert current.time == old.time
        regression.append(dict(grid=n, steps=240, arrays_and_clock_bitwise_equal=True))
    report = dict(utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
                  numpy=np.__version__, wall_seconds=time.monotonic()-start,
                  source_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in [*Path("sentio").glob("*.py"), Path("tools/validate_controls.py")]},
                  sustained=runs, damped_mode=dict(grid=65, speed=3, damping=11, coupling=21,
                      duration=.5, fractions=[1, .5], maximum_amplitude_errors=errors,
                      refinement_ratio=errors[0]/errors[1]),
                  baseline=dict(commit=baseline_commit, source_sha256=hashlib.sha256(baseline_source).hexdigest(),
                                runs=regression),
                  limitations="Selected finite-duration controls; no universal accuracy, long-run stability or real-time guarantee.")
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps(dict(report=str(args.output), wall_seconds=report["wall_seconds"],
                          refinement_ratio=errors[0]/errors[1], baseline=regression)))


if __name__ == "__main__":
    main()
