# Prototype 1 validation — 2026-11-03

## Result and scope

A real C922 drove the evolving 256×256 linear field in a visible Fedora desktop window. The recorded 333.24-second interval sustained approximately 30 capture FPS and 240 simulation steps/s, with finite state and no reported dropped/corrupt/discarded frames. The window was left running for the owner; this evidence is a bounded observation, not a claim about indefinite stability or meaningful recognition.

The implementation is ready for owner review. Controlled physical scene experiments, physical unplug/replug, and hardware shutdown/control-restoration still require owner checks. The live preview was started before the final control-acknowledgement, display-default, and effective-control logging refinements. Its numerical solver and frame buffering are the same; the final refinements were tested through offscreen Qt, a simulated acquisition worker, and direct live hardware readback. The existing live window retains its state and original code until closed; restart it to use the final refinements.

## Environment and commands actually exercised

Host: Fedora 44, kernel `7.2.14-200.fc44.x86_64`; Python 3.14.8, PySide6 6.11.2. The normal user Python imported NumPy 2.4.3; the Fedora RPM NumPy is 2.4.6. This prototype uses CPU NumPy, not the installed RTX 3070 Ti.

| Check | Command / configuration | Actual result |
|---|---|---|
| Main automated suite | `python3 -m unittest discover -s tests -v` | 27 passed, 0 skipped, 2.809 s |
| Fedora system packages | `PYTHONNOUSERSITE=1 python3 -m unittest discover -s tests -v` | 27 passed, 0 skipped, 3.030 s |
| Deterministic measurements | `python3 -m tools.validate_experiments --output docs/evidence/synthetic-validation.json` | Completed in 58.61 wall seconds; all runs finite |
| Paced synthetic runtime | `python3 -m sentio --headless --source recurring --seconds 10 --report /tmp/sentio-recurring-report.json --log /tmp/sentio-recurring.jsonl` | 2,398 steps / 9.9917 simulated seconds; finite; median 239.989 steps/s, no skipped wall time |
| Visible hardware GUI | `python3 -m sentio --source camera --log runs/live-owner-preview.jsonl` | Opened on the owner desktop; C922 actively coupled; observations below |
| GUI rendering | Offscreen `Window` launch, widget interactions, and synthetic screenshot inspected | Signed field, diagnostics, energy plot, controls, and layout rendered; Qt worker shutdown passed |
| Python/import syntax | `python3 -m compileall -q sentio tests` | Passed |
| Editable package / entry point | Temporary venv with system site packages; `python -m pip install --no-cache-dir --no-deps -e .`; `sentio --help` | Built and installed successfully; CLI options displayed |
| Installed CLI exit paths | 0.2 s headless zero-input run; 0.2 s camera run with deliberately nonexistent device | Zero input exited 0; missing camera exited 1 with an explicit error and clean worker shutdown |

An initial editable install using `--no-build-isolation` failed because this environment lacked `setuptools`. Retrying the documented standard build-isolated installation downloaded the declared backend and passed. No project-specific numerical failure was hidden. An initial GUI regression test exposed stale checkbox synchronization; command revisions fixed it, and the complete suite then passed on both NumPy environments.

## Numerical evidence

Small scalar data are retained in [synthetic-validation.json](evidence/synthetic-validation.json); the generating script is checked in. Expected behaviors and results:

- **Zero input:** zero initialized amplitude/velocity remain exactly zero. Eight simulated seconds at 256×256 yielded energy and peak both zero.
- **Propagation and continuation:** a localized velocity impulse propagated to neighbors without wrapping through the fixed edge. Subsequent forcing produced a different state from the same forcing applied to a fresh zero field. Removing forcing did not erase the evolved field.
- **Interference/superposition:** combined-source evolution matched the sum of separate evolutions within float64 tolerances (`u`: `1e-15`; `v`: `2e-14`). Opposite sources cancelled exactly in the tested pair.
- **Damping:** an unforced sine mode at γ=2 lost more than 95% of its initial energy over three seconds; the undamped fixed-wall control's energy error remained below 0.1%.
- **Boundaries:** a centered Gaussian displacement with `c=0.3, γ=0`, N=65 had energy 0.138501 after five seconds with a reflecting wall, versus 0.00102455 with the sponge. Ratio **0.00739741**. This is a representative pulse measurement, not a universal reflection bound.
- **Resolution:** RMS errors against the continuum sine-mode solution at t=0.7 were `1.45450e-4`, `3.65735e-5`, and `8.85628e-6` for N=33,65,129. Roughly fourfold reduction under doubling is consistent with second-order spatial accuracy in this case. Halving the time step separately reduced temporal error by more than 3.9× against the discrete-mode solution.
- **Supported controls:** speed/damping/coupling endpoint tests stayed finite; unsafe and NaN controls were rejected atomically. Full-grid, maximum-speed (`c=2, κ=20`) checkerboard forcing/initial data remained finite for five model seconds at γ=0 and γ=10, with CFL 0.565685.
- **Slow-speed forcing:** at N=33, `c=0.01, κ=20`, uniform sustained forcing remained finite through 600 simulated seconds at γ=0 and γ=10 (144,000 steps each). Peaks reached approximately 10,709 and 1,200 respectively. Large finite displacement under slow propagation is not a numerical instability by itself; it can heavily clip the display. No all-settings, infinite-duration guarantee is made.
- **Reset/checkpoints:** reset cleared both state arrays and the simulation clock. Saved/restored state continued bit-for-bit under the same subsequent source. Invalid/nonfinite/wrong-shape checkpoints were rejected without replacing the current state.

