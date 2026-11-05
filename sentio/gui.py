"""Qt display of signed simulation values, with a separate optional Y preview."""

from collections import deque
from decimal import Decimal, InvalidOperation
import math
import queue
import time

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QLineEdit, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .inputs import SYNTHETIC_MODES
from .models import MODEL_LABELS


def signed_rgb(u, display_range, intensity):
    """Fixed symmetric range: negative blue, zero dark gray, positive orange."""
    # Clip before division: finite extreme controls cannot overflow u*intensity
    # or u/limit, nor erase a representable result through an intermediate zero.
    limit = display_range / intensity
    scaled = np.clip(u, -limit, limit) / limit
    positive = np.array([255, 127, 51]) - 24
    negative = np.array([65, 155, 255]) - 24
    # Preserve every cell and the exact color arithmetic, but avoid several
    # full-grid RGB float64 temporaries at larger resolutions.
    above, below = np.maximum(scaled, 0), np.maximum(-scaled, 0)
    rgb = np.empty((*u.shape, 3), dtype=np.uint8)
    for channel in range(3):
        rgb[..., channel] = 24 + above*positive[channel] + below*negative[channel]
    return rgb


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
        p.drawText(12, 20, "Field energy (includes local potential in sextic mode)")
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


class NumericEdit(QLineEdit):
    """An explicit draft, independent of focus and asynchronous effective state."""

    def __init__(self, value):
        super().__init__(repr(float(value)))
        self.setMaxLength(128)
        self.effective = value
        self.generation = 0
        self.dirty = False
        self.pending = None
        self.feedback = QLabel("Enter to apply · Escape to discard draft")
        self.feedback.setWordWrap(True)
        self.feedback.setStyleSheet("font-size: 11px; color: #a8bad1;")
        self.textEdited.connect(self.edited)

    def edited(self):
        self.generation += 1
        self.dirty = True
        self.feedback.setText(f"Draft · Enter to apply · effective {self.effective!r}")

    def parsed(self):
        try:
            decimal = Decimal(self.text().strip())
            value = float(decimal)
        except (InvalidOperation, ValueError, OverflowError) as exc:
            raise ValueError("enter a complete decimal number (scientific notation is allowed)") from exc
        if not math.isfinite(value):
            raise ValueError("enter a finite float64 number")
        if value == 0 and decimal != 0:
            raise ValueError("number underflows float64; enter a representable value")
        return value

    def synchronize(self, value, result=None):
        previous = self.effective
        self.effective = value
        acknowledged = False
        if self.pending and result and result["revision"] >= self.pending[0]:
            acknowledged = True
            _, submitted_generation = self.pending
            self.pending = None
            applied = result.get("value", value)
            if submitted_generation == self.generation:
                self.dirty = not result["accepted"]
                if result["accepted"]:
                    self.feedback.setText(f"Applied {applied!r}" +
                                          (f" · now effective {value!r}" if applied != value else ""))
                else:
                    self.feedback.setText(f"{result['message']} · effective {value!r}")
            else:
                outcome = f"Applied earlier {applied!r}" if result["accepted"] else result["message"]
                self.feedback.setText(f"{outcome} · effective {value!r} · draft retained; Enter to apply")
        if previous != value and not acknowledged and self.pending is None:
            self.feedback.setText(f"Effective {value!r}" + (" · draft retained; Enter to apply" if self.dirty else ""))
        if not self.dirty and self.pending is None:
            text = repr(float(value))
            if self.text() != text:
                self.setText(text)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.generation += 1
            self.dirty = False
            self.setText(repr(float(self.effective)))
            self.feedback.setText(f"Draft discarded · effective {self.effective!r}")
            return
        super().keyPressEvent(event)


