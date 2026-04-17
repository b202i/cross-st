"""
tests/test_st_cross.py — unit tests for cross_st/st-cross.py

Covers:
  * PAR-1 surface: per-provider rate-limit semaphore registry + CLI flags
    (`--parallel`, `--sequential`, `--max-concurrency`, `--retry-budget`).
  * Orchestration helpers: `_stories_complete`, `_ensure_segments`,
    `_read_progress`, `_fmt`, plus smoke tests of the rendering functions
    `_draw_cross_table` and `_draw_gen_table`.

The full N×N cell-execution loop is *not* exercised here — running real
`st-fact` subprocesses across the matrix would take 30+ minutes; that is
covered by `script/smoke_test.sh` post-release.
"""
import importlib.util
import io
import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ── Module loader (st-cross has a hyphen → can't `import st-cross`) ──────────

@pytest.fixture(scope="module")
def st_cross_mod():
    """Load cross_st/st-cross.py as a module without executing main()."""
    path = Path(__file__).parent.parent / "cross_st" / "st-cross.py"
    spec = importlib.util.spec_from_file_location("st_cross", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["st_cross"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _reset_semaphore_registry(st_cross_mod):
    """Each test starts with an empty semaphore registry."""
    with st_cross_mod._semaphores_lock:
        st_cross_mod._provider_semaphores.clear()
    yield
    with st_cross_mod._semaphores_lock:
        st_cross_mod._provider_semaphores.clear()


# ─────────────────────────────────────────────────────────────────────────────
# _get_provider_semaphore — registry behaviour
# ─────────────────────────────────────────────────────────────────────────────

class TestGetProviderSemaphore:
    def test_default_size_from_get_rate_limit_concurrency(self, st_cross_mod):
        """Default cap matches cross-ai-core's per-provider value."""
        from cross_ai_core import get_rate_limit_concurrency
        sem = st_cross_mod._get_provider_semaphore("openai", None, sequential=False)
        assert isinstance(sem, threading.Semaphore)
        # Drain the semaphore: should allow exactly N acquires non-blocking.
        n = get_rate_limit_concurrency("openai")
        for _ in range(n):
            assert sem.acquire(blocking=False)
        # (n+1)th must block (we test non-blocking → False).
        assert sem.acquire(blocking=False) is False

    def test_max_override_sized_correctly(self, st_cross_mod):
        sem = st_cross_mod._get_provider_semaphore("xai", max_override=2, sequential=False)
        assert sem.acquire(blocking=False)
        assert sem.acquire(blocking=False)
        assert sem.acquire(blocking=False) is False  # cap hit

    def test_sequential_returns_global_semaphore_size_1(self, st_cross_mod):
        sem_a = st_cross_mod._get_provider_semaphore("xai", None, sequential=True)
        sem_b = st_cross_mod._get_provider_semaphore("openai", None, sequential=True)
        assert sem_a is sem_b is st_cross_mod._sequential_semaphore
        # Sequential semaphore is sized 1.
        assert sem_a.acquire(blocking=False)
        assert sem_a.acquire(blocking=False) is False
        sem_a.release()

    def test_same_make_returns_same_instance(self, st_cross_mod):
        a = st_cross_mod._get_provider_semaphore("anthropic", None, sequential=False)
        b = st_cross_mod._get_provider_semaphore("anthropic", None, sequential=False)
        assert a is b

    def test_different_makes_get_different_semaphores(self, st_cross_mod):
        a = st_cross_mod._get_provider_semaphore("xai", None, sequential=False)
        b = st_cross_mod._get_provider_semaphore("gemini", None, sequential=False)
        assert a is not b

    def test_override_keys_separately_from_default(self, st_cross_mod):
        """A make+override combination is a distinct cache key from the make alone."""
        default = st_cross_mod._get_provider_semaphore("openai", None, sequential=False)
        overridden = st_cross_mod._get_provider_semaphore("openai", 1, sequential=False)
        assert default is not overridden


# ─────────────────────────────────────────────────────────────────────────────
# Concurrent rate-limit enforcement (the headline PAR-1 invariant)
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimitEnforcement:
    def test_semaphore_caps_concurrent_acquires(self, st_cross_mod):
        """N+1 threads racing on the same provider semaphore — only N proceed at once.

        Pattern mirrors CAC-8's threading.Barrier race test: N+1 threads call
        acquire(); the (N+1)th must time out, proving the cap is enforced.
        """
        from cross_ai_core import get_rate_limit_concurrency

        make = "openai"
        cap = get_rate_limit_concurrency(make)
        sem = st_cross_mod._get_provider_semaphore(make, None, sequential=False)

        # Hold the cap with `cap` long-running threads.
        proceed = threading.Event()
        in_critical = threading.Semaphore(0)  # counts how many entered the critical section

        def holder():
            with sem:
                in_critical.release()
                proceed.wait(timeout=2.0)

        holders = [threading.Thread(target=holder) for _ in range(cap)]
        for t in holders:
            t.start()

        # Wait until exactly `cap` threads are inside.
        for _ in range(cap):
            assert in_critical.acquire(timeout=1.0), "holders failed to enter critical section"

        # The (cap+1)th acquire must NOT succeed within 100 ms.
        assert sem.acquire(timeout=0.1) is False, \
            "semaphore allowed more than the rate-limit cap to enter concurrently"

        # Release holders so their threads finish.
        proceed.set()
        for t in holders:
            t.join(timeout=1.0)

    def test_sequential_mode_serialises_all_makes(self, st_cross_mod):
        """--sequential routes every make through the same Semaphore(1)."""
        sem_xai = st_cross_mod._get_provider_semaphore("xai", None, sequential=True)
        sem_openai = st_cross_mod._get_provider_semaphore("openai", None, sequential=True)
        # Same instance → cap of 1 across all providers.
        assert sem_xai is sem_openai
        assert sem_xai.acquire(blocking=False)
        # Now no other provider thread can proceed.
        assert sem_openai.acquire(blocking=False) is False
        sem_xai.release()


# ─────────────────────────────────────────────────────────────────────────────
# CLI surface
# ─────────────────────────────────────────────────────────────────────────────

class TestCLISurface:
    """Verify --help advertises the PAR-1 flags and they parse correctly."""

    def _run_help(self):
        import subprocess
        path = Path(__file__).parent.parent / "cross_st" / "st-cross.py"
        result = subprocess.run(
            [sys.executable, str(path), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout

    def test_parallel_flag_in_help(self):
        out = self._run_help()
        assert "--parallel" in out
        assert "--sequential" in out

    def test_max_concurrency_in_help(self):
        out = self._run_help()
        assert "--max-concurrency" in out
        # Mentions the per-provider defaults so users understand the cap.
        assert "xai=3" in out and "anthropic=2" in out

    def test_retry_budget_in_help(self):
        out = self._run_help()
        assert "--retry-budget" in out
        # argparse may wrap "0 = unlimited" across lines; collapse whitespace.
        assert "0 = unlimited" in " ".join(out.split())

    def test_parallel_and_sequential_are_mutually_exclusive(self):
        """argparse must reject `--parallel --sequential` simultaneously."""
        import subprocess
        path = Path(__file__).parent.parent / "cross_st" / "st-cross.py"
        result = subprocess.run(
            [sys.executable, str(path), "--parallel", "--sequential", "dummy.json"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0
        assert "not allowed with" in result.stderr or "mutually exclusive" in result.stderr.lower()

    def test_dry_run_in_help(self):
        out = self._run_help()
        assert "--dry-run" in out
        # Help text mentions the key behaviour.
        assert "Implies --skip-gen" in " ".join(out.split())

    def test_verbose_help_mentions_table_suppression(self):
        out = self._run_help()
        # The verbose flag help should warn that the live table is suppressed
        # to avoid interleaving (Finding 12).
        normalised = " ".join(out.split())
        assert "no live table" in normalised or "live table" in normalised


# ─────────────────────────────────────────────────────────────────────────────
# st-fact --retry-budget surface
# ─────────────────────────────────────────────────────────────────────────────

class TestStFactRetryBudgetCLI:
    def test_retry_budget_in_help(self):
        import subprocess
        path = Path(__file__).parent.parent / "cross_st" / "st-fact.py"
        result = subprocess.run(
            [sys.executable, str(path), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert "--retry-budget" in result.stdout
        assert "0 = unlimited" in " ".join(result.stdout.split())


# ─────────────────────────────────────────────────────────────────────────────
# progress_file_path (mmd_util) — shared naming helper (Finding 7)
# ─────────────────────────────────────────────────────────────────────────────

class TestProgressFilePath:
    """The naming helper is the single source of truth used by st-cross
    (_read_progress) and st-fact (write side). Test the contract directly."""

    def test_basic_shape(self, st_cross_mod, tmp_path, monkeypatch):
        import mmd_util
        monkeypatch.setattr(mmd_util, "get_tmp_dir", lambda: tmp_path)
        path = mmd_util.progress_file_path("myprefix", 1, "openai")
        assert path.parent == tmp_path
        # tmp_safe_name of a bare prefix under cwd falls back to basename.
        assert path.name.endswith("_s1_openai.progress")

    def test_st_cross_and_st_fact_agree(self, st_cross_mod, tmp_path, monkeypatch):
        """st-cross.py _read_progress and the helper must target the same
        file. This closes Finding 7 (path construction was duplicated)."""
        import mmd_util
        monkeypatch.setattr(mmd_util, "get_tmp_dir", lambda: tmp_path)
        # Write via the helper (st-fact side).
        mmd_util.progress_file_path("pfx", 4, "gemini").write_text("9/12")
        # Read via st-cross side — si=3 because _read_progress adds +1.
        assert st_cross_mod._read_progress("pfx", 3, "gemini") == "9/12"


# ─────────────────────────────────────────────────────────────────────────────
# _stories_complete — auto-skip detection for Step 1
# ─────────────────────────────────────────────────────────────────────────────

class TestStoriesComplete:
    """Verify auto-skip detection across missing/partial/complete containers."""

    def test_missing_file_returns_false(self, st_cross_mod, tmp_path):
        missing = tmp_path / "nope.json"
        assert st_cross_mod._stories_complete(str(missing), ["openai"]) is False

    def test_malformed_json_returns_false(self, st_cross_mod, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json")
        assert st_cross_mod._stories_complete(str(path), ["openai"]) is False

    def test_empty_story_list_returns_false(self, st_cross_mod, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text(json.dumps({"data": [], "story": []}))
        assert st_cross_mod._stories_complete(str(path), ["openai", "xai"]) is False

    def test_missing_one_make_returns_false(self, st_cross_mod, tmp_path):
        path = tmp_path / "partial.json"
        path.write_text(json.dumps({
            "data": [],
            "story": [{"make": "openai"}, {"make": "xai"}],
        }))
        # anthropic is needed but absent
        assert st_cross_mod._stories_complete(
            str(path), ["openai", "xai", "anthropic"]) is False

    def test_all_makes_present_returns_true(self, st_cross_mod, tmp_path):
        path = tmp_path / "full.json"
        path.write_text(json.dumps({
            "data": [],
            "story": [{"make": "openai"}, {"make": "xai"}],
        }))
        assert st_cross_mod._stories_complete(str(path), ["openai", "xai"]) is True

    def test_superset_in_container_still_true(self, st_cross_mod, tmp_path):
        """Extra stories in the container don't block the skip decision."""
        path = tmp_path / "super.json"
        path.write_text(json.dumps({
            "data": [],
            "story": [
                {"make": "openai"}, {"make": "xai"}, {"make": "gemini"},
            ],
        }))
        assert st_cross_mod._stories_complete(str(path), ["openai", "xai"]) is True

    def test_empty_ai_list_returns_true(self, st_cross_mod, tmp_path):
        """Degenerate case: needed set is empty → trivially a subset."""
        path = tmp_path / "any.json"
        path.write_text(json.dumps({"data": [], "story": []}))
        assert st_cross_mod._stories_complete(str(path), []) is True


# ─────────────────────────────────────────────────────────────────────────────
# _ensure_segments — pre-build story segments before Step 2
# ─────────────────────────────────────────────────────────────────────────────

class TestEnsureSegments:
    """Verify segment pre-build across missing/empty/populated stories."""

    def _write(self, path: Path, container: dict) -> None:
        path.write_text(json.dumps(container), encoding="utf-8")

    def _load(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_missing_file_noop(self, st_cross_mod, tmp_path, capsys):
        """No file → returns silently without crashing."""
        st_cross_mod._ensure_segments(str(tmp_path / "nope.json"), 3, quiet=True)
        # Nothing should be written.
        assert not (tmp_path / "nope.json").exists()

    def test_malformed_json_noop(self, st_cross_mod, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        original = path.read_text()
        st_cross_mod._ensure_segments(str(path), 3, quiet=True)
        # File preserved untouched
        assert path.read_text() == original

    def test_builds_segments_when_absent(self, st_cross_mod, tmp_path):
        path = tmp_path / "c.json"
        self._write(path, {
            "data": [],
            "story": [{"make": "openai",
                       "text": "First sentence. Second sentence here."}],
        })
        st_cross_mod._ensure_segments(str(path), 1, quiet=True)
        c = self._load(path)
        segs = c["story"][0]["segments"]
        assert isinstance(segs, list) and len(segs) > 0

    def test_preserves_existing_segments(self, st_cross_mod, tmp_path):
        path = tmp_path / "c.json"
        existing = [{"text": "already built", "index": 0}]
        self._write(path, {
            "data": [],
            "story": [{"make": "openai", "text": "Ignored.", "segments": existing}],
        })
        st_cross_mod._ensure_segments(str(path), 1, quiet=True)
        c = self._load(path)
        assert c["story"][0]["segments"] == existing  # untouched

    def test_skips_story_with_no_text(self, st_cross_mod, tmp_path):
        path = tmp_path / "c.json"
        self._write(path, {
            "data": [],
            "story": [{"make": "openai", "text": ""}],
        })
        st_cross_mod._ensure_segments(str(path), 1, quiet=True)
        c = self._load(path)
        # Either absent or empty — never populated from empty text.
        assert not c["story"][0].get("segments")

    def test_respects_n_stories_limit(self, st_cross_mod, tmp_path):
        """Only the first n_stories entries are processed."""
        path = tmp_path / "c.json"
        self._write(path, {
            "data": [],
            "story": [
                {"make": "a", "text": "First report content."},
                {"make": "b", "text": "Second report content."},
                {"make": "c", "text": "Third report content."},
            ],
        })
        st_cross_mod._ensure_segments(str(path), 2, quiet=True)
        c = self._load(path)
        assert c["story"][0].get("segments")
        assert c["story"][1].get("segments")
        # Story index 2 should not have been touched.
        assert not c["story"][2].get("segments")

    def test_no_changes_means_no_write(self, st_cross_mod, tmp_path):
        """When nothing needs building, file mtime is not bumped."""
        path = tmp_path / "c.json"
        self._write(path, {"data": [], "story": []})
        mtime_before = path.stat().st_mtime
        # Give the filesystem a tick so a spurious rewrite would be observable
        time.sleep(0.01)
        st_cross_mod._ensure_segments(str(path), 5, quiet=True)
        assert path.stat().st_mtime == mtime_before

    def test_quiet_suppresses_stdout(self, st_cross_mod, tmp_path, capsys):
        path = tmp_path / "c.json"
        self._write(path, {
            "data": [],
            "story": [{"make": "openai", "text": "A sentence. Another."}],
        })
        st_cross_mod._ensure_segments(str(path), 1, quiet=True)
        captured = capsys.readouterr()
        assert "Segments built" not in captured.out

    def test_verbose_prints_count(self, st_cross_mod, tmp_path, capsys):
        path = tmp_path / "c.json"
        self._write(path, {
            "data": [],
            "story": [{"make": "openai", "text": "A sentence. Another."}],
        })
        st_cross_mod._ensure_segments(str(path), 1, quiet=False)
        captured = capsys.readouterr()
        assert "Segments built" in captured.out

    def test_atomic_write_removes_tmp(self, st_cross_mod, tmp_path):
        """The .tmp sibling must not survive the atomic rename."""
        path = tmp_path / "c.json"
        self._write(path, {
            "data": [],
            "story": [{"make": "openai", "text": "Text here."}],
        })
        st_cross_mod._ensure_segments(str(path), 1, quiet=True)
        assert not (tmp_path / "c.json.tmp").exists()


# ─────────────────────────────────────────────────────────────────────────────
# _read_progress — reads n/total from st-fact's progress file
# ─────────────────────────────────────────────────────────────────────────────

class TestReadProgress:
    def test_missing_file_returns_empty(self, st_cross_mod, tmp_path, monkeypatch):
        # Redirect get_tmp_dir() in mmd_util (progress_file_path resolves it
        # from there, not from st_cross_mod's own namespace).
        import mmd_util
        monkeypatch.setattr(mmd_util, "get_tmp_dir", lambda: tmp_path)
        assert st_cross_mod._read_progress("nope", 0, "openai") == ""

    def test_reads_and_strips_value(self, st_cross_mod, tmp_path, monkeypatch):
        import mmd_util
        monkeypatch.setattr(mmd_util, "get_tmp_dir", lambda: tmp_path)
        safe = st_cross_mod.tmp_safe_name("myprefix")
        (tmp_path / f"{safe}_s1_openai.progress").write_text("  17/47  \n")
        assert st_cross_mod._read_progress("myprefix", 0, "openai") == "17/47"

    def test_story_index_is_one_based_in_filename(self, st_cross_mod, tmp_path, monkeypatch):
        """si=2 must read the file named with s3 (si+1)."""
        import mmd_util
        monkeypatch.setattr(mmd_util, "get_tmp_dir", lambda: tmp_path)
        safe = st_cross_mod.tmp_safe_name("pfx")
        (tmp_path / f"{safe}_s3_xai.progress").write_text("5/10")
        assert st_cross_mod._read_progress("pfx", 2, "xai") == "5/10"


# ─────────────────────────────────────────────────────────────────────────────
# _fmt — mm:ss formatter
# ─────────────────────────────────────────────────────────────────────────────

class TestFmt:
    def test_zero(self, st_cross_mod):
        assert st_cross_mod._fmt(0) == "00:00"

    def test_under_one_minute(self, st_cross_mod):
        assert st_cross_mod._fmt(42) == "00:42"

    def test_exact_minute(self, st_cross_mod):
        assert st_cross_mod._fmt(60) == "01:00"

    def test_minutes_and_seconds(self, st_cross_mod):
        assert st_cross_mod._fmt(125) == "02:05"

    def test_truncates_fractional_seconds(self, st_cross_mod):
        assert st_cross_mod._fmt(12.9) == "00:12"

    def test_over_one_hour_stays_mm_ss(self, st_cross_mod):
        """By design: minutes accumulate past 60 without rolling to hours."""
        assert st_cross_mod._fmt(3661) == "61:01"


# ─────────────────────────────────────────────────────────────────────────────
# _draw_cross_table — smoke test rendering across cell statuses
# ─────────────────────────────────────────────────────────────────────────────

class TestDrawCrossTable:
    """Render the N×N table to a captured stdout and check basic structure.

    We don't assert full ANSI output — only that the call succeeds, prints
    something sensible, and returns a plausible row count.
    """

    def _make_cells(self, st_cross_mod, n: int, status_grid):
        """Build a cells dict with explicit per-cell status. status_grid is a
        list of lists, each inner list of length n giving the status for that
        row. Times are synthesised so that RUNNING/DONE/FAILED cells have
        start_time set, others remain None."""
        now = time.time()
        cells = {}
        for si in range(n):
            for fi in range(n):
                s = status_grid[si][fi]
                cell = {"status": s, "start_time": None, "end_time": None}
                if s == st_cross_mod.ST_RUNNING:
                    cell["start_time"] = now - 5.0
                elif s == st_cross_mod.ST_DONE:
                    cell["start_time"] = now - 10.0
                    cell["end_time"]   = now - 1.0
                elif s == st_cross_mod.ST_FAILED:
                    cell["start_time"] = now - 8.0
                    cell["end_time"]   = now - 2.0
                cells[(si, fi)] = cell
        return cells

    def test_first_draw_returns_positive_row_count(self, st_cross_mod, capsys):
        ai_list = ["openai", "xai"]
        n = len(ai_list)
        cells = self._make_cells(st_cross_mod, n, [
            [st_cross_mod.ST_DONE,    st_cross_mod.ST_RUNNING],
            [st_cross_mod.ST_PENDING, st_cross_mod.ST_FAILED],
        ])
        rows = st_cross_mod._draw_cross_table(
            cells, ai_list, "fileprefix",
            first_draw=True, row_count=0, timeout=0,
        )
        assert rows > 5  # header + divider + N rows + totals + footer
        out = capsys.readouterr().out
        # Column headers include each AI make.
        assert "openai" in out and "xai" in out
        # Footer is present.
        assert "Ctrl+C" in out

    def test_all_pending_renders_dashes(self, st_cross_mod, capsys):
        ai_list = ["openai", "xai"]
        n = len(ai_list)
        cells = self._make_cells(st_cross_mod, n,
                                  [[st_cross_mod.ST_PENDING] * n for _ in range(n)])
        st_cross_mod._draw_cross_table(
            cells, ai_list, "pfx",
            first_draw=True, row_count=0, timeout=1800,
        )
        out = capsys.readouterr().out
        assert "--:--" in out            # pending placeholder
        assert "timeout" in out           # timeout label rendered

    def test_no_timeout_label_rendered(self, st_cross_mod, capsys):
        ai_list = ["openai"]
        cells = self._make_cells(st_cross_mod, 1,
                                  [[st_cross_mod.ST_PENDING]])
        st_cross_mod._draw_cross_table(
            cells, ai_list, "pfx",
            first_draw=True, row_count=0, timeout=0,
        )
        out = capsys.readouterr().out
        assert "no timeout" in out

    def test_prior_cells_dont_break_total(self, st_cross_mod, capsys):
        """Cells pre-loaded from disk (start==end==0) are excluded from Σ totals
        without crashing."""
        ai_list = ["openai", "xai"]
        cells = {
            (0, 0): {"status": st_cross_mod.ST_DONE,
                     "start_time": 0.0, "end_time": 0.0},   # prior
            (0, 1): {"status": st_cross_mod.ST_PENDING,
                     "start_time": None, "end_time": None},
            (1, 0): {"status": st_cross_mod.ST_PENDING,
                     "start_time": None, "end_time": None},
            (1, 1): {"status": st_cross_mod.ST_PENDING,
                     "start_time": None, "end_time": None},
        }
        st_cross_mod._draw_cross_table(
            cells, ai_list, "pfx",
            first_draw=True, row_count=0, timeout=0,
        )
        out = capsys.readouterr().out
        assert "prior" in out             # the "✓ prior" label shows
        assert "Σ" in out                 # totals row rendered


# ─────────────────────────────────────────────────────────────────────────────
# _draw_gen_table — Step-1 progress bar
# ─────────────────────────────────────────────────────────────────────────────

class TestDrawGenTable:
    def _make_jobs(self, st_cross_mod, makes_and_statuses):
        now = time.time()
        jobs = []
        for i, (make, status) in enumerate(makes_and_statuses):
            j = {"index": i, "make": make, "status": status,
                 "start_time": None, "end_time": None}
            if status in (st_cross_mod.ST_RUNNING,
                          st_cross_mod.ST_DONE,
                          st_cross_mod.ST_WARNED,
                          st_cross_mod.ST_FAILED):
                j["start_time"] = now - 3.0
            if status in (st_cross_mod.ST_DONE,
                          st_cross_mod.ST_WARNED,
                          st_cross_mod.ST_FAILED):
                j["end_time"] = now - 0.5
            jobs.append(j)
        return jobs

    def test_renders_headers_and_cells(self, st_cross_mod, capsys):
        jobs = self._make_jobs(st_cross_mod, [
            ("openai", st_cross_mod.ST_DONE),
            ("xai",    st_cross_mod.ST_RUNNING),
            ("gemini", st_cross_mod.ST_PENDING),
        ])
        rows = st_cross_mod._draw_gen_table(jobs, first_draw=True, row_count=0)
        assert rows >= 5  # header, divider, ai row, cell row, divider, footer
        out = capsys.readouterr().out
        assert "Step 1" in out
        for make in ("openai", "xai", "gemini"):
            assert make in out

    def test_failed_status_renders(self, st_cross_mod, capsys):
        jobs = self._make_jobs(st_cross_mod, [("openai", st_cross_mod.ST_FAILED)])
        st_cross_mod._draw_gen_table(jobs, first_draw=True, row_count=0)
        out = capsys.readouterr().out
        assert "✗" in out

    def test_warned_status_renders(self, st_cross_mod, capsys):
        jobs = self._make_jobs(st_cross_mod, [("xai", st_cross_mod.ST_WARNED)])
        st_cross_mod._draw_gen_table(jobs, first_draw=True, row_count=0)
        out = capsys.readouterr().out
        assert "~" in out




