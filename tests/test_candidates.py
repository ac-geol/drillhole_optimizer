import time

import numpy as np
import pandas as pd
import pytest

from engine import schema
from engine.candidates import (
    BYTES_PER_CANDIDATE,
    BYTES_PER_ENTRY,
    CandidateSettings,
    Range,
    angular_conflict_pairs,
    candidate_id,
    conflict_lists,
    estimate_size,
    generate_candidates,
    range_values,
    site_cap_violations,
    trace_group_id,
)


def sites(n=2):
    return pd.DataFrame({"site_id": [f"S{i + 1}" for i in range(n)],
                         "x": np.arange(n) * 100.0, "y": 0.0, "z": 10.0})


def settings(az=(0, 270, 90), dip=(-60, -45, 15), ln=(100, 150, 50)):
    return CandidateSettings(Range(*az), Range(*dip), Range(*ln))


def test_range_values():
    assert list(range_values(Range(0, 1, 0.1))) == pytest.approx(np.arange(0, 1.01, 0.1))
    assert len(range_values(Range(0, 1, 0.1))) == 11
    assert list(range_values(Range(5, 5, 1))) == [5.0]
    with pytest.raises(ValueError):
        range_values(Range(0, 10, 0))
    with pytest.raises(ValueError):
        range_values(Range(10, 0, 1))


def test_id_format_and_stability():
    assert candidate_id("S1", 45, -60, 150) == "S1_A45_D-60_L150"
    assert candidate_id("S1", 45.0, -60.0, 150.0) == "S1_A45_D-60_L150"
    assert candidate_id("S1", 360, -60, 150) == "S1_A0_D-60_L150"
    assert trace_group_id("S1", 45, -60) == "S1_A45_D-60"
    assert trace_group_id("S1", 123, -90) == "S1_A0_D-90"
    a = generate_candidates(sites(), settings())
    b = generate_candidates(sites(), settings())
    pd.testing.assert_frame_equal(a, b)


def test_counts_order_and_columns():
    c = generate_candidates(sites(), settings())
    assert list(c.columns) == schema.HOLE_COLUMNS + ["group_id"]
    assert len(c) == 2 * 4 * 2 * 2
    assert c["hole_id"].is_unique
    assert not c["locked"].any()
    assert list(c.index) == list(range(len(c)))
    assert c.iloc[0].hole_id == "S1_A0_D-60_L100"
    assert c.iloc[1].hole_id == "S1_A0_D-60_L150"
    assert c.iloc[2].hole_id == "S1_A0_D-45_L100"
    assert (c[c.site_id == "S2"]["x"] == 100.0).all()
    assert list(c.site_id[:16].unique()) == ["S1"]


def test_360_equals_0():
    c = generate_candidates(
        sites(1), settings(az=(0, 360, 90), dip=(-60, -60, 1), ln=(100, 100, 1)))
    assert sorted(c.azimuth) == [0.0, 90.0, 180.0, 270.0]


def test_dip_minus_90_single_azimuth():
    c = generate_candidates(
        sites(1), settings(az=(0, 270, 90), dip=(-90, -60, 30), ln=(100, 100, 1)))
    assert len(c[c.dip == -90]) == 1
    assert c[c.dip == -90].azimuth.iloc[0] == 0.0
    assert len(c[c.dip == -60]) == 4


def test_group_shared_across_lengths():
    c = generate_candidates(sites(1), settings())
    assert (c.groupby("group_id")["length"].nunique() == 2).all()
    assert c.group_id.nunique() == len(c) // 2


def test_conflict_lists_same_trace_and_angles():
    c = generate_candidates(
        sites(1), settings(az=(0, 270, 90), dip=(-60, -60, 1), ln=(100, 150, 50)))
    cl = conflict_lists(c, 0)
    assert all(len(x) == 1 for x in cl)
    assert list(cl[0]) == [1]
    cl = conflict_lists(c, 10)
    assert all(len(x) == 1 for x in cl)  # 90 degree azimuth steps do not conflict


def test_conflict_angle_threshold():
    # a-b about 2.5 degrees apart; a-c exactly 10 degrees (dip only); d at another site
    h = pd.DataFrame({
        "hole_id": ["a", "b", "c", "d"], "site_id": ["S"] * 3 + ["T"],
        "azimuth": [0.0, 5.0, 0.0, 0.0], "dip": [-60.0, -60.0, -50.0, -60.0],
    })
    cl = conflict_lists(h, 10)
    assert list(cl[0]) == [1]
    assert list(cl[1]) == [0]
    assert list(cl[2]) == []
    assert list(cl[3]) == []
    assert list(conflict_lists(h, 0)[0]) == []
    assert angular_conflict_pairs(h, 10) == [("a", "b")]
    assert angular_conflict_pairs(h, 0) == []
    assert angular_conflict_pairs(h, 10.5) == [("a", "b"), ("a", "c"), ("b", "c")]


def test_locked_hole_occupies_group():
    h = pd.DataFrame({"hole_id": ["m", "c"], "site_id": ["S", "S"], "azimuth": [45.0, 405.0],
                      "dip": [-60.0, -60.0], "length": [80.0, 120.0]})
    assert list(conflict_lists(h, 0)[0]) == [1]


def test_site_cap():
    h = pd.DataFrame({"site_id": ["A"] * 11 + ["B"] * 10})
    assert site_cap_violations(h, 10) == {"A": 11}
    assert site_cap_violations(h, 5) == {"A": 11, "B": 10}


def test_size_estimate_warnings():
    xyz = np.random.default_rng(0).uniform(0, 1000, (5000, 3))
    s = settings(ln=(100, 200, 100))
    e = estimate_size(100, xyz, s, 50.0)
    assert e.warnings == []
    assert 0 < e.est_entries <= 100 * 5000
    assert e.est_bytes == e.est_entries * BYTES_PER_ENTRY + 100 * BYTES_PER_CANDIDATE
    e = estimate_size(20_000, xyz, s, 50.0)
    assert any("coarser" in w for w in e.warnings)
    e = estimate_size(14_000, xyz, s, 1e6)  # every block in reach of every hole
    assert e.est_entries == 14_000 * 5000
    big = np.random.default_rng(1).uniform(0, 100, (5_000_000, 3))
    e = estimate_size(10_000, big, s, 1e6)
    assert e.est_bytes > 2 * 1024**3 and any("2 GB" in w for w in e.warnings)
    flat = estimate_size(10, np.zeros((5, 3)), s, 10.0)
    assert flat.est_entries == 50


def test_performance_50_sites():
    c = generate_candidates(
        sites(50), settings(az=(0, 350, 10), dip=(-80, -45, 5), ln=(100, 200, 50)))
    assert len(c) == 50 * 36 * 8 * 3
    t = time.time()
    cl = conflict_lists(c, 10)
    assert time.time() - t < 10
    assert len(cl) == len(c)
