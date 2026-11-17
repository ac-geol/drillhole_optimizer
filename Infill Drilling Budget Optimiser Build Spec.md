# Infill Drilling Budget Optimiser: Build Spec

Nov 16, 2026 · @Alex

## 1. Review summary

The plan is sound and is kept almost intact. The changes below close gaps that would otherwise produce wrong or gameable results, or leave the builder guessing. Status: draft for review, no code written.

| # | Change | Why |
| --- | --- | --- |
| 1 | One hole per trace: candidates sharing site, azimuth and dip but differing in length are mutually exclusive | Otherwise a 100 m and a 200 m hole on the same line count as two distinct holes in the three-hole metric |
| 2 | Optional minimum angular separation between selected holes at one site (default 10 degrees) | A tight fan from one collar can satisfy the three-hole rule near the collar with almost no real spatial coverage |
| 3 | Calculation engine is a separate Python package with no Streamlit imports | Makes the acceptance tests runnable, and lets the UI be replaced later without touching the maths |
| 4 | One `evaluate_campaign()` function scores every campaign, manual or optimised | Guarantees identical campaigns give identical results (acceptance test 10) |
| 5 | Storage is fixed: project folders with JSON settings and Parquet data, no SQLite | Simpler, inspectable, easy to back up or copy between machines |
| 6 | Threshold comparisons use a 1e-6 m tolerance | Makes boundary tests deterministic under floating point |
| 7 | Exact search cap of 3 x threshold for hole distances | A hole further than 3T can never be part of a trio with mean <= T, so this prunes work with no loss of accuracy |
| 8 | Proposed-hole support interval defaults to 2 m | Discretisation overstates distance by up to half the interval. 5 m would be a 10% error against a 25 m threshold |
| 9 | Dip sign toggle on manual plan and survey imports | Many mine planning exports use positive-down dips. The internal convention stays negative-down |
| 10 | Null sentinel handling on block model import (for example -99, -999, blank) | Common in block model exports and would corrupt tonnage and metal totals |
| 11 | Deficit tie-breaker is defined precisely, and a final prune pass removes holes that contribute no conversion | Blocks needing three new holes cannot be found by single or pair moves alone. The prune stops budget being spent on progress that never completes |
| 12 | Higher budgets are warm-started from the lower-budget result in independent mode | A heuristic can otherwise return less conversion at a higher budget, which looks broken on the chart |
| 13 | Explicit behaviour when locked holes exceed the budget | Report the overrun and add nothing. The original plan did not say |
| 14 | Pre-run size estimate with a warning | Candidate count x block count can exhaust memory. The user should see this before a run, not during |
| 15 | Three extra acceptance tests (same-trace exclusion, site setup costing, stale-input detection) | Cover the new rules and one existing rule that had no test |
| 16 | Maximum holes per site (default 10, editable) | Added after review: more than about 10 holes from one collar is not a realistic campaign |

Items 1 and 2 are the only ones that change results. The rest are build decisions.

## 2. Decisions needed from you

All six are settled as of 16 Nov 2026. Your notes sit under items 1 and 6, and the other four use the defaults shown.

- [ ] **Data scale.** Assumed: up to 500,000 block rows after domain filtering, 200,000 existing support points, 5,000 candidate holes. Is that the right order of magnitude?
  - [ ] 100-1000 existing drillholes. 500-10000 composites / samples. 100,000 to 1,000,000 resource blocks. I think there would be a realistic max of 50 drill locations. perhaps 1-10 holes per collar but more would be a lot.
- [ ] **Minimum angular separation** (change 2). Default on at 10 degrees, editable. Alternative: off by default.
- [ ] **Where it runs.** Assumed: your own machine first (`streamlit run`), shared server later.
- [ ] **Drillhole domain field.** Default: stored but ignored, so every valid sample counts as support regardless of domain. Alternative: a toggle to count only in-domain samples, which would bias results toward planned holes because they carry no domain coding.
- [ ] **Dip sign in your manual plans.** Default import setting: negative down. Tell me if your exports are positive down and I will flip the default.
- [ ] **Ounces.** For g/t grades, report troy ounces alongside kilograms? Default: yes, as an extra column.
  - [ ] either report imperial units or metric. we don't need both.

## 3. Scope, assumptions and conventions

The tool ranks drilling campaigns by potential geometric conversion of one metal within a budget. It is a planning aid, not a resource classification tool.

