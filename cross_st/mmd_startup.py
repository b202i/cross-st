"""
mmd_startup.py — First-run detection helper for Cross st-* entry points.

Call require_config() near the top of every st-*.py main(), before any API
call.  It checks whether the user has a Cross config file in place and exits
with a friendly message if not, guiding new users toward st-admin --setup.

Call load_cross_env() immediately after require_config() (or once near the top
of module-level scripts) to load the A1 three-layer environment in the correct
order, resolving paths relative to the project root rather than the cross_st/
subdirectory.

Update notifications:
  load_cross_env() calls check_for_updates() automatically.  A background
  thread checks PyPI at most once every 24 hours and caches the result in
  ~/.cross_api_cache/update_check.json.  On the next run, if a newer version
  is available, a single line is printed to stderr before command output.
  Suppressed when stdout is not a TTY (pipes, CI, scripts).
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
            "  See: https://github.com/b202i/cross-st/blob/main/docs/wiki/Onboarding.md\n"
        )
        sys.exit(1)


_UPDATE_CACHE_PATH     = os.path.join(os.path.expanduser("~/.cross_api_cache"),
                                      "update_check.json")
_UPDATE_CHECK_INTERVAL = 86_400   # seconds — re-check PyPI at most once per day


def _read_update_cache() -> dict:
    try:
        import json
        with open(_UPDATE_CACHE_PATH) as _f:
            return json.load(_f)
    except Exception:
        return {}


def _write_update_cache(data: dict) -> None:
    try:
        import json
        os.makedirs(os.path.dirname(_UPDATE_CACHE_PATH), exist_ok=True)
        with open(_UPDATE_CACHE_PATH, "w") as _f:
            json.dump(data, _f)
    except Exception:
        pass


def _fetch_latest_pypi_version() -> "str | None":
    """Return the latest cross-st version string from PyPI, or None on error."""
    try:
        import json
        import urllib.request
        url = "https://pypi.org/pypi/cross-st/json"
        with urllib.request.urlopen(url, timeout=4) as _resp:
            return json.loads(_resp.read().decode())["info"]["version"]
    except Exception:
        return None


def _bg_update_check(current_ver: str) -> None:
    """Background thread: fetch PyPI version and persist to cache."""
    import time
    latest = _fetch_latest_pypi_version()
    _write_update_cache({
        "last_check":      time.time(),
        "latest_version":  latest or "",
        "current_version": current_ver,
    })


def check_for_updates() -> None:
    """Show a one-line update notice if a newer cross-st is on PyPI.

    Behaviour:
    - Reads the cached check result from ~/.cross_api_cache/update_check.json.
    - If the cache is older than 24 h, fires a *daemon* background thread to
      refresh it — zero latency impact on the current command.
    - If the cached latest version is newer than what is installed, prints one
      line to stderr (so it never pollutes piped stdout).
    - Entirely suppressed when sys.stdout is not a TTY (pipes, CI, scripts).
    - Silently no-ops on any error (network, missing package metadata, etc.).
    """
    import threading
    import time

    # Only notify in interactive terminals
    if not sys.stdout.isatty():
        return

    # Resolve installed version
    try:
        from importlib.metadata import version as _pkg_version
        current_ver = _pkg_version("cross-st")
    except Exception:
        return

    cache     = _read_update_cache()
    last_check = cache.get("last_check", 0.0)

    # Kick off a background refresh if the cache is stale
    if time.time() - last_check > _UPDATE_CHECK_INTERVAL:
        t = threading.Thread(
            target=_bg_update_check, args=(current_ver,), daemon=True
        )
        t.start()

    # Notify from previously cached data (background fetch updates *next* run)
    latest_ver = cache.get("latest_version", "")
    if not latest_ver:
        return

    try:
        from packaging.version import Version
        needs_update = Version(latest_ver) > Version(current_ver)
    except Exception:
        needs_update = latest_ver != current_ver

    if needs_update:
        print(
            f"\n  💡 cross-st {latest_ver} is available  "
            f"(installed: {current_ver})  →  st-admin --upgrade\n",
            file=sys.stderr,
        )


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
    check_for_updates()
