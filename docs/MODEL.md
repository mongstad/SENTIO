# Prototype 1 model and implementation

## Dynamics and units

The domain is the dimensionless unit square, with 256×256 nodes including fixed outer-edge nodes. Grid spacing is `dx = 1/(N-1)`. Amplitude `u` and aligned-time velocity `v = du/dt` are float64 arrays initialized to zero. Simulation time is measured in model seconds, not camera exposures.

The linear forced wave equation is:

```text
u_t = v
v_t = c² Δu − (γ + σ(x,y)) v + κ S(x,y,t)
u = v = 0 on the outer edge
```

`Δ` is the five-point finite-difference Laplacian. Supported live ranges are `c ∈ [0.01,2]`, `γ ∈ [0,10]`, and `κ ∈ [0,20]`. Speed is domain lengths per model second; damping has inverse-model-second units; coupling multiplies the normalized input as acceleration. No nonlinear, learned, adaptive, recognition, or feedback term is present.

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

Unsupported, nonfinite, or out-of-range controls are rejected. Source arrays must be finite, grid-shaped, and in `[-1,1]`. Each candidate step is checked for NaN/Inf and a `1e6` magnitude/velocity guard before replacing the previous state. A fault pauses the field and is logged; resetting or restoring valid state is required before resuming. This guard is an operational safeguard, not proof of physical validity. Slow propagation with strong sustained forcing can produce large finite amplitudes; display saturation is reported separately.

## Luminance and coupling

V4L2 is required to negotiate progressive YUYV 640×480 at 30 FPS; another format, size, or nominal rate raises an explicit error. Row padding is honored. `Y0 U Y1 V` supplies the even bytes as luminance. Chroma is discarded.

The full rectangle is resampled to the square grid by separable area averaging of piecewise-constant pixels. This stretches camera aspect ratio to the square domain and is not a spatial calibration. The source is `S = area_average(Y/127.5 − 1)`. It uses fixed 8-bit code-value scaling, without gamma inversion, inferred radiance, per-frame mean removal, contrast normalization, or optical-phase interpretation. Camera processing and possible limited-range Y remain properties of the measurement. Color-space metadata is logged but does not trigger an undocumented rescaling.

Every incoming source contributes acceleration to the existing state. It never writes the amplitude or velocity arrays. Between frames the most recent fresh source is held. At an age above 250 ms, or on capture failure, the source becomes zero while the field continues. Disabling coupling also sets forcing to zero without clearing the field. Constant brightness can drive a DC response; recurring patterns may reflect forcing, ringing, and boundaries. No frame history or artificial memory is implemented.

## Timing and capture lifecycle

Three independent schedules are measured:

- A capture thread owns the V4L2 descriptor and three requested MMAP buffers (bounded to at most eight if the driver adjusts the count). It drains available buffers and publishes the newest frame into a one-element mailbox. Driver sequence gaps, corrupted frames, drain discards, and overwritten mailbox frames have distinct counters. Preview and source are transient arrays.
- A simulation thread targets one model second per wall second, choosing stable time steps independently of capture. It caps catch-up debt at 50 ms and reports skipped wall time under load, rather than increasing the numerical step. At expensive settings, simulation time can advance slower than wall time.
- Qt polls the most recent field snapshot at roughly 30 Hz. Field snapshots, command queue (128 entries), capture mailbox, and energy history (600 scalar samples) are bounded. Pending controls wait for a simulation acknowledgement so stale snapshots cannot undo user changes.

Acquisition uses driver monotonic timestamps when supplied. Receipt-time fallback is visibly labeled because original frame age is then unknown. A two-second valid-frame timeout ends capture with an error; stale forcing has already expired after 250 ms. The field remains available. Reconnection requires restarting the application; automatic recovery is deferred.

The application requests manual exposure, disables exposure-dependent frame-rate changes, fixes autofocus and white balance where supported, and reports unsupported controls. Exposure defaults to 156 units of 100 μs and can be set with `--exposure` (1–300). Firmware may adjust it after stream start: effective controls are read every second and changes logged. Other supported imaging controls are read and recorded, not silently retuned. Normal shutdown/failed initialization restores altered controls in reverse order when the device remains reachable. Unplugging, power loss, and forced process termination can prevent restoration.

## Diagnostics, logs, and checkpoints

The discrete wave-energy diagnostic is

```text
E = (dx²/2) Σ v² + (c²/2)[Σ (u[i+1,j]−u[i,j])² + Σ (u[i,j+1]−u[i,j])²].
```

The gradient term uses all horizontal/vertical edges, including those incident to the fixed boundary. This approximates the wave energy at the current aligned state. It is **not conserved** with forcing/damping, finite integration error, or speed changes. In the continuum, its rate is the input work minus damping loss. It is not the reference script's amplitude-squared proxy.

Every control event records UTC, monotonic time, simulation step/time, and effective physical parameters; resets/restores increment an epoch. Diagnostics are sampled around once per wall second and include acquisition rate, simulation rate, energy components, amplitude, velocity, finiteness, and frame counters. Render FPS is measured independently in the UI. Logs record source, zero initial state/no RNG seed, runtime versions, negotiated mode, and camera controls. No images, luminance arrays, or source arrays are serialized.

Explicit schema-1 NPZ checkpoints contain only `u`, `v`, and JSON metadata (model, grid, parameters, sponge, step/time). Saving uses an atomic same-directory replacement. Loading disables pickle and validates archive size, member headers, model/schema, shape, dtype, finiteness, bounds, and fixed edges before replacing state. Checkpoints resume paused with coupling disabled. Display settings and input schedule remain session settings; consult the scalar log. Exact continuation is tested for a reproduced deterministic source, not for unrecorded webcam input.

## Modules and external interfaces

`field.py` owns numerics/checkpoints; `inputs.py` owns source conversion and test stimuli; `camera.py` owns the Linux capture ABI; `runtime.py` owns threads/control/logging; `gui.py` owns visualization; `__main__.py` owns CLI startup. NumPy and PySide6 are the only Python runtime dependencies. No GPU, proprietary runtime, OpenCV conversion, external service, or network upload is required.

The V4L2 implementation follows the installed `linux/videodev2.h`; a compiled test compares ctypes sizes and ioctl request numbers with that header. The [kernel buffer API](https://docs.kernel.org/userspace-api/media/v4l/vidioc-qbuf.html) defines queue ownership, error flags, and sequence metadata. Rendering copies NumPy RGB bytes into a [Qt QImage](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QImage.html) before presenting them, keeping camera and field images separate.
