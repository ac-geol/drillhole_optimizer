"""Block model import (spec 5.1, acceptance test 4). All data here is synthetic."""

import numpy as np
import pandas as pd
import pytest

from engine.blockmodel import (
    BlockModelMapping,
    distinct_values,
    filter_domain,
    prepare_block_model,
    summarise_by_class,
)
from engine.schema import ClassRank
from engine.units import GradeUnit

CLASS_MAP = {"M": ClassRank.MEASURED, "I": ClassRank.INDICATED, "F": ClassRank.INFERRED}
COLS = {
    "x": "X",
    "y": "Y",
    "z": "Z",
    "dx": "DX",
    "dy": "DY",
    "dz": "DZ",
    "density": "DENS",
    "class_raw": "CLASS",
    "grade": "AU",
}


def mapping(unit=GradeUnit.PERCENT, **kw):
    return BlockModelMapping(
        columns=kw.pop("columns", dict(COLS)),
        constant_dims=kw.pop("constant_dims", {}),
        grade_unit=unit,
        class_map=kw.pop("class_map", dict(CLASS_MAP)),
        **kw,
    )


def synthetic_model():
    # 6 synthetic blocks, 10 x 10 x 5 m = 500 m3 each, density 2.
    return pd.DataFrame(
        {
            "X": range(6),
            "Y": 0,
            "Z": 0,
            "DX": 10,
            "DY": 10,
            "DZ": 5,
            "DENS": 2.0,
            "CLASS": ["M", "M", "I", "I", "I", "F"],
            "AU": [1.0, 3.0, 2.0, 2.0, 4.0, 5.0],
            "DOM": ["a", "a", "a", "b", "b", "b"],
        }
    )


def test_subblock_volumes_use_row_dimensions():
    # Acceptance test 4: 10 m parent blocks split into 5 m and 2.5 m subblocks.
    sizes = [5.0] * 4 + [2.5] * 8
    raw = pd.DataFrame(
        {
            "X": range(len(sizes)),
            "Y": 0,
            "Z": 0,
            "DX": sizes,
            "DY": sizes,
            "DZ": sizes,
            "DENS": 2.5,
            "CLASS": "M",
            "AU": 1.0,
            "PARENT": ["A"] * 4 + ["B"] * 8,
        }
    )
    res = prepare_block_model(raw, mapping(columns=dict(COLS, parent_id="PARENT")))
    expected = 4 * 5.0**3 + 8 * 2.5**3
    assert res.blocks["volume"].sum() == pytest.approx(expected)
    assert res.blocks["volume"].sum() != pytest.approx(12 * 10.0**3)  # not parent dims
    assert list(res.blocks["parent_id"][:2]) == ["A", "A"]


def test_preview_totals_percent():
    res = prepare_block_model(synthetic_model(), mapping())
    s = summarise_by_class(res.blocks).set_index("class")
    assert list(s.index) == ["Measured", "Indicated", "Inferred", "Unclassified"]
    # Measured: 2 blocks, 1000 m3, 2000 t, metal = 1000 t * (1 + 3) / 100 = 40 t
    assert s.loc["Measured", "rows"] == 2
    assert s.loc["Measured", "volume"] == pytest.approx(1000)
    assert s.loc["Measured", "tonnes"] == pytest.approx(2000)
    assert s.loc["Measured", "metal"] == pytest.approx(1000 * (1 + 3) / 100)
    # Indicated: 3 blocks, 3000 t, metal = 1000 * (2 + 2 + 4) / 100 = 80 t
    assert s.loc["Indicated", "tonnes"] == pytest.approx(3000)
    assert s.loc["Indicated", "metal"] == pytest.approx(80)
    # Inferred: 1 block, 1000 t, metal 1000 * 5 / 100 = 50 t
    assert s.loc["Inferred", "metal"] == pytest.approx(50)
    assert s.loc["Unclassified", "rows"] == 0
    assert s.loc["Unclassified", "tonnes"] == 0


