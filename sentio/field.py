"""Linear wave dynamics; no camera or GUI dependencies."""

from dataclasses import asdict, dataclass, replace
import json
import math
import os
from pathlib import Path
import tempfile
import zipfile

import numpy as np

from .grid import DEFAULT_GRID, MAX_GRID, MAX_CHECKPOINT_BYTES


@dataclass(frozen=True)
class Parameters:
    speed: float = 0.3
    damping: float = 0.4
    coupling: float = 2.0

    def __post_init__(self):
        for name, low, high in (("speed", 0.01, 2.0), ("damping", 0.0, 10.0),
                                ("coupling", 0.0, 20.0)):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be finite and in [{low}, {high}]")


class Field:
    """Node grid on [0,1]^2; fixed outer edge, optional quadratic sponge.

    v = du/dt is stored at the same time as u. Exact damping half-steps
    surround a velocity-Verlet wave/forcing step. Forcing is held per step.
    """

    def __init__(self, n=DEFAULT_GRID, parameters=None, sponge=True):
        if type(n) is not int or not 17 <= n <= MAX_GRID:
            raise ValueError(f"grid must be an integer from 17 through {MAX_GRID}")
        self.n = n
        self.dx = 1.0 / (n - 1)
        self.parameters = parameters or Parameters()
        self.sponge = bool(sponge)
        self.u = np.zeros((n, n), dtype=np.float64)
        self.v = np.zeros_like(self.u)
        self.step_count = 0
        self.time = 0.0
        i = np.arange(n)
        distance = np.minimum(i, n - 1 - i)
        edge_distance = np.minimum(distance[:, None], distance[None, :])
        self._sponge = 40.0 * np.maximum(0, 1 - edge_distance / (0.125 * (n - 1))) ** 2
        if not self.sponge:
            self._sponge.fill(0)

    @property
    def dt(self):
        return min(1.0 / 240, 0.8 * self.dx / (math.sqrt(2) * self.parameters.speed))

    def configure(self, **changes):
        candidate = replace(self.parameters, **changes)
        self.parameters = candidate

    def laplacian(self, u):
        out = np.zeros_like(u)
        out[1:-1, 1:-1] = (u[:-2, 1:-1] + u[2:, 1:-1] + u[1:-1, :-2]
                           + u[1:-1, 2:] - 4 * u[1:-1, 1:-1]) / self.dx**2
        return out

    @staticmethod
    def _edge_zero(a):
        a[[0, -1], :] = 0
        a[:, [0, -1]] = 0

    def step(self, source=None, dt=None):
        h = self.dt if dt is None else dt
        if not math.isfinite(h) or not 0 < h <= self.dt * (1 + 1e-12):
            raise ValueError(f"time step must be in (0, {self.dt}]")
        if source is not None:
            if source.shape != self.u.shape or not np.isfinite(source).all() or np.max(np.abs(source)) > 1 + 1e-12:
                raise ValueError("source must match grid, be finite, and lie in [-1,1]")
        p = self.parameters
        force = 0.0 if source is None else p.coupling * source
        decay = np.exp(-0.5 * h * (p.damping + self._sponge))
        with np.errstate(over="ignore", invalid="ignore"):
            v_half = decay * self.v + 0.5 * h * (p.speed**2 * self.laplacian(self.u) + force)
            u = self.u + h * v_half
            self._edge_zero(u)
            v = decay * (v_half + 0.5 * h * (p.speed**2 * self.laplacian(u) + force))
            self._edge_zero(v)
        if not np.isfinite(u).all() or not np.isfinite(v).all():
            raise FloatingPointError("NaN/Inf detected; step rejected")
        if max(float(np.max(np.abs(u))), float(np.max(np.abs(v)))) > 1e6:
            raise FloatingPointError("amplitude/velocity safety limit 1e6 exceeded; step rejected")
        self.u, self.v = u, v
        self.time += h
        self.step_count += 1

    def diagnostics(self):
        kinetic = 0.5 * self.dx**2 * float(np.sum(self.v**2))
        potential = 0.5 * self.parameters.speed**2 * float(
            np.sum(np.diff(self.u, axis=0)**2) + np.sum(np.diff(self.u, axis=1)**2))
        return dict(n=self.n, dx=self.dx, domain_length=1.0,
                    step=self.step_count, simulation_time=self.time, dt=self.dt,
                    cfl=self.parameters.speed * self.dt / self.dx,
                    peak=float(np.max(np.abs(self.u))),
                    velocity_peak=float(np.max(np.abs(self.v))),
                    energy=kinetic + potential, kinetic=kinetic, potential=potential,
                    finite=bool(np.isfinite(self.u).all() and np.isfinite(self.v).all()))

    def reset(self):
        self.u.fill(0)
        self.v.fill(0)
        self.step_count = 0
        self.time = 0.0

    def save(self, path):
        """Atomic, explicit checkpoint: no source frame or preview is stored."""
        path = Path(path)
        metadata = dict(schema=1, n=self.n, parameters=asdict(self.parameters),
                        sponge=self.sponge, step=self.step_count, time=self.time,
                        model="linear-wave-verlet-sponge-v1")
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as f:
                temp = f.name
                np.savez_compressed(f, u=self.u, v=self.v, metadata=json.dumps(metadata))
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            if temp and os.path.exists(temp):
                os.unlink(temp)

    @classmethod
    def load(cls, path):
        # Bound decompression before NumPy allocates anything; never unpickle.
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist()) != 3 or sum(i.file_size for i in archive.infolist()) > MAX_CHECKPOINT_BYTES:
                raise ValueError("invalid or oversized checkpoint")
            if set(archive.namelist()) != {"u.npy", "v.npy", "metadata.npy"}:
                raise ValueError("invalid checkpoint members")
            for name in archive.namelist():
                with archive.open(name) as member:
                    version = np.lib.format.read_magic(member)
                    if version != (1, 0):
                        raise ValueError("unsupported checkpoint array format")
                    shape, _, dtype = np.lib.format.read_array_header_1_0(member)
                    if name == "metadata.npy":
                        valid = shape == () and dtype.kind == "U" and dtype.itemsize <= 10000
                    else:
                        valid = len(shape) == 2 and shape[0] == shape[1] and 17 <= shape[0] <= MAX_GRID and dtype == np.float64
                    if not valid:
                        raise ValueError("invalid checkpoint array header")
        with np.load(path, allow_pickle=False) as data:
            if set(data.files) != {"u", "v", "metadata"}:
                raise ValueError("invalid checkpoint contents")
            meta = json.loads(str(data["metadata"]))
            if meta["schema"] != 1 or meta["model"] != "linear-wave-verlet-sponge-v1":
                raise ValueError("unsupported checkpoint model/schema")
            if type(meta["sponge"]) is not bool:
                raise ValueError("invalid sponge setting")
            field = cls(meta["n"], Parameters(**meta["parameters"]), meta["sponge"])
            for name in ("u", "v"):
                a = data[name]
                if a.shape != field.u.shape or a.dtype != np.float64 or not np.isfinite(a).all() or np.max(np.abs(a)) > 1e6:
                    raise ValueError("invalid field array")
                if np.any(a[[0, -1], :]) or np.any(a[:, [0, -1]]):
                    raise ValueError("checkpoint violates fixed boundary")
                setattr(field, name, a.copy())
            if type(meta["step"]) is not int or meta["step"] < 0 or not math.isfinite(meta["time"]) or meta["time"] < 0:
                raise ValueError("invalid checkpoint clock")
            field.step_count, field.time = meta["step"], meta["time"]
        return field
