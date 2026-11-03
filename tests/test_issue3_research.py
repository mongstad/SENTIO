"""Research-only tests. The accepted application tests remain untouched."""

import unittest

import numpy as np

from research.issue_3.experiments import Case, make_field, run_case, source_at
from research.issue_3.model import MODELS, Potential, ResearchField, measure, sine_spectrum
from sentio.field import Field, Parameters
from sentio.inputs import synthetic_source


class PotentialTests(unittest.TestCase):
    def test_potential_derivative_and_curvature_bound(self):
        for name in MODELS:
            p = Potential(name)
            u = np.linspace(-.399, .399, 101)
            eps = 1e-7
            derivative = (p.density(u+eps)-p.density(u-eps))/(2*eps)
            np.testing.assert_allclose(derivative, p.gradient(u), rtol=2e-8, atol=2e-7)
            curvature = (p.gradient(u+eps)-p.gradient(u-eps))/(2*eps)
            self.assertLessEqual(float(np.max(np.abs(curvature))), p.curvature_bound*(1+1e-7))

    def test_even_potential_odd_force_and_sextic_lower_bound(self):
        u = np.linspace(-.4, .4, 1001)
        for name in MODELS:
            p = Potential(name)
            np.testing.assert_array_equal(p.density(u), p.density(-u))
            np.testing.assert_array_equal(p.gradient(u), -p.gradient(-u))
            self.assertGreaterEqual(float(p.density(u).min()), 0)
        p = Potential("sextic")
        self.assertTrue(np.all(p.density(u) >= .1875*p.omega**2*u*u-1e-12))
        self.assertTrue(np.all(u*p.gradient(u) >= 0))

    def test_small_amplitude_matches_massive_linear_force(self):
        u = np.linspace(-1e-7, 1e-7, 51)
        reference = Potential("massive").gradient(u)
        for name in ("quartic", "sextic", "sine_gordon"):
            np.testing.assert_allclose(Potential(name).gradient(u), reference, rtol=2e-12, atol=1e-18)


