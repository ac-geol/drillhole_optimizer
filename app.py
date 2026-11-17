"""Streamlit entry point. Collects inputs and displays outputs only; all maths lives in engine/."""

import streamlit as st

from engine import DISCLAIMER, __version__

st.set_page_config(page_title="Infill Drilling Budget Optimiser", layout="wide")

st.title("Infill Drilling Budget Optimiser")
st.caption(f"Version {__version__}")
st.write("Use the pages in the sidebar from left to right: Project, Planning, Results, Scenarios.")
st.warning(DISCLAIMER)
