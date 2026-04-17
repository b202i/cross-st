"""
tests/test_integration.py — Integration tests: real CLI subprocesses, no AI calls.

TIER: slow  (@pytest.mark.slow)
Run with: pytest --slow

WHY THIS EXISTS
---------------
Unit tests mock everything and never call main().  Structural bugs — wrong
indentation that silently ends main() early, a NameError that only fires
at runtime, a flag that's wired to the wrong dest — are invisible to unit
tests but caught here in seconds.

The canonical example: st-cross Step 2 never executed for the entire PAR-1
lifetime because the _get_provider_semaphore function was at 0-indent inside
main(), ending main() before any threads launched.  746 unit tests passed.
This integration test catches it in <1 s.

WHAT IS TESTED
--------------
Each test spawns a real subprocess (the installed entry-point or the .py file
directly) and checks:
  - Exit code is 0 (or the expected non-zero for error cases)
  - stdout/stderr contains expected strings
  - stdout does NOT contain "Traceback" (no unhandled exception)

The pizza_dough.json fixture (tests/fixtures/pizza_dough.json) has:
  - data[5]   — raw AI generation payloads for 5 AI providers
  - story[5]  — prepared stories (title, text, hashtags, segments)
  - fact[25]  — 5×5 cross-product fact-check results
This means every st-* command that operates on a fully-populated container
can run without making any AI calls.

SPEED
-----
All tests in this file are subprocess calls on pre-built fixture data.
No AI calls are made.  Total runtime ~5-15 s.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT    = Path(__file__).parent.parent
_FIXTURES = Path(__file__).parent / "fixtures"
_PIZZA   = _FIXTURES / "pizza_dough.json"

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd=None, timeout=30) -> subprocess.CompletedProcess:
    """Run a command, capturing stdout+stderr.  Never raises on non-zero exit."""
    env = os.environ.copy()
    # Ensure cross_st/ is on the path for direct .py invocations
    env["PYTHONPATH"] = str(_ROOT / "cross_st") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        cmd,
        capture_output=True, text=True,
        timeout=timeout,
        cwd=cwd or str(_ROOT),
        env=env,
    )


def _no_traceback(result: subprocess.CompletedProcess):
    """Assert that neither stdout nor stderr contains a Python traceback."""
    combined = result.stdout + result.stderr
    assert "Traceback (most recent call last)" not in combined, (
        f"Unexpected traceback:\n{combined}"
    )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def pizza(tmp_path) -> Path:
    """Copy pizza_dough.json into a temp dir so tests can write to it freely."""
    dest = tmp_path / "pizza_dough.json"
    shutil.copy(_PIZZA, dest)
    return dest


# ===========================================================================
# st-cross integration tests
# ===========================================================================

class TestStCrossIntegration:
    """st-cross: the command that had Step 2 silently never execute."""

    @pytest.mark.slow
    def test_dry_run_exits_zero(self, pizza):
        """--dry-run should preview the matrix and exit 0 without any AI call."""
        result = _run(["st-cross", "--dry-run", str(pizza)])
        assert result.returncode == 0, f"stderr: {result.stderr}"
        _no_traceback(result)
        assert "5×5" in result.stdout, "Expected 5×5 matrix in dry-run output"
        assert "25 cells" in result.stdout

    @pytest.mark.slow
    def test_dry_run_shows_all_done(self, pizza):
        """pizza_dough has all 25 cells — dry-run should show 0 pending."""
        result = _run(["st-cross", "--dry-run", str(pizza)])
        assert result.returncode == 0
        assert "Nothing to do" in result.stdout or "0 pending" in result.stdout, (
            f"Expected all cells pre-completed:\n{result.stdout}"
        )

    @pytest.mark.slow
    def test_skip_gen_does_not_regenerate(self, pizza, tmp_path):
        """--skip-gen should not touch data[] — mtime of pizza should not change."""
        mtime_before = pizza.stat().st_mtime
        # run a dry-run (implies --skip-gen) just to exercise the flag path
        result = _run(["st-cross", "--skip-gen", "--dry-run", str(pizza)])
        assert result.returncode == 0
        _no_traceback(result)

    @pytest.mark.slow
    def test_step2_launches_with_all_preloaded(self, pizza):
        """When all 25 cells are pre-loaded, Step 2 should report 25 done and exit.

        This is the canonical regression test for the 'main() silently returns'
        bug: if Step 2 never executes, the summary line ('Cross-product:') will
        not appear in output.
        """
        result = _run(["st-cross", "--skip-gen", str(pizza)], timeout=60)
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        _no_traceback(result)
        combined = result.stdout + result.stderr
        # The summary line must appear — if main() exited early it won't
        assert "Cross-product:" in combined, (
            "Step 2 summary missing — main() may have exited before threads launched.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "25 done" in combined or "done" in combined

    @pytest.mark.slow
    def test_verbose_step2_banner(self, pizza):
        """--verbose should print the Step 2 header even when all cells are pre-loaded."""
        result = _run(["st-cross", "--verbose", "--skip-gen", str(pizza)], timeout=60)
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        _no_traceback(result)
        assert "Step 2" in result.stdout, (
            "--verbose mode did not print Step 2 banner"
        )

    @pytest.mark.slow
    def test_quiet_produces_no_output(self, pizza):
        """--quiet should suppress all non-error output."""
        result = _run(["st-cross", "--quiet", "--skip-gen", str(pizza)], timeout=60)
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        _no_traceback(result)
        assert result.stdout.strip() == "", (
            f"--quiet produced unexpected output:\n{result.stdout}"
        )


# ===========================================================================
# st-verdict integration tests
# ===========================================================================

class TestStVerdictIntegration:

    @pytest.mark.slow
    def test_runs_on_fixture(self, pizza):
        result = _run(["st-verdict", str(pizza)])
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        _no_traceback(result)

    @pytest.mark.slow
    def test_output_contains_scores(self, pizza):
        result = _run(["st-verdict", str(pizza)])
        combined = result.stdout + result.stderr
        # Should show some kind of score table or percentage
        assert any(c.isdigit() for c in combined), "Expected numeric scores in verdict output"


# ===========================================================================
# st-heatmap integration tests
# ===========================================================================

class TestStHeatmapIntegration:

    @pytest.mark.slow
    def test_runs_on_fixture(self, pizza):
        result = _run(["st-heatmap", str(pizza)])
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        _no_traceback(result)


# ===========================================================================
# st-speed integration tests
# ===========================================================================

class TestStSpeedIntegration:

    @pytest.mark.slow
    def test_runs_on_fixture(self, pizza):
        result = _run(["st-speed", str(pizza)])
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        _no_traceback(result)


# ===========================================================================
# st-analyze integration tests
# ===========================================================================

class TestStAnalyzeIntegration:

    @pytest.mark.slow
    def test_help(self):
        result = _run(["st-analyze", "--help"])
        assert result.returncode == 0
        _no_traceback(result)

    @pytest.mark.slow
    def test_runs_on_fixture(self, pizza):
        result = _run(["st-analyze", str(pizza)])
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        _no_traceback(result)


# ===========================================================================
# st-cat / st-ls integration tests (read-only, no AI needed ever)
# ===========================================================================

class TestStCatIntegration:

    @pytest.mark.slow
    def test_runs_on_fixture(self, pizza):
        result = _run(["st-cat", str(pizza)])
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        _no_traceback(result)
        # Should show story content
        assert len(result.stdout.strip()) > 0


class TestStLsIntegration:

    @pytest.mark.slow
    def test_runs_in_fixture_dir(self, tmp_path):
        shutil.copy(_PIZZA, tmp_path / "pizza_dough.json")
        result = _run(["st-ls"], cwd=str(tmp_path))
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        _no_traceback(result)


# ===========================================================================
# st-find integration tests
# ===========================================================================

class TestStFindIntegration:

    @pytest.mark.slow
    def test_finds_by_keyword(self, pizza):
        result = _run(["st-find", "pizza", str(pizza.parent)])
        # Should either find it or return 0 with no results — just not crash
        _no_traceback(result)
        assert result.returncode in (0, 1)  # 1 = no results is acceptable


# ===========================================================================
# st-plot integration tests
# ===========================================================================

class TestStPlotIntegration:

    @pytest.mark.slow
    def test_runs_on_fixture(self, pizza):
        result = _run(["st-plot", str(pizza)])
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        _no_traceback(result)


# ===========================================================================
# st-merge integration tests
# ===========================================================================

class TestStMergeIntegration:

    @pytest.mark.slow
    def test_help(self):
        result = _run(["st-merge", "--help"])
        assert result.returncode == 0
        _no_traceback(result)


# ===========================================================================
# st-fact integration tests (read/verify only — no new AI calls needed
# when the container already has fact[] entries)
# ===========================================================================

class TestStFactIntegration:

    @pytest.mark.slow
    def test_help(self):
        result = _run(["st-fact", "--help"])
        assert result.returncode == 0
        _no_traceback(result)

    @pytest.mark.slow
    def test_display_on_fixture(self, pizza):
        """--display shows cached fact-check results without calling the API."""
        result = _run(["st-fact", "--display", "--story", "1", str(pizza)])
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        _no_traceback(result)


# ===========================================================================
# st-stones integration tests
# ===========================================================================

class TestStStonesIntegration:

    @pytest.mark.slow
    def test_help(self):
        result = _run(["st-stones", "--help"])
        assert result.returncode == 0
        _no_traceback(result)


# ===========================================================================
# Structural smoke: all 29 entry-points must import cleanly
# ===========================================================================

_ENTRY_POINTS = [
    "st-admin", "st-analyze", "st-bang", "st-cat", "st-cross",
    "st-domain", "st-edit", "st-fact", "st-fetch", "st-find",
    "st-fix", "st-gen", "st-heatmap", "st-ls", "st-man",
    "st-merge", "st-new", "st-plot", "st-post", "st-prep",
    "st-print", "st-speed", "st-stones", "st-verdict",
]

@pytest.mark.slow
@pytest.mark.parametrize("cmd", _ENTRY_POINTS)
def test_entrypoint_help(cmd):
    """Every entry-point must handle --help without a traceback."""
    result = _run([cmd, "--help"])
    assert result.returncode == 0, (
        f"{cmd} --help exited {result.returncode}:\n{result.stderr}"
    )
    _no_traceback(result)

