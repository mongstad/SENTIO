# SENTIO models and implementation

Linear remains the accepted default described below. Issue #6 adds an optional
soft-sextic model (`--model sextic`) using the [documented potential, guards and
energy balance](ISSUE_6_CORE.md). [Live integration](ISSUE_6_LIVE.md) documents
its controls, model transitions, checkpoint dispatch and measured performance.
The owner's PR #7 update authorizes this scoped nonlinear extension and minimal
controls before issue #4; the linear integrator and capture format are unchanged.

Issue #11 adds [optional event-counted local damping](ISSUE_11_REPETITION.md) to
both models, default OFF. It introduces an explicit second state m, detector
timers/latches, bounded event gains and exponential forgetting. The equations and
integration below describe the accepted OFF path; the linked guide specifies the
enabled damping, sampling bounds, schema-3 state and measured limitations.

## Dynamics and units

The domain is the dimensionless unit square, with N×N nodes including fixed outer-edge nodes. N defaults to 256; `--grid 512` and `--grid 1024` are also supported. Resolution is fixed for a session, requiring a restart to change. Grid spacing is `dx = 1/(N-1)`; the physical domain and sponge thickness remain unchanged across resolutions. Amplitude `u` and aligned-time velocity `v = du/dt` are float64 arrays initialized to zero. Simulation time is measured in model seconds, not camera exposures.

The linear forced wave equation is:

```text
u_t = v
v_t = c² Δu − (γ + σ(x,y)) v + κ S(x,y,t)
u = v = 0 on the outer edge
```

`Δ` is the five-point finite-difference Laplacian. Live physical domains are finite
`c > 0`, `γ ≥ 0`, and `κ ≥ 0`, subject to float64 representation and the step/state
safeguards below. `c²` must be finite and nonzero. Nonnegative input gain preserves
the accepted model's gain convention; the source itself supplies signed forcing.
Speed is domain lengths per model second; damping has inverse-model-second units;
coupling multiplies the normalized input as acceleration. With reinforcement OFF, the linear model has no
nonlinear, learned, adaptive, recognition, or feedback term.

The absorbing layer is a **sponge**, not an exact nonreflecting boundary. With `d` the distance in grid cells to the nearest edge and `w = 0.125(N−1)`, `σ = 40 max(0,1−d/w)²`. Waves are damped across the outer eighth of the domain before reaching the fixed wall. Some reflection and boundary resonances remain, especially at other speeds, frequencies, and incidence angles. The sponge-free fixed-wall model exists only for numerical control tests; the application and its checkpoints require the sponge.

## Integration and safeguards

For one step of size `h`, hold the source fixed and use exact damping around velocity Verlet:

```text
D     = exp(−(γ+σ)h/2)
vhalf = D v + (h/2)(c² Δu + κ S)
unew  = u + h vhalf
vnew  = D [vhalf + (h/2)(c² Δunew + κ S)]
```

Outer-edge values are forced to zero after each candidate update. The undamped 2D wave stability criterion is `c h/dx ≤ 1/√2`. Every step uses `h = min(1/240, 0.8 dx/(√2 c))`; smaller final steps are permitted in deterministic experiments. Thus the displayed CFL number never exceeds `0.8/√2 ≈ 0.565685`. Exact nonnegative damping does not impose an explicit damping-step restriction. Hot speed changes recompute the stable step without changing `u` or `v`.

The old experimental parameter caps are removed. Both models reject a required
step below **1e-6 model s** before committing a configuration, including constructor
and checkpoint parameters. This extends sextic's existing operational ceiling of
one million steps/model second to linear; it is not a throughput promise or an
accuracy bound. More demanding accepted settings reduce the measured model-time
rate; the runtime processes commands between individual steps and never attempts
an unbounded catch-up batch. The GUI reports slowdown explicitly.

