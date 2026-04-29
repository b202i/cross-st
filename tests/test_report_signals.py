"""tests/test_report_signals.py — coverage for the shared signal module."""

import importlib.util
import sys
from pathlib import Path

import pytest


_spec = importlib.util.spec_from_file_location(
    "_report_signals",
    Path(__file__).parent.parent / "cross_st" / "_report_signals.py",
)
rs = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass can resolve cls.__module__ (Python 3.14)
sys.modules["_report_signals"] = rs
_spec.loader.exec_module(rs)


# ── parse_prompt: word-count parsing ──────────────────────────────────────────

@pytest.mark.parametrize("text,expect_mid,expect_lo,expect_hi", [
    ("Write a 300-500 word report",       400, 300, 500),
    ("about 800 words please",            800, 800, 800),
    ("approximately 250 words",           250, 250, 250),
    ("400 to 600 words",                  500, 400, 600),
    ("just write 1000 words",            1000, 1000, 1000),
    ("no length given here",              None, None, None),
    ("",                                  None, None, None),
])
def test_parse_prompt_word_count(text, expect_mid, expect_lo, expect_hi):
    sig = rs.parse_prompt(text)
    assert sig.target_words == expect_mid
    assert sig.target_lo    == expect_lo
    assert sig.target_hi    == expect_hi


def test_parse_prompt_subjects_drop_stopwords():
    sig = rs.parse_prompt("Write about quantum computing in 2026 and AI safety")
    assert "quantum" in sig.subjects
    assert "computing" in sig.subjects
    assert "safety" in sig.subjects
    # stopwords removed
    for w in ("about", "write", "and"):
        assert w not in sig.subjects


def test_parse_prompt_subjects_lowercased():
    sig = rs.parse_prompt("Quantum COMPUTING and Solar Panels")
    assert sig.subjects == frozenset({"quantum", "computing", "solar", "panels"})


def test_parse_prompt_min_length_filter():
    """Tokens shorter than 4 chars are dropped (regex contract)."""
    sig = rs.parse_prompt("EV cat dog quantum")
    # quantum kept; "cat", "dog", "EV" dropped (< 4 chars)
    assert "quantum" in sig.subjects
    for w in ("cat", "dog", "ev"):
        assert w not in sig.subjects


def test_parse_prompt_empty_returns_empty():
    sig = rs.parse_prompt("")
    assert sig.subjects == frozenset()
    assert sig.target_words is None


# ── verdict_normalise + parse_claims ──────────────────────────────────────────

def test_verdict_normalise_canonical():
    assert rs.verdict_normalise("True") == "true"
    assert rs.verdict_normalise("PARTIALLY_FALSE") == "partially_false"
    assert rs.verdict_normalise("partiallyfalse") == "partially_false"
    assert rs.verdict_normalise("Unverifiable") == "opinion"
    assert rs.verdict_normalise("") == ""


def test_parse_claims_basic():
    report = """Some intro
Claim 1: "The sky is blue."
Verification: True
Explanation: Standard meteorology.

Claim 2: "Pigs can fly."
Verification: False
Explanation: They cannot."""
    out = rs.parse_claims(report)
    assert len(out) == 2
    assert out[0] == (1, "The sky is blue.", "true", "Standard meteorology.")
    assert out[1][2] == "false"


def test_parse_claims_anthropic_bold_markup():
    """Anthropic wraps labels in bold and leaves stray ** on their own lines.
    The shared CLAIM_BLOCK_RE must tolerate this — used to silently drop
    every anthropic claim (st-ls 'Claims' column showed '-')."""
    report = """# Fact-Check Analysis

**Claim 1:** "The field continues to evolve"
**  
Verification: True  
**
Explanation: Well documented.

**Claim 2:** "Pigs can fly"
**  
Verification: False  
**
Explanation: They cannot.
"""
    out = rs.parse_claims(report)
    assert len(out) == 2, f"expected 2 claims, got {len(out)}: {out}"
    verdicts = [c[2] for c in out]
    assert verdicts == ["true", "false"]


def test_parse_claims_inline_verification():
    """xai/openai sometimes emit Verification on the same line as the claim."""
    report = """Claim 1: "The sky is blue."
Verification: True
Explanation: ok.

Claim 2: "Test claim"
Verification: Partially_true
Explanation: with caveats.
"""
    out = rs.parse_claims(report)
    assert len(out) == 2
    assert out[1][2] == "partially_true"



def test_parse_claims_empty():
    assert rs.parse_claims("") == []
    assert rs.parse_claims(None) == []


# ── get_prompt_text + collect_claims ──────────────────────────────────────────

