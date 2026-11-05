"""Owner-testable synthetic research viewer; never opens a camera or checkpoints."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from sentio.gui import EnergyPlot, pixmap, signed_rgb
from .experiments import Case, SCHEDULES, make_field, patterns, provenance


def map_rgb(m):
    """Fixed 0..1 reinforcement scale, independent of its current extrema."""
    return (24+np.asarray(m)[..., None]*np.array([231, 190, 40])).astype(np.uint8)


class Viewer(QWidget):
    def __init__(self, case=Case()):
        super().__init__()
        self.case = case
        self.setWindowTitle("SENTIO issue #10 · synthetic reinforcement research")
        self.resize(1080, 800)
        self.setStyleSheet("QWidget { background:#10161f; color:#d9e3f0; font-size:13px; } "
                           "QPushButton,QComboBox { background:#253246; padding:6px; }")
        root = QVBoxLayout(self)
        title = QLabel("Synthetic wave + added reinforcement state · reduced dissipation is not recognition")
        title.setWordWrap(True)
        root.addWidget(title)
        controls = QHBoxLayout()
        self.model = QComboBox()
        self.model.addItems(("linear", "sextic"))
        self.model.setCurrentText(case.model)
        self.activity = QComboBox()
        self.activity.addItems(("fixed damping", "source", "wave"))
        self.activity.setCurrentText(case.activity if case.enabled else "fixed damping")
        self.history = QComboBox()
        self.history.addItems(tuple(SCHEDULES))
        self.history.setCurrentText(case.history)
        for widget in (self.model, self.activity, self.history):
            controls.addWidget(widget)
            widget.activated.connect(self.restart)
        self.pause = QCheckBox("Pause")
        controls.addWidget(self.pause)
        restart = QPushButton("Restart all state")
        restart.clicked.connect(self.restart)
        controls.addWidget(restart)
        root.addLayout(controls)
        self.settings = QLabel()
        self.settings.setWordWrap(True)
        root.addWidget(self.settings)
        images = QHBoxLayout()
        self.images = []
        for label in ("Actual signed wave u · fixed ±0.1 (blue / orange)",
                      "Actual reinforcement m · fixed 0..1 (dark / gold)"):
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            image = QLabel()
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setMinimumSize(350, 350)
            column.addWidget(image, 1)
            images.addLayout(column)
            self.images.append(image)
        root.addLayout(images, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.plot = EnergyPlot()
        root.addWidget(self.plot)
        probe_row = QHBoxLayout()
        self.retained = QPushButton("Standard probe: zero u/v, retain training m")
        self.erased = QPushButton("Standard probe: zero u/v, erase m")
        self.retained.clicked.connect(lambda: self.probe(True))
        self.erased.clicked.connect(lambda: self.probe(False))
        probe_row.addWidget(self.retained)
        probe_row.addWidget(self.erased)
        root.addLayout(probe_row)
        explanation = QLabel("Probe buttons explicitly reset wave energy and use the same two-spot input. "
                             "The retained map is the completed training map, not the preceding probe's map. "
                             "No camera, learned templates, automatic scale, or application checkpoint.")
        explanation.setWordWrap(True)
        root.addWidget(explanation)
        self.restart()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)

    def restart(self, *_):
        selected = self.activity.currentText()
        self.case = replace(self.case, model=self.model.currentText(),
                            activity="source" if selected == "fixed damping" else selected,
                            enabled=selected != "fixed damping", history=self.history.currentText())
        self.field = make_field(self.case)
        self.shapes, _ = patterns(self.case.n)
        self.training_map = None
        self.phase = "training"
        self.end = self.case.duration
        self.intervals = SCHEDULES[self.case.history]
        self.shape = self.shapes[self.case.shape]
        self.failure = ""
        self.pause.setChecked(False)
        self.retained.setEnabled(False)
        self.erased.setEnabled(False)
        self.begin_phase()

    def begin_phase(self):
        self.began = time.monotonic()
        self.plot.history = []
        self.settings.setText(f"{self.case.n}² · c=.3, γ₀=.4, κ=2 · η={self.case.eta:g}, "
                              f"λ={self.case.decay:g}, α={self.case.alpha:g}, γmin={self.case.gamma_min:g} · "
                              f"activity={self.case.activity if self.case.enabled else 'disabled'} · "
                              f"shape={self.case.shape}; histories have matched squared-source exposure")
        self.refresh()

    def probe(self, retain):
        if self.training_map is None:
            return
        self.field = make_field(self.case)
        if retain:
            self.field.m[:] = self.training_map
        self.field.rebase()
        self.phase = "probe, retained training m" if retain else "probe, erased m"
        self.end, self.intervals, self.shape = 4.0, ((0,.5),), self.shapes["probe"]
        self.failure = ""
        self.pause.setChecked(False)
        self.begin_phase()

    def tick(self):
        if self.pause.isChecked() or self.failure:
            return
        start = time.monotonic()
        target = min(self.field.wave.time+1/30, self.end)
        boundaries = sorted({self.end, *(t for pair in self.intervals for t in pair)})
        try:
            for _ in range(32):
                t = self.field.wave.time
                if t >= target-1e-12 or time.monotonic()-start > .008:
                    break
                next_event = min(b for b in boundaries if b > t+1e-12)
                source = .5*self.shape if any(a-1e-12 <= t < b-1e-12 for a,b in self.intervals) else None
                self.field.step(source, min(self.field.dt, target-t, next_event-t))
        except (ValueError, FloatingPointError, OverflowError) as exc:
            self.failure = str(exc)
            self.pause.setChecked(True)
        if self.field.wave.time >= self.end-1e-12:
            self.pause.setChecked(True)
            if self.phase == "training":
                self.training_map = self.field.m.copy()
                self.retained.setEnabled(True)
                self.erased.setEnabled(True)
        self.refresh()

    def refresh(self):
        f = self.field
        for label,rgb in zip(self.images, (signed_rgb(f.wave.u,.1,1), map_rgb(f.m))):
            side = min(label.width(), label.height())
            label.setPixmap(pixmap(rgb).scaled(side,side,Qt.AspectRatioMode.KeepAspectRatio))
        d = f.diagnostics()
        self.status.setText(f"{self.phase} · model t={f.wave.time:.3f} / {self.end:g} s · "
            f"{f.wave.time/max(time.monotonic()-self.began,1e-6):.3g} model s/wall s since phase start (includes pauses)\n"
            f"E={d['energy']:.6g}, work={d['input_work']:.6g}, loss={d['damping_loss']:.6g}, "
            f"balance residual={d['balance_residual']:.3g} · wave clipped {100*np.mean(np.abs(f.wave.u)>=.1):.2f}%\n"
            f"m mean/max={d['m_mean']:.4f}/{d['m_max']:.4f}; coverage m≥.1={100*d['coverage']:.2f}% · "
            f"local γ={d['gamma_min']:.4f}…{d['gamma_max']:.4f} (plus sponge)"+
            (f"\nFAULT: {self.failure}; restart required" if self.failure else ""))
        self.plot.history.append((f.wave.time,d["energy"]))
        self.plot.history = self.plot.history[-600:]
        self.plot.update()

    def closeEvent(self, event):
        self.timer.stop()
        event.accept()


def smoke(app, window, output, screenshot=None):
    """Real QWidget/event-loop protocol; offscreen runs are labeled as such."""
    checks = []
    def wait_for(predicate, timeout=50):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if window.failure:
                raise RuntimeError(window.failure)
            if predicate():
                return
            time.sleep(.005)
        raise TimeoutError("research viewer did not reach expected state")
    start = time.monotonic()
    failure = ""
    try:
        wait_for(lambda: window.field.wave.time > .1)
        window.pause.setChecked(True)
        before = [a.copy() for a in (window.field.wave.u,window.field.wave.v,window.field.m)]
        for _ in range(3):
            window.tick()
        for a,b in zip(before,(window.field.wave.u,window.field.wave.v,window.field.m)):
            np.testing.assert_array_equal(a,b)
        checks.append("pause preserves u/v/m")
        window.pause.setChecked(False)
        wait_for(lambda: window.training_map is not None)
        expected_map = window.case.enabled and window.case.history != "zero"
        assert bool(np.max(window.training_map)>0) == expected_map
        assert all(not label.pixmap().isNull() for label in window.images)
        checks.append("training completes with evolving field and separately rendered map")
        if screenshot:
            window.grab().save(str(screenshot))
        window.retained.click()
        assert not np.any(window.field.wave.u)
        np.testing.assert_array_equal(window.field.m,window.training_map)
        wait_for(lambda: window.pause.isChecked())
        retained = window.field.energy()
        window.erased.click()
        assert not np.any(window.field.wave.u) and not np.any(window.field.m)
        wait_for(lambda: window.pause.isChecked())
        erased = window.field.energy()
        checks.append("both identical probes run from zero wave state with retained/erased training map")
        window.restart()
        assert not np.any(window.field.m) and not np.any(window.field.wave.u)
        checks.append("restart clears all state")
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        retained = erased = None
    report = dict(metadata=provenance(), qt_platform=app.platformName(), visible=window.isVisible(),
                  case=window.case.__dict__, wall_seconds=time.monotonic()-start,
                  checks=checks, failure=failure, probe_final_energy=dict(retained=retained,erased=erased),
                  limitations="Automated Qt events; synthetic source only, no camera or physical keyboard testing.")
    window.close()
    app.processEvents()
    report["timer_stopped"] = not window.timer.isActive()
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    return int(bool(failure))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("linear","sextic"), default="linear")
    parser.add_argument("--activity", choices=("source","wave","fixed"), default="source")
    parser.add_argument("--history", choices=tuple(SCHEDULES), default="repeated")
    parser.add_argument("--shape", choices=("familiar","displaced","novel"), default="familiar")
    parser.add_argument("--grid", type=int, choices=(33,65,129,256), default=65)
    parser.add_argument("--smoke-output", type=Path)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    for path in (args.smoke_output,args.screenshot):
        if path:
            if path.exists():
                parser.error("output exists; use a new evidence path")
            path.parent.mkdir(parents=True,exist_ok=True)
    app = QApplication([])
    window = Viewer(Case(model=args.model, activity="source" if args.activity=="fixed" else args.activity,
                         enabled=args.activity!="fixed", history=args.history,shape=args.shape,n=args.grid))
    window.show()
    if args.smoke_output:
        return smoke(app,window,args.smoke_output,args.screenshot)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
