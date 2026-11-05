# Issue #4 — numeric entry, safe domains and launch defaults

2026-11-05 · scoped implementation for owner review; no merge or release.

## Interaction and defaults

Every numeric control is a text field. Select and replace its contents, then
press **Enter or Return**. Decimal and scientific notation are supported without
four-decimal rounding or spinner increments. A complete, representable float64
number is required. Empty/partial input, NaN, infinity, exponent overflow and
nonzero text that rounds to zero are rejected with a concise explanation.

Typing does not change the running model. Focus loss does not submit or discard
an edit. Refreshes, model transitions and checkpoint restore preserve unapplied
drafts, with the effective value shown separately. **Escape** discards the draft.
Each numeric control tracks its submitted revision and edit generation; a delayed
reply cannot erase newer typing. The runtime retains the latest result for each
numeric key, so unrelated commands cannot hide its rejection. A full command
queue leaves the draft available for retry. Accepted replies distinguish the
accepted value from a later effective value if a model transition intervened.

Every fresh session, for either source/model and every supported grid, starts
with **c=0.3, γ=0.4, κ=2.0, display range ±2.0, intensity 1.0, coupling enabled,
and integration running**. These settings and visible initial controls agree
before evolution starts. There is no last-session settings persistence. This
supersedes the old synthetic ±0.2 and sextic ±0.05 display launch defaults; small
signals may need an explicitly entered display range. ω=8 and A=0.1 remain the
sextic model defaults. The existing explicit seed, model transition and restore
actions still pause and disable coupling as documented.

## Exact domains and operational limits

All values must be finite float64 numbers. No old experimental widget min/max
range remains. These mathematical and implementation constraints do remain:

| Control | Domain and reason |
|---|---|
| Wave speed c | Strictly positive; c² must be finite and nonzero. The grid-dependent CFL step (and sextic curvature step) must be at least 1e-6 model s. |
| Damping γ | Nonnegative, preserving dissipative rather than amplifying damping. Its exact exponential half-step can decay to zero at extreme damping. |
| Input acceleration gain κ | Nonnegative, retaining the accepted gain convention. The normalized source supplies the sign; no new polarity-inversion feature is introduced. |
| Display range R | Strictly positive, defining a symmetric amplitude scale. |
| Display intensity I | Strictly positive, defining the display gain. R/I must also be finite and positive so the legend and clipping threshold are representable. |
| Sextic ω, A | Strictly positive, with the existing float64 force/energy coefficient checks, wave/curvature step bound, and current-state envelope validation. |

The **1 µs minimum step** extends the existing sextic operational ceiling to
linear. It rejects configurations needing more than one million steps per model
second before modifying settings; it is neither a hardware throughput promise
nor a mathematical upper bound on wave speed. The speed limit implied by it
depends on dx and, for sextic, ω. Accepted high speeds may still be very slow.
The runtime performs one step between command polls, caps catch-up debt at 50 ms,
and reports achieved model seconds/wall second and skipped wall time. The GUI
adds a slowdown notice below 0.9 model s/wall s after startup. It does not enlarge
the step to catch up or claim skipped physical evolution occurred.

State arrays, clocks and settings remain unchanged on a rejected parameter edit.
Finite extreme gain can be accepted while its next forced step fails: candidate
steps retain the existing NaN/Inf, |u|/|v|≤1e6 and sextic |u|≤4A guards. Both models
also reject a clock increment that float64 cannot resolve. A numerical fault
retains the last committed field and clock, pauses, and requires reset/restore
before resumption. Adjust excessive settings before resuming; Reset retains
settings. These are safety mechanisms, not certificates of accurate dynamics.
Very strong damping can be stable yet inaccurate under the split forcing/wave
integrator; use step-refinement comparisons for new regimes.

Rendering clips u to ±R/I before dividing by that threshold. Thus an intermediate
u×I cannot overflow or underflow and corrupt a representable color. Physical
state is unchanged. The usual signed palette and tested legacy colors remain
identical. Display controls are labeled separately from physical controls.

Checkpoint schemas and explicit restore behavior are unchanged. New valid
out-of-old-range physical settings round-trip exactly. A restore uses the same
numerical guards and same-grid/sponge checks; it restores u/v, model settings
and clock, paused and uncoupled. Display settings remain session settings.

## Validation evidence

Small scalar artifacts are in [evidence/issue-4](evidence/issue-4); each numerical
and live report records source hashes, versions and actual measurements. Logs,
field-only screenshots and binary test checkpoints stay under ignored `runs/`.
No raw camera imagery or frame history is saved.

