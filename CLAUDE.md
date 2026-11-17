# Project notes for Claude

Infill drilling budget optimiser. The build spec (`Infill Drilling Budget Optimiser Build Spec.md`) is the source of truth for behaviour, terminology, milestones and acceptance tests.

## Target platform: Windows

End users run this on Windows PCs. Development may happen on macOS, but code and docs must work on Windows first.

- Docs lead with Windows and PowerShell commands. macOS notes go last and stay short.
- Use `pathlib.Path` for all paths. Never build paths with string concatenation or hard-coded `/`.
- Always pass `encoding="utf-8"` when opening, reading or writing text files. The Windows default is cp1252.
- Write CSVs with `newline=""` (or pandas defaults) so Windows does not insert blank lines.
- Project and scenario names become folder names: strip characters Windows forbids (`<>:"/\|?*`) and avoid reserved names (`CON`, `NUL`, ...).
- Prefer `uv run ...` in instructions over activating the venv, which PowerShell execution policy often blocks.

## Architecture rules (spec section 4)

- Nothing under `engine/` imports Streamlit. `tests/test_architecture.py` enforces this.
- `engine.evaluate.evaluate_campaign()` is the only scoring path for manual and optimised campaigns.
- Threshold comparisons use `engine.TOLERANCE_M`.
- Results text says "potentially converted" and "best-found plan", never "converted" or "optimal".

## Data

Real data never enters git. Only `data/test/` (synthetic or sample data) is tracked. `projects/` is ignored.

## Commands

```
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run streamlit run app.py
```
