"""Project page: create or open a project, upload inputs, map columns, preview the baseline.

UI only. Every calculation is an engine call (pipeline, blockmodel, drilling).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import ui_common
from engine import blockmodel, pipeline
from engine.schema import UPLOADED_LABELS, ClassRank
from engine.storage import Project, sha256_bytes

NONE = "(none)"
CONSTANT = "(use a constant)"
CLASS_CHOICES = [UPLOADED_LABELS[r] for r in (ClassRank.MEASURED, ClassRank.INDICATED,
                                              ClassRank.INFERRED, ClassRank.NONE)]
_RANK_BY_LABEL = {v: int(k) for k, v in UPLOADED_LABELS.items()}
_LABEL_BY_RANK = {int(k): v for k, v in UPLOADED_LABELS.items()}
MAX_CLASS_VALUES = 50

ALIASES = {
    "x": ["x", "xc", "east", "easting", "xcentre", "xcenter", "xmid", "xm"],
    "y": ["y", "yc", "north", "northing", "ycentre", "ycenter", "ymid", "ym"],
    "z": ["z", "zc", "rl", "elev", "elevation", "zcentre", "zcenter", "zmid", "zm"],
    "dx": ["dx", "xinc", "xsize", "sx", "dimx", "xdim"],
    "dy": ["dy", "yinc", "ysize", "sy", "dimy", "ydim"],
    "dz": ["dz", "zinc", "zsize", "sz", "dimz", "zdim"],
    "density": ["density", "dens", "sg", "bd"],
    "class_raw": ["class", "rescat", "category", "resclass", "res_class", "classification"],
    "grade": ["grade", "au", "au_gpt", "cu", "cu_pct", "au_ppm"],
    "block_id": ["block_id", "blockid", "bid"],
    "domain": ["domain", "dom", "zone"],
    "parent_id": ["parent", "parent_id", "parentid"],
    "hole_id": ["hole", "holeid", "hole_id", "bhid", "dhid", "id"],
    "valid": ["valid", "use", "flag"],
    "max_depth": ["max_depth", "maxdepth", "depth", "eoh", "total_depth", "td"],
    "depth": ["depth", "survdepth", "surveydepth", "at", "md"],
    "azimuth": ["azimuth", "az", "azi", "bearing"],
    "dip": ["dip", "inclination", "incl"],
    "from": ["from", "depth_from", "from_m"],
    "to": ["to", "depth_to", "to_m"],
    "site_id": ["site", "siteid", "site_id", "pad"],
    "length": ["length", "len", "depth", "planned_depth", "total_depth"],
}


# --------------------------------------------------------------------------- cached engine calls

@st.cache_data(show_spinner=False)
def _columns(root: str, kind: str, digest: str) -> list[str]:
    df = Project.open(Path(root)).load_input(kind)
    return [str(c) for c in df.columns] if df is not None else []


@st.cache_data(show_spinner=False)
def _distinct(root: str, kind: str, digest: str, column: str) -> list[str]:
    df = Project.open(Path(root)).load_input(kind)
    return blockmodel.distinct_values(df, column)


@st.cache_data(show_spinner="Reading the block model...")
def _block_preview(root: str, hashes: str, blocks_json: str) -> dict:
    project = Project.open(Path(root))
    imp, selected = pipeline.load_blocks(project, {"blocks": json.loads(blocks_json)})
    return {"n_rows": imp.n_rows, "n_invalid": imp.n_invalid,
            "reasons": imp.invalid_reasons, "unmapped": imp.unmapped_classes,
            "n_selected": len(selected), "summary": blockmodel.summarise_by_class(selected)}


@st.cache_data(show_spinner="Reading the existing drilling...")
def _drilling_preview(root: str, hashes: str, drilling_json: str, interval: float) -> dict:
    project = Project.open(Path(root))
    imp = pipeline.load_drilling(project, {"drilling": json.loads(drilling_json)}, interval)
    return {"n_rows": imp.n_rows, "n_dropped": imp.n_dropped, "reasons": imp.dropped_reasons,
            "assumptions": imp.assumptions, "n_points": len(imp.points),
            "n_holes": int(imp.points["hole_id"].nunique())}


@st.cache_data(show_spinner="Measuring baseline drilling geometry (can take a minute)...")
def _baseline(root: str, hashes: str, settings_json: str, planning_json: str) -> dict:
    project = Project.open(Path(root))
    ctx = pipeline.build_project_context(project, json.loads(settings_json),
                                         json.loads(planning_json))
    return {"rank": ctx.baseline_rank, "metal": ctx.blocks["metal"].to_numpy(float),
            "discrepancy": ctx.discrepancy, "eligible": ctx.eligible}


# --------------------------------------------------------------------------- widget helpers

def _guess(field: str, columns: list[str]) -> str | None:
    wanted = ALIASES.get(field, [field])
    lower = {c.strip().lower(): c for c in columns}
    for w in wanted:
        if w in lower:
            return lower[w]
    return None


def pick(label: str, columns: list[str], key: str, field: str, saved: str | None,
         optional: bool = False, help: str | None = None) -> str | None:
    """Selectbox of file columns. Pre-fills from saved settings, else a name guess."""
    default = saved if saved in columns else _guess(field, columns)
    if optional:
        options = [NONE] + columns
        value = st.selectbox(label, options, index=options.index(default) if default else 0,
                             key=key, help=help)
        return None if value == NONE else value
    return st.selectbox(label, columns, index=columns.index(default) if default else None,
                        key=key, placeholder="Choose a column", help=help)


def pick_group(spec: list[tuple[str, str, bool]], columns: list[str], saved: dict,
               key: str) -> dict | None:
    """Selectboxes for (field, label, optional) rows. None if a required field is empty."""
    out, missing = {}, []
    for field, label, optional in spec:
        v = pick(label, columns, f"{key}|{field}", field, saved.get(field), optional)
        if v:
            out[field] = v
        elif not optional:
            missing.append(label)
    if missing:
        st.warning("Still to choose: " + ", ".join(missing) + ".")
        return None
    return out


def guess_class(raw: str) -> str:
    t = raw.strip().lower()
    if t in ("1", "measured") or t.startswith("meas"):
        return "Measured"
    if t in ("2", "indicated") or t.startswith("ind"):
        return "Indicated"
    if t in ("3", "inferred") or t.startswith("inf"):
        return "Inferred"
    return "Unclassified"


def _parse_sentinels(text: str) -> list[float] | None:
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            st.error(f"'{part}' is not a number. Enter null values separated by commas.")
            return None
    return out


def _fmt_sentinels(values: list) -> str:
    return ", ".join(f"{float(v):g}" for v in values)


def upload_slot(project: Project, kind: str, label: str, key: str) -> bool:
    """File uploader for one input kind. Returns True if a file is stored."""
    up = st.file_uploader(label, type=["csv"], key=f"{key}|upload|{kind}")
    if up is not None:
        data = up.getvalue()
        if project.input_hashes().get(kind) != sha256_bytes(data):  # skip on plain reruns
            try:
                project.save_input(kind, data, up.name)
            except ValueError as exc:
                st.error(f"Could not read {up.name}: {exc}")
    stored = project.settings.get("inputs", {}).get(kind)
    if stored:
        st.caption(f"Stored file: **{stored['filename']}**")
    return bool(stored)


# --------------------------------------------------------------------------- page

ui_common.page_setup("Project")

# 1. Create or open --------------------------------------------------------------------------
st.header("1. Project")
existing = Project.list_projects(ui_common.PROJECTS_DIR)
c1, c2 = st.columns(2)
with c1:
    new_name = st.text_input("New project name", key="new_project_name")
    if st.button("Create project"):
        try:
            ui_common.set_project(Project.create(ui_common.PROJECTS_DIR, new_name))
            st.rerun()
        except FileExistsError:
            st.error("A project with that name already exists. Choose another name, or open "
                     "the existing one.")
        except ValueError as exc:
            st.error(f"That name cannot be used: {exc}")
with c2:
    if existing:
        chosen = st.selectbox("Open an existing project", existing, key="open_project_name")
        if st.button("Open project"):
            ui_common.set_project(Project.open(ui_common.PROJECTS_DIR / chosen))
            st.rerun()
    else:
        st.caption("No saved projects yet.")

project = ui_common.require_project()
pkey = project.root.name
root = str(project.root)
settings = project.settings
st.success(f"Open project: **{settings.get('name', pkey)}**")

drafts: dict[str, dict | None] = {}


def K(name: str) -> str:
    return f"{pkey}|{name}"


# 2/3. Block model ---------------------------------------------------------------------------
st.header("2. Block model")
has_blocks = upload_slot(project, "blocks", "Block model (CSV)", pkey)
blocks_draft = None
if has_blocks:
    sb = settings.get("blocks", {})
    dig = project.input_hashes()["blocks"]
    cols = _columns(root, "blocks", dig)
    saved_cols = sb.get("columns", {})
    st.subheader("Match your columns")
    left, right = st.columns(2)
    with left:
        mapped = pick_group(
            [("x", "Centroid easting X (m)", False), ("y", "Centroid northing Y (m)", False),
             ("z", "Centroid elevation Z (m)", False), ("density", "Density (t/m³)", False),
             ("class_raw", "Resource class column", False), ("grade", "Grade column", False)],
            cols, saved_cols, K("blk"))
    with right:
        extra = pick_group(
            [("block_id", "Block ID (optional)", True), ("domain", "Domain (optional)", True),
             ("parent_id", "Parent block ID (optional, stored only)", True)],
            cols, saved_cols, K("blk"))
    st.markdown("**Block size**: choose a column, or one constant size for every block.")
    dims, consts = {}, {}
    dcols = st.columns(3)
    for col_ui, f in zip(dcols, ("dx", "dy", "dz"), strict=True):
        with col_ui:
            default = saved_cols.get(f) if saved_cols.get(f) in cols else (
                None if f in sb.get("constant_dims", {}) else _guess(f, cols))
            options = [CONSTANT] + cols
            v = st.selectbox(f"Block size {f[1].upper()} ({f}, m)", options, key=K(f"dim|{f}"),
                             index=options.index(default) if default else 0)
            if v == CONSTANT:
                consts[f] = st.number_input(
                    f"Constant {f} (m)", min_value=0.001, format="%g", key=K(f"const|{f}"),
                    value=float(sb.get("constant_dims", {}).get(f, 10.0)))
            else:
                dims[f] = v
    unit = st.radio("Grade unit", ["%", "g/t"], horizontal=True, key=K("unit"),
                    index=["%", "g/t"].index(sb.get("grade_unit", "%")),
                    format_func=lambda u: f"{u}  (metal reported in {'t' if u == '%' else 'kg'})")

    class_map: dict[str, int] = {}
    if mapped and mapped.get("class_raw"):
        st.markdown("**Resource class values**: say what each value in your class column means.")
        values = _distinct(root, "blocks", dig, mapped["class_raw"])
        if len(values) > MAX_CLASS_VALUES:
            st.error(f"The class column has {len(values)} different values, which looks like "
                     "the wrong column. Choose a column with only a few class codes.")
            mapped = None
        else:
            saved_map = sb.get("class_map", {})
            ccols = st.columns(min(max(len(values), 1), 4))
            for i, v in enumerate(values):
                default = (_LABEL_BY_RANK.get(int(saved_map[v])) if v in saved_map
                           else guess_class(v))
                with ccols[i % len(ccols)]:
                    choice = st.selectbox(f"'{v}' means", CLASS_CHOICES, key=K(f"cls|{v}"),
                                          index=CLASS_CHOICES.index(default))
                class_map[v] = _RANK_BY_LABEL[choice]

    sent_text = st.text_input(
        "Null values (comma-separated; blank cells are always treated as null)",
        value=_fmt_sentinels(sb.get("null_sentinels", [-99.0, -999.0])), key=K("sentinels"))
    sentinels = _parse_sentinels(sent_text)

    domains: list[str] = []
    if extra and extra.get("domain"):
        dvals = _distinct(root, "blocks", dig, extra["domain"])
        domains = st.multiselect(
            "Domains to include (leave empty for all blocks)", dvals, key=K("domains"),
            default=[d for d in sb.get("domains", []) if d in dvals],
            help="Only blocks in the chosen domains count toward the objective. "
                 "Drilling is never filtered by domain.")

    if mapped is not None and extra is not None and sentinels is not None:
        columns = {**mapped, **extra, **dims}
        blocks_draft = {"columns": columns, "constant_dims": consts, "grade_unit": unit,
                        "class_map": class_map, "null_sentinels": sentinels,
                        "domains": domains}
drafts["blocks"] = blocks_draft

# 4. Existing drilling -----------------------------------------------------------------------
st.header("3. Existing drilling")
sd = settings.get("drilling", {})
route_labels = {"A": "Route A: desurveyed samples",
                "B": "Route B: collars, surveys, optional intervals"}
route = st.radio("How is your existing drilling supplied?", list(route_labels), key=K("route"),
                 index=list(route_labels).index(sd.get("route", "A")),
                 format_func=route_labels.get)
drill_draft = None
if route == "A":
    has = upload_slot(project, "drilling", "Desurveyed samples (CSV)", pkey)
    if has:
        cols = _columns(root, "drilling", project.input_hashes()["drilling"])
        m = pick_group(
            [("hole_id", "Hole ID", False), ("x", "Sample easting X (m)", False),
             ("y", "Sample northing Y (m)", False), ("z", "Sample elevation Z (m)", False),
             ("valid", "Valid flag (optional; rows flagged false are dropped)", True),
             ("domain", "Domain (optional; stored but not used)", True)],
            cols, sd.get("mapping", {}), K("drillA"))
        if m:
            drill_draft = {"route": "A", "mapping": m}
else:
    has_c = upload_slot(project, "collars", "Collars (CSV)", pkey)
    has_s = upload_slot(project, "surveys", "Surveys (CSV)", pkey)
    has_i = upload_slot(project, "intervals", "Sample intervals (CSV, optional)", pkey)
    ih = project.input_hashes()
    parts: dict = {}
    if has_c:
        st.markdown("**Collars**")
        parts["collars"] = pick_group(
            [("hole_id", "Hole ID", False), ("x", "Collar easting X (m)", False),
             ("y", "Collar northing Y (m)", False), ("z", "Collar elevation Z (m)", False),
             ("max_depth", "Final depth (m, optional)", True)],
            _columns(root, "collars", ih["collars"]), sd.get("collars", {}), K("collars"))
    if has_s:
        st.markdown("**Surveys**")
        parts["surveys"] = pick_group(
            [("hole_id", "Hole ID", False), ("depth", "Survey depth (m)", False),
             ("azimuth", "Azimuth (degrees)", False), ("dip", "Dip (degrees)", False)],
            _columns(root, "surveys", ih["surveys"]), sd.get("surveys", {}), K("surveys"))
    if has_i:
        st.markdown("**Sample intervals**")
        parts["intervals"] = pick_group(
            [("hole_id", "Hole ID", False), ("from", "From depth (m)", False),
             ("to", "To depth (m)", False)],
            _columns(root, "intervals", ih["intervals"]), sd.get("intervals", {}), K("ints"))
    pos_down = st.checkbox("Dip is positive downward", value=bool(sd.get("positive_down", False)),
                           key=K("drill_posdown"))
    if parts.get("collars") and parts.get("surveys") and (not has_i or parts.get("intervals")):
        drill_draft = {"route": "B", "collars": parts["collars"], "surveys": parts["surveys"],
                       "positive_down": pos_down}
        if has_i:
            drill_draft["intervals"] = parts["intervals"]
drafts["drilling"] = {**sd, **drill_draft} if drill_draft is not None else None

# 5. Sites -----------------------------------------------------------------------------------
st.header("4. Potential drill sites")
has_sites = upload_slot(project, "sites", "Potential drill sites (CSV)", pkey)
sites_draft = None
if has_sites:
    m = pick_group(
        [("site_id", "Site ID", False), ("x", "Site easting X (m)", False),
         ("y", "Site northing Y (m)", False), ("z", "Site elevation Z (m)", False)],
        _columns(root, "sites", project.input_hashes()["sites"]),
        settings.get("sites", {}).get("columns", {}), K("sites"))
    if m:
        sites_draft = {"columns": m}
drafts["sites"] = sites_draft

# 6. Manual plan -----------------------------------------------------------------------------
st.header("5. Manual plan (optional)")
has_manual = upload_slot(project, "manual", "Manual drilling plan (CSV)", pkey)
manual_draft = None
if has_manual:
    sm = settings.get("manual", {})
    m = pick_group(
        [("hole_id", "Hole ID", False), ("site_id", "Site ID (optional)", True),
         ("x", "Collar easting X (m)", False), ("y", "Collar northing Y (m)", False),
         ("z", "Collar elevation Z (m)", False), ("azimuth", "Azimuth (degrees)", False),
         ("dip", "Dip (degrees)", False), ("length", "Planned length (m)", False)],
        _columns(root, "manual", project.input_hashes()["manual"]), sm.get("columns", {}),
        K("manual"))
    mc1, mc2 = st.columns(2)
    with mc1:
        mpos = st.checkbox("Dip is positive downward", value=bool(sm.get("positive_down", False)),
                           key=K("manual_posdown"))
    with mc2:
        tol = st.number_input("Site match tolerance (m)", min_value=0.0, format="%g",
                              value=float(sm.get("match_tolerance", 1.0)), key=K("manual_tol"),
                              help="A hole with no site ID is matched to a site whose collar "
                                   "is within this distance.")
    if m:
        manual_draft = {"columns": m, "positive_down": mpos, "match_tolerance": tol,
                        "locked": list(sm.get("locked", []))}  # lock boxes live on Planning
drafts["manual"] = manual_draft

# 7. Save ------------------------------------------------------------------------------------
st.header("6. Save")
if st.button("Save mappings", type="primary"):
    ready = {k: v for k, v in drafts.items() if v is not None}
    if not ready:
        st.warning("Nothing to save yet. Upload a file and finish its column choices first.")
    else:
        project.save_settings({**project.settings, **ready})
        settings = project.settings
        files_for = {"blocks": ["blocks"], "sites": ["sites"], "manual": ["manual"],
                     "drilling": ["drilling"] if route == "A" else ["collars", "surveys"]}
        incomplete = [k for k, v in drafts.items()
                      if v is None and any(f in project.input_hashes() for f in files_for[k])]
        st.success("Saved: " + ", ".join(sorted(ready)) + ".")
        if incomplete:
            st.warning("Not saved because the column choices are incomplete: "
                       + ", ".join(sorted(set(incomplete))) + ".")

# 8. Baseline preview ------------------------------------------------------------------------
st.header("7. Baseline preview")
st.caption("The preview uses your saved mappings.")
hashes = json.dumps(project.input_hashes(), sort_keys=True)
mu = ui_common.metal_label(settings)
sb, sdr = settings.get("blocks"), settings.get("drilling")
planning = settings.get("planning") or pipeline.default_planning()
planning_json = json.dumps(planning, sort_keys=True)
inputs = project.input_hashes()

if not sb or "blocks" not in inputs:
    st.info("Upload the block model and save its column mapping to see the block summary.")
else:
    try:
        bp = _block_preview(root, hashes, json.dumps(sb, sort_keys=True))
    except (ValueError, KeyError) as exc:
        st.error(f"The block model could not be read with the saved mapping: {exc}")
        bp = None
    if bp:
        st.subheader("Block model")
        m1, m2, m3 = st.columns(3)
        m1.metric("Rows in file", f"{bp['n_rows']:,}")
        m2.metric("Invalid rows (excluded)", f"{bp['n_invalid']:,}")
        m3.metric("Valid rows in selected domains", f"{bp['n_selected']:,}")
        if bp["reasons"]:
            st.write("Invalid rows by reason: " + "; ".join(
                f"{k}: {v:,}" for k, v in bp["reasons"].items()))
        if bp["unmapped"]:
            st.warning("Class values with no mapping (counted as Unclassified): "
                       + ", ".join(bp["unmapped"]))
        table = bp["summary"].rename(columns={
            "class": "Class", "rows": "Rows", "volume": "Volume (m³)",
            "tonnes": "Tonnes (t)", "metal": f"Metal ({mu})"})
        st.dataframe(table.style.format({"Rows": "{:,.0f}", "Volume (m³)": "{:,.0f}",
                                         "Tonnes (t)": "{:,.0f}", f"Metal ({mu})": "{:,.2f}"}),
                     hide_index=True)

drill_ok = bool(sdr) and (("drilling" in inputs) if sdr.get("route", "A") == "A"
                          else ("collars" in inputs and "surveys" in inputs))
if not sdr or not drill_ok:
    st.info("Upload the existing drilling and save its column mapping to see the drilling "
            "summary.")
else:
    try:
        dp = _drilling_preview(root, hashes, json.dumps(sdr, sort_keys=True),
                               float(planning["support_interval"]))
    except (ValueError, KeyError) as exc:
        st.error(f"The existing drilling could not be read with the saved mapping: {exc}")
        dp = None
    if dp:
        st.subheader("Existing drilling")
        d1, d2, d3 = st.columns(3)
        d1.metric("Rows in file", f"{dp['n_rows']:,}")
        d2.metric("Rows dropped", f"{dp['n_dropped']:,}")
        d3.metric("Support points kept", f"{dp['n_points']:,}", f"{dp['n_holes']:,} holes",
                  delta_color="off")
        if dp["reasons"]:
            st.write("Dropped rows by reason: " + "; ".join(
                f"{k}: {v:,}" for k, v in dp["reasons"].items()))
        for a in dp["assumptions"]:
            st.caption(f"Assumption: {a}")

if sb and "blocks" in inputs and sdr and drill_ok:
    try:
        bl = _baseline(root, hashes, json.dumps({"blocks": sb, "drilling": sdr}, sort_keys=True),
                       planning_json)
    except (ValueError, KeyError) as exc:
        st.error(f"The baseline geometry could not be calculated: {exc}")
        bl = None
    if bl:
        st.subheader("Baseline drilling geometry")
        th = planning["thresholds"]
        st.caption(f"Geometry classes use the planning thresholds: Measured ≤ {th['measured']:g} m, "
                   f"Indicated ≤ {th['indicated']:g} m, Inferred ≤ {th['inferred']:g} m "
                   "(change them on the Planning page).")
        rank, metal = bl["rank"], bl["metal"]
        rows = [{"Baseline geometry class": ui_common.geometry_label(r),
                 "Blocks": int((rank == int(r)).sum()),
                 f"Metal ({mu})": float(metal[rank == int(r)].sum())}
                for r in (ClassRank.MEASURED, ClassRank.INDICATED, ClassRank.INFERRED,
                          ClassRank.NONE)]
        st.dataframe(pd.DataFrame(rows).style.format({"Blocks": "{:,.0f}",
                                                      f"Metal ({mu})": "{:,.2f}"}),
                     hide_index=True)
        src = ui_common.uploaded_label(planning["source_class"])
        tgt = ui_common.geometry_label(planning["target_class"])
        e1, e2 = st.columns(2)
        e1.metric(f"Baseline discrepancy: {src} blocks already at {tgt}",
                  f"{int(bl['discrepancy'].sum()):,} blocks",
                  f"{float(metal[bl['discrepancy']].sum()):,.2f} {mu}", delta_color="off")
        e2.metric(f"Eligible to convert: {src} blocks below {tgt}",
                  f"{int(bl['eligible'].sum()):,} blocks",
                  f"{float(metal[bl['eligible']].sum()):,.2f} {mu}", delta_color="off")
ui_common.disclaimer()
