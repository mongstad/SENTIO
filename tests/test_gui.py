import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import time
import unittest

import numpy as np
from PySide6.QtWidgets import QApplication
from sentio.gui import Window, signed_rgb
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

    def test_signed_rendering_uses_fixed_scale_without_mutation(self):
        u = np.array([[-2., -1., 0., 1., 2.]])
        before = u.copy()
        rgb = signed_rgb(u, 1, 1)
        np.testing.assert_array_equal(rgb[0, 0], [65, 155, 255])
        np.testing.assert_array_equal(rgb[0, 2], [24, 24, 24])
        np.testing.assert_array_equal(rgb[0, 4], [255, 127, 51])
        np.testing.assert_array_equal(rgb[0, 0], rgb[0, 1])
        np.testing.assert_array_equal(u, before)

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
                window.controls["display_range"].setValue(2)
                window.controls["intensity"].setValue(3)
                self.wait_for(lambda: runtime.latest()["intensity"] == 3)
                np.testing.assert_array_equal(runtime.latest()["u"], before)
                window.controls["speed"].setValue(2)
                window.controls["damping"].setValue(10)
                window.controls["coupling"].setValue(20)
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
