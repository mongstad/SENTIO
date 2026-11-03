"""Bounded acquisition, independently paced simulation, and scalar-only logs."""

from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import queue
import threading
import time
import uuid
import zipfile

import numpy as np

from . import __version__
from .camera import V4L2Camera
from .inputs import SYNTHETIC_MODES, luminance_source, synthetic_source
from .models import MODEL_IDS, create_field, load_field, model_name


class EventLog:
    def __init__(self, path=None):
        if path is None:
            path = Path("runs") / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8] + ".jsonl")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("x", encoding="utf-8")
        self.path.chmod(0o600)
        self.lock = threading.Lock()

    def write(self, event, field=None, **values):
        record = dict(event=event, utc=datetime.now(timezone.utc).isoformat(),
                      monotonic=time.monotonic(), **values)
        if field is not None:
            record.update(step=field.step_count, simulation_time=field.time,
                          model=model_name(field), model_id=MODEL_IDS[model_name(field)],
                          nonlinear=asdict(field.nonlinear) if hasattr(field, "nonlinear") else {})
        with self.lock:
            self.file.write(json.dumps(record, allow_nan=False) + "\n")
            self.file.flush()

    def close(self):
        with self.lock:
            self.file.close()


class LatestFrame:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None
        self.pending = False
        self.overwritten = 0
        self.status = dict(state="starting", fps=0.0)

    def publish(self, frame, status):
        with self.lock:
            self.overwritten += int(self.pending)
            self.frame, self.pending, self.status = frame, True, status.copy()

    def update_status(self, **status):
        with self.lock:
            self.status.update(status)
            if status.get("state") in ("error", "stopped"):
                self.frame, self.pending = None, False

    def take(self):
        with self.lock:
            frame = self.frame if self.pending else None
            self.pending = False
            return frame, dict(self.status, mailbox_discards=self.overwritten)


class Acquisition(threading.Thread):
    def __init__(self, mailbox, log, stop, device=None, exposure=156):
        super().__init__(name="sentio-capture", daemon=True)
        self.mailbox, self.log, self.stop_event = mailbox, log, stop
        self.device, self.exposure = device, exposure

    def run(self):
        camera = None
        try:
            camera = V4L2Camera(self.device, self.exposure)
            self.log.write("camera_open", identity=camera.info, mode=camera.mode,
                           controls=camera.controls, warnings=camera.warnings,
                           buffers=len(camera.buffers))
            stamps = deque(maxlen=90)
            last = time.monotonic()
            next_controls, effective_controls = 0.0, {}
            while not self.stop_event.is_set():
                frame = camera.read()
                now = time.monotonic()
                if frame is None:
                    if now - last > 2:
                        raise TimeoutError("No valid camera frame for 2 seconds; input disabled")
                    continue
                y, stamp, sequence = frame
                last = now
                stamps.append((now, camera.frames))
                fps = ((stamps[-1][1] - stamps[0][1]) / (now - stamps[0][0])) if len(stamps) > 1 else 0
                if now >= next_controls:
                    observed = camera.read_controls()
                    if observed != effective_controls:
                        self.log.write("camera_controls_observed", controls=observed)
                    effective_controls = observed
                    next_controls = now + 1
                warnings = camera.warnings.copy()
                for name, setting in camera.controls.items():
                    actual = effective_controls.get(name)
                    if actual != setting["requested"]:
                        warnings.append(f"{name}: requested {setting['requested']}, effective {actual}")
                status = dict(state="running", fps=fps, mode=camera.mode, identity=camera.info,
                              warnings=warnings, effective_controls=effective_controls, **camera.stats())
                # One owned source plus one optional preview; no frame history.
                self.mailbox.publish((luminance_source(y), y, stamp, sequence), status)
        except Exception as exc:
            self.mailbox.update_status(state="error", error=str(exc), fps=0.0)
            self.log.write("camera_error", error=str(exc))
        finally:
            if camera is not None:
                camera.close()
                self.log.write("camera_close", stats=camera.stats(), warnings=camera.warnings)


