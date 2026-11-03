"""Bounded grid sizes; physical domain remains the unit square."""

DEFAULT_GRID = 256
GRID_SIZES = (256, 512, 1024)
MAX_GRID = max(GRID_SIZES)
# Two float64 state arrays plus bounded JSON metadata / NPY headers.
MAX_CHECKPOINT_BYTES = 2*MAX_GRID**2*8 + 32_768


def application_grid(n):
    if type(n) is not int or n not in GRID_SIZES:
        raise ValueError(f"application grid must be one of {GRID_SIZES}")
    return n