- **Users:** site geologists, through a browser, with no code, notebooks or config files.
- **Deployment:** trusted internal use, single user at a time, no authentication.
- **Units (v1):** metres, t/m3, grade in % or g/t chosen explicitly. All conversions live in one `units` module so imperial can be added later without touching the engine. A project reports in one unit system only, so g/t metal is in kilograms with no ounce column.
- **Coordinates:** one projected system and elevation datum for all inputs. No transformations.
- **Angles:** azimuth clockwise from north in degrees, dip negative downward, Z positive upward.
- **Support assumption:** proposed holes provide valid sampling along their full length. Stated on every results screen.
- **Geometry:** isotropic Euclidean distance to block centroids.
- **Terminology:** results say "potentially converted" and "best-found plan", never "converted" or "optimal".
- **Standard disclaimer** on every results screen and export summary: "Planning estimate based on geometric drilling support. Not a resource classification declaration. Geological and QP review required."

## 4. Architecture and repo layout

Two layers: a pure Python engine that does all calculation, and a thin Streamlit app that only collects inputs and displays outputs.

- **Stack:** Python 3.11+, pandas, NumPy, SciPy (`cKDTree`, sparse matrices), PyArrow (Parquet), Streamlit, Plotly, pytest.
- **Rule:** nothing under `engine/` imports Streamlit. The UI calls engine functions and never reimplements a calculation.
- **Caching:** Streamlit reruns the script on every interaction. Expensive steps (import, baseline distances, candidate distances) are cached on a hash of their inputs and settings, and also written to the project's `cache/` folder so a restart does not recompute them.
- **Uploads:** raise Streamlit's upload limit (default 200 MB) to 2 GB in `.streamlit/config.toml`. Convert every uploaded CSV to Parquet on import and keep the original.
- **Determinism:** one seeded NumPy generator per run. Ties broken by candidate ID. No unordered set iteration in the optimiser.

```
infill-optimiser/
  app.py                      # Streamlit entry point
  pages/
    1_Project.py
    2_Planning.py
    3_Results.py
    4_Scenarios.py
  engine/
    units.py                  # grade units, metal units, future imperial
    blockmodel.py             # import, mapping, volume, tonnage, metal
    drilling.py               # Route A import; Route B desurvey (milestone 8)
    holes.py                  # straight-hole geometry, support points
    candidates.py             # candidate grid generation, exclusion groups
    geometry.py               # nearest-three metric, classes
    costs.py                  # campaign cost model
    evaluate.py               # evaluate_campaign(): single source of truth
    optimise.py               # heuristic search
    scenarios.py              # budget runs, manual comparison
    storage.py                # projects, scenarios, hashes, stale checks
    exports.py                # CSV and JSON writers
  tests/
    synthetic.py              # labelled synthetic dataset builders
    test_*.py                 # one file per acceptance test group
  projects/                   # created at runtime, see section 11
  .streamlit/config.toml
  pyproject.toml
  README.md                   # install and run in three commands
```

## 5. Inputs and data model

Four CSV inputs, each mapped through the GUI into a fixed internal table. Only the block model, existing drilling and sites are required to optimise. The manual plan is optional.

### 5.1 Block model

| Internal field | Required | Notes |
| --- | --- | --- |
| `block_id` | No | Row index used if absent |
| `x`, `y`, `z` | Yes | Block centroid |
| `dx`, `dy`, `dz` | Yes | Column or a constant entered in the GUI. Always the row's own dimensions, never the parent's |
| `density` | Yes | t/m3 |
| `class_raw` | Yes | Uploaded classification, never overwritten |
| `grade` | Yes | One column chosen per scenario, with unit % or g/t |
| `domain` | No | Dropdown or multiselect filter |
| `parent_id` | No | Stored only |

- **Class mapping:** each distinct `class_raw` value is mapped to Measured, Indicated, Inferred or Unclassified.
- **Null sentinels:** user-editable list (default -99, -999, blank). Rows with null density or grade are excluded from totals and counted in the preview.
- **Derived:** `volume = dx * dy * dz`, `tonnes = volume * density`, `metal = tonnes * grade / 100` (t, for %) or `tonnes * grade / 1000` (kg, for g/t).
- **Assumption:** rows are non-overlapping volumes. Not validated in v1.
- **Preview:** row count, tonnes and contained metal by mapped class for the current domain selection.
- **Domain filter** selects which blocks count toward the objective. It never removes drilling.

### 5.2 Existing drilling

