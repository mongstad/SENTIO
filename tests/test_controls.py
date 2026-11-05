"""Issue #4: numeric domains, atomic safety, defaults and explicit restore."""

from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

import numpy as np

from sentio.field import Field, MIN_STEP, Parameters
from sentio.runtime import Engine, EventLog
from sentio.sextic import SexticField


class NumericControlTests(unittest.TestCase):
    def test_beyond_old_bounds_remains_finite_and_cfl_safe(self):
        for cls in (Field, SexticField):
            for speed in (.001, 3):
                with self.subTest(model=cls.__name__, speed=speed):
                    field = cls(33, Parameters(speed=speed, damping=11, coupling=21))
                    source = np.ones_like(field.u)
                    for _ in range(120):
                        field.step(source)
                    self.assertTrue(field.diagnostics()["finite"])
                    self.assertLessEqual(field.diagnostics()["cfl"], .8/np.sqrt(2)+1e-14)
                    self.assertGreaterEqual(field.dt, MIN_STEP)

    def test_invalid_domains_representation_and_cfl_reject_atomically(self):
        for cls in (Field, SexticField):
            field = cls(33)
            field.step(np.ones_like(field.u))
            before = field.u.copy(), field.v.copy(), field.diagnostics(), field.parameters
            cases = [{key: value} for key in ("speed", "damping", "coupling")
                     for value in (-1, float("nan"), float("inf"), -float("inf"))]
            cases += [{"speed": v} for v in (0, 1e-300, 1e200, 1e5)]
            for changes in cases:
                with self.subTest(model=cls.__name__, changes=changes), self.assertRaises(ValueError):
                    field.configure(**changes)
                self.assertEqual(field.parameters, before[3])
                self.assertEqual(field.diagnostics(), before[2])
                np.testing.assert_array_equal(field.u, before[0])
                np.testing.assert_array_equal(field.v, before[1])
            field.configure(damping=0, coupling=0)
            self.assertEqual(field.parameters.damping+field.parameters.coupling, 0)
            with self.assertRaisesRegex(ValueError, "infeasible"):
                cls(1024, Parameters(speed=1e5))

    def test_extreme_damping_and_gain_fault_are_handled_without_state_loss(self):
        maximum = np.finfo(np.float64).max.item()
        with tempfile.TemporaryDirectory() as directory:
            for model in ("linear", "sextic"):
                with self.subTest(model=model):
                    log = EventLog(Path(directory)/f"{model}.jsonl")
                    self.addCleanup(log.close)
                    engine = Engine(log, model=model)
                    engine.command("parameters", {"damping": maximum})
                    with np.errstate(over="raise", invalid="raise"):
                        engine.step(np.ones_like(engine.field.u))
                    self.assertFalse(engine.fault)
                    self.assertTrue(engine.field.diagnostics()["finite"])
                    before = engine.field.u.copy(), engine.field.v.copy(), engine.field.diagnostics()
                    engine.command("parameters", {"coupling": maximum})
                    with np.errstate(over="raise", invalid="raise"):
                        engine.step(np.ones_like(engine.field.u))
                    self.assertTrue(engine.paused)
                    self.assertTrue(engine.fault)
                    np.testing.assert_array_equal(engine.field.u, before[0])
                    np.testing.assert_array_equal(engine.field.v, before[1])
                    self.assertEqual(engine.field.diagnostics(), before[2])
                    engine.command("paused", False)
                    self.assertTrue(engine.paused)
                    engine.command("reset")
                    engine.command("parameters", {"damping": .4, "coupling": 2})
                    engine.command("paused", False)
                    engine.step()
                    self.assertFalse(engine.fault)

    def test_display_domains_ratio_representation_and_separate_state(self):
        with tempfile.TemporaryDirectory() as directory:
            log = EventLog(Path(directory)/"display.jsonl")
            self.addCleanup(log.close)
            engine = Engine(log)
            engine.step(np.ones_like(engine.field.u))
            before = engine.field.u.copy(), engine.field.v.copy(), engine.field.diagnostics()
            for key, values in (("display_range", (1e-6, 1e5)), ("intensity", (1e-4, 1e3))):
                for value in values:
                    engine.command(key, value)
                    self.assertEqual(getattr(engine, key), value)
                    self.assertTrue(engine.control_results[key]["accepted"])
                for value in (0, -1, float("nan"), float("inf")):
                    engine.command(key, value)
                    self.assertFalse(engine.control_results[key]["accepted"])
                    self.assertEqual(getattr(engine, key), values[-1])
            engine.command("display_range", 1e-300)
            engine.command("intensity", 1e300)
            self.assertFalse(engine.control_results["intensity"]["accepted"])
            engine.command("display_range", 1e300)
            engine.command("intensity", 1e-300)
            self.assertFalse(engine.control_results["intensity"]["accepted"])
            np.testing.assert_array_equal(engine.field.u, before[0])
            np.testing.assert_array_equal(engine.field.v, before[1])
            self.assertEqual(engine.field.diagnostics(), before[2])

    def test_fresh_launch_defaults_and_explicit_checkpoint_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            log = EventLog(Path(directory)/"defaults.jsonl")
            self.addCleanup(log.close)
            for model in ("linear", "sextic"):
                for source in ("camera", "stationary"):
                    for _ in range(2):
                        engine = Engine(log, source=source, model=model)
                        self.assertEqual(asdict(engine.field.parameters), asdict(Parameters()))
                        self.assertEqual((engine.display_range, engine.intensity), (2, 1))
                        self.assertFalse(engine.paused)
                        self.assertTrue(engine.coupling_enabled)
                        self.assertEqual(engine.field.step_count, 0)
                        engine.command("parameters", {"speed": 3, "damping": 11, "coupling": 21})
                        engine.step(np.ones_like(engine.field.u))
                        before = engine.field.u.copy(), engine.field.v.copy(), engine.field.diagnostics()
                        checkpoint = str(Path(directory)/"explicit.npz")
                        engine.command("save", checkpoint)
                        engine.command("reset")
                        engine.command("parameters", {"speed": .3})
                        engine.command("load", checkpoint)
                        self.assertTrue(engine.paused)
                        self.assertFalse(engine.coupling_enabled)
                        self.assertEqual(engine.field.parameters, Parameters(3, 11, 21))
                        np.testing.assert_array_equal(engine.field.u, before[0])
                        np.testing.assert_array_equal(engine.field.v, before[1])
                        self.assertEqual(engine.field.diagnostics(), before[2])

    def test_linear_clock_resolution_rejects_step_atomically(self):
        field = Field(33)
        field.time = 1e30
        with self.assertRaisesRegex(FloatingPointError, "clock"):
            field.step(np.ones_like(field.u))
        self.assertFalse(np.any(field.u))
        self.assertFalse(np.any(field.v))
        self.assertEqual(field.step_count, 0)
