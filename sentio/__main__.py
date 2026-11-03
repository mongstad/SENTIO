"""python -m sentio: synthetic by default; camera acquisition is explicit."""

import argparse
import json
from pathlib import Path
import signal
import sys
import time

import numpy as np

from .camera import devices
from .inputs import SYNTHETIC_MODES
from .models import MODEL_LABELS
from .runtime import Runtime


def headless(runtime, seconds, output=None):
    runtime.start()
    samples = []
    interrupted = False
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and runtime.is_alive():
            time.sleep(.1)
            snap = runtime.latest()
            if snap:
                samples.append({k:v for k,v in snap.items() if k not in ("u", "preview", "history")})
    except KeyboardInterrupt:
        interrupted = True
    finally:
        runtime.close()
    stable = [s for s in samples if s["wall_seconds"] >= 3]
    report = dict(schema=1, source=runtime.engine.source, model=runtime.engine.model, requested_seconds=seconds,
                  interrupted=interrupted, runtime_failure=runtime.failure,
                  scalar_log=str(runtime.log.path), sample_count=len(samples),
                  all_finite=all(s["diagnostics"]["finite"] and not s["fault"] for s in samples),
                  peak=max((s["diagnostics"]["peak"] for s in samples), default=0),
                  final=samples[-1] if samples else None,
                  measured_after_3s={key: dict(min=float(np.min(values)), median=float(np.median(values)),
                                              max=float(np.max(values)))
                                     for key, values in (("capture_fps", [s["capture"].get("fps", 0) for s in stable]),
                                                         ("simulation_steps_per_second", [s["steps_per_second"] for s in stable]),
                                                         ("simulation_seconds_per_second", [s["sim_speed"] for s in stable])) if values})
    encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if output:
        Path(output).write_text(encoded, encoding="utf-8")
    print(encoded)
    final = report["final"]
    return int(not final or not report["all_finite"] or bool(runtime.failure) or
               (runtime.engine.source == "camera" and (final["capture"]["state"] != "running" or not final["input_fresh"])))


def main(argv=None):
    parser = argparse.ArgumentParser(description="SENTIO: live 2D scalar field")
    parser.add_argument("--model", choices=tuple(MODEL_LABELS), default="linear",
                        help="linear default, or soft sextic experimental dynamics")
    parser.add_argument("--source", choices=("camera", *SYNTHETIC_MODES), default="stationary")
    parser.add_argument("--device", help="V4L2 path, preferably /dev/v4l/by-id/...; otherwise discover unique C922")
    parser.add_argument("--exposure", type=int, default=156, help="manual exposure in 100 µs units (1..300)")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--headless", action="store_true", help="measure without a display")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--report", help="headless scalar-only JSON report destination")
    parser.add_argument("--log", help="new scalar-only JSONL file (refuses overwrite)")
    args = parser.parse_args(argv)
    if args.list_devices:
        print(json.dumps(devices(), indent=2))
        return 0
    if not np.isfinite(args.seconds) or not 0 < args.seconds <= 3600:
        parser.error("--seconds must be in (0, 3600]")
    if not 1 <= args.exposure <= 300:
        parser.error("--exposure must be in [1, 300]")
    runtime = Runtime(args.source, args.device, args.exposure, args.log, model=args.model)
    if args.headless:
        signal.signal(signal.SIGTERM, lambda *_: runtime.stop_event.set())
        return headless(runtime, args.seconds, args.report)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from .gui import Window
    app = QApplication(sys.argv[:1])
    window = Window(runtime)
    signal.signal(signal.SIGINT, lambda *_: window.close())
    signal.signal(signal.SIGTERM, lambda *_: window.close())
    # Keep Python signal dispatch responsive even when Qt is idle.
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(200)
    runtime.start()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
