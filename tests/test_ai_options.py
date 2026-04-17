"""
tests/test_ai_options.py — Tests for the AI content-generation options added to
st-analyze, st-merge, and st-gen:
  --ai-title / --ai-short / --ai-caption / --ai-summary / --ai-story

Coverage:
    _build_story_ai_prompt   — prompt text for each content type
    _run_story_ai_content    — dispatch loop, process_prompt integration
    argparse acceptance      — each command accepts all five flags
"""

import argparse
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Load the three scripts as importable modules ──────────────────────────────

def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"),
        Path(__file__).parent.parent / "cross_st" / f"{name}.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


st_analyze = _load("st-analyze")
st_merge   = _load("st-merge")
st_gen     = _load("st-gen")


# ── Shared fixture: a fake args namespace ─────────────────────────────────────

def _args(**flags):
    """Return an argparse.Namespace with all AI option flags set."""
    defaults = dict(
        ai_title=False,
        ai_short=False,
        ai_caption=False,
        ai_summary=False,
        ai_story=False,
        ai="xai",
        cache=True,
        quiet=False,
        verbose=False,
    )
    defaults.update(flags)
    return argparse.Namespace(**defaults)


# ── _build_story_ai_prompt ────────────────────────────────────────────────────

class TestBuildStoryAiPrompt:
    """_build_story_ai_prompt produces correctly shaped prompts for all types."""

    # Use the function from any one of the three scripts (they are identical).
    build = staticmethod(st_analyze._build_story_ai_prompt)

    CONTEXT = "ARTICLE TITLE: Test Title\n\nARTICLE TEXT:\nSome article text here."

    def test_title_contains_max_10_words(self):
        prompt = self.build(self.CONTEXT, "title")
        assert "10 words" in prompt or "Max 10" in prompt

    def test_title_includes_context(self):
        prompt = self.build(self.CONTEXT, "title")
        assert "Test Title" in prompt

    def test_short_contains_80_words_limit(self):
        prompt = self.build(self.CONTEXT, "short")
        assert "80 words" in prompt

    def test_short_includes_context(self):
        prompt = self.build(self.CONTEXT, "short")
        assert "Some article text" in prompt

    def test_caption_word_range(self):
        prompt = self.build(self.CONTEXT, "caption")
        assert "100" in prompt and "160" in prompt

    def test_caption_two_paragraphs(self):
        prompt = self.build(self.CONTEXT, "caption")
        assert "2 paragraphs" in prompt or "Paragraph 1" in prompt

    def test_summary_word_range(self):
        prompt = self.build(self.CONTEXT, "summary")
        assert "120" in prompt and "200" in prompt

    def test_summary_has_paragraph_structure(self):
        prompt = self.build(self.CONTEXT, "summary")
        assert "Paragraph 1" in prompt

    def test_story_word_range(self):
        prompt = self.build(self.CONTEXT, "story")
        assert "800" in prompt and "1200" in prompt

    def test_story_has_structure_heading(self):
        prompt = self.build(self.CONTEXT, "story")
        assert "STRUCTURE" in prompt or "Introduction" in prompt

    def test_unknown_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown content_type"):
            self.build(self.CONTEXT, "nonsense")

    def test_context_separator_present(self):
        """A separator (---) must appear between context and instruction."""
        prompt = self.build(self.CONTEXT, "caption")
        assert "---" in prompt

    def test_all_types_include_article_text(self):
        for ctype in ("title", "short", "caption", "summary", "story"):
            prompt = self.build(self.CONTEXT, ctype)
            assert "Some article text" in prompt, f"Context missing from '{ctype}' prompt"

    # Confirm identical implementations across all three scripts
    def test_analyze_and_merge_identical(self):
        ctx = "ARTICLE TITLE: X\n\nARTICLE TEXT:\nY"
        for ctype in ("title", "short", "caption", "summary", "story"):
            assert (st_analyze._build_story_ai_prompt(ctx, ctype) ==
                    st_merge._build_story_ai_prompt(ctx, ctype)), \
                f"Mismatch for '{ctype}'"

    def test_analyze_and_gen_identical(self):
        ctx = "ARTICLE TITLE: X\n\nARTICLE TEXT:\nY"
        for ctype in ("title", "short", "caption", "summary", "story"):
            assert (st_analyze._build_story_ai_prompt(ctx, ctype) ==
                    st_gen._build_story_ai_prompt(ctx, ctype)), \
                f"Mismatch for '{ctype}'"


# ── _run_story_ai_content ─────────────────────────────────────────────────────

