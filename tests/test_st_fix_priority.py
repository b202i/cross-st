"""tests/test_st_fix_priority.py — coverage for st-fix's weighted auto-selector.

We exercise the auto-select path end-to-end by constructing a JSON container
on disk, invoking st-fix in dry-run mode through subprocess, and asserting
on stdout. This avoids needing any AI calls.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).parent.parent
ST_FIX = REPO / "cross_st" / "st-fix.py"


def _make_container(stories, prompt="Write a 300-500 word report about quantum computing"):
    return {
        "data": [{"prompt": prompt}],
        "story": stories,
    }


def _make_story(make, text, fact_report=None, generated_by=None,
                counts=None, score=None):
    s = {
        "make":     make,
        "model":    f"{make}-model",
        "title":    "Quantum",
        "markdown": text,
        "text":     text,
        "spoken":   "",
        "hashtags": [],
        "fact":     [],
    }
    if generated_by:
        s["_generated_by"] = generated_by
    if fact_report is not None:
        s["fact"] = [{
            "make":   "xai",
            "model":  "grok",
            "score":  score if score is not None else 1.0,
            "counts": counts or [0, 0, 0, 0, 0],
            "report": fact_report,
        }]
    return s


def _run_stfix(json_path, *extra):
    """Run st-fix --dry-run and return (returncode, stdout)."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "cross_st") + os.pathsep + env.get("PYTHONPATH", "")
    # require_config() needs a .env file somewhere it looks; the JSON's
    # tmp dir is convenient (CWD-level .env counts).  Without this, CI
    # runners with no ~/.crossenv exit 1 before argparse runs.
    tmp_dir = json_path.parent
    (tmp_dir / ".env").write_text("OPENAI_API_KEY=test\nXAI_API_KEY=test\n")
    cmd = [sys.executable, str(ST_FIX), "--dry-run", *extra, str(json_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(tmp_dir))
    return proc.returncode, proc.stdout + proc.stderr


def _claim(verdict):
    return (f'Claim 1: "demo claim"\nVerification: {verdict}\n'
            f'Explanation: details here.\n')


# ── Test fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_container(tmp_path):
    def _build(stories, prompt=None):
        path = tmp_path / "report.json"
        c = _make_container(stories, prompt=prompt) if prompt else _make_container(stories)
        path.write_text(json.dumps(c))
        return path
    return _build


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_no_fact_entries_recovery_hint(tmp_container):
    """Container with stories but zero fact entries → recovery message."""
    stories = [
        _make_story("xai", "Quantum computing is the use of quantum bits."),
        _make_story("openai", "Quantum computers use qubits to compute."),
    ]
    path = tmp_container(stories)
    rc, out = _run_stfix(path)
    assert rc == 0
    assert "No fact entries found" in out
    assert "st-cross" in out


def test_excludes_generated_by_default(tmp_container):
    """A story with _generated_by is skipped from auto-selection unless --include-fixed."""
    stamp = {"tool": "st-fix", "mode": "iterate", "source_s": 1, "source_f": 1,
             "rewriter": "xai", "timestamp": "2026-04-24T00:00:00Z"}
    stories = [
        # original with fixable claims
        _make_story("xai", "Quantum computing is hard.",
                    fact_report=_claim("False"), counts=[0, 0, 0, 0, 1], score=1.0),
        # st-fix output, also with fixable claims
        _make_story("openai", "Computing in quantum is hard.",
                    fact_report=_claim("False"), counts=[0, 0, 0, 0, 1], score=1.0,
                    generated_by=stamp),
    ]
    path = tmp_container(stories)
    rc, out = _run_stfix(path)
    assert rc == 0
    # Auto-pick should be story 1 (the original), not story 2 (st-fix output)
    assert "Auto-selected: story 1" in out


def test_include_fixed_brings_them_back(tmp_container):
    stamp = {"tool": "st-fix", "mode": "iterate", "source_s": 1, "source_f": 1,
             "rewriter": "xai", "timestamp": "2026-04-24T00:00:00Z"}
    stories = [
        # st-fix output is the only one with fixable claims
        _make_story("xai", "Quantum computing report.",
                    fact_report=_claim("True"), counts=[1, 0, 0, 0, 0], score=2.0),
        _make_story("openai", "Quantum computing report.",
                    fact_report=_claim("False"), counts=[0, 0, 0, 0, 1], score=1.0,
                    generated_by=stamp),
    ]
    path = tmp_container(stories)

    # Without --include-fixed → "no unfixed originals have remaining issues" message
    rc, out = _run_stfix(path)
    assert rc == 0
    assert "no unfixed originals" in out.lower() or "all" in out.lower()

    # With --include-fixed → auto-pick the st-fix output (story 2)
    rc, out = _run_stfix(path, "--include-fixed")
    assert rc == 0
    assert "Auto-selected: story 2" in out


def test_score_breaks_tie_when_claims_equal(tmp_container):
    """Two candidates, same fixable count — higher fact-check score wins."""
    stories = [
        # 1 fixable claim, low score
        _make_story("xai", "Quantum computing is a thing about qubits.",
                    fact_report=_claim("False"),
                    counts=[0, 0, 0, 0, 1], score=0.5),
        # 1 fixable claim, high score
        _make_story("openai", "Quantum computing is a thing about qubits.",
                    fact_report=_claim("False"),
                    counts=[0, 0, 0, 0, 1], score=1.8),
    ]
    path = tmp_container(stories)
    rc, out = _run_stfix(path)
    assert rc == 0
    assert "Auto-selected: story 2" in out


def test_table_shows_priority_and_why(tmp_container):
    stories = [
        _make_story("xai", "Quantum computing report on qubits.",
                    fact_report=_claim("False"),
                    counts=[0, 0, 0, 0, 1], score=1.5),
    ]
    path = tmp_container(stories)
    rc, out = _run_stfix(path)
    assert rc == 0
    assert "Prio" in out  # new column
    assert "weighted priority" in out.lower()

