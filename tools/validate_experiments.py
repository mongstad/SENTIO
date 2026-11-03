"""Deterministic numerical measurements, independent of camera and wall speed.

Run from the checkout: python3 -m tools.validate_experiments --output PATH
Only scalar evidence is written, never field arrays or camera frames.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import time

import numpy as np

from sentio.field import Field, Parameters
from sentio.inputs import SYNTHETIC_MODES, synthetic_source


def evolve(field, duration, source=None):
    target = field.time + duration
    while target-field.time > 1e-12:
        field.step(source, min(field.dt, target-field.time))


def run():
    start = time.monotonic()
    report = dict(utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
                  numpy=np.__version__, platform=platform.platform(), seed=None,
                  initial_state="zero except explicitly described mode/pulse tests", experiments={})
    for mode in SYNTHETIC_MODES:
        field = Field()
        next_frame = next_sample = 0
        source = None
        history = []
        while field.time < 8-1e-12:
            if field.time + 1e-12 >= next_frame:
                source = synthetic_source(256, next_frame, mode)
                next_frame += 1/30
            field.step(source, min(field.dt, 8-field.time))
            if field.time + 1e-12 >= next_sample:
                history.append(field.diagnostics())
                next_sample += 1
        report["experiments"][mode] = dict(n=256, parameters=asdict(field.parameters),
                                                 source_rate=30, history=history)
    errors = []
    for n in (33, 65, 129):
        field = Field(n, Parameters(damping=0), sponge=False)
        s = np.sin(np.pi*np.linspace(0, 1, n))
        mode = np.outer(s, s)
        field.u[:] = mode
        field._edge_zero(field.u)
        evolve(field, .7)
        exact = mode*np.cos(np.sqrt(2)*np.pi*.3*.7)
        errors.append(dict(n=n, rms_error=float(np.sqrt(np.mean((field.u-exact)**2)))))
    report["mode_resolution"] = errors
    energies = []
    for sponge in (False, True):
        field = Field(65, Parameters(damping=0), sponge=sponge)
        x, y = np.meshgrid(np.linspace(0, 1, 65), np.linspace(0, 1, 65))
        field.u[:] = np.exp(-((x-.5)**2+(y-.5)**2)/.003)
        field._edge_zero(field.u)
        initial = field.diagnostics()["energy"]
        evolve(field, 5)
        energies.append(dict(sponge=sponge, initial_energy=initial, final_energy=field.diagnostics()["energy"]))
    report["boundary_control"] = energies
    report["sponge_to_reflecting_energy_ratio_at_5s"] = energies[1]["final_energy"]/energies[0]["final_energy"]
    report["slow_speed_long_forcing"] = []
    for damping in (0, 10):
        field = Field(33, Parameters(.01, damping, 20))
        evolve(field, 600, np.ones((33, 33)))
        report["slow_speed_long_forcing"].append(dict(n=33, parameters=asdict(field.parameters),
                                                     duration=600, diagnostics=field.diagnostics()))
    report["high_speed_full_grid"] = []
    for damping in (0, 10):
        field = Field(256, Parameters(2, damping, 20))
        # Includes the highest spatial frequencies, not only a smooth source.
        source = (2*(np.indices((256, 256)).sum(axis=0) % 2)-1).astype(float)
        field.u[:] = source * .01
        field._edge_zero(field.u)
        evolve(field, 5, source)
        report["high_speed_full_grid"].append(dict(parameters=asdict(field.parameters), diagnostics=field.diagnostics()))
    report["wall_seconds"] = time.monotonic()-start
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run()
    Path(args.output).write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"wall_seconds": report["wall_seconds"], "boundary_ratio": report["sponge_to_reflecting_energy_ratio_at_5s"],
                      "mode_resolution": report["mode_resolution"]}, indent=2))
