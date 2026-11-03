# SENTIO

**SENTIO** is an experimental, continuously evolving sensory-field system. Its first goal is to observe what happens when a two-dimensional scalar field receives a live stream of camera measurements and evolves under explicitly defined wave dynamics.

The experiment asks whether interference and continuing field evolution produce recurring, persistent, or otherwise interesting structure over time. **A recognizable image, a neural network, memory, learning, or consciousness is not an assumed outcome.**

## Current status

**Design / prototype 1 — not yet implemented.** Initial hardware validation is complete, but the field application is still to be built.

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

### Planned live controls

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
