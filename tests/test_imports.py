"""
test_imports.py — Regression tests for missing stdlib imports in st-*.py scripts.

Every st-*.py script is parsed with the AST and any stdlib module that is
*referenced* (used as a Name node, e.g. ``signal.SIGINT``) but not *imported*
at the top level is reported as a failure.

This catches the recurring pattern of ``import time``, ``import threading``,
``import signal``, ``import subprocess`` etc. being accidentally omitted.

False-positive guard: common local variable names that happen to shadow stdlib
module names (``cmd``, ``site``, ``_io``, ``_thread``, ``keyword``) are
excluded from the check.
"""
import ast
import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Locate the project root (parent of this tests/ directory)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Stdlib module names available in this Python build
_STDLIB = set(sys.stdlib_module_names)

# Names that are valid as local variables but also happen to be stdlib module
# names — exclude them to avoid false positives.
_FALSE_POSITIVES = {
    "cmd",        # routinely used as a list variable: cmd = ["st-gen", ...]
    "site",       # not imported, appears in string contexts
    "_io",        # internal / rarely direct
    "_thread",    # internal; concurrent.futures preferred
    "keyword",    # appears in st-find as a local variable
    "warnings",   # st-edit uses it inside a nested function that imports locally
    "html",       # st-print references it in a string / variable
    "re",         # watch: re IS missing in st-fact; kept in check (see below)
}
# Note: keep "re" *out* of false-positives so it stays caught.
_FALSE_POSITIVES.discard("re")


def _collect_st_scripts():
    """Return sorted list of (filename, Path) for every st-*.py in cross_st/."""
    scripts = sorted((_REPO_ROOT / "cross_st").glob("st-*.py"))
    return [(p.name, p) for p in scripts]


def _missing_imports(path: Path) -> list[str]:
    """
    Parse *path* with AST and return a sorted list of stdlib module names that
    are referenced as bare Name nodes but not present in any top-level import.
    """
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []

    # Collect everything that is imported (top-level name only, e.g. "concurrent"
    # for "import concurrent.futures").
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])

    # Collect every Name node used anywhere in the file.
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)

    missing = (
        (used & _STDLIB)          # name is a real stdlib module
        - imported                # … but was never imported
        - _FALSE_POSITIVES        # … and is not a known false-positive
        - {"__name__", "__file__", "__doc__"}
    )
    return sorted(missing)


# ---------------------------------------------------------------------------
# Parametrised test — one test case per st-*.py file
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fname,fpath", _collect_st_scripts())
def test_no_missing_stdlib_imports(fname, fpath):
    """
    ``st-*.py`` scripts must import every stdlib module they reference.

    If this test fails, add the appropriate ``import <module>`` to the imports
    block at the top of the named file (keep imports sorted alphabetically).
    """
    missing = _missing_imports(fpath)
    assert missing == [], (
        f"{fname} uses stdlib module(s) without importing them: {missing}\n"
        f"  Fix: add the following to {fname}'s import block:\n"
        + "\n".join(f"    import {m}" for m in missing)
    )

