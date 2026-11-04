"""Small application model registry and validated checkpoint dispatch."""

import json
import zipfile

import numpy as np

from .field import Field
from .sextic import MODEL as SEXTIC_ID, SexticField
from .grid import DEFAULT_GRID, MAX_CHECKPOINT_BYTES


MODEL_LABELS = {"linear": "Linear (default)", "sextic": "Soft sextic (experimental)"}
MODEL_IDS = {"linear": "linear-wave-verlet-sponge-v1", "sextic": SEXTIC_ID}


def create_field(model, n=DEFAULT_GRID):
    if model not in MODEL_LABELS:
        raise ValueError(f"unknown field model: {model}")
    return SexticField(n) if model == "sextic" else Field(n)


def model_name(field):
    return "sextic" if isinstance(field, SexticField) else "linear"


def load_field(path):
    # Inspect only a bounded scalar header before invoking the model's full
    # validator. Never infer a model from arrays or reinterpret their state.
    with zipfile.ZipFile(path) as archive:
        if (len(archive.infolist()) != 3
                or set(archive.namelist()) != {"u.npy", "v.npy", "metadata.npy"}
                or sum(i.file_size for i in archive.infolist()) > MAX_CHECKPOINT_BYTES):
            raise ValueError("invalid or oversized checkpoint")
        with archive.open("metadata.npy") as member:
            if np.lib.format.read_magic(member) != (1, 0):
                raise ValueError("unsupported checkpoint metadata format")
            shape, _, dtype = np.lib.format.read_array_header_1_0(member)
            if shape != () or dtype.kind != "U" or dtype.itemsize > 10000:
                raise ValueError("invalid checkpoint metadata header")
        with archive.open("metadata.npy") as member:
            meta = json.loads(str(np.lib.format.read_array(member, allow_pickle=False)))
    if not isinstance(meta, dict):
        raise ValueError("invalid checkpoint metadata")
    identity = (meta.get("schema"), meta.get("model"))
    if identity == (1, MODEL_IDS["linear"]):
        return Field.load(path)
    if identity == (2, MODEL_IDS["sextic"]):
        return SexticField.load(path)
    raise ValueError("unsupported checkpoint model/schema")
