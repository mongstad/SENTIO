# Recovered reference review

Reviewed, without executing or modifying, `/home/Nozba/Downloads/VB_HolographicTorus_v1_0.py` on 2026-11-03. SHA-256:

```text
5532cada5e16a5d60c8e49c1ae47c00f62629dcbe5dbdf4c4d6cb7fa3bf469fa
```

The file is an independently recovered historical script, not a project dependency. Its archive remains intact; this PR neither copies it into the application nor imports its algorithms. `VB_BlackHoleHorizon_v1_0.py` was located alongside it but was not a required numerical basis for this implementation.

Relevant observations from the code:

- It maintains separate position/velocity arrays and advances them repeatedly, which is conceptually compatible with continuing field state. Its update is a velocity-first first-order step with nonlinear gradient terms, heuristic projection and feedback. A constant small time step alone does not validate those nonlinear dynamics.
- Its periodic finite differences use `roll`, while coordinate spacing is computed as `2L/(N−1)` with endpoint-inclusive coordinates. Periodic-domain geometry, spacing, and duplicate endpoints would need deliberate reconciliation and convergence tests before reuse.
- Projection divides the boundary field by its RMS. That largely removes amplitude dependence; surrounding comments suggesting that a stronger boundary necessarily gives stronger projected forcing do not establish this behavior. The shell weighting and interior mask also prescribe structure independently of field evolution.
- Its reported `mean(v²+u²)` energies omit the wave-gradient contribution and do not establish conservation for the selected model. The ratio of normalized gradient variances is a chosen statistic over different dimensional grids, not evidence of holography.
- Display limits follow the current amplitudes. Automatic contrast changes can make small decaying fields look persistent. Its named phases and displayed complexity do not validate recognition, memory, or a physical hypothesis.
- Integration runs inside animation updates, tying progress to display scheduling. Automatic checkpoints and unbounded histories differ from the requested transient-camera workflow. The script has no C922 acquisition or controlled webcam-to-field coupling.

Prototype 1 therefore uses a separate linear 2D model, explicit input scaling, a documented stable integration method, finite boundaries with a measured sponge, a gradient-based energy diagnostic, independent acquisition/integration/rendering, fixed signed display limits, and requested-only state checkpoints. None of the reference's 3D projection, nonlinear terms, heuristic feedback, or scientific labels are carried over.
