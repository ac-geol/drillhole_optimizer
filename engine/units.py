"""Grade units, metal units and conversions.

Metric only in v1. A project reports in one unit system; imperial can be
added here later without touching the rest of the engine.
"""

from __future__ import annotations

from enum import Enum

import numpy as np


class GradeUnit(str, Enum):
    PERCENT = "%"
    GPT = "g/t"


METAL_UNIT: dict[GradeUnit, str] = {GradeUnit.PERCENT: "t", GradeUnit.GPT: "kg"}

_DIVISOR: dict[GradeUnit, float] = {GradeUnit.PERCENT: 100.0, GradeUnit.GPT: 1000.0}


def metal_from_grade(tonnes, grade, unit: GradeUnit | str):
    """Contained metal: t for % grades, kg for g/t grades (spec 5.1)."""
    unit = GradeUnit(unit)
    return np.asarray(tonnes, dtype=float) * np.asarray(grade, dtype=float) / _DIVISOR[unit]


def metal_unit(unit: GradeUnit | str) -> str:
    return METAL_UNIT[GradeUnit(unit)]


def metal_column(unit: GradeUnit | str) -> str:
    """Export column header carrying the unit, e.g. ``metal_kg``."""
    return f"metal_{metal_unit(unit)}"
