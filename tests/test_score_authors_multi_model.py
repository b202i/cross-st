"""
tests/test_score_authors_multi_model.py — CST-MM-c: alias-aware scorer audit.

Verifies that `score_authors()` and `_collect_author_signals()` already treat
two same-make stories with different models as **distinct authors**, since
identity throughout `_report_signals.py` is `make:model` (post-VRD-10).
This locks the property in case a future refactor regresses to make-only
identity.
"""
import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture
def rs_mod():
    """Load _report_signals as an importable module."""
    path = Path(__file__).parent.parent / "cross_st" / "_report_signals.py"
    spec = importlib.util.spec_from_file_location("_report_signals_mm", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_report_signals_mm"] = mod
    spec.loader.exec_module(mod)
    return mod


def _build_two_alias_container():
    """A minimal container with two same-make authors and one evaluator each."""
    prompt = (
        "Write a 200-word report on the Eiffel Tower. "
        "Cover height, year built, and architect."
    )
    def _story(model, true_n, false_n):
        return {
            "make":     "anthropic",
            "model":    model,
            "role":     "author",
            "title":    f"Eiffel Tower ({model})",
            "markdown": "The Eiffel Tower " * 30,   # ~60 words, enough for parser
            "text":     "The Eiffel Tower " * 30,
            "segments": ["seg-" + str(i) for i in range(5)],
            "fact": [
                {
                    "make":   "openai",
                    "model":  "gpt-4o",
                    "role":   "evaluator",
                    "report": "",
                    "summary": "",
                    "score":  1.0,
                    # 6-int counts (T, ~T, Op, ~F, F, U)
                    "counts": [true_n, 0, 0, 0, false_n, 0],
                    "claims": [],
                },
            ],
        }
    return {
        "prompt": prompt,
        "data": [
            {"make": "anthropic", "model": "claude-opus-4-5",   "role": "author", "prompt": prompt},
            {"make": "anthropic", "model": "claude-sonnet-4-5", "role": "author", "prompt": prompt},
        ],
        "story": [
            _story("claude-opus-4-5",   true_n=10, false_n=0),  # high accuracy
            _story("claude-sonnet-4-5", true_n=2,  false_n=8),  # low accuracy
        ],
    }


class TestSameMakeAliasesScoredDistinctly:
    def test_two_authors_appear_with_distinct_make_model_ids(self, rs_mod):
        scores = rs_mod.score_authors(_build_two_alias_container())
        author_ids = {s.author for s in scores}
        assert "anthropic:claude-opus-4-5"   in author_ids
        assert "anthropic:claude-sonnet-4-5" in author_ids

    def test_two_authors_get_distinct_composite_scores(self, rs_mod):
        scores = rs_mod.score_authors(_build_two_alias_container())
        by_id = {s.author: s for s in scores}
        opus    = by_id["anthropic:claude-opus-4-5"]
        sonnet  = by_id["anthropic:claude-sonnet-4-5"]
        # Opus had 10 True / 0 False; sonnet 2 True / 8 False — opus must
        # outrank sonnet on accuracy (and thus composite, all else equal).
        assert opus.components["accuracy"] > sonnet.components["accuracy"]
        assert opus.composite > sonnet.composite

    def test_collect_author_signals_keys_on_make_model(self, rs_mod):
        signals = rs_mod._collect_author_signals(_build_two_alias_container())
        ids = [s["author"] for s in signals]
        # Must be two distinct entries, not one collapsed "anthropic" row.
        assert len(ids) == 2
        assert len(set(ids)) == 2