def test_get_prompt_text_present_and_missing():
    assert rs.get_prompt_text({"data": [{"prompt": "hello"}]}) == "hello"
    assert rs.get_prompt_text({}) == ""
    assert rs.get_prompt_text({"data": []}) == ""
    assert rs.get_prompt_text({"data": [{}]}) == ""


def test_collect_claims_filters_by_lens():
    container = {
        "story": [{
            "fact": [{
                "make": "xai",
                "model": "grok",
                "report": (
                    'Claim 1: "A"\nVerification: True\nExplanation: ok.\n\n'
                    'Claim 2: "B"\nVerification: False\nExplanation: nope.\n'
                ),
            }],
        }],
    }
    falses = rs.collect_claims(container, 1, lens="false")
    assert len(falses) == 1
    assert falses[0]["verdict"] == "false"
    assert falses[0]["evaluator"] == "xai:grok"

    everything = rs.collect_claims(container, 1, lens=None)
    assert len(everything) == 2

    # Out-of-range index
    assert rs.collect_claims(container, 99, lens=None) == []


# ── calendar_context ──────────────────────────────────────────────────────────

def test_calendar_context_mentions_today():
    from datetime import date
    blk = rs.calendar_context()
    assert date.today().isoformat() in blk
    assert "CALENDAR CONTEXT" in blk


# ── report_tokens ─────────────────────────────────────────────────────────────

def test_report_tokens_basic():
    toks = rs.report_tokens("Quantum computing leads. Solar panels follow.")
    assert "quantum" in toks
    assert "computing" in toks
    assert "solar" in toks
    assert "panels" in toks


# ── score_authors (VRD-10a composite scorer) ──────────────────────────────────

import json


_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "figma_generation_ai.json"


def _load_figma_fixture():
    with open(_FIXTURE_PATH) as fh:
        return json.load(fh)


def test_score_authors_returns_one_per_story():
    container = _load_figma_fixture()
    scores = rs.score_authors(container)
    assert len(scores) == len(container["story"]) == 4


def test_score_authors_identity_is_make_colon_model():
    """Identity must be `make:model`, never `make` alone — forward-compat
    for cross-ai-core multi-model-per-make."""
    container = _load_figma_fixture()
    scores = rs.score_authors(container)
    for s in scores:
        assert ":" in s.author
        assert s.author == f"{s.make}:{s.model}"


def test_score_authors_perplexity_outranks_openai_on_figma_fixture():
    """Headline regression: under the legacy ratio-based scorer openai (~750
    words, low coverage) won over perplexity (full coverage of all 6 prompt
    aspects). The new composite must reverse that.
    See cross-internal/st-verdict/ANALYSIS_scoring_flaws.md §A.2."""
    container = _load_figma_fixture()
    scores = rs.score_authors(container)
    by_author = {s.author: s for s in scores}
    perp = by_author["perplexity:sonar-pro"]
    oai = by_author["openai:gpt-4o"]
    assert perp.composite > oai.composite, (
        f"perplexity {perp.composite:.3f} should beat openai {oai.composite:.3f} "
        f"under the new composite scorer"
    )


def test_score_authors_ranks_are_dense_and_ordered():
    container = _load_figma_fixture()
    scores = rs.score_authors(container)
    included = [s for s in scores if not s.excluded]
    # Rank is 1..N for included
    assert [s.rank for s in included] == list(range(1, len(included) + 1))
    # Composite is monotonically non-increasing
    composites = [s.composite for s in included]
    assert composites == sorted(composites, reverse=True)


def test_score_authors_components_in_expected_ranges():
    container = _load_figma_fixture()
    for s in rs.score_authors(container):
        cov = s.components["coverage"]
        comp = s.components["completeness"]
        acc = s.components["accuracy"]
        cal = s.components["calibration"]
        assert 0.0 <= cov <= 1.0,  f"coverage out of range: {cov}"
        assert 0.0 <= comp <= 1.0, f"completeness out of range: {comp}"
        assert -1.0 <= acc <= 1.0, f"accuracy out of range: {acc}"
        assert 0.0 <= cal <= 1.0,  f"calibration out of range: {cal}"
        # composite is roughly weighted sum; should be in [-1, +1]
        assert -1.0 <= s.composite <= 1.0


def test_score_authors_excludes_evaluator_only_make():
    """An AI present only as a fact-check evaluator (gemini in the fixture)
    must NEVER appear as an author in the scoring output. Guards against
    the '"Gemini emerged as most accurate"' caption hallucination — see
    ANALYSIS_scoring_flaws.md §A.5."""
    container = _load_figma_fixture()
    scores = rs.score_authors(container)
    authors = {s.author for s in scores}
    # Gemini is an evaluator in fact[*] but never authored a story
    assert not any(a.startswith("gemini:") for a in authors), (
        f"gemini must not appear as an author, got: {sorted(authors)}"
    )


