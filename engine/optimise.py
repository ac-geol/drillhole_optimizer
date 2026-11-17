"""Heuristic search for a best-found plan (spec 6.6 and section 8).

Seeded greedy construction with single and pair moves, a prune pass, local
search and restarts. The search works on eligible blocks only, through a
sparse blocks x candidates distance matrix. Reported numbers always come from
engine.evaluate.evaluate_campaign(), never from the search's own bookkeeping.

Exactness of the matrix: an entry is kept only if it is within 3 x T(G) of the
block and below the block's baseline third distance. A hole further than
3 x T(G) cannot be in a trio with mean <= T(G), and a hole no closer than the
current third hole cannot change the nearest three, so conversion is exact.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.spatial import cKDTree

from engine import TOLERANCE_M
from engine.candidates import conflict_lists, trace_group_id
from engine.costs import CostModel, campaign_cost
from engine.evaluate import EvaluationContext
from engine.geometry import hole_block_distances, insert_distances
from engine.holes import support_points
from engine.schema import HOLE_COLUMNS

_EPS = 1e-9


@dataclass(frozen=True)
class OptimiserSettings:
    """Advanced settings (spec 8.4) plus the campaign rules from 7.1."""

    restarts: int = 5
    seed: int = 42
    pair_shortlist: int = 2000
    pair_neighbours: int = 6
    local_search_passes: int = 20
    time_limit_s: float = 600.0
    min_angle: float = 10.0
    site_cap: int = 10


# --------------------------------------------------------------------------- matrix

@dataclass
class CandidateMatrix:
    """Eligible blocks x useful candidates (spec 6.6). Build once, reuse across budgets."""

    candidates: pd.DataFrame      # useful candidates sorted by hole_id, index 0..n_c-1
    eligible_rows: np.ndarray     # positions of eligible blocks in ctx.blocks
    metal: np.ndarray             # metal per eligible block
    base3: np.ndarray             # baseline nearest-three distances per eligible block
    matrix: sparse.csc_matrix     # float32 distances, eligible x candidates
    target_threshold: float
    n_dropped: int                # candidates with no useful entries
    xyz: np.ndarray = field(repr=False)
    interval: float = 2.0


def _hole_distances(tree, xyz, row, interval, radius):
    pts = support_points((row.x, row.y, row.z), row.azimuth, row.dip, row.length, interval)
    return hole_block_distances(tree, xyz, pts, radius)


def build_candidate_matrix(ctx: EvaluationContext, candidates: pd.DataFrame) -> CandidateMatrix:
    t = ctx.thresholds.for_rank(ctx.target.target)
    radius = 3.0 * t
    elig = np.flatnonzero(ctx.eligible)
    xyz = ctx.xyz[elig]
    base3 = ctx.baseline.dist[elig]
    metal = ctx.blocks["metal"].to_numpy(dtype=float)[elig]
    cands = candidates.sort_values("hole_id", kind="stable").reset_index(drop=True)
    if "group_id" not in cands:
        cands["group_id"] = [trace_group_id(s, a, d) for s, a, d in
                             zip(cands["site_id"], cands["azimuth"], cands["dip"])]
    rows_l, data_l, keep = [], [], []
    if len(elig):
        tree = cKDTree(xyz)
        for i, row in enumerate(cands.itertuples(index=False)):
            rows, d = _hole_distances(tree, xyz, row, ctx.interval, radius)
            useful = d < base3[rows, 2]
            if useful.any():
                rows_l.append(rows[useful])
                data_l.append(d[useful].astype(np.float32))
                keep.append(i)
    indptr = np.concatenate([[0], np.cumsum([len(r) for r in rows_l])]).astype(np.int64)
    indices = np.concatenate(rows_l) if rows_l else np.empty(0, dtype=np.int64)
    data = np.concatenate(data_l) if data_l else np.empty(0, dtype=np.float32)
    mat = sparse.csc_matrix((data, indices, indptr), shape=(len(elig), len(keep)))
    useful_cands = cands.iloc[keep].reset_index(drop=True)
    return CandidateMatrix(useful_cands, elig, metal, base3, mat, t,
                           len(cands) - len(keep), xyz, ctx.interval)


# --------------------------------------------------------------------------- search state

def _progress(sum_capped, t):
    return 1.0 - np.maximum(0.0, sum_capped / 3.0 - t) / (2.0 * t)


class _Problem:
    """Fixed data for one budget: candidates, locked holes, costs and conflicts."""

    def __init__(self, cm: CandidateMatrix, locked: pd.DataFrame, budget: float,
                 cost_model: CostModel, settings: OptimiserSettings):
        self.cm, self.settings, self.cost_model = cm, settings, cost_model
        self.t = cm.target_threshold
        self.cap = 3.0 * self.t
        self.metal = cm.metal
        m = cm.matrix
        self.indptr, self.indices = m.indptr, m.indices.astype(np.int64)
        self.data = m.data.astype(np.float64)
        self.n_c = m.shape[1]
        self.col_of = np.repeat(np.arange(self.n_c), np.diff(self.indptr))
        cands = cm.candidates
        self.ids = cands["hole_id"].astype(str).to_numpy()
        self.length = cands["length"].to_numpy(dtype=float)

        locked = locked.reset_index(drop=True)
        self.locked = locked
        sites = pd.factorize(pd.concat([locked["site_id"], cands["site_id"]]).astype(str))[0]
        self.n_sites = int(sites.max()) + 1 if len(sites) else 0
        locked_sites, self.site = sites[:len(locked)], sites[len(locked):]
        self.base_site_count = np.bincount(locked_sites, minlength=self.n_sites)
        self.locked_cost = campaign_cost(locked, cost_model).total
        self.remaining0 = budget - self.locked_cost

        combined = pd.concat([locked[["hole_id", "site_id", "azimuth", "dip"]],
                              cands[["hole_id", "site_id", "azimuth", "dip"]]],
                             ignore_index=True)
        conf = conflict_lists(combined, settings.min_angle)
        nl = len(locked)
        self.base_blocked = np.zeros(self.n_c, dtype=np.int64)
        for i in range(nl):
            c = conf[i]
            np.add.at(self.base_blocked, c[c >= nl] - nl, 1)
        self.conflicts = [c[c >= nl] - nl for c in conf[nl:]]

        # baseline plus locked holes, on eligible blocks
        self.start3 = cm.base3.copy()
        if nl and len(cm.eligible_rows):
            tree = cKDTree(cm.xyz)
            for row in locked.itertuples(index=False):
                rows, d = _hole_distances(tree, cm.xyz, row, cm.interval, self.cap)
                insert_distances(self.start3, rows, d)

        # Active entries: those that can still change a block's nearest three, in
        # (row, distance) order. Adding holes only ever shrinks this set.
        by_row = np.lexsort((self.data, self.indices))
        r = self.indices[by_row]
        with np.errstate(invalid="ignore"):
            conv0 = self.start3.sum(axis=1) / 3.0 <= self.t + TOLERANCE_M
        self.start_act = by_row[~conv0[r] & (self.data[by_row] < self.start3[r, 2])]

    def col(self, c):
        s, e = self.indptr[c], self.indptr[c + 1]
        return self.indices[s:e], self.data[s:e]


class _State:
    def __init__(self, p: _Problem):
        self.p = p
        self.dist3 = p.start3.copy()
        self.conv = self._converted(self.dist3)
        self.metal = float(p.metal[self.conv].sum())
        self.selected: list[int] = []
        self.is_sel = np.zeros(p.n_c, dtype=bool)
        self.blocked = p.base_blocked.copy()
        self.site_count = p.base_site_count.copy()
        self.cost = 0.0  # added cost on top of locked holes
        self.act = p.start_act

    def _converted(self, d3):
        with np.errstate(invalid="ignore"):
            return d3.sum(axis=1) / 3.0 <= self.p.t + TOLERANCE_M

    def added_costs(self):
        p, cm = self.p, self.p.cost_model
        new_site = self.site_count[p.site] == 0
        return p.length * cm.cost_per_metre + cm.fixed_per_hole + np.where(
            new_site, cm.setup_per_site, 0.0)

    def feasible(self, added):
        p = self.p
        return (~self.is_sel & (self.blocked == 0)
                & (self.site_count[p.site] < p.settings.site_cap)
                & (added <= p.remaining0 - self.cost + _EPS))

    def gains(self):
        """Per-candidate (converted metal gain, progress gain) if added alone.

        Only active entries are scored: an entry for a converted block, or one no
        closer than the block's current third hole, adds nothing to either score.
        Returns (metal gain, progress gain, newly-converted flag per active entry).
        """
        p = self.p
        r = p.indices[self.act]
        keep = ~self.conv[r] & (p.data[self.act] < self.dist3[r, 2])
        self.act, r = self.act[keep], r[keep]
        d, col = p.data[self.act], p.col_of[self.act]
        d1, d2, d3 = self.dist3[r, 0], self.dist3[r, 1], self.dist3[r, 2]
        with np.errstate(invalid="ignore"):
            newly = (d1 + d2 + d) / 3.0 <= p.t + TOLERANCE_M
        w = p.metal[r]
        mg = np.bincount(col, weights=w * newly, minlength=p.n_c)
        cap = p.cap
        c12 = np.minimum(d1, cap) + np.minimum(d2, cap)
        dp = _progress(c12 + np.minimum(d, cap), p.t) - _progress(c12 + np.minimum(d3, cap), p.t)
        pg = np.bincount(col, weights=w * dp, minlength=p.n_c)
        return mg, pg, newly

    def add(self, c, added_cost):
        p = self.p
        rows, d = p.col(c)
        insert_distances(self.dist3, rows, d)
        new_conv = self._converted(self.dist3[rows])
        self.metal += float(p.metal[rows][new_conv & ~self.conv[rows]].sum())
        self.conv[rows] = new_conv
        self.selected.append(c)
        self.is_sel[c] = True
        np.add.at(self.blocked, p.conflicts[c], 1)
        self.site_count[p.site[c]] += 1
        self.cost += added_cost

    def joint_gain(self, cols):
        """(metal gain, progress gain) of adding several candidates together."""
        p = self.p
        parts = [p.col(c) for c in cols]
        rows = np.unique(np.concatenate([r for r, _ in parts]))
        sub = self.dist3[rows].copy()
        for r, d in parts:
            insert_distances(sub, np.searchsorted(rows, r), d)
        new_conv = self._converted(sub)
        old = self.dist3[rows]
        mg = float(p.metal[rows][new_conv & ~self.conv[rows]].sum())
        cap = p.cap
        pg = float((p.metal[rows] * (_progress(np.minimum(sub, cap).sum(axis=1), p.t)
                                     - _progress(np.minimum(old, cap).sum(axis=1), p.t))).sum())
        return mg, pg


def _rebuild(p: _Problem, cols) -> _State:
    st = _State(p)
    for c in cols:
        st.add(c, st.added_costs()[c])
    return st


# --------------------------------------------------------------------------- moves

def _pair_shortlist(st: _State, feasible, newly):
    """Pairs from blocks no single feasible candidate converts (spec 8.2)."""
    p = st.p
    k, limit = p.settings.pair_neighbours, p.settings.pair_shortlist
    if limit <= 0 or k < 2:
        return np.empty((0, 2), dtype=np.int64)
    # st.act is in (row, distance) order and aligned with `newly` from st.gains()
    r, c = p.indices[st.act], p.col_of[st.act]
    single = np.zeros(len(p.metal), dtype=bool)
    single[r[newly & feasible[c]]] = True
    keep = ~single[r] & feasible[c]
    r, c = r[keep], c[keep]
    if r.size == 0:
        return np.empty((0, 2), dtype=np.int64)
    start = np.flatnonzero(np.r_[True, r[1:] != r[:-1]])
    rank = np.arange(len(r)) - np.repeat(start, np.diff(np.r_[start, len(r)]))
    near = rank < k
    r, c = r[near], c[near]
    # positions of each row's j-th nearest entry
    row_start = np.flatnonzero(np.r_[True, r[1:] != r[:-1]])
    row_len = np.diff(np.r_[row_start, len(r)])
    keys, weights = [], []
    for i in range(k):
        for j in range(i + 1, k):
            has = row_len > j
            if not has.any():
                continue
            a, b = c[row_start[has] + i], c[row_start[has] + j]
            lo, hi = np.minimum(a, b), np.maximum(a, b)
            keys.append(lo * p.n_c + hi)
            weights.append(p.metal[r[row_start[has]]])
    if not keys:
        return np.empty((0, 2), dtype=np.int64)
    keys, weights = np.concatenate(keys), np.concatenate(weights)
    uniq, inv = np.unique(keys, return_inverse=True)
    w = np.bincount(inv, weights=weights)
    top = np.lexsort((uniq, -w))[:limit]
    pairs = np.column_stack([uniq[top] // p.n_c, uniq[top] % p.n_c])
    # drop pairs that conflict with each other or break the site cap together
    out = []
    for a, b in pairs:
        if b in p.conflicts[a]:
            continue
        if p.site[a] == p.site[b] and st.site_count[p.site[a]] + 2 > p.settings.site_cap:
            continue
        out.append((a, b))
    return np.array(out, dtype=np.int64).reshape(-1, 2)


def _best_moves(st: _State, *, per_cost: bool, use_secondary: bool, use_pairs: bool):
    """Ranked feasible moves: list of (cols tuple, added cost), best first."""
    p = st.p
    added = st.added_costs()
    feas = st.feasible(added)
    mg, pg, newly = st.gains()
    if not use_secondary:
        pg = np.zeros_like(pg)
    cols = np.flatnonzero(feas)
    moves_cols = [(int(c),) for c in cols]
    costs = list(added[cols])
    prim = list(mg[cols])
    sec = list(pg[cols])
    if use_pairs:
        cm = p.cost_model
        for a, b in _pair_shortlist(st, feas, newly):
            cost = added[a] + added[b]
            if p.site[a] == p.site[b] and st.site_count[p.site[a]] == 0:
                cost -= cm.setup_per_site
            if cost > p.remaining0 - st.cost + _EPS:
                continue
            g_m, g_p = st.joint_gain((a, b))
            moves_cols.append((int(a), int(b)))
            costs.append(cost)
            prim.append(g_m)
            sec.append(g_p if use_secondary else 0.0)
    if not moves_cols:
        return []
    costs, prim, sec = np.array(costs), np.array(prim), np.array(sec)
    positive = (prim > _EPS) | (sec > _EPS)
    if per_cost:
        div = np.maximum(costs, _EPS)
        prim, sec = prim / div, sec / div
    idx = np.flatnonzero(positive)
    if idx.size == 0:
        return []
    # rank: primary desc, secondary desc, then candidate IDs (indices are ID-sorted)
    tie = np.array([c[0] * (p.n_c + 1) + (c[1] + 1 if len(c) > 1 else 0)
                    for c in moves_cols])[idx]
    order = idx[np.lexsort((tie, -sec[idx], -prim[idx]))]
    return [(moves_cols[i], costs[i]) for i in order]


def _apply(st: _State, move):
    cols, _ = move
    for c in cols:
        st.add(c, st.added_costs()[c])


def _construct(st, *, per_cost, use_secondary, rng=None, deadline=np.inf):
    while time.monotonic() < deadline:
        moves = _best_moves(st, per_cost=per_cost, use_secondary=use_secondary,
                            use_pairs=True)
        if not moves:
            return
        pick = 0 if rng is None else int(rng.integers(min(3, len(moves))))
        _apply(st, moves[pick])


def _prune(p, st, deadline):
    """Remove holes whose removal leaves converted metal unchanged, then refill."""
    for c in sorted(st.selected, key=lambda c: p.ids[c], reverse=True):
        if c not in st.selected:
            continue
        trial = _rebuild(p, [x for x in st.selected if x != c])
        if trial.metal >= st.metal - _EPS:
            st = trial
    _construct(st, per_cost=True, use_secondary=False, deadline=deadline)
    return st


def _local_search(p, st, deadline):
    """Additions and swaps that raise converted metal within budget (spec 8.3 step 4).

    Removals alone never raise converted metal; they act here as the first half
    of a swap.
    """
    csr = p.cm.matrix.tocsr()
    for _ in range(p.settings.local_search_passes):
        if time.monotonic() > deadline:
            break
        improved = False
        moves = _best_moves(st, per_cost=True, use_secondary=False, use_pairs=False)
        if moves:
            _apply(st, moves[0])
            continue
        for h in sorted(st.selected, key=lambda c: p.ids[c]):
            if time.monotonic() > deadline:
                break
            rows, _ = p.col(h)
            touching = np.unique(csr[rows].indices)
            base = _rebuild(p, [x for x in st.selected if x != h])
            added = base.added_costs()
            feas = base.feasible(added)
            feas[h] = False
            mg, _, _ = base.gains()
            better = touching[feas[touching] & (base.metal + mg[touching] > st.metal + _EPS)]
            if better.size:
                best = better[np.lexsort((better, -mg[better]))[0]]
                base.add(int(best), added[best])
                st, improved = base, True
                break
        if not improved:
            break
    return st


# --------------------------------------------------------------------------- driver

@dataclass
class OptimiseResult:
    holes: pd.DataFrame           # locked holes then selected candidates (HOLE_COLUMNS)
    locked_overrun: float         # > 0 when locked holes alone exceed the budget
    search_metal: float           # the search's own figure; report evaluate_campaign()
    log: list[str]


def optimise(cm: CandidateMatrix, locked: pd.DataFrame | None, budget: float,
             cost_model: CostModel, settings: OptimiserSettings = OptimiserSettings(),
             initial: list[str] | None = None) -> OptimiseResult:
    """Best-found plan for one budget. ``initial`` is an extra warm-start plan
    (candidate IDs), tried as an additional run (spec section 9)."""
    if locked is None:
        locked = pd.DataFrame(columns=HOLE_COLUMNS)
    locked = locked.assign(locked=True)[HOLE_COLUMNS].reset_index(drop=True)
    p = _Problem(cm, locked, budget, cost_model, settings)
    log = []
    if p.remaining0 < -_EPS:
        log.append(f"Locked holes cost {p.locked_cost:,.0f}, above the budget of "
                   f"{budget:,.0f}. No holes were added.")
        return OptimiseResult(locked, p.locked_cost - budget, float("nan"), log)

    t0 = time.monotonic()
    deadline = t0 + settings.time_limit_s
    rng = np.random.default_rng(settings.seed)
    runs = []  # (label, per_cost, random, start cols)
    if initial:
        # First, so it always runs even when the time limit cuts later runs short:
        # this is what keeps conversion from falling as the budget rises (spec 9).
        pos = {h: i for i, h in enumerate(p.ids)}
        start = [pos[h] for h in initial if h in pos]
        runs.append(("warm start", True, False, start))
    runs.append(("deterministic", True, False, []))
    if settings.restarts > 1:
        runs.append(("absolute gain", False, False, []))
    runs += [(f"random top-3 #{i}", True, True, []) for i in range(settings.restarts - 2)]

    best = None
    for label, per_cost, randomised, start in runs:
        if time.monotonic() > deadline and best is not None:
            log.append(f"Time limit reached; skipped run '{label}'.")
            continue
        st = _State(p)
        for c in start:
            added = st.added_costs()
            if st.feasible(added)[c]:
                st.add(c, added[c])
        _construct(st, per_cost=per_cost, use_secondary=True,
                   rng=rng if randomised else None, deadline=deadline)
        st = _prune(p, st, deadline)
        st = _local_search(p, st, deadline)
        key = (-round(st.metal, 9), round(st.cost, 6), tuple(sorted(p.ids[st.selected])))
        log.append(f"Run '{label}': {st.metal:,.3f} metal potentially converted, "
                   f"added cost {st.cost:,.0f}, {len(st.selected)} holes.")
        if best is None or key < best[0]:
            best = (key, st)

    st = best[1]
    chosen = p.cm.candidates.iloc[sorted(st.selected, key=lambda c: p.ids[c])]
    holes = pd.concat([locked, chosen.assign(locked=False)[HOLE_COLUMNS]],
                      ignore_index=True)
    log.append(f"Finished in {time.monotonic() - t0:.1f} s.")
    return OptimiseResult(holes, 0.0, st.metal, log)
