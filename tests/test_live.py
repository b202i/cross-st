"""
tests/test_live.py — Live AI integration tests.

TIER: live  (@pytest.mark.live)
Run with: pytest --live

COST MODEL
----------
Every test in this file calls a real AI provider.  However:

  - All tests pass --cache (or rely on the default --cache=True).
  - Cross-ai-core caches responses in ~/.cross_api_cache/ by MD5 hash
    of the prompt.
  - On the first run, each test costs a small amount of money and takes
    ~5-30 s depending on provider and prompt length.
  - On every subsequent run (same machine, same prompt), the response is
    served from cache: ~0 ms, $0.

Practical workflow
------------------
1. Run once on a machine with valid API keys in ~/.crossenv:
       pytest --live
2. Cache is populated.  From now on:
       pytest --live     # fast (~1-2 s per test), free
3. To force fresh API calls (e.g. to test a new prompt):
       pytest --live --no-cache    # (not implemented yet — force via env)
   Or: CROSS_NO_CACHE=1 pytest --live

PROMPT CHOICE
-------------
Tests use the pizza_dough fixture prompt (short, stable, well-cached) or
a tiny inline prompt.  Neither uses real research topics, so AI output is
predictable and cheap.

Fixtures
--------
  pizza_dough.json  — 5 AI stories + 25 fact-check results, fully cached.

Test scope
----------
Each test validates one end-to-end workflow:
  st-gen     → generates a story from a prompt
  st-fact    → fact-checks a story
  st-cross   → runs Step 1 + Step 2 on a minimal 1×1 matrix
  st-speed   → reads timing data from a populated container
  st-verdict → produces a verdict table
  st-heatmap → produces a heatmap

The tests use --cache so responses come from disk on repeat runs.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT     = Path(__file__).parent.parent
_FIXTURES = Path(__file__).parent / "fixtures"
_PIZZA    = _FIXTURES / "pizza_dough.json"

# ---------------------------------------------------------------------------
# Helper (same as test_integration.py)
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd=None, timeout=120) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT / "cross_st") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        cmd,
        capture_output=True, text=True,
        timeout=timeout,
        cwd=cwd or str(_ROOT),
        env=env,
    )


def _no_traceback(result: subprocess.CompletedProcess):
    combined = result.stdout + result.stderr
    assert "Traceback (most recent call last)" not in combined, (
        f"Unexpected traceback:\n{combined}"
    )


@pytest.fixture()
def pizza(tmp_path) -> Path:
    dest = tmp_path / "pizza_dough.json"
    shutil.copy(_PIZZA, dest)
    return dest


# ---------------------------------------------------------------------------
# Live tests
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestStGenLive:
    """st-gen: generate a story from a prompt file."""

    def test_gen_single_ai(self, tmp_path):
        """Generate one story with one AI, using cache."""
        prompt = tmp_path / "test_topic.prompt"
        prompt.write_text(
            "What are the main ingredients in a basic pizza dough? "
            "Write a short factual report of about 200 words."
        )
        out_json = tmp_path / "test_topic.json"
        result = _run(
            ["st-gen", "--ai", "openai", "--cache", str(prompt)],
            cwd=str(tmp_path),
        )
        _no_traceback(result)
        assert result.returncode == 0, f"st-gen failed:\n{result.stderr}"
        assert out_json.exists(), "st-gen did not create output JSON"
        data = json.loads(out_json.read_text())
        assert len(data.get("data", [])) >= 1, "No data[] entries generated"


@pytest.mark.live
class TestStFactLive:
    """st-fact: fact-check a story that already exists in the fixture."""

    def test_fact_check_story1_openai(self, pizza):
        """Fact-check story 1 with openai, using cache."""
        result = _run(
            ["st-fact", "--ai", "openai", "--story", "1", "--cache", str(pizza)],
            timeout=300,
        )
        _no_traceback(result)
        assert result.returncode == 0, f"st-fact failed:\n{result.stderr}"
        # Verify fact results were written
        data = json.loads(pizza.read_text())
        story1 = data["story"][0]
        facts_by_openai = [f for f in story1.get("fact", []) if f.get("make") == "openai"]
        assert len(facts_by_openai) >= 1, "No openai fact entry found after st-fact"


@pytest.mark.live
class TestStCrossLive:
    """st-cross: full end-to-end with a 1-provider subset."""

    def test_cross_skip_gen_all_cached(self, pizza):
        """Run st-cross --skip-gen on the fully-populated fixture.

        All 25 cells are already complete — Step 2 should detect this, report
        25 done, and exit quickly without making any AI calls.
        This validates that Step 2 actually executes and produces a summary.
        """
        result = _run(
            ["st-cross", "--skip-gen", "--cache", str(pizza)],
            timeout=120,
        )
        _no_traceback(result)
        assert result.returncode == 0, f"st-cross failed:\n{result.stderr}"
        combined = result.stdout + result.stderr
        assert "Cross-product:" in combined, (
            "Step 2 summary line missing — Step 2 may not have executed.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


@pytest.mark.live
class TestStVerdictLive:

    def test_verdict_on_fixture(self, pizza):
        result = _run(["st-verdict", "--cache", str(pizza)])
        _no_traceback(result)
        assert result.returncode == 0, f"st-verdict failed:\n{result.stderr}"


@pytest.mark.live
class TestStSpeedLive:

    def test_speed_on_fixture(self, pizza):
        result = _run(["st-speed", str(pizza)])
        _no_traceback(result)
        assert result.returncode == 0, f"st-speed failed:\n{result.stderr}"


@pytest.mark.live
class TestStHeatmapLive:

    def test_heatmap_on_fixture(self, pizza):
        # --display is required; use MPLBACKEND=Agg to suppress GUI window
        env = os.environ.copy()
        env["MPLBACKEND"] = "Agg"
        result = subprocess.run(
            ["st-heatmap", "--display", str(pizza)],
            capture_output=True, text=True, timeout=120,
            env=env,
        )
        _no_traceback(result)
        assert result.returncode == 0, f"st-heatmap failed:\n{result.stdout}\n{result.stderr}"


@pytest.mark.live
class TestStAnalyzeLive:

    def test_analyze_on_fixture(self, pizza):
        # st-analyze requires a .prompt file alongside the .json
        # Use xai (reliable, fast) with --cache so re-runs are free
        prompt = pizza.with_suffix(".prompt")
        prompt.write_text("What are the best practices in software development?")
        result = _run(["st-analyze", "--ai", "xai", "--cache", str(pizza)])
        _no_traceback(result)
        assert result.returncode == 0, f"st-analyze failed:\n{result.stderr}"

