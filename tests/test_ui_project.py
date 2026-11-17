"""Smoke tests for pages/1_Project.py using Streamlit's AppTest (synthetic data only)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from engine.storage import Project

ROOT = Path(__file__).resolve().parents[1]
PAGE = str(ROOT / "pages" / "1_Project.py")
DATA = ROOT / "data" / "test"

BLOCKS = {
    "columns": {"x": "XC", "y": "YC", "z": "ZC", "dx": "XINC", "dy": "YINC", "dz": "ZINC",
                "density": "DENSITY", "class_raw": "RESCAT", "grade": "AU_GPT",
                "block_id": "BLOCKID", "domain": "DOMAIN", "parent_id": "PARENT"},
    "constant_dims": {}, "grade_unit": "g/t",
    "class_map": {"1": 3, "2": 2, "3": 1}, "null_sentinels": [-99.0, -999.0], "domains": [],
}
DRILLING_A = {"route": "A", "mapping": {"hole_id": "HOLEID", "x": "X", "y": "Y", "z": "Z",
                                        "valid": "VALID"}}
SITES = {"columns": {"site_id": "SITEID", "x": "EAST", "y": "NORTH", "z": "RL"}}


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    """Point ui_common at a temporary projects folder, however it was first imported."""
    import ui_common

    monkeypatch.setenv("INFILL_PROJECTS_DIR", str(tmp_path))
    importlib.reload(ui_common)
    monkeypatch.setattr(ui_common, "PROJECTS_DIR", tmp_path)
    return tmp_path


def _run(project_path: Path | None = None) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=60)
    if project_path is not None:
        at.session_state["project_path"] = str(project_path)
    return at.run()


def _populated(projects_dir: Path) -> Project:
    p = Project.create(projects_dir, "Demo")
    for kind, name in [("blocks", "SYNTHETIC_blocks.csv"),
                       ("drilling", "SYNTHETIC_drilling_routeA.csv"),
                       ("sites", "SYNTHETIC_sites.csv")]:
        p.save_input(kind, (DATA / name).read_bytes(), name)
    p.save_settings({**p.settings, "blocks": BLOCKS, "drilling": DRILLING_A, "sites": SITES})
    return p


def test_renders_without_project(projects_dir):
    at = _run()
    assert not at.exception
    assert any("Open or create a project" in i.value for i in at.info)


def test_create_project_and_duplicate_error(projects_dir):
    at = _run()
    at.text_input(key="new_project_name").set_value("My Project")
    at.button[0].click()
    at.run()
    assert not at.exception
    assert Project.list_projects(projects_dir) == ["My Project"]
    assert at.session_state["project_path"] == str(projects_dir / "My Project")

    at2 = _run()
    at2.text_input(key="new_project_name").set_value("My Project")
    at2.button[0].click()
    at2.run()
    assert not at2.exception
    assert any("already exists" in e.value for e in at2.error)


def test_mapping_prefilled_from_saved_settings(projects_dir):
    p = _populated(projects_dir)
    at = _run(p.root)
    assert not at.exception
    assert at.selectbox(key="Demo|blk|x").value == "XC"
    assert at.selectbox(key="Demo|blk|grade").value == "AU_GPT"
    assert at.selectbox(key="Demo|cls|2").value == "Indicated"
    assert at.text_input(key="Demo|sentinels").value == "-99, -999"


def test_guesses_when_nothing_saved(projects_dir):
    p = Project.create(projects_dir, "Fresh")
    p.save_input("blocks", (DATA / "SYNTHETIC_blocks.csv").read_bytes(), "SYNTHETIC_blocks.csv")
    at = _run(p.root)
    assert not at.exception
    assert at.selectbox(key="Fresh|blk|x").value == "XC"
    assert at.selectbox(key="Fresh|blk|density").value == "DENSITY"
    assert at.selectbox(key="Fresh|cls|1").value == "Measured"


def test_save_mappings_keeps_locked_list(projects_dir):
    p = _populated(projects_dir)
    p.save_input("manual", (DATA / "SYNTHETIC_manual_plan.csv").read_bytes(), "m.csv")
    p.save_settings({**p.settings, "manual": {
        "columns": {"hole_id": "HOLEID", "x": "EAST", "y": "NORTH", "z": "RL",
                    "azimuth": "AZIMUTH", "dip": "DIP", "length": "LENGTH"},
        "positive_down": True, "match_tolerance": 1.0, "locked": ["MAN01"]}})
    at = _run(p.root)
    at.button[-1].click()  # Save mappings is the last button
    at.run()
    assert not at.exception
    saved = json.loads((p.root / "project.json").read_text(encoding="utf-8"))
    assert saved["manual"]["locked"] == ["MAN01"]
    assert saved["blocks"]["columns"]["x"] == "XC"
    assert saved["blocks"]["class_map"] == {"1": 3, "2": 2, "3": 1}
    assert saved["drilling"]["mapping"]["hole_id"] == "HOLEID"


def test_preview_shows_tonnes_table_and_baseline(projects_dir):
    p = _populated(projects_dir)
    at = _run(p.root)
    assert not at.exception
    assert not at.error
    frames = [d.value for d in at.dataframe]
    assert any("Tonnes (t)" in f.columns and "Metal (kg)" in f.columns for f in frames)
    assert any("Baseline geometry class" in f.columns for f in frames)
    labels = [m.label for m in at.metric]
    assert any("Baseline discrepancy" in lab for lab in labels)


def test_route_b_preview(projects_dir):
    p = Project.create(projects_dir, "RouteB")
    for kind, name in [("blocks", "SYNTHETIC_blocks.csv"), ("collars", "SYNTHETIC_collars.csv"),
                       ("surveys", "SYNTHETIC_surveys.csv"), ("sites", "SYNTHETIC_sites.csv")]:
        p.save_input(kind, (DATA / name).read_bytes(), name)
    drilling = {"route": "B", "positive_down": False,
                "collars": {"hole_id": "HOLEID", "x": "EAST", "y": "NORTH", "z": "RL",
                            "max_depth": "DEPTH"},
                "surveys": {"hole_id": "HOLEID", "depth": "SURVDEPTH", "azimuth": "AZIMUTH",
                            "dip": "DIP"}}
    p.save_settings({**p.settings, "blocks": BLOCKS, "drilling": drilling, "sites": SITES})
    at = _run(p.root)
    assert not at.exception
    assert not at.error
    assert any("Baseline geometry class" in d.value.columns for d in at.dataframe)
    assert any("trace points were generated" in c.value for c in at.caption)
