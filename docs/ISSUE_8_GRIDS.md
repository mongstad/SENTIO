# Issue #8 — larger 2D fields and measured CPU limits

2026-11-03 · [Issue #8](https://github.com/mongstad/SENTIO/issues/8)

## Result and scope

SENTIO now supports **256² (default), 512² and 1024²** fields in both Linear and
Soft sextic modes. The physical unit-square domain, camera mode, coupling
definition, float64 integrators and stability criteria are unchanged. Grid size
is selected at launch, displayed in the window and recorded in scalar logs.
The accepted base is `44e1d11160ba40be3f4493798805fe003fec631f`, the owner's merged
PR #7. This work uses the existing dedicated issue #8 branch; it does not depend
on unmerged #6 work or implement #4's numeric-control redesign.

**512² and especially 1024² are slow CPU experiments, not real-time simulation
settings.** The actual C922 GUI was exercised successfully at all three sizes,
including model changes, controls, checkpoints and normal shutdown. A normal
512² camera/sextic window was then opened for owner review. All webcam data stays
transient; only explicit field checkpoints and scalar logs are saved.

The optional **2048² stretch was not run or enabled**: at 1024² the measured
sextic GUI already advanced only about 0.0076 model s/wall s. A larger allocation
alone would not establish practical live performance. CPU throughput, rather
than an observed memory exhaustion, is the reason to stop at 1024². GPU work or
a major solver rewrite should be separately scoped after profiling.

## Implementation and compatibility

Use `--grid 256`, `--grid 512`, or `--grid 1024`; omitting it retains 256².
Restart to change resolution. Switching models keeps the launch grid and follows
the accepted reset/pause/coupling-off policy. The fixed physical sponge width
remains one eighth of the domain. At default c=.3, ω=8:

| Grid | dx | Linear maximum h | Sextic maximum h | u + v storage |
|---|---:|---:|---:|---:|
| 256² | 0.00392157 | 0.00416667 | 0.00208333 | 1 MiB |
| 512² | 0.00195695 | 0.00369005 | 0.00208333 | 4 MiB |
| 1024² | 0.000977517 | 0.00184322 | 0.00181024 | 16 MiB |

The source mapping uses the same separable area average of piecewise-constant
640×480 Y samples at every size. 512² upsamples the 480-row axis; 1024² upsamples
both axes. This supplies more simulation cells, **not more camera measurements**.
Neither interpolation of inferred detail nor automatic contrast is introduced.

Schema-1 linear and schema-2 sextic files already contain N, so their layouts
remain unchanged. Archive/header bounds now accommodate two float64 1024²
arrays plus bounded metadata. Invalid/oversized headers are rejected before
array allocation. The application requires a checkpoint matching its launch
grid and sponge, and rejects mismatches without replacing state. The existing
legacy 256² workflow remains valid. Research/control grids 17…1024 remain
available to the numerical classes, separately from the three launch choices.

The GUI shows grid/dx, model-time rate, process resident and peak resident memory,
and skipped wall time. `/proc/self/status` VmRSS/VmHWM include the whole process,
not just u/v; unavailable measurements are labeled. Peak is cumulative since
launch. Color conversion now builds uint8 RGB channel by channel to avoid large
float64 RGB temporaries. A million-cell test verifies exact equality with the
accepted color formula; all field cells still reach the existing Qt image scaling.
No solver arithmetic or time-step criterion was rewritten for speed.

## Numerical verification

**64 tests passed, zero skipped**, both normally (7.458 s) and with
`PYTHONNOUSERSITE=1` (7.513 s). All previously accepted tests passed. New coverage
includes grid/default bounds, full-size source conversion, fixed edges and
continuing forcing/cessation, capture shape/mode, larger checkpoint continuation,
atomic cross-grid restore rejection and oversized headers. Compile and whitespace
checks passed. A separate [same-input replay](evidence/issue-8/baseline.json)
compared both 256² models with modules loaded from accepted base `44e1d11`:
u/v were bit-for-bit equal after 120 forced steps, with identical clocks and h.

The [deterministic resolution suite](evidence/issue-8/numerical.json) completed
all six model/grid combinations in 59.995 wall seconds. It used model time,
matched physical profiles and no camera/RNG:

- Zero remains zero. A stationary source acts for .08 model s, followed by .08 s
  without input; the existing field continues and remains finite.
- A central Gaussian velocity pulse spreads over .12 s at all sizes; mean squared
  radius of the amplitude profile grows from the initial velocity radius² .00125
  to about .001737 (linear) or .001779 (sextic). Fixed edges remain zero.
- For identical edge-compatible near-boundary pulses at .12 s, sponge/control
  final-to-initial energies are about .377/.999 (linear) and .362/1.000 (sextic).
  Uniform damping alone reduces the ratios to about .786 and .783. This checks
  absorption relative to the same fixed-wall control, not an exact outgoing wall.
- Linear two-pulse superposition errors are at most 6.63e−16. A superposition
  identity is not asserted for nonlinear dynamics.
- A grid-scale checkerboard at c=2, γ=0, κ=20 remains finite through 32 steps at
  every size/model with the enforced CFL/curvature bounds. This is a short stress
  check, not a long-run or high-frequency accuracy certificate.

For a matched `.02 sin(8πx) sin(6πy)` initial amplitude, zero velocity/damping,
no sponge and common h=1/1200 to t=.15, successive state differences reduce by
**4.0156 (linear)** and **4.0161 (sextic)**. States are compared at 129² fixed
physical coordinates using bilinear u and v/8. Linear RMS error against the
continuum mode drops from **4.7064e−6 → 1.1475e−6 → 2.5971e−7**. These results
support better resolution of the selected smooth dynamics; they do not establish
new persistent structures or convergence for arbitrary camera content.

## Measured performance

Fedora 44/kernel 7.2.14, AMD Ryzen 7 5800X, Python 3.14.8, NumPy 2.4.3; CPU only.
Benchmarks ran sequentially, without another issue #8 worker, but the desktop
was not isolated from other applications. Six fresh-process core measurements
use ten warmup steps and approximately three timed seconds with a fixed
synthetic Gaussian source; no capture, Qt or runtime publication is included.

| Core grid/model | Steps/s | Model s/wall s | Resident / peak MiB |
|---|---:|---:|---:|
| 256 linear | 592.27 | 2.468 | 40.5 / 41.7 |
| 256 sextic | 238.98 | 0.498 | 41.1 / 43.5 |
| 512 linear | 128.46 | 0.474 | 56.5 / 60.0 |
| 512 sextic | 52.15 | 0.109 | 54.6 / 65.8 |
| 1024 linear | 27.40 | 0.0505 | 100.6 / 131.7 |
| 1024 sextic | 15.18 | 0.0275 | 124.6 / 155.9 |

The **native Wayland camera GUI** ran for 34.35 / 34.58 / 41.37 wall seconds at
256² / 512² / 1024². Each model phase observes ten wall seconds, excluding its
first three seconds from steady summaries. Sextic appears twice around live
edits and model switching; the table uses the final reset-to-defaults phase.

| GUI grid/model | Camera FPS median | Steps/s median | Model s/wall s median | Qt refresh/s median | RSS median / peak MiB |
|---|---:|---:|---:|---:|---:|
| 256 linear | 29.987 | 239.91 | 0.9996 | 31.27 | 158.0 / 168.2 |
| 256 sextic | 29.987 | 479.98 | 1.0000 | 31.25 | 158.1 / 168.2 |
| 512 linear | 29.989 | 78.47 | 0.2895 | 31.26 | 184.3 / 206.4 |
| 512 sextic | 29.988 | 40.34 | 0.08404 | 31.27 | 188.5 / 210.4 |
| 1024 linear | 30.038 | 7.92 | 0.01461 | 12.51 | 331.6 / 390.5 |
| 1024 sextic | 30.001 | 4.17 | 0.007555 | 12.48 | 326.6 / 403.3 |

Core and GUI use different forcing histories/values and execution conditions;
their rates cannot be subtracted to infer GUI overhead. In particular, the
camera-driven 256² sextic run is faster than the isolated synthetic benchmark.
All values above are measured, not a guaranteed throughput or an enlarged step.
GUI peak is the process high-water mark through each phase, including earlier
models/restore operations; it is not an isolated per-model allocation measure.

All runs negotiated **YUYV 640×480 @30**. Final capture snapshots had
1,013 / 1,022 / 1,217 frames, zero driver drops and zero bad frames. Mailbox
overwrites were **0 / 12 / 939**; capture drain discards **0 / 0 / 19**. At 1024²
the solver consumes far fewer source updates than the camera produces; the
bounded mailbox keeps recent input instead of accumulating latency/history.
Maximum measured GUI command acknowledgements were **45.7 / 96.1 / 644.2 ms**.
At 1024², steady event-loop polling gaps reached about **100 ms**. It remains
operable but is visibly less responsive. Input age and timings are sampled
software measurements, not end-to-end optical/display latency.

Pause while capture continues, typed physical/nonlinear edits, display-only
state preservation, save/reset/restore, uncoupled evolution, model switching
and graceful shutdown all passed. No numerical, capture or runtime errors were
logged. Firmware still read exposure 129 versus requested 156, reported by the
existing warning. Local field/UI window captures were inspected with preview
off; images and binary checkpoints are not committed.

Reports with exact source hashes/settings are in [evidence/issue-8](evidence/issue-8):
`numerical.json`, six `core-GRID-MODEL.json`, three `live-GRID.json`, and the
baseline replay summary. The exploratory 1024² run before the RGB allocation
change is retained locally under ignored `runs/issue8/`, outside the final table.

## Owner use and remaining limits

Close the existing camera window before another launch:

```bash
python3 -m sentio --source camera --model sextic --grid 512
python3 -m sentio --source camera --model sextic --grid 1024
# Omit --model for the accepted linear default; omit --grid for 256².
python3 -m unittest discover -s tests -v
python3 -m tools.validate_grids --output runs/issue8-owner/numerical.json
python3 -m tools.validate_live_gui --grid 512 --output runs/issue8-owner/live-512.json
```

Use fixed camera controls, model parameters and display scale; compare a static
scene at equal **model time** first. Record both clocks when moving the scene:
the camera follows wall time, so grids with different slowdown receive different
forcing histories per model second. Repeat model changes, coupling off and
same-grid checkpoints; see the [experiment protocol](EXPERIMENTS.md#resolution-comparison-issue-8).

These live trials did not demonstrate extra spatial organization from larger
capacity. The controlled numerical mode converged more accurately; upsampled
camera pixels, Qt scaling, different elapsed model times and grid dispersion
remain alternative explanations for visual differences. No automatic selection
of interesting patterns was used. Longer 512²/1024² stability campaigns,
systematic physical scene manipulation and unplug/replug were not performed.
The prior sextic checkerboard accuracy limitation remains; more cells alone do
not remove time-integration error. A separate optimization issue should profile
solver temporaries, publication/rendering and resampling under matched inputs
before choosing acceleration. No GPU, new dependency, 3D or audio work is included.
