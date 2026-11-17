"""Streamlit entry point. Collects inputs and displays outputs only; all maths lives in engine/."""

import streamlit as st

from engine import __version__
from ui_common import LIMITATIONS, SUPPORT_ASSUMPTION, disclaimer, page_setup

page_setup("Infill Drilling Budget Optimiser")
st.caption(f"Version {__version__}")

st.markdown(
    "Ranks drilling campaigns by **potential geometric conversion** of one metal within a "
    "budget. It is a planning aid, not a resource classification tool.\n\n"
    "Use the pages in the sidebar from top to bottom:\n\n"
    "1. **Project**: create or open a project, upload files and map columns.\n"
    "2. **Planning**: choose classes, thresholds, candidate holes, budgets and costs, then run.\n"
    "3. **Results**: summary, budget curve, manual versus optimised, holes, 3D view, downloads.\n"
    "4. **Scenarios**: save, load, duplicate and compare runs."
)
disclaimer()

with st.expander("How the geometry is measured"):
    st.markdown(
        "Every block gets one number: the **mean distance to its nearest three holes**, using "
        "the nearest sample of each distinct hole. That number sets the block's geometry class "
        "(by default Measured ≤ 25 m, Indicated ≤ 50 m, Inferred ≤ 100 m). A block is "
        "**potentially converted** when its uploaded class is the source class, its baseline "
        "geometry does not meet the target class, and the planned campaign brings it there. "
        f"{SUPPORT_ASSUMPTION}"
    )

with st.expander("Known limitations"):
    st.markdown("\n".join(f"- {x}" for x in LIMITATIONS))
