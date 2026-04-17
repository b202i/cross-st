"""
tests/conftest.py — shared pytest configuration and fixtures.

Test tiers
----------

  Unit (default)
      Pure function / module tests.  No subprocesses.  No AI calls.  Fast.
      Run with: pytest

  Slow  (@pytest.mark.slow)
      Spawn real subprocesses but make NO AI calls (use fixture JSON or
      --help / --dry-run patterns).  Catches CLI-level structural bugs that
      unit tests miss (e.g. NameError in main(), argparse misconfiguration,
      broken imports through commands.py).  ~10-30 s.
      Run with: pytest --slow   or   pytest -m slow

  Live  (@pytest.mark.live)
      Spawn real subprocesses AND make real AI calls — but always with
      --cache enabled.  First run costs real money and populates the on-disk
      cache (~/.cross_api_cache/).  Every subsequent run is free and fast
      because responses are served from cache.
      Run with: pytest --live   or   pytest -m live

      Practical workflow:
        1. Run once on a machine with valid API keys:
               pytest --live          # populates cache
        2. Commit nothing extra — cache lives in ~/.cross_api_cache/.
        3. On any future run (CI, re-test, colleague's machine with same
           cache): pytest --live runs in <5 s per test, $0 cost.

      Use the pizza_dough or cross-stones fixtures so the prompts are
      short and deterministic.

Running all tiers at once:
    pytest --slow --live
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
        help="also run @pytest.mark.slow tests (subprocess / integration, no AI)",
    )
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="also run @pytest.mark.live tests (real AI calls, cache-friendly)",
    )


def pytest_collection_modifyitems(config, items):
    run_slow = config.getoption("--slow")
    run_live = config.getoption("--live")
    markexpr = getattr(config.option, "markexpr", "") or ""

    skip_slow = pytest.mark.skip(reason="slow test — run with --slow to include")
    skip_live = pytest.mark.skip(reason="live AI test — run with --live to include")

    for item in items:
        if "slow" in item.keywords:
            if not run_slow and "slow" not in markexpr:
                item.add_marker(skip_slow)
        if "live" in item.keywords:
            if not run_live and "live" not in markexpr:
                item.add_marker(skip_live)
