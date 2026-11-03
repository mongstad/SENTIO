"""Explicit luminance processing and deterministic experimental controls."""

import numpy as np

from .grid import DEFAULT_GRID, MAX_GRID


def extract_y(raw, width, height, stride):
    """YUYV stores Y0 U Y1 V. Honor row padding; return an owned Y array."""
    if width % 2 or stride < width * 2 or len(raw) < stride * height:
        raise ValueError("short or invalid YUYV frame")
    rows = np.frombuffer(raw, dtype=np.uint8, count=stride * height).reshape(height, stride)
    return rows[:, :2 * width:2].copy()


def area_axis(a, size, axis):
    """Exact area average of piecewise-constant pixels, without dense matrices."""
    a = np.moveaxis(a, axis, 0)
    edges = np.linspace(0, a.shape[0], size + 1)
    index = np.minimum(edges.astype(int), a.shape[0] - 1)
    prefix = np.concatenate((np.zeros_like(a[:1]), np.cumsum(a, axis=0)), axis=0)
    integral = prefix[index] + (edges - index).reshape((-1,) + (1,) * (a.ndim - 1)) * a[index]
    return np.moveaxis(np.diff(integral, axis=0) / (a.shape[0] / size), 0, axis)


def luminance_source(y, n=DEFAULT_GRID):
    """Full 640x480 frame mapped to square; fixed code-value centering.

    Y/127.5 - 1 uses all 8-bit code values, without auto contrast, per-frame
    mean removal, gamma inversion, or claiming calibrated radiance.
    """
    if y.ndim != 2 or y.dtype != np.uint8:
        raise ValueError("luminance must be a 2D uint8 array")
    if type(n) is not int or not 1 <= n <= MAX_GRID:
        raise ValueError(f"resampling size must be an integer in [1, {MAX_GRID}]")
    return area_axis(area_axis(y.astype(np.float64) / 127.5 - 1, n, 0), n, 1)


SYNTHETIC_MODES = ("zero", "stationary", "moving", "viewpoint", "loss", "recurring")


def synthetic_source(n, t, mode):
    if mode not in SYNTHETIC_MODES:
        raise ValueError(f"unknown synthetic mode: {mode}")
    axis = np.linspace(0, 1, n)
    x, y = np.meshgrid(axis, axis)
    if mode == "zero" or (mode == "loss" and t >= 2):
        return np.zeros((n, n))
    center = 0.5 + (0.22 * np.sin(2 * np.pi * t / 3) if mode == "moving" else 0)
    if mode == "viewpoint":
        angle = 0.5 * t
        x, y = (np.cos(angle) * (x - .5) - np.sin(angle) * (y - .5) + .5,
                np.sin(angle) * (x - .5) + np.cos(angle) * (y - .5) + .5)
    source = np.exp(-((x - center)**2 + (y - .4)**2) / .003)
    source -= np.exp(-((x - .35)**2 + (y - .65)**2) / .003)
    if mode == "recurring" and t % 3 >= 1:
        source.fill(0)
    return source
