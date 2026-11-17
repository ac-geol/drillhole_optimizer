"""Create a ready-to-run demo project from the SYNTHETIC data in data/test/.

Usage (Windows PowerShell or macOS Terminal, from the project folder):
    uv run python scripts/make_demo_project.py

Creates projects/SYNTHETIC demo with all inputs uploaded and columns mapped, so the
Planning page can be run straight away. Re-running replaces that demo project.
"""

import shutil
from pathlib import Path

from engine.pipeline import default_planning
from engine.storage import Project, safe_name

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "test"
NAME = "SYNTHETIC demo"


def main(projects_dir: Path = ROOT / "projects") -> Project:
    projects_dir.mkdir(exist_ok=True)
    target = projects_dir / safe_name(NAME)
    if target.exists():
        shutil.rmtree(target)
    p = Project.create(projects_dir, NAME)
    for kind, file in [("blocks", "SYNTHETIC_blocks.csv"),
                       ("drilling", "SYNTHETIC_drilling_routeA.csv"),
                       ("collars", "SYNTHETIC_collars.csv"),
                       ("surveys", "SYNTHETIC_surveys.csv"),
                       ("sites", "SYNTHETIC_sites.csv"),
                       ("manual", "SYNTHETIC_manual_plan.csv")]:
        p.save_input(kind, (DATA / file).read_bytes(), file)

    planning = default_planning()
    planning["budgets"] = [100_000.0, 200_000.0, 400_000.0]
    planning["candidates"] = {"azimuth": [0.0, 270.0, 90.0], "dip": [-90.0, -60.0, 15.0],
                              "length": [80.0, 160.0, 40.0]}
    p.save_settings({
        **p.settings,
        "blocks": {"columns": {"block_id": "BLOCKID", "x": "XC", "y": "YC", "z": "ZC",
                               "dx": "XINC", "dy": "YINC", "dz": "ZINC",
                               "parent_id": "PARENT", "density": "DENSITY",
                               "class_raw": "RESCAT", "grade": "AU_GPT", "domain": "DOMAIN"},
                   "constant_dims": {}, "grade_unit": "g/t",
                   "class_map": {"1": 3, "2": 2, "3": 1},
                   "null_sentinels": [-99.0, -999.0], "domains": None},
        "drilling": {"route": "A",
                     "mapping": {"hole_id": "HOLEID", "x": "X", "y": "Y", "z": "Z",
                                 "valid": "VALID", "domain": None},
                     "collars": {"hole_id": "HOLEID", "x": "EAST", "y": "NORTH", "z": "RL",
                                 "max_depth": "DEPTH"},
                     "surveys": {"hole_id": "HOLEID", "depth": "SURVDEPTH",
                                 "azimuth": "AZIMUTH", "dip": "DIP"},
                     "intervals": {}, "positive_down": False},
        "sites": {"columns": {"site_id": "SITEID", "x": "EAST", "y": "NORTH", "z": "RL"}},
        "manual": {"columns": {"hole_id": "HOLEID", "site_id": "SITEID", "x": "EAST",
                               "y": "NORTH", "z": "RL", "azimuth": "AZIMUTH", "dip": "DIP",
                               "length": "LENGTH"},
                   "positive_down": True, "match_tolerance": 1.0, "locked": []},
        "planning": planning,
    })
    print(f"Created {p.root}")
    return p


if __name__ == "__main__":
    main()
