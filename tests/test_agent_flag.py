"""
tests/test_agent_flag.py — Verify that every st-* script uses --agent (not --ai)
as the agent-selector CLI flag (AGT-3 contract).

WHY THIS EXISTS
---------------
The AGT-series renames the agent-selector flag from ``--ai`` to ``--agent``
across all 29 entry-point scripts.  ``--ai-title``, ``--ai-short``, etc. are
*content-type* flags and are intentionally kept as-is.

This test catches:
  1. Any script that still registers ``--ai`` as an agent-selector argument.
  2. Any script (from the expected set) that has not yet grown a ``--agent``
     argument.

WHAT IS TESTED
--------------
Source-file scan only — no subprocesses, no imports.  Fast enough to run in
the default (non-``--slow``) pytest sweep.

Pattern matched as "agent-selector --ai":
  ``add_argument(... '--ai' ...)``  where the string ``'--ai'`` is NOT
  immediately followed by ``-`` (which would make it ``'--ai-title'`` etc.).

HOW IT FAILS RIGHT NOW
----------------------
Until AGT-3 is implemented every script in SCRIPTS_WITH_AGENT_FLAG will fail
assertion 1 (still has ``--ai``) and assertion 2 (does not yet have
``--agent``).  That is intentional — this test is the acceptance gate.

SCRIPTS THAT DO NOT NEED --agent
---------------------------------
  st-admin   — manages agents; does not call one for content generation
  st-cat     — display only
  st-cross   — iterates the full agent list automatically; no single-agent flag
  st-edit    — editor launcher
  st-fetch   — URL / PDF fetch; no AI call
  st-find    — search
  st-ls      — listing
  st-man     — help viewer
  st-post    — Discourse publisher
  st-prep    — pre-processing
  st-print   — PDF renderer
  st-read    — plain text viewer
  st-rm      — removal
  st-speak   — TTS (no agent selection)
  st-stones  — benchmark runner (iterates all agents)
  st-voice   — voice config
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_SCRIPTS_DIR = _ROOT / "cross_st"

# ── Scripts that MUST have --agent and must NOT have a bare --ai ──────────────
# These are the scripts that accept a single agent/model choice from the user.
SCRIPTS_WITH_AGENT_FLAG = [
    "st-analyze",
    "st-bang",
    "st-domain",
    "st-fact",
    "st-fix",
    "st-gen",
    "st-heatmap",
    "st-merge",
    "st-new",
    "st-plot",
    "st-speed",
    "st-verdict",
]

# Regex: add_argument call that registers '--ai' as an agent-selector.
# Matches:  add_argument('--ai', ...)  or  add_argument("-a", '--ai', ...)
# Does NOT match: '--ai-title', '--ai-short', '--ai-caption', etc.
_RE_AI_FLAG = re.compile(r"""add_argument\s*\(.*?['"]--ai['"](?!-)""")

# Regex: add_argument call that registers '--agent'.
_RE_AGENT_FLAG = re.compile(r"""add_argument\s*\(.*?['"]--agent['"]""")


def _source(script_name: str) -> str:
    path = _SCRIPTS_DIR / f"{script_name}.py"
    assert path.exists(), f"Script not found: {path}"
    return path.read_text(encoding="utf-8")


# ── Test 1: no script retains the old bare --ai agent-selector ────────────────

@pytest.mark.parametrize("script", SCRIPTS_WITH_AGENT_FLAG)
def test_no_bare_ai_flag(script):
    """The old ``--ai`` agent-selector must not appear in add_argument() calls.

    ``--ai-title``, ``--ai-short`` etc. are content-type flags and are exempt
    (the regex does not match them).
    """
    source = _source(script)
    matches = [
        line.strip()
        for line in source.splitlines()
        if _RE_AI_FLAG.search(line)
    ]
    assert not matches, (
        f"{script}.py still registers '--ai' as an agent-selector.\n"
        f"Rename it to '--agent' (AGT-3).\n"
        f"Offending lines:\n" + "\n".join(f"  {m}" for m in matches)
    )


# ── Test 2: expected scripts all have --agent ─────────────────────────────────

@pytest.mark.parametrize("script", SCRIPTS_WITH_AGENT_FLAG)
def test_has_agent_flag(script):
    """Every script that selects an agent must register ``--agent``."""
    source = _source(script)
    assert _RE_AGENT_FLAG.search(source), (
        f"{script}.py has no '--agent' argument.\n"
        f"Add:  parser.add_argument('--agent', ...) (AGT-3)."
    )


# ── Test 3: scripts that should NOT have --agent don't accidentally get it ────
# This test is purely defensive — catches copy-paste sprawl.

_ALL_SCRIPTS = [p.stem for p in _SCRIPTS_DIR.glob("st-*.py")]
_SCRIPTS_WITHOUT_AGENT_FLAG = [
    s for s in _ALL_SCRIPTS if s not in SCRIPTS_WITH_AGENT_FLAG
]


@pytest.mark.parametrize("script", _SCRIPTS_WITHOUT_AGENT_FLAG)
def test_unexpected_agent_flag(script):
    """Scripts not in SCRIPTS_WITH_AGENT_FLAG must not register '--agent'.

    If a new script genuinely needs agent selection, add it to
    SCRIPTS_WITH_AGENT_FLAG above.
    """
    source = _source(script)
    assert not _RE_AGENT_FLAG.search(source), (
        f"{script}.py unexpectedly registers '--agent'.\n"
        f"If this is intentional, add '{script}' to SCRIPTS_WITH_AGENT_FLAG "
        f"in tests/test_agent_flag.py."
    )

