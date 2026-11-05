"""Independent refinement, exact-map, replay and source-off energy checks."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from sentio.field import Field
from sentio.sextic import SexticField
from .model import ReinforcedField, Reinforcement
from .experiments import integrate, patterns, provenance


def trial(model, activity, n, factor=1):
    f = ReinforcedField(n, model, Reinforcement(activity=activity), timestep_factor=factor)
    shapes, masks = patterns(n)
    records = integrate(f, shapes["familiar"], ((0,.5),), 2, masks)
    return f, records


def relative_state_errors(a, reference):
    return {name:float(np.linalg.norm(x-y)/max(np.linalg.norm(y),1e-30)) for name,x,y in
            (("u",a.wave.u,reference.wave.u),("v",a.wave.v,reference.wave.v),("m",a.m,reference.m))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; choose a new evidence path")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    started = time.monotonic()
    temporal, spatial, analytic, replay, unforced = [], [], [], [], []
    for model in ("linear","sextic"):
        for activity in ("source","wave"):
            states, residuals = [], []
            for factor in (1,.5,.25):
                f, records = trial(model,activity,65,factor)
                states.append(f)
                residuals.append(max(abs(d["balance_residual"]) for d in records))
            errors = [relative_state_errors(f,states[-1]) for f in states[:2]]
            temporal.append(dict(model=model,activity=activity,grid=65,factors=[1,.5,.25],
                                 relative_errors_to_quarter_step=errors,
                                 max_absolute_balance_residuals=residuals))
            assert residuals[0]/residuals[1] > 3.7
            assert errors[0]["u"]/errors[1]["u"] > 3.7
            grids = []
            for n in (33,65,129):
                f,_ = trial(model,activity,n)
                grids.append(f)
                if activity=="source":
                    shapes,_ = patterns(n)
                    a=.25*shapes["familiar"]**2
                    rate=2*a+.02
                    exact=(2*a/rate)*(-np.expm1(-rate*.5))*np.exp(-.02*1.5)
                    error=float(np.max(np.abs(f.m-exact)))
                    assert error < 1e-12
                    analytic.append(dict(model=model,grid=n,max_map_error=error))
            error_rows=[]
            for i,f in enumerate(grids[:2]):
                stride=2**i
                errors={name:float(np.sqrt(np.mean((x[::stride,::stride]-y[::4,::4])**2)))
                        for name,x,y in (("u",f.wave.u,grids[-1].wave.u),
                                         ("v",f.wave.v,grids[-1].wave.v),("m",f.m,grids[-1].m))}
                error_rows.append(errors)
            spatial.append(dict(model=model,activity=activity,grids=[33,65,129],
                                rms_errors_on_common_nodes_to_n129=error_rows))
            assert error_rows[1]["u"] < error_rows[0]["u"]
            if activity=="wave":
                assert error_rows[1]["m"] < error_rows[0]["m"]
            again,_=trial(model,activity,65)
            for name,a,b in (("u",again.wave.u,grids[1].wave.u),
                             ("v",again.wave.v,grids[1].wave.v),("m",again.m,grids[1].m)):
                np.testing.assert_array_equal(a,b)
            replay.append(dict(model=model,activity=activity,bitwise_equal=True))

            f=ReinforcedField(65,model,Reinforcement(activity=activity))
            axis=np.sin(np.pi*np.linspace(0,1,65))
            f.wave.u[:]=.02*np.outer(axis,axis)
            f.wave._edge_zero(f.wave.u)
            f.m[:]=np.outer(axis,axis)
            f.rebase()
            initial=f.energy()
            highest=initial
            while f.wave.time < 2-1e-12:
                f.step(dt=min(f.dt,2-f.wave.time))
                highest=max(highest,f.energy())
            assert highest/initial <= 1.0001
            unforced.append(dict(model=model,activity=activity,initial_energy=initial,
                                 peak_energy_ratio=highest/initial,final=f.diagnostics()))
    accepted=[]
    for model,cls in (("linear",Field),("sextic",SexticField)):
        a,b=cls(256),ReinforcedField(256,model,enabled=False)
        shapes,_=patterns(256)
        for _ in range(100):
            a.step(.5*shapes["familiar"])
            b.step(.5*shapes["familiar"])
        np.testing.assert_array_equal(a.u,b.wave.u)
        np.testing.assert_array_equal(a.v,b.wave.v)
        assert a.time==b.wave.time
        accepted.append(dict(model=model,n=256,steps=100,arrays_and_clock_bitwise_equal=True))
    report=dict(metadata=provenance(),wall_seconds=time.monotonic()-started,
                protocol="Gaussian .5-amplitude input for .5 model s, then off through t=2; fixed wall + sponge",
                temporal=temporal,spatial=spatial,analytic_source_map=analytic,
                deterministic_replay=replay,unforced_sine=unforced,accepted_disabled=accepted)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps(dict(report=str(args.output),wall_seconds=report["wall_seconds"])))


if __name__ == "__main__":
    main()
