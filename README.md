# Infill Drilling Budget Optimiser

Ranks infill drilling campaigns by potential geometric conversion of one metal within a budget. A planning aid, not a resource classification tool. See `Infill Drilling Budget Optimiser Build Spec.md` for the full specification.

The target platform is **Windows 10/11**. macOS also works and is covered briefly at the end.

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
