"""
tests/test_st_cross.py — PAR-1 unit tests for cross_st/st-cross.py

Covers the per-provider rate-limit semaphore registry and CLI surface added
by PAR-1 (`--parallel`, `--sequential`, `--max-concurrency`, `--retry-budget`).
The cell-execution loop is *not* exercised here — running real `st-fact`
subprocesses across the matrix would take 30+ minutes; that is covered by
`script/smoke_test.sh` post-release.
"""
import importlib.util
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



