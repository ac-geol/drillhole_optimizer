# Infill Drilling Budget Optimiser

Ranks infill drilling campaigns by potential geometric conversion of one metal within a budget. A planning aid, not a resource classification tool. See `Infill Drilling Budget Optimiser Build Spec.md` for the full specification.

## Install and run

Requires Python 3.11+.

```bash
uv venv --python 3.11 && source .venv/bin/activate
uv pip install -e ".[dev]"
streamlit run app.py
```

Run tests with `pytest`.

## Layout

- `engine/`: pure Python calculation engine. Never imports Streamlit.
- `app.py`, `pages/`: thin Streamlit UI that calls the engine.
- `tests/`: pytest acceptance tests on synthetic data (`tests/synthetic.py`).
- `projects/`: created at runtime, git-ignored.

## Data policy

- `data/test/`: small synthetic or sample datasets, tracked in git.
- Everything else under `data/`, and all of `projects/`, is git-ignored. Real project data must never be committed.
