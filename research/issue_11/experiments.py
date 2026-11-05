"""Bounded deterministic comparisons of the actual application solvers/detector."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
import argparse
import hashlib
import json
import math
import multiprocessing
from pathlib import Path
import platform
import time

import numpy as np

from sentio.field import Field, Parameters
from sentio.sextic import SexticField
from sentio.reinforcement import Reinforcement, ReinforcementParameters


@dataclass(frozen=True)
class Case:
    model: str = "linear"
    kind: str = "repeated"
    detector: str = "envelope"
    enabled: bool = True
    n: int = 33
    factor: float = 1.
    amplitude: float = .25
    spacing: float = 4.
    pulses: int = 16
    frequency: float = 1.
    mode: int = 1
    sponge: bool = True
    input_gain: float = 2.


def patterns(n):
    axis = np.linspace(0, 1, n)
    x, y = np.meshgrid(axis, axis)
    left = np.exp(-((x-.35)**2+(y-.5)**2)/.07**2)
    right = np.flip(left, axis=1).copy()
    Field._edge_zero(left)
    Field._edge_zero(right)
    return x, y, left, right, (x-.35)**2+(y-.5)**2 <= .14**2, (x-.65)**2+(y-.5)**2 <= .14**2


def density(f):
    if isinstance(f, SexticField):
        return f.energy_density()
    out = .5*f.v*f.v
    for axis in (0, 1):
        edge = .25*f.parameters.speed**2*np.diff(f.u, axis=axis)**2/f.dx**2
        a, b = [slice(None)]*2, [slice(None)]*2
        a[axis], b[axis] = slice(None, -1), slice(1, None)
        out[tuple(a)] += edge
        out[tuple(b)] += edge
    return out


def measure(f, masks, work, loss, initial):
    r, e = f.reinforcement, density(f)*f.dx**2
    out = dict(t=f.time, energy=float(e.sum()), work=work, loss=loss,
               residual=float(e.sum())-initial-work+loss,
               peak=float(np.max(np.abs(f.u))), **r.diagnostics(f.parameters.damping))
    for name, mask in zip(("left", "right"), masks):
        out.update({name+"_energy":float(e[mask].sum()), name+"_m":float(r.m[mask].mean()),
                    name+"_events":float(r.events[mask].mean())})
    return out


def evolve(f, end, source_at, boundaries, masks, factor=1., cadence=.5):
    """Land exactly on prescribed forcing/sample boundaries; no frame clock."""
    times = sorted(set([end, *[float(x) for x in np.arange(cadence, end, cadence)],
                        *[x for x in boundaries if 0 < x < end]]))
    initial = float(np.sum(density(f))*f.dx**2)
    work = loss = action = 0.
    rows = [measure(f, masks, work, loss, initial)]
    for target in times:
        while target-f.time > 1e-12:
            h = min(f.dt*factor, target-f.time)
            source = source_at(f.time+1e-10)
            old_u, old_v = f.u, f.v
            decay = f._damping(h)
            f.step(source, h)
            work += (0 if source is None else f.parameters.coupling*f.dx**2*float(np.sum(source*(f.u-old_u))))
            loss += .5*f.dx**2*float(np.sum((1-decay**2)*(old_v**2+(f.v/decay)**2)))
            action += (0 if source is None else h*f.dx**2*float(np.sum((f.parameters.coupling*source)**2)))
        rows.append(measure(f, masks, work, loss, initial))
    return dict(curves=rows, source_action=action,
                relative_balance=max(abs(x['residual']) for x in rows)/max(initial, abs(work), 1e-30),
                state_sha256={name:hashlib.sha256(getattr(f,name).tobytes()).hexdigest() for name in ('u','v')},
                map_sha256=hashlib.sha256(f.reinforcement.m.tobytes()).hexdigest())


def run_case(case, include_map=False):
    start = time.perf_counter()
    cls = SexticField if case.model == "sextic" else Field
    f = cls(case.n, parameters=Parameters(coupling=case.input_gain), sponge=case.sponge)
    f.reinforcement = Reinforcement(case.n, ReinforcementParameters(detector=case.detector), case.enabled)
    x, y, left, right, lm, rm = patterns(case.n)
    masks = lm, rm
    last = (case.pulses-1)*case.spacing
    pulses = [(i*case.spacing, i*case.spacing+.5) for i in range(case.pulses)]
    end, off = last+8, last+.5
    if case.kind in ("shock", "single"):
        pulses = [(last, last+.5)]
    if case.kind in ("noise", "sine", "standing"):
        end, off, pulses = 16., 8., [(0.,8.)]
    if case.kind == "bursts":
        duration = 2/case.frequency  # exactly two forcing cycles / burst
        pulses = [(i*(duration+4), i*(duration+4)+duration) for i in range(8)]
        off, end = pulses[-1][1], pulses[-1][1]+8
    if case.kind == "standing":
        off = 0.
        f.u = .02*np.sin(case.mode*np.pi*x)*np.sin(case.mode*np.pi*y)
        f._edge_zero(f.u)
        if isinstance(f, SexticField):
            f.rebase_energy()
    noise = np.random.default_rng(20261105).uniform(-1e-5, 1e-5, (480, case.n, case.n)) if case.kind == "noise" else None
    def source_at(t):
        if case.kind == "standing":
            return None
        if not any(a <= t < b for a,b in pulses):
            return None
        if noise is not None:
            return noise[min(int(t*30), 479)]
        amplitude = 1. if case.kind == "shock" else case.amplitude
        if case.kind == "sine":
            return amplitude*math.sin(2*math.pi*case.frequency*t)*left
        if case.kind == "bursts":
            a = next(a for a,b in pulses if a <= t < b)
            return amplitude*math.sin(2*math.pi*case.frequency*(t-a))*np.sin(case.mode*np.pi*x)*np.sin(case.mode*np.pi*y)
        return amplitude*left
    boundaries = [t for pulse in pulses for t in pulse]
    if noise is not None:
        boundaries += [i/30 for i in range(241)]
    result = dict(case=asdict(case), parameters=asdict(f.reinforcement.parameters), dt=f.dt,
                  source_off=off, status="complete")
    try:
        result['training'] = evolve(f, end, source_at, boundaries, masks, case.factor)
        result['training']['final'] = result['training']['curves'][-1]
        off_row = min(result['training']['curves'], key=lambda r:abs(r['t']-off))
        result['training']['retention'] = result['training']['final']['energy']/max(off_row['energy'],1e-30)
        result['training']['source_off_max_energy_increase'] = max(
            [0.] + [b['energy']-a['energy'] for a,b in zip(result['training']['curves'],result['training']['curves'][1:]) if a['t'] >= off-1e-10])
        trained = f.reinforcement.m.copy()
        result['probes'] = {}
        for label, memory in (("retained",trained), ("erased",np.zeros_like(trained))):
            probe = cls(case.n, sponge=case.sponge)
            probe.reinforcement = Reinforcement(case.n, replace(f.reinforcement.parameters,gain=0), case.enabled)
            probe.reinforcement.m[:] = memory
            probe.v[:] = .1*(left+right)  # identical initial energy on each side
            if isinstance(probe, SexticField):
                probe.rebase_energy()
            out = evolve(probe, 6, lambda t:None, [], masks, case.factor)
            ts = np.array([r['t'] for r in out['curves']])
            for key in ("energy", "left_energy", "right_energy"):
                out[key+"_integral"] = float(np.trapezoid([r[key] for r in out['curves']],ts))
            result['probes'][label] = out
        result['probe_gain'] = {key:result['probes']['retained'][key+'_integral']/result['probes']['erased'][key+'_integral']
                                for key in ("energy", "left_energy", "right_energy")}
    except (FloatingPointError, ValueError, OverflowError) as exc:
        result.update(status="stopped", error=str(exc), stop_time=f.time)
    result['wall_seconds'] = time.perf_counter()-start
    if include_map and result['status'] == 'complete':
        result['map'] = trained
    return result


def cases(suite):
    result=[]
    for model in ('linear','sextic'):
        base=Case(model=model)
        if suite == 'primary':
            result += [base, replace(base,kind='shock'), replace(base,kind='single'),
                       replace(base,enabled=False), replace(base,detector='phase'), replace(base,detector='phase',kind='shock')]
        elif suite == 'controls':
            result += [replace(base,amplitude=a) for a in (.125,.5)]
            result += [replace(base,spacing=s) for s in (2.,8.)]
            result += [replace(base,sponge=False), replace(base,kind='noise'), replace(base,kind='standing')]
            result += [replace(base,kind='sine',frequency=f) for f in (1.,4.)]
            result += [replace(base,kind='bursts',frequency=f,mode=k) for f,k in ((.5,1),(1.,1),(2.,1),(1.,3))]
        elif suite == 'refinement':
            result += [replace(base,n=n) for n in (65,129)] + [replace(base,factor=.5)]
        elif suite == 'strong-shock':
            result += [replace(base,kind='shock',input_gain=20), replace(base,kind='shock',input_gain=20,detector='phase')]
        elif suite == 'full-grid':
            result += [replace(base,n=256,pulses=3)]
    return result


def provenance():
    paths=['sentio/field.py','sentio/sextic.py','sentio/reinforcement.py',str(Path(__file__).relative_to(Path.cwd()))]
    return dict(base='b801d313d6fbcb7fbc27e23ea1c076293b774879',python=platform.python_version(),numpy=np.__version__,
                platform=platform.platform(),files={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths},noise_seed=20261105)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--suite',choices=('primary','controls','refinement','full-grid','strong-shock'),required=True)
    p.add_argument('--workers',type=int,choices=range(1,5),default=2)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:
        started=time.perf_counter()
        with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
            results=[]
            for result in pool.map(run_case,cases(args.suite)):
                results.append(result)
                print(json.dumps(dict(case=result['case'],status=result['status'],wall=result['wall_seconds'])),flush=True)
        json.dump(dict(suite=args.suite,provenance=provenance(),wall_seconds=time.perf_counter()-started,results=results),stream,indent=2,allow_nan=False)
        stream.write('\n')


if __name__ == '__main__':
    main()
