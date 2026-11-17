"""Planning page: classes, thresholds, candidate ranges, budgets, costs and run settings.

The page only collects inputs and shows outputs. Every calculation is an engine call.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import streamlit as st

import ui_common
from engine import candidates, evaluate, pipeline
from engine.candidates import CandidateSettings, Range
from engine.geometry import Thresholds
from engine.schema import GEOMETRY_LABELS, UPLOADED_LABELS, ClassRank
from engine.storage import Project

RANKS = [ClassRank.MEASURED, ClassRank.INDICATED, ClassRank.INFERRED]
MODE_HELP = {
    "independent": "Each budget is optimised on its own. Budgets run in ascending order and "
                   "each also tries the previous budget's plan as a starting point, so "
                   "conversion never falls as budget rises.",
    "expandable": "The lower-budget campaign is locked and holes are added as the budget "
                  "increases.",
}


# --------------------------------------------------------------------------- helpers

def merged_planning(stored: dict | None) -> dict:
    """Stored planning settings laid over the defaults, so every default key is present."""
    out = pipeline.default_planning()
    for k, v in (stored or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def parse_budgets(text: str) -> list[float]:
    """Comma-separated budgets; spaces and underscores group digits ("500 000, 1_000_000")."""
    parts = [p for p in text.split(",") if p.strip()]
    if not parts:
        raise ValueError("Enter at least one budget.")
    out = []
    for p in parts:
        clean = re.sub(r"[\s_ ]", "", p)
        try:
            v = float(clean)
        except ValueError:
            raise ValueError(f"'{p.strip()}' is not a number.") from None
        if not 0 < v < float("inf"):
            raise ValueError(f"Budget '{p.strip()}' must be a positive number.")
        out.append(v)
    return out


def format_budgets(budgets) -> str:
    return ", ".join(f"{b:.0f}" if float(b).is_integer() else f"{b:g}" for b in budgets)


@st.cache_resource(show_spinner="Preparing block and drilling geometry...", max_entries=2)
def cached_context(path: str, inputs_json: str, settings_json: str):
    """Selected blocks and baseline, keyed on project path, input files, saved mappings
    and the planning settings that change the geometry."""
    planning = json.loads(settings_json)
    return pipeline.build_project_context(Project.open(Path(path)), planning=planning)


@st.cache_resource(show_spinner="Counting candidate holes...")
def cached_candidate_count(path: str, inputs_json: str, cand_json: str) -> int:
    p = Project.open(Path(path))
    cs = pipeline.candidate_settings_of({"candidates": json.loads(cand_json)})
    return len(candidates.generate_candidates(pipeline.load_sites(p), cs))


def range_inputs(label: str, key: str, cur: list[float], unit: str) -> list[float]:
    st.markdown(f"**{label}** ({unit})")
    c1, c2, c3 = st.columns(3)
    lo = c1.number_input("Minimum", value=float(cur[0]), key=f"{key}_min")
    hi = c2.number_input("Maximum", value=float(cur[1]), key=f"{key}_max")
    step = c3.number_input("Increment", value=float(cur[2]), min_value=0.0, key=f"{key}_step")
    return [lo, hi, step]


# --------------------------------------------------------------------------- page

ui_common.page_setup("Planning")
p = ui_common.require_project()
ui_common.require_setup(p)

plan = merged_planning(p.settings.get("planning"))
errors: list[str] = []

# 1. Classes
st.subheader("Classes")
c1, c2 = st.columns(2)
source = c1.selectbox("Source class (as uploaded)", RANKS, key="source_class",
                      index=RANKS.index(ClassRank(plan["source_class"])),
                      format_func=lambda r: UPLOADED_LABELS[r])
target = c2.selectbox("Target geometry class", RANKS, key="target_class",
                      index=RANKS.index(ClassRank(plan["target_class"])),
                      format_func=lambda r: GEOMETRY_LABELS[r])
if target <= source:
    errors.append("The target geometry class must rank above the source class.")
    st.error(errors[-1])

# 2. Thresholds
st.subheader("Geometry thresholds")
t1, t2, t3 = st.columns(3)
th_vals = {
    "measured": t1.number_input("Measured geometry (m)",
                                value=float(plan["thresholds"]["measured"]),
                                min_value=0.0, key="th_measured"),
    "indicated": t2.number_input("Indicated geometry (m)",
                                 value=float(plan["thresholds"]["indicated"]),
                                 min_value=0.0, key="th_indicated"),
    "inferred": t3.number_input("Inferred geometry (m)",
                                value=float(plan["thresholds"]["inferred"]),
                                min_value=0.0, key="th_inferred"),
}
thresholds = None
try:
    thresholds = Thresholds(**th_vals)
except ValueError as exc:
    errors.append(str(exc))
    st.error(str(exc))

# 3. Candidate ranges
st.subheader("Candidate holes")
cand_plan = {
    "azimuth": range_inputs("Azimuth", "az", plan["candidates"]["azimuth"], "degrees"),
    "dip": range_inputs("Dip, negative is down", "dip", plan["candidates"]["dip"], "degrees"),
    "length": range_inputs("Length", "len", plan["candidates"]["length"], "metres"),
}
cand_settings = None
try:
    cand_settings = CandidateSettings(*(Range(*cand_plan[k]) for k in ("azimuth", "dip",
                                                                       "length")))
    for r in (cand_settings.azimuth, cand_settings.dip, cand_settings.length):
        candidates.range_values(r)
except ValueError as exc:
    errors.append(f"Candidate ranges: {exc}")
    st.error(errors[-1])
    cand_settings = None

# 6. Advanced (read now: support interval and rules feed the size estimate and warnings)
opt = plan["optimiser"]
with st.expander("Advanced"):
    a1, a2, a3 = st.columns(3)
    support_interval = a1.number_input("Support interval (m)", min_value=0.1,
                                       value=float(plan["support_interval"]), key="support")
    min_angle = a2.number_input("Minimum angular separation at one site (degrees, 0 disables)",
                                min_value=0.0, max_value=180.0, value=float(opt["min_angle"]),
                                key="min_angle")
    site_cap = a3.number_input("Maximum holes per site", min_value=1, step=1,
                               value=int(opt["site_cap"]), key="site_cap")
    b1, b2, b3 = st.columns(3)
    restarts = b1.number_input("Restarts", min_value=1, step=1, value=int(opt["restarts"]),
                               key="restarts")
    seed = b2.number_input("Random seed", step=1, value=int(opt["seed"]), key="seed")
    time_limit = b3.number_input("Time limit per budget (s)", min_value=1.0,
                                 value=float(opt["time_limit_s"]), key="time_limit")
    d1, d2, d3 = st.columns(3)
    pair_shortlist = d1.number_input("Pair shortlist size", min_value=0, step=1,
                                     value=int(opt["pair_shortlist"]), key="pair_shortlist")
    pair_neighbours = d2.number_input("Nearest candidates per block for pairs", min_value=1,
                                      step=1, value=int(opt["pair_neighbours"]),
                                      key="pair_neighbours")
    passes = d3.number_input("Local search pass limit", min_value=0, step=1,
                             value=int(opt["local_search_passes"]), key="passes")

# 4. Budgets, mode, costs
st.subheader("Budgets and costs")
budget_text = st.text_input("Budgets (comma-separated; spaces or underscores may group digits)",
                            value=format_budgets(plan["budgets"]), key="budgets")
budgets: list[float] = []
try:
    budgets = parse_budgets(budget_text)
except ValueError as exc:
    errors.append(f"Budgets: {exc}")
    st.error(errors[-1])
mode_label = {"independent": "Independent", "expandable": "Expandable"}
mode = st.radio("Mode", list(mode_label), key="mode", horizontal=True,
                index=list(mode_label).index(plan["mode"]),
                format_func=lambda m: mode_label[m])
st.caption(MODE_HELP[mode])
k1, k2, k3 = st.columns(3)
cost = {
    "cost_per_metre": k1.number_input("Cost per metre", min_value=0.0, key="cost_m",
                                      value=float(plan["cost"]["cost_per_metre"])),
    "fixed_per_hole": k2.number_input("Fixed cost per hole", min_value=0.0, key="cost_hole",
                                      value=float(plan["cost"]["fixed_per_hole"])),
    "setup_per_site": k3.number_input("Setup cost per site", min_value=0.0, key="cost_site",
                                      value=float(plan["cost"]["setup_per_site"])),
}

new_plan = copy.deepcopy(plan)
new_plan.update(
    source_class=int(source), target_class=int(target), thresholds=th_vals,
    candidates=cand_plan, budgets=budgets, mode=mode, cost=cost,
    support_interval=float(support_interval))
new_plan["optimiser"].update(
    restarts=int(restarts), seed=int(seed), pair_shortlist=int(pair_shortlist),
    pair_neighbours=int(pair_neighbours), local_search_passes=int(passes),
    time_limit_s=float(time_limit), min_angle=float(min_angle), site_cap=int(site_cap))

# Live candidate count and size estimate
sites = None
try:
    sites = pipeline.load_sites(p)
except ValueError as exc:
    errors.append(str(exc))
    st.error(str(exc))

if cand_settings is not None and sites is not None:
    # Mappings are part of the key: a new domain filter or column choice on the Project
    # page changes the eligible blocks without changing any file.
    inputs_json = json.dumps({"hashes": p.input_hashes(),
                              **{k: p.settings.get(k) for k in ("blocks", "drilling", "sites")}},
                             sort_keys=True)
    n_cand = cached_candidate_count(str(p.root), inputs_json, json.dumps(cand_plan))
    st.metric("Candidate holes", f"{n_cand:,}")
    if thresholds is not None and target > source:
        ctx_json = json.dumps({k: new_plan[k] for k in (
            "source_class", "target_class", "thresholds", "cost", "support_interval")},
            sort_keys=True)
        try:
            ctx = cached_context(str(p.root), inputs_json, ctx_json)
        except ValueError as exc:
            errors.append(str(exc))
            st.error(str(exc))
        else:
            est = candidates.estimate_size(n_cand, ctx.xyz[ctx.eligible], cand_settings,
                                           3.0 * thresholds.for_rank(target))
            st.caption(f"Eligible blocks: {int(ctx.eligible.sum()):,}. Estimated working "
                       f"memory for the candidate distance table: up to "
                       f"{est.est_bytes / 1024**2:,.0f} MB (about {est.est_entries:,} entries).")
            for w in est.warnings:
                st.warning(w)

# 5. Manual plan
manual_locked: list[str] | None = None
manual_cfg = p.settings.get("manual")
if manual_cfg and p.load_input("manual") is not None and sites is not None:
    st.subheader("Manual plan")
    try:
        manual = pipeline.load_manual(p, sites)
    except ValueError as exc:
        manual = None
        errors.append(f"Manual plan: {exc}")
        st.error(errors[-1])
    if manual is not None:
        use_manual = st.checkbox("Compare the manual plan with an optimised plan",
                                 key="use_manual", value=bool(plan.get("use_manual", True)))
        new_plan["use_manual"] = bool(use_manual)
        st.caption("Locked holes are always included in the optimised plans. "
                   "The manual plan itself is evaluated unchanged.")
        edited = st.data_editor(manual, key="manual_table", hide_index=True,
                                disabled=[c for c in manual.columns if c != "locked"],
                                column_config={"locked": st.column_config.CheckboxColumn(
                                    "Locked")})
        manual_locked = [str(h) for h in edited.loc[edited["locked"].astype(bool), "hole_id"]]
        for w in evaluate.plan_warnings(manual, float(min_angle), int(site_cap)):
            st.warning(w)

# 7. Run
st.subheader("Run")
name = st.text_input("Scenario name", value="Scenario 1", key="scenario_name")
if not name.strip():
    errors.append("Enter a scenario name.")
    st.error(errors[-1])
run_clicked = st.button("Run", type="primary", disabled=bool(errors), key="run")
st.caption("Large runs can take several minutes per budget.")

if run_clicked:
    bar = st.progress(0.0)
    status = st.empty()

    def progress(msg: str, frac: float) -> None:
        bar.progress(min(max(float(frac), 0.0), 1.0))
        status.text(msg)

    try:
        settings = copy.deepcopy(p.settings)
        settings["planning"] = new_plan
        if manual_locked is not None:
            settings["manual"] = {**settings["manual"], "locked": manual_locked}
        p.save_settings(settings)
        p.settings = settings
        run = pipeline.run_scenario(p, name.strip(), progress=progress)
    except (ValueError, FileNotFoundError) as exc:
        status.empty()
        st.error(str(exc))
    else:
        st.session_state["scenario_id"] = run.scenario_id
        st.success(f"Scenario '{name.strip()}' is saved. Open the Results page to see the "
                   "best-found plans and potentially converted tonnes.")
        try:
            st.page_link("pages/3_Results.py", label="Go to Results")
        except Exception:  # noqa: BLE001 - the link is a convenience only
            st.caption("Open the Results page from the sidebar.")
