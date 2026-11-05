"""Numerical contracts for the isolated, two-state reinforcement experiment."""

import unittest

import numpy as np

from research.issue_10.model import ReinforcedField, Reinforcement
from research.issue_10.experiments import SCHEDULES, integrate, patterns, summarize
from sentio.field import Field, Parameters
from sentio.sextic import SexticField


class ReinforcementTests(unittest.TestCase):
    def test_disabled_is_exact_accepted_evolution(self):
        for name, cls in (("linear", Field), ("sextic", SexticField)):
            for n in (33, 129):
                a, b = cls(n), ReinforcedField(n, name, enabled=False)
                shapes, _ = patterns(n)
                for i in range(40):
                    source = shapes["familiar"]*.5 if i < 20 else None
                    a.step(source)
                    b.step(source)
                np.testing.assert_array_equal(a.u, b.wave.u)
                np.testing.assert_array_equal(a.v, b.wave.v)
                self.assertEqual(a.time, b.wave.time)
                self.assertFalse(np.any(b.m))

    def test_zero_feedback_and_zero_rate_controls(self):
        for rule in (Reinforcement(eta=0), Reinforcement(alpha=0), Reinforcement(gamma_min=.4)):
            a, b = Field(33), ReinforcedField(33, reinforcement=rule)
            source = np.ones((33, 33))*.5
            for _ in range(40):
                a.step(source)
                b.step(source)
            np.testing.assert_array_equal(a.u, b.wave.u)
            np.testing.assert_array_equal(a.v, b.wave.v)
            if rule.eta == 0:
                self.assertFalse(np.any(b.m))
            else:
                self.assertGreater(b.m.max(), 0)

    def test_exact_map_saturation_decay_and_semigroup(self):
        f = ReinforcedField(33)
        activity = np.full_like(f.m, .25)
        rate = 2*.25+.02
        expected = (2*.25/rate)*(1-np.exp(-rate*3))
        whole = f.update_map(f.m, activity, 3)
        halves = f.update_map(f.update_map(f.m, activity, 1.5), activity, 1.5)
        np.testing.assert_allclose(whole, expected, rtol=0, atol=1e-15)
        np.testing.assert_allclose(halves, whole, rtol=0, atol=1e-15)
        high = f.update_map(f.m, np.ones_like(f.m), 1e4)
        self.assertGreaterEqual(high.min(), 0)
        self.assertLessEqual(high.max(), 1)
        decay = f.update_map(high, np.zeros_like(f.m), 3)
        np.testing.assert_allclose(decay, high*np.exp(-.02*3), atol=1e-15)

    def test_activity_measures_applied_force_or_wave_energy(self):
        src = ReinforcedField(33)
        wave = ReinforcedField(33, reinforcement=Reinforcement(activity="wave"))
        src.wave.u[16, 16] = wave.wave.u[16, 16] = .01
        self.assertFalse(np.any(src.activity(src.wave.u, src.wave.v, None)))
        self.assertGreater(wave.activity(wave.wave.u, wave.wave.v, None).max(), 0)
        uncoupled = ReinforcedField(33, parameters=Parameters(coupling=0))
        self.assertFalse(np.any(uncoupled.activity(uncoupled.wave.u, uncoupled.wave.v, np.ones((33,33)))))
        for f in (src, wave):
            plus = f.activity(f.wave.u, f.wave.v, np.ones((33,33))*.5)
            minus = f.activity(-f.wave.u, -f.wave.v, -np.ones((33,33))*.5)
            np.testing.assert_array_equal(plus, minus)
            self.assertGreaterEqual(plus.min(), 0)

    def test_no_energy_from_reinforcement_and_nonnegative_damping(self):
        for model in ("linear", "sextic"):
            for activity in ("source", "wave"):
                f = ReinforcedField(33, model, Reinforcement(activity=activity, alpha=32, gamma_min=0))
                f.m.fill(1)
                for _ in range(100):
                    f.step()
                self.assertEqual(f.energy(), 0)
                self.assertFalse(np.any(f.wave.u))
                self.assertFalse(np.any(f.wave.v))
                self.assertTrue(np.all(f.damping() >= 0))
                self.assertTrue(np.all(f.damping() <= .4))
                self.assertGreater(f.m.min(), 0)
                self.assertLess(f.m.max(), 1)

    def test_invalid_configuration_and_steps_are_atomic(self):
        for key in ("eta", "decay", "alpha", "gamma_min", "source_scale", "energy_scale"):
            for value in (-1, float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    Reinforcement(**{key:value})
        with self.assertRaises(ValueError):
            ReinforcedField(reinforcement=Reinforcement(gamma_min=.5))
        f = ReinforcedField(33, "sextic")
        f.m.fill(.5)
        f.wave.u[16,16], f.wave.v[16,16] = .399, 100
        f.rebase()
        before = f.wave.u.copy(), f.wave.v.copy(), f.m.copy(), f.diagnostics()
        with self.assertRaises(FloatingPointError):
            f.step(np.ones((33,33)))
        np.testing.assert_array_equal(f.wave.u, before[0])
        np.testing.assert_array_equal(f.wave.v, before[1])
        np.testing.assert_array_equal(f.m, before[2])
        self.assertEqual(f.diagnostics(), before[3])
        for source, dt in ((np.full((33,33), np.nan), None), (None, f.dt*2)):
            with self.assertRaises(ValueError):
                f.step(source, dt)
        f.reset()
        self.assertEqual(f.energy(), 0)
        self.assertFalse(np.any(f.m))
        self.assertEqual(f.wave.time, 0)
        with self.assertRaises(NotImplementedError):
            f.save("unused.npz")
        with self.assertRaises(NotImplementedError):
            f.load("unused.npz")

    def test_energy_balance_and_wave_activity_refine(self):
        for model in ("linear", "sextic"):
            balances, states = [], []
            for factor in (1, .5, .25):
                f = ReinforcedField(33, model, Reinforcement(activity="wave"), timestep_factor=factor)
                shapes, masks = patterns(33)
                records = integrate(f, shapes["familiar"], ((0,.5),), 1, masks)
                balances.append(max(abs(d["balance_residual"]) for d in records))
                states.append(np.concatenate([f.wave.u.ravel(), f.wave.v.ravel(), f.m.ravel()]))
            self.assertGreater(balances[0]/balances[1], 3.7)
            self.assertGreater(np.linalg.norm(states[0]-states[2])/np.linalg.norm(states[1]-states[2]), 3.7)

    def test_matched_source_action_and_reflection(self):
        for n in (33,65,129):
            shapes, masks = patterns(n)
            norms = [float(np.sum(shapes[key]**2)) for key in ("familiar", "displaced", "novel")]
            np.testing.assert_allclose(norms, norms[0], rtol=1e-14)
            np.testing.assert_array_equal(shapes["displaced"], shapes["familiar"][:,::-1])
            self.assertEqual(masks[0].sum(), masks[1].sum())
        for name, intervals in SCHEDULES.items():
            self.assertEqual(sum(b-a for a,b in intervals), 0 if name == "zero" else 2)
        f = ReinforcedField(33)
        shapes,masks = patterns(33)
        records = integrate(f, shapes["familiar"], SCHEDULES["repeated"], 5, masks)
        self.assertAlmostEqual(f.source_action, 2*f.wave.dx**2*np.sum(shapes["familiar"]**2), places=13)
        self.assertAlmostEqual(records[-1]["time"],5,delta=1e-12)

    def test_half_life_is_not_invented_for_zero_or_short_series(self):
        record = dict(time=0,energy=0,input_work=0,balance_residual=0,left_energy=0,right_energy=0)
        self.assertIsNone(summarize([record],0)["half_crossing"])
        records=[dict(record,time=t,energy=e) for t,e in ((5,1),(6,.4),(7,.6))]
        self.assertIsNone(summarize(records)["half_crossing"])

    def test_stopped_report_preserves_failure_without_inventing_late_result(self):
        from research.issue_10.report_artifacts import compact
        r=compact(dict(name="failed trial",case={},status="stopped",error="state rejected",
                       final={"time":1},steps=240,dt_bound=1/240,final_sha256={},probes={}))
        self.assertEqual(r["status"],"stopped")
        self.assertEqual(r["final"]["time"],1)
        self.assertNotIn("summary",r)
        self.assertNotIn("probe_gain",r)
