"""
tests/test_agent_migration.py — CST-MM-j regression tests.

Covers the silent ``.ai_models`` → ``~/.cross_ai_models.json`` migration:

  * ``_agent_admin._model_short_id``        — sanitiser
  * ``_agent_admin._parse_legacy_ai_models``— file parser (lenient)
  * ``_agent_admin.migrate_legacy_ai_models``— full migration helper
  * ``_agent_admin.run_migration_with_notice``— prints + swallows errors
  * Idempotency — second invocation is a no-op (legacy file renamed to
    ``.ai_models.migrated``).
  * Skip rules — unknown make, exact (make, model) duplicate already in
    the agent file, blank/comment lines.

Isolation: ``CROSS_AI_AGENTS_FILE`` redirects the agent JSON to tmp;
``mmd_startup._PROJECT_ROOT`` is monkeypatched so the legacy file lives
under tmp_path, never touching the real repo root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure cross_st/ is importable
_CROSS_ST = str(Path(__file__).parent.parent / "cross_st")
if _CROSS_ST not in sys.path:
    sys.path.insert(0, _CROSS_ST)

import _agent_admin  # noqa: E402
import mmd_startup   # noqa: E402
from cross_ai_core.agents import reload_agents  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Tmp agent JSON + tmp project root for the legacy file."""
    agent_file = tmp_path / "cross_ai_models.json"
    monkeypatch.setenv("CROSS_AI_AGENTS_FILE", str(agent_file))
    monkeypatch.setattr(mmd_startup, "_PROJECT_ROOT", str(tmp_path))
    reload_agents()
    yield tmp_path
    monkeypatch.delenv("CROSS_AI_AGENTS_FILE", raising=False)
    reload_agents()


def _write_legacy(tmp_path: Path, body: str) -> Path:
    p = tmp_path / ".ai_models"
    p.write_text(body)
    return p


# ── _model_short_id ──────────────────────────────────────────────────────────

class TestModelShortId:
    def test_sanitises_dots_to_dash(self):
        assert _agent_admin._model_short_id("claude-opus-4.5") == "claude-opus-4-5"

    def test_collapses_runs(self):
        assert _agent_admin._model_short_id("a..b__c") == "a-b-c"

    def test_lowercases(self):
        assert _agent_admin._model_short_id("GPT-4o-MINI") == "gpt-4o-mini"

    def test_truncates(self):
        long = "x" * 100
        assert len(_agent_admin._model_short_id(long)) <= _agent_admin._MODEL_SHORT_MAX

    def test_empty_falls_back(self):
        assert _agent_admin._model_short_id("***") == "custom"


# ── parser ───────────────────────────────────────────────────────────────────

class TestParser:
    def test_skips_blanks_and_comments(self, tmp_path):
        p = _write_legacy(tmp_path, "# comment\n\nxai=grok-3\n   \nopenai=gpt-4o\n")
        pairs = _agent_admin._parse_legacy_ai_models(str(p))
        assert pairs == [("xai", "grok-3"), ("openai", "gpt-4o")]

    def test_skips_lines_without_equals(self, tmp_path):
        p = _write_legacy(tmp_path, "junkline\nxai=grok-3\n")
        assert _agent_admin._parse_legacy_ai_models(str(p)) == [("xai", "grok-3")]

    def test_missing_file_returns_empty(self, tmp_path):
        assert _agent_admin._parse_legacy_ai_models(str(tmp_path / "nope")) == []


# ── migrate_legacy_ai_models ────────────────────────────────────────────────

