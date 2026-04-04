"""
mmd_startup.py — First-run detection helper for Cross st-* entry points.

Call require_config() near the top of every st-*.py main(), before any API
call.  It checks whether the user has a Cross config file in place and exits
with a friendly message if not, guiding new users toward st-admin --setup.

Call load_cross_env() immediately after require_config() (or once near the top
of module-level scripts) to load the A1 three-layer environment in the correct
order, resolving paths relative to the project root rather than the cross_st/
subdirectory.
"""
import os
import sys

# ── Path constants ─────────────────────────────────────────────────────────────
# _CROSS_ST_DIR  — absolute path to the cross_st/ package directory
#                  (where mmd_startup.py and all st-*.py live)
# _PROJECT_ROOT  — parent of cross_st/; the repo root for dev installs,
#                  site-packages/ for pip installs (no .env there — no-op).
_CROSS_ST_DIR = os.path.dirname(os.path.realpath(__file__))
_CROSS_AI_DIR = _CROSS_ST_DIR  # legacy alias — do not use in new code
_PROJECT_ROOT = os.path.dirname(_CROSS_ST_DIR)


def require_config() -> None:
    """Exit with a friendly message if no Cross config is found.

    Checks the same three locations as the A1 load order:
      1. ~/.crossenv          — global config created by st-admin --setup
      2. <project-root>/.env  — repo-local developer keys (cross/.env)
      2b. <cross_st-dir>/.env — co-located keys (future layout / pip installs)
      3. ./.env               — CWD project-level override

    Running from an arbitrary directory (e.g. cross-story/shang/) will still
    succeed as long as the repo-local .env exists (layer 2).
    """
    crossenv   = os.path.expanduser("~/.crossenv")
    repo_env   = os.path.join(_PROJECT_ROOT, ".env")   # cross/.env  (dev layout)
    local_env2 = os.path.join(_CROSS_ST_DIR, ".env")   # cross_st/.env  (future)
    local_env  = os.path.join(os.getcwd(), ".env")
    if not any(os.path.exists(p) for p in (crossenv, repo_env, local_env2, local_env)):
        print(
            "\n  Cross is not configured.\n"
            "  Run 'st-admin --setup' to get started, or create ~/.crossenv with your API keys.\n"
            "  See: https://github.com/b202i/cross/blob/main/docs/wiki/Onboarding.md\n"
        )
        sys.exit(1)


def load_cross_env() -> None:
    """Load Cross environment files in A1 three-layer order.

    Resolves layer 2 relative to the project root (cross/.env) so that the
    correct .env is found whether scripts run via an entry-point wrapper,
    via runpy.run_path(), or directly as ``python cross_st/st-*.py``.

    Layer order (first writer of each key wins; CWD overrides all):
      1. ~/.crossenv                — global config / API keys
      2. <project-root>/.env        — repo-local developer keys (cross/.env)
      2b. <cross_st-dir>/.env       — co-located .env (future / pip layout)
      3. <CWD>/.env  override=True  — per-project override, highest priority
    """
    from dotenv import load_dotenv
    crossenv = os.path.expanduser("~/.crossenv")
    load_dotenv(crossenv)                                          # 1. global
    load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))               # 2. repo root
    load_dotenv(os.path.join(_CROSS_ST_DIR, ".env"))               # 2b. cross_st/
    load_dotenv(os.path.join(os.getcwd(), ".env"), override=True)  # 3. CWD

