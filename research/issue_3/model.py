"""Potential-based wave experiments built around the accepted linear stencil.

All potentials are functions of the local signed field, with no spatial
template, feedback, classification, or modification of the production solver.
"""

from dataclasses import dataclass
import math

import numpy as np

from sentio.field import Field, Parameters


MODELS = ("linear", "massive", "quartic", "sextic", "sine_gordon")


@dataclass(frozen=True)
class Potential:
    name: str = "sextic"
    omega: float = 8.0
    amplitude: float = 0.1
    envelope: float = 4.0

    def __post_init__(self):
        if self.name not in MODELS:
            raise ValueError("unknown research model")
        if not all(math.isfinite(x) and x > 0 for x in (self.omega, self.amplitude, self.envelope)):
            raise ValueError("potential scales and envelope must be positive finite numbers")
        # This harness tests a bounded research domain, not arbitrary parameters.
        if not (1 <= self.omega <= 16 and .025 <= self.amplitude <= 1 and 1 <= self.envelope <= 4):
            raise ValueError("outside research domain: omega 1..16, amplitude .025..1, envelope 1..4")

    def gradient(self, u):
        if self.name == "linear":
            return np.zeros_like(u)
        if self.name == "massive":
            return self.omega**2 * u
        if self.name == "sine_gordon":
            return self.omega**2 * self.amplitude * np.sin(u / self.amplitude)
        q2 = (u / self.amplitude)**2
        factor = 1 + q2 if self.name == "quartic" else 1 + q2 * (-1 + .3*q2)
        return self.omega**2 * u * factor

    def density(self, u):
        if self.name == "linear":
            return np.zeros_like(u)
        if self.name == "massive":
            return .5 * self.omega**2 * u*u
        if self.name == "sine_gordon":
            return 2 * (self.omega*self.amplitude*np.sin(u/(2*self.amplitude)))**2
        q2 = (u/self.amplitude)**2
        factor = .5 + .25*q2 if self.name == "quartic" else .5 + q2*(-.25 + .05*q2)
        return self.omega**2 * u*u * factor

    @property
    def curvature_bound(self):
        if self.name == "linear":
            return 0.0
        if self.name in ("massive", "sine_gordon"):
            return self.omega**2
        q = self.envelope
        # Triangle-inequality bound on |V''| throughout the enforced envelope.
        return self.omega**2 * (1 + 3*q*q + (1.5*q**4 if self.name == "sextic" else 0))

    def check_envelope(self, u):
        if self.name in ("quartic", "sextic") and np.max(np.abs(u)) > self.amplitude*self.envelope:
            raise FloatingPointError("polynomial research envelope exceeded; state rejected, not clipped")


