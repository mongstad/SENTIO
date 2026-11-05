# Issue 11 bounded candidate protocol

The owner-runnable candidate is the application itself: `python3 -m sentio
--source recurring`. Expand **Experimental reinforcement controls**, enable the
mechanism and optionally show the separate m diagnostic. Baseline starts OFF.

Before the comparison run, fix the following protocol. No search for visually
recognizable outcomes. The production envelope detector uses
`max(abs(u), .1*abs(v))`, high threshold .005, low half that, .25 continuous
model seconds of quiet before rearming and .5 seconds minimum event spacing.
Each event adds .02 of remaining capacity (adjustable only through .05), forgetting
is .005 / model second, and damping is `.4*(.05+.95*(1-m)^2)` at baseline gamma.
Both source-driven and propagated activity qualify; no camera frame is an event.
A phase alternative counts alternating signed threshold excursions with the same
refractory interval. It is a comparison, not the GUI default.

Primary training: N=33, both accepted wave models, sponge on, c=.3/gamma=.4/kappa=2,
Gaussian centered at (x=.35,y=.5), width .07, sixteen .5-second pulses of amplitude
.25 at 4-second spacing. Compare one late amplitude-1 pulse (same integral of
squared input acceleration), one late .25 pulse and no reinforcement. Stop at
68 model seconds (7.5 seconds after final input). Also compare the phase detector,
N=65/129, half step, amplitudes .125/.5, spacings 2/8 and sponge-free reflection.

Measure scalar curves, local/total energy, exact damping losses and work, event
counts and map coverage. After training, compare identical velocity probes in
left/right regions with retained versus erased m, with event gain zero so the
probe measures damping rather than rebuilding history. Both probes keep slow
forgetting. This is an explicit second-state intervention, not recognition.

Detector-only controls separate numerical counting from propagation: long held
shock, tiny seeded noise, sustained sinusoidal motion, equal episode counts at
several rates and amplitudes, saturation and exact forgetting. Coupled controls
include persistent sinusoidal forcing, standing-wave initial data and tiny noise.
Compare timestep/grid changes without assuming event detections are smooth at
thresholds. Frequency/wavelength controls use equal numbers of separated forcing
bursts; also report actual local event counts rather than assuming each burst
creates exactly one wave passage everywhere.

Reproduce with fresh paths (refuses overwrite):

```bash
python3 -m research.issue_11.experiments --suite primary --workers 2 --output runs/issue11-owner/primary.json
python3 -m research.issue_11.experiments --suite controls --workers 2 --output runs/issue11-owner/controls.json
python3 -m research.issue_11.experiments --suite refinement --workers 2 --output runs/issue11-owner/refinement.json
```

Results and limitations will be recorded in `docs/ISSUE_11_REPETITION.md`.

## Recorded follow-ups

The strong-shock suite raises input gain to 20 for an isolated amplitude-1 pulse,
for both detectors/models. It followed the primary matched-squared-input trials
to challenge the selected detector with stronger ringing. The full-grid suite
uses three pulses at N=256 (16 seconds), followed by the same six-second probes.
Controls were rerun after correcting the standing-wave metadata: its source-off
time is zero, since its wave is imposed initial data with no forcing at all.
The report-only map replay option does not change stepping. The phase comparator
is rejected by the live runtime after its strong-shock failure; it remains an
explicit research comparator. See the issue guide for outcomes and limitations.