The six deterministic source experiments ran for eight model seconds at N=256, `c=0.3, γ=0.4, κ=2`:

| Source | Final peak | Final wave energy |
|---|---:|---:|
| Zero | 0 | 0 |
| Stationary | 0.0624884 | 0.000911260 |
| Moving | 0.0778847 | 0.00486250 |
| Changing viewpoint (synthetic rotation) | 0.0633102 | 0.00104242 |
| Input removed at t=2 | 0.00211380 | 0.00000710165 |
| Recurring stimulus | 0.0232692 | 0.00159109 |

These are measured responses of selected linear dynamics to specified inputs. They do not test recognition, artificial memory, or autonomous structure generation.

## Hardware evidence

[live-camera-preview.json](evidence/live-camera-preview.json) is a scalar summary of the observed interval. Device serial/path identifiers and raw frames are omitted. The full transient session log remains locally in ignored `runs/`.

| Measurement | Observed value |
|---|---:|
| Mode | Progressive YUYV, 640×480, nominal 30 FPS |
| Allocated MMAP buffers | 3 |
| Observed wall duration | 333.239 s |
| Frames at last observation | 9,981 |
| Capture FPS after five-second warmup | min 29.9224 / median 29.9867 / max 30.0326 |
| Simulation steps/s | min 239.234 / median 239.926 / max 240.970 |
| Model seconds per wall second | median 0.999693 |
| Skipped simulation wall time | 0 s |
| Driver drops / corrupt frames / drain discards / mailbox discards | 0 / 0 / 0 / 0 |
| Last recorded step / model time | 79,945 / 333.104 s |
| Maximum observed field amplitude | 2.06614 |
| Numerical/runtime/capture errors | None recorded |
| Timestamp basis | Driver monotonic |

Manual exposure, disabled dynamic frame rate, disabled autofocus, and fixed white balance were requested. Initial exposure readback was 156, but later direct readback while streaming returned **129 units of 100 μs**; the cause was not established. Final code therefore monitors actual control values after stream start and warns on differences. At that readback: brightness/contrast/saturation/sharpness=128, gain=0, 50 Hz power-line setting, backlight compensation=0, exposure mode=manual, dynamic frame rate=off, autofocus=off, focus=50, white balance auto=off/4500 K, zoom=100, pan/tilt=0. The later readback must not be mistaken for a proof that exposure was 156 throughout the retained interval.

## Remaining limits and owner checks

- The ongoing live preview intentionally was not terminated to test hardware cleanup. Cleanup on startup failure, worker termination, pause with continued acquisition, and stale/disconnected sources have automated tests; physical device closure/control restoration and unplug/replug remain unverified on this run.
- No controlled real-world stationary/moving/viewpoint/recurring-stimulus protocol was executed or labeled by the agent. Deterministic synthetic equivalents passed; the owner can run the documented physical protocol.
- Final UI acknowledgement and ongoing effective-control telemetry were validated separately after the live window started. Restart after saving any desired state to use those refinements. The default camera display range is now ±2; the early live preview started at ±0.2.
- Exact capture latency across USB/firmware was not instrumented; queue bounds, driver timestamps, discards, and stale-source expiry constrain the application path. No claim of a hard end-to-end latency bound is made.
- The sponge can reflect, CPU throughput can fall at extreme settings, and large finite responses can saturate the display. Inspect the measured indicators instead of inferring stability or scientific significance from color patterns.
- Fedora/x86-64 and the listed Python packages were exercised. Other platforms, cameras, Python versions, and indefinite runs are not certified. GPU, nonlinear, 3D, audio, large-grid, and Wavez work remain deferred.

Follow [EXPERIMENTS.md](EXPERIMENTS.md) for exact owner-review steps. Merge remains owner-controlled; this work does not tag, release, merge, or change a project board.