class ResearchNumericsTests(unittest.TestCase):
    def test_linear_control_uses_accepted_state_evolution_exactly(self):
        for n in (33, 256):
            a = Field(n)
            b = ResearchField(n, potential=Potential("linear"))
            source = synthetic_source(n, 0, "stationary")
            for _ in range(30):
                a.step(source)
                b.step(source)
            np.testing.assert_array_equal(a.u, b.u)
            np.testing.assert_array_equal(a.v, b.v)
            self.assertEqual(a.time, b.time)
            self.assertAlmostEqual(a.diagnostics()["energy"], b.energy(), places=14)

    def test_energy_gradient_matches_acceleration(self):
        rng = np.random.default_rng(309)
        for name in MODELS:
            f = ResearchField(33, potential=Potential(name))
            f.u[1:-1, 1:-1] = rng.uniform(-.12, .12, (31, 31))
            direction = np.zeros_like(f.u)
            direction[1:-1, 1:-1] = rng.normal(size=(31, 31))
            original = f.u.copy()
            eps = 1e-7
            f.u[:] = original+eps*direction
            upper = f.energy()
            f.u[:] = original-eps*direction
            lower = f.energy()
            f.u[:] = original
            exact = f.dx**2*np.sum((-f.parameters.speed**2*f.laplacian(f.u)+f.potential.gradient(f.u))*direction)
            self.assertAlmostEqual((upper-lower)/(2*eps), float(exact), delta=2e-8)

    def test_polynomial_envelope_rejects_without_state_change(self):
        f = ResearchField(33, potential=Potential("sextic"))
        f.v[16, 16] = 1e4
        u, v = f.u.copy(), f.v.copy()
        with self.assertRaises(FloatingPointError):
            f.step()
        np.testing.assert_array_equal(f.u, u)
        np.testing.assert_array_equal(f.v, v)
        self.assertEqual(f.step_count, 0)
        self.assertEqual(f.input_work, 0)

    def test_stable_step_rejections_and_checkpoint_isolation(self):
        f = ResearchField(129)
        self.assertLessEqual(f.dt*np.sqrt(8*f.parameters.speed**2/f.dx**2+f.potential.curvature_bound), 1.6+1e-14)
        with self.assertRaises(ValueError):
            f.step(dt=f.dt*1.01)
        with self.assertRaises(ValueError):
            f.step(np.full_like(f.u, np.nan))
        with self.assertRaises(NotImplementedError):
            f.save("unused.npz")
        with self.assertRaises(NotImplementedError):
            ResearchField.load("unused.npz")

    def test_energy_balance_refines_with_time_step(self):
        for stimulus, damping, sponge in (("seed", 0, False), ("stationary", .4, True)):
            errors = []
            for factor in (1, .5):
                result, field, _ = run_case(Case("sextic", stimulus, duration=2, n=33,
                                                damping=damping, sponge=sponge, timestep_factor=factor))
                self.assertEqual(result["status"], "complete")
                final = result["records"][-1]
                errors.append(abs(final["balance_residual"]))
            self.assertGreater(errors[0], 3.8*errors[1])

    def test_deterministic_protocol_and_continuing_field_after_loss(self):
        case = Case("sextic", "cessation", duration=6, n=33)
        a, f, _ = run_case(case)
        b, _, _ = run_case(case)
        self.assertEqual(a["final_u_sha256"], b["final_u_sha256"])
        self.assertEqual(a["records"], b["records"])
        self.assertIsNone(source_at(case, 5))
        self.assertGreater(f.energy(), 0)
        self.assertGreater(f.step_count, 0)
        for stimulus in ("stationary", "moving", "viewpoint", "recurring"):
            case = Case("linear", stimulus, n=33)
            np.testing.assert_array_equal(source_at(case, .7), synthetic_source(33, .7, stimulus))

    def test_matched_initial_states_across_all_models(self):
        for stimulus in ("seed", "impulse", "stationary"):
            reference = make_field(Case("linear", stimulus))
            for model in MODELS[1:]:
                candidate = make_field(Case(model, stimulus))
                np.testing.assert_array_equal(candidate.u, reference.u)
                np.testing.assert_array_equal(candidate.v, reference.v)


class ResearchDiagnosticTests(unittest.TestCase):
    def test_summary_preserves_early_guard_stop_without_inventing_late_data(self):
        from research.issue_3.report_artifacts import compact
        result, _, _ = run_case(Case("sextic", "seed", duration=40, seed_ratio=5))
        self.assertEqual(result["status"], "stopped")
        summary = compact(result)
        self.assertEqual(summary["final"]["time"], 0)
        self.assertIn("envelope", summary["error"])
        self.assertIsNone(summary["late_mean_energy"])
        self.assertIsNone(summary["late_mean_retention"])

    def test_sine_spectrum_known_modes(self):
        axis = np.linspace(0, 1, 65)
        for m, n, band in ((2, 3, "spectral_low"), (10, 8, "spectral_mid"), (27, 1, "spectral_high")):
            u = np.outer(np.sin(m*np.pi*axis), np.sin(n*np.pi*axis))
            spectrum = sine_spectrum(u, 1)
            self.assertAlmostEqual(spectrum[band], 1, places=14)
            self.assertAlmostEqual(spectrum["cycles_rms"], np.sqrt(m*m+n*n)/2, places=12)
        self.assertIsNone(sine_spectrum(np.zeros((65, 65)), 1)["cycles_rms"])

    def test_local_energy_partition_and_organization_bounds(self):
        f = make_field(Case("sextic", "seed"))
        d = measure(f, f.energy())
        self.assertGreater(d["participation"], 0)
        self.assertLessEqual(d["participation"], 1)
        self.assertGreater(d["core_fraction"], .8)
        self.assertLessEqual(d["core_fraction"], 1)
        self.assertAlmostEqual(d["energy"], f.energy(), places=14)
        z = ResearchField(33)
        self.assertIsNone(measure(z, 0)["participation"])
