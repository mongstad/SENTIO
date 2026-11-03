"""Linux process memory diagnostics, including capture and GUI allocations."""

from pathlib import Path


def process_memory():
    values = dict(resident_mib=None, peak_resident_mib=None)
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                key, kib, _ = line.split()
                values["resident_mib" if key == "VmRSS:" else "peak_resident_mib"] = int(kib)/1024
    except (OSError, ValueError):
        pass  # Explicitly unavailable, never a fabricated zero measurement.
    return values