def test_score_authors_excludes_synthetic_short_author():
    """Anti-gaming gate: an author whose word/segment/claim count is below
    0.5×median must be marked excluded with a non-empty reason."""
    container = {
        "data": [
            {"make": "xai", "model": "grok", "prompt": "Write a 1000 word report on quantum computing."},
            {"make": "anthropic", "model": "claude", "prompt": ""},
            {"make": "openai", "model": "gpt", "prompt": ""},
        ],
        "story": [
            {"make": "xai", "model": "grok",
             "markdown": ("quantum computing " * 500),
             "segments": [{"id": i} for i in range(20)],
             "fact": [{"counts": [10, 5, 2, 0, 0]}]},
            {"make": "anthropic", "model": "claude",
             "markdown": ("quantum computing " * 480),
             "segments": [{"id": i} for i in range(18)],
             "fact": [{"counts": [9, 4, 2, 0, 0]}]},
            {"make": "openai", "model": "gpt",
             "markdown": "tiny story",        # 2 words → way below 0.5×median
             "segments": [{"id": 1}],          # 1 segment
             "fact": [{"counts": [0, 0, 0, 0, 0]}]},
        ],
    }
    scores = rs.score_authors(container)
    by_author = {s.author: s for s in scores}
    short = by_author["openai:gpt"]
    assert short.excluded
    assert short.rank is None
    assert short.excluded_reason and "median" in short.excluded_reason
    # Other two are included with proper ranks
    included = [s for s in scores if not s.excluded]
    assert len(included) == 2
    assert {s.rank for s in included} == {1, 2}


def test_score_authors_excludes_author_not_in_data():
    """Defence-in-depth: a story whose make:model isn't in container.data[]
    must be excluded with the 'evaluator-only' reason. Catches malformed
    containers and guards against the gemini hallucination at a deeper
    layer than the evaluator-only check."""
    container = {
        "data": [{"make": "xai", "model": "grok", "prompt": "Write 500 words."}],
        "story": [{
            "make": "ghost", "model": "999",
            "markdown": "x " * 500,
            "segments": [{"id": i} for i in range(10)],
            "fact": [{"counts": [5, 2, 1, 0, 0]}],
        }],
    }
    scores = rs.score_authors(container)
    assert scores[0].excluded
    assert "data[]" in scores[0].excluded_reason


def test_score_authors_custom_weights_change_ranking():
    """`--score-weights` flag plumbing: when accuracy weight is zeroed out
    the ranking should be driven entirely by coverage / completeness /
    calibration."""
    container = _load_figma_fixture()
    default = rs.score_authors(container)
    # Boost coverage to dominate
    boosted = rs.score_authors(container, weights={
        "coverage": 1.0, "completeness": 0.0,
        "accuracy": 0.0, "calibration": 0.0,
    })
    # Top author by pure coverage may differ from default — at minimum the
    # composite values must change.
    default_top = default[0].composite
    boosted_top = boosted[0].composite
    assert default_top != boosted_top, (
        "weights had no effect — composite values are identical"
    )
    # And the boosted top is exactly the highest coverage component
    assert boosted_top == pytest.approx(
        max(s.components["coverage"] for s in boosted), abs=1e-9)


def test_score_authors_rejects_bad_weights():
    container = _load_figma_fixture()
    with pytest.raises(ValueError, match="Unknown score weight"):
        rs.score_authors(container, weights={"bogus": 1.0})
    with pytest.raises(ValueError, match="non-negative"):
        rs.score_authors(container, weights={"coverage": -1.0})
    with pytest.raises(ValueError, match="must be > 0"):
        rs.score_authors(container, weights={
            "coverage": 0.0, "completeness": 0.0,
            "accuracy": 0.0, "calibration": 0.0,
        })


def test_score_authors_empty_container_returns_empty():
    assert rs.score_authors({}) == []
    assert rs.score_authors({"story": []}) == []


def test_score_authors_to_dict_serialisable():
    """AuthorScore.to_dict() must be JSON-serialisable so it can be passed
    straight into the --ai-caption / --ai-short prompt context."""
    container = _load_figma_fixture()
    for s in rs.score_authors(container):
        d = s.to_dict()
        # Round-trip through json
        json.loads(json.dumps(d))
        assert set(d) >= {"author", "rank", "composite", "components",
                          "weights", "excluded", "excluded_reason"}
