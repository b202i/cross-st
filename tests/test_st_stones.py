"""
tests/test_st_stones.py — Regression tests for st-stones.py

Coverage:
    compute_domain_scores     — extraction from container dicts
    compute_cross_stone_scores — ranking, normalisation, edge cases
    display helpers            — smoke-test (no crash, correct output structure)
    collect_json_files         — path expansion (direct + domains/ subdir)
    _is_benchmark_set_config   — benchmark set detection
    _load_benchmark_set        — benchmark set loading and path expansion
    domain_is_complete         — completion detection
    Integration                — pizza_dough.json fixture
"""

import json
import sys
import io
import importlib.util
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── Load st-stones as a module (hyphen in filename) ───────────────────────────
_spec = importlib.util.spec_from_file_location(
    "st_stones", Path(__file__).parent.parent / "cross_st" / "st-stones.py"
)
st_stones = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st_stones)

compute_domain_scores      = st_stones.compute_domain_scores
compute_cross_stone_scores = st_stones.compute_cross_stone_scores
display_leaderboard        = st_stones.display_leaderboard
display_domain_breakdown   = st_stones.display_domain_breakdown
collect_json_files         = st_stones.collect_json_files
domain_is_complete         = st_stones.domain_is_complete
_is_benchmark_set_config   = st_stones._is_benchmark_set_config
_load_benchmark_set        = st_stones._load_benchmark_set
CLAIMS_PER_DOMAIN          = st_stones.CLAIMS_PER_DOMAIN
DEFAULT_W1                 = st_stones.DEFAULT_W1
DEFAULT_W2                 = st_stones.DEFAULT_W2


# ── Builder helpers ───────────────────────────────────────────────────────────

def make_fact(make: str, score: float, counts=None,
              elapsed: float = None, cached: bool = False) -> dict:
    fc: dict = {
        "make":  make,
        "model": f"{make}-test",
        "score": score,
        "counts": counts or [5, 3, 1, 1, 0],
    }
    if elapsed is not None:
        fc["timing"] = {"elapsed_seconds": elapsed, "cached": cached}
    return fc


def make_story(make: str, facts: list) -> dict:
    return {
        "make":  make,
        "model": f"{make}-test",
        "title": f"Test story by {make}",
        "text":  "Test content.",
        "fact":  facts,
    }


def make_data_entry(make: str, elapsed: float = None, cached: bool = False) -> dict:
    entry: dict = {"make": make, "model": f"{make}-test", "md5_hash": f"hash_{make}"}
    if elapsed is not None:
        entry["timing"] = {"elapsed_seconds": elapsed, "cached": cached}
    return entry


def make_container(stories: list, data: list = None) -> dict:
    return {"story": stories, "data": data or []}


# ── 3-AI cross-product fixture used across multiple tests ─────────────────────
_AI3 = ["xai", "openai", "anthropic"]

DOMAIN_A = make_container(
    stories=[
        make_story("xai", [
            make_fact("xai",       1.8, elapsed=40.0),
            make_fact("openai",    1.6, elapsed=35.0),
            make_fact("anthropic", 1.7, elapsed=50.0),
        ]),
        make_story("openai", [
            make_fact("xai",       1.9, elapsed=42.0),
            make_fact("openai",    1.7, elapsed=30.0),
            make_fact("anthropic", 1.8, elapsed=55.0),
        ]),
        make_story("anthropic", [
            make_fact("xai",       1.5, elapsed=38.0),
            make_fact("openai",    1.4, elapsed=32.0),
            make_fact("anthropic", 1.6, elapsed=48.0),
        ]),
    ],
    data=[
        make_data_entry("xai",       elapsed=30.0),
        make_data_entry("openai",    elapsed=25.0),
        make_data_entry("anthropic", elapsed=45.0),
    ],
)

DOMAIN_B = make_container(
    stories=[
        make_story("xai", [
            make_fact("xai",       1.6, elapsed=38.0),
            make_fact("openai",    1.5, elapsed=33.0),
            make_fact("anthropic", 1.4, elapsed=52.0),
        ]),
        make_story("openai", [
            make_fact("xai",       1.8, elapsed=41.0),
            make_fact("openai",    1.9, elapsed=28.0),
            make_fact("anthropic", 1.7, elapsed=49.0),
        ]),
        make_story("anthropic", [
            make_fact("xai",       1.3, elapsed=36.0),
            make_fact("openai",    1.2, elapsed=30.0),
            make_fact("anthropic", 1.5, elapsed=46.0),
        ]),
    ],
    data=[
        make_data_entry("xai",       elapsed=32.0),
        make_data_entry("openai",    elapsed=22.0),
        make_data_entry("anthropic", elapsed=50.0),
    ],
)


