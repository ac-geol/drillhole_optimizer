import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
from pandas.testing import assert_frame_equal

from engine.storage import INPUT_KINDS, Project, safe_name, sha256_bytes


@pytest.mark.parametrize("raw,expected", [
    ("My Project", "My Project"),
    ('a<b>c:d"e/f\\g|h?i*j', "abcdefghij"),
    ("name. . ", "name"),
    ("tab\x01ctl", "tabctl"),
    ("CON", "CON_"), ("nul", "nul_"), ("com1", "com1_"), ("LPT9", "LPT9_"),
    ("aux.txt", "aux.txt_"), ("console", "console"),
])
def test_safe_name(raw, expected):
    assert safe_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "...", '<>:"/\\|?*'])
def test_safe_name_empty(raw):
    with pytest.raises(ValueError):
        safe_name(raw)


def test_project_create_open_list(tmp_path):
    p = Project.create(tmp_path, "Alpha: 1")
    assert p.root == tmp_path / "Alpha 1"
    with pytest.raises(FileExistsError):
        Project.create(tmp_path, "Alpha: 1")
    Project.create(tmp_path, "Beta")
    (tmp_path / "junk").mkdir()
    assert Project.list_projects(tmp_path) == ["Alpha 1", "Beta"]
    assert Project.list_projects(tmp_path / "missing") == []
    p.save_settings({"name": "Alpha: 1", "units": np.str_("%"), "n": np.int64(3)})
    q = Project.open(p.root)
    assert q.settings["n"] == 3 and q.settings["units"] == "%"


def test_input_roundtrip_bom_and_cp1252(tmp_path):
    p = Project.create(tmp_path, "P")
    bom = "﻿id,note\n1,abc\n".encode()
    h = p.save_input("blocks", bom, "blocks.csv")
    assert h == sha256_bytes(bom)
    assert list(p.load_input("blocks").columns) == ["id", "note"]
    assert (tmp_path / "P" / "inputs" / "blocks.parquet").is_file()
    cp = "id,note\n1,caf\xe9\n".encode("cp1252")
    p.save_input("drilling", cp, "d.csv")
    assert p.load_input("drilling")["note"][0] == "caf\xe9"
    utf = "id,note\n1,caf\xe9\n".encode()
    p.save_input("sites", utf, "s.csv")
    assert p.load_input("sites")["note"][0] == "caf\xe9"
    assert p.load_input("manual") is None
    assert set(p.input_hashes()) == {"blocks", "drilling", "sites"}
    assert set(p.input_hashes()) <= set(INPUT_KINDS)
    assert Project.open(p.root).input_hashes() == p.input_hashes()
    with pytest.raises(ValueError):
        p.save_input("nope", b"a\n1\n", "x.csv")


def test_replace_input_overwrites(tmp_path):
    p = Project.create(tmp_path, "P")
    p.save_input("blocks", b"a\n1\n", "one.csv")
    p.save_input("blocks", b"a\n2\n", "two.csv")
    assert list((tmp_path / "P" / "inputs").glob("blocks__*")) == [
        tmp_path / "P" / "inputs" / "blocks__two.csv"]
    assert p.load_input("blocks")["a"][0] == 2


def _results():
    return {
        "summary": pd.DataFrame({"budget": [1.0, 2.0], "holes": [1, 2]}),
        "holes": pd.DataFrame({"hole_id": ["a", "b"], "length": [10.5, 20.0]}),
        "blocks": pd.DataFrame({"block_id": [1, 2, 3], "converted": [True, False, True]}),
    }


def _settings(p):
    return {"name": "Run 1", "budgets": np.array([1.0, 2.0]), "seed": np.int64(7),
            "mapping": {"x": "X"}, "input_hashes": p.input_hashes()}


def test_scenario_roundtrip_and_stale(tmp_path):
    p = Project.create(tmp_path, "P")
    p.save_input("blocks", b"a\n1\n", "b.csv")
    settings = _settings(p)
    sid = p.save_scenario(settings, _results())
    assert "created" not in settings  # caller's dict not mutated
    settings["mapping"]["x"] = "changed"  # snapshot is a copy
    loaded, res = p.load_scenario(sid)
    assert loaded["mapping"] == {"x": "X"}
    assert loaded["budgets"] == [1.0, 2.0] and loaded["seed"] == 7
    assert loaded["name"] == "Run 1" and "created" in loaded and "app_version" in loaded
    for k, df in _results().items():
        assert_frame_equal(res[k], df)
    # save -> load identical settings
    sid2 = p.save_scenario(loaded, res)
    assert p.load_scenario(sid2)[0] == loaded
    assert sid != sid2
    # stale detection (test 14)
    assert [s["stale"] for s in p.list_scenarios()] == [False, False]
    p.save_input("blocks", b"a\n999\n", "b.csv")
    assert all(s["stale"] for s in p.list_scenarios())
    assert p.is_stale(loaded)
    fresh = dict(loaded, input_hashes=p.input_hashes())
    sid3 = p.save_scenario(fresh, res)
    flags = {s["id"]: s["stale"] for s in p.list_scenarios()}
    assert flags[sid3] is False and flags[sid] is True


def test_stale_when_input_missing(tmp_path):
    p = Project.create(tmp_path, "P")
    assert p.is_stale({"input_hashes": {"blocks": "abc"}})
    assert not p.is_stale({"input_hashes": {}})


def test_duplicate_scenario_no_results(tmp_path):
    p = Project.create(tmp_path, "P")
    sid = p.save_scenario(_settings(p), _results())
    dup = p.duplicate_scenario(sid, "Copy: of run?")
    settings, res = p.load_scenario(dup)
    assert res == {}
    assert settings["name"] == "Copy: of run?" and settings["budgets"] == [1.0, 2.0]
    assert dup != sid and ":" not in dup and "?" not in dup
    assert len(p.list_scenarios()) == 2


def test_cache_roundtrip(tmp_path):
    p = Project.create(tmp_path, "P")
    k = p.cache_key("a", {"b": 1, "a": np.float64(2.0)})
    assert k == p.cache_key("a", {"a": 2.0, "b": 1}) and k != p.cache_key("a")
    assert p.cache_load(k) is None
    df = pd.DataFrame({"a": [1, 2], "b": [0.5, 1.5]})
    p.cache_save(k, df)
    assert_frame_equal(p.cache_load(k), df)
    k2 = p.cache_key("arrays")
    arrs = {"i": np.arange(5), "d": np.linspace(0, 1, 5)}
    p.cache_save(k2, arrs)
    got = p.cache_load(k2)
    assert set(got) == {"i", "d"} and np.array_equal(got["d"], arrs["d"])
    k3 = p.cache_key("sparse")
    m = sp.random(20, 30, density=0.1, format="csc", random_state=0)
    p.cache_save(k3, m)
    got = p.cache_load(k3)
    assert sp.issparse(got) and got.format == "csc" and (got != m).nnz == 0
