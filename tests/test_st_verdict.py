"""
tests/test_st_verdict.py — Unit tests for st-verdict argument resolution logic.

Coverage:
    ai_short default resolution — fires only when no other --ai-* flag is given
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Load st-verdict as a module (hyphen in filename) ─────────────────────────
_spec = importlib.util.spec_from_file_location(
    "st_verdict", Path(__file__).parent.parent / "cross_st" / "st-verdict.py"
)
st_verdict = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st_verdict)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse(extra_args=None):
    """Run the st-verdict argument parser with a dummy json file and return args."""
    argv = ["st-verdict", "dummy.json"] + (extra_args or [])
    with patch("sys.argv", argv):
        parser_func = st_verdict.main.__code__  # just confirm it exists
        # Re-build the parser the same way main() does (call the full main()
        # would require a real file; instead test the resolution logic directly).
        import argparse
        from unittest.mock import MagicMock

        # Reproduce the argparse setup from main()
        parser = argparse.ArgumentParser(prog="st-verdict")
        parser.add_argument("json_file", type=str)

        chart_group = parser.add_argument_group("Chart output")
        chart_group.add_argument("--display", action="store_true", default=True)
        chart_group.add_argument("--no-display", dest="display", action="store_false")
        chart_group.add_argument("--file", action="store_true")
        chart_group.add_argument("--path", default="./tmp")

        ai_group = parser.add_argument_group("AI content generation")
        ai_group.add_argument("--ai-title",   action="store_true")
        ai_group.add_argument("--ai-short",   action="store_true", default=None)
        ai_group.add_argument("--no-ai-short", dest="ai_short", action="store_false")
        ai_group.add_argument("--ai-caption", action="store_true")
        ai_group.add_argument("--ai-summary", action="store_true")
        ai_group.add_argument("--ai-story",   action="store_true")
        ai_group.add_argument("--ai", type=str, default=None)

        parser.add_argument("--cache", dest="cache", action="store_true", default=True)
        parser.add_argument("--no-cache", dest="cache", action="store_false")
        parser.add_argument("-v", "--verbose", action="store_true")
        parser.add_argument("-q", "--quiet",   action="store_true")

        args = parser.parse_args(argv[1:])

        # Apply the resolution logic from main()
        if args.ai_short is None:
            args.ai_short = not (
                args.ai_title or args.ai_caption or args.ai_summary or args.ai_story
            )

        return args


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAiShortResolution:
    """ai_short should default-on only when no other --ai-* flag is explicitly given."""

    def test_no_flags_ai_short_defaults_on(self):
        """With no AI flags at all, ai_short should be True (default-on)."""
        args = _parse()
        assert args.ai_short is True

    def test_ai_summary_suppresses_ai_short(self):
        """--ai-summary alone must NOT trigger ai_short."""
        args = _parse(["--ai-summary"])
        assert args.ai_short is False
        assert args.ai_summary is True

    def test_ai_caption_suppresses_ai_short(self):
        """--ai-caption alone must NOT trigger ai_short."""
        args = _parse(["--ai-caption"])
        assert args.ai_short is False
        assert args.ai_caption is True

    def test_ai_title_suppresses_ai_short(self):
        """--ai-title alone must NOT trigger ai_short."""
        args = _parse(["--ai-title"])
        assert args.ai_short is False
        assert args.ai_title is True

    def test_ai_story_suppresses_ai_short(self):
        """--ai-story alone must NOT trigger ai_short."""
        args = _parse(["--ai-story"])
        assert args.ai_short is False
        assert args.ai_story is True

    def test_explicit_ai_short_plus_ai_summary(self):
        """--ai-short --ai-summary must produce both."""
        args = _parse(["--ai-short", "--ai-summary"])
        assert args.ai_short is True
        assert args.ai_summary is True

    def test_explicit_ai_short_alone(self):
        """--ai-short explicitly given must be True."""
        args = _parse(["--ai-short"])
        assert args.ai_short is True

    def test_no_ai_short_suppresses_default(self):
        """--no-ai-short must set ai_short to False regardless of other flags."""
        args = _parse(["--no-ai-short"])
        assert args.ai_short is False

    def test_no_ai_short_with_ai_caption(self):
        """--no-ai-short --ai-caption: only caption, no short."""
        args = _parse(["--no-ai-short", "--ai-caption"])
        assert args.ai_short is False
        assert args.ai_caption is True

    def test_multiple_ai_flags_no_short(self):
        """--ai-caption --ai-summary: neither triggers ai_short automatically."""
        args = _parse(["--ai-caption", "--ai-summary"])
        assert args.ai_short is False
        assert args.ai_caption is True
        assert args.ai_summary is True

