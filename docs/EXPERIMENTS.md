# Reproduction and owner experiments

Run from the repository root after installing the dependencies in `ReadMe.md`. `gcc` and the Linux userspace headers enable the ABI test; the test reports a skip if either is unavailable.

```bash
python3 -m unittest discover -s tests -v
python3 -m tools.validate_experiments --output /tmp/sentio-synthetic-validation.json
python3 -m sentio --headless --source recurring --seconds 10 --report /tmp/sentio-recurring.json
```

The numerical script is deterministic, advances exact simulation durations independently of wall speed, and records only small scalar measurements. Synthetic sources refresh at 30 model-time samples per second. GUI synthetic sources instead refresh at about 30 wall-time samples per second, matching acquisition behavior; these are distinct tests. Sources are explicit controls: zero, two stationary opposite Gaussian spots, a moving spot, a rotating test pattern (`viewpoint`), input removed after two seconds, and a one-second stimulus recurring every three seconds. They are not examples of learned/emergent recognition.

## Hardware validation

Do not open a second streaming application while the live window owns the camera. After closing it normally, run:

```bash
python3 -m sentio --list-devices
python3 -m sentio --headless --source camera --seconds 60 --report /tmp/sentio-camera.json
python3 -m sentio --source camera
```

Check the negotiated mode and **measured** FPS separately. YUYV 640×480 @30 is required; the application refuses a nominal mode fallback. The readback and log can show a firmware-adjusted exposure different from the requested one. Driver drops, corrupt frames, stale input, rendering rate, and simulation speed are separately visible. To reduce a completed or live scalar log without including persistent device IDs:

```bash
python3 -m tools.summarize_session runs/SESSION.jsonl --output /tmp/sentio-session-summary.json
```

## Owner review sequence

1. Observe the camera-driven field at default `c=0.3`, `γ=0.4`, `κ=2`. Show the optional preview only when comparing it with the separately labeled field. Adjust display range to avoid clipping; record the same range in comparisons.
2. Hold the scene stationary, then move a simple object, change viewpoint, and present a recurring stimulus at noted wall times. Write scene/protocol notes alongside the scalar log; no raw recording is required. These physical scene manipulations were not automated or classified by the prototype.
3. Disable coupling. Verify propagation and decay continue from the prior state. Compare with a reset zero-input run. Preserve state first if desired, then repeat identical synthetic stimuli from the same checkpoint to test dependence on prior field history.
4. Pause: the simulation step must stop while measured acquisition continues. Change speed/damping/coupling; resume and verify finite status, changed time step when needed, and independent rates. The speed extremes can change both transient shape and achievable simulation speed.
5. Change display range/intensity while paused. Numerical energy and amplitude must stay unchanged. Compare saturated and unsaturated views; do not interpret contrast changes as physical structure.
6. Save state to a chosen NPZ, reset, restore, and inspect the restored amplitude/velocity and parameters. Restore leaves the field paused with coupling off. A fresh camera stream is a new forcing history, so later exact trajectories are not expected to match.
7. With a saved state if wanted, unplug the camera. Forcing should expire after 250 ms, then a capture error should appear within roughly two seconds; the field should continue and the window remain usable. Replug and restart to reacquire. Physical unplug/replug is an owner check, distinct from the passing mocked disconnection test.
8. Close the window normally. Verify the camera is available again and the changed controls were restored using `v4l2-ctl -d SELECTED_DEVICE --list-ctrls`. Permission loss, unplugging, SIGKILL, and system crashes can prevent restoration.

Use no-input controls, identical model parameters, and identical fixed display scales when comparing observations. Damping-layer reflections, forced steady profiles, source resampling, finite-grid dispersion, exposure changes, and CPU scheduling are alternative explanations for apparent persistence or recurrence. No optical wavefront, recognition, memory, learning, or consciousness conclusion follows from the display.

## Resolution comparison (issue #8)

Read [the measured grid report](ISSUE_8_GRIDS.md) before comparing rates. Close
each camera window before launching the next:

```bash
python3 -m sentio --source camera --model sextic --grid 256
python3 -m sentio --source camera --model sextic --grid 512
python3 -m sentio --source camera --model sextic --grid 1024
```

Repeat with `--model linear`. Keep c, γ, κ, ω/A where applicable, camera controls
and display range/intensity fixed. The physical domain stays [0,1]²; the camera
stays 640×480. First compare a stationary scene at equal **model time**. For
movement or recurring stimuli record both wall and model times: camera changes
follow wall time, so a slower field experiences a different forcing history per
model second. More cells alone do not show additional resolved sensory detail.

At each size, pause, toggle coupling, change a physical control, save/restore a
checkpoint from that size, and switch models. Restore from another grid should
fail without replacing the current state; restart with that grid to load it.
Monitor memory, model-time rate, frame freshness and skipped wall time. Closing
normally releases the camera. A live grid change is deliberately not offered.

Deterministic controls use matched physical initial conditions and fixed model
times, independent of camera/wall-time scheduling:

```bash
python3 -m tools.validate_grids --suite numerical --output runs/issue8-owner/numerical.json
python3 -m tools.validate_grids --suite throughput --grid 1024 --model sextic --output runs/issue8-owner/core-1024-sextic.json
python3 -m tools.validate_live_gui --grid 1024 --output runs/issue8-owner/live-1024.json
```

Repeat throughput in a fresh process for each grid/model, and the visible camera
protocol for each grid. Choose new output paths; do not run CPU benchmarks
concurrently. Numerical controls and live measurements answer different
questions; neither establishes memory, learning or spontaneous organization.
