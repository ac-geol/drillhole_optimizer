"""Hole geometry, support points and the cost model (acceptance test 13)."""

import numpy as np
import pandas as pd
import pytest

from engine.costs import CostModel, campaign_cost
from engine.holes import direction, support_depths, support_points, to_internal_dip


def test_direction_conventions():
    np.testing.assert_allclose(direction(0, 0), [0, 1, 0], atol=1e-12)    # north
    np.testing.assert_allclose(direction(90, 0), [1, 0, 0], atol=1e-12)   # east
    np.testing.assert_allclose(direction(0, -90), [0, 0, -1], atol=1e-12)  # straight down


def test_support_depths_midpoints_and_short_final_interval():
    np.testing.assert_allclose(support_depths(10, 2), [1, 3, 5, 7, 9])
    np.testing.assert_allclose(support_depths(11, 2), [1, 3, 5, 7, 9, 10.5])


def test_support_points_vertical_hole():
    pts = support_points((0, 0, 100), 0, -90, 4, 2)
    np.testing.assert_allclose(pts, [[0, 0, 99], [0, 0, 97]], atol=1e-12)


def test_dip_sign_toggle():
    np.testing.assert_allclose(to_internal_dip([60, 90], positive_down=True), [-60, -90])
    np.testing.assert_allclose(to_internal_dip([-60], positive_down=False), [-60])


def test_13_site_setup_costing():
    holes = pd.DataFrame({"hole_id": ["a", "b", "c"], "site_id": ["S1", "S1", "S2"],
                          "length": [100.0, 150.0, 200.0]})
    model = CostModel(cost_per_metre=250.0, fixed_per_hole=5_000.0, setup_per_site=20_000.0)
    cost = campaign_cost(holes, model)
    expected = 450 * 250.0 + 3 * 5_000.0 + 2 * 20_000.0
    assert cost.total == pytest.approx(expected)
    assert (cost.metres, cost.n_holes, cost.n_sites) == (450, 3, 2)
