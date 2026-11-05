import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from sentio.gui import NumericEdit, Window, signed_rgb
from sentio.runtime import Runtime


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate, timeout=3):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.01)
        self.fail("GUI state did not settle")

    @staticmethod
    def type_value(widget, text, commit=True):
        widget.setFocus()
        widget.selectAll()
        if str(text):
            QTest.keyClicks(widget, str(text))
        else:
            QTest.keyClick(widget, Qt.Key.Key_Backspace)
        if commit:
            QTest.keyClick(widget, Qt.Key.Key_Return)

    def test_signed_rendering_uses_fixed_scale_without_mutation(self):
        u = np.array([[-2., -1., 0., 1., 2.]])
        before = u.copy()
        rgb = signed_rgb(u, 1, 1)
        np.testing.assert_array_equal(rgb[0, 0], [65, 155, 255])
        np.testing.assert_array_equal(rgb[0, 2], [24, 24, 24])
        np.testing.assert_array_equal(rgb[0, 4], [255, 127, 51])
        np.testing.assert_array_equal(rgb[0, 0], rgb[0, 1])
        np.testing.assert_array_equal(u, before)

    def test_large_grid_colors_match_original_mapping_exactly(self):
        u = np.random.default_rng(8).uniform(-.5, .5, (1024, 1024))
        scaled = np.clip(u*1.3/.2, -1, 1)
        original = (np.full((*u.shape, 3), 24.0)
                    + np.maximum(scaled, 0)[..., None]*(np.array([255, 127, 51])-24)
                    + np.maximum(-scaled, 0)[..., None]*(np.array([65, 155, 255])-24)).astype(np.uint8)
        np.testing.assert_array_equal(signed_rgb(u, .2, 1.3), original)

    def test_extreme_display_arithmetic_preserves_signed_colors(self):
        for display_range, intensity, u in (
            (1e308, 1e308, np.array([[-1e6, 0, 1e6]])),
            (1e-300, 1, np.array([[-1e6, 0, 1e6]])),
            (1e-300, 1e-300, np.array([[-.5, 0, .5]])),
        ):
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                colors = signed_rgb(u, display_range, intensity)
            np.testing.assert_array_equal(colors[0, 1], [24, 24, 24])
            self.assertGreater(colors[0, 0, 2], colors[0, 0, 0])
            self.assertGreater(colors[0, 2, 0], colors[0, 2, 2])

    def test_delayed_acknowledgement_preserves_newer_draft_and_rejection(self):
        edit = NumericEdit(.3)
        self.type_value(edit, "3", commit=False)
        edit.pending = (1, edit.generation)
        self.type_value(edit, "4e", commit=False)
        edit.clearFocus()
        edit.synchronize(.3)
        self.assertEqual(edit.text(), "4e")
        edit.synchronize(3, dict(revision=1, accepted=True, message="Applied parameters"))
        self.assertEqual(edit.text(), "4e")
        self.assertIn("draft retained", edit.feedback.text())
        edit.synchronize(2)  # External model reset/restore while draft remains.
        self.assertEqual(edit.text(), "4e")
        self.type_value(edit, "0", commit=False)
        edit.pending = (2, edit.generation)
        edit.synchronize(2, dict(revision=2, accepted=False, message="Rejected: positive speed required"))
        self.assertEqual(edit.text(), "0")
        self.assertIn("Rejected", edit.feedback.text())
        QTest.keyClick(edit, Qt.Key.Key_Escape)
        self.assertEqual(float(edit.text()), 2)
        self.type_value(edit, "0.12345678901234567", commit=False)
        edit.pending = (3, edit.generation)
        value = edit.parsed()
        edit.synchronize(value, dict(revision=3, accepted=True, message="Applied"))
        self.assertEqual(float(edit.text()), value)
        self.assertFalse(edit.dirty)
        edit.selectAll()
        edit.synchronize(value)
        self.assertEqual(edit.selectedText(), edit.text())
        # A model transition can follow acceptance before Qt sees a snapshot.
        self.type_value(edit, "3", commit=False)
        edit.pending = (4, edit.generation)
        edit.synchronize(.3, dict(revision=4, accepted=True, value=3, message="Applied"))
        self.assertEqual(float(edit.text()), .3)
        self.assertIn("Applied 3", edit.feedback.text())
        self.assertIn("now effective 0.3", edit.feedback.text())

    def test_enter_domains_feedback_and_refresh_do_not_lose_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(model="sextic", log_path=Path(directory)/"entry.jsonl")
            runtime.engine.paused = True
            window = Window(runtime)
            runtime.start()
            window.show()
            try:
                self.wait_for(lambda: runtime.latest() is not None)
                for key, values in (("speed", (.001, 3)), ("damping", (0, 11)),
                                    ("coupling", (0, 21)), ("display_range", (1e-6, 1e5)),
                                    ("intensity", (1e-4, 1e3)), ("omega", (1e-5, 8)),
                                    ("amplitude", (1e-5, 1e5))):
                    edit = window.controls[key]
                    for value in values:
                        previous = runtime.command_sequence
                        self.type_value(edit, value, commit=False)
                        window.refresh()
                        self.assertEqual(runtime.command_sequence, previous)
                        QTest.keyClick(edit, Qt.Key.Key_Enter)
                        self.wait_for(lambda: edit.pending is None and not edit.dirty)
                        self.assertEqual(edit.effective, value)
                        self.assertIn("Applied", edit.feedback.text())
                for key in ("speed", "display_range", "intensity"):
                    edit = window.controls[key]
                    effective = edit.effective
                    for text in ("", "-", "1e", "nan", "inf", "1e999", "1e-999", "0", "-1"):
                        self.type_value(edit, text)
                        self.wait_for(lambda: "Rejected" in edit.feedback.text())
                        window.controls["damping"].setFocus()
                        window.refresh()
                        self.assertEqual(edit.text(), text)
                        self.assertEqual(edit.effective, effective)
                edit = window.controls["speed"]
                self.type_value(edit, "1e100")
                # An unrelated command must not hide this field's rejection.
                window.send("paused", True)
                self.wait_for(lambda: edit.pending is None)
                self.assertIn("infeasible", edit.feedback.text())
                self.assertEqual(edit.effective, 3)
                snapshot = runtime.latest().copy()
                snapshot["epoch"] += 1
                snapshot["parameters"] = dict(snapshot["parameters"], speed=.3)
                with patch.object(runtime, "latest", return_value=snapshot):
                    window.refresh()
                self.assertEqual(edit.text(), "1e100")
                self.assertEqual(edit.effective, .3)
                self.assertFalse(np.any(runtime.latest()["u"]))
            finally:
                window.close()
                self.app.processEvents()
            self.assertFalse(runtime.failure)

    def test_repeated_window_launches_show_runtime_defaults_before_start(self):
        with tempfile.TemporaryDirectory() as directory:
            for index, model in enumerate(("linear", "sextic", "linear")):
                runtime = Runtime(model=model, log_path=Path(directory)/f"launch-{index}.jsonl")
                window = Window(runtime)
                try:
                    for key, value in dict(speed=.3, damping=.4, coupling=2,
                                           display_range=2, intensity=1).items():
                        self.assertEqual(float(window.controls[key].text()), value)
                    self.assertTrue(window.coupling.isChecked())
                    self.assertFalse(window.pause.isChecked())
                    self.assertEqual(runtime.engine.field.step_count, 0)
                    runtime.engine.command("parameters", {"speed": 3})
                    runtime.engine.command("display_range", 1e5)
                finally:
                    window.close()

    def test_queue_full_retains_draft_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(log_path=Path(directory)/"queue.jsonl")
            window = Window(runtime)
            try:
                for _ in range(128):
                    runtime.submit("paused", True)
                edit = window.controls["speed"]
                self.type_value(edit, "3.14159")
                self.assertEqual(edit.text(), "3.14159")
                self.assertTrue(edit.dirty)
                self.assertIsNone(edit.pending)
                self.assertIn("Queue full", edit.feedback.text())
            finally:
                window.close()

    def test_sextic_typed_controls_transitions_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(model="sextic", log_path=Path(directory)/"sextic-gui.jsonl")
            window = Window(runtime)
            runtime.start()
            window.show()
            try:
                self.wait_for(lambda: runtime.latest() is not None and runtime.latest()["diagnostics"]["step"] > 10)
                self.assertIn("Soft sextic", window.windowTitle())
                self.assertIn("Validity |u|", window.diagnostics.text())
                omega = window.controls["omega"]
                omega.setFocus()
                omega.selectAll()
                QTest.keyClicks(omega, "12")
                self.assertEqual(runtime.latest()["nonlinear"]["omega"], 8)
                QTest.keyClick(omega, Qt.Key.Key_Return)
                self.wait_for(lambda: runtime.latest()["nonlinear"]["omega"] == 12)
                window.seed.click()
                self.wait_for(lambda: runtime.latest()["paused"] and runtime.latest()["parameters"]["coupling"] == 0)
                self.wait_for(lambda: float(omega.text()) == 8)
                before = runtime.latest()["u"].copy()
                amplitude = window.controls["amplitude"]
                self.type_value(amplitude, .001)
                self.wait_for(lambda: "Rejected parameters" in runtime.latest()["message"])
                self.assertEqual(runtime.latest()["nonlinear"]["amplitude"], .1)
                np.testing.assert_array_equal(runtime.latest()["u"], before)
                checkpoint = str(Path(directory)/"gui.npz")
                window.send("save", checkpoint)
                self.wait_for(lambda: Path(checkpoint).exists())
                index = window.model_combo.findData("linear")
                window.model_combo.activated.emit(index)
                self.wait_for(lambda: runtime.latest()["model"] == "linear")
                self.assertTrue(runtime.latest()["paused"])
                self.assertFalse(runtime.latest()["coupling_enabled"])
                self.wait_for(lambda: not omega.isEnabled())
                self.assertIn("model s/wall s", window.live_status.text())
                window.send("load", checkpoint)
                self.wait_for(lambda: runtime.latest()["model"] == "sextic")
                np.testing.assert_array_equal(runtime.latest()["u"], before)
                self.wait_for(lambda: omega.isEnabled())
            finally:
                window.close()
                self.app.processEvents()
            self.assertFalse(runtime.failure)

    def test_live_widgets_pause_hot_controls_reset_and_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(log_path=Path(directory)/"gui.jsonl")
            window = Window(runtime)
            runtime.start()
            window.show()
            try:
                self.wait_for(lambda: runtime.latest() is not None and runtime.latest()["diagnostics"]["step"] > 10)
                window.pause.setChecked(True)
                self.wait_for(lambda: runtime.latest()["paused"])
                before = runtime.latest()["u"].copy()
                self.type_value(window.controls["display_range"], 2)
                self.type_value(window.controls["intensity"], 3)
                self.wait_for(lambda: runtime.latest()["intensity"] == 3)
                np.testing.assert_array_equal(runtime.latest()["u"], before)
                self.type_value(window.controls["speed"], 2)
                self.type_value(window.controls["damping"], 10)
                self.type_value(window.controls["coupling"], 20)
                self.wait_for(lambda: runtime.latest()["parameters"]["coupling"] == 20)
                self.assertLess(runtime.latest()["diagnostics"]["dt"], 1/240)
                window.coupling.setChecked(False)
                self.wait_for(lambda: not runtime.latest()["coupling_enabled"])
                window.pause.setChecked(False)
                self.wait_for(lambda: not runtime.latest()["paused"])
                self.wait_for(lambda: not np.array_equal(runtime.latest()["u"], before))
                window.pause.setChecked(True)
                self.wait_for(lambda: runtime.latest()["paused"])
                window.send("reset")
                self.wait_for(lambda: runtime.latest()["diagnostics"]["step"] == 0)
                self.assertFalse(np.any(runtime.latest()["u"]))
                self.assertFalse(window.field_image.pixmap().isNull())
            finally:
                window.close()
                self.app.processEvents()
            self.assertFalse(runtime.is_alive())
            self.assertFalse(runtime.failure)
