"""Independent issue #6 core; application integration awaits issue #4."""

from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from research.issue_3.model import Potential, ResearchField
from sentio.field import Field, Parameters
from sentio.inputs import synthetic_source
from sentio.sextic import ENVELOPE_RATIO, MIN_STEP, SexticField, SexticParameters


def advance(field, duration, source=None, fraction=1):
    target = field.time+duration
    while target-field.time > 1e-12:
        field.step(source, min(field.dt*fraction, target-field.time))


class SexticCoreTests(unittest.TestCase):
    def test_potential_matches_research_and_energy_derivative(self):
        p = SexticParameters()
        u = np.linspace(-.4, .4, 101)
        np.testing.assert_array_equal(p.gradient(u), Potential("sextic").gradient(u))
        np.testing.assert_array_equal(p.density(u), Potential("sextic").density(u))
        eps = 1e-7
        np.testing.assert_allclose((p.density(u+eps)-p.density(u-eps))/(2*eps), p.gradient(u),
                                   rtol=2e-8, atol=2e-7)
        self.assertTrue(np.all(p.density(u) >= .1875*p.omega**2*u*u-1e-12))

    def test_matches_research_evolution_at_identical_steps(self):
        for n in (33, 129, 256):
            a = SexticField(n)
            b = ResearchField(n, potential=Potential("sextic"), timestep_factor=.5)
            a.u[n//2, n//2] = .05
            b.u[:] = a.u
            a.rebase_energy()
            for step in range(80):
                source = synthetic_source(n, step*a.dt, "moving")
                a.step(source)
                b.step(source)
            np.testing.assert_allclose(a.u, b.u, rtol=0, atol=2e-16)
            np.testing.assert_allclose(a.v, b.v, rtol=0, atol=2e-14)
            self.assertAlmostEqual(a.energy(), b.energy(), places=13)

    def test_zero_and_input_cessation_continue_existing_state(self):
        f = SexticField(33)
        advance(f, .1)
        self.assertEqual(f.energy(), 0)
        self.assertEqual(f.diagnostics()["balance_residual"], 0)
        source = synthetic_source(33, 0, "stationary")
        advance(f, .2, source)
        old = f.u.copy()
        f.step(None)
        self.assertFalse(np.array_equal(old, f.u))
        self.assertGreater(f.energy(), 0)
        fresh = SexticField(33)
        fresh.step(source)
        self.assertGreater(np.linalg.norm(f.u-fresh.u), .001)

    def test_step_bound_reacts_to_parameters(self):
        f = SexticField(33)
        self.assertEqual(f.dt, 1/480)
        f.configure(omega=200)
        self.assertLess(f.dt, 1/480)
        self.assertGreaterEqual(f.dt, MIN_STEP)
        d = f.diagnostics()
        self.assertLessEqual(d["cfl"], .8/np.sqrt(2)+1e-14)
        self.assertLessEqual(d["wave_curvature_number"], 1.6+1e-14)
        with self.assertRaises(ValueError):
            f.step(dt=f.dt*1.01)

    def test_invalid_and_infeasible_changes_are_atomic(self):
        f = SexticField(33)
        f.seed_control()
        original = (f.parameters, f.nonlinear, f.dt, f.u.copy(), f.v.copy(), f.parameter_work)
        for changes in ({"omega":0}, {"omega":-1}, {"omega":float("nan")},
                        {"omega":float("inf")}, {"omega":1e6}, {"omega":1e308},
                        {"amplitude":0}, {"amplitude":1e-300}, {"amplitude":1e308},
                        {"amplitude":.01}, {"omega":9, "amplitude":.01}, {"envelope":8}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                f.configure(**changes)
            self.assertEqual((f.parameters, f.nonlinear, f.dt), original[:3])
            np.testing.assert_array_equal(f.u, original[3])
            np.testing.assert_array_equal(f.v, original[4])
            self.assertEqual(f.parameter_work, original[5])

    def test_envelope_fault_does_not_clip_or_commit(self):
        f = SexticField(33)
        f.u[16,16], f.v[16,16] = .399, 10
        f.rebase_energy()
        before = f.u.copy(), f.v.copy(), f.diagnostics()
        with self.assertRaisesRegex(FloatingPointError, "envelope"):
            f.step()
        np.testing.assert_array_equal(f.u, before[0])
        np.testing.assert_array_equal(f.v, before[1])
        self.assertEqual(f.diagnostics(), before[2])
        with self.assertRaises(ValueError):
            f.step(np.full_like(f.u, np.nan))
        self.assertEqual(f.diagnostics(), before[2])

    def test_extreme_finite_velocity_rejected_atomically(self):
        f = SexticField(33)
        f.v[16,16] = 1e308
        before = f.u.copy(), f.v.copy()
        with self.assertRaises(FloatingPointError):
            f.step()
        np.testing.assert_array_equal(f.u, before[0])
        np.testing.assert_array_equal(f.v, before[1])
        self.assertEqual(f.step_count, 0)

    def test_parameter_work_accounts_for_energy_jump(self):
        f = SexticField(33)
        f.seed_control()
        advance(f, .1)
        before = f.u.copy(), f.v.copy(), f.diagnostics()["balance_residual"]
        f.configure(speed=.4, omega=10, amplitude=.12, damping=.2, coupling=2)
        np.testing.assert_array_equal(f.u, before[0])
        np.testing.assert_array_equal(f.v, before[1])
        self.assertNotEqual(f.parameter_work, 0)
        self.assertAlmostEqual(f.diagnostics()["balance_residual"], before[2], places=14)
        old_work = f.parameter_work
        f.configure(damping=10, coupling=20)
        self.assertEqual(f.parameter_work, old_work)
        advance(f, .1, np.ones_like(f.u))
        self.assertTrue(f.diagnostics()["finite"])

    def test_balance_error_refines_with_time_step(self):
        for forcing in (False, True):
            errors = []
            for fraction in (1, .5):
                f = SexticField(65)
                if not forcing:
                    f.seed_control()
                source = np.ones_like(f.u)*.2 if forcing else None
                initial = f.energy()
                maximum = 0
                for _ in range(10):
                    advance(f, .1, source, fraction)
                    maximum = max(maximum, abs(f.diagnostics()["balance_residual"]))
                errors.append(maximum)
                if not forcing:
                    self.assertLessEqual(f.energy(), initial*1.001)
            self.assertGreater(errors[0]/errors[1], 3.8)
            self.assertLess(errors[0]/errors[1], 4.2)

    def test_explicit_seed_and_reset_rebase_accounting(self):
        f = SexticField(65)
        f.seed_control()
        self.assertEqual(asdict(f.parameters), dict(speed=.3, damping=0, coupling=0))
        self.assertEqual(f.nonlinear, SexticParameters())
        self.assertAlmostEqual(f.u[32,32], .12)
        self.assertEqual(f.diagnostics()["balance_residual"], 0)
        self.assertAlmostEqual(f.dx**2*float(f.energy_density().sum()), f.energy(), places=14)
        advance(f, .2)
        f.reset()
        self.assertEqual(f.time, 0)
        self.assertEqual(f.step_count, 0)
        self.assertEqual(f.energy(), 0)
        self.assertEqual(f.reference_energy+f.input_work+f.damping_loss+f.parameter_work, 0)


class SexticCheckpointTests(unittest.TestCase):
    def test_exact_continuation_and_no_cross_model_interpretation(self):
        f = SexticField(33)
        source = synthetic_source(33, 0, "stationary")
        advance(f, .2, source)
        f.configure(omega=9)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"state.npz"
            f.save(path)
            restored = SexticField.load(path)
            self.assertEqual(restored.diagnostics(), f.diagnostics())
            with self.assertRaises(ValueError):
                Field.load(path)
            for _ in range(40):
                f.step(source)
                restored.step(source)
            np.testing.assert_array_equal(f.u, restored.u)
            np.testing.assert_array_equal(f.v, restored.v)
            self.assertEqual(f.diagnostics(), restored.diagnostics())
            Field(33).save(path)
            with self.assertRaises(ValueError):
                SexticField.load(path)

    def test_rejects_malformed_metadata_envelope_and_arrays(self):
        f = SexticField(33)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"state.npz"
            f.save(path)
            with np.load(path, allow_pickle=False) as data:
                metadata = json.loads(str(data["metadata"]))
            changes = ({"schema":1}, {"model":"linear-wave-verlet-sponge-v1"},
                       {"parameters":{}}, {"nonlinear":{}}, {"nonlinear":{"omega":8}},
                       {"nonlinear":{"omega":True,"amplitude":.1}},
                       {"envelope_ratio":ENVELOPE_RATIO*2}, {"nonlinear":{"omega":1e8,"amplitude":.1}},
                       {"time":float("nan")}, {"step":-1}, {"sponge":"yes"},
                       {"accounting":dict(reference_energy=0, input_work=0, damping_loss=-1, parameter_work=0)})
            for change in changes:
                np.savez(path, u=f.u, v=f.v, metadata=json.dumps(metadata|change))
                with self.assertRaises(ValueError):
                    SexticField.load(path)

            for array in (np.full_like(f.u, np.nan), np.ones_like(f.u), np.zeros((2,2)),
                          np.zeros_like(f.u, dtype=np.float32)):
                np.savez(path, u=array, v=f.v, metadata=json.dumps(metadata))
                with self.assertRaises(ValueError):
                    SexticField.load(path)
            bad = f.u.copy()
            bad[16,16] = .401
            np.savez(path, u=bad, v=f.v, metadata=json.dumps(metadata))
            with self.assertRaises(ValueError):
                SexticField.load(path)

    def test_invalid_save_preserves_existing_checkpoint(self):
        f = SexticField(33)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"state.npz"
            f.save(path)
            original = path.read_bytes()
            f.u[16,16] = .5
            with self.assertRaises(FloatingPointError):
                f.save(path)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
