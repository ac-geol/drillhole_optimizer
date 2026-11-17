"""Shared internal table layouts and class ranks.

Every engine module and the UI exchange pandas DataFrames with exactly these
column names. Import from here rather than retyping column names.
"""

from __future__ import annotations

from enum import IntEnum


class ClassRank(IntEnum):
    """Rank shared by uploaded (mapped) classes and geometry classes.

    Higher is better. Rank 0 means "Unclassified" for an uploaded class and
    "Outside criteria" for a geometry class.
    """

    NONE = 0
    INFERRED = 1
    INDICATED = 2
    MEASURED = 3


UPLOADED_LABELS: dict[ClassRank, str] = {
    ClassRank.MEASURED: "Measured",
    ClassRank.INDICATED: "Indicated",
    ClassRank.INFERRED: "Inferred",
    ClassRank.NONE: "Unclassified",
}

GEOMETRY_LABELS: dict[ClassRank, str] = {
    ClassRank.MEASURED: "Measured geometry",
    ClassRank.INDICATED: "Indicated geometry",
    ClassRank.INFERRED: "Inferred geometry",
    ClassRank.NONE: "Outside criteria",
}

# Block model (spec 5.1). Required inputs, optional inputs, then derived columns
# added by engine.blockmodel. `uploaded_class` holds a ClassRank int.
BLOCK_REQUIRED = ["x", "y", "z", "dx", "dy", "dz", "density", "class_raw", "grade"]
BLOCK_OPTIONAL = ["block_id", "domain", "parent_id"]
BLOCK_DERIVED = ["uploaded_class", "volume", "tonnes", "metal", "valid"]

# Existing drilling support points, Route A or desurveyed Route B (spec 5.2).
SUPPORT_COLUMNS = ["hole_id", "x", "y", "z"]

# Potential drill sites (spec 5.3).
SITE_COLUMNS = ["site_id", "x", "y", "z"]

# Planned holes: manual plans, candidates and campaigns all use this layout.
# x, y, z are the collar. Dip is negative downward. `group_id` is the
# same-trace exclusion group (site, azimuth, dip).
HOLE_COLUMNS = ["hole_id", "site_id", "x", "y", "z", "azimuth", "dip", "length", "locked"]
CANDIDATE_EXTRA = ["group_id"]
