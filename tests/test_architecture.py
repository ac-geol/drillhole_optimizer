"""Structural rules from spec section 4."""

import ast
import importlib
import pkgutil
from pathlib import Path

import engine

ENGINE_DIR = Path(engine.__file__).parent


def test_engine_modules_import():
    for mod in pkgutil.iter_modules([str(ENGINE_DIR)]):
        importlib.import_module(f"engine.{mod.name}")


def test_engine_never_imports_streamlit():
    offenders = []
    for path in sorted(ENGINE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n == "streamlit" or n.startswith("streamlit.") for n in names):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"engine/ must not import streamlit: {offenders}"
