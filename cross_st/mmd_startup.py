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
    # Only count the dev-repo .env files when actually running inside the project
    # venv — avoids false-positive "configured" result for pipx users whose
    # editable install makes _PROJECT_ROOT point at the source tree.
    dev_envs   = (repo_env, local_env2) if _in_project_venv() else ()
    if not any(os.path.exists(p) for p in (crossenv, *dev_envs, local_env)):
        print(
            "\n  Cross is not configured.\n"
            "  Run 'st-admin --setup' to get started, or create ~/.crossenv with your API keys.\n"
            "  See: https://github.com/b202i/cross-st/blob/main/docs/wiki/Onboarding.md\n"
        )
        sys.exit(1)


_UPDATE_CACHE_PATH     = os.path.join(os.path.expanduser("~/.cross_api_cache"),
                                      "update_check.json")
_SHADOW_CACHE_PATH     = os.path.join(os.path.expanduser("~/.cross_api_cache"),
                                      "shadow_check.json")
_UPDATE_CHECK_INTERVAL  = 86_400   # seconds — re-check PyPI at most once per day
_UPDATE_NOTIFY_INTERVAL =  4 * 3600  # seconds — nag at most once every 4 hours
_SHADOW_NOTIFY_INTERVAL = 86_400   # seconds — shadow warning at most once per day


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


def _running_from_dev_checkout() -> bool:
    """Return True when the *executing script* lives inside _PROJECT_ROOT.

    Distinct from _in_project_venv(): a developer can be running the project
    source through any Python interpreter (system, brew, an old pip install
    that registered 0.2.0 in its metadata) — in that case `_pkg_version()`
    returns the stale installed version, but the code actually executing is
    the fresh checkout. Detect that via sys.argv[0] / __main__.__file__ and
    suppress the upgrade nag so we don't tell the user "you're on 0.2.0" when
    they're patently not.

    Returns False on any error.
    """
    project_prefix = os.path.abspath(_PROJECT_ROOT) + os.sep
    candidates = []
    try:
        if sys.argv and sys.argv[0]:
            candidates.append(os.path.abspath(sys.argv[0]))
    except Exception:
        pass
    try:
        import __main__  # type: ignore
        if hasattr(__main__, "__file__") and __main__.__file__:
            candidates.append(os.path.abspath(__main__.__file__))
    except Exception:
        pass
    return any(c.startswith(project_prefix) for c in candidates)


def check_for_updates() -> None:
    """Show a one-line update notice if a newer cross-st is on PyPI.

    Behaviour:
    - Reads the cached check result from ~/.cross_api_cache/update_check.json.
    - If the cache is older than 24 h, fires a *daemon* background thread to
      refresh it — zero latency impact on the current command.
    - If the cached latest version is newer than what is installed, prints one
      line to stderr at most once every 4 hours (``last_notified`` in cache).
    - Entirely suppressed when sys.stdout is not a TTY (pipes, CI, scripts).
    - Silently no-ops on any error (network, missing package metadata, etc.).
    """
    import threading
    import time

    # Only notify in interactive terminals
    if not sys.stdout.isatty():
        return

    # Skip the nag for developers running the checkout source directly — the
    # installed-package metadata is often a stale pre-existing pip install
    # that does not reflect what's actually executing.  Dev users manage
    # their own version via `git pull` + `pip install -e .`.
    if _in_project_venv() or _running_from_dev_checkout():
        return

    # Resolve installed version
    try:
        from importlib.metadata import version as _pkg_version
        current_ver = _pkg_version("cross-st")
    except Exception:
        return

    cache      = _read_update_cache()
    last_check = cache.get("last_check", 0.0)

    # Kick off a background refresh if the check cache is stale
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

    if not needs_update:
        return

    # Rate-limit the nag: at most once every _UPDATE_NOTIFY_INTERVAL seconds
    last_notified = cache.get("last_notified", 0.0)
    now = time.time()
    if now - last_notified < _UPDATE_NOTIFY_INTERVAL:
        return

    print(
        f"\n  💡 cross-st {latest_ver} is available  "
        f"(installed: {current_ver})  →  st-admin --upgrade\n",
        file=sys.stderr,
    )

    # Record that we just notified so we don't repeat for another 4 hours
    cache["last_notified"] = now
    _write_update_cache(cache)


