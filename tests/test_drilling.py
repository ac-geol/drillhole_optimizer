"""Tests for engine.drilling (spec 5.2, milestones 2 and 8)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine import holes
from engine.drilling import DrillingMapping, desurvey_route_b, prepare_route_a


def _raw(valid):
    n = len(valid)
    return pd.DataFrame({
        "HID": [f" H{i % 2} " for i in range(n)], "X": np.arange(n, dtype=float),
        "Y": 1.0, "Z": 2.0, "OK": valid, "Dom": ["a"] * n,
    })


M = DrillingMapping("HID", "X", "Y", "Z", valid="OK", domain="Dom")


def test_route_a_validity_words_and_numbers():
    valid = ["Y", "n", "TRUE", "false", "T", "f", "yes", "No", 1, 0]
    res = prepare_route_a(_raw(valid), M)
    assert len(res.points) == 5
    assert res.n_rows == 10 and res.n_dropped == 5
    assert res.dropped_reasons == {"validity flag is false": 5}
    assert set(res.points["hole_id"]) == {"H0"}  # kept rows are all even-indexed; ids stripped
    assert (res.points["domain"] == "a").all()


def test_route_a_bool_and_unrecognised():
    res = prepare_route_a(_raw([True, False, "maybe", None, 2]), M)
    assert len(res.points) == 1
    assert res.dropped_reasons == {"validity flag is false": 1,
                                   "unrecognised validity value": 3}


def test_route_a_no_validity_and_bad_coordinates():
    raw = _raw([True] * 4)
    raw["X"] = [1.0, "abc", None, 4.0]
    res = prepare_route_a(raw, DrillingMapping("HID", "X", "Y", "Z"))
    assert len(res.points) == 2
    assert res.dropped_reasons == {"missing or non-numeric coordinates": 2}
    assert "domain" not in res.points.columns
    assert res.points["x"].dtype == np.float64
    assert res.assumptions


def _collars(**kw):
    return pd.DataFrame({"hole_id": ["A"], "x": [0.0], "y": [0.0], "z": [0.0], **kw})


def test_straight_hole_matches_support_points():
    surveys = pd.DataFrame({"hole_id": ["A"] * 3, "depth": [0.0, 30.0, 61.0],
                            "azimuth": [123.0] * 3, "dip": [-55.0] * 3})
    res = desurvey_route_b(_collars(max_depth=[61.0]), surveys, interval=2.0)
    expected = holes.support_points((0, 0, 0), 123.0, -55.0, 61.0, 2.0)
    np.testing.assert_allclose(res.points[["x", "y", "z"]].to_numpy(), expected, atol=1e-9)
    assert any("support interval" in a for a in res.assumptions)


def test_two_station_hand_calculation():
    # Collar (0,0,0). Station 0 m: az 0, dip -60. Station 100 m: az 30, dip -50.
    # Tangents t = (cos d sin a, cos d cos a, sin d):
    #   t1 = (0, cos60, -sin60)            = (0, 0.5, -0.866025)
    #   t2 = (cos50 sin30, cos50 cos30, -sin50) = (0.321394, 0.556670, -0.766044)
    # cos(beta) = t1.t2 = 0.278335 + 0.663414 = 0.941749 -> beta = 0.343002 rad
    # RF = 2/beta * tan(beta/2) = 1.009921
    # Position at 100 m = (L/2) RF (t1 + t2) = 50 * 1.009921 * (0.321394, 1.056670, -1.632070)
    #   = (16.2291, 53.3577, -82.4131)
    # Point at 50 m: tangent halfway along the arc, tm = (t1+t2)/|t1+t2|
    #   = (0.163089, 0.536201, -0.828185); sub-arc beta/2 = 0.171501, RF = 1.002458
    #   position = 25 * 1.002458 * (t1 + tm) = (4.0873, 25.9687, -42.4594)
    surveys = pd.DataFrame({"hole_id": ["A", "A"], "depth": [0.0, 100.0],
                            "azimuth": [0.0, 30.0], "dip": [-60.0, -50.0]})
    ivs = pd.DataFrame({"hole_id": ["A", "A"], "from": [0.0, 50.0], "to": [100.0, 150.0]})
    res = desurvey_route_b(_collars(), surveys, ivs)
    p = res.points[["x", "y", "z"]].to_numpy()
    np.testing.assert_allclose(p[0], [4.0873, 25.9687, -42.4594], atol=0.01)
    # Second interval midpoint is 100 m: the station itself.
    np.testing.assert_allclose(p[1], [16.2291, 53.3577, -82.4131], atol=0.01)
    # Beyond the last station: straight along t2 (50 m past the station at 100 m).
    ivs2 = pd.DataFrame({"hole_id": ["A"], "from": [140.0], "to": [160.0]})
    p2 = desurvey_route_b(_collars(), surveys, ivs2).points[["x", "y", "z"]].to_numpy()[0]
    exp = np.array([16.2291, 53.3577, -82.4131]) + 50 * np.array([0.321394, 0.556670, -0.766044])
    np.testing.assert_allclose(p2, exp, atol=0.01)


def test_implied_surface_station():
    surveys = pd.DataFrame({"hole_id": ["A"], "depth": [20.0], "azimuth": [90.0], "dip": [-45.0]})
    ivs = pd.DataFrame({"hole_id": ["A"], "from": [0.0], "to": [10.0]})
    p = desurvey_route_b(_collars(), surveys, ivs).points.iloc[0]
    s = np.sqrt(0.5)
    np.testing.assert_allclose([p.x, p.y, p.z], [5 * s, 0.0, -5 * s], atol=1e-9)


def test_positive_down_toggle():
    surveys = pd.DataFrame({"hole_id": ["A"], "depth": [0.0], "azimuth": [0.0], "dip": [60.0]})
    ivs = pd.DataFrame({"hole_id": ["A"], "from": [0.0], "to": [10.0]})
    down = desurvey_route_b(_collars(), surveys, ivs, positive_down=True).points.iloc[0]
    assert down.z == pytest.approx(-5 * np.sin(np.radians(60)))
    up = desurvey_route_b(_collars(), surveys, ivs, positive_down=False).points.iloc[0]
    assert up.z == pytest.approx(+5 * np.sin(np.radians(60)))


def test_intervals_vs_generated_and_missing_collars():
    surveys = pd.DataFrame({"hole_id": ["A", "A", "X"], "depth": [0.0, 10.0, 0.0],
                            "azimuth": [0.0, 0.0, 0.0], "dip": [-90.0, -90.0, -90.0]})
    ivs = pd.DataFrame({"hole_id": ["A", "A", "Y"], "from": [0.0, 4.0, 0.0],
                        "to": [4.0, 10.0, 2.0]})
    res = desurvey_route_b(_collars(), surveys, ivs)
    np.testing.assert_allclose(res.points["z"], [-2.0, -7.0])
    assert res.dropped_reasons == {"survey hole has no collar": 1,
                                   "interval hole has no collar": 1}
    assert res.n_dropped == 2 and res.n_rows == 1 + 3 + 3
    gen = desurvey_route_b(_collars(), surveys, None, interval=5.0)
    np.testing.assert_allclose(gen.points["z"], [-2.5, -7.5])


def test_collar_without_survey_is_vertical():
    surveys = pd.DataFrame({"hole_id": ["A"], "depth": [0.0], "azimuth": [0.0], "dip": [-90.0]})
    collars = pd.DataFrame({"hole_id": ["A", "B"], "x": [0.0, 5.0], "y": [0.0, 6.0],
                            "z": [0.0, 100.0], "max_depth": [4.0, 4.0]})
    res = desurvey_route_b(collars, surveys, interval=2.0)
    b = res.points[res.points["hole_id"] == "B"]
    np.testing.assert_allclose(b[["x", "y", "z"]].to_numpy(),
                               [[5, 6, 99], [5, 6, 97]], atol=1e-9)
    assert any("vertical" in a for a in res.assumptions)
