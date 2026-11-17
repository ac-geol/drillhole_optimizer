# Setup and User Guide

This guide takes you from a fresh Windows PC to your first set of results in the Infill Drilling Budget Optimiser. No programming is needed. macOS notes are at the end.

> **What the tool does:** it ranks infill drilling campaigns by how much metal they could *potentially* move from one resource class to a higher geometry class within a budget. It is a planning aid only. Every result is a planning estimate based on geometric drilling support. It is not a resource classification declaration, and geological and QP review is required.

---

## 1. Before you start

You need:

- Windows 10 or 11.
- Internet access for the first install (to download Python packages). After that the app runs offline.
- About 1 GB of free disk space for the software, plus room for your project data.
- A modern web browser (Edge or Chrome). The app opens in your browser but runs only on your own PC; nothing is uploaded anywhere.
- Permission to install software into your own user account. Administrator rights are **not** needed.

## 2. One-time installation

### Step 1: Get the project folder

Get the `drillhole_optimizer` folder from your team, either:

- **With git:** open PowerShell and run `git clone <repository address>` in the folder where you keep your work, or
- **As a zip file:** extract it to a simple location such as `C:\Tools\drillhole_optimizer`.

Avoid putting the folder inside a OneDrive or SharePoint-synced folder. Syncing can lock files while the app is writing them.

### Step 2: Open PowerShell in the project folder

1. Open the project folder in File Explorer.
2. Click the address bar, type `powershell` and press Enter.

A blue or black PowerShell window opens, already in the right folder. Use this window for every command below.

### Step 3: Install uv

`uv` is a small tool that installs the right Python version and all the packages for you. You don't need to install Python separately. Run:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

When it finishes, **close PowerShell and open it again** in the project folder (Step 2), so Windows can find `uv`.

Check it worked:

```powershell
uv --version
```

### Step 4: Install the app

```powershell
uv sync --extra dev
```

The first run downloads Python 3.11 and the packages and takes a few minutes. Later runs take seconds.

### Step 5 (optional): Check the installation

```powershell
uv run pytest
```

Every test should pass (the last line says `passed` with no `failed`). All test data is synthetic.

## 3. Starting and stopping the app

Each time you want to use the app, open PowerShell in the project folder and run:

```powershell
uv run streamlit run app.py
```

Your browser opens at `http://localhost:8501`. If it doesn't, open that address yourself.

- Keep the PowerShell window open while you work. Closing it stops the app.
- To stop the app, click the PowerShell window and press **Ctrl+C**.
- If Windows Firewall asks about network access, you can choose **Cancel**: the app only needs your own PC.

## 4. Try it first with the demo data