Internal form: `hole_id`, `x`, `y`, `z`, optional `valid`, optional `domain` (stored, not used, see decision 4).

- **Route A (milestone 2):** desurveyed CSV of sample or interval-midpoint coordinates. Rows with `valid` false are dropped. No validity column means all rows count.
- **Route B (milestone 8):** collar, survey and optional interval CSVs, desurveyed by minimum curvature to interval midpoints. Without intervals, generate trace points at the support interval and label the assumption in results.

### 5.3 Potential drill sites

`site_id`, `x`, `y`, `z`. Candidate geometry comes from global GUI ranges (section 7). Per-site overrides are deferred.

### 5.4 Manual plan (optional)

`hole_id`, optional `site_id`, collar `x`, `y`, `z`, `azimuth`, `dip`, `length`.

- Import has a "dip is positive downward" toggle. Values are converted to the internal convention on import.
- A hole with no `site_id` is matched to a site whose collar lies within 1 m (editable). If none matches, its collar is treated as its own site.
- Each manual hole has a "lock" checkbox in the GUI.

## 6. Geometry engine

Every block gets one number, the mean distance to its nearest three distinct holes, and one geometry class from that number. All campaign results derive from comparing that class before and after adding planned holes.

### 6.1 Support points for planned holes

- Unit direction from azimuth `a` and dip `d` (negative down): `ux = cos(d) sin(a)`, `uy = cos(d) cos(a)`, `uz = sin(d)`.
- Points sit at the midpoints of consecutive intervals of length `s` from the collar: depths `s/2, 3s/2, ...`. A final short interval gets its own midpoint.
- `s` is the support interval, default 2 m, under Advanced settings. The same function and interval serve manual and generated holes.

### 6.2 Distance metric

1. For a block centroid, take the nearest valid support point on each distinct hole.
2. Keep the three holes with the smallest distances `d1 <= d2 <= d3`.
3. Metric = `(d1 + d2 + d3) / 3`, shown in the interface as "mean distance to nearest three holes".

- Fewer than three distinct holes within the search cap: metric is blank and the block is "outside the specified geometry criteria".
- **Search cap:** `R = 3 x largest threshold` (300 m at defaults). This is exact for classification, because a trio containing a hole beyond `3T` cannot have mean `<= T`.

### 6.3 Classes

| Geometry class | Default rule (editable) |
| --- | --- |
| Measured geometry | metric <= 25 m |
| Indicated geometry | metric <= 50 m |
| Inferred geometry | metric <= 100 m |
| Outside criteria | otherwise |

- Highest class satisfied wins. Comparison is `metric <= T + 1e-6`.
- The GUI rejects thresholds that are not strictly increasing.

### 6.4 Baseline computation

- Build a KD-tree on all valid existing support points.
- For each selected block, query the `k` nearest points within `R` (start `k = 32`). Walk them in distance order and keep the first three distinct hole IDs. Double `k` for blocks that found fewer than three and had more points available.
- Store per block: three distances, three hole IDs, metric, baseline geometry class. Cache to disk.

### 6.5 Eligibility and conversion

A scenario has a source class `S` (uploaded, default Indicated) and a target geometry class `G` (default Measured). `G` must rank above `S`.

| Term | Definition |
| --- | --- |
| Eligible block | Uploaded class is `S` and baseline geometry does not meet `G` |
| Baseline discrepancy | Uploaded class is `S` and baseline geometry already meets `G`. Reported separately, never as conversion |
| Potentially converted | Eligible and post-campaign geometry meets `G` |

### 6.6 Candidate distances

- Build a KD-tree on eligible block centroids.
- For each candidate hole, find blocks within `3 x T(G)` of any support point and keep the minimum distance per block.
- Keep an entry only if it is smaller than the block's baseline third distance, since otherwise the hole cannot enter the nearest three.
- Store as a sparse blocks x candidates matrix (CSC, float32). Candidates with no entries are dropped before optimisation.

### 6.7 evaluate\_campaign()

One function scores any list of planned holes. For each block it merges the baseline three distances with the distances from each campaign hole, keeps the three smallest, and returns metric, class, conversion flag, totals and cost.

- The optimiser calls it on eligible blocks using the sparse matrix.
- The final report calls the same function on all selected blocks at the full search cap, so the block-level export shows post-campaign class for every block.
- Manual plans and optimised plans both go through it, with no separate code path.

## 7. Candidate generation and cost model

### 7.1 Candidate holes

Candidates are every combination of site, azimuth, dip and length from the global GUI ranges (min, max, increment for each, ranges inclusive).

