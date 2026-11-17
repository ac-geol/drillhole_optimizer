"""Shared Streamlit helpers for the pages. UI only: no calculations live here."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from engine import DISCLAIMER
from engine.schema import GEOMETRY_LABELS, UPLOADED_LABELS, ClassRank
from engine.storage import Project
from engine.units import GradeUnit, metal_unit

PROJECTS_DIR = Path(os.environ.get("INFILL_PROJECTS_DIR",
                                   Path(__file__).resolve().parent / "projects"))

SUPPORT_ASSUMPTION = ("Proposed holes are assumed to provide valid sampling along their full "
                      "length.")

LIMITATIONS = [
    ("No directional test: three holes on one side of a block satisfy the metric. The angular "
    "separation rule reduces the worst case but does not replace a coverage test."),
    ("Centroid only: a block is judged at its centroid. Where blocks are large relative to the "
    "thresholds, the class is coarse."),
    ("Full-length support: planned holes count as sampled from collar to toe, including any "
    "waste or cover they pass through."),
    ("Greedy bias: the search prefers moves that convert metal now over moves that set up a "
    "larger gain later. Pair moves and restarts reduce this, not remove it."),
    "Straight holes: no deviation is modelled for planned holes.",
    ("Light validation: overlapping block records, mixed coordinate systems and duplicate hole "
    "IDs are not detected."),
]


def page_setup(title: str) -> None:
    st.set_page_config(page_title=f"{title} · Infill Drilling Budget Optimiser", layout="wide")
    st.title(title)
    p = current_project()
    if p is not None:
        st.sidebar.markdown(f"**Project:** {p.settings.get('name', p.root.name)}")
        sid = st.session_state.get("scenario_id")
        if sid:
            st.sidebar.markdown(f"**Scenario:** {sid}")


def current_project() -> Project | None:
    path = st.session_state.get("project_path")
    if not path:
        return None
    try:
        return Project.open(Path(path))
    except FileNotFoundError:
        st.session_state.pop("project_path", None)
        return None


def set_project(project: Project | None) -> None:
    st.session_state["project_path"] = str(project.root) if project else None
    st.session_state.pop("scenario_id", None)


def require_project() -> Project:
    """Stop the page with a plain message if no project is open."""
    p = current_project()
    if p is None:
        st.info("Open or create a project on the **Project** page first.")
        st.stop()
    return p


def missing_steps(project: Project) -> list[str]:
    """Plain-English list of setup steps not yet done, for prerequisite messages."""
    s, inputs = project.settings, project.input_hashes()
    out = []
    if "blocks" not in inputs:
        out.append("Upload a block model on the Project page.")
    elif not s.get("blocks", {}).get("columns"):
        out.append("Map the block model columns on the Project page.")
    route = s.get("drilling", {}).get("route", "A")
    needed = ["drilling"] if route == "A" else ["collars", "surveys"]
    if any(k not in inputs for k in needed):
        out.append("Upload existing drilling on the Project page.")
    elif not s.get("drilling"):
        out.append("Map the drilling columns on the Project page.")
    if "sites" not in inputs:
        out.append("Upload potential drill sites on the Project page.")
    elif not s.get("sites", {}).get("columns"):
        out.append("Map the drill site columns on the Project page.")
    return out


def require_setup(project: Project) -> None:
    steps = missing_steps(project)
    if steps:
        st.info("Before this page can be used:\n\n" + "\n".join(f"- {x}" for x in steps))
        st.stop()


def disclaimer() -> None:
    """Standard disclaimer and support assumption, shown on every results screen."""
    st.caption(f"⚠️ {DISCLAIMER}  \n{SUPPORT_ASSUMPTION}")


def uploaded_label(rank) -> str:
    return UPLOADED_LABELS[ClassRank(int(rank))]


def geometry_label(rank) -> str:
    return GEOMETRY_LABELS[ClassRank(int(rank))]


def metal_label(settings: dict) -> str:
    """'t' or 'kg' for the project's grade unit."""
    return metal_unit(GradeUnit(settings.get("blocks", {}).get("grade_unit", "%")))
