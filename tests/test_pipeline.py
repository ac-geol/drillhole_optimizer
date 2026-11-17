"""End-to-end pipeline from uploaded CSVs, and acceptance test 11 (scenario reproducibility).

All data is SYNTHETIC.
"""

import numpy as np
import pandas as pd
import pytest

from engine import exports
from engine.pipeline import blocks_for_budget, default_planning, run_scenario
from engine.storage import Project


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def _project(tmp_path) -> Project:
    rng = np.random.default_rng(3)
    n = 300
    blocks = pd.DataFrame({"XC": rng.uniform(0, 150, n), "YC": rng.uniform(0, 150, n),
                           "ZC": rng.uniform(-80, -20, n), "SIZE": 5.0, "DENS": 2.7,
                           "CLASS": rng.choice(["2", "3"], n, p=[0.8, 0.2]),
                           "AU": rng.uniform(0.5, 3.0, n)})
    blocks.loc[0, "AU"] = -99  # null sentinel
    holes = []
    for i, (x, y) in enumerate([(20, 20), (130, 30), (75, 130), (20, 120)]):
        z = np.arange(-1, -120, -2.0)
        holes.append(pd.DataFrame({"BHID": f"DH{i}", "X": x, "Y": y, "Z": z}))
    sites = pd.DataFrame({"SITE": [f"P{i}{j}" for i in range(3) for j in range(3)],
                          "E": [25 + 50 * i for i in range(3) for _ in range(3)],
                          "N": [25 + 50 * j for _ in range(3) for j in range(3)], "RL": 0.0})
    manual = pd.DataFrame({"HOLE": ["M1", "M2"], "E": [75.3, 125.0], "N": [75.0, 125.0],
                           "RL": [0.0, 0.0], "AZI": [0, 0], "DIP": [90, 90], "LEN": [100, 100]})
    p = Project.create(tmp_path, "Synthetic test project")
    p.save_input("blocks", _csv(blocks), "SYNTHETIC_blocks.csv")
    p.save_input("drilling", _csv(pd.concat(holes)), "SYNTHETIC_drilling.csv")
    p.save_input("sites", _csv(sites), "SYNTHETIC_sites.csv")
    p.save_input("manual", _csv(manual), "SYNTHETIC_manual.csv")
    planning = default_planning()
    planning.update(budgets=[60_000.0, 120_000.0],
                    candidates={"azimuth": [0, 270, 90], "dip": [-90, -60, 30],
                                "length": [100, 100, 1]})
    planning["optimiser"].update(restarts=2, time_limit_s=60)
    p.save_settings({**p.settings,
        "blocks": {"columns": {"x": "XC", "y": "YC", "z": "ZC", "dx": "SIZE", "dy": "SIZE",
                               "dz": "SIZE", "density": "DENS", "class_raw": "CLASS",
                               "grade": "AU"},
                   "constant_dims": {}, "grade_unit": "g/t",
                   "class_map": {"2": 2, "3": 3}, "null_sentinels": [-99, -999],
                   "domains": None},
        "drilling": {"route": "A", "mapping": {"hole_id": "BHID", "x": "X", "y": "Y",
                                               "z": "Z"}},
        "sites": {"columns": {"site_id": "SITE", "x": "E", "y": "N", "z": "RL"}},
        "manual": {"columns": {"hole_id": "HOLE", "x": "E", "y": "N", "z": "RL",
                               "azimuth": "AZI", "dip": "DIP", "length": "LEN"},
                   "positive_down": True, "match_tolerance": 1.0, "locked": ["M1"]},
        "planning": planning})
    return p


def test_end_to_end_and_exports(tmp_path):
    p = _project(tmp_path)
    run = run_scenario(p, "Base case")
    s = run.results["summary"]
    assert list(s["budget"]) == [60_000.0, 120_000.0]
    assert (s["planned_cost"] <= s["budget"] + 1e-9).all()
    assert s["converted_metal"].iloc[-1] > 0
    holes = run.results["holes"]
    assert "M1" in set(holes["hole_id"])  # locked manual hole carried into every budget
    assert set(run.results["comparison"]["plan"]) >= {"Manual", "Optimised", "Both plans"}
    blocks = blocks_for_budget(run.results["blocks"], 1)
    assert len(blocks) == 299  # sentinel row excluded
    for table in (exports.blocks_table(blocks, "g/t"), exports.summary_table(s, "g/t")):
        text = exports.csv_bytes(table).decode()
        assert text.startswith("# Planning estimate")
    assert "metal_kg" in exports.blocks_table(blocks, "g/t").columns
    assert {"x", "y", "z"} <= set(run.results["blocks"].columns)  # for the 3D view
    assert run.settings["run_info"]["assumptions"]  # drilling assumptions reach the results


def test_11_scenario_reproducibility(tmp_path):
    p = _project(tmp_path)
    first = run_scenario(p, "Repro")
    stored_settings, _stored_results = p.load_scenario(first.scenario_id)
    assert stored_settings == first.settings
    again = run_scenario(p, "Repro", settings=stored_settings)
    for key in ("summary", "holes", "blocks", "comparison"):
        pd.testing.assert_frame_equal(first.results[key], again.results[key])
    strip = ("created", "run_info")
    assert ({k: v for k, v in first.settings.items() if k not in strip}
            == {k: v for k, v in again.settings.items() if k not in strip})
    assert not p.is_stale(stored_settings)


def test_14_stale_after_input_replaced(tmp_path):
    p = _project(tmp_path)
    run = run_scenario(p, "Stale check")
    sites = p.load_input("sites")
    sites.loc[0, "E"] += 10
    p.save_input("sites", _csv(sites), "SYNTHETIC_sites_v2.csv")
    assert p.is_stale(run.settings)
    rerun = run_scenario(p, "Stale check", settings=run.settings, scenario_id=run.scenario_id)
    assert rerun.scenario_id == run.scenario_id
    assert not p.is_stale(rerun.settings)
    assert [s["id"] for s in p.list_scenarios()] == [run.scenario_id]


def test_replaced_file_with_other_headers_is_a_plain_error(tmp_path):
    p = _project(tmp_path)
    sites = p.load_input("sites").rename(columns={"E": "EASTING"})
    p.save_input("sites", _csv(sites), "SYNTHETIC_sites_renamed.csv")
    with pytest.raises(ValueError, match="no column named E"):
        run_scenario(p, "Broken mapping")
