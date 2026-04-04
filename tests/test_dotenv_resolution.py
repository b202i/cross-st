"""
tests/test_dotenv_resolution.py — Regression tests for the 3-layer .env load pattern
and the check_api_key() diagnostic helper.

Background
----------
All st-* tools run from arbitrary working directories (e.g. cross-story/shang/).
They must find API keys and DISCOURSE config even when the CWD has no .env.

The canonical load order (A1 convention):
  1. ~/.crossenv          — global user config (pip-installed users)
  2. <repo-root>/.env     — developer keys co-located with the scripts
  3. ./.env               — CWD project-level override (highest priority)

Failure mode caught by this suite:
  Before the fix, st-gen loaded only ~/.crossenv and ./.env (CWD).
  Running from cross-story/shang/ found no API keys → silent auth crash
  → st-bang hung for 10 minutes waiting for block files never removed.

Coverage
--------
  Layer resolution        — each of the three layers is tried in order
  Layer priority          — lower-priority layer does not clobber higher one
  CWD override            — layer 3 wins over layers 1 & 2 when present
  Missing key diagnostic  — check_api_key() prints path list, returns False
  Known-key pass          — check_api_key() returns True silently when key set
  Unknown provider        — check_api_key() always returns True (safe pass-through)
  DISCOURSE discovery     — DISCOURSE key is found from repo-local .env
  Every provider mapped   — every entry in AI_LIST has an _API_KEY_ENV_VARS entry
"""

import importlib.util
import os
from pathlib import Path

import pytest

# ── Load ai_handler as a module ───────────────────────────────────────────────

_REPO = Path(__file__).parent.parent   # cross/ repo root

_spec = importlib.util.spec_from_file_location("ai_handler", _REPO / "cross_st" / "ai_handler.py")
ai_handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ai_handler)

check_api_key     = ai_handler.check_api_key
_API_KEY_ENV_VARS = ai_handler._API_KEY_ENV_VARS
get_ai_list       = ai_handler.get_ai_list


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def clean_env(monkeypatch):
    """Remove all known AI API key env vars and DISCOURSE for the test."""
    for var in _API_KEY_ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("DISCOURSE", raising=False)
    yield


@pytest.fixture()
def tmp_dotenv(tmp_path):
    """
    Factory: write a .env-style file and return its Path.
    Usage: env_file = tmp_dotenv("label", KEY="value", KEY2="value2")
    """
    def _make(name: str, **kv) -> Path:
        p = tmp_path / f"{name}.env"
        p.write_text("\n".join(f"{k}={v}" for k, v in kv.items()) + "\n")
        return p
    return _make


