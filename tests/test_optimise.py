"""Optimiser acceptance tests 7, 8, 9, 10, 12 (synthetic data)."""

import numpy as np
import pandas as pd
import pytest

from engine.candidates import CandidateSettings, Range, generate_candidates
from engine.costs import CostModel
from engine.evaluate import Target, build_context, evaluate_campaign
from engine.geometry import Thresholds
from engine.optimise import OptimiserSettings, build_candidate_matrix, optimise
from tests import synthetic as syn

COST = CostModel(cost_per_metre=100.0)
VERTICAL = CandidateSettings(Range(0, 0, 1), Range(-90, -90, 1), Range(100, 100, 1))
FAST = OptimiserSettings(restarts=3, time_limit_s=30)


def _sites(rows):
    return pd.DataFrame(rows, columns=["site_id", "x", "y", "z"])


def _cluster():
    xyz = [[x, y, 0] for x in (-2, 0, 2) for y in (-2, 0, 2)]
    return syn.blocks(xyz, metal=1.0)


def _pair_setup():
    blocks = _cluster()
    support = syn.vertical_support("E1", 0, 15, 50, -50)
    ctx = build_context(blocks, support, thresholds=Thresholds(), target=Target(),
                        cost_model=COST)
    sites = _sites([["S1", 13, -7, 50], ["S2", -13, -7, 50], ["FAR", 900, 900, 50]])
    cands = generate_candidates(sites, VERTICAL)
    return ctx, cands


def test_07_complementary_pair():
    ctx, cands = _pair_setup()
    for site in ("S1", "S2"):
        alone = evaluate_campaign(ctx, cands[cands.site_id == site])
        assert alone.totals["converted_metal"] == 0.0
    cm = build_candidate_matrix(ctx, cands)
    res = optimise(cm, None, budget=25_000, cost_model=COST, settings=FAST)
    assert set(res.holes["site_id"]) == {"S1", "S2"}
    assert evaluate_campaign(ctx, res.holes).totals["converted_metal"] == pytest.approx(9.0)


def test_07_pair_move_found_without_progress_tiebreak():
    # With the secondary score off, no single move has positive gain; only the pair does.
    from engine.optimise import _best_moves, _Problem, _State

    ctx, cands = _pair_setup()
    cm = build_candidate_matrix(ctx, cands)
    from engine.schema import HOLE_COLUMNS

    p = _Problem(cm, pd.DataFrame(columns=HOLE_COLUMNS), 20_000, COST, OptimiserSettings())
    moves = _best_moves(_State(p), per_cost=True, use_secondary=False, use_pairs=True)
    assert len(moves) == 1 and len(moves[0][0]) == 2
    assert _best_moves(_State(p), per_cost=True, use_secondary=False, use_pairs=False) == []


def test_08_locked_holes():
    ctx, cands = _pair_setup()
    cm = build_candidate_matrix(ctx, cands)
    locked = syn.planned_holes([syn.vertical_hole("POOR", "FAR2", 5000, 5000, 50, 50)])
    res = optimise(cm, locked, budget=25_000, cost_model=COST, settings=FAST)
    assert "POOR" in set(res.holes["hole_id"])
    assert bool(res.holes.loc[res.holes.hole_id == "POOR", "locked"].iloc[0])
    ev = evaluate_campaign(ctx, res.holes)
    assert ev.cost.total <= 25_000
    assert set(res.holes["site_id"]) == {"S1", "S2", "FAR2"}
    # budget only covers the locked hole and one more: the pair cannot be afforded
    res = optimise(cm, locked, budget=15_000, cost_model=COST, settings=FAST)
    assert evaluate_campaign(ctx, res.holes).cost.total <= 15_000