class Window(QMainWindow):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime
        self.pending = {}
        self.setWindowTitle("SENTIO · Artificial Sensory Field · Prototype 1")
        self.resize(1180, 850)
        self.setStyleSheet("QWidget { background: #10161f; color: #d9e3f0; font-size: 13px; } "
                           "QPushButton, QLineEdit, QComboBox { background: #253246; padding: 5px; } "
                           "QLabel { background: transparent; }")
        root = QWidget()
        self.setCentralWidget(root)
        row = QHBoxLayout(root)
        left = QVBoxLayout()
        row.addLayout(left, 3)
        panel = QWidget()
        right = QVBoxLayout(panel)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(470)
        row.addWidget(scroll, 2)
        title = QLabel("SENTIO / evolving signed scalar field")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        left.addWidget(title)
        self.live_status = QLabel()
        self.live_status.setWordWrap(True)
        left.addWidget(self.live_status)
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
        self.model_combo = QComboBox()
        for key, label in MODEL_LABELS.items():
            self.model_combo.addItem(label, key)
        self.model_combo.setCurrentIndex(self.model_combo.findData(runtime.engine.model))
        self.model_combo.activated.connect(lambda index: self.send("model", self.model_combo.itemData(index)))
        right.addWidget(self.model_combo)
        transition = QLabel("Changing model resets field and model settings, pauses, and turns coupling off. Display range is retained.")
        transition.setWordWrap(True)
        right.addWidget(transition)
        if runtime.engine.source != "camera":
            self.source_combo = QComboBox()
            self.source_combo.addItems(SYNTHETIC_MODES)
            self.source_combo.setCurrentText(runtime.engine.source)
            self.source_combo.currentTextChanged.connect(lambda v: self.send("source", v))
            right.addWidget(self.source_combo)
        form = QFormLayout()
        self.controls = {}
        physical = runtime.engine.field.parameters
        nonlinear = getattr(runtime.engine.field, "nonlinear", None)
        for key, label, value in (
            ("speed", "Wave speed (domain units / s)", physical.speed),
            ("damping", "Damping (1 / s)", physical.damping),
            ("coupling", "Input acceleration gain", physical.coupling),
            ("omega", "Sextic ω (1 / model s)", nonlinear.omega if nonlinear else 8),
            ("amplitude", "Sextic amplitude scale A", nonlinear.amplitude if nonlinear else .1),
            ("display_range", "Display range (± field units)", runtime.engine.display_range),
            ("intensity", "Display intensity", runtime.engine.intensity),
        ):
            if key in ("speed", "display_range"):
                form.addRow(QLabel("Physical simulation" if key == "speed" else "Display only (no field changes)"))
            edit = NumericEdit(value)
            edit.returnPressed.connect(lambda k=key: self.commit_numeric(k))
            domain = "nonnegative" if key in ("damping", "coupling") else "strictly positive"
            edit.setToolTip(f"Finite, {domain}. Type a decimal or scientific notation, then Enter. "
                            "Numerically unrepresentable or infeasible settings are rejected; no silent clamping.")
            if key in ("omega", "amplitude"):
                edit.setEnabled(runtime.engine.model == "sextic")
            self.controls[key] = edit
            cell = QVBoxLayout()
            cell.addWidget(edit)
            cell.addWidget(edit.feedback)
            form.addRow(label, cell)
        right.addLayout(form)
        self.coupling = QCheckBox("Enable input coupling")
        self.coupling.setChecked(runtime.engine.coupling_enabled)
        self.coupling.toggled.connect(lambda v: self.send("coupling_enabled", v))
        right.addWidget(self.coupling)
        self.pause = QCheckBox("Pause field (acquisition continues)")
        self.pause.setChecked(runtime.engine.paused)
        self.pause.toggled.connect(lambda v: self.send("paused", v))
        right.addWidget(self.pause)
        buttons = QHBoxLayout()
        for label, action in (("Reset field", lambda: self.send("reset")),
                               ("Save state…", self.save), ("Restore…", self.restore)):
            button = QPushButton(label)
            button.clicked.connect(action)
            buttons.addWidget(button)
        right.addLayout(buttons)
        self.seed = QPushButton("Reset to explicit Gaussian seed control (coupling off)")
        self.seed.setEnabled(runtime.engine.model == "sextic")
        self.seed.clicked.connect(lambda: self.send("seed"))
        right.addWidget(self.seed)
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
            return revision
        except queue.Full:
            self.notice.setText("Control queue full; retry when the simulation responds.")

    def commit_numeric(self, key):
        edit = self.controls[key]
        try:
            value = edit.parsed()
        except ValueError as exc:
            edit.dirty = True
            edit.feedback.setText(f"Rejected: {exc} · effective {edit.effective!r}")
            return
        revision = (self.send("parameters", {key: value}) if key in
                    ("speed", "damping", "coupling", "omega", "amplitude") else self.send(key, value))
        if revision is not None:
            edit.pending = (revision, edit.generation)
            edit.feedback.setText(f"Applying {value!r}… · effective {edit.effective!r}")
        else:
            edit.feedback.setText("Queue full; draft retained. Press Enter to retry.")

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
        self.setWindowTitle(f"SENTIO · {snap['grid']}×{snap['grid']} · {MODEL_LABELS[snap['model']]} · {snap['source']}")
        if "model" not in self.pending:
            self.model_combo.setCurrentIndex(self.model_combo.findData(snap["model"]))
        self.seed.setEnabled(snap["model"] == "sextic")
        for key, widget in self.controls.items():
            if key in ("omega", "amplitude"):
                widget.setEnabled(snap["model"] == "sextic")
                if snap["model"] != "sextic":
                    continue
            widget.synchronize(snap["parameters"].get(key, snap["nonlinear"].get(key, snap.get(key))),
                               snap["control_results"].get(key))
        for key, widget in (("paused", self.pause), ("coupling_enabled", self.coupling),
                            ("preview_enabled", self.preview_toggle)):
            if key not in self.pending:
                self.sync(widget, snap[key])
        state = "FAULT" if snap["fault"] else "PAUSED" if snap["paused"] else "FINITE"
        self.live_status.setText(
            f"{MODEL_LABELS[snap['model']]} · {state} · {snap['grid']}×{snap['grid']} field\n"
            f"Camera / source {c.get('fps', 0):.2f} FPS · simulation {snap['steps_per_second']:.1f} steps/s · "
            f"{snap['sim_speed']:.4g} model s/wall s · display {render_fps:.1f} FPS")
        memory = snap["memory"]
        memory_text = (f"Process RSS {memory['resident_mib']:.1f} MiB · peak {memory['peak_resident_mib']:.1f} MiB"
                       if all(v is not None for v in memory.values()) else "Process memory unavailable")
        nonlinear = ""
        if snap["model"] == "sextic":
            nonlinear = (f"Effective ω {snap['nonlinear']['omega']:g} · A {snap['nonlinear']['amplitude']:g}\n"
                         f"Local potential E {d['local_potential']:.5g} · wave/curvature {d['wave_curvature_number']:.3f} ≤ 1.6\n"
                         f"Validity |u| ≤ 4A = {d['envelope']:.5g} · {100*d['envelope_fraction']:.1f}% used"
                         " (separate from display clipping)\n"
                         f"Input work {d['input_work']:.5g} · damping loss {d['damping_loss']:.5g}\n"
                         f"Parameter work {d['parameter_work']:.5g} · balance residual {d['balance_residual']:.3g}\n")
        self.diagnostics.setText(
            f"{MODEL_LABELS[snap['model']]} · {state}\n"
            f"Grid {snap['grid']}×{snap['grid']} · unit square · dx {d['dx']:.6g}\n"
            f"Restart with --grid 256 / 512 / 1024 to change resolution\n"
            f"{memory_text}\n"
            f"Step {d['step']:,} · simulated {d['simulation_time']:.2f} s\n"
            f"Signed u [{snap['u'].min():.5g}, {snap['u'].max():.5g}]\n"
            f"Peak |u| {d['peak']:.5g} · peak |v| {d['velocity_peak']:.5g}\n"
            f"Field energy {d['energy']:.6g} (not conserved with forcing / damping)\n"
            + nonlinear +
            f"dt {d['dt']:.6g} s · CFL {d['cfl']:.3f} ≤ 0.566\n"
            f"Simulation {snap['steps_per_second']:.1f} steps/s · {snap['sim_speed']:.4g} sim s/wall s\n"
            f"Acquisition {c.get('fps', 0):.2f} FPS · display {render_fps:.1f} FPS\n"
            f"Driver drops {c.get('driver_drops', 0)} · bad frames {c.get('bad_frames', 0)}\n"
            f"Latest-frame discards {c.get('mailbox_discards', 0) + c.get('drained_discards', 0)}\n"
            f"Input {'fresh' if snap['input_fresh'] else 'absent / stale → zero force'} · "
            f"{'coupled' if snap['coupling_enabled'] else 'coupling off'} · age {1000*snap['input_age']:.1f} ms\n"
            f"Wall time skipped under load {snap['skipped_wall_seconds']:.3f} s")
        warnings = list(c.get("warnings", []))
        if not snap["paused"] and snap["wall_seconds"] > 3 and snap["sim_speed"] < .9:
            warnings.append("Simulation slower than wall time; use measured model time for comparisons.")
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