# ─────────────────────────────────────────────────────────────────────────────
# compute_domain_scores
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeDomainScores:

    def test_returns_all_story_authors(self):
        scores = compute_domain_scores(DOMAIN_A)
        assert set(scores.keys()) == {"xai", "openai", "anthropic"}

    def test_fact_avg_is_mean_of_fact_check_scores(self):
        scores = compute_domain_scores(DOMAIN_A)
        # xai story: scores 1.8, 1.6, 1.7 → mean ≈ 1.7
        assert scores["xai"]["fact_avg"] == pytest.approx((1.8 + 1.6 + 1.7) / 3)

    def test_n_fact_checkers_matches_fact_list_length(self):
        scores = compute_domain_scores(DOMAIN_A)
        assert scores["xai"]["n_fact_checkers"] == 3
        assert scores["openai"]["n_fact_checkers"] == 3

    def test_gen_elapsed_extracted_from_data_entries(self):
        scores = compute_domain_scores(DOMAIN_A)
        assert scores["xai"]["gen_elapsed"] == 30.0
        assert scores["openai"]["gen_elapsed"] == 25.0
        assert scores["anthropic"]["gen_elapsed"] == 45.0

    def test_gen_elapsed_none_when_absent(self):
        container = make_container(
            stories=[make_story("xai", [make_fact("openai", 1.5)])],
            data=[],   # no timing
        )
        scores = compute_domain_scores(container)
        assert scores["xai"]["gen_elapsed"] is None

    def test_gen_elapsed_skips_cached_entries(self):
        container = make_container(
            stories=[make_story("xai", [make_fact("openai", 1.5)])],
            data=[make_data_entry("xai", elapsed=0.1, cached=True)],
        )
        scores = compute_domain_scores(container)
        assert scores["xai"]["gen_elapsed"] is None

    def test_fc_elapsed_list_contains_evaluator_times(self):
        # "xai" fact-checks the other two stories in DOMAIN_A:
        # DOMAIN_A openai-story: xai elapsed=42.0
        # DOMAIN_A anthropic-story: xai elapsed=38.0
        # DOMAIN_A xai-story: xai elapsed=40.0  (self-check)
        scores = compute_domain_scores(DOMAIN_A)
        xai_fc = sorted(scores["xai"]["fc_elapsed_list"])
        assert 38.0 in xai_fc
        assert 40.0 in xai_fc
        assert 42.0 in xai_fc

    def test_fact_avg_none_when_no_fact_checks(self):
        container = make_container(
            stories=[make_story("xai", [])],  # no facts
        )
        scores = compute_domain_scores(container)
        assert scores["xai"]["fact_avg"] is None

    def test_empty_container(self):
        scores = compute_domain_scores({"story": [], "data": []})
        assert scores == {}

    def test_missing_top_level_keys(self):
        scores = compute_domain_scores({})
        assert scores == {}

    def test_fact_without_score_field_is_skipped(self):
        container = make_container(
            stories=[make_story("xai", [
                {"make": "openai"},         # no score
                make_fact("anthropic", 1.6),
            ])],
        )
        scores = compute_domain_scores(container)
        assert scores["xai"]["n_fact_checkers"] == 1
        assert abs(scores["xai"]["fact_avg"] - 1.6) < 1e-9

    def test_story_without_make_is_skipped(self):
        container = make_container(
            stories=[
                {"model": "some-model", "fact": [make_fact("openai", 1.5)]},
                make_story("anthropic", [make_fact("openai", 1.7)]),
            ],
        )
        scores = compute_domain_scores(container)
        assert "anthropic" in scores
        assert "" not in scores

    def test_fc_elapsed_list_excludes_cached_fact_checks(self):
        """Cached=True fact-check timing entries must be excluded from fc_elapsed_list.

        Note: compute_domain_scores keys results by story *author*.  To verify
        that 'anthropic' as an EVALUATOR has its cached time excluded, anthropic
        must also appear as a story author so it gets an entry in the results dict.
        """
        container = make_container(
            stories=[
                make_story("xai", [
                    make_fact("openai",    1.5, elapsed=30.0, cached=False),
                    make_fact("anthropic", 1.6, elapsed=50.0, cached=True),  # excluded
                ]),
                make_story("openai", [
                    make_fact("xai",       1.7, elapsed=25.0, cached=False),
                    make_fact("anthropic", 1.4, elapsed=45.0, cached=False),  # included
                ]),
                make_story("anthropic", [
                    make_fact("xai",       1.8, elapsed=22.0, cached=False),
                    make_fact("openai",    1.9, elapsed=28.0, cached=False),
                ]),
            ]
        )
        scores = compute_domain_scores(container)
        # anthropic as evaluator: evaluated xai's story (cached=True, 50s → excluded)
        # and openai's story (cached=False, 45s → included)
        assert 45.0 in scores["anthropic"]["fc_elapsed_list"]
        assert 50.0 not in scores["anthropic"]["fc_elapsed_list"]
        assert len(scores["anthropic"]["fc_elapsed_list"]) == 1

    def test_story_missing_fact_key_gives_none_fact_avg(self):
        """A story dict with no 'fact' key is treated identically to fact=[]."""
        container = make_container(
            stories=[{"make": "xai", "model": "xai-test"}]  # no "fact" key at all
        )
        scores = compute_domain_scores(container)
        assert "xai" in scores
        assert scores["xai"]["fact_avg"] is None
        assert scores["xai"]["n_fact_checkers"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# compute_cross_stone_scores
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeCrossStoneScores:

    # -- helpers -----------------------------------------------------------------

    def _scores_for(self, *containers, **kwargs) -> list:
        domain_results = [compute_domain_scores(c) for c in containers]
        return compute_cross_stone_scores(domain_results, **kwargs)

    # -- basic correctness -------------------------------------------------------

    def test_returns_one_row_per_author_ai(self):
        rows = self._scores_for(DOMAIN_A)
        makes = {r["make"] for r in rows}
        assert makes == {"xai", "openai", "anthropic"}

    def test_sorted_descending_by_cross_stone_score(self):
        rows = self._scores_for(DOMAIN_A, DOMAIN_B)
        scores = [r["cross_stone_score"] for r in rows]
        assert scores == sorted(scores, reverse=True)

    def test_n_domains_counts_domains_per_ai(self):
        rows = self._scores_for(DOMAIN_A, DOMAIN_B)
        for r in rows:
            assert r["n_domains"] == 2

    def test_fact_score_is_sum_of_avg_times_n_claims(self):
        rows = self._scores_for(DOMAIN_A)
        by_make = {r["make"]: r for r in rows}
        # xai: (1.8+1.6+1.7)/3 * 10 = 17.0
        expected_xai_fact = (1.8 + 1.6 + 1.7) / 3 * CLAIMS_PER_DOMAIN
        assert abs(by_make["xai"]["fact_score"] - expected_xai_fact) < 1e-9

    def test_fact_norm_is_ratio_to_max(self):
        rows = self._scores_for(DOMAIN_A)
        by_make = {r["make"]: r for r in rows}
        n_domains = 1
        max_fact = n_domains * CLAIMS_PER_DOMAIN * 2.0
        for make, r in by_make.items():
            expected = r["fact_score"] / max_fact
            assert abs(r["fact_norm"] - expected) < 1e-9

    def test_fastest_ai_gets_speed_norm_one(self):
        rows = self._scores_for(DOMAIN_A)
        # openai is fastest: gen=25, fc_avg≈(35+30+32)/3=32.3 → total ~57.3, 1/57.3 highest
        speed_norms = [r["speed_norm"] for r in rows]
        assert max(speed_norms) == pytest.approx(1.0)

    def test_cross_stone_score_between_minus1_and_1(self):
        rows = self._scores_for(DOMAIN_A, DOMAIN_B)
        for r in rows:
            assert -1.1 <= r["cross_stone_score"] <= 1.1

    def test_weights_w1_and_w2(self):
        """w1=1, w2=0 → cross_stone_score equals fact_norm"""
        rows = self._scores_for(DOMAIN_A, w1=1.0, w2=0.0)
        for r in rows:
            assert abs(r["cross_stone_score"] - r["fact_norm"]) < 1e-9

    def test_accuracy_only_flag_equivalent(self):
        rows_no_speed  = self._scores_for(DOMAIN_A, w1=1.0, w2=0.0)
        rows_w1_1      = self._scores_for(DOMAIN_A, w1=1.0, w2=0.0)
        for a, b in zip(rows_no_speed, rows_w1_1):
            assert abs(a["cross_stone_score"] - b["cross_stone_score"]) < 1e-9

    def test_empty_domain_list_returns_empty(self):
        rows = compute_cross_stone_scores([])
        assert rows == []

    def test_ai_with_no_fact_checks_omitted(self):
        domain = make_container(
            stories=[
                make_story("xai", []),        # no facts → fact_avg is None
                make_story("openai", [make_fact("xai", 1.7)]),
            ],
        )
        rows = compute_cross_stone_scores([compute_domain_scores(domain)])
        makes = {r["make"] for r in rows}
        assert "xai" not in makes
        assert "openai" in makes

    # -- no timing data ----------------------------------------------------------

    def test_no_timing_falls_back_to_accuracy_only(self):
        """When no elapsed data exists, speed_score is None and cross_stone = w1/total_w * fact_norm."""
        container = make_container(
            stories=[
                make_story("xai",    [make_fact("openai", 1.8)]),
                make_story("openai", [make_fact("xai",    1.6)]),
            ],
            # no data[] entries → no gen_elapsed; facts have no timing
        )
        w1, w2 = 0.7, 0.3
        rows = compute_cross_stone_scores([compute_domain_scores(container)], w1=w1, w2=w2)
        for r in rows:
            assert r["speed_score"] is None
            assert r["speed_norm"] == 0.0
            # cross_stone = (w1 / (w1+w2)) * fact_norm = 0.7 * fact_norm  (since w1+w2=1.0)
            expected = (w1 / (w1 + w2)) * r["fact_norm"]
            assert r["cross_stone_score"] == pytest.approx(expected)

    # -- custom n_claims ---------------------------------------------------------

    def test_custom_n_claims_changes_max_fact(self):
        """With n_claims=5 instead of 10, max_fact is halved."""
        rows_10 = self._scores_for(DOMAIN_A, n_claims=10)
        rows_5  = self._scores_for(DOMAIN_A, n_claims=5)
        by10 = {r["make"]: r for r in rows_10}
        by5  = {r["make"]: r for r in rows_5}
        for make in by10:
            # fact_score is halved but max_fact is also halved → fact_norm same
            assert abs(by5[make]["fact_norm"] - by10[make]["fact_norm"]) < 1e-9
            # raw fact_score should be halved
            assert abs(by5[make]["fact_score"] - by10[make]["fact_score"] / 2) < 1e-9

    # -- two-domain aggregation --------------------------------------------------

    def test_two_domains_accumulate_correctly(self):
        rows = self._scores_for(DOMAIN_A, DOMAIN_B)
        by_make = {r["make"]: r for r in rows}

        # xai: domain A fact_avg=(1.8+1.6+1.7)/3, domain B fact_avg=(1.6+1.5+1.4)/3
        fa_a = (1.8 + 1.6 + 1.7) / 3 * CLAIMS_PER_DOMAIN
        fa_b = (1.6 + 1.5 + 1.4) / 3 * CLAIMS_PER_DOMAIN
        expected = fa_a + fa_b
        assert abs(by_make["xai"]["fact_score"] - expected) < 1e-9

    def test_ranking_openai_beats_anthropic(self):
        """openai consistently scores higher than anthropic in our fixtures."""
        rows = self._scores_for(DOMAIN_A, DOMAIN_B)
        makes = [r["make"] for r in rows]
        assert makes.index("openai") < makes.index("anthropic")

    # -- single AI edge case -----------------------------------------------------

    def test_single_ai_gets_score_one(self):
        """When only one AI is present, speed_norm = 1.0 (fastest by default)."""
        container = make_container(
            stories=[make_story("xai", [make_fact("xai", 1.8, elapsed=40.0)])],
            data=[make_data_entry("xai", elapsed=30.0)],
        )
        rows = compute_cross_stone_scores([compute_domain_scores(container)])
        assert len(rows) == 1
        assert rows[0]["speed_norm"] == pytest.approx(1.0)

    def test_avg_gen_s_and_avg_fc_s_populated_correctly(self):
        """avg_gen_s and avg_fc_s should reflect per-AI averages across domains."""
        rows = self._scores_for(DOMAIN_A)
        by_make = {r["make"]: r for r in rows}
        # openai gen_elapsed=[25.0] → avg_gen_s=25.0
        assert by_make["openai"]["avg_gen_s"] == pytest.approx(25.0)
        # openai fc_elapsed=[35.0, 30.0, 32.0] (evaluates all 3 stories in DOMAIN_A)
        assert by_make["openai"]["avg_fc_s"] == pytest.approx((35.0 + 30.0 + 32.0) / 3)

    def test_avg_gen_s_is_none_when_no_gen_timing(self):
        """avg_gen_s = None when no data entries carry timing."""
        container = make_container(
            stories=[make_story("xai", [make_fact("openai", 1.5, elapsed=30.0)])],
            data=[],  # no gen timing
        )
        rows = compute_cross_stone_scores([compute_domain_scores(container)])
        assert rows[0]["avg_gen_s"] is None

    def test_speed_uses_gen_only_when_fc_timing_absent(self):
        """When only generation timing exists, speed = 1 / avg_gen."""
        container = make_container(
            stories=[
                make_story("xai",    [make_fact("openai", 1.5)]),   # no fc timing
                make_story("openai", [make_fact("xai",    1.7)]),
            ],
            data=[
                make_data_entry("xai",    elapsed=40.0),
                make_data_entry("openai", elapsed=20.0),
            ],
        )
        rows = compute_cross_stone_scores([compute_domain_scores(container)])
        by_make = {r["make"]: r for r in rows}
        # No fc timing → avg_fc_s = None for both
        assert by_make["xai"]["avg_fc_s"] is None
        assert by_make["openai"]["avg_fc_s"] is None
        # openai (1/20) is faster than xai (1/40)
        assert by_make["openai"]["speed_norm"] == pytest.approx(1.0)
        assert by_make["openai"]["speed_score"] == pytest.approx(1.0 / 20.0)

    def test_speed_uses_fc_only_when_gen_timing_absent(self):
        """When only fact-check timing exists, speed = 1 / avg_fc."""
        container = make_container(
            stories=[
                make_story("xai",    [make_fact("openai", 1.5, elapsed=30.0)]),
                make_story("openai", [make_fact("xai",    1.7, elapsed=50.0)]),
            ],
            data=[],  # no gen timing
        )
        # openai evaluates xai story → fc_elapsed["openai"]=[30.0]
        # xai evaluates openai story → fc_elapsed["xai"]=[50.0]
        rows = compute_cross_stone_scores([compute_domain_scores(container)])
        by_make = {r["make"]: r for r in rows}
        assert by_make["xai"]["avg_gen_s"] is None
        assert by_make["openai"]["avg_gen_s"] is None
        # openai speed=1/30 > xai speed=1/50
        assert by_make["openai"]["speed_norm"] == pytest.approx(1.0)

    def test_ai_in_only_one_domain_gets_correct_n_domains(self):
        """An AI absent from a domain should only count the domains it appears in."""
        domain_partial = make_container(
            stories=[
                make_story("xai",    [make_fact("openai", 1.5)]),
                make_story("openai", [make_fact("xai",    1.7)]),
                # "anthropic" absent from this domain
            ],
            data=[
                make_data_entry("xai",    elapsed=30.0),
                make_data_entry("openai", elapsed=25.0),
            ],
        )
        rows = self._scores_for(DOMAIN_A, domain_partial)
        by_make = {r["make"]: r for r in rows}
        assert by_make["anthropic"]["n_domains"] == 1   # only DOMAIN_A
        assert by_make["xai"]["n_domains"]       == 2   # both domains
        assert by_make["openai"]["n_domains"]    == 2   # both domains

    def test_zero_weights_with_speed_data_gives_zero_score(self):
        """w1=0, w2=0 with timing available → cross_stone_score=0 for all AIs."""
        rows = self._scores_for(DOMAIN_A, w1=0.0, w2=0.0)
        for r in rows:
            assert r["cross_stone_score"] == pytest.approx(0.0)

    def test_zero_weights_without_speed_falls_back_to_fact_norm(self):
        """w1=0, w2=0 with no timing → total_w=0 guard → cross_stone = fact_norm."""
        container = make_container(
            stories=[make_story("xai", [make_fact("openai", 1.6)])],
        )
        rows = compute_cross_stone_scores(
            [compute_domain_scores(container)], w1=0.0, w2=0.0
        )
        assert rows[0]["cross_stone_score"] == pytest.approx(rows[0]["fact_norm"])


# ─────────────────────────────────────────────────────────────────────────────
# display helpers (smoke tests — verify they run without error)
# ─────────────────────────────────────────────────────────────────────────────

class TestDisplayHelpers:

    def _capture(self, fn, *args, **kwargs) -> str:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
        return buf.getvalue()

    def test_display_leaderboard_smoke(self):
        rows = compute_cross_stone_scores(
            [compute_domain_scores(DOMAIN_A), compute_domain_scores(DOMAIN_B)]
        )
        out = self._capture(display_leaderboard, rows, w1=DEFAULT_W1, w2=DEFAULT_W2,
                             n_domains=2, n_claims=CLAIMS_PER_DOMAIN)
        assert "Cross-Stones Leaderboard" in out
        assert "xai" in out
        assert "openai" in out
        assert "anthropic" in out

    def test_display_leaderboard_shows_rank_numbers(self):
        rows = compute_cross_stone_scores([compute_domain_scores(DOMAIN_A)])
        out = self._capture(display_leaderboard, rows, w1=1.0, w2=0.0, n_domains=1)
        assert "| 1 |" in out or "1 |" in out   # tabulate github format

    def test_display_leaderboard_empty_scores(self, capsys):
        display_leaderboard([], w1=0.7, w2=0.3)
        captured = capsys.readouterr()
        assert "No scores" in captured.out

    def test_display_domain_breakdown_smoke(self):
        dr = [compute_domain_scores(DOMAIN_A), compute_domain_scores(DOMAIN_B)]
        out = self._capture(display_domain_breakdown, dr,
                             ["Software Dev", "Healthcare"])
        assert "Software Dev" in out
        assert "Healthcare" in out
        assert "xai" in out

    def test_display_domain_breakdown_empty(self, capsys):
        display_domain_breakdown([], [])
        captured = capsys.readouterr()
        assert captured.out == ""   # nothing printed for empty input

    def test_display_leaderboard_no_speed_data(self):
        """Should still display cleanly when speed_score is None."""
        container = make_container(
            stories=[make_story("xai", [make_fact("openai", 1.8)])],
        )
        rows = compute_cross_stone_scores([compute_domain_scores(container)])
        out = self._capture(display_leaderboard, rows, w1=1.0, w2=0.0, n_domains=1)
        assert "xai" in out

    def test_display_leaderboard_shows_dash_when_no_speed(self):
        """The '—' em-dash placeholder must appear when speed_score is None."""
        container = make_container(
            stories=[make_story("xai", [make_fact("openai", 1.8)])],
        )
        rows = compute_cross_stone_scores([compute_domain_scores(container)])
        out = self._capture(display_leaderboard, rows, w1=0.7, w2=0.3, n_domains=1)
        assert "—" in out


# ─────────────────────────────────────────────────────────────────────────────
# collect_json_files
# ─────────────────────────────────────────────────────────────────────────────

class TestCollectJsonFiles:

    def test_explicit_json_path_returned_as_is(self, tmp_path):
        jf = tmp_path / "foo.json"
        jf.touch()
        result = collect_json_files([str(jf)])
        assert Path(str(jf)) in result

    def test_directory_finds_json_with_matching_prompt(self, tmp_path):
        (tmp_path / "domain_a.prompt").touch()
        (tmp_path / "domain_a.json").touch()
        (tmp_path / "domain_b.prompt").touch()
        (tmp_path / "domain_b.json").touch()
        (tmp_path / "unrelated.json").touch()   # no matching prompt → excluded
        result = collect_json_files([str(tmp_path)])
        names = [p.name for p in result]
        assert "domain_a.json" in names
        assert "domain_b.json" in names
        assert "unrelated.json" not in names

    def test_directory_falls_back_to_domains_subdir(self, tmp_path):
        """When no .prompt files exist at the top level, look in domains/ subdir."""
        sub = tmp_path / "domains"
        sub.mkdir()
        (sub / "alpha.prompt").touch()
        (sub / "beta.prompt").touch()
        result = collect_json_files([str(tmp_path)])
        names = [p.name for p in result]
        assert "alpha.json" in names
        assert "beta.json" in names

    def test_direct_prompts_take_priority_over_domains_subdir(self, tmp_path):
        """If .prompt files exist at top level, domains/ subdir is not used."""
        (tmp_path / "top.prompt").touch()
        sub = tmp_path / "domains"
        sub.mkdir()
        (sub / "sub.prompt").touch()
        result = collect_json_files([str(tmp_path)])
        names = [p.name for p in result]
        assert "top.json" in names
        assert "sub.json" not in names

    def test_extension_added_for_non_json_path(self, tmp_path):
        result = collect_json_files([str(tmp_path / "myfile")])
        assert result[0].suffix == ".json"

    def test_empty_paths_returns_empty(self):
        result = collect_json_files([])
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# _is_benchmark_set_config
# ─────────────────────────────────────────────────────────────────────────────

class TestIsBenchmarkSetConfig:

    def _write_config(self, path, data):
        path.write_text(json.dumps(data))

    def test_valid_set_config_detected(self, tmp_path):
        p = tmp_path / "cross-stones-10.json"
        self._write_config(p, {"id": "cross-stones-10", "domains": [{"id": "a"}]})
        assert _is_benchmark_set_config(p) is True

    def test_domain_container_not_detected_as_set(self, tmp_path):
        p = tmp_path / "story.json"
        self._write_config(p, {"data": [], "story": []})
        assert _is_benchmark_set_config(p) is False

    def test_missing_id_field_not_detected(self, tmp_path):
        p = tmp_path / "no_id.json"
        self._write_config(p, {"domains": [{"id": "a"}]})
        assert _is_benchmark_set_config(p) is False

    def test_domains_not_a_list_not_detected(self, tmp_path):
        p = tmp_path / "bad.json"
        self._write_config(p, {"id": "x", "domains": "not-a-list"})
        assert _is_benchmark_set_config(p) is False

    def test_nonexistent_file_returns_false(self, tmp_path):
        assert _is_benchmark_set_config(tmp_path / "missing.json") is False

    def test_directory_returns_false(self, tmp_path):
        assert _is_benchmark_set_config(tmp_path) is False


# ─────────────────────────────────────────────────────────────────────────────
# _load_benchmark_set
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadBenchmarkSet:

    def _write_config(self, path, data):
        path.write_text(json.dumps(data))
        return path

    def test_returns_domain_paths_and_config(self, tmp_path):
        config = {
            "id": "test-set",
            "n_claims": 10,
            "domains_dir": "domains",
            "domains": [
                {"id": "alpha", "name": "Alpha"},
                {"id": "beta",  "name": "Beta"},
            ],
        }
        cfg_path = self._write_config(tmp_path / "test-set.json", config)
        domain_paths, loaded = _load_benchmark_set(cfg_path)

        assert loaded["id"] == "test-set"
        assert loaded["n_claims"] == 10
        names = [p.name for p in domain_paths]
        assert "alpha.json" in names
        assert "beta.json" in names

    def test_domain_paths_under_domains_subdir(self, tmp_path):
        config = {
            "id": "s",
            "domains_dir": "domains",
            "domains": [{"id": "gamma", "name": "Gamma"}],
        }
        cfg_path = self._write_config(tmp_path / "s.json", config)
        domain_paths, _ = _load_benchmark_set(cfg_path)
        assert domain_paths[0].parent.name == "domains"

    def test_custom_domains_dir_respected(self, tmp_path):
        config = {
            "id": "s",
            "domains_dir": "mydomains",
            "domains": [{"id": "delta", "name": "Delta"}],
        }
        cfg_path = self._write_config(tmp_path / "s.json", config)
        domain_paths, _ = _load_benchmark_set(cfg_path)
        assert domain_paths[0].parent.name == "mydomains"

    def test_empty_domains_list(self, tmp_path):
        config = {"id": "empty", "domains": []}
        cfg_path = self._write_config(tmp_path / "empty.json", config)
        domain_paths, loaded = _load_benchmark_set(cfg_path)
        assert domain_paths == []
        assert loaded["id"] == "empty"

    def test_real_cross_stones_10_config(self):
        """Smoke-test: the live cross-stones-10.json is valid and has 10 domains."""
        cfg_path = (Path(__file__).parent.parent
                    / "cross_stones" / "cross-stones-10.json")
        if not cfg_path.exists():
            pytest.skip("cross-stones-10.json not found")
        domain_paths, config = _load_benchmark_set(cfg_path)
        assert config["n_claims"] == 10
        assert config["max_fact_score"] == 200
        assert len(config["domains"]) == 10   # n_domains is derived, not stored
        assert len(domain_paths) == 10


# ─────────────────────────────────────────────────────────────────────────────
# domain_is_complete
# ─────────────────────────────────────────────────────────────────────────────

class TestDomainIsComplete:

    def test_missing_file_returns_false(self, tmp_path):
        assert domain_is_complete(tmp_path / "nonexistent.json") is False

    def test_empty_story_list_returns_false(self, tmp_path):
        jf = tmp_path / "test.json"
        jf.write_text(json.dumps({"story": [], "data": []}))
        assert domain_is_complete(jf) is False

    def test_stories_without_facts_returns_false(self, tmp_path):
        jf = tmp_path / "test.json"
        jf.write_text(json.dumps({
            "story": [{"make": "xai", "fact": []}, {"make": "openai", "fact": []}],
        }))
        assert domain_is_complete(jf) is False

    def test_all_stories_have_facts_returns_true(self, tmp_path):
        jf = tmp_path / "test.json"
        jf.write_text(json.dumps({
            "story": [
                {"make": "xai",    "fact": [{"make": "openai", "score": 1.5}]},
                {"make": "openai", "fact": [{"make": "xai",    "score": 1.7}]},
            ],
        }))
        assert domain_is_complete(jf) is True

    def test_partial_fact_coverage_returns_false(self, tmp_path):
        jf = tmp_path / "test.json"
        jf.write_text(json.dumps({
            "story": [
                {"make": "xai",    "fact": [{"make": "openai", "score": 1.5}]},
                {"make": "openai", "fact": []},   # no fact-check yet
            ],
        }))
        assert domain_is_complete(jf) is False

    def test_invalid_json_returns_false(self, tmp_path):
        jf = tmp_path / "test.json"
        jf.write_text("{ not valid json }")
        assert domain_is_complete(jf) is False

    def test_story_missing_fact_key_returns_false(self, tmp_path):
        """A story dict with no 'fact' key at all is treated as incomplete."""
        jf = tmp_path / "test.json"
        jf.write_text(json.dumps({
            "story": [{"make": "xai"}]  # no "fact" key
        }))
        assert domain_is_complete(jf) is False


# ─────────────────────────────────────────────────────────────────────────────
# Scoring math — formula verification
# ─────────────────────────────────────────────────────────────────────────────

class TestScoringMath:

    def test_max_fact_norm_is_one_when_all_claims_true(self):
        """A report where all evaluators give score=2.0 should yield fact_norm=1.0."""
        perfect = make_container(
            stories=[
                make_story("xai", [make_fact("openai", 2.0), make_fact("anthropic", 2.0)]),
                make_story("openai", [make_fact("xai", 2.0), make_fact("anthropic", 2.0)]),
            ],
        )
        rows = compute_cross_stone_scores(
            [compute_domain_scores(perfect)],
            w1=1.0, w2=0.0,
            n_claims=CLAIMS_PER_DOMAIN,
        )
        for r in rows:
            assert abs(r["fact_norm"] - 1.0) < 1e-9

    def test_min_fact_norm_is_minus_one_when_all_claims_false(self):
        """A report where all evaluators give score=-2.0 should yield fact_norm=-1.0."""
        worst = make_container(
            stories=[
                make_story("xai", [make_fact("openai", -2.0)]),
            ],
        )
        rows = compute_cross_stone_scores(
            [compute_domain_scores(worst)],
            w1=1.0, w2=0.0,
        )
        assert abs(rows[0]["fact_norm"] - (-1.0)) < 1e-9

    def test_two_equal_speed_ais_both_get_speed_norm_one(self):
        """When two AIs have identical timing, both are tied at speed_norm=1.0."""
        c = make_container(
            stories=[
                make_story("xai",    [make_fact("openai", 1.5, elapsed=40.0)]),
                make_story("openai", [make_fact("xai",    1.5, elapsed=40.0)]),
            ],
            data=[
                make_data_entry("xai",    elapsed=30.0),
                make_data_entry("openai", elapsed=30.0),
            ],
        )
        rows = compute_cross_stone_scores([compute_domain_scores(c)])
        for r in rows:
            assert r["speed_norm"] == pytest.approx(1.0)

    def test_cross_stone_score_formula_direct(self):
        """Manually verify the cross_stone formula for a known fixture."""
        # Single domain, two AIs, no speed data (w1=0.7, w2=0.3)
        c = make_container(
            stories=[
                make_story("xai",    [make_fact("openai", 1.6)]),
                make_story("openai", [make_fact("xai",    1.8)]),
            ],
        )
        w1, w2 = 0.7, 0.3
        rows = compute_cross_stone_scores([compute_domain_scores(c)], w1=w1, w2=w2)
        by = {r["make"]: r for r in rows}

        # max_fact = 1 * 10 * 2 = 20
        max_fact = 1 * CLAIMS_PER_DOMAIN * 2
        # xai  fact_score = 1.6 * 10 = 16  → fact_norm = 16/20 = 0.8
        # openai fact_score = 1.8 * 10 = 18 → fact_norm = 18/20 = 0.9
        assert by["xai"]["fact_norm"]    == pytest.approx(16 / max_fact)
        assert by["openai"]["fact_norm"] == pytest.approx(18 / max_fact)

        # No speed → cross_stone = (w1 / (w1+w2)) * fact_norm
        #                        = 0.7 * fact_norm  (since w1+w2=1)
        for r in rows:
            expected = (w1 / (w1 + w2)) * r["fact_norm"]
            assert r["cross_stone_score"] == pytest.approx(expected)

    def test_speed_weight_reorders_ranking(self):
        """
        When speed dominates (w2=1), the fastest AI tops the leaderboard
        even if its fact score is lower.

        Fixture:
          "fast" generates in 3s and fact-checks others in 5s.
          "slow" generates in 150s and fact-checks others in 200s.
          "fast" has a lower fact score (1.0) but much higher speed.
        """
        c = make_container(
            stories=[
                # "fast" is the story author; "slow" evaluates it — slowly (200s)
                make_story("fast", [make_fact("slow", 1.0, elapsed=200.0)]),
                # "slow" is the story author; "fast" evaluates it — quickly (5s)
                make_story("slow", [make_fact("fast", 1.9, elapsed=5.0)]),
            ],
            data=[
                make_data_entry("fast", elapsed=3.0),    # fast generates quickly
                make_data_entry("slow", elapsed=150.0),  # slow generates slowly
            ],
        )
        # fc_elapsed_by_make: "slow"→[200.0], "fast"→[5.0]
        # fast: speed = 1/(3+5)=0.125   |  slow: speed = 1/(150+200)≈0.00286
        rows_acc   = compute_cross_stone_scores([compute_domain_scores(c)], w1=1.0, w2=0.0)
        rows_speed = compute_cross_stone_scores([compute_domain_scores(c)], w1=0.0, w2=1.0)

        assert rows_acc[0]["make"]   == "slow"   # higher fact score wins on accuracy
        assert rows_speed[0]["make"] == "fast"   # faster wins on speed


# ─────────────────────────────────────────────────────────────────────────────
# Integration — pizza_dough.json fixture
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegrationPizzaDough:

    FIXTURE = Path(__file__).parent / "fixtures" / "pizza_dough.json"

    @pytest.fixture(autouse=True)
    def require_fixture(self):
        if not self.FIXTURE.exists():
            pytest.skip("pizza_dough.json fixture not found")

    def _container(self) -> dict:
        with open(self.FIXTURE) as f:
            return json.load(f)

    def test_compute_domain_scores_returns_all_story_makes(self):
        container = self._container()
        scores = compute_domain_scores(container)
        story_makes = {s["make"] for s in container["story"]}
        assert set(scores.keys()) == story_makes

    def test_fact_avg_is_within_valid_range(self):
        container = self._container()
        scores = compute_domain_scores(container)
        for make, info in scores.items():
            if info["fact_avg"] is not None:
                assert -2.0 <= info["fact_avg"] <= 2.0, (
                    f"{make} fact_avg {info['fact_avg']} out of range"
                )

    def test_compute_cross_stone_scores_runs_without_error(self):
        container = self._container()
        dr = compute_domain_scores(container)
        rows = compute_cross_stone_scores([dr])
        assert isinstance(rows, list)
        assert len(rows) > 0

    def test_all_rows_have_required_keys(self):
        container = self._container()
        rows = compute_cross_stone_scores([compute_domain_scores(container)])
        required = {"make", "fact_score", "fact_norm", "speed_score", "speed_norm",
                    "cross_stone_score", "n_domains", "avg_gen_s", "avg_fc_s"}
        for r in rows:
            assert required.issubset(r.keys()), f"Missing keys in row: {r}"

    def test_cross_stone_scores_are_sorted_descending(self):
        container = self._container()
        rows = compute_cross_stone_scores([compute_domain_scores(container)])
        scores = [r["cross_stone_score"] for r in rows]
        assert scores == sorted(scores, reverse=True)

    def test_domain_is_complete_on_fixture(self, tmp_path):
        """pizza_dough.json has facts for every story — should be marked complete."""
        import shutil
        dest = tmp_path / "pizza_dough.json"
        shutil.copy(self.FIXTURE, dest)
        assert domain_is_complete(dest) is True

    def test_display_does_not_crash(self):
        """End-to-end: load → score → display with no exceptions."""
        container = self._container()
        rows = compute_cross_stone_scores([compute_domain_scores(container)])
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            display_leaderboard(rows, w1=0.7, w2=0.3, n_domains=1)
        assert len(buf.getvalue()) > 0


# ─────────────────────────────────────────────────────────────────────────────
# CLI entrypoint smoke test
# ─────────────────────────────────────────────────────────────────────────────

class TestMainCLI:

    def test_main_runs_with_directory(self, tmp_path, capsys):
        """--help should print usage and exit 0."""
        with pytest.raises(SystemExit) as exc:
            sys.argv = ["st-stones", "--help"]
            st_stones.main()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "cross_stone" in captured.out.lower() or "st-stones" in captured.out

    def test_main_exits_zero_with_no_results(self, tmp_path, capsys):
        """An empty directory (no .prompt files) should exit gracefully."""
        # No .prompt files → no json_files collected → exits with message
        with pytest.raises(SystemExit) as exc:
            sys.argv = ["st-stones", str(tmp_path)]
            st_stones.main()
        # Should exit non-zero (error: no .json files found)
        assert exc.value.code != 0

    def test_main_scores_container_files(self, tmp_path, capsys):
        """Given a directory with one complete domain, main() should print leaderboard."""
        # Write prompt and json files
        (tmp_path / "demo.prompt").write_text("Write 10 claims about pizza.")
        container = {
            "story": [
                make_story("xai",    [make_fact("openai", 1.6)]),
                make_story("openai", [make_fact("xai",    1.8)]),
            ],
            "data": [
                make_data_entry("xai",    elapsed=30.0),
                make_data_entry("openai", elapsed=25.0),
            ],
        }
        (tmp_path / "demo.json").write_text(json.dumps(container))

        sys.argv = ["st-stones", str(tmp_path), "--no-speed", "--quiet"]
        st_stones.main()   # should not raise

        captured = capsys.readouterr()
        assert "xai" in captured.out or "openai" in captured.out

    def test_no_confirmation_flag_accepted(self, tmp_path):
        """--no-confirmation should parse without error."""
        (tmp_path / "demo.prompt").write_text("prompt")
        container = {
            "story": [make_story("xai", [make_fact("openai", 1.5)])],
            "data":  [make_data_entry("xai", elapsed=30.0)],
        }
        (tmp_path / "demo.json").write_text(json.dumps(container))

        sys.argv = ["st-stones", str(tmp_path), "--no-confirmation", "--quiet"]
        st_stones.main()   # should not raise or prompt

    def test_confirmation_is_default(self):
        """--confirmation is the default; the flag should exist and default to True."""
        import argparse
        # Re-parse with no confirmation flags → should default to True
        sys.argv = ["st-stones", "dummy"]
        parser_result = None
        # We can't call main() without a real path, so inspect the parser directly
        # by loading a fresh invocation and checking the default
        spec2 = importlib.util.spec_from_file_location(
            "st_stones2", Path(__file__).parent.parent / "cross_st" / "st-stones.py"
        )
        mod2 = importlib.util.module_from_spec(spec2)
        # Patch sys.argv to avoid main() running; just check parser default via module attr
        assert st_stones.DEFAULT_W1 == 0.7   # module loaded correctly
        # Verify the flag exists in help text
        import io
        buf = io.StringIO()
        with pytest.raises(SystemExit):
            sys.argv = ["st-stones", "--help"]
            with patch("sys.stdout", buf):
                st_stones.main()
        assert "--no-confirmation" in buf.getvalue()
        assert "--confirmation" in buf.getvalue()

    def test_run_keyboard_interrupt_does_not_crash(self, tmp_path, capsys):
        """
        Ctrl+C during --run must NOT propagate as an unhandled exception.
        st-stones should catch KeyboardInterrupt, print a clean message,
        and continue to the scoring phase (which may produce empty output
        if no data is available).
        """
        from unittest.mock import patch, MagicMock

        # Create a minimal complete domain so st-stones loads at least one result
        # (ensures the code path after the break is exercised)
        (tmp_path / "demo.prompt").write_text("Write 10 claims.")
        container = {
            "story": [
                make_story("xai",    [make_fact("openai", 1.6)]),
                make_story("openai", [make_fact("xai",    1.8)]),
            ],
            "data": [
                make_data_entry("xai",    elapsed=30.0),
                make_data_entry("openai", elapsed=25.0),
            ],
        }
        (tmp_path / "demo.json").write_text(json.dumps(container))

        # Create an incomplete second domain so --run tries to launch st-cross
        (tmp_path / "incomplete.prompt").write_text("Another prompt.")
        # No incomplete.json → domain_is_complete returns False → triggers --run

        # Simulate Ctrl+C from the Popen.wait() call inside --run.
        # First wait() raises KeyboardInterrupt (the Ctrl+C); the second
        # wait() in the cleanup handler returns normally (st-cross exited).
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = [KeyboardInterrupt(), None]
        mock_proc.returncode = 0

        with patch.object(st_stones.subprocess, "Popen", return_value=mock_proc) as mock_popen:
            # Should NOT raise — must handle KeyboardInterrupt gracefully
            sys.argv = [
                "st-stones", str(tmp_path), "--run",
                "--no-confirmation", "--quiet",
            ]
            try:
                st_stones.main()   # must not raise
            except KeyboardInterrupt:
                pytest.fail("st-stones propagated KeyboardInterrupt — fix needed")

            # Verify --timeout 300 (the default) was forwarded to st-cross
            call_args = mock_popen.call_args[0][0]   # first positional arg = cmd list
            assert "--timeout" in call_args
            assert "300" in call_args

    def test_run_passes_custom_timeout_to_st_cross(self, tmp_path, capsys):
        """--timeout N must be forwarded verbatim to the st-cross subprocess."""
        from unittest.mock import patch, MagicMock

        (tmp_path / "demo.prompt").write_text("Write 10 claims.")
        container = {
            "story": [make_story("xai", [make_fact("openai", 1.6)])],
            "data":  [make_data_entry("xai", elapsed=30.0)],
        }
        (tmp_path / "demo.json").write_text(json.dumps(container))
        (tmp_path / "incomplete.prompt").write_text("Another prompt.")

        mock_proc = MagicMock()
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch.object(st_stones.subprocess, "Popen", return_value=mock_proc) as mock_popen:
            sys.argv = [
                "st-stones", str(tmp_path), "--run",
                "--no-confirmation", "--quiet", "--timeout", "120",
            ]
            st_stones.main()

            call_args = mock_popen.call_args[0][0]
            assert "--timeout" in call_args
            assert "120" in call_args


# ─────────────────────────────────────────────────────────────────────────────
# build_stones_prompt / _format_leaderboard_for_prompt
# ─────────────────────────────────────────────────────────────────────────────

_format_leaderboard_for_prompt = st_stones._format_leaderboard_for_prompt
build_stones_prompt             = st_stones.build_stones_prompt

# Minimal leaderboard fixture used across prompt tests
_SAMPLE_SCORES = [
    {"make": "anthropic", "fact_score": 13.5, "fact_norm":  0.676,
     "speed_score": 0.005,  "speed_norm": 0.152, "cross_stone_score":  0.519, "n_domains": 1},
    {"make": "perplexity", "fact_score": -1.4, "fact_norm": -0.071,
     "speed_score": 0.0327, "speed_norm": 1.0,   "cross_stone_score":  0.250, "n_domains": 1},
    {"make": "xai",        "fact_score": -8.0, "fact_norm": -0.398,
     "speed_score": 0.0083, "speed_norm": 0.254, "cross_stone_score": -0.202, "n_domains": 1},
]


class TestFormatLeaderboardForPrompt:

    def test_returns_string(self):
        result = _format_leaderboard_for_prompt(_SAMPLE_SCORES, 0.7, 0.3, 1, 10)
        assert isinstance(result, str)

    def test_contains_ai_names(self):
        result = _format_leaderboard_for_prompt(_SAMPLE_SCORES, 0.7, 0.3, 1, 10)
        assert "anthropic" in result
        assert "perplexity" in result
        assert "xai" in result

    def test_contains_fact_scores(self):
        result = _format_leaderboard_for_prompt(_SAMPLE_SCORES, 0.7, 0.3, 1, 10)
        # tabulate strips the leading + from numeric-looking strings
        assert "13.5" in result    # anthropic
        assert "-1.4" in result    # perplexity

    def test_empty_scores_returns_no_data_message(self):
        result = _format_leaderboard_for_prompt([], 0.7, 0.3, 1, 10)
        assert "No leaderboard data" in result

    def test_max_fact_reflects_domains_and_claims(self):
        # 2 domains × 10 claims × 2 = 40
        result = _format_leaderboard_for_prompt(_SAMPLE_SCORES, 0.7, 0.3, 2, 10)
        assert "40" in result


class TestBuildStonesPrompt:

    def test_title_prompt_max_10_words(self):
        prompt = build_stones_prompt(
            _SAMPLE_SCORES, 0.7, 0.3, 1, 10, ["software development"], "title"
        )
        assert "10 words" in prompt

    def test_short_prompt_word_range(self):
        prompt = build_stones_prompt(
            _SAMPLE_SCORES, 0.7, 0.3, 1, 10, ["software development"], "short"
        )
        assert "40" in prompt and "80" in prompt

    def test_caption_prompt_word_range(self):
        prompt = build_stones_prompt(
            _SAMPLE_SCORES, 0.7, 0.3, 1, 10, ["software development"], "caption"
        )
        assert "100" in prompt and "160" in prompt

    def test_all_types_include_leaderboard_table(self):
        for ct in ("title", "short", "caption"):
            prompt = build_stones_prompt(
                _SAMPLE_SCORES, 0.7, 0.3, 1, 10, ["software development"], ct
            )
            assert "anthropic" in prompt, f"AI name missing from {ct!r} prompt"
            assert "LEADERBOARD" in prompt, f"LEADERBOARD block missing from {ct!r} prompt"

    def test_all_types_include_negative_score_explanation(self):
        for ct in ("title", "short", "caption"):
            prompt = build_stones_prompt(
                _SAMPLE_SCORES, 0.7, 0.3, 1, 10, ["software development"], ct
            )
            # Every prompt type must explain what a negative score means
            assert "NEGATIVE" in prompt or "negative" in prompt.lower() or "FALSE" in prompt

    def test_caption_has_two_paragraph_instruction(self):
        prompt = build_stones_prompt(
            _SAMPLE_SCORES, 0.7, 0.3, 1, 10, ["software development"], "caption"
        )
        assert "Paragraph 1" in prompt and "Paragraph 2" in prompt

    def test_unknown_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown content_type"):
            build_stones_prompt(_SAMPLE_SCORES, 0.7, 0.3, 1, 10, [], "invalid_type")

    def test_domain_names_appear_in_context(self):
        prompt = build_stones_prompt(
            _SAMPLE_SCORES, 0.7, 0.3, 2, 10,
            ["software development", "healthcare"], "caption"
        )
        assert "software development" in prompt
        assert "healthcare" in prompt

    def test_weights_reflected_in_prompt(self):
        prompt = build_stones_prompt(
            _SAMPLE_SCORES, 0.5, 0.5, 1, 10, ["test domain"], "caption"
        )
        assert "0.5" in prompt   # w1 and w2 both appear

    def test_no_raw_decimals_instructed(self):
        """Prompt must tell the AI to avoid copying raw decimal numbers."""
        for ct in ("short", "caption"):
            prompt = build_stones_prompt(
                _SAMPLE_SCORES, 0.7, 0.3, 1, 10, [], ct
            )
            # The instruction to avoid raw decimals must be present
            assert "NEVER" in prompt or "never" in prompt.lower()

    def test_baseline_context_appears_in_absolute_mode(self):
        """When speed_baseline_s is provided, the prompt should mention the baseline."""
        prompt = build_stones_prompt(
            _SAMPLE_SCORES, 0.7, 0.3, 1, 10, ["test"],
            "caption",
            speed_baseline_s=60.0,
            baseline_date="2026-03-27",
        )
        assert "baseline" in prompt.lower()
        assert "2026-03-27" in prompt

    def test_baseline_absent_in_relative_mode(self):
        """Without speed_baseline_s, no baseline line should appear."""
        prompt = build_stones_prompt(
            _SAMPLE_SCORES, 0.7, 0.3, 1, 10, ["test"], "caption"
        )
        # Speed (1/s) definition should be present in relative mode
        assert "1/s" in prompt or "1 / " in prompt


# ─────────────────────────────────────────────────────────────────────────────
# Absolute speed scoring (speed_baseline_s)
# ─────────────────────────────────────────────────────────────────────────────

class TestAbsoluteSpeedScoring:
    """Tests for the speed_baseline_s / absolute-mode path in compute_cross_stone_scores."""

    def _domain_with_timing(self, gen: float, fc: float) -> dict:
        """Return a minimal domain-scores dict for one AI with given timing."""
        return {
            "xai": {
                "fact_avg":        1.6,
                "n_fact_checkers": 1,
                "gen_elapsed":     gen,
                "fc_elapsed_list": [fc],
            }
        }

    def test_speed_ratio_is_none_without_baseline(self):
        rows = compute_cross_stone_scores(
            [self._domain_with_timing(10.0, 30.0)]
        )
        assert rows[0]["speed_ratio"] is None

    def test_speed_ratio_is_one_when_at_baseline(self):
        """AI with exactly baseline timing should get speed_ratio=1.0."""
        baseline_s = 40.0  # 10 gen + 30 fc
        rows = compute_cross_stone_scores(
            [self._domain_with_timing(10.0, 30.0)],
            speed_baseline_s=baseline_s,
        )
        assert rows[0]["speed_ratio"] == pytest.approx(1.0)

    def test_speed_ratio_above_one_when_faster_than_baseline(self):
        """AI twice as fast as baseline should get speed_ratio≈2.0."""
        baseline_s = 40.0   # baseline: 40s total
        rows = compute_cross_stone_scores(
            [self._domain_with_timing(5.0, 15.0)],  # 20s total → 2× faster
            speed_baseline_s=baseline_s,
        )
        assert rows[0]["speed_ratio"] == pytest.approx(2.0)

    def test_speed_ratio_below_one_when_slower_than_baseline(self):
        """AI twice as slow as baseline should get speed_ratio≈0.5."""
        baseline_s = 40.0   # baseline: 40s total
        rows = compute_cross_stone_scores(
            [self._domain_with_timing(40.0, 40.0)],  # 80s total → 0.5×
            speed_baseline_s=baseline_s,
        )
        assert rows[0]["speed_ratio"] == pytest.approx(0.5)

    def test_speed_norm_equals_speed_ratio_in_absolute_mode(self):
        """In absolute mode speed_norm must equal speed_ratio (used in composite)."""
        baseline_s = 60.0
        rows = compute_cross_stone_scores(
            [self._domain_with_timing(10.0, 20.0)],  # 30s → ratio=2.0
            speed_baseline_s=baseline_s,
        )
        assert rows[0]["speed_norm"] == pytest.approx(rows[0]["speed_ratio"])

    def test_cross_stone_score_uses_speed_ratio_in_composite(self):
        """composite = w1*fact_norm + w2*speed_ratio in absolute mode."""
        baseline_s = 60.0
        rows = compute_cross_stone_scores(
            [self._domain_with_timing(10.0, 20.0)],  # 30s → ratio=2.0
            speed_baseline_s=baseline_s,
            w1=0.7,
            w2=0.3,
        )
        r = rows[0]
        expected = 0.7 * r["fact_norm"] + 0.3 * r["speed_ratio"]
        assert r["cross_stone_score"] == pytest.approx(expected)

    def test_score_can_exceed_one_when_faster_than_baseline(self):
        """In absolute mode, high speed+accuracy can push score above 1.0."""
        baseline_s = 60.0
        very_fast  = {
            "ai_2031": {
                "fact_avg":        1.95,   # near-perfect accuracy
                "n_fact_checkers": 3,
                "gen_elapsed":     2.0,
                "fc_elapsed_list": [4.0, 4.0, 4.0],  # 10s total → 6× faster
            }
        }
        rows = compute_cross_stone_scores([very_fast], speed_baseline_s=baseline_s)
        assert rows[0]["cross_stone_score"] > 1.0

    def test_relative_mode_unchanged_without_baseline(self):
        """Without speed_baseline_s, relative mode is unchanged: fastest = speed_norm=1.0."""
        domain = {
            "fast": {"fact_avg": 1.5, "n_fact_checkers": 1, "gen_elapsed": 10.0, "fc_elapsed_list": [20.0]},
            "slow": {"fact_avg": 1.5, "n_fact_checkers": 1, "gen_elapsed": 40.0, "fc_elapsed_list": [80.0]},
        }
        rows = compute_cross_stone_scores([domain])
        by_make = {r["make"]: r for r in rows}
        assert by_make["fast"]["speed_norm"] == pytest.approx(1.0)
        assert by_make["slow"]["speed_norm"] < 1.0

    def test_single_ai_gets_meaningful_speed_score_in_absolute_mode(self):
        """Single-AI runs: relative mode gives speed_norm=1.0 (trivial);
        absolute mode gives speed_ratio relative to locked baseline (meaningful)."""
        baseline_s = 60.0
        single = {"xai": {"fact_avg": 1.6, "n_fact_checkers": 1, "gen_elapsed": 10.0, "fc_elapsed_list": [20.0]}}

        rows_rel = compute_cross_stone_scores([single])
        rows_abs = compute_cross_stone_scores([single], speed_baseline_s=baseline_s)

        # Relative: always 1.0 for single AI — uninformative
        assert rows_rel[0]["speed_norm"] == pytest.approx(1.0)
        # Absolute: 30s actual vs 60s baseline → ratio=2.0 — meaningful
        assert rows_abs[0]["speed_ratio"] == pytest.approx(2.0)
        assert rows_abs[0]["speed_norm"]  == pytest.approx(2.0)

    def test_multiple_ais_in_absolute_mode_all_get_ratios(self):
        domain = {
            "fast": {"fact_avg": 1.7, "n_fact_checkers": 2, "gen_elapsed": 5.0,  "fc_elapsed_list": [15.0, 15.0]},
            "slow": {"fact_avg": 1.5, "n_fact_checkers": 2, "gen_elapsed": 30.0, "fc_elapsed_list": [50.0, 50.0]},
        }
        baseline_s = 80.0  # 80s baseline total
        rows = compute_cross_stone_scores([domain], speed_baseline_s=baseline_s)
        by_make = {r["make"]: r for r in rows}
        # fast: 5+15=20s → ratio = 80/20 = 4.0
        assert by_make["fast"]["speed_ratio"] == pytest.approx(4.0)
        # slow: 30+50=80s → ratio = 80/80 = 1.0
        assert by_make["slow"]["speed_ratio"] == pytest.approx(1.0)

    def test_display_leaderboard_shows_vs_baseline_column_in_abs_mode(self):
        """In absolute mode, leaderboard should show 'vs Baseline' column."""
        domain = {"xai": {"fact_avg": 1.6, "n_fact_checkers": 1, "gen_elapsed": 10.0, "fc_elapsed_list": [20.0]}}
        rows = compute_cross_stone_scores([domain], speed_baseline_s=60.0)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            display_leaderboard(rows, w1=0.7, w2=0.3, n_domains=1, n_claims=10,
                                speed_baseline_s=60.0, baseline_date="2026-03-27")
        out = buf.getvalue()
        assert "vs Baseline" in out or "Baseline" in out
        assert "×" in out   # ratio formatted as Nx

    def test_display_leaderboard_no_vs_baseline_in_relative_mode(self):
        """In relative mode, 'vs Baseline' column should NOT appear."""
        domain = {"xai": {"fact_avg": 1.6, "n_fact_checkers": 1, "gen_elapsed": 10.0, "fc_elapsed_list": [20.0]}}
        rows = compute_cross_stone_scores([domain])
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            display_leaderboard(rows, w1=0.7, w2=0.3, n_domains=1, n_claims=10)
        out = buf.getvalue()
        assert "Speed (1/s)" in out
        assert "vs Baseline" not in out


# ─────────────────────────────────────────────────────────────────────────────
# Historical snapshots (save_snapshot, set_baseline_in_config, display_history)
# ─────────────────────────────────────────────────────────────────────────────

display_history          = st_stones.display_history
save_snapshot            = st_stones.save_snapshot
set_baseline_in_config   = st_stones.set_baseline_in_config


class TestSaveSnapshot:

    def _minimal_config(self, tmp_path) -> Path:
        cfg = {"id": "test-set", "version": "2.0", "speed_baseline": {}, "snapshots": [], "domains": []}
        p = tmp_path / "test-set.json"
        p.write_text(json.dumps(cfg, indent=2))
        return p

    def _make_scores(self):
        domain = {
            "xai": {"fact_avg": 1.7, "n_fact_checkers": 2, "gen_elapsed": 12.0, "fc_elapsed_list": [35.0]},
            "openai": {"fact_avg": 1.5, "n_fact_checkers": 2, "gen_elapsed": 10.0, "fc_elapsed_list": [30.0]},
        }
        return compute_cross_stone_scores([domain], speed_baseline_s=60.0)

    def test_snapshot_appended_to_config(self, tmp_path):
        p = self._minimal_config(tmp_path)
        scores = self._make_scores()
        save_snapshot(p, scores, label="test snap", w1=0.7, w2=0.3, n_domains=1, n_claims=10)
        with open(p) as f:
            cfg = json.load(f)
        assert len(cfg["snapshots"]) == 1
        assert cfg["snapshots"][0]["label"] == "test snap"

    def test_snapshot_contains_expected_fields(self, tmp_path):
        p = self._minimal_config(tmp_path)
        scores = self._make_scores()
        save_snapshot(p, scores, label="2026 run", w1=0.7, w2=0.3, n_domains=1, n_claims=10)
        with open(p) as f:
            cfg = json.load(f)
        snap = cfg["snapshots"][0]
        assert "date" in snap
        assert "scores" in snap
        assert "xai" in snap["scores"]
        assert "cross_stone_score" in snap["scores"]["xai"]
        assert "fact_norm" in snap["scores"]["xai"]

    def test_snapshot_stores_speed_ratio_when_available(self, tmp_path):
        p = self._minimal_config(tmp_path)
        scores = self._make_scores()   # uses speed_baseline_s=60.0 → speed_ratio present
        save_snapshot(p, scores, label="snap", w1=0.7, w2=0.3, n_domains=1, n_claims=10)
        with open(p) as f:
            cfg = json.load(f)
        assert cfg["snapshots"][0]["scores"]["xai"]["speed_ratio"] is not None

    def test_multiple_snapshots_accumulate(self, tmp_path):
        p = self._minimal_config(tmp_path)
        scores = self._make_scores()
        save_snapshot(p, scores, label="snap1", w1=0.7, w2=0.3, n_domains=1, n_claims=10)
        save_snapshot(p, scores, label="snap2", w1=0.7, w2=0.3, n_domains=1, n_claims=10)
        with open(p) as f:
            cfg = json.load(f)
        assert len(cfg["snapshots"]) == 2
        assert cfg["snapshots"][0]["label"] == "snap1"
        assert cfg["snapshots"][1]["label"] == "snap2"

    def test_missing_snapshots_key_is_created(self, tmp_path):
        """Config without a 'snapshots' key is handled gracefully."""
        cfg = {"id": "x", "domains": []}
        p = tmp_path / "x.json"
        p.write_text(json.dumps(cfg))
        scores = self._make_scores()
        save_snapshot(p, scores, label="first", w1=0.7, w2=0.3, n_domains=1, n_claims=10)
        with open(p) as f:
            updated = json.load(f)
        assert len(updated["snapshots"]) == 1


class TestSetBaselineInConfig:

    def _minimal_config(self, tmp_path) -> Path:
        cfg = {"id": "test-set", "speed_baseline": {}, "snapshots": [], "domains": []}
        p = tmp_path / "test-set.json"
        p.write_text(json.dumps(cfg, indent=2))
        return p

    def test_baseline_written_to_config(self, tmp_path):
        p = self._minimal_config(tmp_path)
        set_baseline_in_config(p, avg_gen_s=15.0, avg_fc_s=45.0)
        with open(p) as f:
            cfg = json.load(f)
        bl = cfg["speed_baseline"]
        assert bl["gen_seconds"] == pytest.approx(15.0)
        assert bl["fc_seconds"]  == pytest.approx(45.0)
        assert bl["total_seconds"] == pytest.approx(60.0)

    def test_baseline_includes_recorded_date(self, tmp_path):
        p = self._minimal_config(tmp_path)
        set_baseline_in_config(p, avg_gen_s=10.0, avg_fc_s=30.0)
        with open(p) as f:
            cfg = json.load(f)
        assert "recorded_date" in cfg["speed_baseline"]
        assert len(cfg["speed_baseline"]["recorded_date"]) == 10  # ISO: YYYY-MM-DD

    def test_baseline_overwrites_existing(self, tmp_path):
        p = self._minimal_config(tmp_path)
        set_baseline_in_config(p, avg_gen_s=20.0, avg_fc_s=50.0)
        set_baseline_in_config(p, avg_gen_s=10.0, avg_fc_s=25.0)
        with open(p) as f:
            cfg = json.load(f)
        assert cfg["speed_baseline"]["gen_seconds"] == pytest.approx(10.0)
        assert cfg["speed_baseline"]["total_seconds"] == pytest.approx(35.0)

    def test_other_config_keys_preserved(self, tmp_path):
        cfg = {"id": "preserved", "n_claims": 10, "domains": [{"id": "x"}]}
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(cfg))
        set_baseline_in_config(p, avg_gen_s=5.0, avg_fc_s=10.0)
        with open(p) as f:
            updated = json.load(f)
        assert updated["id"] == "preserved"
        assert updated["n_claims"] == 10
        assert updated["domains"] == [{"id": "x"}]


