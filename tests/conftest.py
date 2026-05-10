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


# ─────────────────────────────────────────────────────────────────────────────
# AGT-1 / AGT-2 — module-level alias-registry seed
# ─────────────────────────────────────────────────────────────────────────────
#
# cross-ai-core 0.8.0 stopped auto-seeding built-in providers as
# self-aliases.  On a fresh CI runner there is no ``~/.cross_ai_models.json``
# and no API keys, so ``get_ai_list()`` returns ``[]`` at module-import
# time of any test that captures it eagerly (e.g. tests/test_st_admin.py
# does ``AI_LIST = get_ai_list()`` at the top).
#
# The autouse ``_seed_legacy_alias_registry`` fixture below runs *per-test*
# and is therefore too late to fix that import-time capture.  We replicate
# the same seed at conftest module level — it executes once, before any
# test module is imported, so eager AI_LIST captures see the full provider
# set on CI just as they do on a developer machine.
import os as _os
import tempfile as _tempfile

_TMP_AGENTS = Path(_tempfile.mkdtemp(prefix="cross-test-agents-")) / "cross_ai_models.json"
# Set only the legacy env-var name.  cross-ai-core 0.8.0 reads
# CROSS_AI_AGENTS_FILE first, then CROSS_AI_ALIASES_FILE — by setting only
# the legacy name we leave the new-name slot free so individual tests can
# monkeypatch CROSS_AI_ALIASES_FILE to swap registries without our default
# winning over them.
_os.environ.setdefault("CROSS_AI_ALIASES_FILE", str(_TMP_AGENTS))

try:
    from cross_ai_core.aliases import _AI_ALIASES, AliasSpec  # type: ignore
    from cross_ai_core.ai_handler import AI_LIST as _BUILTIN_AI_LIST  # type: ignore
    for _make in _BUILTIN_AI_LIST:
        _AI_ALIASES[_make] = AliasSpec(make=_make, model=None)

    # Persist the same seed to disk so subprocess-based tests (test_live.py,
    # test_integration.py, --slow tier) inherit a non-empty agent registry
    # via the CROSS_AI_ALIASES_FILE env var above.  Without this, subprocesses
    # see an empty agents file and reject `--agent openai` with
    # `--agent {}` (no valid choices).
    import json as _json
    _agents_payload = {
        "version": 2,
        "agents": {m: {"provider": m, "model": None} for m in _BUILTIN_AI_LIST},
        "_migrated_to_agents_v2": True,
    }
    _TMP_AGENTS.write_text(_json.dumps(_agents_payload, indent=2))
except Exception:
    # cross-ai-core too old / not installed — let the per-test fixture try.
    pass


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


def pytest_configure(config):
    """Force a headless matplotlib backend whenever --slow or --live is active.

    Several `st-*` commands (st-verdict, st-heatmap, st-plot) call
    ``matplotlib.pyplot.show()`` at the end of a successful run.  On a developer
    machine with a display, that opens a Tk/Qt/Cocoa window and the subprocess
    blocks indefinitely until a human closes the window — which causes pytest
    to hang or time out.

    Setting MPLBACKEND=Agg here (in the *parent* pytest process's environment)
    means every subprocess that does ``env = os.environ.copy()`` inherits it.
    The Agg backend has no GUI; ``plt.show()`` becomes a no-op and the
    subprocess exits cleanly.

    We do not unset it on teardown — pytest exits anyway, and unit-tier tests
    don't care about the backend.

    NOTE: st-verdict in particular renders a stacked-bar chart and starts a
    canvas timer inside ``plt.show()``'s event loop to flush AI captions.
    With Agg, the timer never fires (no event loop) but the subprocess still
    exits 0 — exactly what the live test asserts on.
    """
    import os
    if config.getoption("--slow") or config.getoption("--live"):
        os.environ.setdefault("MPLBACKEND", "Agg")


# ─────────────────────────────────────────────────────────────────────────────
# AGT-2 — session-wide alias-registry seed
# ─────────────────────────────────────────────────────────────────────────────
#
# cross-ai-core 0.8.0 stopped auto-seeding built-in providers as
# self-aliases (AGT-1a).  Existing cross-st tests were written against the
# pre-0.8.0 behaviour — many call ``process_prompt("xai", …)`` or look up
# ``get_aliases()["anthropic"]`` directly.
#
# Rather than rewrite every legacy test, this fixture emulates the
# Agents v2 first-run migration once at session start: it seeds one
# self-alias per built-in provider into the in-process registry so the
# legacy lookup contract still holds.
#
# Tests that explicitly want an empty registry override
# ``CROSS_AI_ALIASES_FILE`` to a fresh tmp path and call
# ``reload_aliases()`` themselves — that wipes the seed for the duration
# of the test.

@pytest.fixture(autouse=True)
def _seed_legacy_alias_registry(tmp_path_factory, monkeypatch):
    """Pre-populate the alias registry with built-in self-aliases.

    Mirrors the cross-ai-core test-suite's session fixture so the
    pre-0.8.0 ``--ai <make>`` / ``get_aliases()[<make>]`` test patterns
    keep working without per-test setup.

    Also redirects ``CROSS_AI_ALIASES_FILE`` to a tmp path so the user's
    real ``~/.cross_ai_models.json`` (which on a developer machine has
    already been seeded with explicit models like
    ``{"anthropic": {"provider": "anthropic", "model": "claude-opus-4-5"}}``)
    cannot leak its model assignments into tests that resolve the bare
    make name and expect ``model=None`` semantics.

    Tests that override ``CROSS_AI_ALIASES_FILE`` themselves still win —
    monkeypatch later writes to env vars take precedence.
    """
    try:
        from cross_ai_core.aliases import _AI_ALIASES, AliasSpec
        from cross_ai_core.ai_handler import AI_LIST
    except Exception:
        # cross-ai-core too old for the new symbols — let tests run as-is.
        yield
        return

    # Isolate from the developer's real ~/.cross_ai_models.json.
    tmp_alias_file = tmp_path_factory.mktemp("alias_seed") / "cross_ai_models.json"
    # Pre-seed the file with built-in self-aliases so subprocess-based
    # tests (test_live.py, test_integration.py) inherit a populated
    # registry via the env var below — without this they see an empty
    # agents file and reject `--agent openai` with `(choose from , all)`.
    import json as _json_seed
    tmp_alias_file.write_text(_json_seed.dumps({
        "version": 2,
        "agents": {m: {"provider": m, "model": None} for m in AI_LIST},
        "_migrated_to_agents_v2": True,
    }))
    monkeypatch.setenv("CROSS_AI_ALIASES_FILE", str(tmp_alias_file))

    from collections import OrderedDict
    saved = OrderedDict(_AI_ALIASES)
    _AI_ALIASES.clear()
    for make in AI_LIST:
        _AI_ALIASES[make] = AliasSpec(make=make, model=None)
    try:
        yield
    finally:
        _AI_ALIASES.clear()
        _AI_ALIASES.update(saved)


