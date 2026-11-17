"""Straight-hole geometry and support points (spec 6.1).

Conventions: azimuth clockwise from north in degrees, dip negative downward,
Z positive upward. The same functions serve manual and generated holes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_SUPPORT_INTERVAL = 2.0
_EPS = 1e-9


def direction(azimuth_deg, dip_deg) -> np.ndarray:
    """Unit direction vector(s). Returns shape (..., 3)."""
    a = np.radians(np.asarray(azimuth_deg, dtype=float))
    d = np.radians(np.asarray(dip_deg, dtype=float))
    return np.stack([np.cos(d) * np.sin(a), np.cos(d) * np.cos(a), np.sin(d)], axis=-1)


def to_internal_dip(dip, positive_down: bool):
    """Convert imported dips to the internal negative-down convention (spec change 9)."""
    dip = np.asarray(dip, dtype=float)
    return -dip if positive_down else dip


def support_depths(length: float, interval: float = DEFAULT_SUPPORT_INTERVAL) -> np.ndarray:
    """Midpoint depths of consecutive intervals from the collar: s/2, 3s/2, ...

    A final short interval gets its own midpoint.
    """
    if interval <= 0:
        raise ValueError("support interval must be positive")
    if length <= _EPS:
        return np.empty(0)
    n_full = int(np.floor(length / interval + _EPS))
    depths = (np.arange(n_full) + 0.5) * interval
    remainder = length - n_full * interval
    if remainder > _EPS:
        depths = np.append(depths, n_full * interval + remainder / 2.0)
    return depths


def support_points(collar, azimuth: float, dip: float, length: float,
                   interval: float = DEFAULT_SUPPORT_INTERVAL) -> np.ndarray:
    """Support point coordinates for one straight hole, shape (n, 3)."""
    depths = support_depths(length, interval)
    return np.asarray(collar, dtype=float)[None, :] + depths[:, None] * direction(azimuth, dip)


def holes_support_points(holes: pd.DataFrame,
                         interval: float = DEFAULT_SUPPORT_INTERVAL) -> pd.DataFrame:
    """Support points for a HOLE_COLUMNS table, as a SUPPORT_COLUMNS table."""
    frames = []
    for row in holes.itertuples(index=False):
        pts = support_points((row.x, row.y, row.z), row.azimuth, row.dip, row.length, interval)
        frames.append(pd.DataFrame({"hole_id": row.hole_id, "x": pts[:, 0],
                                    "y": pts[:, 1], "z": pts[:, 2]}))
    if not frames:
        return pd.DataFrame({"hole_id": pd.Series(dtype=str), "x": pd.Series(dtype=float),
                             "y": pd.Series(dtype=float), "z": pd.Series(dtype=float)})
    return pd.concat(frames, ignore_index=True)