class TestMigrate:
    def test_no_legacy_file_is_noop(self, isolated_env):
        assert _agent_admin.migrate_legacy_ai_models() == []
        assert not (isolated_env / ".ai_models.migrated").exists()

    def test_creates_agents_and_renames(self, isolated_env):
        _write_legacy(isolated_env,
                      "anthropic=claude-opus-4-5\nxai=grok-3\n")
        added = _agent_admin.migrate_legacy_ai_models()
        names = {a for a, _, _ in added}
        assert names == {"anthropic-claude-opus-4-5", "xai-grok-3"}
        # Legacy file renamed
        assert not (isolated_env / ".ai_models").exists()
        assert (isolated_env / ".ai_models.migrated").exists()
        # Agents persisted
        data = _agent_admin.read_agents_file()
        assert data["anthropic-claude-opus-4-5"] == {
            "make": "anthropic", "model": "claude-opus-4-5"
        }

    def test_idempotent_second_run(self, isolated_env):
        _write_legacy(isolated_env, "xai=grok-3\n")
        first = _agent_admin.migrate_legacy_ai_models()
        assert len(first) == 1
        # Second invocation — no legacy file → empty
        second = _agent_admin.migrate_legacy_ai_models()
        assert second == []

    def test_unknown_make_skipped(self, isolated_env):
        _write_legacy(isolated_env, "bogus=some-model\nxai=grok-3\n")
        added = _agent_admin.migrate_legacy_ai_models()
        names = {a for a, _, _ in added}
        assert names == {"xai-grok-3"}

    def test_duplicate_skipped(self, isolated_env):
        # Pre-seed agent file with the exact pair
        _agent_admin.write_agents_file({
            "myxai": {"make": "xai", "model": "grok-3"},
        })
        _write_legacy(isolated_env, "xai=grok-3\n")
        added = _agent_admin.migrate_legacy_ai_models()
        assert added == []  # nothing new
        # Legacy still renamed
        assert (isolated_env / ".ai_models.migrated").exists()

    def test_collision_appends_suffix(self, isolated_env):
        _agent_admin.write_agents_file({
            "xai-grok-3": {"make": "xai", "model": "different-model"},
        })
        _write_legacy(isolated_env, "xai=grok-3\n")
        added = _agent_admin.migrate_legacy_ai_models()
        names = {a for a, _, _ in added}
        assert names == {"xai-grok-3-2"}

    def test_empty_legacy_renamed(self, isolated_env):
        _write_legacy(isolated_env, "# only comments\n\n")
        added = _agent_admin.migrate_legacy_ai_models()
        assert added == []
        assert (isolated_env / ".ai_models.migrated").exists()


# ── run_migration_with_notice ────────────────────────────────────────────────

class TestNotice:
    def test_silent_when_nothing_to_do(self, isolated_env, capsys):
        _agent_admin.run_migration_with_notice()
        out = capsys.readouterr()
        assert out.out == ""
        assert out.err == ""

    def test_prints_summary_on_success(self, isolated_env, capsys):
        _write_legacy(isolated_env, "anthropic=claude-opus-4-5\n")
        _agent_admin.run_migration_with_notice()
        out = capsys.readouterr().out
        assert "Migrated legacy .ai_models" in out
        assert "anthropic-claude-opus-4-5" in out

    def test_swallows_exceptions(self, isolated_env, capsys, monkeypatch):
        def boom():
            raise RuntimeError("kaboom")
        monkeypatch.setattr(_agent_admin, "migrate_legacy_ai_models", boom)
        # Must NOT raise
        _agent_admin.run_migration_with_notice()
        out = capsys.readouterr().out
        assert "Could not migrate" in out
        assert "kaboom" in out


# ── mmd_startup wrapper ──────────────────────────────────────────────────────

class TestStartupHook:
    def test_noop_when_no_legacy(self, isolated_env, capsys):
        # Wrapper is the entry-point used by load_cross_env()
        mmd_startup._migrate_legacy_ai_models_once()
        assert capsys.readouterr().out == ""

    def test_runs_when_legacy_present(self, isolated_env, capsys):
        _write_legacy(isolated_env, "openai=gpt-4o\n")
        mmd_startup._migrate_legacy_ai_models_once()
        assert "Migrated legacy .ai_models" in capsys.readouterr().out
        assert (isolated_env / ".ai_models.migrated").exists()