class TestRunStoryAiContent:
    """_run_story_ai_content dispatches correctly and prints AI output."""

    STORY_TEXT  = "The article body."
    STORY_TITLE = "My Article"

    def _fake_result(self, text):
        """Return a 4-tuple that mimics process_prompt's return value."""
        mock_response = MagicMock()
        # get_content is called on the response; patch it globally
        return (None, None, mock_response, "grok-test"), text

    def test_no_flags_no_calls(self, capsys):
        """With no AI flags set, process_prompt must not be called."""
        args = _args()
        with patch.object(st_analyze, "process_prompt") as mock_pp:
            st_analyze._run_story_ai_content(args, self.STORY_TEXT, self.STORY_TITLE, "xai")
        mock_pp.assert_not_called()

    def test_ai_title_calls_process_prompt(self, capsys):
        args = _args(ai_title=True)
        with patch.object(st_analyze, "process_prompt") as mock_pp, \
             patch.object(st_analyze, "get_content_auto", return_value="My Title"):
            mock_pp.return_value = (None, None, MagicMock(), "model")
            st_analyze._run_story_ai_content(args, self.STORY_TEXT, self.STORY_TITLE, "xai")
        mock_pp.assert_called_once()

    def test_ai_title_printed_to_stdout(self, capsys):
        args = _args(ai_title=True)
        with patch.object(st_analyze, "process_prompt") as mock_pp, \
             patch.object(st_analyze, "get_content_auto", return_value="My Title"):
            mock_pp.return_value = (None, None, MagicMock(), "model")
            st_analyze._run_story_ai_content(args, self.STORY_TEXT, self.STORY_TITLE, "xai")
        captured = capsys.readouterr()
        assert "My Title" in captured.out

    def test_multiple_flags_multiple_calls(self):
        args = _args(ai_title=True, ai_short=True, ai_caption=True)
        with patch.object(st_analyze, "process_prompt") as mock_pp, \
             patch.object(st_analyze, "get_content_auto", return_value="text"):
            mock_pp.return_value = (None, None, MagicMock(), "model")
            st_analyze._run_story_ai_content(args, self.STORY_TEXT, self.STORY_TITLE, "xai")
        assert mock_pp.call_count == 3

    def test_labels_printed_when_not_quiet(self, capsys):
        args = _args(ai_caption=True)
        with patch.object(st_analyze, "process_prompt") as mock_pp, \
             patch.object(st_analyze, "get_content_auto", return_value="cap text"):
            mock_pp.return_value = (None, None, MagicMock(), "model")
            st_analyze._run_story_ai_content(args, self.STORY_TEXT, self.STORY_TITLE, "xai")
        out = capsys.readouterr().out
        assert "Caption" in out
        assert "─" * 10 in out  # separator

    def test_quiet_suppresses_labels(self, capsys):
        args = _args(ai_short=True, quiet=True)
        with patch.object(st_analyze, "process_prompt") as mock_pp, \
             patch.object(st_analyze, "get_content_auto", return_value="short text"):
            mock_pp.return_value = (None, None, MagicMock(), "model")
            st_analyze._run_story_ai_content(args, self.STORY_TEXT, self.STORY_TITLE, "xai")
        out = capsys.readouterr().out
        # content still printed, label/separator suppressed
        assert "short text" in out
        assert "Short Summary" not in out

    def test_exception_prints_error_not_raises(self, capsys):
        args = _args(ai_summary=True)
        with patch.object(st_analyze, "process_prompt", side_effect=RuntimeError("boom")):
            # Must not raise
            st_analyze._run_story_ai_content(args, self.STORY_TEXT, self.STORY_TITLE, "xai")
        out = capsys.readouterr().out
        assert "boom" in out or "Generation failed" in out

    def test_cache_flag_forwarded(self):
        args = _args(ai_title=True, cache=False)
        with patch.object(st_analyze, "process_prompt") as mock_pp, \
             patch.object(st_analyze, "get_content_auto", return_value="t"):
            mock_pp.return_value = (None, None, MagicMock(), "model")
            st_analyze._run_story_ai_content(args, self.STORY_TEXT, self.STORY_TITLE, "xai")
        _, kwargs = mock_pp.call_args
        assert kwargs.get("use_cache") is False


# ── Argparse acceptance tests ─────────────────────────────────────────────────

