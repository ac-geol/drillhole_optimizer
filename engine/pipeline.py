"""Project-level orchestration: load mapped inputs, build or reuse cached geometry, run and
save scenarios. The Streamlit pages call these functions and never reimplement a step.

Settings layout
---------------
project.json (project defaults, edited on the Project page):
  blocks:   {columns, constant_dims, grade_unit, class_map {raw: rank}, null_sentinels, domains}
  drilling: {route: "A"|"B", mapping {hole_id,x,y,z,valid,domain},
             collars {hole_id,x,y,z,max_depth}, surveys {hole_id,depth,azimuth,dip},
             intervals {hole_id,from,to}, positive_down}
  sites:    {columns {site_id,x,y,z}}
  manual:   {columns {hole_id,site_id,x,y,z,azimuth,dip,length}, positive_down,
             match_tolerance, locked [hole ids]}
  planning: see default_planning()

scenario.json is a full copy of all of the above at run time plus input_hashes.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine import DISCLAIMER
from engine.blockmodel import (
    BlockModelImport,
    BlockModelMapping,
    filter_domain,
    prepare_block_model,
)
from engine.candidates import CandidateSettings, Range, generate_candidates
from engine.costs import CostModel
from engine.drilling import DrillingImport, DrillingMapping, desurvey_route_b, prepare_route_a
from engine.evaluate import EvaluationContext, Target, build_context
from engine.geometry import NearestThree, Thresholds
from engine.optimise import CandidateMatrix, OptimiserSettings, build_candidate_matrix
from engine.scenarios import (
    compare_manual,
    holes_frame,
    prepare_manual_plan,
    run_budgets,
    summary_frame,
)
from engine.schema import ClassRank
from engine.storage import Project
from engine.units import GradeUnit


def default_planning() -> dict:
    o = OptimiserSettings()
    return {
        "source_class": int(ClassRank.INDICATED),
        "target_class": int(ClassRank.MEASURED),
        "thresholds": {"measured": 25.0, "indicated": 50.0, "inferred": 100.0},
        "candidates": {"azimuth": [0.0, 330.0, 30.0], "dip": [-90.0, -50.0, 10.0],
                       "length": [100.0, 300.0, 50.0]},
        "budgets": [500_000.0, 1_000_000.0, 2_000_000.0],
        "mode": "independent",
        "cost": {"cost_per_metre": 250.0, "fixed_per_hole": 0.0, "setup_per_site": 0.0},
        "support_interval": 2.0,
        "use_manual": True,
        "optimiser": {"restarts": o.restarts, "seed": o.seed, "pair_shortlist": o.pair_shortlist,
                      "pair_neighbours": o.pair_neighbours,
                      "local_search_passes": o.local_search_passes,
                      "time_limit_s": o.time_limit_s, "min_angle": o.min_angle,
                      "site_cap": o.site_cap},
    }


# --------------------------------------------------------------------------- settings -> objects

def thresholds_of(planning: dict) -> Thresholds:
    return Thresholds(**planning["thresholds"])


def target_of(planning: dict) -> Target:
    return Target(ClassRank(planning["source_class"]), ClassRank(planning["target_class"]))


def cost_of(planning: dict) -> CostModel:
    return CostModel(**planning["cost"])


def candidate_settings_of(planning: dict) -> CandidateSettings:
    c = planning["candidates"]
    return CandidateSettings(Range(*c["azimuth"]), Range(*c["dip"]), Range(*c["length"]))


def optimiser_of(planning: dict) -> OptimiserSettings:
    return OptimiserSettings(**planning["optimiser"])


def grade_unit_of(settings: dict) -> GradeUnit:
    return GradeUnit(settings.get("blocks", {}).get("grade_unit", "%"))


# --------------------------------------------------------------------------- inputs

def _require(project: Project, kind: str) -> pd.DataFrame:
    df = project.load_input(kind)
    if df is None:
        raise ValueError(f"No {kind} file has been uploaded.")
    return df


def load_blocks(project: Project, settings: dict | None = None) -> tuple[BlockModelImport, pd.DataFrame]:
    """(import result, selected blocks after the domain filter)."""
    s = (settings or project.settings)["blocks"]
    mapping = BlockModelMapping(
        columns=s["columns"], constant_dims=s.get("constant_dims", {}),
        grade_unit=GradeUnit(s["grade_unit"]),
        class_map={k: ClassRank(v) for k, v in s.get("class_map", {}).items()},
        null_sentinels=s.get("null_sentinels", [-99.0, -999.0]))
    imp = prepare_block_model(_require(project, "blocks"), mapping)
    return imp, filter_domain(imp.blocks, s.get("domains") or None)


def _renamed(df: pd.DataFrame, columns: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame({k: df[v] for k, v in columns.items() if v})


def load_drilling(project: Project, settings: dict | None = None,
                  interval: float = 2.0) -> DrillingImport:
    s = (settings or project.settings)["drilling"]
    if s.get("route", "A") == "A":
        return prepare_route_a(_require(project, "drilling"), DrillingMapping(**s["mapping"]))
    collars = _renamed(_require(project, "collars"), s["collars"])
    surveys = _renamed(_require(project, "surveys"), s["surveys"])
    raw_int = project.load_input("intervals")
    intervals = _renamed(raw_int, s["intervals"]) if raw_int is not None and s.get("intervals") \
        else None
    return desurvey_route_b(collars, surveys, intervals, interval=interval,
                            positive_down=bool(s.get("positive_down", False)))


def load_sites(project: Project, settings: dict | None = None) -> pd.DataFrame:
    s = (settings or project.settings)["sites"]
    out = _renamed(_require(project, "sites"), s["columns"])
    out["site_id"] = out["site_id"].astype(str).str.strip()
    for c in ("x", "y", "z"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    if out[["x", "y", "z"]].isna().any().any():
        raise ValueError("Some drill sites have missing or non-numeric coordinates.")
    if out["site_id"].duplicated().any():
        raise ValueError("Drill site IDs must be unique.")
    return out.reset_index(drop=True)


def load_manual(project: Project, sites: pd.DataFrame | None,
                settings: dict | None = None) -> pd.DataFrame | None:
    s = (settings or project.settings).get("manual")
    raw = project.load_input("manual")
    if raw is None or not s:
        return None
    return prepare_manual_plan(raw, s["columns"], sites,
                               positive_down=bool(s.get("positive_down", False)),
                               match_tolerance=float(s.get("match_tolerance", 1.0)),
                               locked=set(s.get("locked", [])))


# --------------------------------------------------------------------------- cached geometry

def _hashes(project: Project, kinds) -> dict:
    h = project.input_hashes()
    return {k: h.get(k) for k in kinds}


def build_project_context(project: Project, settings: dict | None = None,
                          planning: dict | None = None) -> EvaluationContext:
    """Selected blocks, support and baseline distances (cached on disk by input hash)."""
    settings = settings or project.settings
    planning = planning or settings.get("planning") or default_planning()
    _, blocks = load_blocks(project, settings)
    interval = float(planning["support_interval"])
    drilling = load_drilling(project, settings, interval)
    th = thresholds_of(planning)
    key = project.cache_key("baseline", _hashes(project, ("blocks", "drilling", "collars",
                                                          "surveys", "intervals")),
                            settings["blocks"], settings["drilling"], th.search_radius, interval)
    cached = project.cache_load(key)
    baseline = None
    if isinstance(cached, dict) and len(cached.get("dist", [])) == len(blocks):
        baseline = NearestThree(cached["dist"], cached["hole"], cached["hole_ids"], th)
    ctx = build_context(blocks, drilling.points, thresholds=th, target=target_of(planning),
                        cost_model=cost_of(planning), interval=interval, baseline=baseline)
    if baseline is None:
        project.cache_save(key, {"dist": ctx.baseline.dist, "hole": ctx.baseline.hole,
                                 "hole_ids": ctx.baseline.hole_ids.astype(str)})
    return ctx


def build_project_matrix(project: Project, ctx: EvaluationContext, sites: pd.DataFrame,
                         planning: dict, settings: dict | None = None) -> CandidateMatrix:
    settings = settings or project.settings
    cands = generate_candidates(sites, candidate_settings_of(planning))
    key = project.cache_key("matrix", _hashes(project, ("blocks", "drilling", "collars",
                                                        "surveys", "intervals", "sites")),
                            settings["blocks"], settings["drilling"], settings["sites"],
                            planning["thresholds"], planning["source_class"],
                            planning["target_class"], planning["candidates"],
                            planning["support_interval"])
    mat, meta, useful = (project.cache_load(f"{key}_{p}") for p in ("m", "a", "c"))
    if mat is not None and meta is not None and useful is not None:
        elig = meta["eligible_rows"]
        if np.array_equal(elig, np.flatnonzero(ctx.eligible)):
            return CandidateMatrix(useful, elig, ctx.blocks["metal"].to_numpy(float)[elig],
                                   ctx.baseline.dist[elig], mat.tocsc(),
                                   ctx.thresholds.for_rank(ctx.target.target),
                                   int(meta["n_dropped"][0]), ctx.xyz[elig], ctx.interval)
    cm = build_candidate_matrix(ctx, cands)
    project.cache_save(f"{key}_m", cm.matrix)
    project.cache_save(f"{key}_a", {"eligible_rows": cm.eligible_rows,
                                    "n_dropped": np.array([cm.n_dropped])})
    project.cache_save(f"{key}_c", cm.candidates)
    return cm


# --------------------------------------------------------------------------- scenarios

@dataclass
class ScenarioRun:
    scenario_id: str
    settings: dict
    results: dict[str, pd.DataFrame]


def blocks_for_budget(wide: pd.DataFrame, i: int) -> pd.DataFrame:
    """Block-level table for budget index i, in the layout exports.blocks_table expects."""
    base = wide[["block_id", "uploaded_class", "baseline_metric", "baseline_class",
                 "tonnes", "metal"]].copy()
    base["post_metric"] = wide[f"post_metric_{i}"]
    base["post_class"] = wide[f"post_class_{i}"]
    base["converted"] = wide[f"converted_{i}"]
    return base[["block_id", "uploaded_class", "baseline_metric", "baseline_class",
                 "post_metric", "post_class", "converted", "tonnes", "metal"]]


def run_scenario(project: Project, name: str, settings: dict | None = None,
                 progress: Callable[[str, float], None] | None = None,
                 scenario_id: str | None = None) -> ScenarioRun:
    """Run every budget in the planning settings and save the scenario.

    ``settings`` defaults to the project's current settings; pass a stored
    scenario's settings to rerun it exactly. Pass ``scenario_id`` to recalculate
    that scenario in place instead of saving a new one.
    """
    settings = copy.deepcopy(settings or project.settings)
    planning = settings.setdefault("planning", default_planning())
    say = progress or (lambda msg, frac: None)

    say("Loading inputs and baseline geometry", 0.02)
    sites = load_sites(project, settings)
    ctx = build_project_context(project, settings, planning)
    say("Building candidate distances", 0.15)
    cm = build_project_matrix(project, ctx, sites, planning, settings)
    manual = load_manual(project, sites, settings) if planning.get("use_manual", True) else None
    locked = manual[manual["locked"]] if manual is not None else None
    opt, cost = optimiser_of(planning), cost_of(planning)

    def budget_progress(done, total):
        say(f"Optimised budget {done} of {total}", 0.2 + 0.7 * done / total)

    runs = run_budgets(ctx, cm, locked, planning["budgets"], planning["mode"], cost, opt,
                       budget_progress)
    wide = runs[0].result.blocks[["block_id", "uploaded_class", "baseline_metric",
                                  "baseline_class", "eligible", "discrepancy", "tonnes",
                                  "metal"]].copy() if runs else pd.DataFrame()
    for i, r in enumerate(runs):
        b = r.result.blocks
        wide[f"post_metric_{i}"] = b["post_metric"].to_numpy()
        wide[f"post_class_{i}"] = b["post_class"].to_numpy()
        wide[f"converted_{i}"] = b["converted"].to_numpy()
    summary = summary_frame(runs)
    summary["locked_overrun"] = [r.locked_overrun for r in runs]
    results = {"summary": summary, "holes": holes_frame(runs), "blocks": wide}

    if manual is not None and len(manual):
        say("Comparing with the manual plan", 0.92)
        comp = compare_manual(ctx, cm, manual, cost, opt)
        results["comparison"] = comp.table
        results["manual_holes"] = manual
        results["comparison_holes"] = comp.optimised.holes.assign(budget=comp.optimised.budget)

    eligible = ctx.eligible
    warnings = sorted({w for r in runs for w in r.result.warnings})
    if manual is not None and len(manual):
        warnings += [f"Manual plan: {w}" for w in comp.manual.warnings]
    snapshot = {
        "name": name,
        "disclaimer": DISCLAIMER,
        "input_hashes": project.input_hashes(),
        "blocks": settings["blocks"], "drilling": settings["drilling"],
        "sites": settings["sites"], "manual": settings.get("manual"),
        "planning": planning,
        "run_info": {
            "eligible_blocks": int(eligible.sum()),
            "eligible_metal": float(ctx.blocks["metal"].to_numpy()[eligible].sum()),
            "discrepancy_metal": float(ctx.blocks["metal"].to_numpy()[ctx.discrepancy].sum()),
            "candidates_used": int(cm.matrix.shape[1]),
            "candidates_dropped": int(cm.n_dropped),
            "warnings": warnings,
            "log": [line for r in runs for line in [f"Budget {r.budget:,.0f}:"] + r.log],
        },
    }
    say("Saving scenario", 0.97)
    sid = project.save_scenario(snapshot, results, scenario_id)
    say("Done", 1.0)
    stored, stored_results = project.load_scenario(sid)
    return ScenarioRun(sid, stored, stored_results)