def check_shadowed_install() -> None:
    """Warn once per day if a different cross-st install shadows the active one.

    The classic symptom: a user runs ``pipx upgrade cross-st`` which upgrades
    ~/.local/pipx/venvs/cross-st, but ``st-admin --version`` still reports the
    old version because a raw ``pip install cross-st`` into Homebrew Python (or
    any other Python on $PATH) wrote entry-point scripts that appear *earlier* in
    $PATH (e.g. /opt/homebrew/bin/st-admin) and shadow the pipx copy.

    Detection: resolve which('st-admin') and compare its Python shebang (or its
    real-path prefix) to sys.executable.  If they point at different Python
    installs, print a clear warning.

    Entirely silent on any error (shutil unavailable, no TTY, etc.).
    Rate-limited to one warning per 24 hours via ~/.cross_api_cache/shadow_check.json.
    """
    import time

    if not sys.stdout.isatty():
        return

    try:
        import shutil
        which_result = shutil.which("st-admin")
        if not which_result:
            return

        # Resolve both paths to their real locations for comparison
        which_real = os.path.realpath(which_result)
        self_real  = os.path.realpath(sys.executable)

        # Determine the Python-install prefix each belongs to
        # (e.g. /opt/homebrew/opt/python@3.11 vs /Users/Matt/.local/pipx/...)
        def _prefix(p: str) -> str:
            # Walk up from the binary to find the common install root.
            # For /opt/homebrew/bin/python3.11 → /opt/homebrew
            # For /Users/Matt/.local/pipx/venvs/cross-st/bin/python → .../cross-st
            # We just need "are they the same tree?" so compare up 2 levels.
            return os.path.dirname(os.path.dirname(p))

        which_prefix = _prefix(which_real)
        self_prefix  = _prefix(self_real)

        if which_prefix == self_prefix:
            return  # same install — all good

        # Check if the shadowing script actually uses a different Python by reading
        # its shebang line (pipx wrappers and pip scripts both have one).
        try:
            with open(which_result, "rb") as _f:
                first_line = _f.readline(200).decode("utf-8", errors="replace").strip()
        except Exception:
            first_line = ""

        if first_line.startswith("#!"):
            shadow_python = first_line[2:].split()[0]
        else:
            shadow_python = which_result  # fall back to the script path itself

        if os.path.realpath(shadow_python) == self_real:
            return  # same Python executable — not actually a conflict

        # Rate-limit: warn at most once per day
        try:
            import json
            cache: dict = {}
            try:
                with open(_SHADOW_CACHE_PATH) as _fc:
                    cache = json.load(_fc)
            except Exception:
                pass
            if time.time() - cache.get("last_notified", 0.0) < _SHADOW_NOTIFY_INTERVAL:
                return
            cache["last_notified"] = time.time()
            os.makedirs(os.path.dirname(_SHADOW_CACHE_PATH), exist_ok=True)
            with open(_SHADOW_CACHE_PATH, "w") as _fc:
                json.dump(cache, _fc)
        except Exception:
            pass

        print(
            f"\n  ⚠️  Multiple cross-st installs detected.\n"
            f"     When you type 'st-admin', your shell will run:\n"
            f"       {which_result}\n"
            f"     which uses a different Python ({shadow_python})\n"
            f"     than the version you just upgraded.\n"
            f"\n"
            f"     To fix, remove the PATH-shadowing install:\n"
            f"       {shadow_python} -m pip uninstall cross-st\n"
            f"     Then reopen your terminal.\n",
            file=sys.stderr,
        )

    except Exception:
        pass  # never break a real command over a diagnostic


def _in_project_venv() -> bool:
    """Return True when the running Python executable lives inside _PROJECT_ROOT.

    This is the reliable signal that the developer has activated the project's
    own virtualenv (e.g. ``source .venv/bin/activate``).  When cross-st is
    installed via pipx the executable is in the pipx venv, which is *outside*
    _PROJECT_ROOT even if an editable install points __file__ back at the
    source tree — so this returns False and the dev .env is correctly skipped.

    Implementation note: we use os.path.abspath (path normalisation only) rather
    than os.path.realpath (full symlink resolution) because venv Python binaries
    are typically symlinks to the base interpreter (e.g. .venv/bin/python →
    python3.11 → /opt/homebrew/...).  realpath would escape the project tree and
    give a false negative; abspath preserves the venv path as written.
    """
    project_prefix  = os.path.abspath(_PROJECT_ROOT) + os.sep
    executable_norm = os.path.abspath(sys.executable)
    return executable_norm.startswith(project_prefix)


def load_cross_env() -> None:
    """Load Cross environment files in A1 four-layer order.

    Resolves layer 2 relative to the project root (cross/.env) so that the
    correct .env is found whether scripts run via an entry-point wrapper,
    via runpy.run_path(), or directly as ``python cross_st/st-*.py``.

    Layer order (later layers override earlier ones):
      1. ~/.crossenv                — global fallback / shared API keys (lowest priority)
      2. <project-root>/.env        — repo-local developer keys; overrides global
                                      *** only loaded when the project venv is active ***
                                      (sys.executable is inside _PROJECT_ROOT)
                                      Skipped for pipx / system-Python installs so that
                                      ~/.crossenv remains the sole config source there.
      2b. <cross_st-dir>/.env       — co-located .env (pip install layout); same guard
      3. <CWD>/.env                 — per-project override, highest priority

    Project-level .env always wins over ~/.crossenv when the dev venv is active,
    so that per-repo settings (DEFAULT_AI, model overrides, Discourse site, etc.)
    take effect without editing the global file.
    """
    from dotenv import load_dotenv
    crossenv = os.path.expanduser("~/.crossenv")
    load_dotenv(crossenv)                                                       # 1. global fallback
    if _in_project_venv():
        load_dotenv(os.path.join(_PROJECT_ROOT, ".env"), override=True)        # 2. repo root wins
        load_dotenv(os.path.join(_CROSS_ST_DIR, ".env"), override=True)        # 2b. cross_st/
    load_dotenv(os.path.join(os.getcwd(), ".env"),    override=True)           # 3. CWD — highest
    check_for_updates()
    check_shadowed_install()
