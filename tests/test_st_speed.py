"""
Tests for st-speed.py — AI performance analysis and speed comparison

This test suite validates timing data extraction, summarization, and formatting.
"""

import pytest
import json
from pathlib import Path
import sys
import importlib.util

# Load st-speed.py as a module (handles hyphen in filename)
spec = importlib.util.spec_from_file_location("st_speed", 
    Path(__file__).parent.parent / "cross_st" / "st-speed.py")
st_speed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st_speed)

# Import functions from st-speed
extract_generation_timing = st_speed.extract_generation_timing
extract_fact_check_timing = st_speed.extract_fact_check_timing
format_time = st_speed.format_time
summarize_generation = st_speed.summarize_generation
summarize_fact_checks = st_speed.summarize_fact_checks
build_caption_prompt = st_speed.build_ai_prompt          # renamed: build_ai_prompt
format_data_for_prompt = st_speed.format_data_for_prompt
generate_performance_caption = st_speed.generate_ai_content  # renamed: generate_ai_content
validate_caption = st_speed.validate_ai_content          # renamed: validate_ai_content

# Import get_usage from ai_handler for direct testing
from ai_handler import get_usage


# ─────────────────────────────────────────────────────────────────────────────
# get_usage — provider-specific token extraction
# ─────────────────────────────────────────────────────────────────────────────