Unsupported, nonfinite, unrepresentable or infeasible controls are rejected without
changing the field or effective settings. Source arrays must be finite, grid-shaped,
and in `[-1,1]`. Each candidate step is checked for NaN/Inf, a `1e6` magnitude/velocity
guard and a representable advance of the model clock before replacing the previous
state. A fault pauses the field and is logged; resetting or restoring valid state
is required before resuming. Extreme finite gain may be accepted as a parameter
but trigger this atomic step rejection under forcing. These guards are operational
safeguards, not proof of physical validity. Slow propagation with strong sustained
forcing can produce large finite amplitudes; display saturation is reported separately.
Exact damping remains stable at very large γ, but splitting accuracy for strongly
forced/overdamped dynamics still requires time-step refinement; finite output alone
does not establish accuracy. See [control domains and evidence](ISSUE_4_CONTROLS.md).

Grid changes do not loosen these limits. At c=.3, linear h is approximately
0.00416667, 0.00369005, 0.00184322 at N=256/512/1024; sextic additionally limits
h to 1/480 and the potential-curvature criterion, giving approximately
0.00208333, 0.00208333, 0.00181024 for ω=8. The same model second can therefore
require more steps, each over more cells. See [grid validation](ISSUE_8_GRIDS.md).

## Luminance and coupling

V4L2 is required to negotiate progressive YUYV 640×480 at 30 FPS; another format, size, or nominal rate raises an explicit error. Row padding is honored. `Y0 U Y1 V` supplies the even bytes as luminance. Chroma is discarded.

The full rectangle is resampled to the square grid by separable area averaging of piecewise-constant pixels. This stretches camera aspect ratio to the square domain and is not a spatial calibration. The source is `S = area_average(Y/127.5 − 1)`. It uses fixed 8-bit code-value scaling, without gamma inversion, inferred radiance, per-frame mean removal, contrast normalization, or optical-phase interpretation. Camera processing and possible limited-range Y remain properties of the measurement. Color-space metadata is logged but does not trigger an undocumented rescaling.

This identical mapping is used at every field size. 512² upsamples the camera's
480-row axis while reducing its 640-column axis; 1024² upsamples both axes.
Each output cell averages its overlap with the same piecewise-constant camera
pixels. It can expose pixel boundaries more sharply but adds no measured camera
detail. It does not interpolate an inferred high-resolution image. Sources are
still held in a one-element mailbox, with no recording or frame-history buffer.

Every incoming source contributes acceleration to the existing state. It never writes the amplitude or velocity arrays. Between frames the most recent fresh source is held. At an age above 250 ms, or on capture failure, the source becomes zero while the field continues. Disabling coupling also sets forcing to zero without clearing the field. Constant brightness can drive a DC response; recurring patterns may reflect forcing, ringing, and boundaries. No frame history is stored. Optional reinforcement observes the simulated wave, not source frames; its explicit history is absent by default.

## Timing and capture lifecycle

Three independent schedules are measured:

- A capture thread owns the V4L2 descriptor and three requested MMAP buffers (bounded to at most eight if the driver adjusts the count). It drains available buffers and publishes the newest frame into a one-element mailbox. Driver sequence gaps, corrupted frames, drain discards, and overwritten mailbox frames have distinct counters. Preview and source are transient arrays.
- A simulation thread targets one model second per wall second, choosing stable time steps independently of capture. It caps catch-up debt at 50 ms and reports skipped wall time under load, rather than increasing the numerical step. At expensive settings, simulation time can advance slower than wall time.
- Qt polls the most recent field snapshot at roughly 30 Hz. Field snapshots, command queue (128 entries), capture mailbox, and energy history (600 scalar samples) are bounded. Numeric drafts are separate from effective values. Enter submits a revision; the latest result per numeric key survives unrelated commands, and an acknowledgement never overwrites a newer draft. Focus loss, reset, restore and model transitions preserve unapplied drafts. Escape discards them. Physical and display-only controls are labeled separately.

All fresh sessions use `c=.3, γ=.4, κ=2`, display range ±2, intensity 1, coupling on
and running integration. No previous-session settings are loaded. Explicit model
and grid CLI choices retain those recommendations; model transitions, seed controls
and checkpoint restore keep their separately documented paused/uncoupled behavior.
Display range `R` and intensity `I` must both be finite and positive, with finite,
positive `R/I`. Rendering clips signed amplitude to ±`R/I` before division, avoiding
intermediate overflow/underflow from `u*I/R`. No display control mutates `u` or `v`.

