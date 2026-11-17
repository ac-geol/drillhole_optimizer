"""Calculation engine for the infill drilling budget optimiser.

Rule: nothing in this package imports Streamlit. The UI calls engine
functions and never reimplements a calculation.
"""

__version__ = "0.1.0"

DISCLAIMER = (
    "Planning estimate based on geometric drilling support. "
    "Not a resource classification declaration. Geological and QP review required."
)

# Threshold comparisons use metric <= T + TOLERANCE_M (spec section 6.3).
TOLERANCE_M = 1e-6
