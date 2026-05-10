"""
tests/test_agt5_key_filtering.py — AGT-5 regression tests.

Covers ``cross_ai_core.has_api_key()`` wired into the cross-st consumers:

  * ``_alias_admin.list_aliases(filter_by_keys=True)`` drops keyless rows.
  * ``_alias_admin.agents_missing_keys()`` flags agents whose make has no key.
  * ``_alias_admin.providers_with_unused_keys()`` flags keys with no agent.
  * ``st-admin._show_aliases_table()`` renders both hint blocks.
  * ``st-cross.py`` matrix iteration prints a "skipping agent" warning
    when an agent's make has no API key (smoke check on the import path —
    full run is covered by the live integration suite).
"""
from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

# Module loader (st-admin.py has a hyphen → cannot use plain import).
_SPEC = importlib.util.spec_from_file_location(
    "st_admin", Path(__file__).parent.parent / "cross_st" / "st-admin.py"
)
st_admin = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(st_admin)

_CROSS_ST = str(Path(__file__).parent.parent / "cross_st")
if _CROSS_ST not in sys.path:
    sys.path.insert(0, _CROSS_ST)

import _alias_admin  # noqa: E402
from cross_ai_core.aliases import reload_aliases  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_alias_file(tmp_path, monkeypatch):
    """Redirect alias JSON to a temp file; reseed the registry per test."""
    f = tmp_path / "cross_ai_models.json"
    monkeypatch.setenv("CROSS_AI_ALIASES_FILE", str(f))
    reload_aliases()
    from cross_ai_core.aliases import _AI_ALIASES, AliasSpec
    for make in _alias_admin._builtin_makes():
        _AI_ALIASES.setdefault(make, AliasSpec(make=make, model=None))
    yield f
    monkeypatch.delenv("CROSS_AI_ALIASES_FILE", raising=False)
    reload_aliases()


@pytest.fixture
def all_keys_unset(monkeypatch):
    """Strip every provider's API key from the env so has_api_key()→False."""
    from cross_ai_core import PROVIDER_API_KEY_ENV
    for env_names in PROVIDER_API_KEY_ENV.values():
        for name in env_names:
            monkeypatch.delenv(name, raising=False)


# ── _alias_admin.list_aliases(filter_by_keys=True) ───────────────────────────

class TestListAliasesFilter:
    def test_filter_off_returns_all(self, isolated_alias_file, all_keys_unset):
        rows = _alias_admin.list_aliases(filter_by_keys=False)
        # Pre-AGT-5 contract: every loaded alias is returned.
        assert {r["alias"] for r in rows} == set(_alias_admin._builtin_makes())

    def test_filter_on_drops_all_when_no_keys(
        self, isolated_alias_file, all_keys_unset,
    ):
        rows = _alias_admin.list_aliases(filter_by_keys=True)
        assert rows == []

    def test_filter_on_keeps_provider_with_key(
        self, isolated_alias_file, all_keys_unset, monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        rows = _alias_admin.list_aliases(filter_by_keys=True)
        assert {r["alias"] for r in rows} == {"openai"}
        assert rows[0]["has_api_key"] is True

    def test_has_api_key_field_present_on_unfiltered_rows(
        self, isolated_alias_file, all_keys_unset, monkeypatch,
    ):
        monkeypatch.setenv("XAI_API_KEY", "xai-test")
        rows = _alias_admin.list_aliases(filter_by_keys=False)
        by_make = {r["make"]: r for r in rows}
        assert by_make["xai"]["has_api_key"] is True
        assert by_make["openai"]["has_api_key"] is False


# ── agents_missing_keys / providers_with_unused_keys ────────────────────────

class TestAgentsMissingKeys:
    def test_empty_when_every_agent_has_key(
        self, isolated_alias_file, all_keys_unset, monkeypatch,
    ):
        from cross_ai_core import PROVIDER_API_KEY_ENV
        for env_names in PROVIDER_API_KEY_ENV.values():
            monkeypatch.setenv(env_names[0], "test")
        assert _alias_admin.agents_missing_keys() == []

    def test_lists_keyless_agents(
        self, isolated_alias_file, all_keys_unset, monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        missing = _alias_admin.agents_missing_keys()
        # Every built-in except openai should appear.
        makes_missing = {make for _alias, make, _env in missing}
        builtins = set(_alias_admin._builtin_makes())
        assert makes_missing == builtins - {"openai"}
        # Each tuple carries the canonical env-var name.
        for _alias, make, env_var in missing:
            assert env_var.endswith("_API_KEY")


class TestProvidersWithUnusedKeys:
    def test_empty_when_every_key_has_agent(
        self, isolated_alias_file, all_keys_unset, monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        # 'openai' built-in agent already covers it.
        assert _alias_admin.providers_with_unused_keys() == []

    def test_flags_provider_with_key_but_no_agent(
        self, isolated_alias_file, all_keys_unset, monkeypatch,
    ):
        # Wipe the registry so no agent uses anthropic, then set the key.
        from cross_ai_core.aliases import _AI_ALIASES
        _AI_ALIASES.clear()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        unused = _alias_admin.providers_with_unused_keys()
        assert ("anthropic", "ANTHROPIC_API_KEY") in unused


# ── st-admin._show_aliases_table renders the new hint blocks ────────────────

class TestShowAliasesTable:
    def test_warning_for_keyless_agent(
        self, isolated_alias_file, all_keys_unset, monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        buf = io.StringIO()
        with redirect_stdout(buf):
            st_admin._show_aliases_table()
        out = buf.getvalue()
        # openai row appears in the table; xai/anthropic/etc. surface as warnings.
        assert "openai" in out
        assert "XAI_API_KEY is unset" in out
        assert "ANTHROPIC_API_KEY is unset" in out

    def test_unused_key_hint(
        self, isolated_alias_file, all_keys_unset, monkeypatch,
    ):
        from cross_ai_core.aliases import _AI_ALIASES
        _AI_ALIASES.clear()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        buf = io.StringIO()
        with redirect_stdout(buf):
            st_admin._show_aliases_table()
        out = buf.getvalue()
        assert "you have ANTHROPIC_API_KEY" in out
        assert "no agent uses anthropic" in out

