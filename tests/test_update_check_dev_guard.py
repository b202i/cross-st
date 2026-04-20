"""tests/test_update_check_dev_guard.py

Regression guard for the upgrade-nag bug: when running cross-st from a dev
checkout under a Python interpreter that has a stale `pip install cross-st`
in its metadata (e.g. an old 0.2.0 install in system Python), the upgrade
nag would print "💡 cross-st X is available (installed: 0.2.0)" — even
though the user is patently running newer code from the checkout.

Fix: `mmd_startup.check_for_updates()` now returns early if either
`_in_project_venv()` (project venv active) or `_running_from_dev_checkout()`
(executing script lives inside _PROJECT_ROOT) is True.
"""

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_spec = importlib.util.spec_from_file_location(
    "mmd_startup",
    Path(__file__).parent.parent / "cross_st" / "mmd_startup.py",
)
mmd_startup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mmd_startup)


def test_dev_checkout_detection_via_argv0():
    """When sys.argv[0] points inside _PROJECT_ROOT, return True."""
    fake_script = os.path.join(mmd_startup._PROJECT_ROOT, "cross_st", "st-verdict.py")
    with patch.object(sys, "argv", [fake_script, "x.json"]):
        assert mmd_startup._running_from_dev_checkout() is True


def test_dev_checkout_detection_outside_project_returns_false():
    """When sys.argv[0] is in /usr/local/bin or similar, return False."""
    with patch.object(sys, "argv", ["/usr/local/bin/st-verdict", "x.json"]):
        # __main__ might still be inside the test dir, which is *not* under
        # _PROJECT_ROOT/cross_st — but tests live under _PROJECT_ROOT/tests
        # which IS under _PROJECT_ROOT. So we patch __main__ too.
        import __main__
        with patch.object(__main__, "__file__", "/usr/local/bin/pytest", create=True):
            # Note: this still depends on no stray candidate inside project root
            assert mmd_startup._running_from_dev_checkout() is False


def test_check_for_updates_skipped_when_dev_checkout(capsys):
    """check_for_updates() must return without printing when running dev source."""
    fake_script = os.path.join(mmd_startup._PROJECT_ROOT, "cross_st", "st-verdict.py")
    with patch.object(sys, "argv", [fake_script, "x.json"]):
        with patch.object(sys.stdout, "isatty", return_value=True):
            mmd_startup.check_for_updates()
    captured = capsys.readouterr()
    assert "is available" not in captured.err
    assert "is available" not in captured.out


def test_check_for_updates_skipped_when_in_project_venv(capsys):
    """check_for_updates() must also return early when the venv is the project's."""
    with patch.object(mmd_startup, "_in_project_venv", return_value=True):
        with patch.object(sys.stdout, "isatty", return_value=True):
            mmd_startup.check_for_updates()
    captured = capsys.readouterr()
    assert "is available" not in captured.err
    assert "is available" not in captured.out

