"""tests/test_report_signals.py — coverage for the shared signal module."""

import importlib.util
from pathlib import Path

import pytest


_spec = importlib.util.spec_from_file_location(
    "_report_signals",
    Path(__file__).parent.parent / "cross_st" / "_report_signals.py",
)
rs = importlib.util.module_from_spec(_spec)
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

