"""Existing drilling import (spec 5.2).

Route A: desurveyed sample or interval-midpoint CSV, cleaned into support points.
Route B (milestone 8): collar, survey and optional interval tables desurveyed by
minimum curvature to interval midpoints.

Conventions: azimuth clockwise from north in degrees, dip negative downward
internally, Z positive upward.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from engine import holes, schema

_TRUE_WORDS = {"y", "yes", "true", "t", "1"}
_FALSE_WORDS = {"n", "no", "false", "f", "0"}
_SMALL_ANGLE = 1e-10


@dataclass
class DrillingMapping:
    """Route A column mapping. `domain` is stored only, never used for filtering."""

    hole_id: str
    x: str
    y: str
    z: str
    valid: str | None = None
    domain: str | None = None


@dataclass
class DrillingImport:
    """Result of either import route."""

    points: pd.DataFrame
    n_rows: int
    n_dropped: int
    dropped_reasons: dict[str, int] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)


def _empty_points() -> pd.DataFrame:
    return pd.DataFrame({"hole_id": pd.Series(dtype=str), "x": pd.Series(dtype="float64"),
                         "y": pd.Series(dtype="float64"), "z": pd.Series(dtype="float64")})


def _bump(reasons: dict[str, int], key: str, n: int) -> None:
    if n > 0:
        reasons[key] = reasons.get(key, 0) + int(n)


def _parse_valid(value) -> bool | None:
    """True / False for a recognised validity value, None if unrecognised."""
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    text = str(value).strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return None


def _numeric(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce").astype("float64")
    return out.where(np.isfinite(out))


def _clean_ids(series: pd.Series) -> pd.Series:
    """Stripped string ids; null ids become NaN (object) so callers can drop them."""
    ids = series.astype("string").str.strip()
    ids = ids.where(ids.notna() & (ids != ""))
    return ids.astype(object).where(ids.notna(), np.nan)


# ---------------------------------------------------------------- Route A

def prepare_route_a(raw: pd.DataFrame, mapping: DrillingMapping) -> DrillingImport:
    """Clean a desurveyed point table into SUPPORT_COLUMNS (plus `domain` if mapped)."""
    n_rows = len(raw)
    reasons: dict[str, int] = {}
    absent = [c for c in (mapping.hole_id, mapping.x, mapping.y, mapping.z, mapping.valid,
                          mapping.domain) if c is not None and c not in raw.columns]
    if absent:
        raise ValueError("The drilling file has no column named " + ", ".join(absent)
                         + ". Re-map its columns on the Project page.")
    df = pd.DataFrame({
        "hole_id": _clean_ids(raw[mapping.hole_id]),
        "x": _numeric(raw[mapping.x]),
        "y": _numeric(raw[mapping.y]),
        "z": _numeric(raw[mapping.z]),
    })
    if mapping.domain is not None:
        df["domain"] = raw[mapping.domain].astype("string").str.strip().astype(object)
    keep = pd.Series(True, index=df.index)
    assumptions: list[str] = []

    if mapping.valid is not None:
        parsed = raw[mapping.valid].map(_parse_valid)
        unrecognised = parsed.isna()
        invalid = (parsed == False) & ~unrecognised
        _bump(reasons, "validity flag is false", int(invalid.sum()))
        _bump(reasons, "unrecognised validity value", int(unrecognised.sum()))
        keep &= ~(invalid | unrecognised)
    else:
        assumptions.append("No validity column was mapped, so every drilling row counts.")

    missing_id = df["hole_id"].isna() & keep
    _bump(reasons, "missing hole id", int(missing_id.sum()))
    keep &= ~missing_id
    bad_xyz = df[["x", "y", "z"]].isna().any(axis=1) & keep
    _bump(reasons, "missing or non-numeric coordinates", int(bad_xyz.sum()))
    keep &= ~bad_xyz

    cols = list(schema.SUPPORT_COLUMNS) + (["domain"] if mapping.domain is not None else [])
    points = df.loc[keep, cols].reset_index(drop=True)
    points["hole_id"] = points["hole_id"].astype(str)
    return DrillingImport(points=points, n_rows=n_rows, n_dropped=sum(reasons.values()),
                          dropped_reasons=reasons, assumptions=assumptions)


# ---------------------------------------------------------------- Route B

def _slerp(t1: np.ndarray, t2: np.ndarray, beta: np.ndarray, f: np.ndarray) -> np.ndarray:
    """Tangent at fraction f along the arc t1 -> t2 (rows are vectors)."""
    small = beta < _SMALL_ANGLE
    sb = np.where(small, 1.0, np.sin(beta))
    w1 = np.where(small, 1.0 - f, np.sin((1.0 - f) * beta) / sb)
    w2 = np.where(small, f, np.sin(f * beta) / sb)
    return w1[:, None] * t1 + w2[:, None] * t2


def _mc_offset(t1: np.ndarray, t2: np.ndarray, length: np.ndarray) -> np.ndarray:
    """Minimum-curvature displacement over `length` between unit tangents t1, t2."""
    cos_b = np.clip(np.sum(t1 * t2, axis=1), -1.0, 1.0)
    beta = np.arccos(cos_b)
    small = beta < _SMALL_ANGLE
    safe = np.where(small, 1.0, beta)
    rf = np.where(small, 1.0, 2.0 / safe * np.tan(safe / 2.0))
    return (length * rf / 2.0)[:, None] * (t1 + t2)


def _desurvey_hole(collar: np.ndarray, st_depth: np.ndarray, st_az: np.ndarray,
                   st_dip: np.ndarray, depths: np.ndarray) -> np.ndarray:
    """Positions (n, 3) at `depths` for one hole by minimum curvature."""
    order = np.argsort(st_depth, kind="stable")
    sd, saz, sdip = st_depth[order], st_az[order], st_dip[order]
    _, first = np.unique(sd, return_index=True)  # one station per depth
    sd, saz, sdip = sd[first], saz[first], sdip[first]
    if sd[0] > 0:  # imply a station at the collar from the first orientation
        sd = np.insert(sd, 0, 0.0)
        saz = np.insert(saz, 0, saz[0])
        sdip = np.insert(sdip, 0, sdip[0])
    tang = holes.direction(saz, sdip)
    if len(sd) > 1:
        seg_len = np.diff(sd)
        seg_off = _mc_offset(tang[:-1], tang[1:], seg_len)
        station_pos = np.vstack([np.zeros(3), np.cumsum(seg_off, axis=0)])
    else:
        station_pos = np.zeros((1, 3))
    out = np.empty((len(depths), 3))
    # Segment index: station at or above each depth; clamp to the last station.
    idx = np.clip(np.searchsorted(sd, depths, side="right") - 1, 0, len(sd) - 1)
    last = idx == len(sd) - 1
    base = station_pos[idx]
    delta = depths - sd[idx]
    if last.any():  # straight beyond the last station
        out[last] = base[last] + delta[last, None] * tang[idx[last]]
    mid = ~last
    if mid.any():
        i = idx[mid]
        f = delta[mid] / (sd[i + 1] - sd[i])
        t1, t2 = tang[i], tang[i + 1]
        beta = np.arccos(np.clip(np.sum(t1 * t2, axis=1), -1.0, 1.0))
        out[mid] = base[mid] + _mc_offset(t1, _slerp(t1, t2, beta, f), delta[mid])
    return collar[None, :] + out


def desurvey_route_b(collars: pd.DataFrame, surveys: pd.DataFrame,
                     intervals: pd.DataFrame | None = None, *,
                     interval: float = holes.DEFAULT_SUPPORT_INTERVAL,
                     positive_down: bool = False) -> DrillingImport:
    """Desurvey collars + surveys to interval midpoints or generated trace points."""
    reasons: dict[str, int] = {}
    assumptions: list[str] = []
    n_rows = len(collars) + len(surveys) + (len(intervals) if intervals is not None else 0)

    # Collars
    c = pd.DataFrame({"hole_id": _clean_ids(collars["hole_id"]),
                      "x": _numeric(collars["x"]), "y": _numeric(collars["y"]),
                      "z": _numeric(collars["z"])})
    c["max_depth"] = _numeric(collars["max_depth"]) if "max_depth" in collars.columns else np.nan
    bad = c["hole_id"].isna() | c[["x", "y", "z"]].isna().any(axis=1)
    _bump(reasons, "collar with missing id or non-numeric coordinates", int(bad.sum()))
    c = c[~bad]
    dup = c["hole_id"].duplicated()
    _bump(reasons, "duplicate collar hole id", int(dup.sum()))
    c = c[~dup].set_index("hole_id")

    # Surveys
    s = pd.DataFrame({"hole_id": _clean_ids(surveys["hole_id"]),
                      "depth": _numeric(surveys["depth"]),
                      "azimuth": _numeric(surveys["azimuth"]),
                      "dip": _numeric(surveys["dip"])})
    bad = s.isna().any(axis=1)
    _bump(reasons, "survey row with missing or non-numeric values", int(bad.sum()))
    s = s[~bad]
    orphan = ~s["hole_id"].isin(c.index)
    _bump(reasons, "survey hole has no collar", int(orphan.sum()))
    s = s[~orphan].copy()
    s["dip"] = holes.to_internal_dip(s["dip"].to_numpy(), positive_down)
    surv_groups = {k: g for k, g in s.groupby("hole_id", sort=False)}

    no_survey = [h for h in c.index if h not in surv_groups]
    if no_survey:
        assumptions.append(
            f"{len(no_survey)} collar(s) have no survey and were treated as vertical "
            f"(dip -90): {', '.join(map(str, no_survey[:5]))}"
            + (", ..." if len(no_survey) > 5 else "") + ".")

    # Depths to evaluate
    if intervals is not None:
        iv = pd.DataFrame({"hole_id": _clean_ids(intervals["hole_id"]),
                           "from": _numeric(intervals["from"]), "to": _numeric(intervals["to"])})
        bad = iv.isna().any(axis=1) | (iv["to"] <= iv["from"]) | (iv["from"] < 0)
        _bump(reasons, "interval with missing values or invalid from/to", int(bad.sum()))
        iv = iv[~bad]
        orphan = ~iv["hole_id"].isin(c.index)
        _bump(reasons, "interval hole has no collar", int(orphan.sum()))
        iv = iv[~orphan]
        iv = iv.assign(depth=(iv["from"] + iv["to"]) / 2.0)
        depth_groups = {k: g["depth"].to_numpy() for k, g in iv.groupby("hole_id", sort=False)}
        assumptions.append("Existing drilling points are interval midpoints desurveyed by "
                           "minimum curvature.")
    else:
        depth_groups = {}
        no_depth = 0
        for h in c.index:
            md = c.at[h, "max_depth"]
            if not np.isfinite(md):
                md = surv_groups[h]["depth"].max() if h in surv_groups else np.nan
            if not np.isfinite(md) or md <= 0:
                no_depth += 1
                continue
            depth_groups[h] = holes.support_depths(float(md), interval)
        _bump(reasons, "collar with no usable depth (no max_depth or survey)", no_depth)
        assumptions.append(
            f"No intervals were given, so trace points were generated along each hole at the "
            f"{interval:g} m support interval (down to max_depth, or the deepest survey).")

    frames = []
    for h, depths in depth_groups.items():
        collar = c.loc[h, ["x", "y", "z"]].to_numpy(dtype=float)
        if h in surv_groups:
            g = surv_groups[h]
            pos = _desurvey_hole(collar, g["depth"].to_numpy(), g["azimuth"].to_numpy(),
                                 g["dip"].to_numpy(), depths)
        else:
            pos = _desurvey_hole(collar, np.array([0.0]), np.array([0.0]), np.array([-90.0]),
                                 depths)
        frames.append(pd.DataFrame({"hole_id": str(h), "x": pos[:, 0], "y": pos[:, 1],
                                    "z": pos[:, 2]}))
    points = pd.concat(frames, ignore_index=True) if frames else _empty_points()
    return DrillingImport(points=points, n_rows=n_rows, n_dropped=sum(reasons.values()),
                          dropped_reasons=reasons, assumptions=assumptions)
