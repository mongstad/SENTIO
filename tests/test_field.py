import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from sentio.field import Field, Parameters
from sentio.inputs import area_axis, extract_y, luminance_source, synthetic_source


def advance(field, duration, source=None):
    target = field.time + duration
    while target - field.time > 1e-12:
        field.step(source, min(field.dt, target - field.time))


class FieldTests(unittest.TestCase):
    def test_zero_input_preserves_zero(self):
        f = Field(33)
        advance(f, .5)
        self.assertEqual(f.diagnostics()["energy"], 0)
        self.assertEqual(f.step_count, 120)

    def test_impulse_propagates_without_wraparound(self):
        f = Field(65)
        f.v[32, 32] = 1
        advance(f, .15)
        self.assertGreater(np.max(np.abs(f.u[31:34, 34:38])), 0)
        self.assertTrue(np.array_equal(f.u[[0, -1]], np.zeros((2, 65))))
        self.assertTrue(np.all(f.u[:, [0, -1]] == 0))
        self.assertLess(np.max(np.abs(f.u[:5])), 1e-15)

    def test_interference_superposition_and_cancellation(self):
        a, b, combined = (Field(33) for _ in range(3))
        a.v[12, 16] = 1
        b.v[20, 16] = -1
        combined.v[:] = a.v + b.v
        sa = synthetic_source(33, 0, "stationary") * .3
        sb = np.flip(sa, axis=1) * -.5
        for _ in range(120):
            a.step(sa)
            b.step(sb)
            combined.step(sa + sb)
        np.testing.assert_allclose(combined.u, a.u+b.u, atol=1e-15)
        np.testing.assert_allclose(combined.v, a.v+b.v, atol=2e-14)
        a2, b2 = Field(33), Field(33)
        for _ in range(20):
            a2.step(sa)
            b2.step(-sa)
        np.testing.assert_array_equal(a2.u, -b2.u)

    def test_new_input_modifies_existing_field(self):
        old, fresh = Field(33), Field(33)
        first = synthetic_source(33, 0, "stationary")
        advance(old, .3, first)
        second = synthetic_source(33, .8, "moving")
        old.step(second)
        fresh.step(second)
        self.assertGreater(np.linalg.norm(old.u-fresh.u), .01)
        before = old.u.copy()
        old.step(None)
        self.assertFalse(np.array_equal(before, old.u))
        self.assertGreater(np.linalg.norm(old.u), 0)

    def test_damping_reduces_wave_energy(self):
        a = Field(65, Parameters(damping=0), sponge=False)
        b = Field(65, Parameters(damping=2), sponge=False)
        mode = np.sin(np.pi*np.linspace(0, 1, 65))
        a.u[1:-1, 1:-1] = np.outer(mode, mode)[1:-1, 1:-1]
        b.u[:] = a.u
        initial = a.diagnostics()["energy"]
        advance(a, 3)
        advance(b, 3)
        self.assertLess(abs(a.diagnostics()["energy"] / initial - 1), .001)
        self.assertLess(b.diagnostics()["energy"] / initial, .05)

    def test_sponge_absorbs_more_than_reflecting_control(self):
        a, b = Field(65, Parameters(damping=0)), Field(65, Parameters(damping=0), sponge=False)
        x, y = np.meshgrid(np.linspace(0, 1, 65), np.linspace(0, 1, 65))
        a.u[:] = np.exp(-((x-.5)**2 + (y-.5)**2) / .003)
        a._edge_zero(a.u)
        b.u[:] = a.u
        advance(a, 5)
        advance(b, 5)
        self.assertLess(a.diagnostics()["energy"] / b.diagnostics()["energy"], .25)

    def test_sustained_input_and_control_extremes(self):
        for speed in (.01, .3, 2):
            for damping in (0, 10):
                with self.subTest(speed=speed, damping=damping):
                    f = Field(33, Parameters(speed, damping, 20))
                    source = np.ones_like(f.u)
                    advance(f, 3, source)
                    self.assertTrue(f.diagnostics()["finite"])
                    self.assertLess(f.diagnostics()["cfl"], 1/np.sqrt(2))
                    self.assertGreater(f.diagnostics()["energy"], 0)

    def test_mode_resolution_and_time_step_convergence(self):
        errors = []
        for n in (33, 65, 129):
            f = Field(n, Parameters(damping=0), sponge=False)
            s = np.sin(np.pi*np.linspace(0, 1, n))
            mode = np.outer(s, s)
            f.u[:] = mode
            f._edge_zero(f.u)
            advance(f, .7)
            exact = mode * np.cos(np.sqrt(2)*np.pi*.3*.7)
            errors.append(float(np.sqrt(np.mean((f.u-exact)**2))))
        self.assertGreater(errors[0], 3*errors[1])
        self.assertGreater(errors[1], 3*errors[2])
        temporal = []
        for fraction in (1, .5):
            f = Field(33, Parameters(damping=0), sponge=False)
            s = np.sin(np.pi*np.linspace(0, 1, 33))
            mode = np.outer(s, s)
            f.u[:] = mode
            f._edge_zero(f.u)
            dt = f.dt * fraction
            for _ in range(round(.5/dt)):
                f.step(dt=dt)
            omega = .3*np.sqrt(8)*np.sin(np.pi/(2*32))/f.dx
            temporal.append(float(np.max(np.abs(f.u-mode*np.cos(omega*.5)))))
        self.assertGreater(temporal[0], 3.9*temporal[1])

    def test_hot_parameters_and_invalid_values_are_atomic(self):
        f = Field()
        f.v[128, 128] = 1
        f.step()
        old = f.u.copy()
        f.configure(speed=2, damping=10, coupling=20)
        np.testing.assert_array_equal(f.u, old)
        self.assertLess(f.dt, 1/240)
        for kwargs in ({"speed":0}, {"speed":float("nan")}, {"damping":-1}, {"coupling":-1}):
            with self.assertRaises(ValueError):
                f.configure(**kwargs)
            self.assertEqual(f.parameters.speed, 2)
        with self.assertRaises(ValueError):
            f.step(dt=1)
        with self.assertRaises(ValueError):
            f.step(np.full_like(f.u, np.nan))
        np.testing.assert_array_equal(f.u, old)

    def test_numerical_guard_rejects_step_without_overwriting(self):
        f = Field(33)
        f.v[16, 16] = 1e7
        before = f.u.copy()
        with self.assertRaises(FloatingPointError):
            f.step()
        np.testing.assert_array_equal(f.u, before)
        self.assertEqual(f.step_count, 0)

    def test_reset_and_checkpoint_exact_continuation(self):
        f = Field(33)
        source = synthetic_source(33, 0, "stationary")
        advance(f, .1, source)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"state.npz"
            f.save(path)
            restored = Field.load(path)
            with np.load(path, allow_pickle=False) as data:
                self.assertEqual(set(data.files), {"u", "v", "metadata"})
            for _ in range(20):
                f.step(source)
                restored.step(source)
            np.testing.assert_array_equal(f.u, restored.u)
            np.testing.assert_array_equal(f.v, restored.v)
            self.assertEqual(f.time, restored.time)
        f.reset()
        self.assertEqual(f.diagnostics()["energy"], 0)
        self.assertEqual(f.step_count, 0)
        self.assertEqual(f.time, 0)

    def test_checkpoint_rejects_malformed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"state.npz"
            f = Field(33)
            f.save(path)
            with np.load(path) as data:
                meta = json.loads(str(data["metadata"]))
            for field in (np.full_like(f.u, np.nan), np.ones_like(f.u), np.zeros((2, 2))):
                np.savez(path, metadata=json.dumps(meta), u=field, v=f.v)
                with self.assertRaises(ValueError):
                    Field.load(path)


