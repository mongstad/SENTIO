# Issue #6 — independent nonlinear core, integration blocked on #4

## Scope and dependency boundary

The owner explicitly directed this phase to implement and validate only the
independent numerical core while [issue #4](https://github.com/mongstad/SENTIO/issues/4)
remains separate. **This is not completion of issue #6.** Runtime/UI integration
and its final validation must wait until #4 is merged. The PR is a draft handoff,
not a request to merge the partial implementation.

`sentio/sextic.py` supplies an optional `SexticField`, without importing it into
the application. The accepted linear solver, runtime, GUI, capture, CLI,
dependencies, launch defaults, numeric controls, existing tests and historical
research evidence are unchanged from main `97b24cb`. No #4 branch was modified.
The application remains linear; it cannot yet select or restore this new model.

## Numerical implementation

The core retains float64 signed amplitude/aligned velocity, the five-point
Laplacian, fixed edges and the existing quadratic sponge. Exact damping
half-steps surround velocity Verlet, adding the researched local restoring force:

```text
q = u/A
V = ω² A² (q²/2 − q⁴/4 + 0.3q⁶/6)
V' = ω² A (q − q³ + 0.3q⁵)
u_tt = c² Δu − (γ+σ)u_t + κS − V'(u)
```

Defaults for the core are `ω=8, A=.1, c=.3, γ=.4, κ=2`, zero initial state.
No source overwrites the field. The separately named `seed_control()` explicitly
resets to `u=.12 exp(−r²/.15²), v=0, γ=0, κ=0, c=.3, ω=8, A=.1` and resets the
clock/accounting. It is an imposed experimental initial condition, not a
sensory-driven structure. Model units and interpretation follow the
[accepted research](ISSUE_3_NONLINEAR_RESEARCH.md).

Every step respects both wave and potential curvature:

```text
B = 433 ω² >= max |V''(u)| on |u/A| <= 4
h <= min(1/480, 0.8 dx/(sqrt(2)c), 1.6/sqrt(8c²/dx²+B))
```

The envelope ratio is fixed at 4; neither parameter edits nor checkpoints can
raise it. Exceeding `|u|≤4A` rejects the candidate without clipping, replacing
state, advancing time, or updating work/loss. NaN/Inf, magnitude/velocity above
1e6, and an unresolved floating-point clock also reject a step. A future runtime
must catch the numerical exception and pause, rather than retrying indefinitely.

`ω` and `A` must be finite and positive, and the force/energy coefficients must
be representable without overflow or total underflow. A requested configuration
with a computed bound below 1e−6 s is rejected before mutation. This operational
ceiling of one million steps per model second prevents vanishing-step requests;
it is **not a promise of real-time throughput**, nor evidence that all allowed
values are scientifically validated. Reconcile this guard with #4's accepted
runtime policy during integration. Physical `Parameters` still retain the
existing limits until #4 changes them; this phase does not remove those limits.

`configure(...)` accepts physical and nonlinear changes in one atomic operation.
It checks the current state against a new A/envelope, recalculates the step, and
accounts for the instantaneous energy change caused by new c/ω/A. Field arrays
and the simulation clock are preserved. Unsafe changes leave all of them and
the parameters/accounting unchanged. Damping and coupling do not themselves
change the energy function.

Diagnostics split total energy into kinetic, gradient and local potential
components and report signed extrema, the envelope and utilization, CFL, and
the combined wave/curvature number. Input work is `κ dx² ΣS Δu` per held-source
step; damping loss uses the two exact damping substeps. With parameter work J,

```text
balance residual = E − E_reference − input_work − J + damping_loss
```

The residual measures finite integration error, not an exactly conserved energy.
`rebase_energy()` starts a new balance after explicit assignment of valid initial
arrays. Reset/seed actions rebase automatically. Damping arrays are cached by
step/damping to avoid repeated exponentials; integration remains CPU NumPy.

## Core checkpoints

Explicit saves are atomic NPZ files containing only `u`, `v` and scalar metadata.
Schema 2 uses model ID `soft-sextic-verlet-sponge-v1`, explicit physical/nonlinear
parameters, the fixed envelope, clock and energy-accounting state. The loader
checks archive/header bounds before allocation, forbids pickle, validates
arrays/edges/envelope and rejects missing, nonfinite or incompatible metadata.
Successful restore continues the core bit-for-bit in the tested environment.

The legacy `Field.load` continues to handle schema-1 linear checkpoints and
rejects nonlinear files; `SexticField.load` rejects linear files. No application
checkpoint dispatcher or model transition has been added. Save/restore through
the live window is explicitly deferred. Failed saves are tested to leave an
existing checkpoint intact.

## Measurements — 2026-11-03

Fedora 44, Python 3.14.8, NumPy 2.4.3; CPU NumPy only. Both complete test suites
passed: **53 tests, 0 skipped** in 4.969 s normally and 4.837 s with
`PYTHONNOUSERSITE=1`. All 40 pre-existing tests remain unchanged; 13 core tests
cover reference agreement, guards, atomic edits, accounting, continuation and
malformed/failed checkpoints. Compile/import and whitespace checks passed.
The existing suite exercises the unchanged linear runtime and offscreen GUI;
it does not constitute nonlinear application validation.

All ten [long comparisons](evidence/issue-6-core/long.json) reached their specified
duration without a guard stop. Defaults were `ω=8, A=.1, c=.3, h≤1/480`, sponge
on, source held at 30 model Hz. Peaks below are sampled at 0.5 s; guards ran on
every step. The relative balance residual uses the largest sampled absolute
residual divided by `max(initial energy, max |input work|, 1e−30)`.

| N / stimulus | γ / κ | Duration (model s) | Sampled peak | Final energy | Max relative balance residual |
|---|---|---:|---:|---:|---:|
| 65 / sextic seed | 0 / 0 | 120 | 0.15652 | 0.00955281 | 1.22e−4 |
| 129 / sextic seed | 0 / 0 | 120 | 0.15515 | 0.00957710 | 1.23e−4 |
| 256 / sextic seed | 0 / 0 | 120 | 0.15476 | 0.00958616 | 1.22e−4 |
| 129 / massive linear seed control | 0 / 0 | 120 | 0.12 | 0.000160647 | 7.91e−5 |
| 256 / stationary | .4 / 2 | 120 | 0.018586 | 0.000180939 | 4.07e−5 |
| 256 / moving | .4 / 2 | 120 | 0.032456 | 0.00110060 | 1.68e−4 |
| 256 / recurring | .4 / 2 | 120 | 0.020464 | 0.000236820 | 9.46e−5 |
| 256 / cessation at t=5 | .4 / 2 | 120 | 0.018586 | 2.38e−28 | 8.34e−5 |
| 256 / alternating checkerboard | 0 / 20 | 60 | 0.00046577 | 0.00278645 | **0.05019** |
| 256 / uniform | .4 / 20 | 60 | 0.29553 | 0.777213 | 3.87e−4 |

The N=129 sextic final u/v hashes exactly match the accepted issue #3
N=129/h≤1/480 seed run. Energy differs only by summation rounding (relative
2.22e−16). The N=256 seed's mean retention over t=100…120 is 0.71074, and its
mean energy fraction inside radius 0.2 is 0.97018. The massive control retains
0.01258 with core fraction 0.49319. These are identical imposed initial arrays,
with different model energies; they are not equal-energy or sensory-formation
experiments. Cessation demonstrates continued evolution followed by decay.

[Refinement checks](evidence/issue-6-core/checks.json) used unforced seeds without
sponge/damping at t=2. Successive state differences under h, h/2, h/4 reduce by
4.00092. N=64/127/253 at common h=1/1920 gives differences 0.0581513 and
0.0159908, reduction 3.63654; the coarser spatial solutions are still imperfect.
Four-second balance residuals reduce by 3.99981 (unforced) and 4.00000
(stationary forced/damped) on halving h. Coarse relative values are 6.48e−5 and
3.00e−5 respectively. This is consistency evidence in the executed regimes,
not a nonlinear stability theorem for every allowable parameter/source.

The larger checkerboard residual prompted a separate, recorded
[high-frequency follow-up](evidence/issue-6-core/high-frequency.json): four model
seconds at N=256, γ=0, κ=20, with source sign alternating each 1/30 s. At steps
1/480, 1/960 and 1/1920, maximum relative balance residuals were **0.05016,
0.01250 and 0.003129** (reductions 4.012 and 3.995). Final energies were
0.0005099, 0.0008467 and 0.0006614. Thus finite evolution at the default step
does **not** imply phase/response accuracy for forcing at the grid scale; those
final responses are not yet tightly converged. No high-frequency accuracy claim
is made. Finer steps and their runtime cost must remain visible in later review.

[Standalone throughput](evidence/issue-6-core/throughput.json), after 100 warmup
steps and without other issue #6 numerical workers, measured three 1,000-step
windows at N=256: **235.85–246.70 steps/s**, or **0.491–0.514 model seconds per
wall second**. This includes core work/loss accounting and excludes capture,
source conversion, rendering and runtime publication. The host was not isolated
from other applications. It does not certify 480 steps/s or live camera speed;
the future application must report slowdown honestly. No performance rewrite or
GPU path was introduced to hide this limitation.

The four small scalar artifacts retain versions/settings/source hashes and no
frame data. Checks/long runs used immutable core revision `2a2c374`. Subsequent
core edits only strengthened checkpoint metadata validation; an AST comparison
confirmed all other numerical methods unchanged. The later high-frequency
driver was added in response to the measured residual. Each artifact records
the actual source hashes used, rather than attributing every run to a later edit.

## Reproduction

From the repository root, with new output paths to preserve prior evidence:

```bash
python3 -m unittest discover -s tests -p test_sextic.py -v
python3 -m unittest discover -s tests -v
PYTHONNOUSERSITE=1 python3 -m unittest discover -s tests -v
python3 -m tools.validate_sextic_core --suite checks --output runs/issue6-owner/checks.json
python3 -m tools.validate_sextic_core --suite long --workers 3 --output runs/issue6-owner/long.json
python3 -m tools.validate_sextic_core --suite high_frequency --output runs/issue6-owner/high-frequency.json
# Run throughput after the long suite finishes, without other numerical workers.
python3 -m tools.validate_sextic_core --suite throughput --output runs/issue6-owner/throughput.json
```

The deterministic harness records versions, settings, source hashes, actual
duration, stop reasons, signed amplitudes, energy balance and final-state hashes.
It uses the accepted synthetic sources held at 30 model Hz; this is not webcam
acquisition. Core/participation energy metrics follow issue #3. No raw camera
data or binary checkpoints are committed. The long suite uses 120 model seconds
for seeds and nominal full-grid forcing/cessation, 60 seconds for strong uniform
and alternating checkerboard forcing. Wall times depend on CPU/load.

## Required after #4 merges

Rebase this branch onto the owner's merged #4 without replacing its controls.
Then complete these issue #6 requirements in the same issue PR:

1. Model selector and ω/A keyboard controls using #4's Enter-to-apply and
   asynchronous acknowledgement behavior; reconcile parameter/step policies.
2. Explicit model transition: reset, pause and disable coupling with a clear
   owner-visible explanation. Keep linear as the normal fresh-launch default.
3. Runtime exception-to-pause handling, model/parameter logging, nonlinear energy
   and envelope indicators, and explicit seed versus camera presets.
4. Model-aware checkpoint dispatch and live restore/transition tests, preserving
   legacy linear files and current #4 defaults.
5. Full integrated regression and hot-control tests, visible Fedora GUI, actual
   C922 640×480/30-FPS YUYV acquisition, latency/drop/slowdown measurements, and
   an owner protocol for static/moving/recurring input and loss of input at fixed
   visualization scale.

No nonlinear camera FPS, latency, live control, pause, model switching or visible
window result is claimed in this phase. Seeded localization does not establish
spontaneous formation, recognition, learning, memory or indefinite persistence.