A ready-made demo project uses the synthetic files in `data\test\`. It's the quickest way to learn the workflow.

```powershell
uv run python scripts/make_demo_project.py
uv run streamlit run app.py
```

Then in the browser:

1. **Project:** choose "SYNTHETIC demo" and click **Open project**. Scroll down to see the baseline preview.
2. **Planning:** type a scenario name and click **Run**. On the demo data this takes under a minute.
3. **Results:** look at the summary, budget curve, manual-versus-optimised comparison, selected holes and 3D view.
4. **Scenarios:** duplicate, recalculate and compare runs.

Running the demo script again resets the demo project.

## 5. Preparing your own data

You need three CSV files, plus an optional fourth. Column names can be anything you like: you match them to the app's fields on the Project page. All coordinates must use the same projected grid and elevation datum, in metres.

### Block model (required)

One row per block or sub-block.

| Field | Required | Notes |
| --- | --- | --- |
| Centroid X, Y, Z | Yes | Block centre, metres |
| Block size X, Y, Z | Yes | A column each, or one constant size typed in the app. Use each row's own size, not its parent's |
| Density | Yes | t/m³ |
| Resource class | Yes | Your class codes, for example 1/2/3 or MEAS/IND/INF. You say what each code means in the app |
| Grade | Yes | One metal, in % or g/t |
| Block ID | No | Row number used if absent |
| Domain | No | Lets you restrict the blocks that count |
| Parent block ID | No | Stored only |

Null values such as `-99`, `-999` and blank cells are excluded from totals and counted in the preview. You can edit the list of null codes. Rows with a negative grade are also excluded.

### Existing drilling (required): choose one route

**Route A: desurveyed samples.** One row per sample or interval midpoint.

| Field | Required | Notes |
| --- | --- | --- |
| Hole ID | Yes | |
| X, Y, Z | Yes | Sample position |
| Valid flag | No | Rows marked `N`, `No`, `False` or `0` are dropped. `Y`, `Yes`, `True` and `1` count. Other values are dropped and counted |
| Domain | No | Stored but not used: all drilling counts as support |

**Route B: collars and surveys.** The app desurveys the holes for you (minimum curvature).

- **Collars:** hole ID, X, Y, Z, and optionally final depth.
- **Surveys:** hole ID, depth, azimuth, dip.
- **Sample intervals (optional):** hole ID, from, to. Without intervals, points are generated along each hole at the support interval and the assumption is shown with the results.

Dips are negative downward by default. Tick **Dip is positive downward** if your file uses positive-down dips.

### Potential drill sites (required)

| Field | Required |
| --- | --- |
| Site ID | Yes |
| X, Y, Z | Yes (the collar position) |

Site IDs must be unique. The app generates candidate holes at every site from the azimuth, dip and length ranges you set on the Planning page.

### Manual drilling plan (optional)

Your own proposed campaign, to compare against the optimised one.

| Field | Required | Notes |
| --- | --- | --- |
| Hole ID | Yes | Must be unique |
| Site ID | No | Without it, a hole is matched to a site within 1 m (editable). Otherwise its collar becomes its own site |
| Collar X, Y, Z | Yes | |
| Azimuth, dip, length | Yes | Degrees and metres. There's a positive-down dip toggle |

### File tips

- Save as **CSV UTF-8** from Excel if you can. Plain Excel CSV (Windows-1252) also works.
- One header row, no title rows or blank rows above the header.
- Files up to 2 GB can be uploaded.

## 6. Using the app with your own data

Work through the pages in the sidebar from top to bottom. Each page tells you plainly if an earlier step is missing.

### Project page

1. Type a **New project name** and click **Create project**. Next time, pick it under **Open an existing project**.
2. Upload each file, then match your columns. The app guesses common names (for example `XC`, `EAST`, `RL`, `HOLEID`); check every choice.
3. For the block model, choose the grade unit (% reports metal in tonnes, g/t in kilograms), say what each class code means, and optionally pick domains.
4. Click **Save mappings**.
5. Check the **Baseline preview**: rows, tonnes and metal by class, any invalid rows and their reasons, and how much metal sits in each baseline geometry class.

### Planning page

1. **Classes:** the source class (as uploaded, default Indicated) and the target geometry class (default Measured).
2. **Geometry thresholds:** mean distance to the nearest three holes for each class (defaults 25, 50 and 100 m).
3. **Candidate holes:** azimuth, dip and length ranges (minimum, maximum and increment). The candidate count and a memory estimate update as you type. If you see a warning, use coarser increments.
4. **Budgets and costs:** one or more budgets separated by commas, the mode (Independent or Expandable), and the cost per metre, per hole and per site.
5. **Manual plan:** tick **Locked** for any holes that must be in every optimised plan.
6. **Advanced** (optional): support interval, minimum angle between holes at one site, maximum holes per site, and optimiser settings. The defaults suit most cases.
7. Type a **Scenario name** and click **Run**. A progress bar shows each budget. Each budget is searched for up to 10 minutes by default; large projects can take several minutes per budget.

### Results page

- Summary metrics for each budget, the budget-versus-metal curve, the manual-versus-optimised table, the selected holes and a 3D view.
- **Downloads:** selected holes, budget summary, manual versus optimised, block-level results and the scenario settings. Every CSV starts with the disclaimer line.
- **Warnings and assumptions** and **Run log** sit at the bottom.

### Scenarios page

- Every run is saved automatically.
- **Duplicate** copies the settings without results. **Use these settings on the Planning page** loads a scenario's settings for a new run.
- If you replace an input file, older scenarios are marked **STALE**. Click **Recalculate** to update them with the current files.
- Choose two or more scenarios to compare their metrics, budget curves and the settings that differ.

## 7. Where your data is kept

Each project is a folder under `projects\` in the app folder, for example `projects\My Pit 2027\`:

- `project.json`: your column mappings and settings.
- `inputs\`: your original CSVs and fast-loading copies.
- `cache\`: saved calculations that make re-runs quicker. Safe to delete at any time; it is rebuilt when needed, and can grow large on big block models.
- `scenarios\`: one folder per saved scenario.

**Backups:** copy the project folder. **Moving to another PC:** copy the project folder into that PC's `projects\` folder.

The `projects\` folder is never committed to git, so real data stays on your PC. To keep projects somewhere else, set the `INFILL_PROJECTS_DIR` environment variable to that folder before starting the app.

## 8. Updating to a new version

Stop the app, then in PowerShell in the project folder:

```powershell
git pull
uv sync --extra dev
```

If you received a zip instead, extract the new version to a new folder and copy your `projects\` folder across. Your projects are not affected by updates. Recalculate older scenarios if you want results from the new version.

## 9. Troubleshooting

| Problem | What to do |
| --- | --- |
| `uv` is not recognised | Close and reopen PowerShell after installing uv. If it still fails, sign out of Windows and back in |
| "running scripts is disabled on this system" | Use `uv run ...` as shown in this guide. You never need to activate the environment (`.venv\Scripts\Activate.ps1`) |
| `uv sync` fails to download | Your network may need a proxy. Ask IT for the proxy address and set it with `$env:HTTPS_PROXY = "http://proxy:port"` in the same PowerShell window, then retry |
| "Port 8501 is already in use" | The app is already running in another window. Use that one, or start on another port: `uv run streamlit run app.py --server.port 8502` |
| Browser shows "Connection error" | The PowerShell window was closed or stopped. Start the app again |
| A file "could not be read" | Check it's a CSV with one header row. Re-save from Excel as **CSV UTF-8** |
| "has no column named ..." after replacing a file | The new file's headers differ. Re-match the columns on the Project page and click **Save mappings** |
| Many invalid block rows | Read the reasons under the preview. Usually a null code missing from the null-values list, or a wrong density or size column |
| Run is slow or memory warning | Use coarser candidate increments, fewer sites or a domain filter. Lower the time limit under Advanced |
| Results look out of date | The scenario may be STALE. Click **Recalculate** |

## 10. Known limitations

- **No directional test:** three holes on one side of a block satisfy the metric. The angular separation rule reduces the worst case but does not replace a coverage test.
- **Centroid only:** a block is judged at its centroid, so large blocks are classed coarsely.
- **Full-length support:** planned holes count as sampled from collar to toe, including waste or cover.
- **Greedy bias:** the search finds a best-found plan, not a proven optimum.
- **Straight holes:** no deviation is modelled for planned holes.
- **Light validation:** overlapping blocks, mixed coordinate systems and duplicate hole IDs are not detected.

## macOS

Install uv in Terminal with:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then use the same commands as above in Terminal from the project folder: `uv sync --extra dev`, `uv run streamlit run app.py`, and `uv run python scripts/make_demo_project.py`. Paths use `/` instead of `\`.
