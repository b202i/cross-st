"""
tests/test_st_admin_agent_menu.py — CST-MM-i regression tests.

Covers the agent-management layer added to ``st-admin`` in 0.9.x:

  * ``cross_st/_agent_admin.py``   read/write/add/remove/edit + listing helpers.
  * ``st-admin --add-agent``       CLI flag (happy + error paths).
  * ``st-admin --remove-agent``    CLI flag (happy + error paths).
  * ``st-admin --list-agents``    CLI flag (smoke).

Isolation strategy:
  * ``CROSS_AI_AGENTS_FILE`` env var redirected to a temp file so neither
    the user's real ``~/.cross_ai_models.json`` nor the cross-ai-core
    in-process registry from other tests is touched permanently.
  * ``cross_ai_core.agents.reload_agents()`` is called in fixtures to make
    sure the registry reflects each test's file.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ── Module loader (st-admin.py has a hyphen → cannot use plain import) ───────
_SPEC = importlib.util.spec_from_file_location(
    "st_admin", Path(__file__).parent.parent / "cross_st" / "st-admin.py"
)
st_admin = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(st_admin)

# Ensure ``cross_st/`` is on sys.path so the agent-admin internal import works
# the same way it does at runtime.
_CROSS_ST = str(Path(__file__).parent.parent / "cross_st")
if _CROSS_ST not in sys.path:
    sys.path.insert(0, _CROSS_ST)

import _agent_admin  # noqa: E402
from cross_ai_core.agents import reload_agents, get_agents  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_agent_file(tmp_path, monkeypatch):
    """Redirect the agent JSON file to a temp path; reload the registry.

    Post-AGT-1 the cross-ai-core registry no longer auto-seeds built-in
    providers, so this fixture re-seeds them after ``reload_agents()``
    to preserve the CST-MM-i test contract (``list_agents()`` returns
    one row per built-in self-agent when the file is empty).
    """
    f = tmp_path / "cross_ai_models.json"
    monkeypatch.setenv("CROSS_AI_AGENTS_FILE", str(f))
    reload_agents()
    # Re-seed built-ins so tests written against the pre-AGT-1 contract
    # (where the registry always exposed every provider) keep passing.
    from cross_ai_core.agents import _AI_ALIASES, AgentSpec
    for make in _agent_admin._builtin_makes():
        _AI_ALIASES.setdefault(make, AgentSpec(make=make, model=None))
    yield f
    # Reset env var; reload so other tests aren't polluted.
    monkeypatch.delenv("CROSS_AI_AGENTS_FILE", raising=False)
    reload_agents()


# ── _agent_admin: file I/O ───────────────────────────────────────────────────

class TestReadAliasFile:
    def test_missing_file_returns_empty(self, isolated_agent_file):
        assert _agent_admin.read_agents_file() == {}

    def test_malformed_json_returns_empty(self, isolated_agent_file):
        isolated_agent_file.write_text("{not valid json")
        assert _agent_admin.read_agents_file() == {}

    def test_round_trip(self, isolated_agent_file):
        data = {"anthropic-opus": {"make": "anthropic", "model": "claude-opus-4-5"}}
        _agent_admin.write_agents_file(data)
        loaded = _agent_admin.read_agents_file()
        assert loaded == data

    def test_write_is_atomic_no_tmp_left_behind(self, isolated_agent_file):
        _agent_admin.write_agents_file({"x": {"make": "xai", "model": None}})
        siblings = list(isolated_agent_file.parent.iterdir())
        # Only the target file — no .tmp leftovers.
        assert siblings == [isolated_agent_file]

    def test_write_reloads_registry(self, isolated_agent_file):
        _agent_admin.write_agents_file(
            {"anthropic-opus": {"make": "anthropic", "model": "claude-opus-4-5"}}
        )
        # After write, cross-ai-core's in-process registry must see the new agent.
        assert "anthropic-opus" in get_agents()


# ── _agent_admin: add_agent ──────────────────────────────────────────────────

class TestAddAlias:
    def test_happy_path(self, isolated_agent_file):
        _agent_admin.add_agent("anthropic-opus", "anthropic", "claude-opus-4-5")
        data = _agent_admin.read_agents_file()
        assert data == {
            "anthropic-opus": {"make": "anthropic", "model": "claude-opus-4-5"}
        }
        # And the registry sees it.
        assert "anthropic-opus" in get_agents()

    def test_model_none_means_handler_default(self, isolated_agent_file):
        _agent_admin.add_agent("custom", "openai", None)
        data = _agent_admin.read_agents_file()
        assert data["custom"] == {"make": "openai", "model": None}

    def test_empty_model_string_normalises_to_none(self, isolated_agent_file):
        _agent_admin.add_agent("custom", "xai", "  ")
        assert _agent_admin.read_agents_file()["custom"]["model"] is None

    def test_empty_name_rejected(self, isolated_agent_file):
        with pytest.raises(_agent_admin.AgentError, match="empty"):
            _agent_admin.add_agent("", "anthropic", "claude-opus-4-5")

    def test_unknown_make_rejected(self, isolated_agent_file):
        with pytest.raises(_agent_admin.AgentError, match="Unknown make"):
            _agent_admin.add_agent("foo", "no_such_make", None)

    def test_collision_with_builtin_make_rejected(self, isolated_agent_file):
        # 'anthropic' is a built-in; pointing it at a different mapping
        # would silently change what --ai anthropic means.
        with pytest.raises(_agent_admin.AgentError, match="shadow"):
            _agent_admin.add_agent("anthropic", "anthropic", "claude-opus-4-5")

    def test_self_agent_to_builtin_with_none_is_allowed(self, isolated_agent_file):
        # Identity mapping (same make, model=None) is harmless — this is what
        # the auto-seeder does at registry load.
        _agent_admin.add_agent("xai", "xai", None)
        assert _agent_admin.read_agents_file()["xai"] == {"make": "xai", "model": None}

    def test_replace_existing(self, isolated_agent_file):
        _agent_admin.add_agent("anthropic-opus", "anthropic", "claude-opus-4-5")
        _agent_admin.add_agent("anthropic-opus", "anthropic", "claude-opus-4-6")
        assert (
            _agent_admin.read_agents_file()["anthropic-opus"]["model"]
            == "claude-opus-4-6"
        )


# ── _agent_admin: remove_agent ───────────────────────────────────────────────

class TestRemoveAlias:
    def test_happy_path(self, isolated_agent_file):
        _agent_admin.add_agent("opus", "anthropic", "claude-opus-4-5")
        _agent_admin.remove_agent("opus")
        assert _agent_admin.read_agents_file() == {}

    def test_missing_user_alias_raises(self, isolated_agent_file):
        with pytest.raises(_agent_admin.AgentError, match="No agent"):
            _agent_admin.remove_agent("nonexistent")

    def test_builtin_self_alias_refused(self, isolated_agent_file):
        # 'anthropic' is built-in — auto-seeded but not in the user file.
        with pytest.raises(_agent_admin.AgentError, match="built-in"):
            _agent_admin.remove_agent("anthropic")


# ── _agent_admin: edit_agent_model ───────────────────────────────────────────

class TestEditAliasModel:
    def test_happy_path(self, isolated_agent_file):
        _agent_admin.add_agent("opus", "anthropic", "claude-opus-4-5")
        _agent_admin.edit_agent_model("opus", "claude-opus-4-6")
        assert _agent_admin.read_agents_file()["opus"]["model"] == "claude-opus-4-6"

    def test_set_to_none(self, isolated_agent_file):
        _agent_admin.add_agent("opus", "anthropic", "claude-opus-4-5")
        _agent_admin.edit_agent_model("opus", None)
        assert _agent_admin.read_agents_file()["opus"]["model"] is None

    def test_missing_alias_raises(self, isolated_agent_file):
        with pytest.raises(_agent_admin.AgentError, match="No user agent"):
            _agent_admin.edit_agent_model("nope", "x")


# ── _agent_admin: list_agents / format_agent_table ──────────────────────────

class TestListAliases:
    def test_lists_all_builtins_when_file_empty(self, isolated_agent_file):
        rows = _agent_admin.list_agents()
        builtins = _agent_admin._builtin_makes()
        # One row per built-in self-agent; all flagged is_builtin=True.
        for make in builtins:
            assert any(r["agent"] == make and r["is_builtin"] for r in rows), make

    def test_user_alias_not_marked_builtin(self, isolated_agent_file):
        _agent_admin.add_agent("anthropic-opus", "anthropic", "claude-opus-4-5")
        rows = _agent_admin.list_agents()
        opus = next(r for r in rows if r["agent"] == "anthropic-opus")
        assert opus["is_builtin"] is False
        assert opus["model_effective"] == "claude-opus-4-5"
        assert opus["model_file"] == "claude-opus-4-5"

    def test_env_override_picked_up(self, isolated_agent_file, monkeypatch):
        _agent_admin.add_agent("anthropic-opus", "anthropic", "claude-opus-4-5")
        monkeypatch.setenv("ANTHROPIC_OPUS_MODEL", "claude-opus-future")
        rows = _agent_admin.list_agents()
        opus = next(r for r in rows if r["agent"] == "anthropic-opus")
        assert opus["env_override"] == "ANTHROPIC_OPUS_MODEL"
        assert opus["model_effective"] == "claude-opus-future"

    def test_make_env_override_fallback(self, isolated_agent_file, monkeypatch):
        # Bare-make agent picks up <MAKE>_MODEL when no <ALIAS>_MODEL set.
        monkeypatch.setenv("XAI_MODEL", "grok-3-latest")
        rows = _agent_admin.list_agents()
        xai = next(r for r in rows if r["agent"] == "xai")
        assert xai["env_override"] == "XAI_MODEL"
        assert xai["model_effective"] == "grok-3-latest"

    def test_format_agent_table_renders(self, isolated_agent_file):
        _agent_admin.add_agent("anthropic-opus", "anthropic", "claude-opus-4-5")
        # add_agent → write_agents_file → reload_agents() wipes the
        # built-in seed installed by the fixture.  Re-seed so the table
        # renders both built-in and user-defined rows.
        from cross_ai_core.agents import _AI_ALIASES, AgentSpec
        for make in _agent_admin._builtin_makes():
            _AI_ALIASES.setdefault(make, AgentSpec(make=make, model=None))
        text = _agent_admin.format_agent_table(_agent_admin.list_agents())
        assert "Agent" in text and "Provider" in text and "Model" in text
        assert "Env override" in text
        assert "anthropic-opus" in text and "claude-opus-4-5" in text
        # Built-in self-agent rendered alongside the user-defined one.
        assert "anthropic" in text


# ── CLI flags — invoke st-admin as a subprocess ──────────────────────────────

def _run_st_admin(*args, env_extra=None):
    """Spawn st-admin in a child process so argparse + sys.exit work normally.

    Strips every provider's API-key env vars so the AGT-2 first-run
    migration does not seed unwanted starter agents into the test's tmp
    agent file (would shadow the asserted post-state).
    """
    import os
    env = os.environ.copy()
    env["PATH"] = f"{_CROSS_ST}:{env['PATH']}"  # ensure module path
    # Strip API-key env vars — keeps AGT-2 migration in "empty" branch
    # so it never writes seeded built-ins into the test's tmp file.
    from cross_ai_core.keys import PROVIDER_API_KEY_ENV
    for env_names in PROVIDER_API_KEY_ENV.values():
        for var in env_names:
            env.pop(var, None)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(Path(_CROSS_ST) / "st-admin.py"), *args],
        capture_output=True, text=True, env=env, timeout=15,
    )
    return proc


class TestCliAddAlias:
    def test_happy_path(self, tmp_path):
        f = tmp_path / "agents.json"
        # Pre-seed an empty v2 envelope so the AGT-2 migration is a no-op
        # in the subprocess (otherwise any stray API key reachable via
        # ~/.crossenv would seed starter agents into the file).
        f.write_text(json.dumps({
            "version": 2, "agents": {}, "_migrated_to_agents_v2": True,
        }))
        proc = _run_st_admin(
            "--add-agent", "anthropic-opus=anthropic:claude-opus-4-5",
            env_extra={"CROSS_AI_AGENTS_FILE": str(f)},
        )
        assert proc.returncode == 0, proc.stderr
        assert "anthropic-opus" in proc.stdout
        # On-disk shape is the v2 envelope; flatten via read_agents_file.
        import os
        os.environ["CROSS_AI_AGENTS_FILE"] = str(f)
        try:
            data = _agent_admin.read_agents_file()
        finally:
            del os.environ["CROSS_AI_AGENTS_FILE"]
        assert data == {
            "anthropic-opus": {"make": "anthropic", "model": "claude-opus-4-5"}
        }

    def test_no_model_means_handler_default(self, tmp_path):
        f = tmp_path / "agents.json"
        f.write_text(json.dumps({
            "version": 2, "agents": {}, "_migrated_to_agents_v2": True,
        }))
        proc = _run_st_admin(
            "--add-agent", "fast=xai",
            env_extra={"CROSS_AI_AGENTS_FILE": str(f)},
        )
        assert proc.returncode == 0, proc.stderr
        import os
        os.environ["CROSS_AI_AGENTS_FILE"] = str(f)
        try:
            data = _agent_admin.read_agents_file()
        finally:
            del os.environ["CROSS_AI_AGENTS_FILE"]
        assert data == {"fast": {"make": "xai", "model": None}}

    def test_bad_format_exits_1(self, tmp_path):
        proc = _run_st_admin(
            "--add-agent", "no_equals_sign",
            env_extra={"CROSS_AI_AGENTS_FILE": str(tmp_path / "x.json")},
        )
        assert proc.returncode == 1
        assert "NAME=MAKE" in proc.stderr

    def test_unknown_make_exits_1(self, tmp_path):
        proc = _run_st_admin(
            "--add-agent", "x=no_such_provider",
            env_extra={"CROSS_AI_AGENTS_FILE": str(tmp_path / "x.json")},
        )
        assert proc.returncode == 1
        assert "Unknown make" in proc.stderr


class TestCliRemoveAlias:
    def test_happy_path(self, tmp_path):
        f = tmp_path / "agents.json"
        f.write_text(json.dumps({"opus": {"make": "anthropic", "model": "x"}}))
        proc = _run_st_admin(
            "--remove-agent", "opus",
            env_extra={"CROSS_AI_AGENTS_FILE": str(f)},
        )
        assert proc.returncode == 0, proc.stderr
        import os
        os.environ["CROSS_AI_AGENTS_FILE"] = str(f)
        try:
            assert _agent_admin.read_agents_file() == {}
        finally:
            del os.environ["CROSS_AI_AGENTS_FILE"]

    def test_builtin_refused(self, tmp_path):
        # AGT-2: write an explicit (empty) v2 envelope so the migration is a
        # no-op and the registry stays empty — otherwise on a developer
        # machine the legacy ``anthropic`` self-agent has already been
        # written into the test home dir by a prior test, then loaded into
        # this subprocess via the real ``CROSS_AI_AGENTS_FILE`` resolution.
        f = tmp_path / "empty.json"
        f.write_text(json.dumps({
            "version": 2, "agents": {}, "_migrated_to_agents_v2": True,
        }))
        proc = _run_st_admin(
            "--remove-agent", "anthropic",
            env_extra={"CROSS_AI_AGENTS_FILE": str(f)},
        )
        assert proc.returncode == 1
        assert "built-in" in proc.stderr


class TestCliListAliases:
    def test_smoke(self, tmp_path):
        f = tmp_path / "agents.json"
        f.write_text(json.dumps(
            {"anthropic-opus": {"make": "anthropic", "model": "claude-opus-4-5"}}
        ))
        proc = _run_st_admin(
            "--list-agents",
            env_extra={"CROSS_AI_AGENTS_FILE": str(f)},
        )
        assert proc.returncode == 0, proc.stderr
        # Header + at least the new agent and the built-ins are present.
        assert "Agent" in proc.stdout
        assert "anthropic-opus" in proc.stdout
        assert "claude-opus-4-5" in proc.stdout


# ── Menu definition smoke ────────────────────────────────────────────────────

class TestMenuDefinition:
    def test_ai_submenu_has_manage_aliases_entry(self):
        ai_label, ai_sub = st_admin._MENU["a"]
        assert ai_label == "AI"
        # 'm' is now a sub-submenu (tuple), not a leaf string.
        assert isinstance(ai_sub["m"], tuple)
        manage_label, manage_sub = ai_sub["m"]
        assert manage_label == "Manage agents"
        # All four mutation actions are bound (a/r/e/R) plus the table
        # view (M) which is also surfaced one level up.
        for k in ("a", "r", "e", "R", "M"):
            assert k in manage_sub

    def test_ai_submenu_has_view_aliases_leaf(self):
        ai_label, ai_sub = st_admin._MENU["a"]
        assert isinstance(ai_sub["M"], str)
        assert "agent" in ai_sub["M"].lower()


# ── Recommended-models curated list ──────────────────────────────────────────

class TestRecommendedModels:
    def test_every_builtin_has_at_least_one_recommendation(self):
        for make in _agent_admin._builtin_makes():
            recs = _agent_admin.get_recommended_models(make)
            assert recs, f"no curated recommendations for {make}"
            # At least one is flagged recommended=True (★).
            assert any(r[2] for r in recs), f"no ★ recs for {make}"

    def test_unknown_make_returns_empty(self):
        assert _agent_admin.get_recommended_models("no_such_make") == []

