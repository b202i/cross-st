"""
tests/test_st_cross_alias_matrix.py — CST-MM-b: agent-aware st-cross matrix.

Coverage:
    * `_get_provider_semaphore(agent, …)` keys on rate-limit group, so two
      agents sharing a make share one semaphore.
    * `_stories_complete(json_path, ai_list)` compares on (make, model)
      pairs — two agents sharing a make produce two needed entries.
    * Resume detection in main() matches fact rows on (make, model) so the
      right column is preloaded when same-make agents are present.
"""
import importlib.util
import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest


# ── Module loader (matches existing test_st_cross.py pattern) ─────────────────

@pytest.fixture
def st_cross_mod():
    path = Path(__file__).parent.parent / "cross_st" / "st-cross.py"
    spec = importlib.util.spec_from_file_location("st_cross_alias", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def _reset_semaphore_registry(st_cross_mod):
    st_cross_mod._provider_semaphores.clear()
    yield
    st_cross_mod._provider_semaphores.clear()


@pytest.fixture
def agent_file(tmp_path, monkeypatch):
    """Inject a ~/.cross_ai_models.json that defines two same-make agents.

    Also seeds the bare ``anthropic`` and ``xai`` self-agents that the
    AGT-2 first-run migration would create on any real install with the
    matching API key set.  Several tests in this module resolve the bare
    make name (``"anthropic"``, ``"xai"``) to verify that agents sharing
    a make share a semaphore — that resolution requires the bare name to
    be defined (cross-ai-core 0.8.0 stopped auto-seeding).
    """
    path = tmp_path / "cross_ai_models.json"
    path.write_text(json.dumps({
        "anthropic":        {"make": "anthropic", "model": None},
        "anthropic-opus":   {"make": "anthropic", "model": "claude-opus-4-5"},
        "anthropic-sonnet": {"make": "anthropic", "model": "claude-sonnet-4-5"},
        "xai":              {"make": "xai",       "model": None},
    }))
    monkeypatch.setenv("CROSS_AI_AGENTS_FILE", str(path))
    from cross_ai_core.agents import reload_agents
    reload_agents()
    yield path
    monkeypatch.delenv("CROSS_AI_AGENTS_FILE", raising=False)
    reload_agents()


# ── Semaphore: agents share rate-limit group ──────────────────────────────────

class TestSemaphoreSharedAcrossAliases:
    def test_two_aliases_same_make_share_semaphore(
            self, st_cross_mod, _reset_semaphore_registry, agent_file):
        sem_opus   = st_cross_mod._get_provider_semaphore(
            "anthropic-opus", None, sequential=False)
        sem_sonnet = st_cross_mod._get_provider_semaphore(
            "anthropic-sonnet", None, sequential=False)
        # Same identity — both agents share the anthropic group.
        assert sem_opus is sem_sonnet

    def test_alias_and_make_share_semaphore(
            self, st_cross_mod, _reset_semaphore_registry, agent_file):
        sem_alias = st_cross_mod._get_provider_semaphore(
            "anthropic-opus", None, sequential=False)
        sem_make  = st_cross_mod._get_provider_semaphore(
            "anthropic", None, sequential=False)
        assert sem_alias is sem_make

    def test_different_makes_get_different_semaphores(
            self, st_cross_mod, _reset_semaphore_registry, agent_file):
        sem_anth = st_cross_mod._get_provider_semaphore(
            "anthropic-opus", None, sequential=False)
        sem_xai  = st_cross_mod._get_provider_semaphore(
            "xai", None, sequential=False)
        assert sem_anth is not sem_xai

    def test_max_override_still_shared_within_group(
            self, st_cross_mod, _reset_semaphore_registry, agent_file):
        sem_a = st_cross_mod._get_provider_semaphore(
            "anthropic-opus", 1, sequential=False)
        sem_b = st_cross_mod._get_provider_semaphore(
            "anthropic-sonnet", 1, sequential=False)
        assert sem_a is sem_b

    def test_unknown_alias_raises(
            self, st_cross_mod, _reset_semaphore_registry):
        # No agent file loaded → unknown agent surfaces ValueError from
        # resolve_agent before semaphore creation.
        with pytest.raises(ValueError, match="Unsupported AI"):
            st_cross_mod._get_provider_semaphore(
                "no-such-agent", None, sequential=False)


# ── _stories_complete: (make, model) parity ────────────────────────────────────

class TestStoriesCompleteWithAliases:
    def test_one_story_per_alias_required(
            self, st_cross_mod, agent_file, tmp_path):
        # File has only one anthropic story → not complete for two agents.
        report = tmp_path / "report.json"
        report.write_text(json.dumps({
            "data": [],
            "story": [
                {"make": "anthropic", "model": "claude-opus-4-5"},
            ],
        }))
        ai_list = ["anthropic-opus", "anthropic-sonnet"]
        assert st_cross_mod._stories_complete(str(report), ai_list) is False

    def test_two_stories_two_aliases_complete(
            self, st_cross_mod, agent_file, tmp_path):
        report = tmp_path / "report.json"
        report.write_text(json.dumps({
            "data": [],
            "story": [
                {"make": "anthropic", "model": "claude-opus-4-5"},
                {"make": "anthropic", "model": "claude-sonnet-4-5"},
            ],
        }))
        ai_list = ["anthropic-opus", "anthropic-sonnet"]
        assert st_cross_mod._stories_complete(str(report), ai_list) is True

    def test_legacy_make_only_alias_satisfied_by_any_model(
            self, st_cross_mod, agent_file, tmp_path):
        # An ai_list entry that resolves to (make, None) — i.e. the bare
        # make agent — should be satisfied by any anthropic story.
        report = tmp_path / "report.json"
        report.write_text(json.dumps({
            "data": [],
            "story": [
                {"make": "anthropic", "model": "claude-3-haiku"},
            ],
        }))
        ai_list = ["anthropic"]   # bare make → model=None
        assert st_cross_mod._stories_complete(str(report), ai_list) is True

    def test_missing_file_returns_false(self, st_cross_mod):
        assert st_cross_mod._stories_complete("/nonexistent/path.json", ["anthropic"]) is False

