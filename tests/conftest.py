"""
tests/conftest.py — shared pytest configuration and fixtures.

Slow-test gate
--------------
Tests marked @pytest.mark.slow spawn real subprocesses and are skipped by
default.  Pass --slow to opt in:

    pytest              # fast unit tests only  (~2 s)
    pytest --slow       # also runs slow subprocess/integration tests
    pytest -m slow      # slow tests only
"""
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Make cross_st/ importable by its short module names (mmd_util, st_admin …)
# This mirrors what runpy.run_path does at runtime: it prepends the script's
# directory to sys.path so that sibling imports like `from mmd_util import …`
# resolve correctly.
# ---------------------------------------------------------------------------
_CROSS_AI = Path(__file__).parent.parent / "cross_st"
if str(_CROSS_AI) not in sys.path:
    sys.path.insert(0, str(_CROSS_AI))


def pytest_addoption(parser):
    parser.addoption(
        "--slow",
        action="store_true",
        default=False,
        help="also run @pytest.mark.slow tests (subprocess / integration)",
    )


def pytest_collection_modifyitems(config, items):
    # Don't add skip if the user explicitly opted in via --slow or -m slow
    if config.getoption("--slow"):
        return
    markexpr = getattr(config.option, "markexpr", "") or ""
    if "slow" in markexpr:
        return
    skip = pytest.mark.skip(reason="slow test — run with --slow to include")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
