"""Qt display of signed simulation values, with a separate optional Y preview."""

from collections import deque
import queue
import time

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .inputs import SYNTHETIC_MODES


def signed_rgb(u, display_range, intensity):
    """Fixed symmetric range: negative blue, zero dark gray, positive orange."""
    scaled = np.clip(u * intensity / display_range, -1, 1)
    base = np.full((*u.shape, 3), 24.0)
    positive = np.array([255, 127, 51]) - 24
    negative = np.array([65, 155, 255]) - 24
    return (base + np.maximum(scaled, 0)[..., None] * positive
            + np.maximum(-scaled, 0)[..., None] * negative).astype(np.uint8)


def pixmap(rgb):
    rgb = np.ascontiguousarray(rgb)
    image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(image)


class EnergyPlot(QWidget):
    def __init__(self):
        super().__init__()
        self.history = []
        self.setMinimumHeight(145)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#141b25"))
        p.setPen(QColor("#c8d4e3"))
        p.drawText(12, 20, "Discrete wave energy (not conserved with input / damping)")
        if not self.history:
            return
        t0, t1 = self.history[0][0], self.history[-1][0]
        high = max(e for _, e in self.history) or 1e-12
        p.drawText(12, 40, f"0 … {high:.4g}   |   simulation time {t0:.1f} … {t1:.1f} s")
        points = [QPointF(12 + (t - t0) / max(t1-t0, 1e-12) * (self.width()-24),
                          self.height()-12 - e/high * (self.height()-65)) for t, e in self.history]
        p.setPen(QPen(QColor("#69dbc7"), 2))
        for a, b in zip(points, points[1:]):
            p.drawLine(a, b)