class Engine:
    """Simulation state owner. All mutations execute between integration steps."""

    def __init__(self, log, source="stationary", model="linear"):
        if source not in ("camera", *SYNTHETIC_MODES):
            raise ValueError("invalid input source")
        self.field, self.log, self.source = create_field(model), log, source
        self.paused = False
        self.coupling_enabled = True
        self.fault = ""
        self.message = ""
        self.display_range = .05 if model == "sextic" else (2.0 if source == "camera" else 0.2)
        self.intensity = 1.0
        self.preview_enabled = False
        self.command_revision = 0
        self.epoch = 0
        self.log.write("session_start", self.field, version=__version__, source=source,
                       parameters=asdict(self.field.parameters), n=self.field.n,
                       sponge=self.field.sponge, display_range=self.display_range,
                       intensity=self.intensity, initial_state="zero", random_seed=None,
                       python=platform.python_version(), numpy=np.__version__,
                       platform=platform.platform(), source_scaling="Y/127.5-1; full-frame area average")

    @property
    def model(self):
        return model_name(self.field)

    def command(self, name, value=None, revision=None):
        self.command_revision = self.command_revision + 1 if revision is None else revision
        try:
            if name == "parameters":
                self.field.configure(**value)
            elif name == "model":
                if value == self.model:
                    raise ValueError("Model already active; use Reset field to clear its state")
                candidate = create_field(value)
                self.field = candidate
                self.paused, self.coupling_enabled, self.fault = True, False, ""
                self.epoch += 1
            elif name == "seed":
                if self.model != "sextic":
                    raise ValueError("The explicit seed control requires soft sextic mode")
                self.field.seed_control()
                self.paused, self.coupling_enabled, self.fault = True, False, ""
                self.epoch += 1
            elif name == "paused":
                if self.fault and not value:
                    raise ValueError("Reset or restore a valid checkpoint before resuming a numerical fault")
                self.paused = bool(value)
            elif name == "coupling_enabled":
                self.coupling_enabled = bool(value)
            elif name == "preview_enabled":
                self.preview_enabled = bool(value)
            elif name == "reset":
                self.field.reset()
                self.fault = ""
                self.epoch += 1
            elif name in ("display_range", "intensity"):
                low, high = ((.0001, 10000) if name == "display_range" else (.01, 100))
                if not np.isfinite(value) or not low <= value <= high:
                    raise ValueError(f"{name} must be in [{low}, {high}]")
                setattr(self, name, float(value))
            elif name == "save":
                self.field.save(value)
            elif name == "load":
                loaded = load_field(value)
                if loaded.n != 256 or not loaded.sponge:
                    raise ValueError("Application checkpoints must use a 256x256 grid with sponge")
                self.field = loaded
                self.paused, self.coupling_enabled, self.fault = True, False, ""
                self.epoch += 1
            elif name == "source" and self.source != "camera" and value in SYNTHETIC_MODES:
                self.source = value
            else:
                raise ValueError(f"unsupported command: {name}")
            self.message = f"Applied {name}" + ("; paused, coupling off" if name in ("load", "model", "seed") else "")
            if name == "model":
                self.message += "; model defaults, zero state on change; display range retained"
            elif name == "seed":
                self.message += "; imposed Gaussian, c=.3, γ=κ=0, ω=8, A=.1 (not camera formation)"
            self.log.write("control", self.field, name=name, value=value, epoch=self.epoch,
                           parameters=asdict(self.field.parameters), paused=self.paused,
                           coupling_enabled=self.coupling_enabled)
        except (ValueError, OSError, KeyError, TypeError, EOFError, OverflowError,
                FloatingPointError, zipfile.BadZipFile) as exc:
            self.message = f"Rejected {name}: {exc}"
            self.log.write("control_rejected", self.field, name=name, error=str(exc))

    def step(self, source=None):
        if self.paused:
            return
        try:
            self.field.step(source if self.coupling_enabled else None)
        except (FloatingPointError, ValueError) as exc:
            self.paused, self.fault = True, str(exc)
            self.log.write("numerical_fault", self.field, error=self.fault)


