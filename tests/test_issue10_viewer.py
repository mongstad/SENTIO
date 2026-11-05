"""Actual research QWidget behavior; no camera access."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
import numpy as np
from PySide6.QtWidgets import QApplication

from research.issue_10.experiments import Case
from research.issue_10.viewer import Viewer, map_rgb


class ResearchViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_fixed_scale_and_separate_state(self):
        m=np.array([[0.,.5,1.]])
        before=m.copy()
        rgb=map_rgb(m)
        np.testing.assert_array_equal(rgb[0,0],[24,24,24])
        np.testing.assert_array_equal(rgb[0,2],[255,214,64])
        np.testing.assert_array_equal(m,before)
        np.testing.assert_array_equal(map_rgb(np.array([[.5]]))[0,0],rgb[0,1])

    def test_pause_restart_model_selection_and_explicit_probe_intervention(self):
        window=Viewer(Case(n=33))
        window.timer.stop()
        window.show()
        try:
            for _ in range(10):
                window.tick()
            self.assertGreater(window.field.m.max(),0)
            self.assertGreater(window.field.energy(),0)
            window.pause.setChecked(True)
            before=(window.field.wave.u.copy(),window.field.wave.v.copy(),window.field.m.copy())
            window.tick()
            for a,b in zip(before,(window.field.wave.u,window.field.wave.v,window.field.m)):
                np.testing.assert_array_equal(a,b)
            self.assertFalse(window.retained.isEnabled())
            window.training_map=window.field.m.copy()
            window.probe(True)
            self.assertFalse(np.any(window.field.wave.u))
            self.assertFalse(np.any(window.field.wave.v))
            np.testing.assert_array_equal(window.field.m,before[2])
            window.tick()
            window.probe(False)
            self.assertFalse(np.any(window.field.m))
            self.assertEqual(window.field.wave.time,0)
            window.model.setCurrentText("sextic")
            window.activity.setCurrentText("wave")
            window.restart()
            self.assertEqual(window.field.model,"sextic")
            self.assertEqual(window.field.rule.activity,"wave")
            self.assertIsNone(window.training_map)
            window.activity.setCurrentText("fixed damping")
            window.restart()
            window.tick()
            self.assertFalse(window.field.enabled)
            self.assertFalse(np.any(window.field.m))
            self.assertFalse(window.failure)
            self.assertTrue(all(not image.pixmap().isNull() for image in window.images))
        finally:
            window.close()
        self.assertFalse(window.timer.isActive())