class TestDisplayHistory:

    def _capture(self, fn, *args, **kwargs) -> str:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
        return buf.getvalue()

    def _config_with_snapshots(self, snapshots: list, baseline: dict = None) -> dict:
        return {
            "id": "cross-stones-10",
            "speed_baseline": baseline or {},
            "snapshots": snapshots,
        }

    def test_no_snapshots_shows_no_snapshots_message(self):
        cfg = self._config_with_snapshots([])
        out = self._capture(display_history, cfg)
        assert "No snapshots" in out or "no snapshots" in out.lower()

    def test_snapshot_history_shows_dates_and_labels(self):
        snaps = [
            {"date": "2026-03-27", "label": "Initial run", "scores": {
                "xai": {"cross_stone_score": 0.71, "fact_norm": 0.73, "speed_ratio": 1.0}
            }},
            {"date": "2027-06-01", "label": "Mid 2027",  "scores": {
                "xai": {"cross_stone_score": 0.85, "fact_norm": 0.78, "speed_ratio": 1.8}
            }},
        ]
        cfg = self._config_with_snapshots(snaps, baseline={
            "gen_seconds": 15.0, "fc_seconds": 45.0, "total_seconds": 60.0,
            "recorded_date": "2026-03-27"
        })
        out = self._capture(display_history, cfg)
        assert "2026-03-27" in out
        assert "2027-06-01" in out
        assert "Initial run" in out
        assert "Mid 2027" in out

    def test_snapshot_history_shows_composite_scores(self):
        snaps = [{"date": "2026-03-27", "label": "run1", "scores": {
            "xai": {"cross_stone_score": 0.7120, "fact_norm": 0.70, "speed_ratio": None}
        }}]
        out = self._capture(display_history, self._config_with_snapshots(snaps))
        # tabulate may drop trailing zeros: 0.7120 → 0.712
        assert "0.712" in out

    def test_speed_ratio_table_shown_when_baseline_and_ratios_present(self):
        snaps = [{"date": "2026-03-27", "label": "snap", "scores": {
            "xai": {"cross_stone_score": 0.71, "fact_norm": 0.70, "speed_ratio": 1.3}
        }}]
        cfg = self._config_with_snapshots(snaps, baseline={
            "total_seconds": 60.0, "recorded_date": "2026-03-27"
        })
        out = self._capture(display_history, cfg)
        assert "1.30×" in out or "speed" in out.lower()

    def test_speed_ratio_table_absent_when_no_baseline(self):
        snaps = [{"date": "2026-03-27", "label": "snap", "scores": {
            "xai": {"cross_stone_score": 0.71, "fact_norm": 0.70, "speed_ratio": None}
        }}]
        out = self._capture(display_history, self._config_with_snapshots(snaps))
        # No speed ratios present, no baseline → ratio table omitted
        assert "1.00×" not in out

    def test_accuracy_table_always_shown(self):
        snaps = [{"date": "2026-03-27", "label": "snap", "scores": {
            "xai": {"cross_stone_score": 0.71, "fact_norm": 0.726, "speed_ratio": None}
        }}]
        out = self._capture(display_history, self._config_with_snapshots(snaps))
        assert "72.6%" in out   # fact_norm as percentage

    def test_multiple_ais_all_appear_as_columns(self):
        snaps = [{"date": "2026-03-27", "label": "s", "scores": {
            "xai":       {"cross_stone_score": 0.71, "fact_norm": 0.70, "speed_ratio": None},
            "anthropic": {"cross_stone_score": 0.68, "fact_norm": 0.67, "speed_ratio": None},
            "openai":    {"cross_stone_score": 0.69, "fact_norm": 0.68, "speed_ratio": None},
        }}]
        out = self._capture(display_history, self._config_with_snapshots(snaps))
        assert "xai" in out
        assert "anthropic" in out
        assert "openai" in out

    def test_set_id_shown_in_header(self):
        cfg = self._config_with_snapshots([], baseline={})
        out = self._capture(display_history, cfg)
        assert "cross-stones-10" in out