def _apply_3layer(crossenv_path, repo_env_path, cwd_env_path, monkeypatch):
    """
    Apply the canonical 3-layer dotenv load used by every st-*.py script.
    Wipes known API key vars first so each test starts clean.
    """
    from dotenv import load_dotenv as _ld
    for var in _API_KEY_ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("DISCOURSE", raising=False)

    _ld(str(crossenv_path))
    _ld(str(repo_env_path))
    if cwd_env_path and os.path.isfile(str(cwd_env_path)):
        _ld(str(cwd_env_path), override=True)
    return dict(os.environ)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. check_api_key — diagnostic helper
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckApiKey:

    def test_returns_true_when_key_present(self, monkeypatch):
        """check_api_key returns True silently when the env var is set."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        assert check_api_key("xai") is True

    def test_returns_false_when_key_missing(self, clean_env, capsys):
        """check_api_key returns False and prints a diagnostic when key absent."""
        result = check_api_key("xai", paths_checked=["/a/.crossenv", "/b/.env", "/c/.env"])
        assert result is False
        out = capsys.readouterr().out
        assert "XAI_API_KEY" in out
        assert "xai" in out

    def test_diagnostic_lists_all_three_paths(self, clean_env, capsys):
        """The diagnostic output includes every path that was searched."""
        paths = ["/home/user/.crossenv", "/repo/cross/.env", "/story/shang/.env"]
        check_api_key("anthropic", paths_checked=paths)
        out = capsys.readouterr().out
        for p in paths:
            assert p in out, f"Expected path {p!r} in diagnostic output"

    def test_diagnostic_marks_existing_files(self, clean_env, tmp_path, capsys):
        """Existing files are marked ✓ exists; absent files are marked ✗ not found."""
        existing = tmp_path / "real.env"
        existing.write_text("DUMMY=1\n")
        missing = tmp_path / "ghost.env"

        check_api_key("openai", paths_checked=[str(existing), str(missing)])
        out = capsys.readouterr().out
        assert "✓ exists" in out
        assert "✗ not found" in out

    def test_unknown_provider_returns_true(self, clean_env):
        """Unknown AI make passes through without printing anything."""
        assert check_api_key("unknown_ai_xyz") is True

    def test_default_paths_shown_when_not_supplied(self, clean_env, capsys):
        """When paths_checked is omitted the canonical default paths appear."""
        check_api_key("gemini")
        out = capsys.readouterr().out
        assert ".crossenv" in out or ".env" in out

    @pytest.mark.parametrize("make", get_ai_list())
    def test_every_provider_has_key_var(self, make):
        """Every provider in AI_LIST must have an entry in _API_KEY_ENV_VARS."""
        assert make in _API_KEY_ENV_VARS, (
            f"Provider '{make}' is in AI_LIST but missing from _API_KEY_ENV_VARS. "
            f"Add  '{make}': '<ENV_VAR_NAME>'  to ai_handler._API_KEY_ENV_VARS."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 3-layer dotenv resolution
# ═══════════════════════════════════════════════════════════════════════════════

class TestDotenvResolution:
    """
    Verify the load order:
      layer 1 — ~/.crossenv       (loaded first, no override)
      layer 2 — <repo>/.env       (loaded second, no override → layer 1 wins ties)
      layer 3 — CWD/.env          (loaded with override=True → wins all ties)
    """

    def test_layer1_crossenv_loaded(self, tmp_dotenv, monkeypatch):
        """Key present only in ~/.crossenv-equivalent is found."""
        crossenv = tmp_dotenv("crossenv", XAI_API_KEY="key-from-crossenv")
        repo_env = tmp_dotenv("repo")
        env = _apply_3layer(crossenv, repo_env, None, monkeypatch)
        assert env.get("XAI_API_KEY") == "key-from-crossenv"

    def test_layer2_repo_env_loaded(self, tmp_dotenv, monkeypatch):
        """Key present only in the repo-local .env is found."""
        crossenv = tmp_dotenv("crossenv")
        repo_env = tmp_dotenv("repo", ANTHROPIC_API_KEY="key-from-repo")
        env = _apply_3layer(crossenv, repo_env, None, monkeypatch)
        assert env.get("ANTHROPIC_API_KEY") == "key-from-repo"

    def test_layer3_cwd_env_overrides(self, tmp_dotenv, monkeypatch):
        """CWD .env (override=True) wins over layers 1 and 2."""
        crossenv = tmp_dotenv("crossenv", OPENAI_API_KEY="key-from-crossenv")
        repo_env = tmp_dotenv("repo",     OPENAI_API_KEY="key-from-repo")
        cwd_env  = tmp_dotenv("cwd",      OPENAI_API_KEY="key-from-cwd")
        env = _apply_3layer(crossenv, repo_env, cwd_env, monkeypatch)
        assert env.get("OPENAI_API_KEY") == "key-from-cwd"

    def test_layer2_does_not_override_layer1(self, tmp_dotenv, monkeypatch):
        """Repo-local .env does NOT overwrite a key already set by ~/.crossenv."""
        crossenv = tmp_dotenv("crossenv", GEMINI_API_KEY="key-from-crossenv")
        repo_env = tmp_dotenv("repo",     GEMINI_API_KEY="key-from-repo")
        env = _apply_3layer(crossenv, repo_env, None, monkeypatch)
        assert env.get("GEMINI_API_KEY") == "key-from-crossenv"

    def test_missing_cwd_env_does_not_fail(self, tmp_dotenv, monkeypatch):
        """
        Running from a directory with no .env still works.
        This is the exact failure mode from the bug: running st-bang from
        cross-story/shang/ where there is no .env file.
        """
        crossenv = tmp_dotenv("crossenv", XAI_API_KEY="key-from-crossenv")
        repo_env = tmp_dotenv("repo")
        env = _apply_3layer(crossenv, repo_env, "/nonexistent/path/.env", monkeypatch)
        assert env.get("XAI_API_KEY") == "key-from-crossenv"

    def test_discourse_found_from_repo_env(self, tmp_dotenv, monkeypatch):
        """DISCOURSE key is found from the repo-local .env (its canonical home)."""
        discourse_json = '{"sites":[{"slug":"Test","url":"https://example.com"}]}'
        crossenv = tmp_dotenv("crossenv")
        repo_env = tmp_dotenv("repo", DISCOURSE=discourse_json)
        env = _apply_3layer(crossenv, repo_env, None, monkeypatch)
        assert env.get("DISCOURSE") == discourse_json

    def test_all_five_provider_keys_via_layer2(self, tmp_dotenv, monkeypatch):
        """All five provider API keys can be loaded from the repo-local .env."""
        kv = {var: f"dummy-{i}" for i, var in enumerate(_API_KEY_ENV_VARS.values())}
        crossenv = tmp_dotenv("crossenv")
        repo_env = tmp_dotenv("repo", **kv)
        env = _apply_3layer(crossenv, repo_env, None, monkeypatch)
        for var, expected in kv.items():
            assert env.get(var) == expected, f"{var} not found via layer 2"

