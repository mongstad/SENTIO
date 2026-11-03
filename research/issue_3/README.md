# Issue #3 experimental protocol

This directory is isolated research authorized by SENTIO issue #3. It does not
extend the application model registry, CLI, UI, camera, or checkpoint format.
The accepted baseline is commit `46f90e22dcb75b7f8a6db268b22038c882f3277b`.

Before running the matrix, the following comparisons and decision rule were
chosen. A recommendation requires a reproducible nonlinear effect beyond the
matched massive linear control, no numerical failure in the nominal forcing
cases, and persistence of the useful behavior under grid, time-step, and
boundary checks. A long-lived seeded configuration alone does not establish
spontaneous formation under sensory input. If evidence fails these checks,
the result is no justified runtime candidate, not a request to expand scope.

All five models use `u_tt = c² Δu − (γ+σ)u_t + κS − V'(u)` with identical
sources/initial arrays and the accepted fixed wall/quadratic sponge. The two
controls are the actual accepted massless linear solver (`V=0`) and a massive
linear solver (`V=ω²u²/2`). Nonlinear models are:

```text
q = u/A
quartic:    V = ω² A² (q²/2 + q⁴/4)
sextic:     V = ω² A² (q²/2 − q⁴/4 + 0.3 q⁶/6)
sine-Gordon V = ω² A² (1 − cos q)
```

Defaults: `c=.3`, `κ=2`, `ω=8`, `A=.1`, unit-square domain, N=65 for
screening, and the accepted maximum step of 1/240. Research steps additionally
satisfy `h sqrt(8c²/dx² + B) ≤ 1.6`, where `B` bounds `|V''|`. For polynomial
models the declared envelope is `|q|≤4`, with bounds `ω²(1+3Q²)` and
`ω²(1+3Q²+1.5Q⁴)` respectively. Excursions stop the run without clipping or
replacing the previous state. Massive/sine-Gordon curvature bounds are global.
No theorem of nonlinear stability is claimed; explicit refinement and energy
balance measurements check the executed regimes. The existing 1e6 magnitude
guard is retained. No production parameter ranges are widened.

Synthetic sources reuse `sentio.inputs.synthetic_source`, held at 30 samples
per model second, with integration steps aligned to source changes. The
cessation case removes stationary input exactly at t=5. The impulse starts
with `v=ωA exp(−r²/.06²), u=0`. The seed starts with
`u=1.2A exp(−r²/.15²), v=0`; this explicitly imposed seed is not a spontaneously
generated object. All seeds are centered, edge-zeroed, and identical across
models. No random generator or webcam is used.

Suites, selected before inspecting their results:

| Suite | Matched cases |
|---|---|
| `screen` | Five models × zero, impulse, seed, stationary, moving, viewpoint, recurring, cessation; γ=.4; 40 s |
| `long` | Five models × seed, impulse, resonant forcing; γ=.02; 120 s |
| `stress` | Five models, uniform source with κ=20 and γ=.4; 40 s |
| `robustness` | All models' weakly damped seeds at N=129, plus L=2/N=129 at the same dx as L=1/N=65; massive/sextic/sine-Gordon also half-step N=129 and sponge-free N=65; 120 s |
| `parameters` | Sextic seed: one-factor ω=6/10, A=.075/.15, seed ratio=.8/1.6, width=.12/.18; γ=.02; 60 s |
| `full_grid` | Five models, cessation, accepted N=256; 10 s |

Resonant forcing uses the first fixed-wall sine mode, driven at
`sqrt(ω²+2(πc/L)²)`, the continuum massive-control frequency. It is a declared
stress/control signal, not a claim about typical camera spectra. At most four
local numerical worker processes run per command; these are ordinary
deterministic computations. No GPU or new runtime dependency is required.

Run from the repository root, using new paths so prior evidence is preserved:

```bash
python3 -m unittest discover -s tests -p test_issue3_research.py -v
python3 -m research.issue_3.experiments --suite screen --workers 4 --output runs/issue3/screen.json
python3 -m research.issue_3.experiments --suite long --workers 4 --output runs/issue3/long.json
python3 -m research.issue_3.experiments --suite stress --workers 4 --output runs/issue3/stress.json
python3 -m research.issue_3.experiments --suite robustness --workers 4 --output runs/issue3/robustness.json
python3 -m research.issue_3.experiments --suite parameters --workers 4 --output runs/issue3/parameters.json
python3 -m research.issue_3.experiments --suite full_grid --workers 4 --output runs/issue3/full-grid.json
python3 -m research.issue_3.checks --output runs/issue3/checks.json
python3 -m research.issue_3.followup --workers 4 --output runs/issue3/followup.json
python3 -m research.issue_3.mechanism --output runs/issue3/mechanism.json
python3 -m research.issue_3.report_artifacts --input runs/issue3 --output runs/issue3-review
```

The last two numerical commands are explicitly **follow-up** experiments, added
after inspecting the first matrix. Uniform damping erased the late localization,
so `followup` removes it while retaining the sponge and repeats grid/domain
controls (17 runs, 120 s each). It also refines the underresolved sextic N=33
spatial check to N=64/127/253. `mechanism` compares the massive and sextic center
time series at N=129, h≤1/480, sampling at 120 Hz for a frequency diagnostic.
Neither changes the initial seed or searches for a more favorable shape.

`report_artifacts` needs all nine JSON files with the names shown above. For the
two static SVG figures, add `--figures`; this alone needs optional Matplotlib
(exercised 3.10.8), not a new application dependency. On Fedora it can be installed
with `sudo dnf install python3-matplotlib`. Use a writable `MPLCONFIGDIR` if the
default cache is unavailable. Scripts refuse to overwrite existing evidence;
use a new run directory throughout for repetition. Run from the checkout:
research is deliberately excluded from the installed application package.

Raw local output is scalar-only JSON under ignored `runs/`, including source
hashes, settings, versions, stop/fault outcomes, and final-state hashes.
Plots/compact summaries intended for review are explicitly bounded artifacts.
The linear baseline and existing evidence must remain unchanged.

See the [report](../../docs/ISSUE_3_NONLINEAR_RESEARCH.md) for measured results,
the distinction between a bounded implementation domain and tested settings,
and exact owner checks. Wall times and UTC stamps vary on repetition; compare
settings, diagnostics, and state hashes within the same numerical environment.
