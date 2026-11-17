"""Candidate grid generation, stable IDs, exclusion groups, angular separation and size estimate.

Spec 7.1. Candidates are every site x azimuth x dip x length combination. Candidates
sharing a trace (site, azimuth, dip) form an exclusion group; at most one can be selected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine import schema
from engine.holes import direction

_EPS = 1e-9
MAX_CANDIDATES_WARN = 15_000
MAX_BYTES_WARN = 2 * 1024**3
# Working memory per matrix entry during a run, not just the stored table: the float32
# value and int32 row index on disk (8 bytes) plus the search's float64 and int64 working
# copies, column index, active-entry index and row-ordered copy (8 bytes each).
BYTES_PER_ENTRY = 48
BYTES_PER_CANDIDATE = 8


@dataclass(frozen=True)
class Range:
    """Inclusive (min, max, step) range."""

    min: float
    max: float
    step: float


@dataclass(frozen=True)
class CandidateSettings:
    azimuth: Range
    dip: Range
    length: Range


@dataclass(frozen=True)
class SizeEstimate:
    n_candidates: int
    est_entries: int
    est_bytes: int
    warnings: list[str]


def range_values(r: Range) -> np.ndarray:
    """Inclusive values min, min+step, ... <= max (float tolerant), rounded to 6 dp."""
    if r.step <= 0:
        raise ValueError("range step must be positive")
    if r.min > r.max:
        raise ValueError("range min must not exceed max")
    if r.min == r.max:
        return np.array([round(float(r.min), 6)])
    n = math.floor((r.max - r.min) / r.step + 1e-9) + 1
    return np.round(r.min + np.arange(n) * r.step, 6)


def _norm_az(az: float, dip: float) -> float:
    if abs(float(dip) + 90.0) <= _EPS:
        return 0.0
    a = round(float(az) % 360.0, 6) % 360.0
    return 0.0 if a == 360.0 else a  # also maps -0.0 to 0.0


def trace_group_id(site_id, azimuth, dip) -> str:
    """Exclusion group id: site, azimuth (mod 360; 0 at dip -90) and dip."""
    return f"{site_id}_A{_norm_az(azimuth, dip):g}_D{float(dip):g}"


def candidate_id(site_id, azimuth, dip, length) -> str:
    return f"{trace_group_id(site_id, azimuth, dip)}_L{float(length):g}"


def _azimuths_for_dip(azimuths: np.ndarray, dip: float) -> np.ndarray:
    if abs(dip + 90.0) <= _EPS:
        return np.array([0.0])
    norm = np.array([_norm_az(a, dip) for a in azimuths])
    _, first = np.unique(norm, return_index=True)
    return norm[np.sort(first)]


def generate_candidates(sites: pd.DataFrame, settings: CandidateSettings) -> pd.DataFrame:
    """One row per site x azimuth x dip x length, deterministic order."""
    azs = range_values(settings.azimuth)
    dips = range_values(settings.dip)
    lens = range_values(settings.length)
    valid = {float(d): set(_azimuths_for_dip(azs, float(d)).tolist()) for d in dips}
    all_az = sorted(set().union(*valid.values()))
    rows = []
    # Order: site, azimuth, dip, length ascending.
    for s in sites.itertuples(index=False):
        for az in all_az:
            for dip in dips:
                if az not in valid[float(dip)]:
                    continue
                gid = trace_group_id(s.site_id, az, dip)
                for ln in lens:
                    rows.append((candidate_id(s.site_id, az, dip, ln), s.site_id, s.x, s.y,
                                 s.z, float(az), float(dip), float(ln), False, gid))
    cols = schema.HOLE_COLUMNS + schema.CANDIDATE_EXTRA
    return pd.DataFrame(rows, columns=cols)


def angle_between(az1, dip1, az2, dip2):
    """Angle in degrees between two hole directions."""
    dot = np.sum(direction(az1, dip1) * direction(az2, dip2), axis=-1)
    return np.degrees(np.arccos(np.clip(dot, -1.0, 1.0)))


def _group_ids(holes: pd.DataFrame) -> np.ndarray:
    if "group_id" in holes.columns:
        return holes["group_id"].to_numpy()
    return np.array([trace_group_id(s, a, d) for s, a, d in
                     zip(holes["site_id"], holes["azimuth"], holes["dip"])], dtype=object)


def _site_blocks(holes: pd.DataFrame):
    """Yield (row positions, angle matrix in degrees, same-group matrix) per site."""
    sites = holes["site_id"].to_numpy()
    groups = pd.factorize(_group_ids(holes))[0]
    az = holes["azimuth"].to_numpy(dtype=float)
    dip = holes["dip"].to_numpy(dtype=float)
    for pos in pd.Series(np.arange(len(holes))).groupby(sites, sort=False):
        idx = pos[1].to_numpy()
        dirs = direction(az[idx], dip[idx])
        ang = np.degrees(np.arccos(np.clip(dirs @ dirs.T, -1.0, 1.0)))
        g = groups[idx]
        yield idx, ang, g[:, None] == g[None, :]


def conflict_lists(holes: pd.DataFrame, min_angle: float) -> list[np.ndarray]:
    """Per row, sorted indices of rows that cannot be selected together with it."""
    out: list[np.ndarray] = [np.empty(0, dtype=np.int64) for _ in range(len(holes))]
    for idx, ang, same in _site_blocks(holes):
        mask = same.copy()
        if min_angle > 0:
            mask |= ang < min_angle - _EPS
        np.fill_diagonal(mask, False)
        for k, i in enumerate(idx):
            out[i] = idx[np.flatnonzero(mask[k])]
    return out


def angular_conflict_pairs(holes: pd.DataFrame, min_angle: float) -> list[tuple[str, str]]:
    """Hole-id pairs at one site closer than min_angle degrees (sorted)."""
    if min_angle <= 0:
        return []
    ids = holes["hole_id"].to_numpy()
    pairs = []
    for idx, ang, _ in _site_blocks(holes):
        a, b = np.nonzero(np.triu(ang < min_angle - _EPS, k=1))
        pairs.extend(tuple(sorted((str(ids[idx[i]]), str(ids[idx[j]])))) for i, j in zip(a, b))
    return sorted(pairs)


def site_cap_violations(holes: pd.DataFrame, cap: int) -> dict[str, int]:
    counts = holes.groupby("site_id").size()
    return {str(k): int(v) for k, v in counts[counts > cap].items()}


def estimate_size(n_candidates: int, eligible_xyz: np.ndarray, settings: CandidateSettings,
                  search_radius: float) -> SizeEstimate:
    xyz = np.asarray(eligible_xyz, dtype=float).reshape(-1, 3)
    n = len(xyz)
    entries_per = 0.0
    if n > 0 and n_candidates > 0:
        extent = xyz.max(axis=0) - xyz.min(axis=0)
        volume = float(np.prod(extent))
        if volume > 0:
            density = n / volume
            mean_len = float(np.mean(range_values(settings.length)))
            r = float(search_radius)
            capsule = math.pi * r**2 * mean_len + 4.0 / 3.0 * math.pi * r**3
            entries_per = min(density * capsule, float(n))
        else:
            entries_per = float(n)  # degenerate box: assume every block is in reach
    est_entries = round(entries_per * n_candidates)
    est_bytes = est_entries * BYTES_PER_ENTRY + n_candidates * BYTES_PER_CANDIDATE
    warnings = []
    if n_candidates > MAX_CANDIDATES_WARN:
        warnings.append(f"{n_candidates:,} candidate holes is above {MAX_CANDIDATES_WARN:,}. "
                        "Use coarser azimuth, dip or length increments to reduce run time.")
    if est_bytes > MAX_BYTES_WARN:
        warnings.append(f"Estimated memory is about {est_bytes / 1024**3:.1f} GB, above 2 GB. "
                        "Use coarser increments or fewer sites to avoid running out of memory.")
    return SizeEstimate(int(n_candidates), est_entries, int(est_bytes), warnings)
