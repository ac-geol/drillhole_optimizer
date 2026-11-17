"""Labelled synthetic dataset builders for the acceptance tests (spec section 13).

All data built here is SYNTHETIC. Builders return tables already in the
engine's internal layouts (engine.schema), bypassing CSV import, so tests of
the geometry, evaluation and optimiser do not depend on the import code.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.schema import ClassRank


def blocks(xyz, uploaded_class=ClassRank.INDICATED, tonnes=1000.0, metal=1.0,
           size=5.0, prefix="SYN_B") -> pd.DataFrame:
    """Prepared block table (as engine.blockmodel would output) at the given centroids."""
    xyz = np.atleast_2d(np.asarray(xyz, dtype=float))
    n = len(xyz)
    out = pd.DataFrame({
        "block_id": [f"{prefix}{i}" for i in range(n)],
        "x": xyz[:, 0], "y": xyz[:, 1], "z": xyz[:, 2],
        "dx": size, "dy": size, "dz": size,
        "uploaded_class": np.broadcast_to(np.asarray(uploaded_class, dtype=np.int8), n).copy(),
        "volume": size ** 3,
        "tonnes": np.broadcast_to(np.asarray(tonnes, dtype=float), n).copy(),
        "metal": np.broadcast_to(np.asarray(metal, dtype=float), n).copy(),
        "valid": True,
    })
    out["density"] = out["tonnes"] / out["volume"]
    out["grade"] = 0.0
    out["class_raw"] = out["uploaded_class"].astype(str)
    return out


def support(hole_id: str, xyz) -> pd.DataFrame:
    """Existing drilling support points for one hole."""
    xyz = np.atleast_2d(np.asarray(xyz, dtype=float))
    return pd.DataFrame({"hole_id": hole_id, "x": xyz[:, 0], "y": xyz[:, 1], "z": xyz[:, 2]})


def vertical_support(hole_id: str, x: float, y: float, z_top: float, z_bottom: float,
                     step: float = 1.0) -> pd.DataFrame:
    z = np.arange(z_top, z_bottom - 1e-9, -step)
    return support(hole_id, np.column_stack([np.full_like(z, x), np.full_like(z, y), z]))


def combine(*frames: pd.DataFrame) -> pd.DataFrame:
    return pd.concat(frames, ignore_index=True)


def planned_holes(rows: list[dict]) -> pd.DataFrame:
    """Planned holes table (schema.HOLE_COLUMNS). Each dict needs hole_id, site_id,
    x, y, z, azimuth, dip, length; locked defaults to False."""
    out = pd.DataFrame(rows)
    if "locked" not in out:
        out["locked"] = False
    return out


def vertical_hole(hole_id: str, site_id: str, x: float, y: float, z_collar: float,
                  length: float) -> dict:
    return {"hole_id": hole_id, "site_id": site_id, "x": x, "y": y, "z": z_collar,
            "azimuth": 0.0, "dip": -90.0, "length": length, "locked": False}
