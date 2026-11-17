"""Budget scenarios, manual plan import and comparison (synthetic data)."""

import numpy as np
import pandas as pd
import pytest

from engine.candidates import CandidateSettings, Range, generate_candidates
from engine.costs import CostModel
from engine.evaluate import Target, build_context
from engine.geometry import Thresholds
from engine.optimise import OptimiserSettings, build_candidate_matrix
from engine.scenarios import (
    EXPANDABLE,
    INDEPENDENT,
    compare_manual,
    holes_frame,
    prepare_manual_plan,
    run_budgets,
    summary_frame,
)
from tests import synthetic as syn

COST = CostModel(cost_per_metre=100.0, fixed_per_hole=1_000.0, setup_per_site=5_000.0)
FAST = OptimiserSettings(restarts=2, time_limit_s=30)


def _field():
    """A 200 x 200 m Indicated zone with sparse existing drilling and a grid of sites."""
    rng = np.random.default_rng(0)
    xyz = np.column_stack([rng.uniform(0, 200, 400), rng.uniform(0, 200, 400),
                           rng.uniform(-80, -20, 400)])
    blocks = syn.blocks(xyz, metal=rng.uniform(0.5, 2.0, 400))
    support = syn.combine(*[syn.vertical_support(f"E{i}", x, y, 0, -120, 2)
                            for i, (x, y) in enumerate([(30, 30), (170, 40), (100, 170),
                                                        (40, 150), (160, 160)])])
    ctx = build_context(blocks, support, thresholds=Thresholds(), target=Target(),
                        cost_model=COST)
    sites = pd.DataFrame([[f"S{i}{j}", 25 + 50 * i, 25 + 50 * j, 0]
                          for i in range(4) for j in range(4)],
                         columns=["site_id", "x", "y", "z"])
    cands = generate_candidates(sites, CandidateSettings(Range(0, 270, 90), Range(-90, -60, 30),
                                                         Range(100, 100, 1)))
    return ctx, build_candidate_matrix(ctx, cands), sites


@pytest.mark.parametrize("mode", [INDEPENDENT, EXPANDABLE])
def test_conversion_non_decreasing_across_budgets(mode):
    ctx, cm, _ = _field()
    budgets = [150_000, 30_000, 60_000, 100_000]
    runs = run_budgets(ctx, cm, None, budgets, mode, COST, FAST)
    summary = summary_frame(runs)
    assert list(summary["budget"]) == sorted(budgets)
    assert (np.diff(summary["converted_metal"]) >= -1e-9).all()
    assert (summary["planned_cost"] <= summary["budget"] + 1e-9).all()
    assert summary["converted_metal"].iloc[-1] > 0
    if mode == EXPANDABLE:
        h = holes_frame(runs)
        for lo, hi in zip(sorted(budgets), sorted(budgets)[1:]):
            assert set(h[h.budget == lo].hole_id) <= set(h[h.budget == hi].hole_id)


def test_manual_plan_import_dip_toggle_and_site_matching():
    sites = pd.DataFrame([["S1", 0, 0, 0]], columns=["site_id", "x", "y", "z"])
    raw = pd.DataFrame({"ID": ["M1", "M2"], "E": [0.5, 500], "N": [0, 0], "RL": [0, 0],
                        "AZ": [90, 0], "DIP": [60, 90], "LEN": [100, 50]})
    cols = {"hole_id": "ID", "x": "E", "y": "N", "z": "RL", "azimuth": "AZ", "dip": "DIP",
            "length": "LEN"}
    plan = prepare_manual_plan(raw, cols, sites, positive_down=True, locked={"M2"})
    assert list(plan["dip"]) == [-60, -90]
    assert list(plan["site_id"]) == ["S1", "COLLAR_M2"]
    assert list(plan["locked"]) == [False, True]


def test_manual_comparison_splits():
    ctx, cm, _ = _field()
    manual = syn.planned_holes([syn.vertical_hole("M1", "S11", 75, 75, 0, 100),
                                syn.vertical_hole("M2", "S22", 125, 125, 0, 100)])
    comp = compare_manual(ctx, cm, manual, COST, FAST)
    t = comp.table.set_index("plan")
    assert t.loc["Optimised", "planned_cost"] <= t.loc["Manual", "budget"] + 1e-9
    assert t.loc["Optimised", "converted_metal"] >= t.loc["Manual", "converted_metal"] - 1e-9
    both, m_only, o_only = (t.loc[k, "converted_metal"]
                            for k in ("Both plans", "Manual only", "Optimised only"))
    assert both + m_only == pytest.approx(t.loc["Manual", "converted_metal"])
    assert both + o_only == pytest.approx(t.loc["Optimised", "converted_metal"])


def test_repeated_budget_runs_once():
    ctx, cm, _ = _field()
    runs = run_budgets(ctx, cm, None, [60_000, 60_000.0, 30_000], INDEPENDENT, COST, FAST)
    assert [r.budget for r in runs] == [30_000.0, 60_000.0]
    assert not holes_frame(runs).duplicated(["budget", "hole_id"]).any()
    assert not any(line.startswith("Note:") for r in runs for line in r.log)


def test_manual_plan_missing_column_is_a_plain_error():
    raw = pd.DataFrame({"ID": ["M1"], "E": [0.0]})
    cols = {"hole_id": "ID", "x": "E", "y": "N", "z": "RL", "azimuth": "AZ", "dip": "DIP",
            "length": "LEN"}
    with pytest.raises(ValueError, match="no column named N, RL"):
        prepare_manual_plan(raw, cols, None)
