"""Short core-only cost/finite-state check at all supported application grids."""
import argparse
import gc
import json
from pathlib import Path
import time

from sentio.field import Field
from sentio.sextic import SexticField
from sentio.reinforcement import Reinforcement
from sentio.metrics import process_memory
from .experiments import provenance, patterns


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as out:
        results=[]
        for n in (256,512,1024):
            for cls in (Field,SexticField):
                for enabled in (False,True):
                    gc.collect()
                    f=cls(n)
                    if enabled:
                        f.reinforcement=Reinforcement(n)
                    source=.25*patterns(n)[2]
                    for _ in range(5):
                        f.step(source)
                    start=time.perf_counter()
                    for _ in range(30):
                        f.step(source)
                    elapsed=time.perf_counter()-start
                    row=dict(n=n,model=cls.__name__,enabled=enabled,warmup_steps=5,measured_steps=30,
                             wall_seconds=elapsed,steps_per_second=30/elapsed,model_seconds_per_wall_second=30*f.dt/elapsed,
                             diagnostics=f.diagnostics(),memory=process_memory())
                    if enabled:
                        row['reinforcement']=f.reinforcement.diagnostics(f.parameters.damping)
                    assert row['diagnostics']['finite']
                    results.append(row)
                    del f,source
        json.dump(dict(provenance=provenance(),results=results,limitations='One short core window, no acquisition/rendering; not a steady-state live rate or long-run stability test. Process peak memory is cumulative.'),out,indent=2,allow_nan=False)
        out.write('\n')
    print(json.dumps(dict(output=str(a.output),runs=len(results))))


if __name__=='__main__':
    main()