class InputTests(unittest.TestCase):
    def test_yuyv_luminance_and_padding(self):
        raw = bytes([0, 5, 255, 8, 99, 99, 100, 2, 200, 9, 88, 88])
        np.testing.assert_array_equal(extract_y(raw, 2, 2, 6), [[0, 255], [100, 200]])
        with self.assertRaises(ValueError):
            extract_y(raw[:5], 2, 2, 6)

    def test_area_resampling_and_fixed_scaling(self):
        np.testing.assert_allclose(area_axis(np.arange(6, dtype=float), 3, 0), [.5, 2.5, 4.5])
        np.testing.assert_allclose(area_axis(np.arange(3, dtype=float), 2, 0), [1/3, 5/3])
        for level in (0, 16, 127, 128, 235, 255):
            source = luminance_source(np.full((480, 640), level, np.uint8))
            np.testing.assert_allclose(source, level/127.5 - 1, atol=2e-12)
        checker = (np.indices((480, 640)).sum(axis=0) % 2 * 255).astype(np.uint8)
        self.assertLess(abs(luminance_source(checker).mean()), 1e-12)

    def test_synthetic_experiment_controls(self):
        self.assertFalse(np.any(synthetic_source(33, 3, "loss")))
        np.testing.assert_array_equal(synthetic_source(33, .5, "recurring"), synthetic_source(33, 3.5, "recurring"))
        self.assertFalse(np.array_equal(synthetic_source(33, 0, "moving"), synthetic_source(33, 1, "moving")))
        self.assertFalse(np.array_equal(synthetic_source(33, 0, "viewpoint"), synthetic_source(33, 1, "viewpoint")))
