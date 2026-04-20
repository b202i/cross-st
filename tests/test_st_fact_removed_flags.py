"""tests/test_st_fact_removed_flags.py — VRD-5 regression coverage.

In cross-st 0.7.0 the interpretive `--ai-*` flags were removed from
`st-fact` and migrated to `st-verdict` (see VRD-2/3/5).  `st-fact.py`
catches each removed flag *before* argparse sees it and prints a
friendly migration message + exits 2.

These tests guard the migration message so a future refactor cannot
silently drop the deprecation guidance.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_SCRIPT = _ROOT / "cross_st" / "st-fact.py"

_REMOVED_FLAGS = [
    "--ai-title",
    "--ai-short",
    "--no-ai-short",
    "--ai-caption",
    "--ai-summary",
    "--ai-story",
    "--ai-review",
]


@pytest.fixture(scope="module")
def fake_home(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    (home / ".crossenv").write_text("DEFAULT_AI=xai\n")
    return home


@pytest.mark.slow
@pytest.mark.parametrize("flag", _REMOVED_FLAGS)
def test_removed_flag_exits_with_migration_message(flag, fake_home, tmp_path):
    """Each removed flag must exit 2 with a stderr pointer to st-verdict."""
    dummy_json = tmp_path / "dummy.json"
    dummy_json.write_text("{}")

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), flag, str(dummy_json)],
        capture_output=True,
        text=True,
        timeout=15,
        env={
            "HOME": str(fake_home),
            "PATH": "/usr/bin:/bin",
        },
    )

    assert result.returncode == 2, (
        f"`st-fact {flag}` should exit 2; got {result.returncode}.\n"
        f"stdout: {result.stdout[:300]}\nstderr: {result.stderr[:300]}"
    )
    assert "removed from st-fact" in result.stderr, (
        f"stderr should mention removal; got: {result.stderr[:300]}"
    )
    assert "st-verdict" in result.stderr, (
        f"stderr should redirect users to st-verdict; got: {result.stderr[:300]}"
    )
    assert "Traceback" not in result.stderr

