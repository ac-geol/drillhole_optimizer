"""Scenarios page: list, load, duplicate, recalculate and compare saved scenarios."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ui_common
from engine import pipeline

ui_common.page_setup("Scenarios")
p = ui_common.require_project()

st.caption("A scenario is saved automatically when a run finishes. Recalculating a scenario "
           "re-runs it with its own stored settings and the current input files, and replaces "
           "its results.")

scenarios = p.list_scenarios()
if not scenarios:
    st.info("No scenarios yet. Run a scenario on the **Planning** page first.")
    st.stop()

ui_common.disclaimer()


def goto_results() -> None:
    try:
        st.page_link("pages/3_Results.py", label="Open the Results page")
    except st.errors.StreamlitAPIException:  # page links need the multipage app context
        st.write("Open the **Results** page from the sidebar.")


def recalculate(settings: dict, fallback_name: str, scenario_id: str):
    bar = st.progress(0.0)
    return pipeline.run_scenario(
        p, settings.get("name", fallback_name), settings=settings, scenario_id=scenario_id,
        progress=lambda msg, frac: bar.progress(min(frac, 1.0), text=msg))


# --------------------------------------------------------------------------- list

st.subheader("Saved scenarios")
for s in scenarios:
    sid = s["id"]
    settings, results = p.load_scenario(sid)
    has_results = "summary" in results and len(results["summary"]) > 0
    with st.container(border=True):
        flags = []
        if s["stale"]:
            flags.append("STALE")
        if not has_results:
            flags.append("no results")
        st.markdown(f"**{s['name']}**  \nCreated {s['created'] or 'not yet run'}"
                    + (f"  \n:orange[{', '.join(flags)}]" if flags else ""))
        c = st.columns([1, 2, 2])
        if c[0].button("Load", key=f"load_{sid}"):
            st.session_state["scenario_id"] = sid
            st.session_state["loaded_note"] = sid
        if c[1].button("Use these settings on the Planning page", key=f"use_{sid}",
                       help="Copies this scenario's planning settings into the project."):
            if settings.get("planning"):
                p.save_settings({**p.settings, "planning": settings["planning"]})
                st.success("Planning settings copied to the project.")
            else:
                st.warning("This scenario has no planning settings.")
        if st.session_state.get("loaded_note") == sid:
            st.success("Scenario loaded.")
            goto_results()
        dup_name = st.text_input("New name for a duplicate", value=f"{s['name']} copy",
                                 key=f"dupname_{sid}")
        if st.button("Duplicate", key=f"dup_{sid}",
                     help="Copies the settings only; the copy has no results until run."):
            if dup_name.strip():
                p.duplicate_scenario(sid, dup_name.strip())
                st.rerun()
            else:
                st.warning("Enter a name for the duplicate.")
        if (s["stale"] or not has_results) and st.button("Recalculate", key=f"recalc_{sid}"):
            run = recalculate(settings, s["name"], sid)
            st.session_state["scenario_id"] = run.scenario_id
            st.success("Recalculated with the current input files.")
            st.rerun()

# --------------------------------------------------------------------------- compare

st.subheader("Compare scenarios")
by_id = {s["id"]: s for s in scenarios}
chosen = st.multiselect("Scenarios to compare (two or more)", list(by_id),
                        format_func=lambda i: by_id[i]["name"]
                        + (" (STALE)" if by_id[i]["stale"] else ""))
if len(chosen) < 2:
    st.caption("Choose at least two scenarios.")
    st.stop()

loaded = {i: p.load_scenario(i) for i in chosen}
label = {i: by_id[i]["name"] + (" (STALE)" if by_id[i]["stale"] else "") for i in chosen}
stale_names = [by_id[i]["name"] for i in chosen if by_id[i]["stale"]]
if stale_names:
    st.warning("Stale scenarios in this comparison: " + ", ".join(stale_names)
               + ". Their inputs changed after they were run.")

frames = []
for i in chosen:
    summ = loaded[i][1].get("summary")
    if summ is not None and len(summ):
        frames.append(summ.assign(scenario=label[i]))
if frames:
    table = pd.concat(frames, ignore_index=True)
    table = table[["scenario", *[c for c in table.columns if c != "scenario"]]]
    st.dataframe(table, hide_index=True, use_container_width=True)
    unit = ui_common.metal_label(loaded[chosen[0]][0])
    fig = go.Figure()
    for name, g in table.groupby("scenario", sort=False):
        fig.add_scatter(x=g["budget"], y=g["converted_metal"], mode="lines+markers", name=name)
    fig.update_layout(xaxis_title="Budget",
                      yaxis_title=f"Potentially converted metal ({unit})", margin={"t": 20})
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Metal units follow the first selected scenario; compare like with like.")
else:
    st.info("None of the selected scenarios has results yet.")

IGNORE = {"name", "created", "app_version", "run_info", "disclaimer"}


def flatten(obj, prefix=""):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if not prefix and k in IGNORE:
                continue
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    return {prefix: obj}


flat = {i: flatten(loaded[i][0]) for i in chosen}
keys = sorted(set().union(*flat.values()))
rows = []
for k in keys:
    vals = [flat[i].get(k, "(absent)") for i in chosen]
    if any(str(v) != str(vals[0]) for v in vals[1:]):
        rows.append({"setting": k,
                     **{label[i]: str(v) for i, v in zip(chosen, vals, strict=True)}})
st.markdown("**Settings that differ**")
if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
else:
    st.caption("The selected scenarios have identical settings.")