class TestGetUsage:
    """Tests for the centralised get_usage() dispatcher in ai_handler."""

    # ── OpenAI format ─────────────────────────────────────────────────────────
    def test_openai_standard_fields(self):
        response = {"usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}}
        result = get_usage("openai", response)
        assert result == {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300}

    def test_openai_total_computed_when_absent(self):
        response = {"usage": {"prompt_tokens": 50, "completion_tokens": 75}}
        result = get_usage("openai", response)
        assert result["total_tokens"] == 125

    def test_openai_missing_usage_key(self):
        result = get_usage("openai", {})
        assert result == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    # ── Perplexity format (OpenAI-compatible) ─────────────────────────────────
    def test_perplexity_same_as_openai(self):
        response = {"usage": {"prompt_tokens": 80, "completion_tokens": 120, "total_tokens": 200}}
        result = get_usage("perplexity", response)
        assert result == {"input_tokens": 80, "output_tokens": 120, "total_tokens": 200}

    # ── Anthropic format ──────────────────────────────────────────────────────
    def test_anthropic_standard_fields(self):
        response = {"usage": {"input_tokens": 150, "output_tokens": 350}}
        result = get_usage("anthropic", response)
        assert result == {"input_tokens": 150, "output_tokens": 350, "total_tokens": 500}

    def test_anthropic_total_always_computed(self):
        """Anthropic never returns total_tokens; we always sum input + output."""
        response = {"usage": {"input_tokens": 200, "output_tokens": 400}}
        result = get_usage("anthropic", response)
        assert result["total_tokens"] == 600

    def test_anthropic_missing_usage_key(self):
        result = get_usage("anthropic", {})
        assert result == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    # ── xAI format (Anthropic-compatible) ────────────────────────────────────
    def test_xai_same_as_anthropic(self):
        response = {"usage": {"input_tokens": 90, "output_tokens": 210}}
        result = get_usage("xai", response)
        assert result == {"input_tokens": 90, "output_tokens": 210, "total_tokens": 300}

    # ── Gemini format (flat top-level keys) ──────────────────────────────────
    def test_gemini_top_level_keys(self):
        response = {
            "prompt_token_count": 120,
            "candidates_token_count": 280,
            "total_token_count": 400,
        }
        result = get_usage("gemini", response)
        assert result == {"input_tokens": 120, "output_tokens": 280, "total_tokens": 400}

    def test_gemini_total_computed_when_absent(self):
        response = {"prompt_token_count": 60, "candidates_token_count": 140}
        result = get_usage("gemini", response)
        assert result["total_tokens"] == 200

    def test_gemini_missing_all_fields(self):
        result = get_usage("gemini", {})
        assert result == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    # ── Unknown provider ──────────────────────────────────────────────────────
    def test_unknown_provider_returns_zeros(self):
        result = get_usage("unknown_ai", {"usage": {"prompt_tokens": 999}})
        assert result == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    # ── Values are always ints (no None, no floats) ───────────────────────────
    def test_all_values_are_ints(self):
        for provider in ("openai", "anthropic", "xai", "perplexity", "gemini"):
            result = get_usage(provider, {})
            for key, val in result.items():
                assert isinstance(val, int), f"{provider}.{key} should be int, got {type(val)}"


class TestTimingDataExtraction:
    """Test extraction of timing data from containers"""
    
    def test_extract_generation_timing_basic(self):
        """Extract timing from data entries"""
        container = {
            "data": [{
                "make": "xai",
                "model": "grok-4-latest",
                "timing": {
                    "elapsed_seconds": 317.5,
                    "tokens_input": 193,
                    "tokens_output": 1287,
                    "tokens_total": 1480,
                    "tokens_per_second": 4.66,
                    "cached": False
                }
            }]
        }
        
        result = extract_generation_timing(container)
        
        assert len(result) == 1
        assert result[0]["ai"] == "xai"
        assert result[0]["elapsed_seconds"] == 317.5
        assert result[0]["tokens_total"] == 1480
        assert result[0]["cached"] is False
    
    def test_extract_generation_timing_empty(self):
        """Handle empty container"""
        container = {"data": []}
        result = extract_generation_timing(container)
        assert result == []
    
    def test_extract_generation_timing_no_timing_field(self):
        """Skip entries without timing data"""
        container = {
            "data": [
                {"make": "xai", "model": "grok-4-latest"},  # No timing
                {
                    "make": "gemini",
                    "model": "gemini-2.5-flash",
                    "timing": {"elapsed_seconds": 178.0, "tokens_total": 1287}
                }
            ]
        }
        
        result = extract_generation_timing(container)
        assert len(result) == 1
        assert result[0]["ai"] == "gemini"
    
    def test_extract_fact_check_timing_basic(self):
        """Extract timing from fact-checks"""
        container = {
            "story": [{
                "make": "xai",
                "segments": [{"id": 1}, {"id": 2}, {"id": 3}],  # 3 segments = 3 AI calls
                "fact": [{
                    "make": "perplexity",
                    "model": "sonar-pro",
                    "score": 1.29,
                    "timing": {
                        "elapsed_seconds": 91.5,
                        "tokens_total": 320,
                        "tokens_per_second": 3.49,
                        "cached": False
                    }
                }]
            }]
        }
        
        result = extract_fact_check_timing(container)
        
        assert len(result) == 1
        assert result[0]["ai"] == "perplexity"
        assert result[0]["story_index"] == 1
        assert result[0]["elapsed_seconds"] == 91.5
        assert result[0]["score"] == 1.29
        assert result[0]["segments"] == 3  # New: track segment count

    def test_extract_fact_check_timing_new_format_fully_fresh(self):
        """New-format container (n_fresh == n_total): elapsed = elapsed_fresh_seconds."""
        container = {
            "story": [{
                "make": "xai",
                "segments": [{"id": i} for i in range(5)],
                "fact": [{
                    "make": "openai",
                    "model": "gpt-4o",
                    "score": 1.5,
                    "timing": {
                        "elapsed_seconds":       100.0,   # total wall clock
                        "elapsed_fresh_seconds": 98.0,    # nearly identical for fully-fresh run
                        "n_total": 5,
                        "n_fresh": 5,
                        "n_cached": 0,
                        "tokens_total": 500,
                        "cached": False,
                    }
                }]
            }]
        }
        result = extract_fact_check_timing(container)
        assert len(result) == 1
        # For fully-fresh: elapsed_fresh / n_fresh * n_total == elapsed_fresh (no change)
        assert result[0]["elapsed_seconds"] == pytest.approx(98.0)
        assert result[0]["n_fresh"] == 5
        assert result[0]["n_total"] == 5

    def test_extract_fact_check_timing_new_format_partial_cache(self):
        """Partially-cached run: elapsed is extrapolated from fresh calls."""
        # 2 of 10 segments were fresh, took 20s total → avg 10s/segment
        # Extrapolated full run: 10s × 10 = 100s
        container = {
            "story": [{
                "make": "anthropic",
                "segments": [{"id": i} for i in range(10)],
                "fact": [{
                    "make": "gemini",
                    "model": "gemini-2.5-flash",
                    "score": 1.7,
                    "timing": {
                        "elapsed_seconds":       20.2,   # mostly cache-hit time
                        "elapsed_fresh_seconds": 20.0,   # 2 fresh calls × ~10s
                        "n_total": 10,
                        "n_fresh": 2,
                        "n_cached": 8,
                        "tokens_total": 200,
                        "cached": False,
                    }
                }]
            }]
        }
        result = extract_fact_check_timing(container)
        # extrapolated: 20.0 / 2 * 10 = 100.0
        assert result[0]["elapsed_seconds"] == pytest.approx(100.0)

    def test_extract_fact_check_timing_old_format_fallback(self):
        """Old-format containers (no n_fresh/elapsed_fresh_seconds) use elapsed_seconds."""
        container = {
            "story": [{
                "make": "xai",
                "segments": [{"id": i} for i in range(4)],
                "fact": [{
                    "make": "perplexity",
                    "score": 1.3,
                    "timing": {
                        "elapsed_seconds": 75.0,
                        "tokens_total": 400,
                        "cached": False,
                        # no n_fresh, no elapsed_fresh_seconds
                    }
                }]
            }]
        }
        result = extract_fact_check_timing(container)
        assert result[0]["elapsed_seconds"] == pytest.approx(75.0)
        assert result[0]["n_fresh"] is None   # absent in old format
    
    def test_extract_fact_check_timing_multiple_stories(self):
        """Extract from multiple stories with multiple fact-checks"""
        container = {
            "story": [
                {
                    "make": "xai",
                    "fact": [
                        {"make": "gemini", "timing": {"elapsed_seconds": 50.0}},
                        {"make": "openai", "timing": {"elapsed_seconds": 60.0}}
                    ]
                },
                {
                    "make": "anthropic",
                    "fact": [
                        {"make": "gemini", "timing": {"elapsed_seconds": 55.0}}
                    ]
                }
            ]
        }
        
        result = extract_fact_check_timing(container)
        
        assert len(result) == 3
        assert result[0]["story_index"] == 1
        assert result[1]["story_index"] == 1
        assert result[2]["story_index"] == 2


class TestTimeFormatting:
    """Test time formatting utilities"""
    
    def test_format_time_minutes_seconds(self):
        """Format seconds as mm:ss"""
        assert format_time(0) == "00:00"
        assert format_time(45) == "00:45"
        assert format_time(90) == "01:30"
        assert format_time(317) == "05:17"
        assert format_time(3661) == "61:01"  # Over an hour
    
    def test_format_time_negative(self):
        """Handle negative times gracefully"""
        assert format_time(-10) == "--:--"
    
    def test_format_time_fractional(self):
        """Handle fractional seconds (truncate)"""
        assert format_time(90.7) == "01:30"
        assert format_time(119.9) == "01:59"


class TestGenerationSummary:
    """Test story generation performance summarization"""
    
    def test_summarize_generation_basic(self):
        """Summarize generation timing"""
        timing_data = [
            {
                "ai": "gemini",
                "elapsed_seconds": 178.0,
                "tokens_total": 1287,
                "tokens_per_second": 7.23,
                "cached": False
            },
            {
                "ai": "openai",
                "elapsed_seconds": 273.0,
                "tokens_total": 1072,
                "tokens_per_second": 3.93,
                "cached": False
            }
        ]
        
        result = summarize_generation(timing_data)
        
        assert len(result) == 2
        # Should be sorted by time (fastest first)
        assert result[0]["AI"] == "gemini"
        assert result[1]["AI"] == "openai"
        assert result[0]["Time"] == "02:58"
        assert result[1]["Time"] == "04:33"
    
    def test_summarize_generation_excludes_cached_from_metrics(self):
        """Cached entries must not skew timing/tok-per-sec metrics for an AI
        that also has fresh entries."""
        timing_data = [
            {"ai": "gemini", "elapsed_seconds": 178.0, "tokens_total": 1287,
             "tokens_per_second": 7.23, "cached": False},
            {"ai": "gemini", "elapsed_seconds": 0.5, "tokens_total": 1287,
             "tokens_per_second": 2574.0, "cached": True},  # cache hit — ignore for metrics
        ]

        result = summarize_generation(timing_data)

        # gemini should appear once, using only the fresh entry
        assert len(result) == 1
        assert result[0]["AI"] == "gemini"
        assert result[0]["Samples"] == 1        # only the fresh entry counted
        assert result[0]["Time"] == "02:58"     # not skewed by the 0.5s cache hit

    def test_summarize_generation_cached_only_shows_cache_row(self):
        """
        Regression: an AI whose *only* entry is a cache hit must still appear
        in the table as ``(cache)`` rather than being silently dropped.

        This was the bug that caused xai to vanish from st-speed output when
        its generation was served from the API cache.
        """
        timing_data = [
            {"ai": "xai",   "elapsed_seconds": 0.018, "tokens_total": 3687,
             "tokens_per_second": 204850.0, "cached": True},
            {"ai": "openai", "elapsed_seconds": 18.4,  "tokens_total": 1631,
             "tokens_per_second": 88.6, "cached": False},
        ]

        result = summarize_generation(timing_data)

        # Both providers must be present
        ais = {r["AI"] for r in result}
        assert "xai" in ais,   "xai must appear even when its only entry is cached"
        assert "openai" in ais

        xai_row = next(r for r in result if r["AI"] == "xai")
        assert xai_row["Time"] == "(cache)", (
            f"Expected Time='(cache)' for a cache-only row, got {xai_row['Time']!r}"
        )
        assert xai_row["Tok/s"] == "—", "Tok/s must be '—' for cache-only rows"
        assert xai_row["Tokens"] == 3687

        # The fresh provider (openai) must sort *before* the cached one
        openai_idx = next(i for i, r in enumerate(result) if r["AI"] == "openai")
        xai_idx    = next(i for i, r in enumerate(result) if r["AI"] == "xai")
        assert openai_idx < xai_idx, "Fresh rows must sort before cached rows"

    def test_summarize_generation_all_cached_returns_cache_rows(self):
        """When every AI entry is cached the table still has a row per AI."""
        timing_data = [
            {"ai": "xai",      "elapsed_seconds": 0.01, "tokens_total": 3500,
             "tokens_per_second": 350000.0, "cached": True},
            {"ai": "anthropic", "elapsed_seconds": 0.01, "tokens_total": 4000,
             "tokens_per_second": 400000.0, "cached": True},
        ]

        result = summarize_generation(timing_data)

        assert len(result) == 2
        for row in result:
            assert row["Time"] == "(cache)"
            assert row["Tok/s"] == "—"

    
    def test_summarize_generation_multiple_samples(self):
        """Average across multiple runs"""
        timing_data = [
            {"ai": "gemini", "elapsed_seconds": 170.0, "tokens_total": 1200,
             "tokens_per_second": 7.0, "cached": False},
            {"ai": "gemini", "elapsed_seconds": 180.0, "tokens_total": 1400,
             "tokens_per_second": 7.8, "cached": False},
        ]
        
        result = summarize_generation(timing_data)
        
        assert len(result) == 1
        assert result[0]["Samples"] == 2
        # Average: (170 + 180) / 2 = 175s = 02:55
        assert result[0]["Time"] == "02:55"
        # Average tokens: (1200 + 1400) / 2 = 1300
        assert result[0]["Tokens"] == 1300
    
    def test_summarize_generation_filter_by_ai(self):
        """Filter summary by specific AI"""
        timing_data = [
            {"ai": "gemini", "elapsed_seconds": 178.0, "tokens_total": 1287,
             "tokens_per_second": 7.23, "cached": False},
            {"ai": "openai", "elapsed_seconds": 273.0, "tokens_total": 1072,
             "tokens_per_second": 3.93, "cached": False}
        ]
        
        result = summarize_generation(timing_data, ai_filter="gemini")
        
        assert len(result) == 1
        assert result[0]["AI"] == "gemini"
    
    def test_summarize_generation_empty(self):
        """Handle empty timing data"""
        result = summarize_generation([])
        assert result is None


class TestFactCheckSummary:
    """Test fact-check performance summarization"""
    
    def test_summarize_fact_checks_basic(self):
        """Summarize fact-check timing with statistics"""
        timing_data = [
            {"ai": "perplexity", "elapsed_seconds": 70.0, "cached": False, "segments": 25},
            {"ai": "perplexity", "elapsed_seconds": 80.0, "cached": False, "segments": 30},
            {"ai": "perplexity", "elapsed_seconds": 90.0, "cached": False, "segments": 28},
        ]
        
        result = summarize_fact_checks(timing_data)
        
        assert len(result) == 1
        assert result[0]["AI"] == "perplexity"
        assert result[0]["Avg"] == "01:20"   # 80s average
        assert result[0]["Median"] == "01:20"  # 80s median
        assert result[0]["Min"] == "01:10"   # 70s
        assert result[0]["Max"] == "01:30"   # 90s
        assert result[0]["Samples"] == 3
        assert result[0]["Segments"] == "27/job"  # Average of 25, 30, 28
    
    def test_summarize_fact_checks_multiple_ais(self):
        """Summarize across multiple AIs"""
        timing_data = [
            {"ai": "perplexity", "elapsed_seconds": 70.0, "cached": False, "segments": 20},
            {"ai": "gemini", "elapsed_seconds": 140.0, "cached": False, "segments": 35},
            {"ai": "perplexity", "elapsed_seconds": 75.0, "cached": False, "segments": 22},
        ]
        
        result = summarize_fact_checks(timing_data)
        
        assert len(result) == 2
        # Should be sorted by average time
        assert result[0]["AI"] == "perplexity"
        assert result[1]["AI"] == "gemini"
        assert "Segments" in result[0]  # Has segment info
    
    def test_summarize_fact_checks_single_sample(self):
        """Handle single sample (no stdev)"""
        timing_data = [
            {"ai": "openai", "elapsed_seconds": 81.0, "cached": False, "segments": 42}
        ]

        result = summarize_fact_checks(timing_data)

        assert len(result) == 1
        assert result[0]["StdDev"] == "0.0s"  # No variance with 1 sample
        assert result[0]["Segments"] == "42/job"

    def test_summarize_fact_checks_all_cached_returns_empty(self):
        """When every entry is cached, no rows should be returned."""
        timing_data = [
            {"ai": "openai", "elapsed_seconds": 0.05, "cached": True, "segments": 20}
        ]
        result = summarize_fact_checks(timing_data)
        assert result is None or len(result) == 0


class TestEdgeCases:
    """Test edge cases and error handling"""
    
    def test_extract_with_missing_fields(self):
        """Handle containers with missing optional fields"""
        container = {
            "data": [{
                "timing": {
                    "elapsed_seconds": 100.0
                    # Missing: tokens_total, tokens_per_second, etc.
                }
            }]
        }
        
        result = extract_generation_timing(container)
        
        assert len(result) == 1
        assert result[0]["ai"] == "unknown"  # Default when 'make' missing
        assert result[0]["tokens_total"] == 0  # Default when missing
    
    def test_extract_fact_check_no_segments(self):
        """Handle fact-checks without segment data (backwards compatibility)"""
        container = {
            "story": [{
                "make": "xai",
                # No 'segments' field
                "fact": [{
                    "make": "gemini",
                    "timing": {"elapsed_seconds": 100.0}
                }]
            }]
        }
        
        result = extract_fact_check_timing(container)
        
        assert len(result) == 1
        assert result[0]["segments"] == 0  # Default when segments missing
    
    def test_summarize_all_cached(self):
        """Handle case where all entries are cached — now shows (cache) rows."""
        timing_data = [
            {"ai": "gemini", "elapsed_seconds": 0.1, "tokens_total": 1000,
             "tokens_per_second": 10000, "cached": True}
        ]

        result = summarize_generation(timing_data)

        # Previously returned empty; now returns a "(cache)" row so the provider
        # is visible in the table rather than silently absent.
        assert len(result) == 1
        assert result[0]["AI"] == "gemini"
        assert result[0]["Time"] == "(cache)"


class TestCaptionGeneration:
    """Test AI caption generation feature"""

    def test_build_caption_prompt(self):
        """Test prompt construction with performance data"""
        gen_summary = [
            {"AI": "gemini", "Time": "02:58", "Tokens": 1287, "Tok/s": "7.23", "Samples": 1}
        ]
        fact_summary = [
            {"AI": "openai", "Avg": "00:34", "Median": "00:35", "Min": "00:03",
             "Max": "01:04", "StdDev": "28.4s", "Samples": 5, "Segments": "19/job"}
        ]

        # Test normal caption (content_type="caption")
        prompt = build_caption_prompt(gen_summary, fact_summary, content_type="caption")

        # Should include both tables
        assert "generation" in prompt.lower() or "GENERATION" in prompt
        assert "fact" in prompt.lower() or "FACT" in prompt

        # Should include data
        assert "gemini" in prompt.lower()
        assert "openai" in prompt.lower()

        # Should have requirements
        assert len(prompt) > 200  # Meaningful prompt

    def test_build_caption_prompt_short(self):
        """Test short caption prompt construction"""
        fact_summary = [
            {"AI": "openai", "Avg": "00:34", "Samples": 5, "Segments": "19/job"}
        ]

        prompt = build_caption_prompt(None, fact_summary, content_type="short")

        # Should request short format
        assert "80 words" in prompt or "short" in prompt.lower()
        assert "LENGTH" in prompt or "length" in prompt.lower()

    def test_build_caption_prompt_standard_word_counts(self):
        """Test standard caption prompt includes specific word counts"""
        fact_summary = [
            {"AI": "openai", "Avg": "00:34", "Samples": 5, "Segments": "19/job"}
        ]

        prompt = build_caption_prompt(None, fact_summary, content_type="caption")

        # Should specify word counts for detailed caption
        assert "100" in prompt or "160" in prompt
        assert "LENGTH" in prompt or "length" in prompt.lower()

    def test_caption_validation_word_count_short(self):
        """Test validation accepts short captions with appropriate word count"""
        # 40 words with a number — valid for short (max 80 words)
        short_caption_40 = " ".join(["word"] * 39) + " 42"
        is_valid, _, _ = validate_caption(short_caption_40, content_type="short")
        assert is_valid is True

        # 1 word — too short (min 1 word for short, but needs a number check)
        # For short type, numbers are not required, so single word fails only on length if min>1
        # Actually min_words for "short" is 1, but we want >1 practically; skip edge test

        # 80 words (max for short) with a number
        short_caption_80 = " ".join(["word"] * 79) + " 42"
        is_valid2, _, _ = validate_caption(short_caption_80, content_type="short")
        assert is_valid2 is True

    def test_caption_validation_word_count_standard(self):
        """Test validation accepts standard captions with 100-160 words"""
        # 100 words with a number — valid for caption
        standard_caption_100 = " ".join(["word"] * 99) + " 42"
        is_valid, _, _ = validate_caption(standard_caption_100, content_type="caption")
        assert is_valid is True

        # 50 words — too short for standard caption (needs 100+)
        too_short = " ".join(["word"] * 49) + " 42"
        is_valid2, _, _ = validate_caption(too_short, content_type="caption")
        assert is_valid2 is False

        # 160 words with a number — at max boundary
        standard_caption_160 = " ".join(["word"] * 159) + " 42"
        is_valid3, _, _ = validate_caption(standard_caption_160, content_type="caption")
        assert is_valid3 is True

    def test_caption_validation_requires_numbers(self):
        """Test validation requires data-driven content (numbers) for captions"""
        # Has words but no numbers — invalid for "caption" type
        no_numbers = " ".join(["word"] * 110)
        is_valid, _, _ = validate_caption(no_numbers, content_type="caption")
        assert is_valid is False

        # Has numbers — valid
        with_numbers = " ".join(["word"] * 109) + " 34"
        is_valid2, _, _ = validate_caption(with_numbers, content_type="caption")
        assert is_valid2 is True

    def test_format_data_for_prompt(self):
        """Test formatting summary data as text table"""
        summary = [
            {"AI": "openai", "Time": "00:34", "Samples": 5}
        ]

        result = format_data_for_prompt(summary)

        assert "openai" in result
        assert "00:34" in result
        assert "5" in result

    def test_generate_caption_mock(self):
        """Test caption generation with mocked AI call"""
        from unittest.mock import MagicMock, patch
        import sys

        gen_summary = [{"AI": "gemini", "Time": "02:58", "Samples": 1}]
        fact_summary = [{"AI": "openai", "Avg": "00:34", "Samples": 5, "Segments": "19/job"}]

        mock_response = {
            "text": "OpenAI dominates at 30 seconds, showing excellent consistency. "
                    "The data reveals Gemini generation is competitive for most workloads."
        }

        # Register the dynamically-loaded module so patch() can find it
        sys.modules['st_speed'] = st_speed

        try:
            with patch.object(st_speed, 'process_prompt') as mock_prompt:
                mock_prompt.return_value = (None, None, mock_response, "gemini-2.5-flash")

                caption = generate_performance_caption(
                    gen_summary, fact_summary, "gemini", content_type="caption"
                )

                # Should produce some content (may be empty if validate rejects it, but call succeeded)
                assert isinstance(caption, str)
        finally:
            sys.modules.pop('st_speed', None)

    def test_caption_validation(self):
        """Test caption quality validation returns a tuple"""
        # A sentence with 10 words and a number — too short for 'caption' (needs 100+)
        short_text = "OpenAI at 34 seconds is the fastest option available today."
        is_valid, wc, msg = validate_caption(short_text, content_type="caption")
        assert is_valid is False  # too short

        # A very short text
        bad_caption = "Good."
        is_valid2, _, _ = validate_caption(bad_caption, content_type="caption")
        assert is_valid2 is False

    def test_caption_with_no_data(self):
        """Test caption generation when no performance data exists"""
        result = generate_performance_caption([], [], "gemini", content_type="caption")
        assert result == "" or "no data" in result.lower()


class TestIntegration:
    """Integration tests using realistic fixture data"""
    
    def test_with_pizza_dough_fixture(self):
        """Test with real pizza_dough.json fixture"""
        fixture_path = Path(__file__).parent / "fixtures" / "pizza_dough.json"
        
        if not fixture_path.exists():
            pytest.skip("pizza_dough.json fixture not found")
        
        with open(fixture_path) as f:
            container = json.load(f)
        
        gen_data = extract_generation_timing(container)
        fact_data = extract_fact_check_timing(container)
        
        # Should have some timing data (if Phase 1 was implemented)
        # If not, this documents the current state
        if gen_data:
            assert all("ai" in entry for entry in gen_data)
            assert all("elapsed_seconds" in entry for entry in gen_data)
        
        if fact_data:
            assert all("ai" in entry for entry in fact_data)
            assert all("story_index" in entry for entry in fact_data)


# ─────────────────────────────────────────────────────────────────────────────
# validate_ai_content — all content types
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateAiContentAllTypes:
    """Extended coverage for validate_ai_content across all content_type values."""

    def test_title_valid_short(self):
        title = "OpenAI Leads Speed Race"  # 4 words — within 1-10
        is_valid, wc, msg = validate_caption(title, content_type="title")
        assert is_valid is True
        assert wc == 4

    def test_title_too_long(self):
        # 11 words — exceeds max of 10
        long_title = "OpenAI Leads the Speed Race Against All Other Competitors Today Now"
        is_valid, wc, msg = validate_caption(long_title, content_type="title")
        assert is_valid is False
        assert "too long" in msg

    def test_title_requires_no_digits(self):
        # title type has no digit requirement
        title = "Speed and Accuracy Trade-offs"
        is_valid, _, _ = validate_caption(title, content_type="title")
        assert is_valid is True

    def test_summary_valid(self):
        # 160 words with a digit — within 120-200
        words = ["word"] * 159 + ["42"]
        is_valid, wc, _ = validate_caption(" ".join(words), content_type="summary")
        assert is_valid is True
        assert wc == 160

    def test_summary_too_short(self):
        words = ["word"] * 100 + ["42"]
        is_valid, _, msg = validate_caption(" ".join(words), content_type="summary")
        assert is_valid is False
        assert "too short" in msg

    def test_summary_too_long(self):
        words = ["word"] * 201 + ["42"]
        is_valid, _, msg = validate_caption(" ".join(words), content_type="summary")
        assert is_valid is False
        assert "too long" in msg

    def test_summary_requires_digits(self):
        words = ["word"] * 150  # no digits
        is_valid, _, msg = validate_caption(" ".join(words), content_type="summary")
        assert is_valid is False
        assert "lacks data" in msg

    def test_story_valid(self):
        # 1000 words with a digit — within 800-1200
        words = ["word"] * 999 + ["42"]
        is_valid, wc, _ = validate_caption(" ".join(words), content_type="story")
        assert is_valid is True
        assert wc == 1000

    def test_story_too_short(self):
        words = ["word"] * 798 + ["42"]   # 799 total — below 800-word minimum
        is_valid, _, msg = validate_caption(" ".join(words), content_type="story")
        assert is_valid is False
        assert "too short" in msg

    def test_story_too_long(self):
        words = ["word"] * 1201 + ["42"]
        is_valid, _, msg = validate_caption(" ".join(words), content_type="story")
        assert is_valid is False
        assert "too long" in msg

    def test_unknown_type_returns_error_tuple(self):
        is_valid, _, msg = validate_caption("some content 42", content_type="alien")
        assert is_valid is False
        assert "Unknown content_type" in msg

    def test_empty_string_always_invalid(self):
        for ct in ("title", "short", "caption", "summary", "story"):
            is_valid, _, _ = validate_caption("", content_type=ct)
            assert is_valid is False, f"Expected invalid for content_type={ct!r}"


# ─────────────────────────────────────────────────────────────────────────────
# build_ai_prompt — all content types
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildAiPromptAllTypes:
    """build_ai_prompt covers every content_type branch."""

    _fact = [{"AI": "openai", "Avg": "00:34", "Samples": 5, "Segments": "19/job"}]

    def test_title_prompt_mentions_word_limit(self):
        prompt = build_caption_prompt(None, self._fact, content_type="title")
        assert "10 words" in prompt

    def test_summary_prompt_mentions_word_count(self):
        prompt = build_caption_prompt(None, self._fact, content_type="summary")
        assert "120" in prompt or "200" in prompt

    def test_story_prompt_mentions_word_count(self):
        prompt = build_caption_prompt(None, self._fact, content_type="story")
        assert "800" in prompt or "1200" in prompt

    def test_story_prompt_includes_data(self):
        prompt = build_caption_prompt(None, self._fact, content_type="story")
        assert "openai" in prompt.lower()

    def test_unknown_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown content_type"):
            build_caption_prompt(None, self._fact, content_type="bad_type")

    def test_none_gen_summary_still_builds_prompt(self):
        # Only fact data — should not crash
        prompt = build_caption_prompt(None, self._fact, content_type="caption")
        assert "FACT" in prompt.upper()
        assert "GENERATION" not in prompt.upper()


# ─────────────────────────────────────────────────────────────────────────────
# format_data_for_prompt — edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatDataForPromptEdgeCases:
    """Edge cases for format_data_for_prompt."""

    def test_empty_list_returns_no_data_message(self):
        result = format_data_for_prompt([])
        assert "No data available" in result


# ─────────────────────────────────────────────────────────────────────────────
# export_to_csv
# ─────────────────────────────────────────────────────────────────────────────

class TestExportToCsv:
    """Tests for export_to_csv — file creation and content structure."""

    _gen  = [{"ai": "openai",  "elapsed_seconds": 30.0, "cached": False}]
    _fact = [{"ai": "gemini",  "elapsed_seconds": 45.0, "cached": False}]

    def test_creates_output_file(self, tmp_path):
        out = tmp_path / "timing.csv"
        st_speed.export_to_csv(self._gen, [], str(out))
        assert out.exists()

    def test_gen_section_header_present(self, tmp_path):
        out = tmp_path / "timing.csv"
        st_speed.export_to_csv(self._gen, [], str(out))
        content = out.read_text()
        assert "GENERATION TIMING" in content
        assert "openai" in content

    def test_fact_section_header_present(self, tmp_path):
        out = tmp_path / "timing.csv"
        st_speed.export_to_csv([], self._fact, str(out))
        content = out.read_text()
        assert "FACT-CHECK TIMING" in content
        assert "gemini" in content

    def test_both_sections_written_together(self, tmp_path):
        out = tmp_path / "timing.csv"
        st_speed.export_to_csv(self._gen, self._fact, str(out))
        content = out.read_text()
        assert "GENERATION TIMING" in content
        assert "FACT-CHECK TIMING" in content

    def test_empty_data_creates_empty_file(self, tmp_path):
        out = tmp_path / "timing.csv"
        st_speed.export_to_csv([], [], str(out))
        assert out.exists()
        assert out.read_text() == ""


# ─────────────────────────────────────────────────────────────────────────────
# save_story_to_container
# ─────────────────────────────────────────────────────────────────────────────

class TestSaveStoryToContainer:
    """Tests for save_story_to_container — append, persist, index, error handling."""

    def test_appends_story_and_returns_index_one(self, tmp_path):
        jf = tmp_path / "test.json"
        container = {"data": [], "story": []}
        jf.write_text(json.dumps(container))
        idx = st_speed.save_story_to_container(
            container, str(jf), "Test story content.", "gemini", "gemini-2.5-flash",
            None, None
        )
        assert idx == 1
        assert len(container["story"]) == 1

    def test_persists_correct_make_to_file(self, tmp_path):
        jf = tmp_path / "test.json"
        container = {"data": [], "story": []}
        jf.write_text(json.dumps(container))
        st_speed.save_story_to_container(
            container, str(jf), "Test story.", "openai", "gpt-4o", None, None
        )
        saved = json.loads(jf.read_text())
        assert len(saved["story"]) == 1
        assert saved["story"][0]["make"] == "openai"

    def test_index_increments_from_existing_stories(self, tmp_path):
        jf = tmp_path / "test.json"
        container = {"data": [], "story": [{"make": "xai", "text": "existing"}]}
        jf.write_text(json.dumps(container))
        idx = st_speed.save_story_to_container(
            container, str(jf), "New story.", "gemini", "gemini-2.5-flash",
            None, None
        )
        assert idx == 2

    def test_creates_story_list_if_missing(self, tmp_path):
        jf = tmp_path / "test.json"
        container = {"data": []}  # no "story" key
        jf.write_text(json.dumps(container))
        idx = st_speed.save_story_to_container(
            container, str(jf), "Story text.", "openai", "gpt-4o", None, None
        )
        assert idx == 1
        assert "story" in container

    def test_bad_path_returns_minus_one(self):
        container = {"story": []}
        idx = st_speed.save_story_to_container(
            container, "/nonexistent/bad/path.json", "Story.", "openai", "gpt-4o",
            None, None
        )
        assert idx == -1


# ─────────────────────────────────────────────────────────────────────────────
# Backward-compatible wrappers
# ─────────────────────────────────────────────────────────────────────────────

class TestBackwardCompatWrappers:
    """
    validate_caption / build_caption_prompt / generate_performance_caption
    are backward-compat wrappers with slightly different semantics from the
    new validate_ai_content / build_ai_prompt / generate_ai_content.
    """

    # ── validate_caption ──────────────────────────────────────────────────────

    def test_validate_caption_short_true_valid_range(self):
        # 50 words: inside the 40-75 short window
        caption = " ".join(["word"] * 50)
        assert st_speed.validate_caption(caption, short_caption=True) is True

    def test_validate_caption_short_true_too_short(self):
        # 39 words: below the 40-word floor
        caption = " ".join(["word"] * 39)
        assert st_speed.validate_caption(caption, short_caption=True) is False

    def test_validate_caption_short_true_too_long(self):
        # 76 words: above the 75-word ceiling
        caption = " ".join(["word"] * 76)
        assert st_speed.validate_caption(caption, short_caption=True) is False

    def test_validate_caption_short_false_valid(self):
        # 60 words with a digit: passes standard (50+ words AND has digit)
        caption = " ".join(["word"] * 59) + " 42"
        assert st_speed.validate_caption(caption, short_caption=False) is True

    def test_validate_caption_short_false_no_digit(self):
        # 60 words but no digit: fails standard check
        caption = " ".join(["word"] * 60)
        assert st_speed.validate_caption(caption, short_caption=False) is False

    def test_validate_caption_short_false_too_short(self):
        # Under 50 words: fails length check
        assert st_speed.validate_caption("Too short but has 42", short_caption=False) is False

    def test_validate_caption_returns_bool_not_tuple(self):
        # Distinguish from validate_ai_content which returns a 3-tuple
        result = st_speed.validate_caption("OpenAI wins at 30 seconds. " * 4, short_caption=False)
        assert isinstance(result, bool)

    def test_validate_caption_empty_string_both_modes(self):
        assert st_speed.validate_caption("", short_caption=False) is False
        assert st_speed.validate_caption("", short_caption=True) is False

    # ── build_caption_prompt ──────────────────────────────────────────────────

    def test_build_caption_prompt_short_false_matches_caption_type(self):
        fact = [{"AI": "openai", "Avg": "00:34", "Samples": 5}]
        wrapper  = st_speed.build_caption_prompt(None, fact, short_caption=False)
        direct   = build_caption_prompt(None, fact, content_type="caption")
        assert wrapper == direct

    def test_build_caption_prompt_short_true_matches_short_type(self):
        fact = [{"AI": "openai", "Avg": "00:34", "Samples": 5}]
        wrapper  = st_speed.build_caption_prompt(None, fact, short_caption=True)
        direct   = build_caption_prompt(None, fact, content_type="short")
        assert wrapper == direct

    # ── generate_performance_caption ─────────────────────────────────────────

    def test_generate_performance_caption_delegates_to_generate_ai_content(self):
        """short_caption=False → content_type='caption' is forwarded to generate_ai_content."""
        from unittest.mock import patch

        gen_summary  = [{"AI": "gemini", "Time": "02:58", "Samples": 1}]
        fact_summary = [{"AI": "openai", "Avg": "00:34", "Samples": 5, "Segments": "19/job"}]
        mock_response = {"text": "OpenAI at 30 seconds leads. Consistent performance."}

        sys.modules["st_speed"] = st_speed
        try:
            with patch.object(st_speed, "process_prompt") as mock_p:
                mock_p.return_value = (None, None, mock_response, "gemini-test")
                result = st_speed.generate_performance_caption(
                    gen_summary, fact_summary, "gemini",
                    short_caption=False, verbose=False
                )
                assert isinstance(result, str)
                mock_p.assert_called_once()
        finally:
            sys.modules.pop("st_speed", None)


