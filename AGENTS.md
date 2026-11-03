# AGENTS.md — SENTIO project baseline

These instructions apply repository-wide to coding agents, including Astra/Codex. Follow explicit issue requirements and the repository's current documents where they are more specific. If an instruction conflicts with the experimental goal, surface the conflict for owner review rather than silently changing the goal.

## Mission and scope

- **Prototype 1:** Capture live Logitech C922 luminance measurements (640×480, 30 FPS YUYV), couple them into an evolving **2D scalar field** (initially 256×256), and visualize the actual signed field with live diagnostics and parameter controls.
- The continuing field state matters: never replace/reset the field for each incoming camera frame.
- **No** conventional/pretrained neural network, labels, object classification, image reconstruction target, scripted recognition, AI-generated display, or automatic optimization toward visually recognizable shapes.
- **3D field coupling, audio, nonlinear dynamics, adaptive topology, and Wavez integration are deferred** until separately scoped and approved.
- Maintain the distinction between measured camera data (processed YUYV luminance), simulated field dynamics, and rendering. Do not claim optical wavefront reconstruction.

## Working agreement

- **Owner controls merges.** Use a branch for each scoped issue/task and propose a pull request. Never merge, force-push shared branches, delete repositories, publish releases, or create tags without explicit owner permission.
- Prefer one issue/task at a time; do not opportunistically add unrelated features.
- Inspect the repository before changing code. Preserve accepted design decisions, test evidence, and existing functioning behavior.
- Keep commits and PR summaries focused. State what changed, what was tested, what remains unverified, and how the owner can reproduce results.
- Seek owner approval for substantial architectural or scientific changes; avoid open-ended speculation and unnecessary clarification for routine implementation choices.

## Engineering baseline

- Target Fedora Linux 44, Python where appropriate, and NVIDIA RTX 3070 Ti 8 GB. Keep dependencies documented and reproducible; avoid assuming a proprietary or unavailable runtime.
- V4L2 C922 device path observed as `/dev/video0`, but enumerate/select devices robustly; don't hardcode the index as a permanent identity.
- Preferred initial capture: **YUYV 640×480 @ 30 FPS**, measured sustained under manual exposure and disabled dynamic frame rate. Avoid silently falling back to MJPEG or lower FPS; report effective negotiated mode and measured rate.
- Use luminance samples consistently. Make any scaling, centering, resampling, or coupling explicit, testable, and documented. Avoid leaking camera preview pixels into the field visualization as a purported emergent result.
- Keep acquisition, numerical integration, and rendering at independently measured rates. Bound capture buffering/latency; handle disconnection and cleanup gracefully.
- Start with a documented *linear* wave equation and explicit integration scheme, including stable time step (CFL or corresponding criterion), damping, and boundary conditions. Test before introducing nonlinear terms.
- Introduce live controls for propagation speed, damping, input coupling, display range/intensity, camera-coupling toggle, pause/resume, and reset. Apply simulation changes safely; keep visualization controls separate from physical state.
- Track NaN/Inf, peak amplitudes, energy-like diagnostics with correct definitions, dropped frames, capture FPS, and simulation speed. Avoid calling a diagnostic 'conserved energy' unless it is actually conserved for the chosen model.
- Log parameter changes with simulation step/timestamp and record settings and seeds for repeatability.
- Keep webcam data transient in memory by default. No continuous raw video archive, no external network upload, and no collection of unrelated personal data. Explicitly requested checkpoints may save simulation state, not historical frame datasets.
- Design efficient numerical paths but do not assume a large grid or GPU acceleration is necessary before profiling. Correctness and reproducibility precede scaling.

## Validation and reporting

- First implement deterministic synthetic-input tests: impulse propagation, interference/superposition, damping, boundaries, zero input, sustained input, reset, and sensitivity to time step/resolution.
- Demonstrate that the incoming stream modifies an existing field rather than overwriting it. Test camera mode negotiation, sustained capture, dropped-frame handling, hot control changes, pause, reset, and graceful shutdown.
- Check numerical stability across supported controls; reject or clamp unsafe values with a clear indication. Record the test configuration, expected behavior, and actual measurements.
- For scientific claims, compare against no-input and control conditions. Separate observed structure from rendering choices, normalization artifacts, boundary resonances, and numerical errors.
- If a test fails, report it accurately. Never claim an experiment was run based only on code review, synthetic imagery, or plausible output.
- Preserve small, relevant diagnostic reports and instructions for owner reproduction. Do not commit massive captures, transient output files, caches, or binary checkpoints unless specifically approved.

## References and documentation

- `ReadMe.md` is the canonical project introduction (preserve its filename casing).
- Existing historical Claude scripts (`VB_HolographicTorus_v1_0.py`, `VB_BlackHoleHorizon_v1_0.py`) are conceptual references only; do not import their algorithms uncritically or treat reported visual 'complexity' as evidence of holography.
- Document deviations from the baseline, including reasons, trade-offs, and owner authorization.

## Completion checklist

For each PR: summarize scope, list code/docs changed, show exact tests and results, identify limitations and risk, give reproducible run instructions, and leave the branch ready for owner review. **Do not merge.**