- The unchanged starting branch passed **64 tests**. The final full suite passed
  **75 tests in 8.673 s**, and the Fedora system-package run passed **75 tests in
  8.505 s**, both with zero skips. Python 3.14.10, PySide6 6.11.2 and NumPy 2.4.3
  / system NumPy 2.4.6 were exercised. `compileall` and `git diff --check` passed.
  `checks.json` records source/log hashes. New tests cover Enter/Return, partial/invalid
  text, subnormal underflow, delayed replies, selection preservation, newer
  drafts, unrelated commands, refresh/epoch changes, queue saturation, display
  arithmetic, defaults, safety faults and checkpoint restore.
- `numerical.json`: four N=256 uniform-forcing trials (linear/sextic, c=.001/3,
  γ=11, κ=21) ran for **2 model seconds of forcing plus 0.5 seconds without input**,
  remaining finite and inside their step constraints. This samples values beyond
  the former lower/upper speed and upper damping/gain bounds.
- At N=65, c=3, γ=11, κ=21, a forced, damped eigenmode was compared with the exact
  solution of the discrete spatial model at t=.5. Halving the step reduced the
  maximum amplitude error by **4.004×**, consistent with second-order temporal
  convergence in this tested regime.
- The default linear solver matched accepted commit `4bf7a98` **bit for bit in
  u/v and clock** after 240 identical moving-source steps at N=33 and N=256.
  Existing superposition, damping, grid convergence, nonlinear reference,
  checkpoint, capture ABI and mocked acquisition regressions remain in the suite.
- `live-256.json`: the visible Qt application exercised the real C922, typed
  physical/nonlinear/display controls, invalid edits, focus changes, pause with
  ongoing acquisition, save/reset/restore, both model transitions and clean
  shutdown. Measurements below are bounded observations on this CPU, without
  other validation workers running, not performance guarantees.

The real camera negotiated **YUYV 640×480 @30 FPS**. The report separately records
measured capture FPS, model-time rate, UI refresh rate, acknowledgements, frame
counters and firmware exposure readback. The camera preview remained disabled.

| Live phase (256²) | Median capture FPS | Model s / wall s | Qt refresh / s |
|---|---:|---:|---:|
| Sextic initial defaults (10 wall s) | 29.987 | 1.0000 | 31.26 |
| Linear c=3, γ=11, κ=21 (5 wall s) | 29.987 | 0.6032 | 31.27 |
| Linear c=100, γ=11, κ=21 (5 wall s) | 29.986 | 0.01781 | 31.26 |
| Linear restored baseline (10 wall s) | 29.986 | 0.9998 | 31.26 |
| Sextic final baseline (10 wall s) | 29.987 | 0.9993 | 31.26 |

Phase statistics exclude the first three wall seconds of each phase. The final
camera snapshot counted **1,339 frames**, with zero driver drops, bad frames,
drain discards or mailbox overwrites. Maximum measured command acknowledgement
was **44.2 ms**. No numerical, runtime or camera error was logged. Both workers
stopped normally; the camera-close event reported no cleanup warnings. Firmware
read back exposure **155**, versus requested **156**, and the existing warning
remained visible. Physical post-close control readback was not separately tested.
Field-only window captures were inspected locally, including retained rejected
drafts with their different effective values. Qt key events were automated, not
physical keyboard operation. The preliminary visible run also passed; retained
artifacts describe the final build, including the final acknowledgement refinements.

## Reproduction and owner checks

From the repository root, close any other camera client first. Use new output
paths to preserve previous evidence:

```bash
python3 -m unittest discover -s tests -v
PYTHONNOUSERSITE=1 python3 -m unittest discover -s tests -v
python3 -m tools.validate_controls --output runs/issue4-owner/numerical.json
python3 -m tools.validate_live_gui --output runs/issue4-owner/live-256.json
python3 -m sentio --source camera
```

1. Confirm all seven launch recommendations above, close normally, and reopen.
2. Pause and type c=3, γ=11, κ=21; press Enter for each. Verify acceptance and the
   smaller dt, then resume and inspect achieved model-time rate. Try a draft `4e`,
   change focus, and return: it must remain a draft. Enter rejects it; Escape
   restores the effective value. Try c=1e100: rejection must preserve state/settings.
3. While paused, change display range/intensity above and below their former
   bounds. Inspect the legend and unchanged energy/state. Rejected drafts remain
   visible with their effective values; they are not active settings.
4. Save, reset, and explicitly restore. Confirm the field/settings/clock return,
   paused and uncoupled. Close and relaunch: baseline recommendations return.
5. Repeat on the desired launch grid and, if relevant, sextic mode. Monitor the
   validity envelope, finite-state indicators and actual model time separately
   from display contrast and camera time.

The finite-duration trials do not validate all finite combinations, indefinite
stability, universal accuracy, or million-step throughput. Physical keyboard
ergonomics, controlled scene manipulation, unplug/replug and a new full live
512²/1024² performance campaign remain owner checks; existing larger-grid
evidence retains its original provenance. No learning, recognition or sensory
formation conclusion follows from these control tests.