- **ID:** `{site_id}_A{az}_D{dip}_L{length}`, stable across runs.
- **Deduplication:** azimuth 360 equals 0. At dip -90 only one azimuth is generated.
- **Exclusion group:** candidates sharing site, azimuth and dip form one group. At most one hole per group can be selected (change 1). A locked manual hole on the same trace occupies the group.
- **Angular separation:** two holes at one site whose directions differ by less than the minimum angle (default 10 degrees, 0 disables) cannot both be selected (change 2). Applies to optimiser picks and locked holes. Manual plans are evaluated unchanged, with a warning listing any pairs that break the rule.
- **Size estimate:** the Planning page shows candidate count and an estimate of sparse-matrix entries before any run. It warns above 15,000 candidates (50 sites at 300 combinations each) or about 2 GB estimated memory and suggests coarser increments.

* **Holes per site:** a campaign holds at most 10 holes per site (editable). Locked holes count toward the cap. Manual plans are evaluated unchanged, with a warning if they exceed it.

### 7.2 Cost model

`cost = total metres x cost per metre + holes x fixed cost per hole + distinct sites x setup cost per site`

- Fixed cost and setup cost default to zero.
- Site setup is charged once per distinct site in the campaign. A candidate at a site already in the campaign adds no setup cost.
- Locked holes are costed first. If locked cost exceeds the budget, the run adds no holes and reports the overrun instead of failing.
- Holes are selected whole. Lengths are never trimmed to use up budget.
- Every scenario reports budget, planned cost, remaining budget, total metres, hole count and site count.

## 8. Optimiser

The optimiser maximises contained metal in potentially converted blocks subject to the budget, using a seeded greedy construction with pair moves, a prune pass and local search. Output is a best-found plan with no optimality guarantee.

### 8.1 Scores

- **Primary:** gain in potentially converted metal per unit of added cost.
- **Secondary (tie-breaker):** gain in progress score per unit of added cost. Used to rank moves with equal primary gain, including when no move converts anything.
- **Progress score:** for each eligible unconverted block, cap each of its three distances at `3T` (missing holes count as `3T`), take the mean, then `progress = 1 - max(0, mean - T) / (2T)`. The score is the sum of `metal x progress`. It is shown in the run log as "distance-deficit progress" and never reported as conversion.

### 8.2 Moves

- **Single:** add one feasible candidate.
- **Pair:** add two feasible candidates together. Pairs come from a shortlist: for each eligible block that no single candidate converts, take its 6 nearest useful candidates, form their pairs, weight each pair by the block's metal, and keep the top 2,000 pairs overall.
- **Feasible** means within remaining budget and consistent with exclusion groups and angular separation.

### 8.3 Procedure

1. Start from existing drilling plus locked holes. Stop here if locked cost exceeds budget.
2. **Construct:** repeatedly apply the best-scoring feasible move until none has a positive primary or secondary gain.
3. **Prune:** remove any unlocked hole whose removal leaves converted metal unchanged. Then refill using primary gain only.
4. **Local search:** try swaps (one selected unlocked hole for one unselected candidate touching the same blocks), additions and removals. Accept the first change that raises converted metal within budget. Stop when a full pass finds nothing, or after 20 passes.
5. **Restarts:** run 1 is deterministic. Later runs pick at random among the top 3 moves in step 2. One restart ranks by absolute gain instead of gain per cost.
6. Keep the best result by converted metal, then lower cost, then sorted hole IDs.

### 8.4 Settings (Advanced)

| Setting | Default |
| --- | --- |
| Restarts | 5 |
| Random seed | 42 |
| Pair shortlist size | 2,000 |
| Nearest candidates per block for pairs | 6 |
| Local search pass limit | 20 |
| Time limit per budget | 120 s, returns best so far |

### 8.5 Performance

- Baseline distances and the candidate matrix are computed once per project and geometry setting, then reused across budgets and restarts.
- Adding a hole updates only the blocks in its sparse column. Removals recompute affected blocks from the baseline plus the remaining campaign columns.
- Target at the confirmed scale (up to 1,000,000 blocks, 1,000 existing holes, 10,000 samples, 50 sites): under 2 minutes per budget on a laptop. This is a target to measure in milestone 5, not a promise.

## 9. Budget scenarios and manual comparison

Users enter several budgets and run them together in one of two modes.