class Runtime(threading.Thread):
    def __init__(self, source="stationary", device=None, exposure=156, log_path=None, model="linear"):
        super().__init__(name="sentio-simulation", daemon=True)
        self.log = EventLog(log_path)
        self.engine = Engine(self.log, source, model)
        self.stop_event = threading.Event()
        self.mailbox = LatestFrame()
        self.capture = Acquisition(self.mailbox, self.log, self.stop_event, device, exposure) if source == "camera" else None
        self.commands = queue.Queue(maxsize=128)
        self.lock = threading.Lock()
        self.command_sequence = 0
        self.snapshot = None
        self.failure = ""

    def submit(self, name, value=None):
        with self.lock:
            revision = self.command_sequence + 1
            self.commands.put_nowait((name, value, revision))
            self.command_sequence = revision
        return revision

    def latest(self):
        with self.lock:
            return self.snapshot

    def run(self):
        if self.capture:
            self.capture.start()
        engine = self.engine
        start = previous = rate_start = time.monotonic()
        next_publish = next_log = next_input = start
        budget = skipped_wall = 0.0
        source = preview = None
        stamp = 0.0
        rate_steps = 0
        sps = sim_speed = 0.0
        rate_time = 0.0
        capture = dict(state="synthetic", fps=0.0)
        input_frames = 0
        history = deque(maxlen=600)
        last_epoch = engine.epoch
        try:
            while not self.stop_event.is_set():
                now = time.monotonic()
                elapsed, previous = now - previous, now
                # Slow machines lose wall time, never increase the stable time step.
                added = min(elapsed, .05)
                skipped_wall += elapsed - added + max(0.0, budget + added - .05)
                budget = min(.05, budget + added)
                while True:
                    try:
                        engine.command(*self.commands.get_nowait())
                    except queue.Empty:
                        break
                if engine.epoch != last_epoch:
                    history.clear()
                    budget = 0
                    last_epoch = engine.epoch
                if self.capture:
                    frame, capture = self.mailbox.take()
                    if frame is not None:
                        source, preview, stamp, _ = frame
                    fresh = source is not None and 0 <= now - stamp <= .25 and capture["state"] == "running"
                    if not fresh:
                        preview = None
                else:
                    if now >= next_input:
                        source = synthetic_source(256, now - start, engine.source)
                        stamp = now
                        input_frames += 1
                        next_input = now + 1 / 30
                    capture = dict(state="synthetic", fps=input_frames / max(now - start, .001))
                    fresh = True
                if engine.paused:
                    budget = 0
                    self.stop_event.wait(.002)
                elif budget >= engine.field.dt:
                    dt = engine.field.dt
                    old_steps = engine.field.step_count
                    engine.step(source if fresh else None)
                    if engine.field.step_count != old_steps:
                        rate_steps += 1
                        rate_time += dt
                    budget -= dt
                else:
                    self.stop_event.wait(min(.002, engine.field.dt - budget))
                if now - rate_start >= 1:
                    sps, sim_speed = rate_steps / (now - rate_start), rate_time / (now - rate_start)
                    rate_start, rate_steps, rate_time = now, 0, 0.0
                if now >= next_publish:
                    diagnostics = engine.field.diagnostics()
                    if now >= next_log:
                        history.append((engine.field.time, diagnostics["energy"]))
                        self.log.write("diagnostics", engine.field, diagnostics=diagnostics,
                                       steps_per_second=sps, simulation_seconds_per_second=sim_speed,
                                       skipped_wall_seconds=skipped_wall, capture=capture,
                                       input_fresh=fresh, input_enabled=engine.coupling_enabled,
                                       input_age=max(0, now-stamp),
                                       paused=engine.paused, epoch=engine.epoch)
                        next_log = now + 1
                    snap = dict(u=engine.field.u.copy(), diagnostics=diagnostics,
                                model=engine.model,
                                nonlinear=asdict(engine.field.nonlinear) if engine.model == "sextic" else {},
                                parameters=asdict(engine.field.parameters), paused=engine.paused,
                                coupling_enabled=engine.coupling_enabled, fault=engine.fault,
                                message=engine.message, source=engine.source, capture=capture,
                                input_fresh=fresh, input_age=max(0, now - stamp),
                                preview=preview, steps_per_second=sps, sim_speed=sim_speed,
                                skipped_wall_seconds=skipped_wall, history=list(history),
                                display_range=engine.display_range, intensity=engine.intensity,
                                preview_enabled=engine.preview_enabled,
                                epoch=engine.epoch,
                                command_revision=engine.command_revision,
                                wall_seconds=now-start)
                    with self.lock:
                        self.snapshot = snap
                    next_publish = now + 1 / 30
        except Exception as exc:
            self.failure = str(exc)
            self.log.write("runtime_error", engine.field, error=self.failure)
        finally:
            self.stop_event.set()
            if self.capture:
                self.capture.join(timeout=5)
            self.log.write("session_end", engine.field, failure=self.failure,
                           capture_stopped=self.capture is None or not self.capture.is_alive())

    def close(self):
        self.stop_event.set()
        if self.ident is not None:
            self.join(timeout=6)
        if self.is_alive() or (self.capture and self.capture.is_alive()):
            raise RuntimeError("worker did not stop within timeout")
        self.log.close()
