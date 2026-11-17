# Infill Drilling Budget Optimiser

Ranks infill drilling campaigns by potential geometric conversion of one metal within a budget. A planning aid, not a resource classification tool. See `Infill Drilling Budget Optimiser Build Spec.md` for the full specification.

The target platform is **Windows 10/11**. macOS also works and is covered briefly at the end.

**New users:** follow the step-by-step [Setup and User Guide](docs/SETUP_GUIDE.md). It covers installation, preparing your CSV files, the workflow through each page, and troubleshooting. This README is the short version.

## Install and run on Windows

Use PowerShell from the project folder.

1. Install `uv` (one time). It downloads Python 3.11 for you, so no separate Python install is needed:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   Close and reopen PowerShell afterwards so `uv` is on the PATH.

2. Install the project:

   ```powershell
   uv sync --extra dev
   ```

3. Start the app. It opens in your default browser:

   ```powershell
   uv run streamlit run app.py
   ```

`uv run` uses the project's environment directly, so you never need to activate it. That avoids the PowerShell script-execution policy error that `.venv\Scripts\Activate.ps1` often triggers on locked-down PCs.

Run the tests with:

```powershell
uv run pytest
```

## Try it on the synthetic demo data

A ready-mapped demo project built from the SYNTHETIC files in `data\test\`:

```powershell
uv run python scripts/make_demo_project.py
uv run streamlit run app.py
```

Then in the browser:

1. **Project**: choose "SYNTHETIC demo", click **Open project**. Check the baseline preview at the bottom.
2. **Planning**: enter a scenario name and click **Run** (about a minute on the demo data).
3. **Results**: summary, budget curve, manual versus optimised, selected holes, 3D view and downloads.
4. **Scenarios**: duplicate, recalculate and compare runs.

To use your own data, create a new project on the Project page, upload your CSVs and map the columns.

## Run time

Expensive steps (baseline distances and the candidate distance table) are cached in the project's `cache\` folder, so re-runs with the same inputs skip them. Each budget is searched for up to the time limit under Planning > Advanced (default 600 s), after which the best plan found so far is used. Measure your own scale with:

```powershell
uv run python scripts/benchmark_scale.py 1000000
```

## Layout

- `engine\`: pure Python calculation engine. Never imports Streamlit.
- `app.py`, `pages\`: thin Streamlit UI that calls the engine.
- `tests\`: pytest acceptance tests on synthetic data (`tests\synthetic.py`).
- `projects\`: created at runtime, git-ignored.

## Data policy

- `data\test\`: small synthetic or sample datasets, tracked in git.
- Everything else under `data\`, and all of `projects\`, is git-ignored. Real project data must never be committed.

## macOS

Install `uv` with `curl -LsSf https://astral.sh/uv/install.sh | sh`, then use the same `uv sync --extra dev`, `uv run streamlit run app.py` and `uv run pytest` commands in Terminal.
