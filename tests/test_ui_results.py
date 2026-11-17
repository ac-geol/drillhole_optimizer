"""UI smoke tests for the Results and Scenarios pages. All data is SYNTHETIC."""

import importlib
import os
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from engine import DISCLAIMER
from engine.pipeline import run_scenario
from engine.storage import Project
from tests.test_pipeline import _csv, _project

TIMEOUT = 60
PAGES = Path(__file__).resolve().parent.parent / "pages"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("projects")
    os.environ["INFILL_PROJECTS_DIR"] = str(tmp)
    import ui_common
    importlib.reload(ui_common)
    p = _project(tmp)
    p.settings["planning"]["optimiser"]["restarts"] = 1
    p.save_settings(p.settings)
    first = run_scenario(p, "Base case")
    second = run_scenario(p, "Second case", settings={**p.settings, "planning": {
        **p.settings["planning"], "budgets": [90_000.0]}})
    return p, first.scenario_id, second.scenario_id


def _app(page, p, sid=None):
    at = AppTest.from_file(str(page), default_timeout=TIMEOUT)
    at.session_state["project_path"] = str(p.root)
    if sid:
        at.session_state["scenario_id"] = sid
    return at.run()


def _text(at):
    return " ".join(x.value for x in at.markdown) + " " + " ".join(x.value for x in at.caption)


def test_results_fresh(built):
    p, sid, _ = built
    at = _app(PAGES / "3_Results.py", p, sid)
    assert not at.exception
    assert len(at.metric) > 0
    assert DISCLAIMER in _text(at)
    assert "(STALE)" not in " ".join(x.value for x in at.subheader)


def test_duplicate_without_results(built):
    p, sid, _ = built
    new = p.duplicate_scenario(sid, "Dup")
    at = _app(PAGES / "3_Results.py", p, new)
    assert not at.exception
    assert any("no results yet" in i.value for i in at.info)


def test_results_stale(built, tmp_path):
    p, sid, _ = built
    root = tmp_path / "stale_copy"
    shutil.copytree(p.root, root)
    q = Project.open(root)
    sites = q.load_input("sites")
    sites.loc[0, "E"] += 10
    q.save_input("sites", _csv(sites), "SYNTHETIC_sites_v2.csv")
    at = _app(PAGES / "3_Results.py", q, sid)
    assert not at.exception
    assert any("Stale" in w.value for w in at.warning)
    assert "(STALE)" in " ".join(x.value for x in at.subheader)


def test_scenarios_compare(built):
    p, sid, sid2 = built
    at = _app(PAGES / "4_Scenarios.py", p)
    assert not at.exception
    at.multiselect[0].set_value([sid, sid2]).run()
    assert not at.exception
    assert len(at.dataframe) >= 2
