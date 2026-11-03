from pathlib import Path
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from sentio.runtime import Engine, EventLog, LatestFrame, Runtime


class RuntimeTests(unittest.TestCase):
    def test_bounded_mailbox_and_disconnect(self):
        box = LatestFrame()
        for i in range(10):
            box.publish(i, {"state":"running"})
        frame, status = box.take()
        self.assertEqual(frame, 9)
        self.assertEqual(status["mailbox_discards"], 9)
        self.assertIsNone(box.take()[0])
        box.publish(10, {"state":"running"})
        box.update_status(state="error")
        self.assertIsNone(box.take()[0])

    def test_pause_reset_controls_checkpoint_and_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log = EventLog(Path(directory)/"events.jsonl")
            e = Engine(log)
            e.step(np.ones((256, 256)))
            before = e.field.u.copy()
            e.command("paused", True)
            e.step(np.ones((256, 256)))
            np.testing.assert_array_equal(e.field.u, before)
            e.command("display_range", 2)
            e.command("intensity", 3)
            np.testing.assert_array_equal(e.field.u, before)
            e.command("parameters", {"speed": 2})
            self.assertEqual(e.field.parameters.speed, 2)
            e.command("parameters", {"speed": -1})
            self.assertEqual(e.field.parameters.speed, 2)
            self.assertIn("Rejected", e.message)
            path = str(Path(directory)/"state.npz")
            e.command("save", path)
            e.command("reset")
            self.assertFalse(np.any(e.field.u))
            e.command("load", path)
            np.testing.assert_array_equal(e.field.u, before)
            self.assertTrue(e.paused)
            self.assertFalse(e.coupling_enabled)
            invalid = Path(directory)/"invalid.npz"
            invalid.write_text("not a checkpoint")
            e.command("load", str(invalid))
            self.assertIn("Rejected", e.message)
            np.testing.assert_array_equal(e.field.u, before)
            log.close()
            text = Path(log.path).read_text()
            self.assertIn('"step": 1', text)
            self.assertNotIn('"preview"', text)

    def test_runtime_runs_and_stops_without_camera(self):
        with tempfile.TemporaryDirectory() as directory:
            r = Runtime(log_path=Path(directory)/"events.jsonl")
            r.start()
            deadline = time.monotonic()+3
            while time.monotonic() < deadline:
                snap = r.latest()
                if snap and snap["diagnostics"]["step"] > 10:
                    break
                time.sleep(.02)
            r.submit("paused", True)
            time.sleep(.15)
            paused = r.latest()["diagnostics"]["step"]
            time.sleep(.15)
            self.assertEqual(r.latest()["diagnostics"]["step"], paused)
            self.assertTrue(r.latest()["paused"])
            r.close()
            self.assertFalse(r.is_alive())
            self.assertFalse(r.failure)
            self.assertGreater(paused, 10)

    def test_stale_camera_input_expires_while_field_continues(self):
        class FakeCapture(threading.Thread):
            def __init__(self, mailbox, log, stop, *args):
                super().__init__()
                self.mailbox, self.stop_event = mailbox, stop
            def run(self):
                self.mailbox.publish((np.ones((256, 256)), np.zeros((480, 640), np.uint8), time.monotonic(), 0),
                                     dict(state="running", fps=30))
                self.stop_event.wait()
        with tempfile.TemporaryDirectory() as directory, patch("sentio.runtime.Acquisition", FakeCapture):
            r = Runtime(source="camera", log_path=Path(directory)/"events.jsonl")
            r.start()
            try:
                time.sleep(.2)
                first = r.latest()
                self.assertTrue(first["input_fresh"])
                time.sleep(.3)
                last = r.latest()
                self.assertFalse(last["input_fresh"])
                self.assertIsNone(last["preview"])
                self.assertGreater(last["diagnostics"]["step"], first["diagnostics"]["step"])
                self.assertGreater(last["diagnostics"]["energy"], 0)
                r.mailbox.update_status(state="error", error="test disconnect")
                time.sleep(.1)
                self.assertEqual(r.latest()["capture"]["state"], "error")
            finally:
                r.close()
            self.assertFalse(r.capture.is_alive())

    def test_acquisition_continues_when_paused_observes_controls_and_closes(self):
        instances = []
        class FakeCamera:
            def __init__(self, *args):
                self.frames = 0
                self.info = {"card": "fake"}
                self.mode = {"fourcc": "YUYV", "fps": 30}
                self.controls = {"exposure_absolute": {"requested":156}}
                self.warnings, self.buffers = [], [None]*3
                self.closed = False
                instances.append(self)
            def read(self):
                time.sleep(.01)
                self.frames += 1
                return np.full((480, 640), 200, np.uint8), time.monotonic(), self.frames
            def read_controls(self):
                return {"exposure_absolute": 129}
            def stats(self):
                return dict(frames=self.frames, driver_drops=0, drained_discards=0, bad_frames=0)
            def close(self):
                self.closed = True
        with tempfile.TemporaryDirectory() as directory, patch("sentio.runtime.V4L2Camera", FakeCamera):
            r = Runtime(source="camera", log_path=Path(directory)/"events.jsonl")
            r.start()
            try:
                time.sleep(.2)
                r.submit("paused", True)
                time.sleep(.1)
                snap = r.latest()
                self.assertTrue(snap["paused"])
                frames, steps = snap["capture"]["frames"], snap["diagnostics"]["step"]
                time.sleep(.15)
                snap = r.latest()
                self.assertGreater(snap["capture"]["frames"], frames)
                self.assertEqual(snap["diagnostics"]["step"], steps)
                self.assertIn("effective 129", " ".join(snap["capture"]["warnings"]))
            finally:
                r.close()
            self.assertTrue(instances[0].closed)
            rows=[json.loads(line) for line in r.log.path.read_text().splitlines()]
            self.assertTrue(any(row["event"] == "camera_controls_observed" for row in rows))
            self.assertTrue(rows[-1]["capture_stopped"])
