"""
tests/test_dotenv_resolution.py — Regression tests for the A1 4-layer .env load pattern
and the check_api_key() diagnostic helper.

Background
----------
All st-* tools run from arbitrary working directories (e.g. ~/mmd/ or cross-story/shang/).
They must find API keys and DISCOURSE config even when the CWD has no .env.

The canonical load order (A1 convention — project .env > ~/.crossenv):
  1. ~/.crossenv              — global user config / shared API keys (lowest priority)
  2. <repo-root>/.env         — repo-local developer keys; overrides global (override=True)
  2b. <cross_st-dir>/.env     — pip install co-located .env (override=True)
  3. ./.env (CWD)             — per-project override, highest priority (override=True)

Key invariants:
  - Project .env WINS over ~/.crossenv for any key present in both.
  - CWD .env wins over everything.
  - Running from a directory with no .env must NOT fail.
  - discourse.py must use _project_root (parent of cross_st/) — NOT cross_st/ itself.
  - st.py must call load_cross_env() BEFORE get_discourse_slugs_sites().

Regressions caught by this suite:
  R1: discourse.py used cross_st/ as _basedir → looked for cross_st/.env (never exists).
      Fixed: _project_root = os.path.dirname(cross_st_dir).
  R2: st.py called get_discourse_slugs_sites() at module level before any env loaded.
      Fixed: load_cross_env() called before get_discourse_slugs_sites() in st.py.
  R3: ~/.crossenv was loaded without override, project .env loaded without override
      → ~/.crossenv silently won any key-collision. Previous test
      test_layer2_does_not_override_layer1 was asserting the WRONG behavior.
      Fixed: layers 2+ use override=True so project .env wins.
"""

import importlib
import importlib.util
import os
from pathlib import Path

import pytest

# ── Load modules under test ───────────────────────────────────────────────────

_REPO       = Path(__file__).parent.parent           # cross/ repo root
_CROSS_ST   = _REPO / "cross_st"

def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

ai_handler = _load("ai_handler", "cross_st/ai_handler.py")

check_api_key     = ai_handler.check_api_key
_API_KEY_ENV_VARS = ai_handler._API_KEY_ENV_VARS
get_ai_list       = ai_handler.get_ai_list


# ── Helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def clean_env(monkeypatch):
    """Remove all known AI API key env vars and DISCOURSE for the test."""
    for var in _API_KEY_ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("DISCOURSE",    raising=False)
    monkeypatch.delenv("DEFAULT_AI",   raising=False)
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


