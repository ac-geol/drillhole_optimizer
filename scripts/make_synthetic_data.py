"""Write a small SYNTHETIC demo data set to data/test/ (not real data).

Usage:  uv run python scripts/make_synthetic_data.py

Files written (all names start with SYNTHETIC_):
  SYNTHETIC_blocks.csv          block model, 10 m parents with some 5 m sub-blocks
  SYNTHETIC_drilling_routeA.csv desurveyed 1 m composites (Route A)
  SYNTHETIC_collars.csv         collars for the same holes (Route B)
  SYNTHETIC_surveys.csv         surveys for the same holes (Route B, dip negative downward)
  SYNTHETIC_sites.csv           potential drill sites over the Indicated core
  SYNTHETIC_manual_plan.csv     five planned holes (dip positive downward)

The output is seeded and deterministic.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "test"
SEED = 20240611
SIZE = 400.0          # model extent in x and y (m)
TOP_RL = 420.0        # surface elevation (m)
DEPTH = 120.0         # model depth (m)
CENTRE = np.array([200.0, 200.0])


def _radius(x, y) -> np.ndarray:
    return np.hypot(np.asarray(x) - CENTRE[0], np.asarray(y) - CENTRE[1])


def make_blocks(rng: np.random.Generator) -> pd.DataFrame:
    xs = np.arange(5.0, SIZE, 10.0)
    zs = np.arange(TOP_RL - DEPTH + 5.0, TOP_RL, 10.0)
    gx, gy, gz = np.meshgrid(xs, xs, zs, indexing="ij")
    px, py, pz = gx.ravel(), gy.ravel(), gz.ravel()
    split = set(rng.choice(len(px), size=60, replace=False).tolist())
    offs = (-2.5, 2.5)
    rows = []
    for i in range(len(px)):
        pid = f"P{i:05d}"
        if i in split:
            for ox in offs:
                for oy in offs:
                    for oz in offs:
                        rows.append((px[i] + ox, py[i] + oy, pz[i] + oz, 5.0, pid))
        else:
            rows.append((px[i], py[i], pz[i], 10.0, pid))
    b = pd.DataFrame(rows, columns=["XC", "YC", "ZC", "XINC", "PARENT"])
    b["YINC"] = b["XINC"]
    b["ZINC"] = b["XINC"]
    r = _radius(b["XC"], b["YC"])
    b["RESCAT"] = np.where(r < 80, 1, np.where(r < 200, 2, 3))
    base = 2.5 * np.exp(-((r / 160.0) ** 2)) + 0.4 * np.sin(b["ZC"] / 25.0)
    b["AU_GPT"] = np.clip(base + rng.normal(0, 0.35, len(b)) + 0.4, 0.02, None).round(3)
    b["DENSITY"] = (2.6 + 0.1 * rng.random(len(b))).round(3)
    b["DOMAIN"] = np.where(b["AU_GPT"] >= 1.5, "HG", np.where(b["AU_GPT"] >= 0.5, "LG", "WASTE"))
    sentinel = rng.choice(len(b), size=6, replace=False)
    b.loc[sentinel[:3], "AU_GPT"] = -99
    b.loc[sentinel[3:], "DENSITY"] = -99
    b.insert(0, "BLOCKID", [f"B{i:06d}" for i in range(len(b))])
    cols = ["BLOCKID", "XC", "YC", "ZC", "XINC", "YINC", "ZINC", "PARENT", "DENSITY",
            "RESCAT", "AU_GPT", "DOMAIN"]
    return b[cols].round({"XC": 2, "YC": 2, "ZC": 2})


def make_holes(rng: np.random.Generator) -> pd.DataFrame:
    """Collars with orientation: dense in the Measured core, sparse in the Indicated ring."""
    pts = []
    for spacing, lo, hi in ((20.0, 0.0, 80.0), (40.0, 80.0, 200.0), (50.0, 200.0, 400.0)):
        g = np.arange(spacing / 2, SIZE, spacing)
        for x in g:
            for y in g:
                x2 = x + rng.uniform(-spacing / 5, spacing / 5)
                y2 = y + rng.uniform(-spacing / 5, spacing / 5)
                if lo <= _radius(x2, y2) < hi and 0 < x2 < SIZE and 0 < y2 < SIZE:
                    pts.append((x2, y2))
    pts = np.array(pts)
    n = len(pts)
    inclined = rng.random(n) < 0.4
    return pd.DataFrame({
        "HOLEID": [f"SYN{i:03d}" for i in range(n)],
        "EAST": pts[:, 0].round(2), "NORTH": pts[:, 1].round(2),
        "RL": (TOP_RL + rng.normal(0, 1.0, n)).round(2),
        "AZIMUTH": np.where(inclined, rng.uniform(0, 360, n), 0.0).round(1),
        "DIP": np.where(inclined, rng.uniform(-75, -55, n), -90.0).round(1),
        "DEPTH": np.where(inclined, rng.uniform(80, 130, n), rng.uniform(70, 120, n)).round(1),
    })


def trace(row, depths: np.ndarray) -> np.ndarray:
    a, d = np.radians(row.AZIMUTH), np.radians(row.DIP)
    v = np.array([np.cos(d) * np.sin(a), np.cos(d) * np.cos(a), np.sin(d)])
    return np.array([row.EAST, row.NORTH, row.RL]) + depths[:, None] * v


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    blocks = make_blocks(rng)
    holes = make_holes(rng)

    frames = []
    for row in holes.itertuples(index=False):
        depths = np.arange(0.5, row.DEPTH, 1.0)
        xyz = trace(row, depths)
        frames.append(pd.DataFrame({
            "HOLEID": row.HOLEID, "FROM": depths - 0.5, "TO": depths + 0.5,
            "X": xyz[:, 0].round(2), "Y": xyz[:, 1].round(2), "Z": xyz[:, 2].round(2),
            "VALID": "Y"}))
    drilling = pd.concat(frames, ignore_index=True)
    drilling.loc[rng.choice(len(drilling), 20, replace=False), "VALID"] = "N"

    collars = holes[["HOLEID", "EAST", "NORTH", "RL", "DEPTH"]]
    surveys = pd.concat([
        pd.DataFrame({"HOLEID": holes["HOLEID"], "SURVDEPTH": 0.0,
                      "AZIMUTH": holes["AZIMUTH"], "DIP": holes["DIP"]}),
        pd.DataFrame({"HOLEID": holes["HOLEID"], "SURVDEPTH": holes["DEPTH"],
                      "AZIMUTH": holes["AZIMUTH"], "DIP": holes["DIP"]}),
    ]).sort_values(["HOLEID", "SURVDEPTH"], kind="stable")

    # Sites: spread over the Indicated ring, where infill would convert blocks.
    angles = np.linspace(0, 2 * np.pi, 20, endpoint=False) + rng.uniform(0, 0.3)
    rad = rng.uniform(95, 180, 20)
    sites = pd.DataFrame({
        "SITEID": [f"SITE{i + 1:02d}" for i in range(20)],
        "EAST": (CENTRE[0] + rad * np.cos(angles)).round(2),
        "NORTH": (CENTRE[1] + rad * np.sin(angles)).round(2),
        "RL": TOP_RL})

    # Manual plan: five holes at five of the sites, dips positive downward.
    pick = sites.iloc[[0, 4, 8, 12, 16]]
    manual = pd.DataFrame({
        "HOLEID": [f"MAN{i + 1:02d}" for i in range(5)],
        "SITEID": pick["SITEID"].to_numpy(),
        "EAST": pick["EAST"].to_numpy(), "NORTH": pick["NORTH"].to_numpy(),
        "RL": pick["RL"].to_numpy(),
        "AZIMUTH": [0.0, 90.0, 180.0, 270.0, 45.0],
        "DIP": [60.0, 70.0, 60.0, 90.0, 75.0],
        "LENGTH": [100.0, 110.0, 120.0, 100.0, 90.0]})

    files = {
        "SYNTHETIC_blocks.csv": blocks, "SYNTHETIC_drilling_routeA.csv": drilling,
        "SYNTHETIC_collars.csv": collars, "SYNTHETIC_surveys.csv": surveys,
        "SYNTHETIC_sites.csv": sites, "SYNTHETIC_manual_plan.csv": manual}
    for name, df in files.items():
        df.to_csv(OUT_DIR / name, index=False, encoding="utf-8", lineterminator="\n")
        print(f"{name}: {len(df)} rows")


if __name__ == "__main__":
    main()