class Window(QMainWindow):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime
        self.pending = {}
        self.setWindowTitle("SENTIO · Artificial Sensory Field · Prototype 1")
        self.resize(1180, 850)
        self.setStyleSheet("QWidget { background: #10161f; color: #d9e3f0; font-size: 13px; } "
                           "QPushButton, QDoubleSpinBox, QComboBox { background: #253246; padding: 5px; } "
                           "QLabel { background: transparent; }")
        root = QWidget()
        self.setCentralWidget(root)
        row = QHBoxLayout(root)
        left, right = QVBoxLayout(), QVBoxLayout()
        row.addLayout(left, 3)
        row.addLayout(right, 2)
        title = QLabel("SENTIO / evolving signed scalar field")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        left.addWidget(title)
        self.field_image = QLabel()
        self.field_image.setMinimumSize(400, 400)
        self.field_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.field_image, 1)
        self.legend = QLabel()
        self.legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.legend)
        self.plot = EnergyPlot()
        left.addWidget(self.plot)
        self.source_label = QLabel()
        self.source_label.setWordWrap(True)
        right.addWidget(self.source_label)
        if runtime.engine.source != "camera":
            self.source_combo = QComboBox()
            self.source_combo.addItems(SYNTHETIC_MODES)
            self.source_combo.setCurrentText(runtime.engine.source)
            self.source_combo.currentTextChanged.connect(lambda v: self.send("source", v))
            right.addWidget(self.source_combo)
        form = QFormLayout()
        self.controls = {}
        for key, label, low, high, step, value in (
            ("speed", "Wave speed (domain units / s)", .01, 2, .05, .3),
            ("damping", "Damping (1 / s)", 0, 10, .1, .4),
            ("coupling", "Input acceleration gain", 0, 20, .1, 2),
            ("display_range", "Display range (± field units)", .0001, 10000, .05, runtime.engine.display_range),
            ("intensity", "Display intensity", .01, 100, .1, 1),
        ):
            spin = QDoubleSpinBox()
            spin.setDecimals(4)
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setValue(value)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda v, k=key: self.send("parameters", {k:v}) if k in ("speed", "damping", "coupling") else self.send(k, v))
            self.controls[key] = spin
            form.addRow(label, spin)
        right.addLayout(form)
        self.coupling = QCheckBox("Enable input coupling")
        self.coupling.setChecked(True)
        self.coupling.toggled.connect(lambda v: self.send("coupling_enabled", v))
        right.addWidget(self.coupling)
        self.pause = QCheckBox("Pause field (acquisition continues)")
        self.pause.toggled.connect(lambda v: self.send("paused", v))
        right.addWidget(self.pause)
        buttons = QHBoxLayout()
        for label, action in (("Reset field", lambda: self.send("reset")),
                               ("Save state…", self.save), ("Restore…", self.restore)):
            button = QPushButton(label)
            button.clicked.connect(action)
            buttons.addWidget(button)
        right.addLayout(buttons)
        self.diagnostics = QLabel()
        self.diagnostics.setWordWrap(True)
        self.diagnostics.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(self.diagnostics)
        self.preview_toggle = QCheckBox("Show measured camera luminance (diagnostic only)")
        self.preview_toggle.setEnabled(runtime.engine.source == "camera")
        self.preview_toggle.toggled.connect(lambda v: self.send("preview_enabled", v))
        right.addWidget(self.preview_toggle)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(self.preview)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet("color: #f3cd85;")
        right.addWidget(self.notice)
        log_label = QLabel(f"Scalar diagnostics / controls: {runtime.log.path}\nNo camera frames are saved.")
        log_label.setWordWrap(True)
        right.addWidget(log_label)
        right.addStretch()
        self.render_times = deque(maxlen=90)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(33)

    def send(self, name, value=None):
        try:
            revision = self.runtime.submit(name, value)
            for key in (value.keys() if name == "parameters" else (name,)):
                self.pending[key] = revision
        except queue.Full:
            self.notice.setText("Control queue full; retry when the simulation responds.")

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save simulation state (no camera data)", "field-state.npz", "NumPy checkpoint (*.npz)")
        if path:
            self.send("save", path if path.endswith(".npz") else path + ".npz")

    def restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore simulation state; resumes paused", "", "NumPy checkpoint (*.npz)")
        if path:
            self.send("load", path)

    @staticmethod
    def sync(widget, value):
        widget.blockSignals(True)
        if isinstance(widget, QCheckBox):
            widget.setChecked(value)
        else:
            widget.setValue(value)
        widget.blockSignals(False)

    def refresh(self):
        snap = self.runtime.latest()
        if self.runtime.failure:
            self.notice.setText(f"Runtime stopped: {self.runtime.failure}")
            return
        if snap is None:
            return
        now = time.monotonic()
        self.render_times.append(now)
        render_fps = (len(self.render_times)-1) / max(now-self.render_times[0], 1e-6)
        d, c = snap["diagnostics"], snap["capture"]
        self.pending = {key:revision for key,revision in self.pending.items()
                        if revision > snap["command_revision"]}
        image = pixmap(signed_rgb(snap["u"], snap["display_range"], snap["intensity"]))
        side = min(self.field_image.width(), self.field_image.height())
        self.field_image.setPixmap(image.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.FastTransformation))
        limit = snap["display_range"] / snap["intensity"]
        saturation = np.mean(np.abs(snap["u"]) >= limit) * 100
        self.legend.setText(f"Blue −{limit:.4g}   ·   dark 0   ·   orange +{limit:.4g}   |   clipped {saturation:.2f}%")
        self.source_label.setText("LIVE CAMERA · processed luminance → acceleration" if snap["source"] == "camera"
                                  else f"SYNTHETIC CONTROL · {snap['source']} (no webcam)")
        for key, widget in self.controls.items():
            if not widget.hasFocus() and key not in self.pending:
                self.sync(widget, snap["parameters"].get(key, snap.get(key)))
        for key, widget in (("paused", self.pause), ("coupling_enabled", self.coupling),
                            ("preview_enabled", self.preview_toggle)):
            if key not in self.pending:
                self.sync(widget, snap[key])
        state = "FAULT" if snap["fault"] else "PAUSED" if snap["paused"] else "FINITE"
        self.diagnostics.setText(
            f"{state} · step {d['step']:,} · simulated {d['simulation_time']:.2f} s\n"
            f"Peak |u| {d['peak']:.5g} · peak |v| {d['velocity_peak']:.5g}\n"
            f"Wave energy {d['energy']:.6g}\n"
            f"dt {d['dt']:.6f} s · CFL {d['cfl']:.3f} ≤ 0.566\n"
            f"Simulation {snap['steps_per_second']:.1f} steps/s · {snap['sim_speed']:.2f} sim s/wall s\n"
            f"Acquisition {c.get('fps', 0):.2f} FPS · display {render_fps:.1f} FPS\n"
            f"Driver drops {c.get('driver_drops', 0)} · bad frames {c.get('bad_frames', 0)}\n"
            f"Latest-frame discards {c.get('mailbox_discards', 0) + c.get('drained_discards', 0)}\n"
            f"Input {'fresh' if snap['input_fresh'] else 'absent / stale → zero force'} · "
            f"{'coupled' if snap['coupling_enabled'] else 'coupling off'}\n"
            f"Wall time skipped under load {snap['skipped_wall_seconds']:.3f} s")
        warnings = list(c.get("warnings", []))
        if snap["source"] == "camera":
            if "mode" in c:
                mode = c["mode"]
                warnings.insert(0, f"{mode['fourcc']} {mode['width']}×{mode['height']} @ {mode['fps']:g} negotiated")
            if snap["wall_seconds"] > 3 and c.get("fps", 0) < 28:
                warnings.append("Measured camera rate below 28 FPS; inspect exposure / USB load.")
            if c.get("timestamp_kind", "").startswith("receipt"):
                warnings.append("Driver capture age unknown; freshness uses receipt time.")
        self.notice.setText("\n".join(filter(None, [snap["fault"], c.get("error", ""), *warnings, snap["message"]])))
        if self.preview_toggle.isChecked() and snap["preview"] is not None:
            y = snap["preview"]
            self.preview.setPixmap(pixmap(np.repeat(y[..., None], 3, axis=2)).scaledToWidth(240))
            self.preview.show()
        else:
            self.preview.clear()
            self.preview.hide()
        self.plot.history = snap["history"]
        self.plot.update()

    def closeEvent(self, event):
        self.timer.stop()
        try:
            self.runtime.close()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Shutdown", str(exc))
        event.accept()