def _make_analyze_parser():
    """Reproduce the argparse setup from st-analyze.main()."""
    parser = argparse.ArgumentParser(prog="st-analyze")
    parser.add_argument("json_file")
    parser.add_argument("--ai", default="xai")
    parser.add_argument("--cache", dest="cache", action="store_true", default=True)
    parser.add_argument("--no-cache", dest="cache", action="store_false")
    parser.add_argument("--site", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    ai_group = parser.add_argument_group("AI content generation")
    ai_group.add_argument("--ai-title",   action="store_true")
    ai_group.add_argument("--ai-short",   action="store_true")
    ai_group.add_argument("--ai-caption", action="store_true")
    ai_group.add_argument("--ai-summary", action="store_true")
    ai_group.add_argument("--ai-story",   action="store_true")
    return parser


def _make_merge_parser():
    parser = argparse.ArgumentParser(prog="st-merge")
    parser.add_argument("json_file")
    parser.add_argument("--ai", default="xai")
    parser.add_argument("--cache", dest="cache", action="store_true", default=True)
    parser.add_argument("--no-cache", dest="cache", action="store_false")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    ai_group = parser.add_argument_group("AI content generation")
    ai_group.add_argument("--ai-title",   action="store_true")
    ai_group.add_argument("--ai-short",   action="store_true")
    ai_group.add_argument("--ai-caption", action="store_true")
    ai_group.add_argument("--ai-summary", action="store_true")
    ai_group.add_argument("--ai-story",   action="store_true")
    return parser


def _make_gen_parser():
    parser = argparse.ArgumentParser(prog="st-gen")
    parser.add_argument("prompt", nargs="?")
    parser.add_argument("--ai", default="xai")
    parser.add_argument("--cache", dest="cache", action="store_true", default=True)
    parser.add_argument("--no-cache", dest="cache", action="store_false")
    parser.add_argument("--bang", type=int, default=-1)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    ai_group = parser.add_argument_group("AI content generation")
    ai_group.add_argument("--ai-title",   action="store_true")
    ai_group.add_argument("--ai-short",   action="store_true")
    ai_group.add_argument("--ai-caption", action="store_true")
    ai_group.add_argument("--ai-summary", action="store_true")
    ai_group.add_argument("--ai-story",   action="store_true")
    return parser


class TestArgParseAnalyze:
    """st-analyze accepts all five AI content flags."""

    def _parse(self, extra):
        return _make_analyze_parser().parse_args(["dummy.json"] + extra)

    def test_no_flags_all_false(self):
        args = self._parse([])
        assert not any([args.ai_title, args.ai_short, args.ai_caption,
                        args.ai_summary, args.ai_story])

    def test_ai_title_accepted(self):
        assert self._parse(["--ai-title"]).ai_title is True

    def test_ai_short_accepted(self):
        assert self._parse(["--ai-short"]).ai_short is True

    def test_ai_caption_accepted(self):
        assert self._parse(["--ai-caption"]).ai_caption is True

    def test_ai_summary_accepted(self):
        assert self._parse(["--ai-summary"]).ai_summary is True

    def test_ai_story_accepted(self):
        assert self._parse(["--ai-story"]).ai_story is True

    def test_multiple_flags_independent(self):
        args = self._parse(["--ai-title", "--ai-caption"])
        assert args.ai_title is True
        assert args.ai_caption is True
        assert args.ai_short is False

    def test_no_cache_propagates(self):
        args = self._parse(["--no-cache", "--ai-caption"])
        assert args.cache is False
        assert args.ai_caption is True


class TestArgParseMerge:
    """st-merge accepts all five AI content flags."""

    def _parse(self, extra):
        return _make_merge_parser().parse_args(["dummy.json"] + extra)

    def test_no_flags_all_false(self):
        args = self._parse([])
        assert not any([args.ai_title, args.ai_short, args.ai_caption,
                        args.ai_summary, args.ai_story])

    def test_ai_title_accepted(self):
        assert self._parse(["--ai-title"]).ai_title is True

    def test_ai_short_accepted(self):
        assert self._parse(["--ai-short"]).ai_short is True

    def test_ai_caption_accepted(self):
        assert self._parse(["--ai-caption"]).ai_caption is True

    def test_ai_summary_accepted(self):
        assert self._parse(["--ai-summary"]).ai_summary is True

    def test_ai_story_accepted(self):
        assert self._parse(["--ai-story"]).ai_story is True

    def test_all_five_simultaneously(self):
        args = self._parse(
            ["--ai-title", "--ai-short", "--ai-caption", "--ai-summary", "--ai-story"])
        assert all([args.ai_title, args.ai_short, args.ai_caption,
                    args.ai_summary, args.ai_story])


class TestArgParseGen:
    """st-gen accepts all five AI content flags."""

    def _parse(self, extra):
        return _make_gen_parser().parse_args(["dummy.prompt"] + extra)

    def test_no_flags_all_false(self):
        args = self._parse([])
        assert not any([args.ai_title, args.ai_short, args.ai_caption,
                        args.ai_summary, args.ai_story])

    def test_ai_title_accepted(self):
        assert self._parse(["--ai-title"]).ai_title is True

    def test_ai_short_accepted(self):
        assert self._parse(["--ai-short"]).ai_short is True

    def test_ai_caption_accepted(self):
        assert self._parse(["--ai-caption"]).ai_caption is True

    def test_ai_summary_accepted(self):
        assert self._parse(["--ai-summary"]).ai_summary is True

    def test_ai_story_accepted(self):
        assert self._parse(["--ai-story"]).ai_story is True

    def test_bang_and_ai_caption_together(self):
        """--bang and AI flags are independent."""
        args = self._parse(["--bang", "0", "--ai-caption"])
        assert args.bang == 0
        assert args.ai_caption is True

