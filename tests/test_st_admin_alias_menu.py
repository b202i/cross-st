"""
tests/test_st_admin_alias_menu.py — CST-MM-i regression tests.

Covers the alias-management layer added to ``st-admin`` in 0.9.x:

  * ``cross_st/_alias_admin.py``   read/write/add/remove/edit + listing helpers.
  * ``st-admin --add-alias``       CLI flag (happy + error paths).
  * ``st-admin --remove-alias``    CLI flag (happy + error paths).
  * ``st-admin --list-aliases``    CLI flag (smoke).

Isolation strategy:
  * ``CROSS_AI_ALIASES_FILE`` env var redirected to a temp file so neither
    the user's real ``~/.cross_ai_models.json`` nor the cross-ai-core
    in-process registry from other tests is touched permanently.
  * ``cross_ai_core.aliases.reload_aliases()`` is called in fixtures to make
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

# Ensure ``cross_st/`` is on sys.path so the alias-admin internal import works
# the same way it does at runtime.
_CROSS_ST = str(Path(__file__).parent.parent / "cross_st")
if _CROSS_ST not in sys.path:
    sys.path.insert(0, _CROSS_ST)

import _alias_admin  # noqa: E402
from cross_ai_core.aliases import reload_aliases, get_aliases  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_alias_file(tmp_path, monkeypatch):
    """Redirect the alias JSON file to a temp path; reload the registry."""
    f = tmp_path / "cross_ai_models.json"
    monkeypatch.setenv("CROSS_AI_ALIASES_FILE", str(f))
    reload_aliases()
    yield f
    # Reset env var; reload so other tests aren't polluted.
    monkeypatch.delenv("CROSS_AI_ALIASES_FILE", raising=False)
    reload_aliases()


# ── _alias_admin: file I/O ───────────────────────────────────────────────────

class TestReadAliasFile:
    def test_missing_file_returns_empty(self, isolated_alias_file):
        assert _alias_admin.read_alias_file() == {}

    def test_malformed_json_returns_empty(self, isolated_alias_file):
        isolated_alias_file.write_text("{not valid json")
        assert _alias_admin.read_alias_file() == {}

    def test_round_trip(self, isolated_alias_file):
        data = {"anthropic-opus": {"make": "anthropic", "model": "claude-opus-4-5"}}
        _alias_admin.write_alias_file(data)
        loaded = _alias_admin.read_alias_file()
        assert loaded == data

    def test_write_is_atomic_no_tmp_left_behind(self, isolated_alias_file):
        _alias_admin.write_alias_file({"x": {"make": "xai", "model": None}})
        siblings = list(isolated_alias_file.parent.iterdir())
        # Only the target file — no .tmp leftovers.
        assert siblings == [isolated_alias_file]

    def test_write_reloads_registry(self, isolated_alias_file):
        _alias_admin.write_alias_file(
            {"anthropic-opus": {"make": "anthropic", "model": "claude-opus-4-5"}}
        )
        # After write, cross-ai-core's in-process registry must see the new alias.
        assert "anthropic-opus" in get_aliases()


# ── _alias_admin: add_alias ──────────────────────────────────────────────────

class TestAddAlias:
    def test_happy_path(self, isolated_alias_file):
        _alias_admin.add_alias("anthropic-opus", "anthropic", "claude-opus-4-5")
        data = _alias_admin.read_alias_file()
        assert data == {
            "anthropic-opus": {"make": "anthropic", "model": "claude-opus-4-5"}
        }
        # And the registry sees it.
        assert "anthropic-opus" in get_aliases()

    def test_model_none_means_handler_default(self, isolated_alias_file):
        _alias_admin.add_alias("custom", "openai", None)
        data = _alias_admin.read_alias_file()
        assert data["custom"] == {"make": "openai", "model": None}

    def test_empty_model_string_normalises_to_none(self, isolated_alias_file):
        _alias_admin.add_alias("custom", "xai", "  ")
        assert _alias_admin.read_alias_file()["custom"]["model"] is None

    def test_empty_name_rejected(self, isolated_alias_file):
        with pytest.raises(_alias_admin.AliasError, match="empty"):
            _alias_admin.add_alias("", "anthropic", "claude-opus-4-5")

    def test_unknown_make_rejected(self, isolated_alias_file):
        with pytest.raises(_alias_admin.AliasError, match="Unknown make"):
            _alias_admin.add_alias("foo", "no_such_make", None)

    def test_collision_with_builtin_make_rejected(self, isolated_alias_file):
        # 'anthropic' is a built-in; pointing it at a different mapping
        # would silently change what --ai anthropic means.
        with pytest.raises(_alias_admin.AliasError, match="shadow"):
            _alias_admin.add_alias("anthropic", "anthropic", "claude-opus-4-5")

    def test_self_alias_to_builtin_with_none_is_allowed(self, isolated_alias_file):
        # Identity mapping (same make, model=None) is harmless — this is what
        # the auto-seeder does at registry load.
        _alias_admin.add_alias("xai", "xai", None)
        assert _alias_admin.read_alias_file()["xai"] == {"make": "xai", "model": None}

    def test_replace_existing(self, isolated_alias_file):
        _alias_admin.add_alias("anthropic-opus", "anthropic", "claude-opus-4-5")
        _alias_admin.add_alias("anthropic-opus", "anthropic", "claude-opus-4-6")
        assert (
            _alias_admin.read_alias_file()["anthropic-opus"]["model"]
            == "claude-opus-4-6"
        )


# ── _alias_admin: remove_alias ───────────────────────────────────────────────

class TestRemoveAlias:
    def test_happy_path(self, isolated_alias_file):
        _alias_admin.add_alias("opus", "anthropic", "claude-opus-4-5")
        _alias_admin.remove_alias("opus")
        assert _alias_admin.read_alias_file() == {}

    def test_missing_user_alias_raises(self, isolated_alias_file):
        with pytest.raises(_alias_admin.AliasError, match="No alias"):
            _alias_admin.remove_alias("nonexistent")

    def test_builtin_self_alias_refused(self, isolated_alias_file):
        # 'anthropic' is built-in — auto-seeded but not in the user file.
        with pytest.raises(_alias_admin.AliasError, match="built-in"):
            _alias_admin.remove_alias("anthropic")


# ── _alias_admin: edit_alias_model ───────────────────────────────────────────

class TestEditAliasModel:
    def test_happy_path(self, isolated_alias_file):
        _alias_admin.add_alias("opus", "anthropic", "claude-opus-4-5")
        _alias_admin.edit_alias_model("opus", "claude-opus-4-6")
        assert _alias_admin.read_alias_file()["opus"]["model"] == "claude-opus-4-6"

    def test_set_to_none(self, isolated_alias_file):
        _alias_admin.add_alias("opus", "anthropic", "claude-opus-4-5")
        _alias_admin.edit_alias_model("opus", None)
        assert _alias_admin.read_alias_file()["opus"]["model"] is None

    def test_missing_alias_raises(self, isolated_alias_file):
        with pytest.raises(_alias_admin.AliasError, match="No user alias"):
            _alias_admin.edit_alias_model("nope", "x")


# ── _alias_admin: list_aliases / format_alias_table ──────────────────────────

class TestListAliases:
    def test_lists_all_builtins_when_file_empty(self, isolated_alias_file):
        rows = _alias_admin.list_aliases()
        builtins = _alias_admin._builtin_makes()
        # One row per built-in self-alias; all flagged is_builtin=True.
        for make in builtins:
            assert any(r["alias"] == make and r["is_builtin"] for r in rows), make

    def test_user_alias_not_marked_builtin(self, isolated_alias_file):
        _alias_admin.add_alias("anthropic-opus", "anthropic", "claude-opus-4-5")
        rows = _alias_admin.list_aliases()
        opus = next(r for r in rows if r["alias"] == "anthropic-opus")
        assert opus["is_builtin"] is False
        assert opus["model_effective"] == "claude-opus-4-5"
        assert opus["model_file"] == "claude-opus-4-5"

    def test_env_override_picked_up(self, isolated_alias_file, monkeypatch):
        _alias_admin.add_alias("anthropic-opus", "anthropic", "claude-opus-4-5")
        monkeypatch.setenv("ANTHROPIC_OPUS_MODEL", "claude-opus-future")
        rows = _alias_admin.list_aliases()
        opus = next(r for r in rows if r["alias"] == "anthropic-opus")
        assert opus["env_override"] == "ANTHROPIC_OPUS_MODEL"
        assert opus["model_effective"] == "claude-opus-future"

    def test_make_env_override_fallback(self, isolated_alias_file, monkeypatch):
        # Bare-make alias picks up <MAKE>_MODEL when no <ALIAS>_MODEL set.
        monkeypatch.setenv("XAI_MODEL", "grok-3-latest")
        rows = _alias_admin.list_aliases()
        xai = next(r for r in rows if r["alias"] == "xai")
        assert xai["env_override"] == "XAI_MODEL"
        assert xai["model_effective"] == "grok-3-latest"

    def test_format_alias_table_renders(self, isolated_alias_file):
        _alias_admin.add_alias("anthropic-opus", "anthropic", "claude-opus-4-5")
        text = _alias_admin.format_alias_table(_alias_admin.list_aliases())
        assert "Agent" in text and "Provider" in text and "Model" in text
        assert "Type" in text and "Env override" in text
        assert "anthropic-opus" in text and "claude-opus-4-5" in text
        # Custom aliases tagged "custom"; default ones tagged "default".
        assert "custom"  in text
        assert "default" in text


# ── CLI flags — invoke st-admin as a subprocess ──────────────────────────────

def _run_st_admin(*args, env_extra=None):
    """Spawn st-admin in a child process so argparse + sys.exit work normally."""
    import os
    env = os.environ.copy()
    env["PATH"] = f"{_CROSS_ST}:{env['PATH']}"  # ensure module path
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(Path(_CROSS_ST) / "st-admin.py"), *args],
        capture_output=True, text=True, env=env, timeout=15,
    )
    return proc


class TestCliAddAlias:
    def test_happy_path(self, tmp_path):
        f = tmp_path / "aliases.json"
        proc = _run_st_admin(
            "--add-alias", "anthropic-opus=anthropic:claude-opus-4-5",
            env_extra={"CROSS_AI_ALIASES_FILE": str(f)},
        )
        assert proc.returncode == 0, proc.stderr
        assert "anthropic-opus" in proc.stdout
        data = json.loads(f.read_text())
        assert data == {
            "anthropic-opus": {"make": "anthropic", "model": "claude-opus-4-5"}
        }

    def test_no_model_means_handler_default(self, tmp_path):
        f = tmp_path / "aliases.json"
        proc = _run_st_admin(
            "--add-alias", "fast=xai",
            env_extra={"CROSS_AI_ALIASES_FILE": str(f)},
        )
        assert proc.returncode == 0, proc.stderr
        data = json.loads(f.read_text())
        assert data == {"fast": {"make": "xai", "model": None}}

    def test_bad_format_exits_1(self, tmp_path):
        proc = _run_st_admin(
            "--add-alias", "no_equals_sign",
            env_extra={"CROSS_AI_ALIASES_FILE": str(tmp_path / "x.json")},
        )
        assert proc.returncode == 1
        assert "NAME=MAKE" in proc.stderr

    def test_unknown_make_exits_1(self, tmp_path):
        proc = _run_st_admin(
            "--add-alias", "x=no_such_provider",
            env_extra={"CROSS_AI_ALIASES_FILE": str(tmp_path / "x.json")},
        )
        assert proc.returncode == 1
        assert "Unknown make" in proc.stderr


class TestCliRemoveAlias:
    def test_happy_path(self, tmp_path):
        f = tmp_path / "aliases.json"
        f.write_text(json.dumps({"opus": {"make": "anthropic", "model": "x"}}))
        proc = _run_st_admin(
            "--remove-alias", "opus",
            env_extra={"CROSS_AI_ALIASES_FILE": str(f)},
        )
        assert proc.returncode == 0, proc.stderr
        assert json.loads(f.read_text()) == {}

    def test_builtin_refused(self, tmp_path):
        proc = _run_st_admin(
            "--remove-alias", "anthropic",
            env_extra={"CROSS_AI_ALIASES_FILE": str(tmp_path / "empty.json")},
        )
        assert proc.returncode == 1
        assert "built-in" in proc.stderr


class TestCliListAliases:
    def test_smoke(self, tmp_path):
        f = tmp_path / "aliases.json"
        f.write_text(json.dumps(
            {"anthropic-opus": {"make": "anthropic", "model": "claude-opus-4-5"}}
        ))
        proc = _run_st_admin(
            "--list-aliases",
            env_extra={"CROSS_AI_ALIASES_FILE": str(f)},
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
        for make in _alias_admin._builtin_makes():
            recs = _alias_admin.get_recommended_models(make)
            assert recs, f"no curated recommendations for {make}"
            # At least one is flagged recommended=True (★).
            assert any(r[2] for r in recs), f"no ★ recs for {make}"

    def test_unknown_make_returns_empty(self):
        assert _alias_admin.get_recommended_models("no_such_make") == []

