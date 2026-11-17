import json

import numpy as np
import pandas as pd

from engine import DISCLAIMER
from engine.costs import CostModel
from engine.exports import (
    blocks_table,
    comparison_table,
    csv_bytes,
    holes_table,
    scenario_json_bytes,
    summary_table,
)
from engine.schema import ClassRank
from engine.units import GradeUnit


def test_csv_bytes_disclaimer_and_no_blank_lines():
    out = csv_bytes(pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}))
    text = out.decode("utf-8")
    lines = text.split("\n")
    assert lines[0] == "# " + DISCLAIMER
    assert lines[1] == "a,b" and lines[-1] == ""
    assert "\r" not in text and "" not in lines[:-1]


def test_scenario_json():
    data = json.loads(scenario_json_bytes(
        {"seed": np.int64(3), "b": np.array([1.0, 2.0]), "u": GradeUnit.GPT}))
    assert data["disclaimer"] == DISCLAIMER
    assert data["seed"] == 3 and data["b"] == [1.0, 2.0] and data["u"] == "g/t"


def test_holes_table():
    holes = pd.DataFrame({"budget": [1000.0], "hole_id": ["h1"], "site_id": ["s1"],
                          "x": [1.0], "y": [2.0], "z": [3.0], "azimuth": [90.0],
                          "dip": [-60.0], "length": [100.0], "locked": [False]})
    t = holes_table(holes, CostModel(cost_per_metre=10.0, fixed_per_hole=50.0, setup_per_site=999))
    assert t["hole_cost_excl_setup"][0] == 1050.0
    assert t["length_m"][0] == 100.0 and "length" not in t.columns


def test_summary_and_comparison_headers():
    s = pd.DataFrame({"budget": [1.0], "planned_cost": [1.0], "remaining_budget": [0.0],
                      "metres": [1.0], "holes": [1], "sites": [1], "converted_tonnes": [5.0],
                      "converted_metal": [2.0], "metal_per_metre": [1.0],
                      "metal_per_cost": [1.0]})
    t = summary_table(s, GradeUnit.GPT)
    assert {"metres_m", "potentially_converted_tonnes_t", "potentially_converted_metal_kg",
            "metal_kg_per_m", "metal_kg_per_cost"} <= set(t.columns)
    assert not any(c in ("converted_tonnes", "converted_metal") for c in t.columns)
    c = pd.DataFrame({"plan": ["Manual", "Both plans"], "converted_tonnes": [5.0, 3.0],
                      "converted_metal": [2.0, 1.0], "holes": [2, np.nan]})
    ct = comparison_table(c, GradeUnit.PERCENT)
    assert "potentially_converted_metal_t" in ct.columns and "plan" in ct.columns


def test_blocks_table():
    b = pd.DataFrame({
        "block_id": [1, 2], "uploaded_class": [int(ClassRank.INDICATED), 0],
        "baseline_metric": [30.0, np.nan], "baseline_class": [2, 0],
        "post_metric": [20.0, np.nan], "post_class": [3, 0],
        "converted": [True, False], "tonnes": [10.0, 20.0], "metal": [1.0, 2.0]})
    t = blocks_table(b, GradeUnit.PERCENT)
    assert list(t.columns) == [
        "block_id", "uploaded_class", "baseline_geometry_class",
        "baseline_mean_dist_3_holes_m", "post_geometry_class", "post_mean_dist_3_holes_m",
        "potentially_converted", "tonnes_t", "metal_t"]
    assert list(t["uploaded_class"]) == ["Indicated", "Unclassified"]
    assert list(t["post_geometry_class"]) == ["Measured geometry", "Outside criteria"]
    assert csv_bytes(t).decode().startswith("# " + DISCLAIMER + "\n")
