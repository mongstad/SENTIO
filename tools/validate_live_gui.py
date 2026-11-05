"""Focused visible GUI smoke protocol, real camera by default; scalar evidence only.

Run from a desktop terminal. No offscreen fallback and no camera image saving.
The optional screenshot contains the field/UI only (preview remains disabled).
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sentio.gui import Window
from sentio.runtime import Runtime
from sentio.grid import DEFAULT_GRID, GRID_SIZES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("camera", "stationary"), default="camera")
    parser.add_argument("--grid", type=int, choices=GRID_SIZES, default=DEFAULT_GRID)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--leave-open", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new evidence path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    if app.platformName() in ("offscreen", "minimal"):
        parser.error("this protocol requires a visible desktop Qt platform")
    runtime = Runtime(source=args.source, model="sextic", grid=args.grid)
    window = Window(runtime)
    measurements, controls, checks = {}, [], []
    failure = ""

    def wait_for(predicate, timeout=5):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if runtime.failure:
                raise RuntimeError(runtime.failure)
            if predicate():
                return
            time.sleep(.01)
        raise AssertionError("GUI acknowledgement/state timed out")

    def command(name, value=None, widget_action=None, accepted=True):
        start = time.monotonic()
        prior = runtime.command_sequence
        (widget_action or (lambda: window.send(name, value)))()
        wait_for(lambda: runtime.command_sequence > prior and
                 runtime.latest()["command_revision"] >= runtime.command_sequence)
        snap = runtime.latest()
        controls.append(dict(name=name, value=value, acknowledgement_seconds=time.monotonic()-start,
                             message=snap["message"], model=snap["model"]))
        if snap["message"].startswith("Rejected") == accepted:
            raise AssertionError(snap["message"])

    def typed(key, value, accepted=True):
        def action():
            widget = window.controls[key]
            widget.setFocus()
            widget.selectAll()
            QTest.keyClicks(widget, str(value))
            QTest.keyClick(widget, Qt.Key.Key_Return)
        physical = key in ("speed", "damping", "coupling", "omega", "amplitude")
        command("parameters" if physical else key, {key: value} if physical else value, action, accepted)

    def observe(seconds, phase=None):
        start, samples = time.monotonic(), []
        previous_poll = start
        while time.monotonic()-start < seconds:
            app.processEvents()
            snap = runtime.latest()
            if snap["fault"] or runtime.failure:
                raise AssertionError(snap["fault"] or runtime.failure)
            if args.source == "camera" and snap["capture"]["state"] != "running":
                raise AssertionError(str(snap["capture"]))
            if phase and time.monotonic()-start >= 3:
                times = window.render_times
                samples.append(dict(camera_fps=snap["capture"]["fps"],
                                    steps_per_second=snap["steps_per_second"],
                                    model_seconds_per_wall_second=snap["sim_speed"],
                                    input_age_ms=1000*snap["input_age"],
                                    display_fps=(len(times)-1)/max(times[-1]-times[0], 1e-6),
                                    event_loop_gap_ms=1000*(time.monotonic()-previous_poll),
                                    resident_mib=snap["memory"]["resident_mib"],
                                    peak_resident_mib=snap["memory"]["peak_resident_mib"],
                                    skipped_wall_seconds=snap["skipped_wall_seconds"],
                                    peak=snap["diagnostics"]["peak"]))
            previous_poll = time.monotonic()
            time.sleep(.01)
        if phase:
            measurements[phase] = {key: dict(min=float(np.min(values)), median=float(np.median(values)),
                                              max=float(np.max(values)))
                                   for key in samples[0] for values in ([s[key] for s in samples],)}

    runtime.start()
    window.show()
    try:
        assert runtime.engine.display_range == 2 and runtime.engine.intensity == 1
        assert runtime.engine.field.parameters.speed == .3
        assert runtime.engine.field.parameters.damping == .4
        assert runtime.engine.field.parameters.coupling == 2
        assert not runtime.engine.paused and runtime.engine.coupling_enabled
        checks.append("fresh launch recommended defaults before first GUI event")
        wait_for(lambda: runtime.latest() is not None and runtime.latest()["diagnostics"]["step"] > 10)
        if args.source == "camera":
            wait_for(lambda: runtime.latest()["capture"]["state"] == "running")
        observe(10, "sextic_initial")
        for key, value in (("omega", 10), ("amplitude", .12), ("speed", .35),
                           ("damping", .5), ("coupling", 1.5)):
            typed(key, value)
        command("paused", True, lambda: window.pause.setChecked(True))
        before = runtime.latest()["u"].copy()
        frames = runtime.latest()["capture"].get("frames", 0)
        observe(1)
        np.testing.assert_array_equal(runtime.latest()["u"], before)
        if args.source == "camera":
            assert runtime.latest()["capture"]["frames"] > frames
        checks.append("pause freezes field while acquisition continues")
        command("display_range", .025)
        command("intensity", 1.5)
        np.testing.assert_array_equal(runtime.latest()["u"], before)
        checks.append("display controls preserve physical state")
        command("save", str(args.output.with_suffix(".npz")))
        command("reset")
        assert not np.any(runtime.latest()["u"])
        command("load", str(args.output.with_suffix(".npz")))
        np.testing.assert_array_equal(runtime.latest()["u"], before)
        assert runtime.latest()["paused"] and not runtime.latest()["coupling_enabled"]
        checks.append("sextic save/reset/restore exact, paused and uncoupled")
        command("paused", False)
        observe(2)
        assert not np.array_equal(runtime.latest()["u"], before)
        checks.append("uncoupled field continues evolving")
        index = window.model_combo.findData("linear")
        command("model", "linear", lambda: window.model_combo.activated.emit(index))
        assert runtime.latest()["paused"] and not runtime.latest()["coupling_enabled"]
        assert not np.any(runtime.latest()["u"])
        wait_for(lambda: float(window.controls["coupling"].text()) == 2)
        for key, values in (("speed", (.001, 3)), ("damping", (11,)), ("coupling", (21,)),
                            ("display_range", (1e-6, 1e5)), ("intensity", (1e-4, 1e3))):
            for value in values:
                typed(key, value)
        before = runtime.latest()["u"].copy()
        for key, value in (("speed", 1e100), ("speed", 0), ("damping", -1),
                           ("coupling", -1), ("display_range", 0), ("intensity", -1)):
            typed(key, value, accepted=False)
        np.testing.assert_array_equal(runtime.latest()["u"], before)
        checks.append("typed values beyond old physical/display bounds; unsafe edits rejected atomically")
        edit = window.controls["speed"]
        edit.setFocus()
        edit.selectAll()
        QTest.keyClicks(edit, "4e")
        prior = runtime.command_sequence
        window.controls["intensity"].setFocus()
        observe(.2)
        assert edit.text() == "4e" and runtime.command_sequence == prior
        QTest.keyClick(edit, Qt.Key.Key_Return)
        assert "Rejected" in edit.feedback.text()
        assert runtime.command_sequence == prior
        QTest.keyClick(edit, Qt.Key.Key_Escape)
        assert float(edit.text()) == 3
        checks.append("partial draft survives focus/polling, rejects on Enter, Escape restores effective value")
        command("coupling_enabled", True)
        command("paused", False)
        observe(5, "linear_beyond_old_bounds")
        typed("speed", 100)
        observe(5, "linear_slow_cfl")
        typed("speed", .3)
        typed("damping", .4)
        typed("coupling", 2)
        command("reset")
        command("display_range", .05)
        command("intensity", 1)
        command("coupling_enabled", True)
        command("paused", False)
        observe(10, "linear")
        index = window.model_combo.findData("sextic")
        command("model", "sextic", lambda: window.model_combo.activated.emit(index))
        assert runtime.latest()["paused"] and not runtime.latest()["coupling_enabled"]
        assert not np.any(runtime.latest()["u"])
        checks.append("both model transitions reset, pause and disable coupling")
        command("coupling_enabled", True)
        command("paused", False)
        observe(10, "sextic_final")
        if args.screenshot:
            window.grab().save(str(args.screenshot))
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    snap = runtime.latest()
    report = dict(utc=datetime.now(timezone.utc).isoformat(), source=args.source, grid=args.grid,
                  qt_platform=app.platformName(), visible=window.isVisible(),
                  python=platform.python_version(), numpy=np.__version__,
                  source_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in [*Path("sentio").glob("*.py"), Path("tools/validate_live_gui.py")]},
                  scalar_log=str(runtime.log.path), checks=checks, controls=controls,
                  measurements=measurements, failure=failure, final_model=snap["model"] if snap else None,
                  camera={k:v for k,v in snap["capture"].items() if k not in ("identity",)} if snap else None,
                  final_diagnostics=snap["diagnostics"] if snap else None,
                  limitations="No physical scene manipulation or unplugging; age is sampled driver-frame age at simulation publication, not end-to-end optical latency.")
    if not args.leave_open or failure:
        window.close()
        app.processEvents()
        report["shutdown"] = dict(runtime_stopped=not runtime.is_alive(),
                                  capture_stopped=runtime.capture is None or not runtime.capture.is_alive())
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps(dict(report=str(args.output), failure=failure,
                          measurements=measurements, left_open=args.leave_open and not failure)), flush=True)
    if args.leave_open and not failure:
        return app.exec()
    return int(bool(failure))


if __name__ == "__main__":
    raise SystemExit(main())
