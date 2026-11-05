# Issue #10 protocol (declared before the comparison matrix)

The owner's request to implement #10 activates its backlog authorization gate.
This is a separate deterministic research model/viewer, following issue #3's
isolation convention. It does not change `sentio`, camera acquisition, application
checkpoints, launch defaults, COGNIO, or WVZ formats. No webcam trials are planned
in this bounded investigation. A second local state m is explicitly added.

Start with the accepted linear or soft-sextic wave, c=.3, gamma0=.4, kappa=2,
omega=8, A=.1, fixed edges and the existing sponge. Reinforcement obeys

```
m_t = eta * activity * (1-m) - lambda*m
gamma(m) = gamma_min + (gamma0-gamma_min)/(1+alpha*m)
source activity = (kappa*S/2)^2
wave activity = local_wave_energy_density/(local_wave_energy_density + .005)
```

Source activity measures normalized applied acceleration squared; it is zero
when forcing is absent or kappa=0. Wave activity includes kinetic, gradient and
sextic potential density, so unforced waves can reinforce their propagation
path. These are different, explicitly scaled rules, not calibrated biological
activity. Nominal eta=2, lambda=.02, alpha=9, gamma_min=.02; m starts at zero.
It stays in [0,1] by an exact affine update with frozen activity, not clipping.
An m half-update, the accepted damping/Verlet wave step at frozen midpoint m,
and a second m half-update form a symmetric split. The original wave/curvature
step guards and candidate-state rejection are retained. Disabled reinforcement
dispatches to the actual accepted solver. No spatial templates enter the rule.

The energy function depends on u/v, not m. Its continuum rate is input work
minus nonnegative damping loss. m stores a damping history, not an accounted
energy reservoir. Measure exact held-source work and damping-substep losses;
report the integration residual and refine the step instead of claiming exact
energy conservation or a proof of nonlinear stability.

## Predeclared comparisons

Training shapes: a Gaussian centered at (x=.35,y=.5), width sigma=.07; its exact
left/right reflection; and a signed vertical dipole at the familiar location,
normalized to the Gaussian's discrete squared norm. All start at u=v=m=0.
Training amplitude .5. Schedules have equal two-second total on-time:

- repeated: [0,.5), [1.5,2), [3,3.5), [4.5,5)
- single recent: [3,5)
- single early: [0,2)
- clustered: [2,2.5), [2.75,3.25), [3.5,4), [4.5,5)

All trains end by common t=5, followed by eight model seconds without input.
This matches integral(kappa*S)^2 dx² dt, **not actual work**: forcing phase and
the response can change supplied work. Report both, plus E(t)/E(5), finite-window
half-energy crossing, map quantiles/coverage and participation, and energy/map
mass inside equal left/right disks (radius .14). Gaussian tails mean a nonzero
map is not evidence of propagation; coverage uses the declared m>=.1 threshold.

Then impose a clearly labeled state-matching intervention: u=v=0, retain the
t=13 map, and compare against an erased-m copy under the **identical** two-spot
probe (.5 amplitude, .5 s on, 3.5 s off). Reinforcement remains active during
the probe. This separates response due to m from leftover wave energy; it is
not a claim that the physical field spontaneously reset. Measure regional and
total probe-energy integrals, final retention and map changes. Comparing a
reflected training history and the novel dipole tests spatial bias, not object
recognition. There is no pattern-matching or classifier in the dynamics.

Suites (fixed before inspecting results):

- `matrix`: both models; fixed damping plus source/wave reinforcement; repeated,
  single recent/early, clustered, displaced, novel and zero histories at N=65.
- `sweep`: both models and activity rules, repeated history; one-factor eta
  0/.5/4, lambda 0/.2, alpha 0/4/32, gamma_min 0/.4 around the nominal values.
  This is not a Cartesian validation of every combination.
- `refine`: nominal repeated fixed/source/wave cases at N=33/65/129, h/2 at N=65,
  and sponge-free N=65 controls. Report amplitude/map/energy convergence and
  sensitivity to boundaries. Uniform damping remains nonnegative without sponge.
- `full_grid`: nominal repeated fixed/source/wave at N=256.
- `long`: nominal repeated source/wave at N=65, followed by 55 s without input;
  verify map decay versus continued wave reinforcement and inspect energy drift.

Decision rule: report history-dependent damping only if differences exceed
time/grid refinement changes and survive the residual-energy intervention.
Report localization with quantified coverage, including failure if wave-driven
reinforcement spreads widely. A null result is acceptable. Longer-lived energy
alone is not evidence of learned content or a single-field memory mechanism.

Use commands documented in the final report. Outputs refuse overwriting; local
full scalar curves and state hashes stay in ignored `runs/`. At most four
ordinary numerical worker processes are used. Review summaries and fixed-scale
figures are bounded; optional Matplotlib is only for scientific plots, as in
issue #3, and is not an application dependency.
