import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from sentio.field import Field
from sentio.grid import DEFAULT_GRID, GRID_SIZES, application_grid
from sentio.inputs import luminance_source, synthetic_source
from sentio.models import load_field
from sentio.runtime import Acquisition, Engine, EventLog, LatestFrame
from sentio.sextic import SexticField


class GridTests(unittest.TestCase):
    def test_defaults_bounds_and_resolution_dependent_steps(self):
        self.assertEqual(DEFAULT_GRID, 256)
        for invalid in (True, 0, 33, 257, 2048, 512.0, "512"):
            with self.assertRaises(ValueError):
                application_grid(invalid)
        for cls in (Field, SexticField):
            steps = []
            for n in GRID_SIZES:
                f = cls(n)
                self.assertEqual(f.u.shape, (n, n))
                self.assertEqual(f.dx, 1/(n-1))
                d = f.diagnostics()
                self.assertEqual((d["n"], d["domain_length"]), (n, 1))
                self.assertLessEqual(d["cfl"], .8/np.sqrt(2)+1e-14)
                if cls is SexticField:
                    self.assertLessEqual(d["wave_curvature_number"], 1.6)
                steps.append(f.dt)
            self.assertLess(steps[-1], steps[0])
            with self.assertRaises(ValueError):
                cls(2048)

    def test_zero_forcing_cessation_and_fixed_edges_at_each_size(self):
        for cls in (Field, SexticField):
            for n in GRID_SIZES:
                with self.subTest(model=cls.__name__, n=n):
                    f = cls(n)
                    f.step()
                    self.assertFalse(np.any(f.u))
                    source = synthetic_source(n, 0, "stationary")
                    for _ in range(4):
                        f.step(source)
                    before = f.u.copy()
                    f.step(None)
                    self.assertFalse(np.array_equal(f.u, before))
                    self.assertTrue(f.diagnostics()["finite"])
                    self.assertGreater(f.diagnostics()["energy"], 0)
                    self.assertFalse(np.any(f.u[[0, -1], :]))
                    self.assertFalse(np.any(f.u[:, [0, -1]]))

    def test_upsampling_preserves_constant_mean_and_pixel_areas(self):
        # Half dark/half bright: camera sampling stays 640x480 at every size.
        y = np.zeros((480, 640), np.uint8)
        y[:, 320:] = 255
        for n in GRID_SIZES:
            with self.subTest(n=n):
                source = luminance_source(y, n)
                self.assertEqual(source.shape, (n, n))
                np.testing.assert_array_equal(source[:, :n//2], -np.ones((n, n//2)))
                np.testing.assert_array_equal(source[:, n//2:], np.ones((n, n//2)))
                constant = luminance_source(np.full_like(y, 128), n)
                np.testing.assert_allclose(constant, 128/127.5-1, atol=2e-12)
        # A nonaligned source pixel contributes its fractional area to output
        # cells; upsampling does not invent a smooth camera detail.
        stripe = np.zeros_like(y)
        stripe[:, 1] = 255
        result = luminance_source(stripe, 1024)
        edges = np.linspace(0, 640, 1025)
        overlap = np.maximum(0, np.minimum(edges[1:], 2)-np.maximum(edges[:-1], 1))
        expected = 2*overlap/(640/1024)-1
        np.testing.assert_allclose(result, np.broadcast_to(expected, result.shape), atol=2e-12)

    def test_larger_checkpoints_continue_exactly_and_reject_cross_grid_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            log = EventLog(Path(directory)/"events.jsonl")
            self.addCleanup(log.close)
            for cls in (Field, SexticField):
                for n in GRID_SIZES:
                    with self.subTest(model=cls.__name__, n=n):
                        f = cls(n)
                        source = synthetic_source(n, 0, "stationary")
                        f.step(source)
                        path = Path(directory)/"state.npz"
                        f.save(path)
                        restored = load_field(path)
                        f.step(source)
                        restored.step(source)
                        np.testing.assert_array_equal(f.u, restored.u)
                        np.testing.assert_array_equal(f.v, restored.v)
                        e = Engine(log, grid=512 if n != 512 else 256)
                        original = e.field
                        e.command("load", str(path))
                        self.assertIn("Checkpoint must match", e.message)
                        self.assertIs(e.field, original)
                        self.assertFalse(e.paused)
                        self.assertTrue(e.coupling_enabled)
            e = Engine(log, grid=1024)
            e.command("model", "sextic")
            self.assertEqual(e.field.n, 1024)
            e.command("load", str(path))
            self.assertNotIn("Rejected", e.message)
            self.assertEqual(e.field.n, 1024)
            self.assertTrue(e.paused)
            self.assertFalse(e.coupling_enabled)

    def test_oversized_array_header_rejected_before_allocation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"oversize.npz"
            for cls in (Field, SexticField):
                cls(33).save(path)
                with zipfile.ZipFile(path) as archive:
                    members = {name: archive.read(name) for name in archive.namelist()}
                stream = io.BytesIO()
                np.lib.format.write_array_header_1_0(stream, dict(shape=(2048, 2048),
                                                                  fortran_order=False, descr="<f8"))
                members["u.npy"] = stream.getvalue()  # Tiny file claiming a huge allocation.
                with zipfile.ZipFile(path, "w") as archive:
                    for name, value in members.items():
                        archive.writestr(name, value)
                with patch("numpy.load", side_effect=AssertionError("allocated before header check")):
                    with self.assertRaises(ValueError):
                        load_field(path)

    def test_acquisition_resamples_selected_grid_without_changing_camera_mode(self):
        stop = threading.Event()
        class FakeCamera:
            def __init__(self, *args):
                self.frames = 0
                self.info = {"card": "fake C922"}
                self.mode = dict(width=640, height=480, fourcc="YUYV", fps=30)
                self.controls, self.warnings, self.buffers = {}, [], [None]*3
            def read(self):
                self.frames += 1
                stop.set()
                return np.full((480, 640), 200, np.uint8), 0., self.frames
            def read_controls(self):
                return {}
            def stats(self):
                return dict(frames=self.frames)
            def close(self):
                pass
        with tempfile.TemporaryDirectory() as directory:
            log = EventLog(Path(directory)/"capture.jsonl")
            self.addCleanup(log.close)
            for n in GRID_SIZES:
                stop.clear()
                mailbox = LatestFrame()
                with patch("sentio.runtime.V4L2Camera", FakeCamera):
                    Acquisition(mailbox, log, stop, grid=n).run()
                (source, preview, _, _), status = mailbox.take()
                self.assertEqual(source.shape, (n, n))
                self.assertEqual(preview.shape, (480, 640))
                self.assertEqual(status["mode"], dict(width=640, height=480, fourcc="YUYV", fps=30))
                np.testing.assert_allclose(source, 200/127.5-1, atol=2e-12)
