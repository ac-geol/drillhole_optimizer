"""Results page: summary metrics, budget curve, manual vs optimised, holes, 3D view, downloads.

Display only. Every number comes from the saved scenario; nothing is recalculated here.
"""

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ui_common
from engine import exports, pipeline
from engine.costs import CostModel
from engine.holes import direction
from engine.scenarios import COMPARISON_NOTE
from engine.storage import Project, safe_name

MAX_POINTS = 30_000
SEED = 12345

ui_common.page_setup("Results")
p = ui_common.require_project()

scenarios = p.list_scenarios()
if not scenarios:
    st.info("No scenarios yet. Run a scenario on the **Planning** page first.")
    st.stop()

ids = [s["id"] for s in scenarios]
default = st.session_state.get("scenario_id")
index = ids.index(default) if default in ids else len(ids) - 1
by_id = {s["id"]: s for s in scenarios}
sid = st.selectbox("Scenario", ids, index=index,
                   format_func=lambda i: f"{by_id[i]['name']} ({by_id[i]['created'] or i})")
st.session_state["scenario_id"] = sid
settings, results = p.load_scenario(sid)
planning = settings.get("planning", {})
stale = p.is_stale(settings)
unit = ui_common.metal_label(settings)
grade_unit = settings.get("blocks", {}).get("grade_unit", "%")


def recalculate_button(key: str) -> None:
    if st.button("Recalculate", key=key, type="primary"):
        bar = st.progress(0.0)
        run = pipeline.run_scenario(
            p, settings.get("name", "Scenario"), settings=settings, scenario_id=sid,
            progress=lambda msg, frac: bar.progress(min(frac, 1.0), text=msg))
        st.session_state["scenario_id"] = run.scenario_id
        st.rerun()


def section(title: str) -> None:
    st.subheader(f"{title} (STALE)" if stale else title)


ui_common.disclaimer()
if stale:
    st.warning("Stale, recalculate. An input file changed after this scenario was run, so "
               "the results below no longer match the project's data. They are shown for "
               "reference only.")
    recalculate_button("recalc_stale")

summary = results.get("summary")
if summary is None or summary.empty:
    st.info("This scenario has no results yet (for example it was duplicated and not run). "
            "Recalculate to produce them.")
    if not stale:
        recalculate_button("recalc_empty")
    st.stop()

run_info = settings.get("run_info", {})


# --------------------------------------------------------------------------- cached loads

def _hashes_key() -> str:
    return json.dumps(settings.get("input_hashes", {}), sort_keys=True)


@st.cache_data(show_spinner=False)
def cached_blocks(path: str, scenario: str, hashes: str) -> pd.DataFrame:
    proj = Project.open(path)
    s, _ = proj.load_scenario(scenario)
    return pipeline.load_blocks(proj, s)[1][["block_id", "x", "y", "z"]]


@st.cache_data(show_spinner=False)
def cached_drilling(path: str, scenario: str, hashes: str, interval: float) -> pd.DataFrame:
    proj = Project.open(path)
    s, _ = proj.load_scenario(scenario)
    return pipeline.load_drilling(proj, s, interval).points


@st.cache_data(show_spinner=False)
def cached_sites(path: str, scenario: str, hashes: str) -> pd.DataFrame:
    proj = Project.open(path)
    s, _ = proj.load_scenario(scenario)
    return pipeline.load_sites(proj, s)


def downsample(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) <= MAX_POINTS:
        return df
    return df.sample(n=MAX_POINTS, random_state=SEED)


# --------------------------------------------------------------------------- 1. summary

section("Summary")
budgets = list(summary["budget"])
bi = st.selectbox("Budget", range(len(budgets)), index=len(budgets) - 1,
                  format_func=lambda i: f"{budgets[i]:,.0f}")
