"""
tests/test_agents_v2_migration.py — AGT-2 regression tests.

Covers ``_agent_admin.migrate_to_agents_v2`` and the
``mmd_startup._migrate_to_agents_v2_once`` startup hook:

  * No file + no API keys     → "empty"  (no write, no notice)
  * No file + some API keys   → "seeded" (one starter agent per detected provider)
  * Existing v1 flat dict     → "v1_to_v2" (envelope written, names preserved)
  * Existing v2 envelope      → "noop"   (idempotent on second run)
  * write_agents_file always wraps in v2 envelope on disk
  * read_agents_file flattens both v1 and v2 inputs back to flat shape
"""

from __future__ import annotations

import json
import sys
from collections import OrderedDict
from pathlib import Path

import pytest

# Ensure cross_st/ is importable
_CROSS_ST = str(Path(__file__).parent.parent / "cross_st")
if _CROSS_ST not in sys.path:
    sys.path.insert(0, _CROSS_ST)

import _agent_admin  # noqa: E402
import mmd_startup   # noqa: E402
from cross_ai_core.agents import reload_agents  # noqa: E402
from cross_ai_core.keys import PROVIDER_API_KEY_ENV  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_agents_file(tmp_path, monkeypatch):
    """Tmp agent JSON path; clear every API-key env var by default."""
    agent_file = tmp_path / "cross_ai_models.json"
    monkeypatch.setenv("CROSS_AI_AGENTS_FILE", str(agent_file))
    # Strip every provider's API-key env vars so seeding starts from a clean slate.
    for env_names in PROVIDER_API_KEY_ENV.values():
        for var in env_names:
            monkeypatch.delenv(var, raising=False)
    reload_agents()
    yield agent_file
    monkeypatch.delenv("CROSS_AI_AGENTS_FILE", raising=False)
    reload_agents()


def _read_envelope(path: Path) -> dict:
    return json.loads(path.read_text())


# ── read_agents_file / write_agents_file round-trip ────────────────────────────

class TestEnvelopeRoundTrip:
    def test_write_emits_v2_envelope(self, isolated_agents_file):
        _agent_admin.write_agents_file({
            "myxai": {"make": "xai", "model": "grok-3"},
        })
        env = _read_envelope(isolated_agents_file)
        assert env["version"] == 2
        assert env["_migrated_to_agents_v2"] is True
        assert env["agents"]["myxai"] == {"provider": "xai", "model": "grok-3"}

    def test_read_unwraps_v2_to_flat(self, isolated_agents_file):
        # Hand-write a v2 envelope and confirm the flat-shape contract holds.
        isolated_agents_file.write_text(json.dumps({
            "version": 2,
            "agents": {"a1": {"provider": "anthropic", "model": "claude-x"}},
            "_migrated_to_agents_v2": True,
        }))
        flat = _agent_admin.read_agents_file()
        assert flat == OrderedDict([
            ("a1", {"make": "anthropic", "model": "claude-x"}),
        ])

    def test_read_passes_through_v1_flat(self, isolated_agents_file):
        # Pre-0.10 file shape — flat dict with inner "make".
        isolated_agents_file.write_text(json.dumps({
            "old": {"make": "openai", "model": "gpt-4o"},
        }))
        flat = _agent_admin.read_agents_file()
        assert flat == OrderedDict([
            ("old", {"make": "openai", "model": "gpt-4o"}),
        ])

    def test_write_preserves_order(self, isolated_agents_file):
        data = OrderedDict([
            ("z", {"make": "xai",       "model": None}),
            ("a", {"make": "anthropic", "model": None}),
            ("m", {"make": "openai",    "model": None}),
        ])
        _agent_admin.write_agents_file(data)
        env = _read_envelope(isolated_agents_file)
        assert list(env["agents"].keys()) == ["z", "a", "m"]


# ── migrate_to_agents_v2 — branches ──────────────────────────────────────────

