"""Experimental event-counted damping state; no source, camera or display access.

The envelope detector counts activity episodes, not solver steps or energy.
The phase alternative is retained for explicit numerical comparisons only.
"""

from dataclasses import dataclass, replace
import math

import numpy as np


@dataclass(frozen=True)
class ReinforcementParameters:
    threshold: float = .005           # displacement units
    gain: float = .02                # maximum fraction of remaining capacity / event
    forgetting: float = .005         # inverse model seconds
    quiet_time: float = .25          # continuously below half threshold to re-arm
    refractory: float = .5           # minimum model seconds between events
    velocity_time: float = .1        # converts velocity to displacement units
    floor: float = .05               # gamma_min / baseline gamma
    exponent: float = 2.0
    detector: str = "envelope"

    def __post_init__(self):
        for name in ("threshold", "gain", "forgetting", "quiet_time", "refractory",
                     "velocity_time", "floor", "exponent"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"reinforcement {name} must be finite and nonnegative")
        if (self.threshold < 1e-12 or self.threshold > 1e6 or not 0 <= self.gain <= .05
                or self.forgetting > 100 or not 0 <= self.floor <= 1
                or not .1 <= self.exponent <= 16):
            raise ValueError("reinforcement requires threshold 1e-12…1e6, gain 0….05, floor 0…1, "
                             "forgetting 0…100 / s, exponent .1…16")
        if any(not .001 <= getattr(self, k) <= 1000
               for k in ("quiet_time", "refractory", "velocity_time")):
            raise ValueError("detector times must be .001…1000 model seconds")
        if self.detector not in ("envelope", "phase"):
            raise ValueError("unknown reinforcement detector")

    @property
    def step_bound(self):
        return min(self.quiet_time / 4, self.refractory / 8, self.velocity_time / 8)


class Reinforcement:
    array_dtypes = dict(m=np.dtype("float64"), quiet=np.dtype("float64"),
                        cooldown=np.dtype("float64"), armed=np.dtype("bool"),
                        polarity=np.dtype("int8"), events=np.dtype("uint64"))

    def __init__(self, n, parameters=None, enabled=True):
        self.parameters = parameters or ReinforcementParameters()
        self.enabled = bool(enabled)
        for name, dtype in self.array_dtypes.items():
            setattr(self, name, np.zeros((n, n), dtype=dtype))
        self.armed.fill(True)

    def configure(self, **changes):
        candidate = replace(self.parameters, **changes)
        if candidate.detector != self.parameters.detector:
            raise ValueError("changing detector requires a fresh reinforcement state")
        # Preserve latches: tuning must not re-count an already elevated wave.
        self.parameters = candidate

    def reset(self):
        for name in self.array_dtypes:
            getattr(self, name).fill(name == "armed")

    def damping(self, baseline, half_step=0):
        p = self.parameters
        m = self.m * math.exp(-p.forgetting * half_step)
        fraction = p.floor + (1-p.floor) * (1-m)**p.exponent
        return baseline * fraction

    def propose(self, u, v, h):
        """Pure candidate update at the accepted wave step endpoint.

        Source-driven and propagated waves are deliberately indistinguishable.
        A held high envelope is one event, even with oscillating displacement.
        """
        p = self.parameters
        cooldown = np.maximum(0, self.cooldown-h)
        if p.detector == "envelope":
            activity = np.maximum(np.abs(u), p.velocity_time*np.abs(v))
            quiet = np.where(activity <= .5*p.threshold, self.quiet+h, 0)
            quiet = np.minimum(quiet, p.quiet_time)
            armed = self.armed | (quiet >= p.quiet_time)
            event = armed & (activity >= p.threshold) & (cooldown <= 0)
            armed = armed & ~event
            polarity = self.polarity.copy()
        else:
            sign = np.sign(u).astype(np.int8)
            event = ((np.abs(u) >= p.threshold) & (sign != self.polarity)
                     & (cooldown <= 0))
            polarity = np.where(event, sign, self.polarity).astype(np.int8)
            quiet, armed = self.quiet.copy(), self.armed.copy()
        event[[0, -1], :] = False
        event[:, [0, -1]] = False
        cooldown = np.where(event, p.refractory, cooldown)
        m = self.m * math.exp(-p.forgetting*h)
        m = np.where(event, m+p.gain*(1-m), m)
        if np.any(event & (self.events == np.iinfo(np.uint64).max)):
            raise FloatingPointError("reinforcement event counter exhausted; step rejected")
        candidate = dict(m=m, quiet=quiet, cooldown=cooldown, armed=armed,
                         polarity=polarity, events=self.events+event.astype(np.uint64))
        if not np.isfinite(m).all() or np.any(m < 0) or np.any(m > 1):
            raise FloatingPointError("invalid reinforcement strength; step rejected")
        return candidate

    def commit(self, candidate):
        for name, value in candidate.items():
            setattr(self, name, value)

    def validate(self, n):
        for name, dtype in self.array_dtypes.items():
            a = getattr(self, name)
            if a.shape != (n, n) or a.dtype != dtype or not np.isfinite(a).all():
                raise ValueError(f"invalid reinforcement {name}")
        if (np.any(self.m < 0) or np.any(self.m > 1) or np.any(self.quiet < 0)
                or np.any(self.quiet > 1000) or np.any(self.cooldown < 0)
                or np.any(self.cooldown > 1000) or np.any(self.polarity < -1) or np.any(self.polarity > 1)):
            raise ValueError("reinforcement state outside bounds")
        for name in ("m", "events"):
            a = getattr(self, name)
            if np.any(a[[0, -1], :]) or np.any(a[:, [0, -1]]):
                raise ValueError("reinforcement violates fixed boundary")

    def diagnostics(self, baseline):
        gamma = self.damping(baseline) if self.enabled else np.full_like(self.m, baseline)
        return dict(enabled=self.enabled, detector=self.parameters.detector,
                    mean=float(self.m.mean()), maximum=float(self.m.max()),
                    coverage=float(np.mean(self.m >= .1)),
                    events_mean=float(self.events.mean()), events_max=int(self.events.max()),
                    gamma_min=float(gamma.min()), gamma_max=float(gamma.max()))