Acquisition uses driver monotonic timestamps when supplied. Receipt-time fallback is visibly labeled because original frame age is then unknown. A two-second valid-frame timeout ends capture with an error; stale forcing has already expired after 250 ms. The field remains available. Reconnection requires restarting the application; automatic recovery is deferred.

The application requests manual exposure, disables exposure-dependent frame-rate changes, fixes autofocus and white balance where supported, and reports unsupported controls. Exposure defaults to 156 units of 100 μs and can be set with `--exposure` (1–300). Firmware may adjust it after stream start: effective controls are read every second and changes logged. Other supported imaging controls are read and recorded, not silently retuned. Normal shutdown/failed initialization restores altered controls in reverse order when the device remains reachable. Unplugging, power loss, and forced process termination can prevent restoration.

## Diagnostics, logs, and checkpoints

The discrete wave-energy diagnostic is

```text
E = (dx²/2) Σ v² + (c²/2)[Σ (u[i+1,j]−u[i,j])² + Σ (u[i,j+1]−u[i,j])²].
```

The gradient term uses all horizontal/vertical edges, including those incident to the fixed boundary. This approximates the wave energy at the current aligned state. It is **not conserved** with forcing/damping, finite integration error, or speed changes. In the continuum, its rate is the input work minus damping loss. It is not the reference script's amplitude-squared proxy.

Every control event records UTC, monotonic time, simulation step/time, and effective physical parameters; resets/restores increment an epoch. Diagnostics are sampled around once per wall second and include acquisition rate, simulation rate, energy components, amplitude, velocity, finiteness, and frame counters. Render FPS is measured independently in the UI. Logs record source, zero initial state/no RNG seed, runtime versions, negotiated mode, and camera controls. No images, luminance arrays, or source arrays are serialized.

Grid, dx and fixed domain length are included in scalar events/diagnostics.
Linux `/proc/self/status` supplies process resident memory (VmRSS) and peak
resident memory (VmHWM), sampled about once per second. These include NumPy,
Qt, acquisition and transient allocations; they are not merely the u/v array
size. Peak is cumulative since process launch. Missing OS measurements are
reported unavailable. Display colors still use every field cell; channel-wise
conversion avoids full-grid float64 RGB temporaries without changing colors.

Explicit schema-1 NPZ checkpoints contain only `u`, `v`, and JSON metadata (model, grid, parameters, sponge, step/time). Saving uses an atomic same-directory replacement. Loading disables pickle and validates archive size, member headers, model/schema, shape, dtype, finiteness, bounds, and fixed edges before replacing state. Checkpoints resume paused with coupling disabled. Display settings and input schedule remain session settings; consult the scalar log. Exact continuation is tested for a reproduced deterministic source, not for unrecorded webcam input.

Schema 1 (linear) and schema 2 (sextic) already encode N; their layouts remain
compatible. Bounded loaders now accept core grids from 17 through 1024 and at
most `2*1024²*8 + 32768` uncompressed bytes, validating array dimensions before
allocation. The application requires its launch grid and the sponge. A restore
from a different grid is rejected atomically with a restart instruction, even
when its model is otherwise supported; fields are never resized on restore.

## Modules and external interfaces

`field.py` owns linear numerics/checkpoints; `sextic.py` owns nonlinear numerics/checkpoints; `models.py` owns the small model registry and validated checkpoint dispatch. `inputs.py` owns source conversion and test stimuli; `camera.py` owns the Linux capture ABI; `runtime.py` owns threads/control/logging; `gui.py` owns visualization; `__main__.py` owns CLI startup. NumPy and PySide6 are the only Python runtime dependencies. No GPU, proprietary runtime, OpenCV conversion, external service, or network upload is required.

The V4L2 implementation follows the installed `linux/videodev2.h`; a compiled test compares ctypes sizes and ioctl request numbers with that header. The [kernel buffer API](https://docs.kernel.org/userspace-api/media/v4l/vidioc-qbuf.html) defines queue ownership, error flags, and sequence metadata. Rendering copies NumPy RGB bytes into a [Qt QImage](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QImage.html) before presenting them, keeping camera and field images separate.
