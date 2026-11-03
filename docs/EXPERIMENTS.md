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
