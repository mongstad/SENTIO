"""Reduce a scalar-only session log to reviewable evidence, omitting device IDs."""

import argparse
import json
from pathlib import Path
import statistics


def summarize(path):
    lines = Path(path).read_text().splitlines()
    rows = []
    for i, line in enumerate(lines):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if i != len(lines)-1:
                raise
    start = next(r for r in rows if r["event"] == "session_start")
    diagnostics = [r for r in rows if r["event"] == "diagnostics"]
    warmed = [r for r in diagnostics if r["monotonic"]-start["monotonic"] >= 5]
    report = dict(schema=1, started_utc=start["utc"], source=start["source"],
                  python=start["python"], numpy=start["numpy"], platform=start["platform"],
                  initial_parameters=start["parameters"],
                  observed_seconds=diagnostics[-1]["monotonic"]-start["monotonic"],
                  diagnostics_count=len(diagnostics),
                  all_finite=all(r["diagnostics"]["finite"] for r in diagnostics),
                  peak=max(r["diagnostics"]["peak"] for r in diagnostics),
                  final_diagnostics=diagnostics[-1]["diagnostics"],
                  skipped_wall_seconds=diagnostics[-1]["skipped_wall_seconds"],
                  session_closed=any(r["event"] == "session_end" for r in rows),
                  errors=[r for r in rows if r["event"] in ("runtime_error", "camera_error", "numerical_fault")],
                  control_events=[{k:v for k,v in r.items() if k in ("name", "value", "step", "simulation_time", "utc")}
                                  for r in rows if r["event"] == "control"])
    for name, values in (("capture_fps", [r["capture"]["fps"] for r in warmed]),
                         ("simulation_steps_per_second", [r["steps_per_second"] for r in warmed]),
                         ("simulation_seconds_per_second", [r["simulation_seconds_per_second"] for r in warmed])):
        if values:
            report[name] = dict(min=min(values), median=statistics.median(values), max=max(values))
    opened = next((r for r in rows if r["event"] == "camera_open"), None)
    if opened:
        report["camera"] = dict(card=opened["identity"]["card"], mode=opened["mode"],
                                controls_at_open=opened["controls"], buffers=opened["buffers"])
        latest = diagnostics[-1]["capture"]
        report["capture_counters"] = {k:latest[k] for k in ("frames", "driver_drops", "drained_discards", "bad_frames", "mailbox_discards", "timestamp_kind") if k in latest}
        observed = [r for r in rows if r["event"] == "camera_controls_observed"]
        if observed:
            report["camera"]["last_effective_controls"] = observed[-1]["controls"]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("log")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = summarize(args.log)
    Path(args.output).write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(f"{report['observed_seconds']:.1f}s observed; finite={report['all_finite']}; closed={report['session_closed']}")
