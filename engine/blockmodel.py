"""Block model import, column mapping, null sentinels, class mapping, volume, tonnage and metal."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from engine.schema import BLOCK_OPTIONAL, BLOCK_REQUIRED, UPLOADED_LABELS, ClassRank
from engine.units import GradeUnit, metal_from_grade

_DIMS = ["dx", "dy", "dz"]
_SENTINEL_TOL = 1e-9


@dataclass
class BlockModelMapping:
    columns: dict[str, str]
    constant_dims: dict[str, float]
    grade_unit: GradeUnit
    class_map: dict[str, ClassRank]
    null_sentinels: list[float] = field(default_factory=lambda: [-99.0, -999.0])


@dataclass
class BlockModelImport:
    blocks: pd.DataFrame
    n_rows: int
    n_invalid: int
    invalid_reasons: dict[str, int]
    unmapped_classes: list[str]


def _as_text(series: pd.Series) -> pd.Series:
    """Stripped strings with blanks and NaN as empty string."""
    return series.where(series.notna(), "").astype(str).str.strip()


def distinct_values(raw: pd.DataFrame, column: str) -> list[str]:
    """Sorted distinct stripped non-blank string values of a column."""
    if column not in raw.columns:
        raise ValueError(f"Column '{column}' is not in the uploaded file.")
    values = _as_text(raw[column])
    return sorted(set(values[values != ""]))


def _numeric(series: pd.Series, sentinels: list[float] | None = None) -> pd.Series:
    """Float series; non-numeric text and sentinel values become NaN."""
    out = pd.to_numeric(series, errors="coerce").astype("float64")
    for s in sentinels or []:
        out = out.mask((out - s).abs() <= _SENTINEL_TOL)
    return out


def prepare_block_model(raw: pd.DataFrame, mapping: BlockModelMapping) -> BlockModelImport:
    cols = {k: v for k, v in mapping.columns.items() if v}
    consts = mapping.constant_dims

    # Check the mapping is complete before touching the data.
    for name in BLOCK_REQUIRED:
        if name in _DIMS:
            if name not in cols and name not in consts:
                raise ValueError(f"'{name}' is required: choose a column or enter a constant value.")
        elif name not in cols:
            raise ValueError(f"'{name}' is required: choose a column for it.")
    for name, source in cols.items():
        if name in BLOCK_REQUIRED + BLOCK_OPTIONAL and source not in raw.columns:
            raise ValueError(f"Column '{source}' mapped to '{name}' is not in the uploaded file.")

    n = len(raw)
    idx = raw.index
    blocks = pd.DataFrame(index=idx)
    if "block_id" in cols:
        blocks["block_id"] = _as_text(raw[cols["block_id"]])
    else:
        blocks["block_id"] = [str(i) for i in range(n)]

    for name in ["x", "y", "z"]:
        blocks[name] = _numeric(raw[cols[name]])
    for name in _DIMS:
        if name in cols:
            blocks[name] = _numeric(raw[cols[name]])
        else:
            blocks[name] = float(consts[name])
    blocks["density"] = _numeric(raw[cols["density"]], mapping.null_sentinels)
    blocks["grade"] = _numeric(raw[cols["grade"]], mapping.null_sentinels)

    blocks["class_raw"] = _as_text(raw[cols["class_raw"]])
    if "domain" in cols:
        blocks["domain"] = _as_text(raw[cols["domain"]])
    if "parent_id" in cols:
        blocks["parent_id"] = _as_text(raw[cols["parent_id"]])

    class_map = {str(k).strip(): ClassRank(v) for k, v in mapping.class_map.items()}
    blocks["uploaded_class"] = (
        blocks["class_raw"].map(lambda v: int(class_map.get(v, ClassRank.NONE))).astype("int8")
    )
    unmapped = sorted(set(blocks["class_raw"]) - set(class_map))

    # Validity rules, each with its own reason.
    checks = {
        "null coordinate": blocks[["x", "y", "z"]].isna().any(axis=1),
        "null block dimension": blocks[_DIMS].isna().any(axis=1),
        "null density": blocks["density"].isna(),
        "null grade": blocks["grade"].isna(),
        "non-positive density": blocks["density"] <= 0,
        "non-positive block dimension": (blocks[_DIMS] <= 0).any(axis=1),
    }
    invalid = pd.Series(False, index=idx)
    reasons: dict[str, int] = {}
    for reason, mask in checks.items():
        count = int(mask.sum())
        if count:
            reasons[reason] = count
        invalid |= mask
    blocks["valid"] = ~invalid

    blocks["volume"] = blocks["dx"] * blocks["dy"] * blocks["dz"]
    tonnes = blocks["volume"] * blocks["density"]
    blocks["tonnes"] = tonnes.where(blocks["valid"], np.nan)
    metal = metal_from_grade(blocks["tonnes"], blocks["grade"], mapping.grade_unit)
    blocks["metal"] = pd.Series(metal, index=idx).where(blocks["valid"], np.nan)

    return BlockModelImport(
        blocks=blocks.reset_index(drop=True),
        n_rows=n,
        n_invalid=int(invalid.sum()),
        invalid_reasons=reasons,
        unmapped_classes=unmapped,
    )


def filter_domain(blocks: pd.DataFrame, domains: list[str] | None) -> pd.DataFrame:
    """Blocks in the chosen domains. None or empty means all blocks."""
    if not domains:
        return blocks
    if "domain" not in blocks.columns:
        raise ValueError("The block model has no domain column to filter on.")
    return blocks[blocks["domain"].isin([str(d).strip() for d in domains])]


def summarise_by_class(blocks: pd.DataFrame) -> pd.DataFrame:
    """Rows, volume, tonnes and metal per uploaded class, valid rows only."""
    valid = blocks[blocks["valid"]]
    out = []
    for rank in [ClassRank.MEASURED, ClassRank.INDICATED, ClassRank.INFERRED, ClassRank.NONE]:
        sub = valid[valid["uploaded_class"] == int(rank)]
        out.append(
            {
                "class": UPLOADED_LABELS[rank],
                "rows": len(sub),
                "volume": float(sub["volume"].sum()),
                "tonnes": float(sub["tonnes"].sum()),
                "metal": float(sub["metal"].sum()),
            }
        )
    return pd.DataFrame(out)
