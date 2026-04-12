"""
Tests for mmd_data_analysis.py — data flattening and square-matrix logic.

Tests only the pure data functions (get_flattened_fc_data_simple,
get_flattened_fc_data, and the module's embedded json_data).
The plotting/print functions (analysis_plots, print_basics) are not
tested here because they call matplotlib.show() and write to stdout
without return values useful for assertions.
"""
import pytest
import pandas as pd

from mmd_data_analysis import (
    get_flattened_fc_data_simple,
    get_flattened_fc_data,
    json_data,
)


# ── Shared test fixtures ──────────────────────────────────────────────────────

# Minimal valid 2×2 dataset: 2 evaluators, each fact-checking 2 targets
_2x2_DATA = {
    "story": [
        {
            "make": "openai", "model": "gpt-4o",
            "fact": [
                {"make": "openai", "model": "gpt-4o",  "counts": [10, 2, 1, 0, 0], "score": 1.80, "summary": ""},
                {"make": "xai",    "model": "grok-2",   "counts": [8,  1, 0, 0, 0], "score": 1.90, "summary": ""},
            ],
        },
        {
            "make": "xai", "model": "grok-2",
            "fact": [
                {"make": "openai", "model": "gpt-4o",  "counts": [5,  3, 0, 1, 0], "score": 1.60, "summary": ""},
                {"make": "xai",    "model": "grok-2",   "counts": [7,  2, 2, 0, 0], "score": 1.70, "summary": ""},
            ],
        },
    ]
}

# Data with some malformed fact entries mixed in
_MALFORMED_DATA = {
    "story": [
        {
            "make": "openai", "model": "gpt-4o",
            "fact": [
                {"make": "xai", "model": "grok-2", "counts": [10, 2, 1, 0, 0], "score": 1.8, "summary": ""},
                {"make": "bad", "model": "model",  "score": 1.0},             # missing counts key
                {"make": "bad", "model": "model2", "counts": [1, 2], "score": 0.5},  # counts too short
            ],
        },
    ]
}

# ── get_flattened_fc_data_simple ──────────────────────────────────────────────

class TestGetFlattenedFcDataSimple:

    def test_returns_list(self):
        assert isinstance(get_flattened_fc_data_simple(_2x2_DATA), list)

    def test_length_is_stories_times_facts(self):
        # 2 stories × 2 facts = 4 rows
        result = get_flattened_fc_data_simple(_2x2_DATA)
        assert len(result) == 4

    def test_each_row_is_dict(self):
        for row in get_flattened_fc_data_simple(_2x2_DATA):
            assert isinstance(row, dict)

    def test_expected_keys_present(self):
        expected = {
            "evaluator_make", "evaluator_model",
            "target_make", "target_model",
            "true_count", "partially_true_count", "opinion_count",
            "partially_false_count", "false_count",
            "score", "summary",
        }
        for row in get_flattened_fc_data_simple(_2x2_DATA):
            assert expected <= set(row.keys())

    def test_scores_preserved(self):
        result = get_flattened_fc_data_simple(_2x2_DATA)
        scores = {r["score"] for r in result}
        assert 1.80 in scores
        assert 1.90 in scores
        assert 1.60 in scores
        assert 1.70 in scores

    def test_evaluator_make_set_correctly(self):
        result = get_flattened_fc_data_simple(_2x2_DATA)
        openai_rows = [r for r in result if r["evaluator_make"] == "openai"]
        assert len(openai_rows) == 2

    def test_skips_missing_counts(self):
        result = get_flattened_fc_data_simple(_MALFORMED_DATA)
        # Only the valid fact (xai:grok-2) should appear
        assert len(result) == 1
        assert result[0]["target_make"] == "xai"

    def test_skips_counts_too_short(self):
        data = {
            "story": [{"make": "openai", "model": "gpt", "fact": [
                {"make": "x", "model": "m", "counts": [1, 2, 3, 4], "score": 1.0, "summary": ""}
            ]}]
        }
        assert get_flattened_fc_data_simple(data) == []

    def test_model_truncated_to_17_chars(self):
        long_model = "a" * 30
        data = {
            "story": [{"make": "openai", "model": long_model, "fact": [
                {"make": "xai", "model": "b" * 30, "counts": [1, 0, 0, 0, 0], "score": 2.0, "summary": ""}
            ]}]
        }
        result = get_flattened_fc_data_simple(data)
        assert len(result[0]["evaluator_model"]) <= 17
        assert len(result[0]["target_model"]) <= 17

    def test_embedded_json_data_non_empty(self):
        result = get_flattened_fc_data_simple(json_data)
        assert len(result) > 0

    def test_produces_valid_dataframe(self):
        result = get_flattened_fc_data_simple(_2x2_DATA)
        df = pd.DataFrame(result)
        assert len(df) == 4
        assert "score" in df.columns
        assert "evaluator_make" in df.columns


