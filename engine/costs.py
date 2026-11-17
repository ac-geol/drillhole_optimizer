"""Campaign cost model (spec 7.2).

cost = total metres x cost per metre + holes x fixed cost per hole
       + distinct sites x setup cost per site
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class CostModel:
    cost_per_metre: float
    fixed_per_hole: float = 0.0
    setup_per_site: float = 0.0


@dataclass(frozen=True)
class CostBreakdown:
    total: float
    metres: float
    n_holes: int
    n_sites: int
    drilling: float
    fixed: float
    setup: float


def campaign_cost(holes: pd.DataFrame, model: CostModel) -> CostBreakdown:
    """Cost of a campaign given as a HOLE_COLUMNS table (locked holes included)."""
    metres = float(holes["length"].sum()) if len(holes) else 0.0
    n_holes = len(holes)
    n_sites = int(holes["site_id"].nunique()) if len(holes) else 0
    drilling = metres * model.cost_per_metre
    fixed = n_holes * model.fixed_per_hole
    setup = n_sites * model.setup_per_site
    return CostBreakdown(drilling + fixed + setup, metres, n_holes, n_sites, drilling, fixed, setup)


def added_cost(length: float, site_is_new: bool, model: CostModel) -> float:
    """Marginal cost of adding one hole to a campaign."""
    return length * model.cost_per_metre + model.fixed_per_hole + (
        model.setup_per_site if site_is_new else 0.0)