class ResearchField(Field):
    """Same grid, stencil, damping split and state convention, plus -V'(u).

    A fixed step is bounded by the wave frequency AND a predeclared potential
    curvature bound. Negative curvature can cause physical growth; the bound
    is not a nonlinear stability theorem. Refinement and balance checks remain
    necessary. Polynomial excursions beyond the certified envelope stop a run.
    """

    def __init__(self, n=65, parameters=None, potential=None, length=1.0,
                 timestep_factor=1.0, sponge=True):
        if not math.isfinite(length) or not 1 <= length <= 2:
            raise ValueError("research domain length must be 1..2")
        if not math.isfinite(timestep_factor) or not 0 < timestep_factor <= 1:
            raise ValueError("time-step factor must be in (0,1]")
        self.potential = potential or Potential()
        self.length, self.timestep_factor = length, timestep_factor
        super().__init__(n, parameters or Parameters(), sponge)
        self.dx = length/(n-1)
        self.input_work = self.damping_loss = 0.0

    @property
    def dt(self):
        wave_dt = super().dt
        frequency2 = 8*self.parameters.speed**2/self.dx**2 + self.potential.curvature_bound
        return self.timestep_factor * min(wave_dt, 1.6/math.sqrt(frequency2))

    def step(self, source=None, dt=None):
        h = self.dt if dt is None else dt
        if not math.isfinite(h) or not 0 < h <= self.dt*(1+1e-12):
            raise ValueError("step exceeds research wave/potential bound")
        if source is not None and (source.shape != self.u.shape or not np.isfinite(source).all()
                                   or np.max(np.abs(source)) > 1+1e-12):
            raise ValueError("invalid research source")
        old_u, old_v = self.u, self.v
        self.potential.check_envelope(old_u)
        p = self.parameters
        decay = np.exp(-.5*h*(p.damping + self._sponge))
        if self.potential.name == "linear":
            # Exercise the actual accepted implementation for the baseline.
            super().step(source, h)
        else:
            force = 0.0 if source is None else p.coupling*source
            with np.errstate(over="raise", invalid="raise"):
                a = p.speed**2*self.laplacian(old_u) + force - self.potential.gradient(old_u)
                half = decay*old_v + .5*h*a
                u = old_u + h*half
                self._edge_zero(u)
                self.potential.check_envelope(u)
                v = decay*(half + .5*h*(p.speed**2*self.laplacian(u) + force - self.potential.gradient(u)))
                self._edge_zero(v)
            if not np.isfinite(u).all() or not np.isfinite(v).all() or max(np.max(np.abs(u)), np.max(np.abs(v))) > 1e6:
                raise FloatingPointError("nonfinite or magnitude guard; research step rejected")
            self.u, self.v = u, v
            self.time += h
            self.step_count += 1
        # Constant source does exact work κ S · Δu in each held-source step.
        if source is not None:
            self.input_work += p.coupling*self.dx**2*float(np.sum(source*(self.u-old_u)))
        # Exact kinetic loss at the two damping substeps. Edge velocities = 0.
        before_second_damping = self.v/decay
        self.damping_loss += .5*self.dx**2*float(np.sum((1-decay**2)*(old_v**2 + before_second_damping**2)))

    def energy_density(self):
        density = .5*self.v**2 + self.potential.density(self.u)
        for axis in (0, 1):
            edge = .25*self.parameters.speed**2*np.diff(self.u, axis=axis)**2/self.dx**2
            lower, upper = [slice(None)]*2, [slice(None)]*2
            lower[axis], upper[axis] = slice(None, -1), slice(1, None)
            density[tuple(lower)] += edge
            density[tuple(upper)] += edge
        return density

    def energy(self):
        return self.dx**2*float(np.sum(self.energy_density()))

    def save(self, path):
        raise NotImplementedError("research states must not masquerade as linear application checkpoints")

    @classmethod
    def load(cls, path):
        raise NotImplementedError("application checkpoint import is outside this isolated research")


def sine_spectrum(u, length):
    """DST-I power from odd-extension FFT; compatible with fixed zero edges."""
    modes = u[1:-1, 1:-1]
    for axis in (0, 1):
        m = modes.shape[axis]
        shape = list(modes.shape)
        shape[axis] = 2*(m+1)
        odd = np.zeros(shape)
        positive, negative = [slice(None)]*2, [slice(None)]*2
        positive[axis], negative[axis] = slice(1, m+1), slice(m+2, None)
        odd[tuple(positive)] = modes
        odd[tuple(negative)] = -np.flip(modes, axis)
        modes = -np.fft.rfft(odd, axis=axis).imag[tuple(positive)]/2
    power = modes**2
    k = np.arange(1, u.shape[0]-1)
    cycles = np.sqrt(k[:, None]**2 + k[None, :]**2)/(2*length)
    total = float(np.sum(power))
    if float(np.sum(u*u))*(length/(len(u)-1))**2 < 1e-24:
        return dict(spectral_low=None, spectral_mid=None, spectral_high=None, cycles_rms=None)
    return dict(spectral_low=float(np.sum(power[cycles <= 4])/total),
                spectral_mid=float(np.sum(power[(cycles > 4) & (cycles <= 12)])/total),
                spectral_high=float(np.sum(power[cycles > 12])/total),
                cycles_rms=float(np.sqrt(np.sum(power*cycles**2)/total)))


def measure(field, initial_energy):
    density = field.energy_density()
    total = float(np.sum(density))
    energy = field.dx**2*total
    axis = np.linspace(-field.length/2, field.length/2, field.n)
    core = axis[:, None]**2 + axis[None, :]**2 <= .2**2
    core_energy = field.dx**2*float(np.sum(density[core]))
    participation = total**2/(density.size*float(np.sum(density**2))) if energy > 1e-20 else None
    return dict(time=field.time, minimum=float(field.u.min()), maximum=float(field.u.max()),
                peak=float(np.max(np.abs(field.u))), rms=float(np.sqrt(np.mean(field.u**2))),
                velocity_peak=float(np.max(np.abs(field.v))), energy=energy,
                core_energy=core_energy, core_fraction=core_energy/energy if energy > 1e-20 else None,
                participation=participation, input_work=field.input_work, damping_loss=field.damping_loss,
                balance_residual=energy-initial_energy-field.input_work+field.damping_loss,
                **sine_spectrum(field.u, field.length))
