# SENTIO

**SENTIO** is an experimental, continuously evolving sensory-field system. Its first goal is to observe what happens when a two-dimensional scalar field receives a live stream of camera measurements and evolves under explicitly defined wave dynamics.

The experiment asks whether interference and continuing field evolution produce recurring, persistent, or otherwise interesting structure over time. **A recognizable image, a neural network, memory, learning, or consciousness is not an assumed outcome.**

## Current status

**Prototype 1 accepted in PR #2.** The separate `sentio` Python application couples live C922 luminance to a continuing linear 2D field. Synthetic numerical tests and a sustained live-camera run have been performed; see [validation and limitations](docs/VALIDATION.md). No recognition or learning claim is made.

[Issue #3 research](docs/ISSUE_3_NONLINEAR_RESEARCH.md) compares three isolated nonlinear potentials with the accepted solver and a massive linear control. A soft sextic potential supports a localized, explicitly seeded oscillation in the tested regime. This does not establish sensory-driven formation or learning.

**Issue #6 adds an optional live soft-sextic mode**, with model selection, ω/A controls, safety diagnostics and model-aware checkpoints. Linear remains the default. The owner authorized minimal GUI integration before #4; its broader numeric-control redesign remains separate. See the [live application guide and validation](docs/ISSUE_6_LIVE.md) and preserved [core numerical evidence](docs/ISSUE_6_CORE.md).

**Issue #8 adds launch-selectable 256², 512² and 1024² fields** on the same unit-square domain. The default remains 256². Larger grids can advance much slower than wall time on the CPU; camera resolution remains 640×480. See [grid measurements and limitations](docs/ISSUE_8_GRIDS.md).

### Run on Fedora 44

From this checkout, install the open-source CPU/Qt dependencies and first run the synthetic control:

```bash
sudo dnf install python3 python3-pip python3-numpy python3-pyside6 v4l-utils
python3 -m unittest discover -s tests -v
python3 -m sentio --source stationary
```

Then close the synthetic window and enable the camera explicitly:

```bash
python3 -m sentio --list-devices
python3 -m sentio --source camera
# Optional experimental model, same live C922 acquisition:
python3 -m sentio --source camera --model sextic
```

Choose a field resolution at launch, with one camera window at a time:

```bash
python3 -m sentio --source camera --model sextic --grid 512
python3 -m sentio --source camera --model sextic --grid 1024
```

Close and restart to change grid size; model switching retains the selected grid.
Restore requires a checkpoint from the same grid size, and reports the required
launch size otherwise. Grid size, actual model-time rate, process resident/peak
memory and skipped wall time are shown in the window. At a large grid, a smoothly
refreshing window does not imply the field is advancing at real time.

The application discovers a unique C922 capture node, preferring `/dev/v4l/by-id/`. With multiple cameras, pass the selected persistent path using `--device /dev/v4l/by-id/...`. `/dev/video0` remains usable as an explicit, temporary selection. Run as your desktop user with camera access, not as root. Close other applications using the camera. The Codex sandbox may hide video devices; launch from a normal desktop terminal in that case.

For a virtual environment using the exact exercised Python package versions:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-tested.txt
python -m pip install --no-deps -e .
sentio --source camera
```

The field uses blue for negative values, dark gray for zero, and orange for positive values. **Display range** and **Display intensity** change only the color mapping; the legend shows the effective clipping threshold and clipped fraction. Linear defaults to ±2 for camera input and ±0.2 for synthetic input; sextic starts at a fixed ±0.05. Use **Enable input coupling** for a no-input control without clearing the field. **Pause** freezes integration while acquisition continues; **Reset** zeros amplitude, velocity, simulation time, and step, retaining settings. The optional camera preview is separately labeled and disabled initially.

Changing the model resets the field and model parameters, pauses, and disables input coupling; explicitly enable coupling and uncheck Pause to continue. The display scale is retained for comparisons. Type ω/A and press Enter to apply; rejected settings leave the solver unchanged. The experimental validity envelope `|u|≤4A` is separate from display saturation. The **explicit Gaussian seed** button is a control experiment with γ=κ=0, paused and uncoupled; it is not camera-generated structure.

Use **Save state** explicitly to save amplitude, velocity, model settings, and simulation clock. **Restore** validates the checkpoint and opens it paused with coupling off; enable coupling and resume when ready. No frame history is saved, and restoring cannot reproduce unrecorded camera stimuli. Normal window close stops acquisition and attempts to restore changed camera controls.

Scalar-only JSONL logs are written under ignored `runs/`; checkpoints are also ignored by Git. Camera frames stay in memory. [Model and implementation](docs/MODEL.md), [experiments](docs/EXPERIMENTS.md), and [reference review](docs/REFERENCE_REVIEW.md) describe the assumptions and reproduction procedure.

### Hardware baseline

- **Host:** Fedora Linux 44, NVIDIA RTX 3070 Ti (8 GB VRAM)
- **Camera:** Logitech C922 Pro Stream, V4L2 device observed at `/dev/video0` (device numbering may change)
- **Verified capture:** 640 × 480, 30 FPS, uncompressed **YUYV** through V4L2
- **Observed camera behavior:** Auto-exposure with dynamic frame rate reduced measured capture speed; manually setting exposure and disabling dynamic frame-rate adjustment sustained 30 FPS
- **Data limitation:** YUYV is uncompressed *processed* video, not raw Bayer samples or a measurement of optical phase/wavelength

## Prototype 1: live 2D sensory field

1. Acquire frames continuously from the C922; use the luminance (Y) samples as a spatially arranged sensor signal.
2. Resample the input consistently to an initially **256 × 256** scalar-field grid.
3. Couple incoming measurements to an *already evolving* field. **Do not clear or replace the field state on each new frame.**
4. Evolve the field between camera frames using a documented, numerically checked 2D wave model, initially linear, with configurable propagation, damping, coupling, and sensible boundaries.
5. Display the **actual signed field state** in real time. An optional camera preview is for capture diagnostics only.
6. Monitor field energy, peak amplitude, measured camera FPS, simulation performance, numerical stability, and live parameter changes.
7. Save field-state checkpoints and concise experiment parameters/diagnostics when requested; do **not** continuously archive webcam footage.

The field is a *simulation driven by camera measurements*, not a reconstruction of the original optical wavefront. We will test the resulting dynamics without prescribing what structures should appear.

### Live controls

Wave speed, damping, camera coupling, visualization range/intensity, pause/resume, field reset, and camera-coupling on/off. Changes to numerical parameters must be bounded to preserve integrator stability and must be logged alongside simulation time/step.

### Initial validation

Use reproducible synthetic inputs **before** enabling the camera. Verify propagation, superposition, damping, boundary behavior, finite values, timing, and controlled camera-stream integration. Compare outputs against no-input and reset controls. Distinguish meaningful field dynamics from visualization artifacts and numerical instability. A visually striking pattern by itself is not evidence of learning or recognition.

**Prototype 1 succeeds** when a live camera stream reliably influences a stable, observable 2D field and the user can adjust parameters during execution. The emergence of recognizable structure is an open experimental outcome, not a release gate.

## Later experiments (not prototype 1)

- Coupling the evolving 2D sensory field to a **3D scalar-field volume**
- Testing nonlinear and alternative wave dynamics, resolution scaling, and long-running field histories
- Audio input and additional sensory channels
- Possible Wavez visualization/integration
- Field-based information processing hypotheses, evaluated only after the basic dynamics are measured

## Historical reference

Earlier Python experiments in the user's `Neural_Network` archive include `VB_HolographicTorus_v1_0.py` and `VB_BlackHoleHorizon_v1_0.py` (implemented with Claude). They explore 2D boundary-to-3D bulk projection and evolution, and are **reference material**, not validated scientific or numerical foundations. Any reused method must be reviewed and tested independently.

## Development process

See [AGENTS.md](AGENTS.md) for repository-wide instructions for coding agents. Work on scoped branches and open pull requests for owner review; do not merge, tag, or publish releases without explicit owner authorization.

## Scope and interpretation

SENTIO is a computational research prototype, not an established model of human vision, biological memory, or fundamental physics. Report observations and limitations without labeling emergent-looking patterns as intelligence or proof of a physical hypothesis.
