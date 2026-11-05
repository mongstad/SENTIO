"""Phenomenological damping history; no sensory acquisition or rendering."""

from dataclasses import dataclass
import math

import numpy as np

from sentio.field import Field, Parameters
from sentio.sextic import SexticField


@dataclass(frozen=True)
class Reinforcement:
    activity: str = "source"
    eta: float = 2.0
    decay: float = .02
    alpha: float = 9.0
    gamma_min: float = .02
    source_scale: float = 2.0
    energy_scale: float = .005

    def __post_init__(self):
        if self.activity not in ("source", "wave"):
            raise ValueError("activity must be source or wave")
        for key in ("eta", "decay", "alpha", "gamma_min", "source_scale", "energy_scale"):
            value = getattr(self, key)
            if not math.isfinite(value) or value < 0 or (key.endswith("scale") and value == 0):
                raise ValueError(f"invalid reinforcement {key}")
        if not math.isfinite(self.eta+self.decay):
            raise ValueError("reinforcement rate sum overflows")


class ReinforcedField:
    """Owns (u,v) through an accepted wave object, plus an explicit map m.

    Settings are fixed for one research trial. Steps commit all state/accounting
    together. No application checkpoint may omit m or reinterpret this model.
    """

    def __init__(self, n=65, model="linear", reinforcement=None, enabled=True,
                 parameters=None, sponge=True, timestep_factor=1.0):
        if model not in ("linear", "sextic"):
            raise ValueError("model must be linear or sextic")
        if not math.isfinite(timestep_factor) or not 0 < timestep_factor <= 1:
            raise ValueError("timestep_factor must be in (0,1]")
        self.rule = reinforcement or Reinforcement()
        parameters = parameters or Parameters()
        if self.rule.gamma_min > parameters.damping:
            raise ValueError("gamma_min must not exceed baseline damping")
        self.model, self.enabled, self.timestep_factor = model, bool(enabled), timestep_factor
        self.wave = (Field if model == "linear" else SexticField)(n, parameters, sponge=sponge)
        self.m = np.zeros_like(self.wave.u)
        self.rebase()

    @property
    def dt(self):
        return self.wave.dt*self.timestep_factor

    def density(self, u=None, v=None):
        w = self.wave
        u, v = (w.u if u is None else u), (w.v if v is None else v)
        density = .5*v*v
        if self.model == "sextic":
            density = density+w.nonlinear.density(u)
        for axis in (0, 1):
            edge = .25*w.parameters.speed**2*np.diff(u, axis=axis)**2/w.dx**2
            lower, upper = [slice(None)]*2, [slice(None)]*2
            lower[axis], upper[axis] = slice(None, -1), slice(1, None)
            density[tuple(lower)] += edge
            density[tuple(upper)] += edge
        return density

    def energy(self):
        return self.wave.dx**2*float(np.sum(self.density()))

    def rebase(self):
        self._validate(self.wave.u, self.wave.v, self.m)
        self.reference_energy = self.energy()
        self.input_work = self.damping_loss = self.source_action = 0.0

    def damping(self, m=None):
        baseline, rule = self.wave.parameters.damping, self.rule
        if not self.enabled or rule.alpha == 0:
            return np.full_like(self.m, baseline)
        m = self.m if m is None else m
        reduced = rule.gamma_min+(baseline-rule.gamma_min)/(1+rule.alpha*m)
        # Preserve exact accepted gamma0 at a never-reinforced site.
        return np.where(m == 0, baseline, reduced)

    def activity(self, u, v, source):
        if self.rule.activity == "source":
            if source is None:
                return np.zeros_like(u)
            return (self.wave.parameters.coupling*source/self.rule.source_scale)**2
        energy = self.density(u, v)
        return energy/(energy+self.rule.energy_scale)

    def update_map(self, m, activity, h):
        rate = self.rule.eta*activity
        total = rate+self.rule.decay
        equilibrium = np.divide(rate, total, out=np.zeros_like(m), where=total > 0)
        # expm1 retains very slow updates; the exact affine solution is convex.
        weight = -np.expm1(-total*h)
        return m*(1-weight)+equilibrium*weight

    def _validate(self, u, v, m):
        if any(a.shape != self.wave.u.shape or not np.isfinite(a).all() for a in (u, v, m)):
            raise FloatingPointError("nonfinite or wrong-shaped research state")
        if np.min(m) < 0 or np.max(m) > 1:
            raise FloatingPointError("reinforcement outside [0,1]; state rejected, not clipped")
        if max(float(np.max(np.abs(u))), float(np.max(np.abs(v)))) > 1e6:
            raise FloatingPointError("amplitude/velocity safety limit 1e6 exceeded")
        if self.model == "sextic":
            self.wave._validate_state(u, v)

    def step(self, source=None, dt=None):
        w, p = self.wave, self.wave.parameters
        h = self.dt if dt is None else dt
        if not math.isfinite(h) or not 0 < h <= self.dt*(1+1e-12):
            raise ValueError("step exceeds research wave/curvature bound")
        if source is not None and (source.shape != w.u.shape or not np.isfinite(source).all()
                                   or np.max(np.abs(source)) > 1+1e-12):
            raise ValueError("source must be finite, grid-shaped, and in [-1,1]")
        self._validate(w.u, w.v, self.m)
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            m_half = (self.update_map(self.m, self.activity(w.u, w.v, source), h/2)
                      if self.enabled else self.m)
            decay = np.exp(-.5*h*(self.damping(m_half)+w._sponge))
            force = 0.0 if source is None else p.coupling*source
            acceleration = p.speed**2*w.laplacian(w.u)+force
            if self.model == "sextic":
                acceleration -= w.nonlinear.gradient(w.u)
            half = decay*w.v+.5*h*acceleration
            u = w.u+h*half
            w._edge_zero(u)
            self._validate(u, w.v, m_half)
            acceleration = p.speed**2*w.laplacian(u)+force
            if self.model == "sextic":
                acceleration -= w.nonlinear.gradient(u)
            before_damping = half+.5*h*acceleration
            w._edge_zero(before_damping)
            v = decay*before_damping
            m = (self.update_map(m_half, self.activity(u, v, source), h/2)
                 if self.enabled else self.m)
            self._validate(u, v, m)
            work = self.input_work+(0 if source is None else p.coupling*w.dx**2*float(np.sum(source*(u-w.u))))
            loss = self.damping_loss+.5*w.dx**2*float(np.sum((1-decay**2)*(w.v**2+before_damping**2)))
            action = self.source_action+(0 if source is None else h*w.dx**2*float(np.sum(force**2)))
        if not all(math.isfinite(x) for x in (work, loss, action, w.time+h)) or w.time+h <= w.time:
            raise FloatingPointError("nonfinite accounting or unresolved research clock")
        if not self.enabled:
            # The disabled branch executes the actual production step, retaining
            # its floating-point ordering. Candidate work above validates the
            # independent ledger before the production state can be committed.
            w.step(source, h)
        else:
            w.u, w.v = u, v
            w.time += h
            w.step_count += 1
        self.m, self.input_work, self.damping_loss, self.source_action = m, work, loss, action

    def reset(self):
        self.wave.reset()
        self.m.fill(0)
        self.rebase()

    def save(self, path):
        raise NotImplementedError("research (u,v,m) is not an application checkpoint; reproduce its protocol")

    @classmethod
    def load(cls, path):
        raise NotImplementedError("application checkpoints do not represent reinforcement history")

    def diagnostics(self):
        energy = self.energy()
        return dict(time=self.wave.time, step=self.wave.step_count, dt=self.dt,
                    cfl=self.wave.parameters.speed*self.dt/self.wave.dx,
                    energy=energy, input_work=self.input_work, damping_loss=self.damping_loss,
                    source_action=self.source_action,
                    balance_residual=energy-self.reference_energy-self.input_work+self.damping_loss,
                    peak=float(np.max(np.abs(self.wave.u))),
                    velocity_peak=float(np.max(np.abs(self.wave.v))),
                    m_mean=float(np.mean(self.m)), m_max=float(np.max(self.m)),
                    m_quantiles=np.quantile(self.m, [.5, .9, .99]).tolist(),
                    coverage=float(np.mean(self.m >= .1)),
                    gamma_min=float(np.min(self.damping())), gamma_max=float(np.max(self.damping())))
