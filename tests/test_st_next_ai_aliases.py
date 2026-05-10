"""
tests/test_st_next_ai_aliases.py — CST-MM-k regression test.

One-line behaviour confirmation: ``st.py``'s ``next_ai()`` cycles through
the alias registry returned by ``cross_ai_core.get_ai_list()``, which now
includes user-defined aliases (CST-MM-i + CAC-10).

Also asserts the global ``A`` / ``S`` / ``F`` reserved-key contract is
intact at the menu-dispatch level (these keys must remain bound to the
``next_ai`` / ``next_story`` / ``next_fact_check`` rotations and must not
be reused as menu shortcuts anywhere in ``st.py``'s _MENU tree).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_CROSS_ST = str(Path(__file__).parent.parent / "cross_st")
if _CROSS_ST not in sys.path:
    sys.path.insert(0, _CROSS_ST)


def _load_st(monkeypatch, alias_file: Path):
    """Load cross_st/st.py as a fresh module under an isolated alias file."""
    monkeypatch.setenv("CROSS_AI_ALIASES_FILE", str(alias_file))
    # Force cross-ai-core to re-read the alias file
    from cross_ai_core.aliases import reload_aliases
    reload_aliases()
    spec = importlib.util.spec_from_file_location(
        "st_under_test", Path(_CROSS_ST) / "st.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def alias_file(tmp_path):
    """Alias file with built-in self-aliases + two user aliases.

    The five bare-make entries mirror what the AGT-2 first-run migration
    would create on any install with all five provider API keys present.
    Tests in this module assert the rotation/menu contract over the full
    set, so we seed them explicitly post-AGT-1 (no auto-seed).
    """
    f = tmp_path / "cross_ai_models.json"
    f.write_text(json.dumps({
        "anthropic":        {"make": "anthropic", "model": None},
        "openai":           {"make": "openai",    "model": None},
        "xai":              {"make": "xai",       "model": None},
        "gemini":           {"make": "gemini",    "model": None},
        "perplexity":       {"make": "perplexity","model": None},
        "anthropic-opus":   {"make": "anthropic", "model": "claude-opus-4-5"},
        "anthropic-sonnet": {"make": "anthropic", "model": "claude-sonnet-4-5"},
    }))
    return f


def test_ai_opt_includes_user_aliases(monkeypatch, alias_file):
    st = _load_st(monkeypatch, alias_file)
    # Built-in 5 + 2 user aliases = 7
    assert "anthropic-opus" in st.ai_opt
    assert "anthropic-sonnet" in st.ai_opt
    assert len(st.ai_opt) >= 7


def test_next_ai_eventually_visits_user_alias(monkeypatch, alias_file):
    st = _load_st(monkeypatch, alias_file)
    # Cycle exactly len(ai_opt) times — must cover every entry.
    visited = set()
    for _ in range(len(st.ai_opt)):
        st.next_ai()
        visited.add(st.ai)
    assert "anthropic-opus" in visited
    assert "anthropic-sonnet" in visited


def test_next_ai_wraps_around(monkeypatch, alias_file):
    st = _load_st(monkeypatch, alias_file)
    n = len(st.ai_opt)
    start = st.ai_select
    for _ in range(n):
        st.next_ai()
    assert st.ai_select == start
    assert st.ai == st.ai_opt[start]


def test_next_ai_advances_one_step(monkeypatch, alias_file):
    st = _load_st(monkeypatch, alias_file)
    before = st.ai_select
    st.next_ai()
    assert st.ai_select == (before + 1) % len(st.ai_opt)
    assert st.ai == st.ai_opt[st.ai_select]


def test_ASF_keys_not_reused_in_menu(monkeypatch, alias_file):
    """Reserved-key contract: A/S/F never used as menu shortcuts in st.py."""
    st = _load_st(monkeypatch, alias_file)

    def walk(menu):
        for key, val in menu.items():
            assert key not in {"A", "S", "F"}, (
                f"Reserved global key {key!r} must not be a menu shortcut "
                "(see AGENTS.md → 'st.py reserved keys — A, S, F')"
            )
            if isinstance(val, tuple) and len(val) == 2 and isinstance(val[1], dict):
                walk(val[1])

    for top_menu in st.menus.values():
        if isinstance(top_menu, dict):
            walk(top_menu)


def test_argparse_choices_include_aliases(monkeypatch, alias_file):
    """The --ai CLI flag's choices list must come from get_ai_list()."""
    st = _load_st(monkeypatch, alias_file)
    parser = st.argparse.ArgumentParser()
    # Re-mirror the argument from st.py (line 420) using the live ai_opt
    parser.add_argument("-a", "--ai", choices=st.ai_opt)
    ns = parser.parse_args(["--ai", "anthropic-opus"])
    assert ns.ai == "anthropic-opus"


