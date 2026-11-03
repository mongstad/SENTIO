"""Resolved central time series for a selected seeded-state mechanism check.

This targeted follow-up asks whether the retained sextic seed oscillates below
the massive linear radiation threshold. It does not infer an infinite lifetime.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .experiments import Case, make_field, provenance


def series(model, duration=120, rate=120):
    case = Case(model, "seed", duration=duration, n=129, damping=0, timestep_factor=.5)
    field = make_field(case)
    center = field.n//2
    values = [float(field.u[center, center])]
    for tick in range(1, round(duration*rate)+1):
        target = tick/rate
        while target-field.time > 1e-12:
            field.step(dt=min(field.dt, target-field.time))
        values.append(float(field.u[center, center]))
    # Last 60 seconds: deterministic mean removal/Hann window for a scalar
    # frequency diagnostic, never applied to field evolution or rendering.
    tail = np.asarray(values[-60*rate:])
    spectrum = np.abs(np.fft.rfft((tail-tail.mean())*np.hanning(len(tail))))**2
    frequency = np.fft.rfftfreq(len(tail), 1/rate)
    index = int(np.argmax(spectrum[1:])+1)
    keep = frequency <= 8
    return dict(model=model, rate=rate, duration=duration, fft_window=[60,120],
                frequency_resolution=rate/len(tail), dominant_frequency=float(frequency[index]),
                linear_threshold=case.omega/(2*np.pi), center=values,
                spectrum_frequency=frequency[keep].tolist(),
                spectrum_power=(spectrum[keep]/max(float(spectrum.max()), 1e-300)).tolist(),
                final_energy=field.energy(), final_peak=float(np.max(np.abs(field.u))),
                final_u_sha256=hashlib.sha256(field.u.tobytes()).hexdigest())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; preserve prior evidence")
    results = []
    for model in ("massive", "sextic"):
        result = series(model)
        results.append(result)
        print(f"{model}: {result['dominant_frequency']:.6f} cycles/s; "
              f"linear threshold {result['linear_threshold']:.6f}", flush=True)
    metadata = provenance()
    metadata["source_sha256"]["research/issue_3/mechanism.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(schema=1, metadata=metadata, results=results), allow_nan=False)+"\n")
