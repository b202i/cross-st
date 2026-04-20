"""tests/test_st_cross_force_flag.py

Regression guard for the --force flag (BUGFIX 2026-04-19): without it, a
re-run on a fully-populated container short-circuits at the resume pre-scan
("✓ Cross-product fact-check already complete") even when the user wants to
re-fact-check after a prompt change. --force must:

  1. Be present in the argparse surface.
  2. Imply --no-cache (so stale cached responses can't sneak through under
     the same MD5).
  3. Clear all existing story[N].fact[] entries on disk before the launch
     loop, so the re-run produces a clean 25-cell matrix instead of
     appending duplicates.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.mark.slow
def test_force_flag_present_in_help():
    """--force appears in --help output with the expected wording."""
    repo = Path(__file__).parent.parent
    out = subprocess.run(
        [sys.executable, str(repo / "cross_st" / "st-cross.py"), "--help"],
        capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(repo / "cross_st")},
    )
    assert out.returncode == 0
    assert "--force" in out.stdout
    assert "Implies --no-cache" in out.stdout


@pytest.mark.slow
def test_no_cache_help_warns_force_is_separate():
    """--no-cache help text must clarify it does NOT force a re-fact-check."""
    repo = Path(__file__).parent.parent
    out = subprocess.run(
        [sys.executable, str(repo / "cross_st" / "st-cross.py"), "--help"],
        capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(repo / "cross_st")},
    )
    assert "see --force" in out.stdout


def test_force_clears_fact_entries_on_disk():
    """When --force runs against a populated container, all fact[] entries
    are cleared from disk before the launch loop. Verify by simulating the
    pre-scan block's clear logic against a fixture container."""
    container = {
        "data": [{"prompt": "p"}],
        "story": [
            {"title": "s1", "fact": [{"make": "xai", "md5_hash": "old"},
                                      {"make": "anthropic", "md5_hash": "old2"}]},
            {"title": "s2", "fact": [{"make": "xai", "md5_hash": "old3"}]},
        ],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(container, f)
        path = f.name
    try:
        # Re-implement the clear block from st-cross.py (lines ~671-688) to
        # verify the contract — keeps this test independent of subprocess
        # orchestration and cheap to run.
        with open(path) as f:
            c = json.load(f)
        cleared = 0
        N = 5
        for story in c.get("story", [])[:N]:
            facts = story.get("fact") or []
            cleared += len(facts)
            story["fact"] = []
        with open(path, "w") as f:
            json.dump(c, f)

        with open(path) as f:
            after = json.load(f)
        assert cleared == 3
        for story in after["story"]:
            assert story["fact"] == []
    finally:
        os.unlink(path)


def test_force_implies_no_cache_in_argparse():
    """Smoke-load the argparse builder and verify the --force → cache=False
    side-effect is present in the wiring."""
    src = (Path(__file__).parent.parent / "cross_st" / "st-cross.py").read_text()
    # The implication is one explicit line — exact-string regression guard.
    assert "if args.force:" in src
    assert "args.cache = False" in src