def test_preview_totals_gpt_is_kg():
    res = prepare_block_model(synthetic_model(), mapping(GradeUnit.GPT))
    s = summarise_by_class(res.blocks).set_index("class")
    # Measured: 1000 t * (1 + 3) g/t / 1000 = 4 kg
    assert s.loc["Measured", "metal"] == pytest.approx(4.0)
    assert s.loc["Indicated", "metal"] == pytest.approx(8.0)
    assert s.loc["Inferred", "metal"] == pytest.approx(5.0)


def test_sentinels_and_blanks_excluded_and_counted():
    raw = synthetic_model()
    raw["AU"] = raw["AU"].astype(object)
    raw.loc[0, "AU"] = -99
    raw.loc[1, "AU"] = -999.0
    raw.loc[2, "AU"] = ""
    raw.loc[3, "AU"] = "n/a"
    raw.loc[4, "DENS"] = -99.0
    raw.loc[5, "DENS"] = np.nan
    res = prepare_block_model(raw, mapping())
    assert res.n_rows == 6
    assert res.n_invalid == 6
    assert res.invalid_reasons["null grade"] == 4
    assert res.invalid_reasons["null density"] == 2
    assert res.blocks["tonnes"].isna().all()
    assert res.blocks["metal"].isna().all()
    assert len(res.blocks) == 6  # invalid rows stay in the table
    assert summarise_by_class(res.blocks)["rows"].sum() == 0


def test_custom_sentinel_list():
    raw = synthetic_model()
    raw.loc[0, "AU"] = -99.0  # not a sentinel any more
    raw.loc[1, "AU"] = 9999.0
    res = prepare_block_model(raw, mapping(null_sentinels=[9999.0]))
    assert res.n_invalid == 1
    assert bool(res.blocks.loc[0, "valid"]) and not bool(res.blocks.loc[1, "valid"])


def test_non_positive_density_and_dims_have_own_reasons():
    raw = synthetic_model()
    raw.loc[0, "DENS"] = 0.0
    raw.loc[1, "DX"] = 0
    res = prepare_block_model(raw, mapping())
    assert res.invalid_reasons == {
        "non-positive density": 1,
        "non-positive block dimension": 1,
    }
    assert res.n_invalid == 2


def test_constant_dims_and_default_block_id():
    raw = synthetic_model().drop(columns=["DZ"])
    cols = {k: v for k, v in COLS.items() if k != "dz"}
    res = prepare_block_model(raw, mapping(columns=cols, constant_dims={"dz": 5.0}))
    assert (res.blocks["dz"] == 5.0).all()
    assert res.blocks["volume"].iloc[0] == pytest.approx(500)
    assert list(res.blocks["block_id"]) == ["0", "1", "2", "3", "4", "5"]


def test_class_mapping_with_unmapped_value():
    raw = synthetic_model()
    raw.loc[5, "CLASS"] = " Potential "
    assert distinct_values(raw, "CLASS") == ["I", "M", "Potential"]
    res = prepare_block_model(raw, mapping())
    assert res.unmapped_classes == ["Potential"]
    assert res.blocks.loc[5, "uploaded_class"] == ClassRank.NONE
    assert res.blocks.loc[5, "class_raw"] == "Potential"
    s = summarise_by_class(res.blocks).set_index("class")
    assert s.loc["Unclassified", "rows"] == 1


def test_domain_filter():
    res = prepare_block_model(synthetic_model(), mapping(columns=dict(COLS, domain="DOM")))
    assert len(filter_domain(res.blocks, None)) == 6
    assert len(filter_domain(res.blocks, [])) == 6
    sub = filter_domain(res.blocks, ["b"])
    assert list(sub["domain"].unique()) == ["b"]
    assert summarise_by_class(sub).set_index("class").loc["Indicated", "rows"] == 2


def test_missing_required_mapping_raises():
    raw = synthetic_model()
    no_dz = {k: v for k, v in COLS.items() if k != "dz"}
    no_grade = {k: v for k, v in COLS.items() if k != "grade"}
    with pytest.raises(ValueError, match="'dz' is required"):
        prepare_block_model(raw, mapping(columns=no_dz))
    with pytest.raises(ValueError, match="'grade' is required"):
        prepare_block_model(raw, mapping(columns=no_grade))
    with pytest.raises(ValueError, match="not in the uploaded file"):
        prepare_block_model(raw, mapping(columns=dict(COLS, grade="NOPE")))
