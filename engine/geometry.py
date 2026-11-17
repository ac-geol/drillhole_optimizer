"""Nearest-three-distinct-holes metric, geometry classes and distance queries (spec 6).

Every block gets one number, the mean distance to its nearest three distinct
holes, and one geometry class from that number. Distances are isotropic
Euclidean from the block centroid to the nearest support point of each hole.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from engine import TOLERANCE_M
from engine.schema import ClassRank

_K0 = 32
_CHUNK = 100_000


@dataclass(frozen=True)
class Thresholds:
    """Geometry class thresholds in metres (spec 6.3). Must be strictly increasing."""

    measured: float = 25.0
    indicated: float = 50.0
    inferred: float = 100.0

    def __post_init__(self):
        if not (0 < self.measured < self.indicated < self.inferred):
            raise ValueError("Thresholds must be positive and strictly increasing: "
                             "Measured < Indicated < Inferred.")

    def for_rank(self, rank: ClassRank | int) -> float:
        rank = ClassRank(rank)
        if rank == ClassRank.MEASURED:
            return self.measured
        if rank == ClassRank.INDICATED:
            return self.indicated
        if rank == ClassRank.INFERRED:
            return self.inferred
        raise ValueError("Rank NONE has no threshold.")

    @property
    def search_radius(self) -> float:
        """R = 3 x largest threshold: exact for classification (spec 6.2)."""
        return 3.0 * self.inferred


def classify(metric, thresholds: Thresholds) -> np.ndarray:
    """Geometry class rank per metric. Highest class satisfied wins; NaN -> outside."""
    m = np.asarray(metric, dtype=float)
    rank = np.zeros(m.shape, dtype=np.int8)
    with np.errstate(invalid="ignore"):
        rank[m <= thresholds.inferred + TOLERANCE_M] = ClassRank.INFERRED
        rank[m <= thresholds.indicated + TOLERANCE_M] = ClassRank.INDICATED
        rank[m <= thresholds.measured + TOLERANCE_M] = ClassRank.MEASURED
    return rank


def metric_from_three(dist3: np.ndarray) -> np.ndarray:
    """Mean of the three distances; NaN when fewer than three holes (inf entries)."""
    with np.errstate(invalid="ignore"):
        metric = dist3.mean(axis=1)
    metric[~np.isfinite(metric)] = np.nan
    return metric


def _query_radius(radius: float) -> float:
    # cKDTree's upper bound is strict; widen by the comparison tolerance.
    return radius * (1 + 1e-12) + TOLERANCE_M


@dataclass
class NearestThree:
    """Per-block nearest three distinct holes.

    dist: (n, 3) ascending distances, inf where fewer than three holes in range.
    hole: (n, 3) hole codes into ``hole_ids``, -1 where missing.
    """

    dist: np.ndarray
    hole: np.ndarray
    hole_ids: np.ndarray
    thresholds: Thresholds

    @property
    def metric(self) -> np.ndarray:
        return metric_from_three(self.dist)

    @property
    def rank(self) -> np.ndarray:
        return classify(self.metric, self.thresholds)


def _walk_distinct(d: np.ndarray, idx: np.ndarray, codes: np.ndarray, m: int):
    """First three distinct hole codes per row, walking neighbours in distance order."""
    n, k = d.shape
    out_d = np.full((n, 3), np.inf)
    out_h = np.full((n, 3), -1, dtype=np.int64)
    count = np.zeros(n, dtype=np.int64)
    in_range = idx < m
    hole = np.where(in_range, codes[np.minimum(idx, m - 1)], -1)
    for j in range(k):
        hj = hole[:, j]
        new = ((hj >= 0) & (count < 3) & (hj != out_h[:, 0])
               & (hj != out_h[:, 1]) & (hj != out_h[:, 2]))
        if new.any():
            rows = np.flatnonzero(new)
            out_d[rows, count[rows]] = d[rows, j]
            out_h[rows, count[rows]] = hj[rows]
            count[rows] += 1
        if np.all((count >= 3) | (hj < 0)):
            break
    return out_d, out_h, count


def nearest_three(block_xyz: np.ndarray, support: pd.DataFrame, thresholds: Thresholds,
                  radius: float | None = None) -> NearestThree:
    """Baseline computation (spec 6.4) against existing support points.

    Query the k nearest points within R (k starts at 32), keep the first three
    distinct holes, and double k for blocks that found fewer than three while
    more points were available.
    """
    block_xyz = np.asarray(block_xyz, dtype=float)
    n = len(block_xyz)
    radius = thresholds.search_radius if radius is None else radius
    hole_ids, codes = np.unique(support["hole_id"].astype(str).to_numpy(), return_inverse=True)
    out_d = np.full((n, 3), np.inf)
    out_h = np.full((n, 3), -1, dtype=np.int64)
    m = len(support)
    if m == 0 or n == 0:
        return NearestThree(out_d, out_h, hole_ids, thresholds)

    tree = cKDTree(support[["x", "y", "z"]].to_numpy(dtype=float))
    r = _query_radius(radius)
    for start in range(0, n, _CHUNK):
        todo = np.arange(start, min(start + _CHUNK, n))
        k = _K0
        while todo.size:
            kk = min(k, m)
            d, idx = tree.query(block_xyz[todo], k=kk, distance_upper_bound=r)
            if kk == 1:
                d, idx = d[:, None], idx[:, None]
            fd, fh, count = _walk_distinct(d, idx, codes, m)
            out_d[todo], out_h[todo] = fd, fh
            more = (count < 3) & np.isfinite(d[:, -1]) & (kk < m)
            todo, k = todo[more], k * 2
    return NearestThree(out_d, out_h, hole_ids, thresholds)


def hole_block_distances(block_tree: cKDTree, block_xyz: np.ndarray, hole_points: np.ndarray,
                         radius: float) -> tuple[np.ndarray, np.ndarray]:
    """Blocks within ``radius`` of any support point of one hole, and the minimum
    distance to that hole for each. Returns (row indices ascending, distances)."""
    hole_points = np.asarray(hole_points, dtype=float)
    if len(hole_points) == 0:
        return np.empty(0, dtype=np.int64), np.empty(0)
    centre = (hole_points[0] + hole_points[-1]) / 2.0
    reach = np.sqrt(((hole_points - centre) ** 2).sum(axis=1)).max()
    r = _query_radius(radius)
    rows = np.asarray(block_tree.query_ball_point(centre, r + reach), dtype=np.int64)
    if rows.size == 0:
        return rows, np.empty(0)
    rows.sort()
    d, _ = cKDTree(hole_points).query(block_xyz[rows], k=1, distance_upper_bound=r)
    keep = np.isfinite(d)
    return rows[keep], d[keep]


def insert_distances(dist3: np.ndarray, rows: np.ndarray, dist: np.ndarray) -> None:
    """In place: merge one new hole's distances into the per-block nearest three."""
    if rows.size == 0:
        return
    merged = np.concatenate([dist3[rows], dist[:, None]], axis=1)
    merged.sort(axis=1)
    dist3[rows] = merged[:, :3]
