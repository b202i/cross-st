"""
test_st_bang.py — Regression tests for st-bang.py rendering helpers.

Catches logic bugs in the live-table drawing code that would silently cancel
all jobs via the ``except Exception: _cancel_all()`` handler (e.g. the
self-referential ``timeout_str`` assignment that caused instant cancellation).
"""
import importlib.util
import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Load st-bang.py as a module (filename contains a hyphen)
# ---------------------------------------------------------------------------
_BANG_PATH = Path(__file__).resolve().parent.parent / "cross_st" / "st-bang.py"


def _load_st_bang():
    spec = importlib.util.spec_from_file_location("st_bang", _BANG_PATH)
    mod = importlib.util.module_from_spec(spec)
    # Prevent main() from running at import time
    mod.__name__ = "st_bang"
    spec.loader.exec_module(mod)
    return mod


# Load once for the whole module — avoid re-executing for every test.
try:
    _st_bang = _load_st_bang()
    _LOAD_ERROR = None
except Exception as exc:
    _st_bang = None
    _LOAD_ERROR = exc


def _skip_if_load_failed():
    if _LOAD_ERROR is not None:
        pytest.skip(f"st-bang.py failed to load: {_LOAD_ERROR}")


# ---------------------------------------------------------------------------
# Minimal job fixture
# ---------------------------------------------------------------------------
def _make_jobs(statuses=None):
    """Return a list of mock job dicts compatible with _draw_table."""
    makes = ["xai", "anthropic", "openai", "perplexity", "gemini"]
    if statuses is None:
        statuses = [_st_bang.ST_RUNNING] * len(makes)
    jobs = []
    for i, (make, status) in enumerate(zip(makes, statuses)):
        jobs.append({
            "index":      i,
            "ai_key":     make,
            "make":       make,
            "model":      "test-model-v1",
            "block_file": f"/tmp/fake_{make}.block",
            "out_file":   f"/tmp/fake_{make}.json",
            "status":     status,
            "start_time": 0.0,
            "end_time":   None,
            "process":    None,
            "skipped":    False,
        })
    return jobs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestDrawTable:
    """_draw_table must not raise regardless of timeout / status combination."""

    def setup_method(self):
        _skip_if_load_failed()

    def _call_draw(self, jobs, args_timeout=0, first_draw=True):
        """Call _draw_table, capturing stdout so terminal escapes don't matter."""
        with patch("sys.stdout", new_callable=io.StringIO):
            _st_bang._draw_table(
                jobs,
                first_draw=first_draw,
                row_count=0,
                args_timeout=args_timeout,
            )

    def test_draw_no_timeout(self):
        """Renders without error when timeout is disabled (0)."""
        jobs = _make_jobs()
        self._call_draw(jobs, args_timeout=0)

    def test_draw_with_timeout_default(self):
        """
        Renders without error with the default 600-second timeout.

        This is the regression for the self-referential ``timeout_str``
        NameError that caused instant job cancellation.
        """
        jobs = _make_jobs()
        self._call_draw(jobs, args_timeout=600)

    def test_draw_with_timeout_custom(self):
        """Renders without error with a non-standard timeout."""
        jobs = _make_jobs()
        self._call_draw(jobs, args_timeout=1800)

    def test_draw_mixed_statuses(self):
        """Renders without error when jobs have mixed terminal/running statuses."""
        statuses = [
            _st_bang.ST_DONE,
            _st_bang.ST_FAILED,
            _st_bang.ST_RUNNING,
            _st_bang.ST_CACHED,
            _st_bang.ST_CANCELLED,
        ]
        jobs = _make_jobs(statuses)
        # give terminal-state jobs an end_time so elapsed calculates correctly
        import time
        for j in jobs:
            if j["status"] in (_st_bang.ST_DONE, _st_bang.ST_FAILED,
                                _st_bang.ST_CANCELLED):
                j["end_time"] = j["start_time"] + 42.0
        self._call_draw(jobs, args_timeout=600)

    def test_draw_redraw(self):
        """Second draw (first_draw=False) must not raise."""
        jobs = _make_jobs()
        self._call_draw(jobs, args_timeout=600, first_draw=False)

    def test_timeout_str_content(self):
        """The hint row must contain the formatted timeout when one is set."""
        jobs = _make_jobs()
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _st_bang._draw_table(jobs, first_draw=True, row_count=0,
                                 args_timeout=600)
        output = buf.getvalue()
        # "10:00" is the formatted form of 600 seconds
        assert "10:00" in output, (
            "Expected formatted timeout '10:00' in hint row, got:\n" + output
        )

    def test_no_timeout_no_hint_suffix(self):
        """When timeout=0 the hint row must not contain a timeout marker."""
        jobs = _make_jobs()
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _st_bang._draw_table(jobs, first_draw=True, row_count=0,
                                 args_timeout=0)
        output = buf.getvalue()
        assert "timeout" not in output.lower(), (
            "Expected no timeout string in hint row when timeout=0, got:\n"
            + output
        )

