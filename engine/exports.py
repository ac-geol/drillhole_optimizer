"""CSV and JSON export writers. Every export carries the standard disclaimer."""

from __future__ import annotations

import pandas as pd

from engine import DISCLAIMER, units
from engine.costs import CostModel
from engine.schema import GEOMETRY_LABELS, UPLOADED_LABELS
from engine.storage import json_text, to_jsonable


def csv_bytes(df: pd.DataFrame) -> bytes:
    """UTF-8 CSV, disclaimer comment line first, no index, LF newlines, no blank lines."""
    body = df.to_csv(index=False, lineterminator="\n")
    return f"# {DISCLAIMER}\n{body}".encode()


def scenario_json_bytes(settings: dict) -> bytes:
    data = {"disclaimer": DISCLAIMER, **to_jsonable(settings)}
    return json_text(data).encode("utf-8")


def _labels(series: pd.Series, labels: dict) -> pd.Series:
    return series.map({int(k): v for k, v in labels.items()})


def holes_table(holes: pd.DataFrame, cost_model: CostModel) -> pd.DataFrame:
    """Per-hole cost excludes site setup, which is a campaign-level cost (spec 7.2)."""
    out = holes.copy()
    out["length"] = out["length"].astype(float)
    out["hole_cost_excl_setup"] = (
        out["length"] * cost_model.cost_per_metre + cost_model.fixed_per_hole)
    out = out.rename(columns={"length": "length_m"})
    cols = ["budget", "hole_id", "site_id", "x", "y", "z", "azimuth", "dip",
            "length_m", "hole_cost_excl_setup", "locked"]
    return out[[c for c in cols if c in out.columns]].reset_index(drop=True)


def _metric_rename(grade_unit) -> dict[str, str]:
    metal = units.metal_column(grade_unit)
    return {
        "metres": "metres_m",
        "converted_tonnes": "potentially_converted_tonnes_t",
        "converted_metal": f"potentially_converted_{metal}",
        "metal_per_metre": f"{metal}_per_m",
        "metal_per_cost": f"{metal}_per_cost",
        "tonnes": "tonnes_t",
        "metal": metal,
    }


def summary_table(summary: pd.DataFrame, grade_unit) -> pd.DataFrame:
    return summary.rename(columns=_metric_rename(grade_unit)).reset_index(drop=True)


def comparison_table(comparison: pd.DataFrame, grade_unit) -> pd.DataFrame:
    return summary_table(comparison, grade_unit)


def blocks_table(blocks: pd.DataFrame, grade_unit) -> pd.DataFrame:
    out = pd.DataFrame({"block_id": blocks["block_id"]})
    out["uploaded_class"] = _labels(blocks["uploaded_class"], UPLOADED_LABELS)
    out["baseline_geometry_class"] = _labels(blocks["baseline_class"], GEOMETRY_LABELS)
    out["baseline_mean_dist_3_holes_m"] = blocks["baseline_metric"]
    out["post_geometry_class"] = _labels(blocks["post_class"], GEOMETRY_LABELS)
    out["post_mean_dist_3_holes_m"] = blocks["post_metric"]
    out["potentially_converted"] = blocks["converted"].astype(bool)
    out["tonnes_t"] = blocks["tonnes"]
    out[units.metal_column(grade_unit)] = blocks["metal"]
    return out.reset_index(drop=True)