class TestMigrate:
    def test_no_file_no_keys_is_empty(self, isolated_agents_file):
        action, names = _agent_admin.migrate_to_agents_v2()
        assert action == "empty"
        assert names == []
        assert not isolated_agents_file.exists()

    def test_no_file_with_keys_seeds(self, isolated_agents_file, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY",       "x-test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "a-test")
        action, names = _agent_admin.migrate_to_agents_v2()
        assert action == "seeded"
        assert set(names) == {"xai", "anthropic"}
        env = _read_envelope(isolated_agents_file)
        assert env["version"] == 2
        assert env["_migrated_to_agents_v2"] is True
        assert set(env["agents"]) == {"xai", "anthropic"}
        # Each starter agent should reference its provider.
        assert env["agents"]["xai"]["provider"] == "xai"
        assert env["agents"]["anthropic"]["provider"] == "anthropic"

    def test_v1_file_is_upgraded(self, isolated_agents_file):
        isolated_agents_file.write_text(json.dumps({
            "anthropic":      {"make": "anthropic", "model": None},
            "anthropic-opus": {"make": "anthropic", "model": "claude-opus-4-5"},
        }))
        action, names = _agent_admin.migrate_to_agents_v2()
        assert action == "v1_to_v2"
        assert set(names) == {"anthropic", "anthropic-opus"}
        env = _read_envelope(isolated_agents_file)
        assert env["version"] == 2
        assert env["_migrated_to_agents_v2"] is True
        assert env["agents"]["anthropic-opus"] == {
            "provider": "anthropic", "model": "claude-opus-4-5",
        }

    def test_v2_file_is_noop(self, isolated_agents_file):
        isolated_agents_file.write_text(json.dumps({
            "version": 2,
            "agents": {"a": {"provider": "openai", "model": None}},
            "_migrated_to_agents_v2": True,
        }))
        mtime_before = isolated_agents_file.stat().st_mtime_ns
        action, names = _agent_admin.migrate_to_agents_v2()
        assert action == "noop"
        assert names == []
        # File untouched
        assert isolated_agents_file.stat().st_mtime_ns == mtime_before

    def test_idempotent_after_seed(self, isolated_agents_file, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "x-test")
        first_action, _ = _agent_admin.migrate_to_agents_v2()
        assert first_action == "seeded"
        second_action, second_names = _agent_admin.migrate_to_agents_v2()
        assert second_action == "noop"
        assert second_names == []

    def test_idempotent_after_v1_upgrade(self, isolated_agents_file):
        isolated_agents_file.write_text(json.dumps({
            "x": {"make": "xai", "model": "grok-3"},
        }))
        first_action, _ = _agent_admin.migrate_to_agents_v2()
        assert first_action == "v1_to_v2"
        second_action, second_names = _agent_admin.migrate_to_agents_v2()
        assert second_action == "noop"
        assert second_names == []

    def test_mixed_keys_only_seeds_present(self, isolated_agents_file, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "o-test")
        action, names = _agent_admin.migrate_to_agents_v2()
        assert action == "seeded"
        assert names == ["openai"]
        env = _read_envelope(isolated_agents_file)
        assert list(env["agents"].keys()) == ["openai"]


# ── run_agents_v2_migration_with_notice ──────────────────────────────────────

class TestNotice:
    def test_silent_when_empty(self, isolated_agents_file, capsys):
        _agent_admin.run_agents_v2_migration_with_notice()
        out = capsys.readouterr()
        assert out.out == ""
        assert out.err == ""

    def test_silent_when_noop(self, isolated_agents_file, capsys):
        isolated_agents_file.write_text(json.dumps({
            "version": 2,
            "agents": {},
            "_migrated_to_agents_v2": True,
        }))
        _agent_admin.run_agents_v2_migration_with_notice()
        assert capsys.readouterr().out == ""

    def test_prints_seeded_summary(self, isolated_agents_file, monkeypatch, capsys):
        monkeypatch.setenv("XAI_API_KEY", "x-test")
        _agent_admin.run_agents_v2_migration_with_notice()
        out = capsys.readouterr().out
        assert "Created 1 starter agent" in out
        assert "xai" in out

    def test_prints_v1_upgrade_summary(self, isolated_agents_file, capsys):
        isolated_agents_file.write_text(json.dumps({
            "x": {"make": "xai", "model": "grok-3"},
            "y": {"make": "openai", "model": "gpt-4o"},
        }))
        _agent_admin.run_agents_v2_migration_with_notice()
        out = capsys.readouterr().out
        assert "Upgraded" in out and "Agents v2" in out
        assert "2 agents preserved" in out

    def test_swallows_exceptions(self, isolated_agents_file, monkeypatch, capsys):
        def boom():
            raise RuntimeError("kaboom")
        monkeypatch.setattr(_agent_admin, "migrate_to_agents_v2", boom)
        # Must NOT raise
        _agent_admin.run_agents_v2_migration_with_notice()
        out = capsys.readouterr().out
        assert "Could not migrate agents file to v2" in out
        assert "kaboom" in out


# ── mmd_startup wrapper ──────────────────────────────────────────────────────

class TestStartupHook:
    def test_noop_when_already_v2(self, isolated_agents_file, capsys):
        isolated_agents_file.write_text(json.dumps({
            "version": 2,
            "agents": {},
            "_migrated_to_agents_v2": True,
        }))
        mmd_startup._migrate_to_agents_v2_once()
        assert capsys.readouterr().out == ""

    def test_runs_v1_upgrade(self, isolated_agents_file, capsys):
        isolated_agents_file.write_text(json.dumps({
            "x": {"make": "xai", "model": None},
        }))
        mmd_startup._migrate_to_agents_v2_once()
        out = capsys.readouterr().out
        assert "Upgraded" in out
        env = _read_envelope(isolated_agents_file)
        assert env["version"] == 2

    def test_swallows_errors(self, isolated_agents_file, monkeypatch, capsys):
        # Make the underlying helper blow up; the wrapper must absorb it.
        def boom():
            raise RuntimeError("startup boom")
        monkeypatch.setattr(
            _agent_admin, "run_agents_v2_migration_with_notice", boom,
        )
        # Must NOT raise; output is irrelevant here.
        mmd_startup._migrate_to_agents_v2_once()