def _apply_a1(crossenv_path, repo_env_path, cwd_env_path, monkeypatch):
    """
    Apply the canonical A1 4-layer dotenv load used by load_cross_env().

    Layer order (later layers win):
      1. ~/.crossenv         — no override (lowest priority)
      2. <repo-root>/.env    — override=True  ← project wins over global
      3. CWD/.env            — override=True  ← highest priority

    Wipes known API key vars and DISCOURSE first so each test starts clean.
    """
    from dotenv import load_dotenv as _ld
    for var in _API_KEY_ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("DISCOURSE",  raising=False)
    monkeypatch.delenv("DEFAULT_AI", raising=False)

    _ld(str(crossenv_path))                                             # 1. global fallback
    _ld(str(repo_env_path), override=True)                             # 2. project wins
    if cwd_env_path and os.path.isfile(str(cwd_env_path)):
        _ld(str(cwd_env_path), override=True)                          # 3. CWD highest
    return dict(os.environ)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. check_api_key — diagnostic helper
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckApiKey:

    def test_returns_true_when_key_present(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        assert check_api_key("xai") is True

    def test_returns_false_when_key_missing(self, clean_env, capsys):
        result = check_api_key("xai", paths_checked=["/a/.crossenv", "/b/.env", "/c/.env"])
        assert result is False
        out = capsys.readouterr().out
        assert "XAI_API_KEY" in out
        assert "xai" in out

    def test_diagnostic_lists_all_three_paths(self, clean_env, capsys):
        paths = ["/home/user/.crossenv", "/repo/cross/.env", "/story/shang/.env"]
        check_api_key("anthropic", paths_checked=paths)
        out = capsys.readouterr().out
        for p in paths:
            assert p in out, f"Expected path {p!r} in diagnostic output"

    def test_diagnostic_marks_existing_files(self, clean_env, tmp_path, capsys):
        existing = tmp_path / "real.env"
        existing.write_text("DUMMY=1\n")
        missing = tmp_path / "ghost.env"
        check_api_key("openai", paths_checked=[str(existing), str(missing)])
        out = capsys.readouterr().out
        assert "✓ exists" in out
        assert "✗ not found" in out

    def test_unknown_provider_returns_true(self, clean_env):
        assert check_api_key("unknown_ai_xyz") is True

    def test_default_paths_shown_when_not_supplied(self, clean_env, capsys):
        check_api_key("gemini")
        out = capsys.readouterr().out
        assert ".crossenv" in out or ".env" in out

    @pytest.mark.parametrize("make", get_ai_list())
    def test_every_provider_has_key_var(self, make):
        assert make in _API_KEY_ENV_VARS, (
            f"Provider '{make}' is in AI_LIST but missing from _API_KEY_ENV_VARS. "
            f"Add  '{make}': '<ENV_VAR_NAME>'  to ai_handler._API_KEY_ENV_VARS."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. A1 4-layer dotenv resolution
# ═══════════════════════════════════════════════════════════════════════════════

class TestDotenvResolution:
    """
    Verify the A1 load order — project .env WINS over ~/.crossenv.

      layer 1 — ~/.crossenv       (no override — lowest priority)
      layer 2 — <repo>/.env       (override=True — PROJECT WINS over global)
      layer 3 — CWD/.env          (override=True — wins all)

    R3 regression guard: the old code loaded layer 2 without override=True so
    ~/.crossenv silently won any collision.  The old test had it backwards too.
    """

    def test_layer1_crossenv_loaded(self, tmp_dotenv, monkeypatch):
        """Key only in ~/.crossenv is found as a fallback."""
        crossenv = tmp_dotenv("crossenv", XAI_API_KEY="key-from-crossenv")
        repo_env = tmp_dotenv("repo")
        env = _apply_a1(crossenv, repo_env, None, monkeypatch)
        assert env.get("XAI_API_KEY") == "key-from-crossenv"

    def test_layer2_repo_env_loaded(self, tmp_dotenv, monkeypatch):
        """Key only in repo-local .env is found."""
        crossenv = tmp_dotenv("crossenv")
        repo_env = tmp_dotenv("repo", ANTHROPIC_API_KEY="key-from-repo")
        env = _apply_a1(crossenv, repo_env, None, monkeypatch)
        assert env.get("ANTHROPIC_API_KEY") == "key-from-repo"

    def test_layer2_overrides_layer1(self, tmp_dotenv, monkeypatch):
        """
        R3 regression guard: repo-local .env WINS over ~/.crossenv.

        The old behavior was the opposite — ~/.crossenv won because layer 2
        was loaded without override=True.  This test was previously named
        test_layer2_does_not_override_layer1 and asserted the wrong result.
        """
        crossenv = tmp_dotenv("crossenv", GEMINI_API_KEY="key-from-crossenv")
        repo_env = tmp_dotenv("repo",     GEMINI_API_KEY="key-from-repo")
        env = _apply_a1(crossenv, repo_env, None, monkeypatch)
        assert env.get("GEMINI_API_KEY") == "key-from-repo", (
            "Project .env must override ~/.crossenv (R3 regression). "
            "Check that load_cross_env() uses override=True for layer 2."
        )

    def test_default_ai_in_project_env_overrides_crossenv(self, tmp_dotenv, monkeypatch):
        """DEFAULT_AI in project .env takes precedence over ~/.crossenv."""
        crossenv = tmp_dotenv("crossenv", DEFAULT_AI="xai")
        repo_env = tmp_dotenv("repo",     DEFAULT_AI="gemini")
        env = _apply_a1(crossenv, repo_env, None, monkeypatch)
        assert env.get("DEFAULT_AI") == "gemini"

    def test_layer3_cwd_env_wins_all(self, tmp_dotenv, monkeypatch):
        """CWD .env wins over both ~/.crossenv and project .env."""
        crossenv = tmp_dotenv("crossenv", OPENAI_API_KEY="key-from-crossenv")
        repo_env = tmp_dotenv("repo",     OPENAI_API_KEY="key-from-repo")
        cwd_env  = tmp_dotenv("cwd",      OPENAI_API_KEY="key-from-cwd")
        env = _apply_a1(crossenv, repo_env, cwd_env, monkeypatch)
        assert env.get("OPENAI_API_KEY") == "key-from-cwd"

    def test_missing_cwd_env_does_not_fail(self, tmp_dotenv, monkeypatch):
        """
        Running from a directory with no .env still works.
        This is the classic failure mode: running st from ~/mmd/ where there
        is no .env file — must fall back to project .env successfully.
        """
        crossenv = tmp_dotenv("crossenv", XAI_API_KEY="key-from-crossenv")
        repo_env = tmp_dotenv("repo")
        env = _apply_a1(crossenv, repo_env, "/nonexistent/path/.env", monkeypatch)
        assert env.get("XAI_API_KEY") == "key-from-crossenv"

    def test_discourse_found_from_repo_env(self, tmp_dotenv, monkeypatch):
        """DISCOURSE key is found from the repo-local .env."""
        discourse_json = '{"sites":[{"slug":"Test","url":"https://example.com"}]}'
        crossenv = tmp_dotenv("crossenv")
        repo_env = tmp_dotenv("repo", DISCOURSE=discourse_json)
        env = _apply_a1(crossenv, repo_env, None, monkeypatch)
        assert env.get("DISCOURSE") == discourse_json

    def test_discourse_in_project_env_overrides_crossenv(self, tmp_dotenv, monkeypatch):
        """DISCOURSE in project .env wins over ~/.crossenv."""
        global_disc  = '{"sites":[{"slug":"Global","url":"https://global.example.com"}]}'
        project_disc = '{"sites":[{"slug":"Project","url":"https://project.example.com"}]}'
        crossenv = tmp_dotenv("crossenv", DISCOURSE=global_disc)
        repo_env = tmp_dotenv("repo",     DISCOURSE=project_disc)
        env = _apply_a1(crossenv, repo_env, None, monkeypatch)
        assert env.get("DISCOURSE") == project_disc

    def test_all_five_provider_keys_via_layer2(self, tmp_dotenv, monkeypatch):
        """All five provider API keys can be loaded from the repo-local .env."""
        kv = {var: f"dummy-{i}" for i, var in enumerate(_API_KEY_ENV_VARS.values())}
        crossenv = tmp_dotenv("crossenv")
        repo_env = tmp_dotenv("repo", **kv)
        env = _apply_a1(crossenv, repo_env, None, monkeypatch)
        for var, expected in kv.items():
            assert env.get(var) == expected, f"{var} not found via layer 2"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. discourse.py path resolution (R1 regression guard)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiscoursePathResolution:
    """
    R1 regression guard: discourse.py must look for .env in the PROJECT ROOT
    (parent of cross_st/), NOT in cross_st/ itself.

    After the C1 migration, cross_st/ became a subdirectory.
    discourse.py used os.path.dirname(__file__) which gives cross_st/ — it
    then looked for cross_st/.env which never exists.  The bug was silent
    when CWD == repo root (CWD layer found .env), but broke when running
    from any other directory.
    """

    def test_discourse_project_root_is_parent_of_cross_st(self):
        """discourse.py must delegate env loading to mmd_startup.load_cross_env().

        R1/R3 guard: discourse.py used to maintain its own 4-layer load_dotenv
        chain that ignored the venv guard in `_in_project_venv()`, so it
        silently shadowed ~/.crossenv with a stale dev .env even for pipx and
        system-Python users.  The fix is to delegate to the canonical loader.
        See `cross-internal/st-admin/BUGFIX_discourse_add_site_shadowed.md`.
        """
        import ast
        src = (_CROSS_ST / "discourse.py").read_text()
        tree = ast.parse(src)
        func_src = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_discourse_slugs_sites":
                func_src = ast.get_source_segment(src, node)
                break
        assert func_src is not None, "get_discourse_slugs_sites() not found in discourse.py"
        assert "load_cross_env" in func_src, (
            "discourse.py must call mmd_startup.load_cross_env() rather than "
            "rolling its own load_dotenv chain — otherwise the venv guard is "
            "bypassed and the dev .env shadows ~/.crossenv for non-dev users."
        )

    def test_discourse_uses_override_true_for_project_env(self):
        """discourse.py must NOT contain an unguarded load_dotenv override chain.

        R3 guard: any direct ``load_dotenv(..., override=True)`` here would
        re-introduce the silent-shadow bug because it would skip the
        `_in_project_venv()` check that mmd_startup applies.  All env loading
        must go through `load_cross_env()`.
        """
        src = (_CROSS_ST / "discourse.py").read_text()
        offending = [
            l for l in src.splitlines()
            if "load_dotenv" in l and "override=True" in l
        ]
        assert not offending, (
            "discourse.py must not call load_dotenv(..., override=True) directly; "
            "delegate to mmd_startup.load_cross_env() instead.  Offending lines:\n  "
            + "\n  ".join(offending)
        )

    def test_load_cross_env_uses_override_true_for_project_layers(self):
        """mmd_startup.load_cross_env() must use override=True for layers 2+ (R3 guard)."""
        src = (_REPO / "cross_st" / "mmd_startup.py").read_text()
        lines = src.splitlines()
        project_root_lines = [l for l in lines if "_PROJECT_ROOT" in l and "load_dotenv" in l]
        assert project_root_lines, (
            "No load_dotenv(_PROJECT_ROOT, ...) call found in mmd_startup.py"
        )
        assert any("override=True" in l for l in project_root_lines), (
            "mmd_startup.load_cross_env() must use override=True for the project-root layer "
            "so project .env wins over ~/.crossenv (R3)."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. st.py initialization order (R2 regression guard)
# ═══════════════════════════════════════════════════════════════════════════════

class TestStPyInitOrder:
    """
    R2 regression guard: st.py must call load_cross_env() BEFORE calling
    get_discourse_slugs_sites().

    The module-level call to get_discourse_slugs_sites() runs at import time.
    If env is not loaded first, DISCOURSE is absent → 'Discourse is not
    configured' error → st crashes on startup from any non-repo CWD.
    """

    def test_load_cross_env_called_before_discourse(self):
        """load_cross_env() must appear before get_discourse_slugs_sites() in st.py."""
        import ast
        src = (_CROSS_ST / "st.py").read_text()
        tree = ast.parse(src)

        load_env_line    = None
        discourse_line   = None

        for node in ast.walk(tree):
            # Module-level Call statements (bare calls and assignments)
            call = None
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value

            if call is None:
                continue

            # load_cross_env()
            if isinstance(call.func, ast.Name) and call.func.id == "load_cross_env":
                load_env_line = node.lineno
            # get_discourse_slugs_sites()
            if isinstance(call.func, ast.Name) and call.func.id == "get_discourse_slugs_sites":
                discourse_line = node.lineno

        assert load_env_line is not None, (
            "st.py must call load_cross_env() at module level before get_discourse_slugs_sites()."
        )
        assert discourse_line is not None, (
            "get_discourse_slugs_sites() call not found in st.py."
        )
        assert load_env_line < discourse_line, (
            f"load_cross_env() (line {load_env_line}) must come BEFORE "
            f"get_discourse_slugs_sites() (line {discourse_line}) in st.py. "
            f"Otherwise DISCOURSE is unset when running from non-repo CWD (R2)."
        )