row = summary.iloc[bi]
c = st.columns(4)
c[0].metric("Budget", f"{row['budget']:,.0f}")
c[1].metric("Planned cost", f"{row['planned_cost']:,.0f}")
c[2].metric("Remaining budget", f"{row['remaining_budget']:,.0f}")
c[3].metric("Metres", f"{row['metres']:,.0f}")
c = st.columns(4)
c[0].metric("Holes", f"{int(row['holes'])}")
c[1].metric("Sites", f"{int(row['sites'])}")
c[2].metric("Potentially converted tonnes (t)", f"{row['converted_tonnes']:,.0f}")
c[3].metric(f"Potentially converted metal ({unit})", f"{row['converted_metal']:,.1f}")
c = st.columns(2)
c[0].metric(f"Metal per metre ({unit}/m)", f"{row['metal_per_metre']:,.3f}")
c[1].metric(f"Metal per unit cost ({unit}/cost)", f"{row['metal_per_cost']:,.5f}")
overrun = float(row.get("locked_overrun", 0) or 0)
if overrun > 0:
    st.warning(f"Locked holes exceed this budget by {overrun:,.0f}; no holes were added.")
c = st.columns(2)
c[0].metric(f"Eligible metal ({unit})", f"{run_info.get('eligible_metal', 0):,.1f}")
c[1].metric(f"Baseline discrepancy metal ({unit})",
            f"{run_info.get('discrepancy_metal', 0):,.1f}")
st.caption("Baseline discrepancy is metal in blocks of the source class whose existing "
           "drilling already meets the target geometry class. It is reported separately and is "
           "never counted as conversion.")

# --------------------------------------------------------------------------- 2. curve

section("Budget vs potentially converted metal")
fig = go.Figure(go.Scatter(x=summary["budget"], y=summary["converted_metal"],
                           mode="lines+markers",
                           line={"color": "#9aa0a6" if stale else "#1f77b4"}))
fig.update_layout(xaxis_title="Budget", yaxis_title=f"Potentially converted metal ({unit})",
                  margin={"t": 20})
st.plotly_chart(fig, use_container_width=True)

# --------------------------------------------------------------------------- 3. comparison

comparison = results.get("comparison")
if comparison is not None and len(comparison):
    section("Manual vs optimised")
    st.dataframe(comparison, hide_index=True, use_container_width=True)
    st.caption(COMPARISON_NOTE)

# --------------------------------------------------------------------------- 4. holes

holes_all = results.get("holes", pd.DataFrame())
section("Selected holes")
holes = holes_all[holes_all["budget"] == row["budget"]] if len(holes_all) else holes_all
if len(holes):
    shown = holes.drop(columns=["budget"]).reset_index(drop=True)
    shown["locked"] = shown["locked"].map({True: "Locked", False: ""})
    st.dataframe(shown, hide_index=True, use_container_width=True)
else:
    st.caption("No holes were selected for this budget.")

# --------------------------------------------------------------------------- 5. 3D view

section("3D view")
wide = results.get("blocks", pd.DataFrame())
path = str(p.root)
interval = float(planning.get("support_interval", 2.0))
cols = st.columns(5)
show_target = cols[0].checkbox("Target blocks", value=True)
show_conv = cols[1].checkbox("Potentially converted blocks", value=True)
show_drill = cols[2].checkbox("Existing drilling", value=False)
show_sites = cols[3].checkbox("Available sites", value=False)
show_holes = cols[4].checkbox("Selected planned holes", value=True)

