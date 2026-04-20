"""tests/test_calendar_context_in_prompts.py

Regression guard for the calendar-anchor bug: AIs whose training-data cutoff
predates the current date can confidently reject legitimate dates as
"future" / "non-existent" if the prompt does not declare today's date.

Symptom that triggered this fix: gemini's `--what-is-false` summary
fact-flagged every 2025-dated study cited in a software-development report
as "future-dated, therefore false" — when the run was on 2026-04-19.

The fix injects today's date into:
  - st-fact's `get_fact_check_prompt()` (the root cause — fact-checkers
    were producing the false verdicts the lens then aggregated)
  - st-verdict's three lens prompts (`_build_missing_prompt`,
    `_build_howtofix_prompt`, and the truth-ledger branch in
    `build_lens_prompt`) — covered in tests/test_st_verdict.py
    `TestCalendarContext`.
"""

import importlib.util
from datetime import date
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "st_fact", Path(__file__).parent.parent / "cross_st" / "st-fact.py"
)
st_fact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st_fact)


def test_fact_check_prompt_includes_today():
    today = date.today().isoformat()
    prompt = st_fact.get_fact_check_prompt("The sky is blue.")
    assert today in prompt, f"fact-check prompt missing today's date ({today})"


def test_fact_check_prompt_warns_against_future_date_fallacy():
    """The prompt must explicitly tell the AI not to flag dates as false
    purely because they are after its training-data cutoff."""
    prompt = st_fact.get_fact_check_prompt("Some claim from a 2025 study.")
    assert "training-data cutoff" in prompt
    # Must say 'past or present' so the model treats post-cutoff dates as such
    assert "past or present" in prompt


def test_fact_check_prompt_still_contains_paragraph():
    """Paragraph injection is unbroken by the new preamble."""
    prompt = st_fact.get_fact_check_prompt("UNIQUE_PARAGRAPH_TEXT_MARKER")
    assert "UNIQUE_PARAGRAPH_TEXT_MARKER" in prompt

