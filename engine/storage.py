"""Project folders, scenario JSON and Parquet persistence, input hashes and stale checks."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import shutil
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp

from engine import __version__

INPUT_KINDS = ("blocks", "drilling", "sites", "manual", "collars", "surveys", "intervals")

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
    f"LPT{i}" for i in range(1, 10)}
_CSV_ENCODINGS = ("utf-8-sig", "cp1252")  # utf-8-sig also reads plain utf-8


def safe_name(name: str) -> str:
    """Windows-safe folder name."""
    cleaned = _FORBIDDEN.sub("", str(name)).strip().rstrip(". ").strip()
    if not cleaned:
        raise ValueError(f"Name {name!r} is empty after removing characters Windows forbids")
    if cleaned.split(".")[0].strip().upper() in _RESERVED:
        cleaned += "_"
    return cleaned


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def to_jsonable(obj):
    """Convert numpy scalars/arrays, enums, paths and NaN to plain JSON-safe Python."""
    if isinstance(obj, Enum):
        return to_jsonable(obj.value)
    if isinstance(obj, dict):
        return {str(k.value if isinstance(k, Enum) else k): to_jsonable(v)
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist())
    if isinstance(obj, np.generic):
        return to_jsonable(obj.item())
    if isinstance(obj, Path):
        return obj.as_posix()
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def json_text(obj) -> str:
    return json.dumps(to_jsonable(obj), indent=2, ensure_ascii=False) + "\n"


def _write_json(path: Path, obj) -> None:
    path.write_text(json_text(obj), encoding="utf-8", newline="\n")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic(path: Path, writer) -> None:
    tmp = path.with_name(path.name + ".tmp")
    writer(tmp)
    os.replace(tmp, path)


def parse_csv(data: bytes) -> pd.DataFrame:
    """Parse CSV bytes: utf-8 (BOM ok), falling back to cp1252 for Excel exports."""
    last: Exception | None = None
    for enc in _CSV_ENCODINGS:
        try:
            # low_memory=False types each column from the whole file. The default reads in
            # chunks and can leave a column holding both numbers and text, which Parquet
            # cannot store.
            return pd.read_csv(io.BytesIO(data), encoding=enc, low_memory=False)
        except UnicodeDecodeError as exc:
            last = exc
    raise ValueError(f"Could not decode CSV as UTF-8 or Windows-1252: {last}")


class Project:
    def __init__(self, root: Path, settings: dict):
        self.root = Path(root)
        self.settings = settings

    # -- lifecycle ---------------------------------------------------------
    @classmethod
    def create(cls, projects_dir: Path, name: str) -> Project:
        root = Path(projects_dir) / safe_name(name)
        if root.exists():
            raise FileExistsError(f"Project folder already exists: {root}")
        for sub in ("inputs", "cache", "scenarios"):
            (root / sub).mkdir(parents=True)
        proj = cls(root, {"name": name, "inputs": {}})
        proj.save_settings(proj.settings)
        return proj

    @classmethod
    def open(cls, path: Path) -> Project:
        path = Path(path)
        pj = path / "project.json"
        if not pj.is_file():
            raise FileNotFoundError(f"Not a project folder (no project.json): {path}")
        settings = _read_json(pj)
        settings.setdefault("inputs", {})
        return cls(path, settings)

    @staticmethod
    def list_projects(projects_dir: Path) -> list[str]:
        d = Path(projects_dir)
        if not d.is_dir():
            return []
        return sorted(p.name for p in d.iterdir() if (p / "project.json").is_file())

    # -- settings ----------------------------------------------------------
    @property
    def _inputs_dir(self) -> Path:
        return self.root / "inputs"

    def save_settings(self, settings: dict) -> None:
        settings = json.loads(json_text(settings))
        settings.setdefault("inputs", self.settings.get("inputs", {}))
        self.settings = settings
        _write_json(self.root / "project.json", settings)

    # -- inputs ------------------------------------------------------------
    def save_input(self, kind: str, data: bytes, filename: str) -> str:
        if kind not in INPUT_KINDS:
            raise ValueError(f"Unknown input kind {kind!r}; expected one of {INPUT_KINDS}")
        df = parse_csv(data)  # parse first so a bad file leaves the project untouched
        self._inputs_dir.mkdir(parents=True, exist_ok=True)
        for old in self._inputs_dir.glob(f"{kind}__*"):
            old.unlink()
        original = self._inputs_dir / f"{kind}__{safe_name(Path(filename).name)}"
        original.write_bytes(data)
        _atomic(self._inputs_dir / f"{kind}.parquet", lambda p: df.to_parquet(p, index=False))
        digest = sha256_bytes(data)
        self.settings.setdefault("inputs", {})[kind] = {"filename": filename, "sha256": digest}
        _write_json(self.root / "project.json", self.settings)
        return digest

    def load_input(self, kind: str) -> pd.DataFrame | None:
        path = self._inputs_dir / f"{kind}.parquet"
        return pd.read_parquet(path) if path.is_file() else None

    def input_hashes(self) -> dict[str, str]:
        return {k: v["sha256"] for k, v in self.settings.get("inputs", {}).items()}

    # -- cache -------------------------------------------------------------
    @staticmethod
    def cache_key(*parts) -> str:
        text = json.dumps(to_jsonable(list(parts)), sort_keys=True, separators=(",", ":"))
        return sha256_bytes(text.encode("utf-8"))

    @property
    def _cache_dir(self) -> Path:
        return self.root / "cache"

    def cache_save(self, key: str, obj) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        base = self._cache_dir / key
        if isinstance(obj, pd.DataFrame):
            _atomic(base.with_suffix(".parquet"), lambda p: obj.to_parquet(p))
        elif sp.issparse(obj):
            def w(p):
                with open(p, "wb") as f:
                    sp.save_npz(f, obj)
            _atomic(base.with_suffix(".sparse.npz"), w)
        elif isinstance(obj, dict):
            def w(p):
                with open(p, "wb") as f:
                    np.savez(f, **{k: np.asarray(v) for k, v in obj.items()})
            _atomic(base.with_suffix(".arrays.npz"), w)
        else:
            raise TypeError(f"Cannot cache object of type {type(obj).__name__}")

    def cache_load(self, key: str):
        base = self._cache_dir / key
        try:
            p = base.with_suffix(".parquet")
            if p.is_file():
                return pd.read_parquet(p)
            p = base.with_suffix(".sparse.npz")
            if p.is_file():
                return sp.load_npz(p)
            p = base.with_suffix(".arrays.npz")
            if p.is_file():
                with np.load(p) as z:
                    return {k: z[k] for k in z.files}
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            # a corrupt or partial cache file is a miss, not an error
            return None
        return None

    # -- scenarios ---------------------------------------------------------
    @property
    def _scen_dir(self) -> Path:
        return self.root / "scenarios"

    def _new_id(self, name: str) -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        try:
            slug = safe_name(re.sub(r"\s+", "_", name))[:40].rstrip(". ")
        except ValueError:
            slug = "scenario"
        base = f"{stamp}_{slug}"
        sid, n = base, 2
        while (self._scen_dir / sid).exists():
            sid = f"{base}-{n}"
            n += 1
        return sid

    def _write_scenario(self, settings: dict, results: dict[str, pd.DataFrame],
                        scenario_id: str | None = None) -> str:
        snap = json.loads(json_text(settings))  # deep copy, plain Python
        snap.setdefault("name", "Scenario")
        snap.setdefault("created", datetime.now(UTC).isoformat(timespec="seconds"))
        snap.setdefault("app_version", __version__)
        if scenario_id is None:
            sid = self._new_id(str(snap["name"]))
            folder = self._scen_dir / sid
            folder.mkdir(parents=True)
        else:  # recalculation replaces the scenario's results in place
            sid = safe_name(scenario_id)
            folder = self._scen_dir / sid
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob("*.parquet"):
                old.unlink()
        for table, df in results.items():
            df.to_parquet(folder / f"{safe_name(table)}.parquet")
        _write_json(folder / "scenario.json", snap)
        return sid

    def save_scenario(self, settings: dict, results: dict[str, pd.DataFrame],
                      scenario_id: str | None = None) -> str:
        """Save a new scenario, or overwrite ``scenario_id`` when recalculating it."""
        return self._write_scenario(settings, results, scenario_id)

    def load_scenario(self, scenario_id: str, tables: Iterable[str] | None = None
                      ) -> tuple[dict, dict[str, pd.DataFrame]]:
        """Settings and result tables. Pass ``tables`` to read only those (the block
        table is large); an empty list reads the settings alone."""
        folder = self._scen_dir / safe_name(scenario_id)
        settings = _read_json(folder / "scenario.json")
        wanted = None if tables is None else set(tables)
        results = {p.stem: pd.read_parquet(p) for p in sorted(folder.glob("*.parquet"))
                   if wanted is None or p.stem in wanted}
        return settings, results

    def list_scenarios(self) -> list[dict]:
        out = []
        if not self._scen_dir.is_dir():
            return out
        for folder in sorted(self._scen_dir.iterdir()):
            sj = folder / "scenario.json"
            if not sj.is_file():
                continue
            s = _read_json(sj)
            out.append({"id": folder.name, "name": s.get("name", folder.name),
                        "created": s.get("created"), "stale": self.is_stale(s),
                        "has_results": (folder / "summary.parquet").is_file()})
        return out

    def duplicate_scenario(self, scenario_id: str, new_name: str) -> str:
        settings, _ = self.load_scenario(scenario_id)
        settings["name"] = new_name
        settings.pop("created", None)
        settings.pop("app_version", None)
        return self._write_scenario(settings, {})

    def delete_scenario(self, scenario_id: str) -> None:
        shutil.rmtree(self._scen_dir / safe_name(scenario_id))

    def is_stale(self, settings: dict) -> bool:
        current = self.input_hashes()
        return any(current.get(kind) != h
                   for kind, h in settings.get("input_hashes", {}).items())