traces, captions = [], []
try:
    if (show_target or show_conv) and len(wide):
        xyz = cached_blocks(path, sid, _hashes_key())
        j = xyz.merge(wide[["block_id", "eligible", f"converted_{bi}"]], on="block_id")
        for flag, mask, name, colour in (
                (show_target, j["eligible"].astype(bool), "Target blocks", "#bbbbbb"),
                (show_conv, j[f"converted_{bi}"].astype(bool), "Potentially converted blocks",
                 "#d62728")):
            if not flag:
                continue
            full = j[mask]
            part = downsample(full)
            captions.append(f"{name}: showing {len(part):,} of {len(full):,} blocks")
            traces.append(go.Scatter3d(x=part["x"], y=part["y"], z=part["z"], mode="markers",
                                       name=name, marker={"size": 2, "color": colour,
                                                          "opacity": 0.5}))
    if show_drill:
        pts = cached_drilling(path, sid, _hashes_key(), interval)
        part = downsample(pts)
        captions.append(f"Existing drilling: showing {len(part):,} of {len(pts):,} points")
        traces.append(go.Scatter3d(x=part["x"], y=part["y"], z=part["z"], mode="markers",
                                   name="Existing drilling",
                                   marker={"size": 1.5, "color": "#2ca02c"}))
    if show_sites:
        sites = cached_sites(path, sid, _hashes_key())
        traces.append(go.Scatter3d(x=sites["x"], y=sites["y"], z=sites["z"], mode="markers",
                                   name="Available sites",
                                   marker={"size": 3, "color": "#ff7f0e", "symbol": "diamond"}))
except (ValueError, KeyError, OSError) as exc:  # inputs may have been replaced or become unreadable
    st.warning(f"Some 3D layers could not be loaded from the project inputs: {exc}")
if show_holes and len(holes):
    h = holes.reset_index(drop=True)
    start = h[["x", "y", "z"]].to_numpy(float)
    end = start + direction(h["azimuth"], h["dip"]) * h["length"].to_numpy(float)[:, None]
    lx, ly, lz = [], [], []
    for a, b in zip(start, end, strict=True):
        lx += [a[0], b[0], None]
        ly += [a[1], b[1], None]
        lz += [a[2], b[2], None]
    traces.append(go.Scatter3d(x=lx, y=ly, z=lz, mode="lines", name="Selected planned holes",
                               line={"color": "#1f77b4", "width": 4}))
fig3 = go.Figure(traces)
fig3.update_layout(scene={"aspectmode": "data"}, margin={"t": 10, "l": 0, "r": 0, "b": 0},
                   height=600)
st.plotly_chart(fig3, use_container_width=True)
for text in captions:
    st.caption(f"{text}. Numbers above always use the full dataset.")

# --------------------------------------------------------------------------- 6. downloads

section("Downloads")
base = safe_name(settings.get("name", "scenario"))
cost_model = CostModel(**planning["cost"]) if planning.get("cost") else CostModel(0.0)
d = st.columns(3)
d[0].download_button("Selected planned holes (CSV)",
                     exports.csv_bytes(exports.holes_table(holes_all, cost_model)),
                     file_name=safe_name(f"{base}_holes.csv"), mime="text/csv")
d[1].download_button("Budget scenario summary (CSV)",
                     exports.csv_bytes(exports.summary_table(summary, grade_unit)),
                     file_name=safe_name(f"{base}_summary.csv"), mime="text/csv")
if comparison is not None and len(comparison):
    d[2].download_button("Manual vs optimised (CSV)",
                         exports.csv_bytes(exports.comparison_table(comparison, grade_unit)),
                         file_name=safe_name(f"{base}_manual_vs_optimised.csv"),
                         mime="text/csv")
d = st.columns(2)
if len(wide):
    d[0].download_button("Block results for chosen budget (CSV)",
                         exports.csv_bytes(exports.blocks_table(
                             pipeline.blocks_for_budget(wide, bi), grade_unit)),
                         file_name=safe_name(f"{base}_blocks_budget_{int(row['budget'])}.csv"),
                         mime="text/csv")
d[1].download_button("Scenario settings (JSON)", exports.scenario_json_bytes(settings),
                     file_name=safe_name(f"{base}_settings.json"), mime="application/json")

# --------------------------------------------------------------------------- 7. details

with st.expander("Warnings"):
    warns = run_info.get("warnings", [])
    if warns:
        st.markdown("\n".join(f"- {w}" for w in warns))
    else:
        st.write("No warnings.")
with st.expander("Run log"):
    st.code("\n".join(run_info.get("log", [])) or "No log.", language=None)
with st.expander("Known limitations"):
    st.markdown("\n".join(f"- {x}" for x in ui_common.LIMITATIONS))
