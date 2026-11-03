# Issue #6 — live C922 soft-sextic application

2026-11-03 · [PR #7](https://github.com/mongstad/SENTIO/pull/7) · owner review, unmerged

## Delivered behavior and authorization

The completed nonlinear core now runs in the actual Fedora GUI with live C922
luminance. Linear remains the default; its integrator, input conversion, capture
implementation and dependencies are unchanged. The [owner's PR direction](https://github.com/mongstad/SENTIO/pull/7#issuecomment-6614518495)
explicitly supersedes the earlier #4 dependency boundary: minimal model/ω/A
controls are authorized now. This does not implement or close #4's broader
numeric-control redesign. The [earlier core report](ISSUE_6_CORE.md), refinement
results and long-run evidence retain their original provenance.

From the repository root, close any other camera client and run:

```bash
python3 -m sentio --source camera --model sextic
# Accepted default, without nonlinear restoring force:
python3 -m sentio --source camera
```

Run one camera window at a time as the desktop user. The application discovers
the unique C922, preferring its persistent V4L2 path; `--device` remains available.
No root privileges, GPU runtime, new dependency or raw camera recording is needed.
The source remains processed YUYV luminance, area-averaged and centered exactly
as before; camera preview is optional, diagnostic, and initially hidden.

## Controls and state policy

- Fresh sextic startup: zero field, `c=.3, γ=.4, κ=2, ω=8, A=.1`, running and
  coupled. Display range is fixed at ±.05, intensity 1. Fresh linear startup
  retains its prior defaults, including ±2 for camera input.
- Selecting a different model resets the field **and model parameters to their
  defaults**, pauses, and disables coupling. Display range/intensity stay fixed.
  Enable coupling and uncheck Pause to start the comparison. Selecting the same
  model is rejected without changing state; use Reset field to clear it.
- Type ω/A (or existing physical controls) and press Enter. Existing spinbox
  conventions also commit on focus loss or arrow changes. Changes execute between
  steps; unsafe configurations leave the state/settings unchanged and show a
  rejection. Effective ω/A are also printed in diagnostics. Field resets/model
  transitions synchronize even a focused widget to the new settings.
- Minimal widget ranges: ω .0001…1,000,000; A .0001…10,000, four decimal places.
  These are input-widget limits, **not a scientifically validated region**.
  Existing physical/display widget ranges remain unchanged pending #4. The
  solver additionally checks positive finite coefficients, representability,
  the current amplitude envelope and the wave/curvature step bound. The
  operational minimum step remains 1e−6 s, not a real-time performance promise.
- A rejected candidate step pauses with a numerical fault, retaining the last
  accepted state without clipping. Reset, seed, restore, or an explicit model
  change supplies valid state before resuming. The fixed validity envelope
  `|u|≤4A` is separate from display saturation and cannot be enlarged independently.
- **Reset to explicit Gaussian seed control** sets the researched initial field
  and `c=.3, γ=κ=0, ω=8, A=.1`, paused and uncoupled. This is an imposed initial
  condition, not a pattern formed by the camera. Use display range ±.2 to inspect
  the initial peak without saturation. For camera forcing afterward, reset and
  set γ=.4, κ=2, enable coupling and resume.
- Save/restore dispatches by validated schema/model: legacy linear schema 1
  and nonlinear schema 2. Restore adopts the checkpoint's model/settings and
  state, paused with coupling off; malformed or unsupported files leave the
  current field intact. Application states require 256² and the sponge. No frame
  history, preview or source array is saved.

The window shows the actual signed field, independent camera/display/simulation
rates, model seconds per wall second, signed extrema, energy, envelope use,
wave/curvature bound, input work, damping loss, parameter work and balance residual.
The right panel scrolls to the detailed diagnostics, camera warnings and log path.
The always-visible strip above the field includes model, fault/pause state and
rates. Model/settings changes and numerical diagnostics are recorded as scalar
JSONL. The energy graph starts a new history after reset/model/seed/restore.

## Verification performed

Fedora 44, Python 3.14.8, NumPy 2.4.3, native Qt Wayland, real Logitech C922.
The final visible-desktop smoke lasted **34.35 wall seconds**. Each measured
phase ran for ten seconds; the table summarizes its last seven seconds. The
report contains actual source hashes, settings, control acknowledgements,
camera readback and diagnostics: [scalar evidence](evidence/issue-6-live/desktop-smoke.json).

| Phase | Camera FPS (median) | Simulation steps/s (median) | Model s / wall s (median) | Display refresh/s (median) |
|---|---:|---:|---:|---:|
| Sextic before edits | 29.987 | 479.935 | 0.999865 | 31.252 |
| Linear | 29.987 | 239.998 | 0.999993 | 31.255 |
| Sextic after switching back | 29.987 | 479.894 | 0.999779 | 31.257 |

The camera negotiated **YUYV 640×480 @30**, with 1,014 frames in the final
published snapshot and zero reported driver drops, bad frames, drained discards
or mailbox discards. Firmware read back exposure 129 rather than requested 156;
the existing warning remains visible/logged. Manual exposure, dynamic-frame-rate
off, fixed focus and white balance were read back. Capture and simulation both
stopped normally at the end of the smoke; the normal CLI application was then
launched separately in camera/sextic mode and left open for owner review.

Measured command-to-snapshot acknowledgements were **16.2–42.7 ms**. Published
driver-frame age in the steady samples ranged **36.0–81.5 ms**, with medians
53.5–54.4 ms. This is sampled input age at simulation publication, not an optical
stimulus-to-screen latency measurement. Display rate counts Qt refresh calls,
not independently measured compositor presentations.

The visible protocol exercised typed Enter changes to ω/A/speed/damping/coupling,
pause while acquisition continues, display-only changes preserving state,
save/reset/restore, continuing uncoupled evolution, both safe model transitions,
and synchronization of focused controls after transitions. The actual field/UI
was inspected from a local Qt window capture with preview disabled. The capture
and binary checkpoint remain ignored local artifacts, not committed evidence.
No camera, numerical or runtime error occurred in the final smoke.

Automated checks:

```bash
python3 -m unittest discover -s tests -v
PYTHONNOUSERSITE=1 python3 -m unittest discover -s tests -v
python3 -m compileall -q sentio tests tools
git diff --check
```

Both complete suites passed **57 tests, zero skips**. They include the prior 53
checks plus exact linear engine regression, nonlinear transition/fault/rejection
handling, cross-model checkpoint dispatch and offscreen typed GUI controls.
Compile and whitespace checks passed. No additional long research matrix was
run; the numerical evolution methods are unchanged from the validated core.

To repeat the short **visible, actual-camera** protocol after closing the normal
window (choose a new report path; it refuses overwrite):

```bash
python3 -m tools.validate_live_gui --output runs/issue6-owner/desktop.json
# Optional: leave its final camera/sextic window open after the checks.
python3 -m tools.validate_live_gui --output runs/issue6-owner/review.json --leave-open
```

This tool refuses offscreen/minimal Qt. It opens the real camera by default,
uses the same Runtime/Window classes as the normal CLI, records scalar results,
and saves one explicit field checkpoint. It does not record camera imagery.

## Limits and owner experiment

The earlier isolated core measurement was **0.491–0.514 model s/wall s**. The
desktop run above was faster under its execution conditions; this does not
invalidate the earlier result or establish a guaranteed real-time rate. No
numerical optimization, step enlargement or GPU rewrite was introduced. Watch
the live rate and skipped-wall-time indicators when raising speed or ω or under
other desktop load. Finer numerical steps can reduce model-time throughput.

The prior grid-scale checkerboard test had about **5% balance residual** at
1/480; halving/quartering the step reduced it, but final responses were not
tightly converged. Default finite evolution is not a high-frequency accuracy
guarantee. The seed retention result does not establish spontaneous formation.
The live scene was uncontrolled: physical object movement, viewpoint changes,
recurring presentations and unplug/replug remain owner experiments, not executed
or recognized automatically. No indefinite stability claim follows from this
short camera smoke.

1. Start sextic with the command above. At c=.3, γ=.4, κ=2, ω=8, A=.1, hold the
   scene still, move a hand/object, change viewpoint, then repeat a stimulus.
   Note wall times in your observations; raw footage is unnecessary.
2. Disable input coupling. The existing field should continue oscillating and
   decaying. Pause to inspect the signed range, energy and envelope use. Reset
   with coupling off supplies a zero-input control.
3. Select Linear. It resets, pauses and disables coupling. Enable coupling and
   resume; repeat the same scene actions. Repeat with sextic. Use a common fixed
   display range/intensity when comparing amplitudes (±2 avoids saturation for
   the linear response measured here). Zoom sextic to ±.05 for detail only with
   the explicit understanding that this changes visual contrast, not the field.
4. In sextic, type ω=10 and A=.12 and press Enter; watch effective values and
   step size. Keep the validity-envelope fraction distinct from display clipping.
   Scroll the right panel for full diagnostics and rejection/camera messages.
5. Optionally run the explicitly labeled seed control with coupling off, range
   ±.2, then unpause. Compare seeded dynamics with camera forcing without calling
   the seed a sensory-created structure. Save state before replacing a field
   you want to retain. Close normally to release the camera and restore controls.

PR #7 remains a draft for the owner's visual review. No merge, tag, release or
issue #4 branch change was performed.