def test_08_locked_holes_over_budget():
    ctx, cands = _pair_setup()
    cm = build_candidate_matrix(ctx, cands)
    locked = syn.planned_holes([syn.vertical_hole("BIG", "S9", 0, 0, 50, 500)])
    res = optimise(cm, locked, budget=10_000, cost_model=COST, settings=FAST)
    assert list(res.holes["hole_id"]) == ["BIG"]
    assert res.locked_overrun == pytest.approx(40_000)


@pytest.mark.parametrize("budget", [5_000, 10_000, 19_999, 20_000, 1e6])
def test_09_within_budget(budget):
    ctx, cands = _pair_setup()
    cm = build_candidate_matrix(ctx, cands)
    res = optimise(cm, None, budget=budget, cost_model=COST, settings=FAST)
    assert evaluate_campaign(ctx, res.holes).cost.total <= budget + 1e-9
    if budget < 10_000:  # below the cheapest hole
        assert res.holes.empty


def test_10_manual_equals_generated():
    ctx, cands = _pair_setup()
    cm = build_candidate_matrix(ctx, cands)
    res = optimise(cm, None, budget=25_000, cost_model=COST, settings=FAST)
    manual = res.holes.copy()
    manual["hole_id"] = [f"MANUAL_{i}" for i in range(len(manual))]
    a, b = evaluate_campaign(ctx, res.holes), evaluate_campaign(ctx, manual)
    assert a.blocks.equals(b.blocks)
    assert a.totals == b.totals and a.cost == b.cost


def test_12_same_trace_exclusion_and_site_cap():
    blocks = _cluster()
    support = syn.combine(syn.vertical_support("E1", 0, 15, 50, -50),
                          syn.vertical_support("E2", 15, -5, 50, -50))
    ctx = build_context(blocks, support, thresholds=Thresholds(), target=Target(),
                        cost_model=COST)
    sites = _sites([["S1", -12, -8, 50]])
    two_lengths = CandidateSettings(Range(0, 0, 1), Range(-90, -90, 1), Range(100, 200, 100))
    cands = generate_candidates(sites, two_lengths)
    assert cands["group_id"].nunique() == 1 and len(cands) == 2
    for _, c in cands.iterrows():  # both attractive on their own
        assert evaluate_campaign(ctx, c.to_frame().T).totals["converted_metal"] > 0
    res = optimise(build_candidate_matrix(ctx, cands), None, budget=1e6, cost_model=COST,
                   settings=FAST)
    assert len(res.holes) == 1

    # site cap: a spread of blocks that many holes from one collar could serve
    xyz = [[x, y, -60] for x in range(-60, 61, 20) for y in range(-60, 61, 20)]
    ctx = build_context(syn.blocks(xyz), syn.vertical_support("E0", 0, 0, 50, -150),
                        thresholds=Thresholds(), target=Target(), cost_model=COST)
    fan = CandidateSettings(Range(0, 315, 45), Range(-90, -45, 15), Range(150, 150, 1))
    sites = _sites([["S1", 0, 5, 0], ["S2", 5, 0, 0]])
    settings = OptimiserSettings(restarts=1, site_cap=2, min_angle=0)
    res = optimise(build_candidate_matrix(ctx, generate_candidates(sites, fan)), None,
                   budget=1e7, cost_model=COST, settings=settings)
    counts = res.holes.groupby("site_id").size()
    assert len(res.holes) > 0 and (counts <= 2).all()


def test_deterministic_with_seed():
    ctx, cands = _pair_setup()
    cm = build_candidate_matrix(ctx, cands)
    a = optimise(cm, None, budget=25_000, cost_model=COST, settings=FAST)
    b = optimise(cm, None, budget=25_000, cost_model=COST, settings=FAST)
    assert a.holes.equals(b.holes)


def test_matrix_drops_useless_candidates():
    ctx, cands = _pair_setup()
    cm = build_candidate_matrix(ctx, cands)
    assert cm.n_dropped == 1 and set(cm.candidates["site_id"]) == {"S1", "S2"}
    assert cm.matrix.dtype == np.float32