| Mode | Behaviour |
| --- | --- |
| Independent | Each budget is optimised on its own. Budgets run in ascending order and each also tries the previous budget's plan as a starting point, so conversion never falls as budget rises |
| Expandable | The lower-budget campaign is locked and holes are added as budget increases |

Per budget, report: budget, planned cost, remaining budget, metres, holes, sites, potentially converted tonnes, potentially converted metal, metal per metre, metal per unit cost.

### Manual plan comparison

- Evaluate the manual plan unchanged through `evaluate_campaign()`.
- Run one optimisation with budget equal to the manual plan's cost, honouring any locked manual holes.
- Show the two side by side with the same metrics as above.
- Split converted blocks into three sets by block ID: both plans, manual only, optimised only. Report tonnes and metal for each.
- Fixed note under the comparison: "Greater geometric conversion does not make a plan the better geological programme."

## 10. GUI

Four pages in the Streamlit sidebar, used left to right. Each page shows a plain message naming the missing step if its prerequisites are not met.

| Page | Contents |
| --- | --- |
| Project | Create or open a project. Upload the four files. Map columns, units, class values and null sentinels. Pick domain and metal. Baseline preview: rows, tonnes and metal by class, counts by baseline geometry class, baseline discrepancy total |
| Planning | Source and target class. Thresholds. Candidate ranges with live candidate count and size estimate. Budgets (comma-separated list), mode, cost inputs. Manual plan table with lock checkboxes. Advanced: support interval, angular separation, optimiser settings, seed. Run button with progress bar |
| Results | Summary metrics. Budget versus converted metal chart. Manual versus optimised table. Selected-hole table. 3D view. Download buttons |
| Scenarios | Save, load, duplicate. Compare two or more saved scenarios: metrics table, overlaid budget curves, list of settings that differ. Stale scenarios are flagged |

### 3D view (Plotly)

- Layers, each with a toggle: target blocks, potentially converted blocks, existing drilling, available sites, selected planned holes.
- Blocks are drawn as points, randomly downsampled to at most 30,000 for display. The caption states the display count against the full count.
- Numbers on screen always come from the full dataset.

## 11. Persistence and exports

A project is a folder. Settings are JSON, tables are Parquet, and nothing needs a database.

```
projects/<project_name>/
  project.json                # mappings, units, defaults, input file hashes
  inputs/                     # original CSVs plus Parquet copies
  cache/                      # baseline distances, candidate matrix, keyed by hash
  scenarios/<scenario_id>/
    scenario.json             # full settings snapshot, see below
    summary.parquet           # one row per budget
    holes.parquet             # selected holes per budget
    blocks.parquet            # block-level results
```

### scenario.json holds

- Name, creation timestamp, app version.
- SHA-256 hash of each input file used.
- Column mappings and units as they were at run time (a copy, not a reference to project defaults).
- Domain selection, metal, grade unit, source and target class, thresholds.
- Budgets, mode, cost inputs, candidate settings, support interval, angular separation.
- Locked holes, optimiser settings, random seed.

### Rules

- Loading a scenario restores its own settings, never the current project settings.
- If any stored input hash differs from the current file, the scenario is marked "stale, recalculate" and its results are shown greyed with that label.
- Duplicate copies settings without results.

### Exports

| Download | Format | Contents |
| --- | --- | --- |
| Selected planned holes | CSV | Budget, hole ID, site ID, collar XYZ, azimuth, dip, length, cost, locked flag |
| Budget-scenario summary | CSV | Section 9 metrics, one row per budget |
| Manual versus optimised | CSV | Both plans' metrics plus the common and unique splits |
| Block-level results | CSV | Block ID, uploaded class, baseline geometry class and metric, post-campaign class and metric, potential-conversion flag, tonnes, contained metal |
| Scenario settings | JSON | `scenario.json` |

- Column headers carry units, for example `metal_kg` or `metal_t`.
- CSV exports start with the standard disclaimer as a comment line. The JSON carries it as a field.

## 12. Build milestones

Eight milestones in the original order. Each ends with something you can run in the browser and a stop for your review. Test numbers refer to section 13.

