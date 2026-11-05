"""Visible application validation of issue 11; camera preview stays disabled."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sentio.gui import Window
from sentio.runtime import Runtime


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',choices=('stationary','camera'),default='stationary')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--screenshot',type=Path)
    args=parser.parse_args()
    if args.output.exists() or (args.screenshot and args.screenshot.exists()):
        parser.error('choose fresh output paths')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    app=QApplication([])
    if app.platformName() in ('offscreen','minimal'):
        parser.error('requires a visible desktop Qt platform')
    runtime=Runtime(source=args.source,log_path=args.output.with_suffix('.jsonl'))
    window=Window(runtime)
    checks, measurements, acknowledgements=[],{},[]
    failure=''
    def wait(predicate,timeout=10):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            app.processEvents()
            if runtime.failure:
                raise AssertionError(runtime.failure)
            if predicate():
                return
            time.sleep(.01)
        raise AssertionError('application acknowledgement timed out')
    def command(name,value=None,action=None,accepted=True):
        began=time.monotonic()
        if action:
            action()
            revision=runtime.command_sequence
        else:
            revision=window.send(name,value)
        wait(lambda:runtime.latest() is not None and runtime.latest()['command_revision']>=revision)
        assert runtime.latest()['message'].startswith('Rejected') != accepted, runtime.latest()['message']
        acknowledgements.append(dict(name=name,value=value,seconds=time.monotonic()-began,accepted=accepted))
    def typed(key,value,accepted=True):
        def action():
            edit=window.controls[key]
            edit.setFocus(); edit.selectAll()
            QTest.keyClicks(edit,str(value)); QTest.keyClick(edit,Qt.Key.Key_Return)
        command(key,value,action,accepted)
    def observe(seconds,label):
        began=time.monotonic(); samples=[]
        while time.monotonic()-began<seconds:
            app.processEvents()
            s=runtime.latest()
            assert not s['fault'] and not runtime.failure, s['fault'] or runtime.failure
            if args.source=='camera':
                assert s['capture']['state']=='running',s['capture']
            if time.monotonic()-began>=2:
                samples.append(dict(speed=s['sim_speed'],steps=s['steps_per_second'],fps=s['capture']['fps'],
                                    age_ms=1000*s['input_age'],rss_mib=s['memory']['resident_mib']))
            time.sleep(.01)
        measurements[label]=dict(summary={k:dict(min=float(np.min([s[k] for s in samples])),
                                                median=float(np.median([s[k] for s in samples])),
                                                max=float(np.max([s[k] for s in samples]))) for k in samples[0]},
                                 diagnostics=runtime.latest()['diagnostics'])
    runtime.start(); window.show()
    try:
        wait(lambda:runtime.latest() is not None and runtime.latest()['diagnostics']['step']>10)
        if args.source=='camera':
            wait(lambda:runtime.latest()['capture']['state']=='running')
        assert not runtime.latest()['reinforcement_enabled']
        assert not window.reinforcement_panel.isVisible()
        checks.append('default OFF and collapsed controls')
        observe(4,'linear_off')
        window.reinforcement_details.click()
        command('reinforcement_enabled',True,lambda:window.reinforcement_toggle.setChecked(True))
        command('map_enabled',True,lambda:window.map_toggle.setChecked(True))
        typed('display_range',.025)
        observe(10,'linear_on')
        command('paused',True)
        before=runtime.latest()['u'].copy(); memory=runtime.latest()['m'].copy()
        assert memory.max()>0,'no reinforcement formed in visible run'
        command('map_enabled',False)
        typed('display_range',.01)
        command('map_enabled',True)
        np.testing.assert_array_equal(runtime.latest()['u'],before)
        np.testing.assert_array_equal(runtime.latest()['m'],memory)
        checks.append('map/display controls leave u and m unchanged while paused')
        typed('gain',.03); typed('gain',.1,False)
        assert float(runtime.latest()['reinforcement_parameters']['gain'])==.03
        checks.append('Enter applies valid gain; oversized event gain rejected')
        checkpoint=args.output.with_suffix('.npz')
        command('save',str(checkpoint))
        command('reset')
        assert not runtime.latest()['u'].any() and not runtime.latest()['m'].any()
        command('load',str(checkpoint))
        np.testing.assert_array_equal(runtime.latest()['u'],before)
        np.testing.assert_array_equal(runtime.latest()['m'],memory)
        assert runtime.latest()['paused'] and not runtime.latest()['coupling_enabled']
        checks.append('schema 3 save/reset/restore exact and paused/uncoupled')
        command('reinforcement_enabled',False)
        command('paused',False)
        observe(3,'linear_off_retained')
        np.testing.assert_array_equal(runtime.latest()['m'],memory)
        checks.append('OFF freezes reinforcement while baseline wave continues')
        command('model','sextic')
        assert not runtime.latest()['reinforcement_enabled']
        command('reinforcement_enabled',True)
        command('coupling_enabled',True); command('paused',False)
        observe(12,'sextic_on')
        assert runtime.latest()['m'].max()>0
        command('coupling_enabled',False)
        observe(3,'sextic_source_off')
        checks.append('both models evolve with reinforcement; input-off does not reset the field')
        command('paused',True)
        # Bring the optional diagnostic into the panel viewport for inspection.
        wait(lambda:window.pause.isChecked())
        from PySide6.QtWidgets import QScrollArea
        window.findChild(QScrollArea).ensureWidgetVisible(window.map_image)
        window.refresh(); app.processEvents()
        if args.screenshot:
            assert window.grab().save(str(args.screenshot))
    except Exception as exc:
        failure=f'{type(exc).__name__}: {exc}'
    final=runtime.latest()
    window.close(); app.processEvents()
    report=dict(source=args.source,qt_platform=app.platformName(),python=platform.python_version(),numpy=np.__version__,
                files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*Path('sentio').glob('*.py'),Path(__file__)]},
                checks=checks,measurements=measurements,acknowledgements=acknowledgements,failure=failure,
                camera=final['capture'] if final else None,
                shutdown=dict(runtime_stopped=not runtime.is_alive(),capture_stopped=runtime.capture is None or not runtime.capture.is_alive()),
                limitations='Automated Qt widget actions; no physical scene protocol, unplug/replug or end-to-end optical latency measurement. No camera image saved.')
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(output=str(args.output),failure=failure,checks=checks,shutdown=report['shutdown'])),flush=True)
    return int(bool(failure))


if __name__=='__main__':
    raise SystemExit(main())
