"""Optional soft-sextic numerical core; no runtime, camera or GUI integration.

Issue #6's integration is blocked on the separately owned issue #4. The
accepted Field implementation remains the linear default and is untouched.
"""

from dataclasses import asdict, dataclass, replace
import json
import math
import os
from pathlib import Path
import tempfile
import zipfile

import numpy as np

from .field import Field, Parameters


MODEL = "soft-sextic-verlet-sponge-v1"
ENVELOPE_RATIO = 4.0
# Operational ceiling, not a real-time promise: at most 10^6 steps/model s.
# Runtime integration must reconcile this with issue #4's accepted policy.
MIN_STEP = 1e-6
MAX_STEP = 1/480


@dataclass(frozen=True)
class SexticParameters:
    omega: float = 8.0
    amplitude: float = .1

    def __post_init__(self):
        for name in ("omega", "amplitude"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and strictly positive")
        try:
            # The endpoint bounds are valid throughout |u/A| <= 4. Reject
            # coefficients whose force/energy cannot be represented in float64.
            bounds = (self.omega**2, 4*self.amplitude,
                      248*self.omega**2*self.amplitude,
                      149*(self.omega*self.amplitude)**2)
        except OverflowError as exc:
            raise ValueError("nonlinear coefficients exceed float64 representation") from exc
        if not all(math.isfinite(x) and x > 0 for x in bounds):
            raise ValueError("nonlinear force/energy coefficients overflow or underflow float64")

    @property
    def envelope(self):
        return ENVELOPE_RATIO*self.amplitude

    @property
    def curvature_bound(self):
        # |1 - 3q² + 1.5q⁴| <= 1 + 3*4² + 1.5*4⁴ = 433.
        return 433*self.omega**2

    def gradient(self, u):
        q2 = (u/self.amplitude)**2
        return self.omega**2*u*(1+q2*(-1+.3*q2))

    def density(self, u):
        q2 = (u/self.amplitude)**2
        return self.omega**2*u*u*(.5+q2*(-.25+.05*q2))


class SexticField(Field):
    """Damped velocity Verlet with a local bounded-below sextic potential.

    Parameter changes preserve u/v and account for their instantaneous energy
    change. Steps and configurations commit only after validation. This class
    does not switch models or decide when an application should pause.
    """

    def __init__(self, n=256, parameters=None, nonlinear=None, sponge=True):
        super().__init__(n, parameters, sponge)
        self.nonlinear = nonlinear or SexticParameters()
        self._step_bound(self.parameters, self.nonlinear)
        self._decay_key = None
        self.rebase_energy()

    def _step_bound(self, parameters, nonlinear):
        frequency = math.hypot(math.sqrt(8)*parameters.speed/self.dx,
                               math.sqrt(433)*nonlinear.omega)
        h = min(MAX_STEP, .8*self.dx/(math.sqrt(2)*parameters.speed), 1.6/frequency)
        if not math.isfinite(h) or h < MIN_STEP:
            raise ValueError(f"nonlinear wave/curvature step {h:g} is below {MIN_STEP:g} s; "
                             "requested configuration requires an infeasible step rate")
        return h

    @property
    def dt(self):
        return self._step_bound(self.parameters, self.nonlinear)

    def _validate_state(self, u, v, nonlinear=None):
        nonlinear = nonlinear or self.nonlinear
        if not np.isfinite(u).all() or not np.isfinite(v).all():
            raise FloatingPointError("NaN/Inf detected; nonlinear state rejected")
        if float(np.max(np.abs(u))) > nonlinear.envelope:
            raise FloatingPointError(f"soft-sextic validity envelope |u| <= 4A = {nonlinear.envelope:g} "
                                     "exceeded; state rejected without clipping")
        if max(float(np.max(np.abs(u))), float(np.max(np.abs(v)))) > 1e6:
            raise FloatingPointError("amplitude/velocity safety limit 1e6 exceeded; state rejected")

    def _energy(self, parameters, nonlinear):
        kinetic = .5*self.dx**2*float(np.sum(self.v*self.v))
        gradient = .5*parameters.speed**2*float(
            np.sum(np.diff(self.u, axis=0)**2)+np.sum(np.diff(self.u, axis=1)**2))
        local = self.dx**2*float(np.sum(nonlinear.density(self.u)))
        if not all(math.isfinite(x) for x in (kinetic, gradient, local, kinetic+gradient+local)):
            raise FloatingPointError("nonfinite nonlinear energy; configuration/state rejected")
        return kinetic, gradient, local

    def energy(self):
        return sum(self._energy(self.parameters, self.nonlinear))

    def energy_density(self):
        """Nonnegative local density; split each gradient edge equally."""
        density = .5*self.v**2+self.nonlinear.density(self.u)
        for axis in (0, 1):
            edge = .25*self.parameters.speed**2*np.diff(self.u, axis=axis)**2/self.dx**2
            lower, upper = [slice(None)]*2, [slice(None)]*2
            lower[axis], upper[axis] = slice(None, -1), slice(1, None)
            density[tuple(lower)] += edge
            density[tuple(upper)] += edge
        return density

    def rebase_energy(self):
        """Begin a new diagnostic balance after explicitly assigning initial data."""
        self._validate_state(self.u, self.v)
        self.reference_energy = self.energy()
        self.input_work = self.damping_loss = self.parameter_work = 0.0

    def configure(self, **changes):
        physical = {k:v for k,v in changes.items() if k in ("speed", "damping", "coupling")}
        local = {k:v for k,v in changes.items() if k in ("omega", "amplitude")}
        if len(physical)+len(local) != len(changes):
            raise ValueError("unknown soft-sextic parameter")
        candidate = replace(self.parameters, **physical)
        nonlinear = replace(self.nonlinear, **local)
        self._step_bound(candidate, nonlinear)
        try:
            self._validate_state(self.u, self.v, nonlinear)
            jump = sum(self._energy(candidate, nonlinear))-self.energy()
        except (FloatingPointError, OverflowError) as exc:
            raise ValueError(str(exc)) from exc
        work = self.parameter_work+jump
        if not math.isfinite(work):
            raise ValueError("parameter-change energy accounting overflow")
        self.parameters, self.nonlinear, self.parameter_work = candidate, nonlinear, work

    def step(self, source=None, dt=None):
        h = self.dt if dt is None else dt
        if not math.isfinite(h) or not 0 < h <= self.dt*(1+1e-12):
            raise ValueError(f"time step must be in (0, {self.dt}] for this wave/potential")
        if source is not None and (source.shape != self.u.shape or not np.isfinite(source).all()
                                   or np.max(np.abs(source)) > 1+1e-12):
            raise ValueError("source must match grid, be finite, and lie in [-1,1]")
        self._validate_state(self.u, self.v)
        p, potential = self.parameters, self.nonlinear
        key = (h, p.damping)
        if key != self._decay_key:
            self._decay = np.exp(-.5*h*(p.damping+self._sponge))
            self._loss_weight = 1-self._decay**2
            self._decay_key = key
        decay = self._decay
        force = 0.0 if source is None else p.coupling*source
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            acceleration = p.speed**2*self.laplacian(self.u)+force-potential.gradient(self.u)
            half = decay*self.v+.5*h*acceleration
            u = self.u+h*half
            self._edge_zero(u)
            # Validate before evaluating a high-order polynomial at the candidate.
            self._validate_state(u, self.v)
            before_damping = half+.5*h*(p.speed**2*self.laplacian(u)+force-potential.gradient(u))
            self._edge_zero(before_damping)
            v = decay*before_damping
            self._validate_state(u, v)
            work = self.input_work+(0.0 if source is None else
                    p.coupling*self.dx**2*float(np.sum(source*(u-self.u))))
            loss = self.damping_loss+.5*self.dx**2*float(np.sum(
                self._loss_weight*(self.v**2+before_damping**2)))
        if not all(math.isfinite(x) for x in (work, loss, self.time+h)) or self.time+h <= self.time:
            raise FloatingPointError("nonfinite accounting or unresolved simulation clock; step rejected")
        self.u, self.v, self.input_work, self.damping_loss = u, v, work, loss
        self.time += h
        self.step_count += 1

    def diagnostics(self):
        kinetic, gradient, local = self._energy(self.parameters, self.nonlinear)
        energy = kinetic+gradient+local
        peak = float(np.max(np.abs(self.u)))
        return dict(model=MODEL, step=self.step_count, simulation_time=self.time, dt=self.dt,
                    cfl=self.parameters.speed*self.dt/self.dx,
                    curvature_bound=self.nonlinear.curvature_bound,
                    wave_curvature_number=self.dt*math.hypot(math.sqrt(8)*self.parameters.speed/self.dx,
                                                            math.sqrt(433)*self.nonlinear.omega),
                    minimum=float(self.u.min()), maximum=float(self.u.max()), peak=peak,
                    velocity_peak=float(np.max(np.abs(self.v))),
                    energy=energy, kinetic=kinetic, gradient_energy=gradient, local_potential=local,
                    potential=gradient+local, reference_energy=self.reference_energy,
                    input_work=self.input_work, damping_loss=self.damping_loss,
                    parameter_work=self.parameter_work,
                    balance_residual=energy-self.reference_energy-self.input_work-self.parameter_work+self.damping_loss,
                    envelope=self.nonlinear.envelope, envelope_ratio=ENVELOPE_RATIO,
                    envelope_fraction=peak/self.nonlinear.envelope,
                    envelope_ok=peak <= self.nonlinear.envelope,
                    finite=bool(np.isfinite(self.u).all() and np.isfinite(self.v).all()))

    def reset(self):
        super().reset()
        self.rebase_energy()

    def seed_control(self):
        """Explicit researched IC/preset, not sensory-driven formation.

        The future runtime must also disable input coupling and label this action.
        """
        self.parameters = Parameters(speed=.3, damping=0, coupling=0)
        self.nonlinear = SexticParameters()
        axis = np.linspace(-.5, .5, self.n)
        self.u[:] = 1.2*self.nonlinear.amplitude*np.exp(-(axis[:, None]**2+axis[None, :]**2)/.15**2)
        self._edge_zero(self.u)
        self.v.fill(0)
        self.time, self.step_count = 0.0, 0
        self.rebase_energy()

    def save(self, path):
        """Explicit schema-2 state, never readable as a legacy linear checkpoint."""
        self._validate_state(self.u, self.v)
        self._energy(self.parameters, self.nonlinear)
        path = Path(path)
        metadata = dict(schema=2, model=MODEL, n=self.n, parameters=asdict(self.parameters),
                        nonlinear=asdict(self.nonlinear), envelope_ratio=ENVELOPE_RATIO,
                        sponge=self.sponge, step=self.step_count, time=self.time,
                        accounting={k:getattr(self,k) for k in
                                    ("reference_energy", "input_work", "damping_loss", "parameter_work")})
        encoded = json.dumps(metadata, allow_nan=False)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as stream:
                temporary = stream.name
                np.savez_compressed(stream, u=self.u, v=self.v, metadata=encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def load(cls, path):
        # Validate sizes and headers before NumPy allocation, as for schema 1.
        # No dispatch or changes to the accepted linear loader in this core PR.
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist()) != 3 or sum(i.file_size for i in archive.infolist()) > 2_000_000:
                raise ValueError("invalid or oversized nonlinear checkpoint")
            if set(archive.namelist()) != {"u.npy", "v.npy", "metadata.npy"}:
                raise ValueError("invalid nonlinear checkpoint members")
            for name in archive.namelist():
                with archive.open(name) as member:
                    if np.lib.format.read_magic(member) != (1, 0):
                        raise ValueError("unsupported checkpoint array format")
                    shape, _, dtype = np.lib.format.read_array_header_1_0(member)
                    valid = (shape == () and dtype.kind == "U" and dtype.itemsize <= 10000) if name == "metadata.npy" else (
                        len(shape) == 2 and shape[0] == shape[1] and 17 <= shape[0] <= 256 and dtype == np.float64)
                    if not valid:
                        raise ValueError("invalid nonlinear checkpoint array header")
        with np.load(path, allow_pickle=False) as data:
            meta = json.loads(str(data["metadata"]))
            if not isinstance(meta, dict):
                raise ValueError("invalid nonlinear checkpoint metadata")
            for key, names in (("parameters", {"speed", "damping", "coupling"}),
                               ("nonlinear", {"omega", "amplitude"}),
                               ("accounting", {"reference_energy", "input_work", "damping_loss", "parameter_work"})):
                values = meta.get(key)
                if not isinstance(values, dict) or set(values) != names:
                    raise ValueError(f"checkpoint must explicitly specify all {key}")
                if any(type(value) not in (int, float) or not math.isfinite(value) for value in values.values()):
                    raise ValueError(f"invalid numeric checkpoint {key}")
            if meta["schema"] != 2 or meta["model"] != MODEL or meta["envelope_ratio"] != ENVELOPE_RATIO:
                raise ValueError("unsupported nonlinear checkpoint model/schema/envelope")
            if type(meta["sponge"]) is not bool:
                raise ValueError("invalid sponge setting")
            field = cls(meta["n"], Parameters(**meta["parameters"]), SexticParameters(**meta["nonlinear"]), meta["sponge"])
            for name in ("u", "v"):
                a = data[name]
                if a.shape != field.u.shape or a.dtype != np.float64:
                    raise ValueError("invalid nonlinear field array")
                if np.any(a[[0, -1], :]) or np.any(a[:, [0, -1]]):
                    raise ValueError("checkpoint violates fixed boundary")
                setattr(field, name, a.copy())
            try:
                field._validate_state(field.u, field.v)
                field._energy(field.parameters, field.nonlinear)
            except FloatingPointError as exc:
                raise ValueError(str(exc)) from exc
            if (type(meta["step"]) is not int or meta["step"] < 0 or type(meta["time"]) not in (int, float)
                    or not math.isfinite(meta["time"]) or meta["time"] < 0):
                raise ValueError("invalid nonlinear checkpoint clock")
            field.step_count, field.time = meta["step"], meta["time"]
            for key in ("reference_energy", "input_work", "damping_loss", "parameter_work"):
                value = meta["accounting"][key]
                if not math.isfinite(value) or (key in ("reference_energy", "damping_loss") and value < 0):
                    raise ValueError("invalid nonlinear energy accounting")
                setattr(field, key, value)
            if not math.isfinite(field.diagnostics()["balance_residual"]):
                raise ValueError("nonfinite nonlinear energy balance")
        return field
