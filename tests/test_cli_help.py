"""
tests/test_cli_help.py — Smoke tests: every st-* command must handle --help
without raising a Python exception.

WHY THIS EXISTS
---------------
Existing tests only reach into helper functions; they never call main().
Bugs in argparse setup — NameError (undefined variable used as a default=),
ImportError, AttributeError — are invisible until someone runs the command.
This file catches that entire class of regression.

WHAT IS TESTED
--------------
For each command (two subprocess calls per command):

  test_help_via_entry_point  — invokes the installed entry-point wrapper in
      .venv/bin/ (e.g. ``st-verdict --help``).  This is the ONLY path that
      exercises commands.py → runpy.run_path(), which is the path a real user
      takes.  Bugs like a missing sys.path insert in _run() only show up here.

  test_help_via_script  — invokes the .py file directly
      (``python cross_st/st-verdict.py --help``).  Python automatically adds
      the script directory to sys.path[0], so module imports resolve even if
      commands.py is broken.  Kept as a quick sanity check.

For each variant:
  1. "Traceback" must NOT appear in stderr  — no Python exception raised.
  2. Exit code must be 0                    — --help printed cleanly.

SPEED NOTE
----------
These tests spawn real Python subprocesses and are intentionally excluded
from the default `pytest` run.  They are marked `slow`.

  pytest                  # fast unit tests only  (~2 s)
  pytest --slow           # also run CLI smoke tests  (~20 s)
  pytest -m slow          # slow tests only

EXCLUDED
--------
  st        — interactive curses menu; no --help flag.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_SCRIPTS = _ROOT / "cross_st"        # st-*.py scripts live in cross_st/
_VENV_BIN = Path(sys.executable).parent  # .venv/bin — entry-point wrappers

# Every command that exposes a --help flag (argparse or manual).
_COMMANDS = [
    "st-admin",
    "st-analyze",
    "st-bang",
    "st-cat",
    "st-cross",
    "st-domain",
    "st-edit",
    "st-fact",
    "st-fetch",
    "st-find",
    "st-fix",
    "st-gen",
    "st-heatmap",
    "st-ls",
    "st-man",
    "st-merge",
    "st-new",
    "st-plot",
    "st-post",
    "st-prep",
    "st-print",
    "st-read",
    "st-rm",
    "st-speak",
    "st-speed",
    "st-stones",
    "st-verdict",
    "st-voice",
]


@pytest.fixture(scope="module")
def fake_home(tmp_path_factory):
    """Return a tmp dir with a minimal .crossenv so require_config() passes."""
    home = tmp_path_factory.mktemp("home")
    (home / ".crossenv").write_text("DEFAULT_AI=xai\n")
    return home


def _env(fake_home):
    """Minimal environment dict for subprocess calls."""
    return {
        "HOME": str(fake_home),
        "PATH": str(_VENV_BIN) + ":/usr/bin:/bin",
    }


@pytest.mark.slow
@pytest.mark.parametrize("cmd", _COMMANDS)
def test_help_via_entry_point(cmd, fake_home):
    """Entry-point wrapper (commands.py → runpy.run_path) must handle --help.

    This is the critical path: it exercises the same code that runs when a
    user types ``st-verdict --help`` after ``pip install cross-ai``.
    Bugs in commands._run() (e.g. missing sys.path insert) only show up here.
    """
    entry_point = _VENV_BIN / cmd
    if not entry_point.exists():
        pytest.skip(f"entry-point {entry_point} not found — run pip install -e .")

    result = subprocess.run(
        [str(entry_point), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
        env=_env(fake_home),
    )

    assert "Traceback" not in result.stderr, (
        f"`{cmd} --help` (entry-point) raised a Python exception:\n\n{result.stderr}"
    )
    assert result.returncode == 0, (
        f"`{cmd} --help` (entry-point) exited {result.returncode}.\n"
        f"stdout: {result.stdout[:300]}\n"
        f"stderr: {result.stderr[:300]}"
    )


@pytest.mark.slow
@pytest.mark.parametrize("cmd", _COMMANDS)
def test_help_via_script(cmd, fake_home):
    """Direct script execution must handle --help.

    ``python cross_st/st-verdict.py --help`` — Python adds cross_st/ to
    sys.path[0] automatically, so this passes even when commands.py is broken.
    Kept as a quick sanity check that the script itself is well-formed.
    """
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS / f"{cmd}.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
        env=_env(fake_home),
    )

    assert "Traceback" not in result.stderr, (
        f"`{cmd} --help` (direct script) raised a Python exception:\n\n{result.stderr}"
    )
    assert result.returncode == 0, (
        f"`{cmd} --help` (direct script) exited {result.returncode}.\n"
        f"stdout: {result.stdout[:300]}\n"
        f"stderr: {result.stderr[:300]}"
    )
