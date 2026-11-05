"""Schema 3 container: validated legacy wave state plus all event-detector state.

No changes to schemas 1/2. Nested arrays are bounded before allocation; the
existing wave validators remain authoritative. No pickle or source data.
"""

import copy
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile

import numpy as np

from .grid import MAX_GRID, MAX_CHECKPOINT_BYTES
from .reinforcement import Reinforcement, ReinforcementParameters


MEMBERS = {"schema.json", "wave.npz", "reinforcement.npz"}
MEMORY_BYTES = MAX_GRID**2 * 34 + 32768
CONTAINER_BYTES = MAX_CHECKPOINT_BYTES + MEMORY_BYTES + 65536
IDENTITY = "event-counted-local-damping-v1"


def save(field, path):
    r = field.reinforcement
    r.validate(field.n)
    path = Path(path)
    # A shallow wave copy routes to the unchanged legacy writer without ever
    # detaching the live detector. Temporary files contain simulation state only.
    wave = copy.copy(field)
    wave.reinforcement = None
    metadata = json.dumps(dict(schema=3, model=IDENTITY, enabled=r.enabled,
                               parameters=asdict(r.parameters)), allow_nan=False)
    temporary = None
    try:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)/"wave.npz"
            wave.save(base)
            memory = io.BytesIO()
            np.savez_compressed(memory, **{k:getattr(r, k) for k in r.array_dtypes})
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as stream:
                temporary = stream.name
                with zipfile.ZipFile(stream, "w") as archive:
                    archive.writestr("schema.json", metadata)
                    archive.write(base, "wave.npz")
                    archive.writestr("reinforcement.npz", memory.getvalue())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load(path):
    from .models import load_field

    with zipfile.ZipFile(path) as archive:
        if (len(archive.infolist()) != 3 or set(archive.namelist()) != MEMBERS
                or sum(i.file_size for i in archive.infolist()) > CONTAINER_BYTES
                or archive.getinfo("schema.json").file_size > 10000
                or archive.getinfo("wave.npz").file_size > MAX_CHECKPOINT_BYTES+32768
                or archive.getinfo("reinforcement.npz").file_size > MEMORY_BYTES+32768):
            raise ValueError("invalid or oversized reinforcement checkpoint")
        meta = json.loads(archive.read("schema.json"))
        if (not isinstance(meta, dict) or meta.get("schema") != 3 or meta.get("model") != IDENTITY
                or type(meta.get("enabled")) is not bool
                or not isinstance(meta.get("parameters"), dict)
                or set(meta["parameters"]) != set(asdict(ReinforcementParameters()))):
            raise ValueError("invalid reinforcement checkpoint metadata")
        parameters = ReinforcementParameters(**meta["parameters"])
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)/"wave.npz"
            base.write_bytes(archive.read("wave.npz"))
            field = load_field(base, allow_reinforcement=False)
        memory = io.BytesIO(archive.read("reinforcement.npz"))
    r = Reinforcement(field.n, parameters, meta["enabled"])
    with zipfile.ZipFile(memory) as archive:
        if (len(archive.infolist()) != len(r.array_dtypes)
                or set(archive.namelist()) != {k+".npy" for k in r.array_dtypes}
                or sum(i.file_size for i in archive.infolist()) > MEMORY_BYTES):
            raise ValueError("invalid reinforcement array members")
        for name, dtype in r.array_dtypes.items():
            with archive.open(name+".npy") as stream:
                if np.lib.format.read_magic(stream) != (1, 0):
                    raise ValueError("unsupported reinforcement array format")
                shape, _, actual = np.lib.format.read_array_header_1_0(stream)
                if shape != (field.n, field.n) or actual != dtype:
                    raise ValueError("invalid reinforcement array header")
    memory.seek(0)
    with np.load(memory, allow_pickle=False) as data:
        for name in r.array_dtypes:
            setattr(r, name, data[name].copy())
    r.validate(field.n)
    field.reinforcement = r
    return field
