"""evaluate_campaign(): the single source of truth for scoring any campaign (spec 6.5, 6.7).

Manual plans and optimised plans both go through evaluate_campaign(), with no
separate code path. The optimiser searches on a sparse matrix for speed, but
every reported number comes from this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from engine.costs import CostBreakdown, CostModel, campaign_cost
from engine.geometry import (
    NearestThree,
    Thresholds,
    classify,
    hole_block_distances,
    insert_distances,
    metric_from_three,
    nearest_three,
)
from engine.holes import DEFAULT_SUPPORT_INTERVAL, support_points
from engine.schema import ClassRank


@dataclass(frozen=True)
class Target:
    """Source uploaded class S and target geometry class G. G must rank above S."""

    source: ClassRank = ClassRank.INDICATED
    target: ClassRank = ClassRank.MEASURED

    def __post_init__(self):
        if ClassRank(self.target) <= ClassRank(self.source) or self.target == ClassRank.NONE:
            raise ValueError("The target geometry class must rank above the source class.")


@dataclass
class EvaluationContext:
    """Everything that stays fixed while campaigns are evaluated.

    ``blocks`` are the selected (domain-filtered) valid blocks with a fresh
    0..n-1 index; row i of every array refers to blocks.iloc[i].
    """

    blocks: pd.DataFrame
    xyz: np.ndarray
    tree: cKDTree
    baseline: NearestThree
    thresholds: Thresholds
    target: Target
    cost_model: CostModel
    interval: float = DEFAULT_SUPPORT_INTERVAL
    baseline_metric: np.ndarray = field(init=False)
    baseline_rank: np.ndarray = field(init=False)
    eligible: np.ndarray = field(init=False)
    discrepancy: np.ndarray = field(init=False)

    def __post_init__(self):
        self.baseline_metric = self.baseline.metric
        self.baseline_rank = self.baseline.rank
        is_source = self.blocks["uploaded_class"].to_numpy() == int(self.target.source)
        meets = self.baseline_rank >= int(self.target.target)
        self.eligible = is_source & ~meets
        self.discrepancy = is_source & meets


def build_context(blocks: pd.DataFrame, support: pd.DataFrame, *, thresholds: Thresholds,
                  target: Target, cost_model: CostModel,
                  interval: float = DEFAULT_SUPPORT_INTERVAL,
                  baseline: NearestThree | None = None) -> EvaluationContext:
    """Prepare blocks and the baseline. Pass ``baseline`` to reuse a cached one."""
    if "valid" in blocks.columns:
        blocks = blocks[blocks["valid"].to_numpy(dtype=bool)]
    blocks = blocks.reset_index(drop=True)
    xyz = blocks[["x", "y", "z"]].to_numpy(dtype=float)
    if baseline is None:
        baseline = nearest_three(xyz, support, thresholds)
    elif len(baseline.dist) != len(blocks):
        raise ValueError("Cached baseline does not match the selected blocks.")
    return EvaluationContext(blocks, xyz, cKDTree(xyz), baseline, thresholds, target,
                             cost_model, interval)


@dataclass
class CampaignResult:
    blocks: pd.DataFrame          # block-level results, one row per selected block
    totals: dict[str, float]
    cost: CostBreakdown
    warnings: list[str]

    @property
    def converted_block_ids(self) -> set[str]:
        b = self.blocks
        return set(b.loc[b["converted"], "block_id"].astype(str))


def campaign_distances(ctx: EvaluationContext, holes: pd.DataFrame) -> np.ndarray:
    """Per-block nearest three distances after adding the campaign holes."""
    dist3 = ctx.baseline.dist.copy()
    radius = ctx.thresholds.search_radius
    for row in holes.itertuples(index=False):
        pts = support_points((row.x, row.y, row.z), row.azimuth, row.dip, row.length,
                             ctx.interval)
        rows, d = hole_block_distances(ctx.tree, ctx.xyz, pts, radius)
        insert_distances(dist3, rows, d)
    return dist3


def plan_warnings(holes: pd.DataFrame, min_angle: float | None,
                  site_cap: int | None) -> list[str]:
    """Rule breaches in a plan that is evaluated unchanged (manual plans)."""
    from engine.candidates import angular_conflict_pairs, site_cap_violations

    out = []
    if min_angle and len(holes):
        for a, b in angular_conflict_pairs(holes, min_angle):
            out.append(f"Holes {a} and {b} are less than {min_angle:g} degrees apart "
                       "at the same site.")
    if site_cap and len(holes):
        for site, n in site_cap_violations(holes, site_cap).items():
            out.append(f"Site {site} has {n} holes, above the limit of {site_cap}.")
    return out


def evaluate_campaign(ctx: EvaluationContext, holes: pd.DataFrame, *,
                      min_angle: float | None = None,
                      site_cap: int | None = None) -> CampaignResult:
    """Score a campaign (HOLE_COLUMNS table, locked holes included) on all selected blocks."""
    if holes["hole_id"].duplicated().any():
        raise ValueError("Campaign hole IDs must be unique.")
    dist3 = campaign_distances(ctx, holes)
    post_metric = metric_from_three(dist3)
    post_rank = classify(post_metric, ctx.thresholds)
    g = int(ctx.target.target)
    converted = ctx.eligible & (post_rank >= g)

    b = ctx.blocks
    tonnes = b["tonnes"].to_numpy(dtype=float)
    metal = b["metal"].to_numpy(dtype=float)
    table = pd.DataFrame({
        "block_id": b["block_id"].astype(str).to_numpy() if "block_id" in b else
        b.index.astype(str).to_numpy(),
        "uploaded_class": b["uploaded_class"].to_numpy(dtype=np.int8),
        "baseline_metric": ctx.baseline_metric,
        "baseline_class": ctx.baseline_rank,
        "post_metric": post_metric,
        "post_class": post_rank,
        "eligible": ctx.eligible,
        "discrepancy": ctx.discrepancy,
        "converted": converted,
        "tonnes": tonnes,
        "metal": metal,
    })
    totals = {
        "converted_tonnes": float(tonnes[converted].sum()),
        "converted_metal": float(metal[converted].sum()),
        "converted_blocks": int(converted.sum()),
        "eligible_tonnes": float(tonnes[ctx.eligible].sum()),
        "eligible_metal": float(metal[ctx.eligible].sum()),
        "discrepancy_tonnes": float(tonnes[ctx.discrepancy].sum()),
        "discrepancy_metal": float(metal[ctx.discrepancy].sum()),
    }
    cost = campaign_cost(holes, ctx.cost_model)
    return CampaignResult(table, totals, cost, plan_warnings(holes, min_angle, site_cap))
