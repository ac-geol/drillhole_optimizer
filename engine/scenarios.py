"""Budget scenario runs and manual-plan comparison (spec section 9), and manual plan import (5.4)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from engine.costs import CostModel
from engine.evaluate import CampaignResult, EvaluationContext, evaluate_campaign
from engine.holes import to_internal_dip
from engine.optimise import CandidateMatrix, OptimiserSettings, optimise
from engine.schema import HOLE_COLUMNS

INDEPENDENT = "independent"
EXPANDABLE = "expandable"
COMPARISON_NOTE = "Greater geometric conversion does not make a plan the better geological programme."

SUMMARY_COLUMNS = ["budget", "planned_cost", "remaining_budget", "metres", "holes", "sites",
                   "converted_tonnes", "converted_metal", "metal_per_metre", "metal_per_cost"]


# --------------------------------------------------------------------------- manual plan

def prepare_manual_plan(raw: pd.DataFrame, columns: dict[str, str], sites: pd.DataFrame | None,
                        *, positive_down: bool = False, match_tolerance: float = 1.0,
                        locked: set[str] | None = None) -> pd.DataFrame:
    """Map a manual plan CSV to HOLE_COLUMNS (spec 5.4).

    ``columns`` maps internal field -> source column for hole_id, site_id (optional),
    x, y, z, azimuth, dip, length. A hole without a site_id is matched to a site whose
    collar lies within ``match_tolerance`` m; otherwise its collar is its own site.
    """
    absent = [v for v in columns.values() if v and v not in raw.columns]
    if absent:
        raise ValueError("The manual plan file has no column named " + ", ".join(absent)
                         + ". Re-map its columns on the Project page.")
    out = pd.DataFrame({k: raw[v] for k, v in columns.items() if v})
    missing = [c for c in ("hole_id", "x", "y", "z", "azimuth", "dip", "length") if c not in out]
    if missing:
        raise ValueError(f"Manual plan is missing required fields: {', '.join(missing)}.")
    out["hole_id"] = out["hole_id"].astype(str).str.strip()
    for c in ("x", "y", "z", "azimuth", "dip", "length"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    bad = out[["x", "y", "z", "azimuth", "dip", "length"]].isna().any(axis=1) | (out["length"] <= 0)
    if bad.any():
        raise ValueError("Manual plan rows with missing or non-numeric geometry: "
                         + ", ".join(out.loc[bad, "hole_id"].head(10)))
    if out["hole_id"].duplicated().any():
        raise ValueError("Manual plan hole IDs must be unique.")
    out["dip"] = to_internal_dip(out["dip"], positive_down)
    site = out["site_id"].astype(str).str.strip() if "site_id" in out else pd.Series("", index=out.index)
    site = site.where(~site.isin(["", "nan", "None"]), "")
    for i in np.flatnonzero(site.to_numpy() == ""):
        row = out.iloc[i]
        match = ""
        if sites is not None and len(sites):
            d = np.sqrt((sites["x"] - row.x) ** 2 + (sites["y"] - row.y) ** 2
                        + (sites["z"] - row.z) ** 2).to_numpy()
            j = int(np.argmin(d))
            if d[j] <= match_tolerance:
                match = str(sites["site_id"].iloc[j])
        site.iloc[i] = match or f"COLLAR_{row.hole_id}"
    out["site_id"] = site
    out["locked"] = out["hole_id"].isin(locked or set())
    return out[HOLE_COLUMNS].reset_index(drop=True)


# --------------------------------------------------------------------------- budget runs

@dataclass
class BudgetRun:
    budget: float
    holes: pd.DataFrame
    result: CampaignResult
    locked_overrun: float
    log: list[str] = field(default_factory=list)


def run_budgets(ctx: EvaluationContext, cm: CandidateMatrix, locked: pd.DataFrame | None,
                budgets: list[float], mode: str, cost_model: CostModel,
                settings: OptimiserSettings | None = None,
                progress: Callable[[int, int], None] | None = None) -> list[BudgetRun]:
    """Run several budgets in ascending order.

    Independent: each budget is optimised on its own and also tries the previous
    budget's plan as a starting point, so conversion does not fall as budget rises.
    Expandable: the previous budget's campaign is locked and holes are added.
    """
    settings = settings or OptimiserSettings()
    if mode not in (INDEPENDENT, EXPANDABLE):
        raise ValueError(f"Unknown mode {mode!r}.")
    user_locked = pd.DataFrame(columns=HOLE_COLUMNS) if locked is None else locked
    user_ids = set(user_locked["hole_id"].astype(str))
    runs: list[BudgetRun] = []
    prev: pd.DataFrame | None = None
    ordered = sorted({float(b) for b in budgets})  # a repeated budget is run once
    for i, budget in enumerate(ordered):
        initial = None
        fixed = user_locked
        if prev is not None:
            carried = prev[~prev["hole_id"].astype(str).isin(user_ids)]
            if mode == EXPANDABLE:
                fixed = pd.concat([user_locked, carried], ignore_index=True)
            else:
                initial = carried["hole_id"].astype(str).tolist()
        res = optimise(cm, fixed, budget, cost_model, settings, initial=initial)
        holes = res.holes.copy()
        holes["locked"] = holes["hole_id"].astype(str).isin(user_ids)
        ev = evaluate_campaign(ctx, holes, min_angle=settings.min_angle,
                               site_cap=settings.site_cap)
        log = list(res.log)
        reported = ev.totals["converted_metal"]
        if np.isfinite(res.search_metal) and not np.isclose(res.search_metal, reported,
                                                            rtol=1e-6, atol=1e-9):
            # The search stores distances as float32, so a block sitting exactly on the
            # threshold can differ. The reported figure is always the evaluated one.
            log.append(f"Note: the search counted {res.search_metal:,.3f} metal and the "
                       f"evaluation reports {reported:,.3f}. The reported figure is used.")
        runs.append(BudgetRun(budget, holes, ev, res.locked_overrun, log))
        prev = holes
        if progress:
            progress(i + 1, len(ordered))
    return runs


def _metrics(budget: float, result: CampaignResult) -> dict:
    c, t = result.cost, result.totals
    metal = t["converted_metal"]
    return {
        "budget": budget,
        "planned_cost": c.total,
        "remaining_budget": budget - c.total,
        "metres": c.metres,
        "holes": c.n_holes,
        "sites": c.n_sites,
        "converted_tonnes": t["converted_tonnes"],
        "converted_metal": metal,
        "metal_per_metre": metal / c.metres if c.metres else np.nan,
        "metal_per_cost": metal / c.total if c.total else np.nan,
    }


def summary_frame(runs: list[BudgetRun]) -> pd.DataFrame:
    return pd.DataFrame([_metrics(r.budget, r.result) for r in runs], columns=SUMMARY_COLUMNS)


def holes_frame(runs: list[BudgetRun]) -> pd.DataFrame:
    frames = [r.holes.assign(budget=r.budget) for r in runs]
    if not frames:
        return pd.DataFrame(columns=["budget", *HOLE_COLUMNS])
    return pd.concat(frames, ignore_index=True)[["budget", *HOLE_COLUMNS]]


# --------------------------------------------------------------------------- comparison

@dataclass
class Comparison:
    manual: CampaignResult
    optimised: BudgetRun
    table: pd.DataFrame       # plan rows: Manual, Optimised, Both plans, Manual only, Optimised only
    note: str = COMPARISON_NOTE


def compare_manual(ctx: EvaluationContext, cm: CandidateMatrix, manual: pd.DataFrame,
                   cost_model: CostModel,
                   settings: OptimiserSettings | None = None) -> Comparison:
    """Evaluate the manual plan unchanged, then optimise at the manual plan's cost,
    honouring any locked manual holes, and split converted blocks by block ID."""
    settings = settings or OptimiserSettings()
    man = evaluate_campaign(ctx, manual, min_angle=settings.min_angle, site_cap=settings.site_cap)
    budget = man.cost.total
    locked = manual[manual["locked"].astype(bool)]
    opt = run_budgets(ctx, cm, locked, [budget], INDEPENDENT, cost_model, settings)[0]

    blocks = man.blocks
    m_conv = blocks["converted"].to_numpy()
    o_conv = opt.result.blocks["converted"].to_numpy()
    rows = [{"plan": "Manual", **_metrics(budget, man)},
            {"plan": "Optimised", **_metrics(budget, opt.result)}]
    for label, mask in (("Both plans", m_conv & o_conv), ("Manual only", m_conv & ~o_conv),
                        ("Optimised only", ~m_conv & o_conv)):
        rows.append({"plan": label,
                     "converted_tonnes": float(blocks["tonnes"].to_numpy()[mask].sum()),
                     "converted_metal": float(blocks["metal"].to_numpy()[mask].sum())})
    table = pd.DataFrame(rows, columns=["plan", *SUMMARY_COLUMNS])
    return Comparison(man, opt, table)
