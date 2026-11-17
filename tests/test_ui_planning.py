"""Smoke tests for the Planning page (AppTest). All data is SYNTHETIC."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from engine.storage import Project
from tests.test_pipeline import _project

PAGE = str(Path(__file__).resolve().parents[1] / "pages" / "2_Planning.py")


@pytest.fixture
def at(tmp_path, monkeypatch):
    monkeypatch.setenv("INFILL_PROJECTS_DIR", str(tmp_path))
    return AppTest.from_file(PAGE, default_timeout=60)


def _open(at, tmp_path) -> Project:
    p = _project(tmp_path)
    at.session_state["project_path"] = str(p.root)
    return p


def test_no_project(at):
    at.run()
    assert not at.exception
    assert any("Project" in i.value for i in at.info)


def test_renders_with_candidate_count(at, tmp_path):
    _open(at, tmp_path)
    at.run()
    assert not at.exception
    counts = [m for m in at.metric if m.label == "Candidate holes"]
    assert counts and int(counts[0].value.replace(",", "")) > 0
    assert not at.error


def test_invalid_thresholds(at, tmp_path):
    _open(at, tmp_path)
    at.run()
    at.number_input(key="th_measured").set_value(80.0).run()
    assert not at.exception
    assert any("increasing" in e.value for e in at.error)
    assert at.button(key="run").disabled


def test_run_sets_scenario(at, tmp_path):
    p = _open(at, tmp_path)
    at.run()
    at.text_input(key="budgets").set_value("60 000, 120_000")
    at.number_input(key="restarts").set_value(1)
    at.run()
    at.button(key="run").click().run()
    assert not at.exception
    assert not at.error
    assert at.session_state["scenario_id"]
    assert Project.open(p.root).settings["planning"]["budgets"] == [60000.0, 120000.0]
