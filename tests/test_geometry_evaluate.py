"""Geometry metric and evaluate_campaign(): acceptance tests 1, 2, 3, 5, 6 (synthetic data)."""

import numpy as np
import pytest

from engine.costs import CostModel
from engine.evaluate import Target, build_context, evaluate_campaign
from engine.geometry import Thresholds, classify, nearest_three
from engine.schema import ClassRank
from tests import synthetic as syn

T = Thresholds()


def test_01_one_hole_counts_once():
    block = np.array([[0.0, 0.0, 0.0]])
    pts = np.column_stack([np.linspace(-5, 5, 50), np.full(50, 3.0), np.zeros(50)])
    nt = nearest_three(block, syn.support("H1", pts), T)
    assert np.isnan(nt.metric[0])
    assert nt.rank[0] == ClassRank.NONE
    assert nt.hole[0, 0] >= 0 and (nt.hole[0, 1:] == -1).all()


def test_02_three_nearest_distinct_holes():
    block = np.array([[0.0, 0.0, 0.0]])
    # five holes at 10..50 m, the nearest with several samples
    frames = [syn.support(f"H{d}", [[d, 0, 0], [d + 1, 0, 0], [d + 2, 0, 0]])
              for d in (10, 20, 30, 40, 50)]
    nt = nearest_three(block, syn.combine(*frames), T)
    np.testing.assert_allclose(nt.dist[0], [10, 20, 30])
    assert nt.metric[0] == pytest.approx(20.0)


def test_nearest_three_needs_more_than_k0_points():
    # 100 points of one hole closer than two other holes: k must grow past 32
    block = np.array([[0.0, 0.0, 0.0]])
    near = syn.support("NEAR", np.column_stack([np.full(100, 1.0), np.linspace(-1, 1, 100),
                                                np.zeros(100)]))
    frames = [near, syn.support("B", [[0, 5, 0]]), syn.support("C", [[0, -6, 0]])]
    nt = nearest_three(block, syn.combine(*frames), T)
    assert nt.dist[0, 2] == pytest.approx(6.0)


@pytest.mark.parametrize("value,expected", [
    (25.0, ClassRank.MEASURED), (25.01, ClassRank.INDICATED),
    (50.0, ClassRank.INDICATED), (50.01, ClassRank.INFERRED),
    (100.0, ClassRank.INFERRED), (100.01, ClassRank.NONE),
])
def test_03_threshold_boundaries(value, expected):
    # three holes each exactly `value` from the block, on the three axes
    block = np.array([[0.0, 0.0, 0.0]])
    frames = [syn.support("X", [[value, 0, 0]]), syn.support("Y", [[0, value, 0]]),
              syn.support("Z", [[0, 0, value]])]
    nt = nearest_three(block, syn.combine(*frames), T)
    assert nt.rank[0] == expected
    assert classify([value], T)[0] == expected


def test_thresholds_must_increase():
    with pytest.raises(ValueError):
        Thresholds(25, 25, 100)


def _ctx(blocks, support):
    return build_context(blocks, support, thresholds=T, target=Target(),
                         cost_model=CostModel(cost_per_metre=100.0))


def test_05_baseline_not_claimed():
    blocks = syn.blocks([[0, 0, 0]], uploaded_class=ClassRank.INDICATED, metal=7.0)
    support = syn.combine(syn.support("A", [[10, 0, 0]]), syn.support("B", [[0, 10, 0]]),
                          syn.support("C", [[-10, 0, 0]]))
    ctx = _ctx(blocks, support)
    holes = syn.planned_holes([syn.vertical_hole("P1", "S1", 1, 1, 50, 100)])
    res = evaluate_campaign(ctx, holes)
    assert res.totals["converted_metal"] == 0.0
    assert res.totals["discrepancy_metal"] == 7.0
    assert bool(res.blocks["discrepancy"].iloc[0]) and not bool(res.blocks["converted"].iloc[0])


def test_06_no_double_counting():
    xyz = [[x, 0, 0] for x in (-4, -2, 0, 2, 4)]
    blocks = syn.blocks(xyz, metal=2.0)
    # two existing holes 20 m away: only two holes, so blocks start outside criteria
    support = syn.combine(syn.vertical_support("E1", 0, 20, 50, -50),
                          syn.vertical_support("E2", 0, -20, 50, -50))
    ctx = _ctx(blocks, support)
    p1 = syn.vertical_hole("P1", "S1", 10, 0, 50, 100)
    p2 = syn.vertical_hole("P2", "S2", -10, 0, 50, 100)
    one = evaluate_campaign(ctx, syn.planned_holes([p1]))
    other = evaluate_campaign(ctx, syn.planned_holes([p2]))
    both = evaluate_campaign(ctx, syn.planned_holes([p1, p2]))
    assert one.totals["converted_metal"] == pytest.approx(10.0)
    assert other.totals["converted_metal"] == pytest.approx(10.0)
    assert both.totals["converted_metal"] == pytest.approx(10.0)  # union, not 20


def test_evaluate_identical_campaigns_identical_results():
    blocks = syn.blocks([[x, 0, 0] for x in range(-20, 21, 5)])
    support = syn.vertical_support("E1", 0, 15, 50, -50)
    ctx = _ctx(blocks, support)
    plan = syn.planned_holes([syn.vertical_hole("P1", "S1", 5, -5, 50, 100),
                              syn.vertical_hole("P2", "S2", -5, -5, 50, 100)])
    a, b = evaluate_campaign(ctx, plan), evaluate_campaign(ctx, plan.iloc[::-1])
    assert a.blocks.equals(b.blocks) and a.totals == b.totals


def test_target_must_rank_above_source():
    with pytest.raises(ValueError):
        Target(source=ClassRank.MEASURED, target=ClassRank.INDICATED)
