import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np

from sentio.field import Field, Parameters
from sentio.sextic import SexticField
from sentio.models import load_field
from sentio.reinforcement import Reinforcement, ReinforcementParameters
from sentio.runtime import Engine, EventLog


class ReinforcementTests(unittest.TestCase):
    def advance(self, r, u=0., v=0., seconds=.5, h=.01):
        a, b = np.full_like(r.m, u), np.full_like(r.m, v)
        Field._edge_zero(a)
        Field._edge_zero(b)
        for _ in range(round(seconds/h)):
            r.commit(r.propose(a, b, h))

    def test_single_held_shock_has_capped_amplitude_independent_gain(self):
        for amplitude in (.006, .1, 10000):
            r = Reinforcement(17, ReinforcementParameters(forgetting=0))
            self.advance(r, amplitude, seconds=3)
            self.assertEqual(r.events[8, 8], 1)
            self.assertEqual(r.m[8, 8], .02)
            self.assertFalse(np.any(r.m[0]))

    def test_rearming_refractory_and_repetition_saturation(self):
        r = Reinforcement(17, ReinforcementParameters(forgetting=0))
        for count in range(1, 101):
            self.advance(r, .01, seconds=.3)
            self.advance(r, seconds=.3)
            self.assertEqual(r.events[8, 8], count)
            self.assertAlmostEqual(r.m[8, 8], 1-.98**count, places=14)
        self.assertLess(r.m.max(), 1)
        self.assertGreater(r.m.max(), .86)
        r = Reinforcement(17)
        for _ in range(10):
            self.advance(r, .01, seconds=.1)
            self.advance(r, seconds=.1)  # insufficient quiet interval
        self.assertEqual(r.events[8, 8], 1)

    def test_exact_forgetting_and_quiet_noise(self):
        r = Reinforcement(17)
        r.m[1:-1, 1:-1] = .8
        self.advance(r, .0001, .0001, seconds=5)
        np.testing.assert_allclose(r.m[1:-1, 1:-1], .8*np.exp(-.005*5), rtol=3e-14)
        self.assertFalse(r.events.any())

    def test_full_reinforcement_cannot_create_a_wave_from_zero(self):
        for cls in (Field, SexticField):
            f = cls(33)
            f.reinforcement = Reinforcement(33)
            f.reinforcement.m[1:-1,1:-1] = 1
            for _ in range(100):
                f.step()
            self.assertFalse(f.u.any())
            self.assertFalse(f.v.any())
            self.assertFalse(f.reinforcement.events.any())
            np.testing.assert_allclose(f.reinforcement.m[1:-1,1:-1], np.exp(-.005*f.time), rtol=1e-14)

    def test_envelope_rejects_standing_cycle_counts_phase_does_not(self):
        for detector, expected in (("envelope", 1), ("phase", 8)):
            r = Reinforcement(17, ReinforcementParameters(detector=detector, forgetting=0))
            for t in np.arange(.001, 4.0001, .001):
                self.advance(r, .02*np.sin(2*np.pi*t), .04*np.pi*np.cos(2*np.pi*t),
                             seconds=.001, h=.001)
            self.assertEqual(r.events[8, 8], expected)

    def test_equal_episode_counts_multiple_rates_and_steps(self):
        for period in (.7, 1., 2.):
            for h in (.01, .005, .0025):
                r = Reinforcement(17, ReinforcementParameters(forgetting=0))
                for _ in range(8):
                    self.advance(r, .02, seconds=.2, h=h)
                    self.advance(r, seconds=period-.2, h=h)
                self.assertEqual(r.events[8, 8], 8)
                self.assertAlmostEqual(r.m[8, 8], 1-.98**8)

    def test_off_preserves_both_solvers_bitwise_and_freezes_history(self):
        for cls in (Field, SexticField):
            a, b = cls(33), cls(33)
            a.reinforcement = Reinforcement(33, enabled=False)
            a.reinforcement.m[1:-1, 1:-1] = .7
            source = np.zeros_like(a.u)
            source[10:18, 12:20] = .2
            for _ in range(80):
                a.step(source)
                b.step(source)
            np.testing.assert_array_equal(a.u, b.u)
            np.testing.assert_array_equal(a.v, b.v)
            self.assertEqual(a.dt, b.dt)
            self.assertTrue(np.all(a.reinforcement.m[1:-1, 1:-1] == .7))
            self.assertFalse(a.reinforcement.events.any())

    def test_local_damping_bounds_and_identical_probe_retention(self):
        for cls in (Field, SexticField):
            energies = []
            for strength in (0., .9):
                f = cls(33, parameters=Parameters(speed=.1, damping=2, coupling=0))
                f.reinforcement = Reinforcement(33, ReinforcementParameters(gain=0, forgetting=0))
                f.reinforcement.m[1:-1, 1:-1] = strength
                x = np.linspace(0, 1, 33)
                f.v = .1*np.sin(np.pi*x[:, None])*np.sin(np.pi*x[None, :])
                f._edge_zero(f.v)
                gamma = f.reinforcement.damping(2)
                self.assertGreaterEqual(gamma.min(), .1)
                self.assertLessEqual(gamma.max(), 2)
                for _ in range(round(1/f.dt)):
                    f.step()
                energies.append(f.diagnostics()["energy"])
            self.assertGreater(energies[1], energies[0]*2)

    def test_coupled_matched_squared_input_shock_vs_separate_pulses(self):
        # Sixteen quarter-strength pulses and one full-strength pulse have the same
        # integral of squared acceleration. They need not do equal wave work.
        axis = np.linspace(0, 1, 33)
        shape = np.exp(-((axis[:,None]-.5)**2+(axis[None,:]-.35)**2)/.07**2)
        Field._edge_zero(shape)
        for cls in (Field, SexticField):
            results = []
            for repeated in (False, True):
                f = cls(33)
                f.reinforcement = Reinforcement(33)
                steps = round(68/f.dt)
                spacing, width = round(4/f.dt), round(.5/f.dt)
                for i in range(steps):
                    on = (i//spacing < 16 and i%spacing < width) if repeated else (15*spacing <= i < 15*spacing+width)
                    f.step((.25 if repeated else 1)*shape if on else None)
                results.append(f.reinforcement.m.copy())
                self.assertTrue(f.diagnostics()["finite"])
                self.assertLessEqual(f.reinforcement.m.max(), 1)
            shock, repeated = results
            self.assertLess(shock.max(), .06)
            self.assertGreater(repeated[16, 11], shock[16, 11]*2)

    def test_state_and_detector_commit_atomically_on_fault(self):
        for cls in (Field, SexticField):
            f = cls(17, parameters=Parameters(coupling=1e308))
            r = f.reinforcement = Reinforcement(17)
            before = {k:getattr(r,k).copy() for k in r.array_dtypes}
            with self.assertRaises(FloatingPointError):
                f.step(np.ones_like(f.u))
            self.assertEqual(f.step_count, 0)
            self.assertFalse(f.u.any())
            for k in before:
                np.testing.assert_array_equal(getattr(r,k), before[k])
        f = Field(17)
        f.reinforcement = Reinforcement(17)
        f.reinforcement.events[8,8] = np.iinfo(np.uint64).max
        f.v[8,8] = .1
        u, v = f.u.copy(), f.v.copy()
        with self.assertRaisesRegex(FloatingPointError, "counter"):
            f.step()
        np.testing.assert_array_equal(f.u, u)
        np.testing.assert_array_equal(f.v, v)

    def test_parameter_domains_and_step_resolution(self):
        for changes in (dict(gain=.1), dict(floor=-.1), dict(forgetting=float("nan")),
                        dict(refractory=0), dict(threshold=0), dict(detector="energy")):
            with self.assertRaises(ValueError):
                ReinforcementParameters(**changes)
        f = Field(17)
        r = f.reinforcement = Reinforcement(17)
        before = r.parameters
        with self.assertRaises(ValueError):
            r.configure(threshold=.01, gain=.1)
        self.assertEqual(r.parameters, before)
        r.configure(refractory=.001)
        self.assertEqual(f.dt, .001/8)

    def test_checkpoint_continuation_all_detector_state_and_legacy_schemas(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"state.npz"
            for cls in (Field, SexticField):
                for detector in ("envelope", "phase"):
                    f = cls(33)
                    f.reinforcement = Reinforcement(33, ReinforcementParameters(detector=detector))
                    source = np.full_like(f.u, .1)
                    for _ in range(120):
                        f.step(source)
                    f.save(path)
                    restored = load_field(path)
                    for _ in range(40):
                        f.step(source)
                        restored.step(source)
                    np.testing.assert_array_equal(f.u, restored.u)
                    np.testing.assert_array_equal(f.v, restored.v)
                    for k in f.reinforcement.array_dtypes:
                        np.testing.assert_array_equal(getattr(f.reinforcement,k), getattr(restored.reinforcement,k))
                    f.reinforcement.enabled = False
                    f.save(path)
                    self.assertFalse(load_field(path).reinforcement.enabled)
                legacy = cls(33)
                legacy.save(path)
                self.assertIsNone(load_field(path).reinforcement)

    def test_malformed_checkpoint_and_failed_save_preserve_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"state.npz"
            f = Field(17)
            f.reinforcement = Reinforcement(17)
            f.save(path)
            original = path.read_bytes()
            f.reinforcement.m[8,8] = float("nan")
            with self.assertRaises(ValueError):
                f.save(path)
            self.assertEqual(path.read_bytes(), original)
            with zipfile.ZipFile(io.BytesIO(original)) as z:
                members = {k:z.read(k) for k in z.namelist()}
            for changes in (dict(schema=2), dict(enabled=1), dict(parameters={})):
                meta = json.loads(members["schema.json"])
                meta.update(changes)
                with zipfile.ZipFile(path, "w") as z:
                    for k,v in members.items():
                        z.writestr(k, json.dumps(meta) if k == "schema.json" else v)
                with self.assertRaises(ValueError):
                    load_field(path)
            # An outer container cannot nest another schema-3 container.
            with zipfile.ZipFile(path, "w") as z:
                for k,v in members.items():
                    z.writestr(k, original if k == "wave.npz" else v)
            with self.assertRaises(ValueError):
                load_field(path)

    def test_checkpoint_rejects_bad_arrays_before_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"state.npz"
            f = Field(17)
            f.reinforcement = Reinforcement(17)
            f.save(path)
            with zipfile.ZipFile(path) as z:
                members = {k:z.read(k) for k in z.namelist()}
            with np.load(io.BytesIO(members["reinforcement.npz"]),allow_pickle=False) as data:
                arrays = {k:data[k] for k in data.files}
            for name, replacement in (("m",np.full((17,17),np.nan)),
                                      ("m",np.full((17,17),1.01)),
                                      ("m",np.ones((17,17))),  # nonzero boundary
                                      ("polarity",np.full((17,17),-128,dtype=np.int8)),
                                      ("events",np.zeros((17,17),dtype=np.float64)),
                                      ("armed",np.zeros((18,18),dtype=bool))):
                memory = io.BytesIO()
                np.savez_compressed(memory,**dict(arrays,**{name:replacement}))
                with zipfile.ZipFile(path,"w") as z:
                    for key,value in members.items():
                        z.writestr(key,memory.getvalue() if key=="reinforcement.npz" else value)
                with self.assertRaises(ValueError):
                    load_field(path)

    def test_runtime_toggle_reset_parameter_ack_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            log = EventLog(Path(directory)/"events.jsonl")
            self.addCleanup(log.close)
            e = Engine(log)
            self.assertIsNone(e.field.reinforcement)
            e.command("reinforcement_parameters", None)
            self.assertIn("must be a mapping", e.message)
            self.assertIsNone(e.field.reinforcement)
            e.command("reinforcement_enabled", True)
            r = e.field.reinforcement
            e.command("reinforcement_parameters", {"gain": .03})
            self.assertTrue(e.control_results["gain"]["accepted"])
            e.command("reinforcement_parameters", {"gain": 1})
            self.assertFalse(e.control_results["gain"]["accepted"])
            self.assertEqual(r.parameters.gain, .03)
            r.m[128,128] = .5
            e.command("map_enabled", True)
            self.assertEqual(r.m[128,128], .5)
            e.command("reinforcement_enabled", False)
            e.step()
            self.assertEqual(r.m[128,128], .5)
            path = str(Path(directory)/"r.npz")
            e.command("save", path)
            e.command("reset")
            self.assertEqual(r.m.max(), 0)
            self.assertEqual(r.parameters.gain, .03)
            e.command("load", path)
            self.assertEqual(e.field.reinforcement.m[128,128], .5)
            self.assertTrue(e.paused)
            self.assertFalse(e.coupling_enabled)
            e.command("model", "sextic")
            self.assertIsNone(e.field.reinforcement)
            e.command("reinforcement_parameters", {"detector": "phase"})
            self.assertIn("research comparator", e.message)
            self.assertIsNone(e.field.reinforcement)
            e.field.reinforcement = Reinforcement(256, ReinforcementParameters(detector="phase"))
            e.field.save(path)
            e.field.reinforcement = None
            before = e.field
            e.command("load", path)
            self.assertIn("research-only", e.message)
            self.assertIs(e.field, before)