# ── get_flattened_fc_data ─────────────────────────────────────────────────────

class TestGetFlattenedFcData:

    def test_returns_list(self):
        assert isinstance(get_flattened_fc_data(_2x2_DATA), list)

    def test_2x2_produces_4_rows(self):
        result = get_flattened_fc_data(_2x2_DATA)
        assert len(result) == 4

    def test_expected_keys_present(self):
        expected = {
            "evaluator_make", "evaluator_model",
            "target_make", "target_model",
            "true_count", "partially_true_count", "opinion_count",
            "partially_false_count", "false_count",
            "score",
        }
        for row in get_flattened_fc_data(_2x2_DATA):
            assert expected <= set(row.keys())

    def test_result_forms_square_matrix(self):
        """Every evaluator evaluates every target exactly once."""
        result = get_flattened_fc_data(_2x2_DATA)
        df = pd.DataFrame(result)
        n_evaluators = df["evaluator_make"].nunique()
        n_targets = df["target_make"].nunique()
        assert n_evaluators == n_targets
        assert len(df) == n_evaluators * n_targets

    def test_builtin_4x4_produces_16_rows(self):
        """The embedded sample dataset is 4×4 → 16 rows."""
        result = get_flattened_fc_data(json_data)
        df = pd.DataFrame(result)
        assert len(df) == 16
        assert df["evaluator_make"].nunique() == 4
        assert df["target_make"].nunique() == 4

    def test_non_square_input_trimmed_to_largest_square(self):
        """
        3 evaluators but only 2 share a common pair of targets →
        largest square is 2×2.
        """
        data = {
            "story": [
                {
                    "make": "openai", "model": "gpt",
                    "fact": [
                        {"make": "openai", "model": "gpt",  "counts": [5, 1, 0, 0, 0], "score": 1.8},
                        {"make": "xai",    "model": "grok", "counts": [4, 1, 0, 0, 0], "score": 1.7},
                    ],
                },
                {
                    "make": "xai", "model": "grok",
                    "fact": [
                        {"make": "openai", "model": "gpt",  "counts": [3, 2, 0, 0, 0], "score": 1.6},
                        {"make": "xai",    "model": "grok", "counts": [6, 0, 0, 0, 0], "score": 2.0},
                    ],
                },
                {
                    # This evaluator only checks one unique target
                    "make": "anthropic", "model": "claude",
                    "fact": [
                        {"make": "anthropic", "model": "claude", "counts": [9, 0, 0, 0, 0], "score": 2.0},
                    ],
                },
            ]
        }
        result = get_flattened_fc_data(data)
        # Should find the 2×2 square (openai + xai)
        assert len(result) == 4

    def test_empty_stories_raises(self):
        """Empty story list raises ValueError (max on empty sequence)."""
        with pytest.raises((ValueError, StopIteration)):
            get_flattened_fc_data({"story": []})

    def test_scores_preserved(self):
        result = get_flattened_fc_data(_2x2_DATA)
        scores = {r["score"] for r in result}
        assert 1.80 in scores
        assert 1.90 in scores

    def test_produces_valid_dataframe(self):
        result = get_flattened_fc_data(_2x2_DATA)
        df = pd.DataFrame(result)
        assert not df.empty
        assert "score" in df.columns

    def test_single_story_single_fact_returns_1x1(self):
        """A 1×1 dataset is the degenerate minimum square."""
        data = {
            "story": [
                {
                    "make": "openai", "model": "gpt",
                    "fact": [
                        {"make": "openai", "model": "gpt", "counts": [5, 1, 0, 0, 0], "score": 1.8},
                    ],
                }
            ]
        }
        result = get_flattened_fc_data(data)
        assert len(result) == 1