| # | Milestone | Deliverable | Done when |
| --- | --- | --- | --- |
| 1 | Block model import | Project page: upload, mapping, class mapping, domain filter, tonnes and metal preview. Synthetic dataset builder | Test 4 passes. Preview totals match a hand calculation on the synthetic model |
| 2 | Drilling import and baseline geometry | Route A import. Baseline metric and class per block, shown in the preview | Tests 1, 2, 3 pass |
| 3 | Manual plan evaluation | Manual plan import, support points, `evaluate_campaign()`, conversion totals and baseline discrepancy | Tests 5, 6 pass. **Gate: you confirm the evaluator on a case you know before the optimiser is started** |
| 4 | Candidates and costing | Candidate generation, exclusion groups, angular separation, cost model, size estimate | Tests 12, 13 pass |
| 5 | Optimiser | Single-budget optimisation with locked holes, pairs, prune, local search, restarts | Tests 7, 8, 9, 10 pass. Run time measured on a synthetic set at the confirmed scale |
| 6 | Budget scenarios and comparison | Multi-budget runs in both modes, budget curve, manual versus optimised with common and unique splits | Conversion is non-decreasing across budgets in both modes on the synthetic set |
| 7 | Scenarios, 3D view, exports | Save, load, duplicate, compare. 3D view. All five downloads | Tests 11, 14 pass. Every export opens and carries the disclaimer |
| 8 | Route B desurvey | Collar, survey and interval import with minimum curvature | Desurveyed midpoints match a hand-calculated two-station hole to 0.01 m |

Milestones 1 to 3 already give a usable manual-plan evaluator, which is worth using on real data before the optimiser exists.

## 13. Acceptance tests

Fourteen pytest tests on small synthetic datasets built in `tests/synthetic.py`. Tests 1 to 11 are from the original plan and 12 to 14 are new. Synthetic data is labelled as such in file names and in the app.

| # | Test | Setup | Pass condition |
| --- | --- | --- | --- |
| 1 | One hole counts once | One block, one hole with 50 samples nearby, no other holes | Block has fewer than three holes and is outside criteria |
| 2 | Three nearest distinct holes | One block, five holes at known distances | Metric equals the mean of the three smallest |
| 3 | Threshold boundaries | Blocks with metric exactly 25, 50, 100 and each plus 0.01 | Exact values take the higher class. Plus 0.01 takes the lower |
| 4 | Subblock volumes | Parent 10 m blocks with 5 m and 2.5 m subblocks | Total volume equals the sum of row volumes from row dimensions |
| 5 | Baseline not claimed | Indicated block already at Measured geometry, plus a new hole next to it | Reported as baseline discrepancy. Conversion is zero |
| 6 | No double counting | Two planned holes that each convert the same blocks | Campaign metal equals the union, not the sum |
| 7 | Complementary pair | Blocks with one existing hole nearby. Two candidates that convert only together | Both selected. Each alone converts nothing |
| 8 | Locked holes | One locked hole with poor value | It stays selected and its cost is deducted before other picks |
| 9 | Within budget | Several budgets, including one below the cheapest hole | Planned cost never exceeds budget. The low budget returns an empty plan |
| 10 | Manual equals generated | A manual plan identical to a generated campaign | Block-level results and totals are identical |
| 11 | Scenario reproducibility | Save, reload and rerun with the same inputs and seed | Settings and results identical |
| 12 | Same-trace exclusion | Candidates of 100 m and 200 m on one trace, both attractive | At most one is selected. With the site cap set to 2, no site receives a third hole |
| 13 | Site setup costing | Three holes over two sites with non-zero setup and fixed costs | Cost equals the formula in section 7.2 |
| 14 | Stale detection | Save a scenario, then replace an input file | Scenario is flagged stale until recalculated |

## 14. Known limitations and out of scope

### Limitations to state in the app's help text

- **No directional test.** Three holes on one side of a block satisfy the metric. The angular separation rule reduces the worst case but does not replace a coverage test.
- **Centroid only.** A block is judged at its centroid. Where blocks are large relative to the thresholds, the class is coarse.
- **Full-length support.** Planned holes count as sampled from collar to toe, including any waste or cover they pass through.
- **Greedy bias.** The search prefers moves that convert metal now over moves that set up a larger gain later. Pair moves and restarts reduce this, not remove it.
- **Straight holes.** No deviation is modelled for planned holes.
- **Light validation.** Overlapping block records, mixed coordinate systems and duplicate hole IDs are not detected.

### Out of scope (unchanged from the plan)

- Conditional simulation and grade uncertainty.
- Automatic geological interpretation or classification post-processing.
- Multiple-metal objectives.
- Rig scheduling and deviation forecasting.
- Coordinate transformations.
- Authentication, multi-user editing and enterprise integrations.
- Anisotropic searches, geological barriers and per-site candidate overrides (deferred, not rejected).
