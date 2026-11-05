"""Detector controls, immutable accepted-baseline regression and bounded guards."""
import argparse
from dataclasses import replace
import hashlib
import importlib
import json
import math
from pathlib import Path
import subprocess
import sys
import types

import numpy as np

from sentio.field import Field
from sentio.sextic import SexticField
from sentio.models import load_field
from sentio.reinforcement import Reinforcement, ReinforcementParameters
from research.issue_11.experiments import provenance


def trace(values, h, parameters):
    r=Reinforcement(17,parameters)
    u,v=np.zeros((17,17)),np.zeros((17,17))
    for displacement,velocity in values:
        u[1:-1,1:-1]=displacement; v[1:-1,1:-1]=velocity
        r.commit(r.propose(u,v,h))
    return dict(events=int(r.events[8,8]),m=float(r.m[8,8]))


def controls():
    p=ReinforcementParameters(forgetting=0)
    out=dict(held=[],episodes=[],continuous=[],saturation=[],forgetting=[])
    for amplitude in (.006,.06,6000):
        for h in (.01,.005):
            result=trace(((amplitude,0) for _ in range(round(10/h))),h,p)
            assert result['events']==1 and result['m']==.02
            out['held'].append(dict(amplitude=amplitude,h=h,**result))
    for period in (.7,1.,2.):
        for h in (.01,.005):
            for amplitude in (.006,.06):
                values=((amplitude if t%period < .2-1e-9 else 0,0) for t in np.arange(h/2,8*period,h))
                result=trace(values,h,p)
                assert result['events']==8
                out['episodes'].append(dict(period=period,h=h,amplitude=amplitude,**result))
    for detector in ('envelope','phase'):
        for frequency in (.25,.5,1.):
            for h in (.01,.005):
                omega=2*np.pi*frequency
                values=((.02*np.sin(omega*t),.02*omega*np.cos(omega*t)) for t in np.arange(h,4/frequency+h/2,h))
                result=trace(values,h,replace(p,detector=detector))
                out['continuous'].append(dict(detector=detector,frequency=frequency,h=h,**result))
    for count in (1,10,100,1000):
        values=((.01 if i%60<30 else 0,0) for i in range(count*60))
        result=trace(values,.01,p)
        assert result['events']==count
        expected=1-.98**count
        assert abs(result['m']-expected)<1e-14 and result['m']<=1
        out['saturation'].append(dict(count=count,h=.01,expected=expected,**result))
    for h in (.01,.005):
        r=Reinforcement(17);r.m[1:-1,1:-1]=.8
        zero=np.zeros((17,17));rng=np.random.default_rng(20261105)
        for _ in range(round(20/h)):
            noise=rng.uniform(-1e-5,1e-5,(17,17))
            r.commit(r.propose(noise,zero,h))
        expected=.8*np.exp(-.005*20)
        assert not r.events.any()
        out['forgetting'].append(dict(h=h,duration=20,expected=expected,actual=float(r.m[8,8]),absolute_error=abs(float(r.m[8,8])-expected)))
    return out


def baseline(directory):
    directory.mkdir(parents=True,exist_ok=True)
    base='b801d313d6fbcb7fbc27e23ea1c076293b774879'
    hashes={}
    for name in ('field','sextic','grid'):
        raw=subprocess.check_output(['git','show',f'{base}:sentio/{name}.py'])
        (directory/f'{name}.py').write_bytes(raw)
        hashes[name]=hashlib.sha256(raw).hexdigest()
    package=types.ModuleType('_sentio_issue11_baseline');package.__path__=[str(directory)]
    sys.modules[package.__name__]=package
    old_field=importlib.import_module(package.__name__+'.field').Field
    old_sextic=importlib.import_module(package.__name__+'.sextic').SexticField
    results=[]
    for old_cls,cls in ((old_field,Field),(old_sextic,SexticField)):
        for n in (33,256):
            for allocated in (False,True):
                old,new=old_cls(n),cls(n)
                if allocated:
                    new.reinforcement=Reinforcement(n,enabled=False)
                    new.reinforcement.m[1:-1,1:-1]=.8
                for step in range(120):
                    axis=np.linspace(0,1,n)
                    s=.2*np.sin(3*np.pi*axis[:,None])*np.cos(2*np.pi*axis[None,:])*math.sin(step/17)
                    old.step(s);new.step(s)
                np.testing.assert_array_equal(old.u,new.u)
                np.testing.assert_array_equal(old.v,new.v)
                assert old.time==new.time and old.diagnostics()==new.diagnostics()
                path=directory/f'legacy-{cls.__name__}-{n}-{allocated}.npz'
                old.save(path)
                restored=load_field(path)
                np.testing.assert_array_equal(restored.u,old.u)
                np.testing.assert_array_equal(restored.v,old.v)
                assert restored.diagnostics()==old.diagnostics() and restored.reinforcement is None
                results.append(dict(model=cls.__name__,n=n,allocated_disabled=allocated,steps=120,
                                    arrays_clock_diagnostics_exact=True,legacy_checkpoint_exact=True))
    return dict(commit=base,source_sha256=hashes,runs=results)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as stream:
        report=dict(provenance=provenance(),checks_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    detectors=controls(),baseline=baseline(a.output.parent/'baseline_source'))
        json.dump(report,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps(dict(output=str(a.output),baseline_runs=len(report['baseline']['runs']))))


if __name__=='__main__':
    main()
