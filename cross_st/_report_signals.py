"""
cross_st/_report_signals.py — shared container/prompt parsing primitives.

Extracted (per st-fix selector design doc, item 3) from st-verdict.py so
both st-verdict and st-fix can read prompts, parse claims, and reason
about reports without duplicating regex/normalisation rules.

Public API:
    parse_prompt(text)            -> PromptSignals(target_words, target_lo,
                                                   target_hi, subjects)
    get_prompt_text(container)    -> str  (data[0].prompt or "")
    parse_claims(report_text)     -> list[(n, claim, verdict, explanation)]
    collect_claims(container, story_index, lens=None)
                                  -> list[dict]  (claim, verdict, explanation, evaluator)
    verdict_normalise(s)          -> str
    calendar_context()            -> str  (CALENDAR CONTEXT prefix block)

Module-level constants kept public for use by callers:
    VERDICT_NORMALISE             -> dict[str, str]
    LENS_VERDICTS                 -> dict[str, set[str] | None]

Backwards-compat aliases (st-verdict still imports the leading-underscore
names):
    _VERDICT_NORMALISE = VERDICT_NORMALISE
    _LENS_VERDICTS     = LENS_VERDICTS
    _today_context_block = calendar_context
"""

from __future__ import annotations

import re
from datetime import date
from typing import NamedTuple

# ── Verdict normalisation + lens groupings ────────────────────────────────────

VERDICT_NORMALISE = {
    "true":             "true",
    "partially_true":   "partially_true",
    "partiallytrue":    "partially_true",
    "opinion":          "opinion",
    "partially_false":  "partially_false",
    "partiallyfalse":   "partially_false",
    "false":            "false",
    "unverifiable":     "opinion",   # treat as neutral for the lens
    "unverified":       "opinion",
}

LENS_VERDICTS = {
    "false":    {"false", "partially_false"},
    "true":     {"true", "partially_true"},
    # "missing"/"howtofix" use the report itself + every verdict — handled separately
    "missing":  None,
    "howtofix": None,
}

# Backwards-compat aliases for callers that imported the old names
_VERDICT_NORMALISE = VERDICT_NORMALISE
_LENS_VERDICTS     = LENS_VERDICTS


def verdict_normalise(s: str) -> str:
    """Normalise a raw verdict token (case-insensitive) to a canonical form."""
    if not s:
        return ""
    return VERDICT_NORMALISE.get(s.strip().lower(), s.strip().lower())


# ── Claim parsing ─────────────────────────────────────────────────────────────

# Match a "Claim N: ..." block followed by Verification: <category> and Explanation: ...
# Tolerant of:
#   - extra whitespace and bold/italic markup (`**`, `__`) around any label
#   - stray markup tokens sitting on their own lines between blocks
#     (anthropic frequently emits `**\nVerification: True\n**` — see
#      st-internal/st-fix/IMPLEMENTATION_anthropic_claims_parse.md)
#   - inline `Verification:` (xai/openai) OR on its own line (anthropic/gemini)
# Captures: (claim_number, claim_text, verdict, explanation)
CLAIM_BLOCK_RE = re.compile(
    r"Claim\s+(\d+)\s*:\s*"
    r"[*_]*\s*[\"\u201c]?(.+?)[\"\u201d]?\s*[*_]*"            # claim text
    r"\s*[\n\r]+[\s*_]*"                                      # gap → may be empty
    r"Verification\s*[*_]*\s*:\s*[*_]*\s*"
    r"([A-Za-z_]+)"                                            # verdict
    r"\s*[*_]*"
    r"\s*[\n\r]+[\s*_]*"
    r"Explanation\s*[*_]*\s*:\s*"
    r"(.+?)(?=[\n\r]+[\s*_]*Claim\s+\d+\s*:|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def parse_claims(report_text):
    """Parse a fact-check report into [(n, claim, verdict_norm, explanation), …]."""
    if not report_text:
        return []
    out = []
    for match in CLAIM_BLOCK_RE.finditer(report_text):
        n_str, claim, verdict, explanation = match.groups()
        verdict_norm = verdict_normalise(verdict)
        try:
            n = int(n_str)
        except ValueError:
            n = 0
        out.append((n, claim.strip(), verdict_norm, explanation.strip()))
    return out


def collect_claims(container, story_index, lens=None):
    """Collect claims across every fact[] entry of one story.

    lens=None / "missing" / "howtofix" → return every parseable claim.
    lens="false" / "true"              → filter to that lens family.

    Returns: list of {claim, verdict, explanation, evaluator}.
    """
    target = LENS_VERDICTS.get(lens) if lens else None
    stories = container.get("story", [])
    if not (1 <= story_index <= len(stories)):
        return []
    story = stories[story_index - 1]
    collected = []
    for fact in story.get("fact", []):
        report = fact.get("report", "")
        evaluator = f"{fact.get('make', '?')}:{fact.get('model', '?')}"
        for _n, claim, verdict, explanation in parse_claims(report):
            if target is None or verdict in target:
                collected.append({
                    "claim": claim,
                    "verdict": verdict,
                    "explanation": explanation,
                    "evaluator": evaluator,
                })
    return collected


# ── Prompt extraction ─────────────────────────────────────────────────────────

def get_prompt_text(container):
    """Return the original prompt text from container['data'][0]['prompt'] or ''."""
    data = container.get("data", [])
    if data and isinstance(data[0], dict):
        return data[0].get("prompt", "") or ""
    return ""


# ── Prompt signal parsing (NEW — st-fix selector item 3) ──────────────────────

class PromptSignals(NamedTuple):
    target_words: int | None      # midpoint of requested range, or None
    target_lo:    int | None
    target_hi:    int | None
    subjects:     frozenset       # lowercase noun-phrase tokens


# Word-count patterns, ordered most-specific first
_WORD_RANGE_PATTERNS = [
    re.compile(r"(\d{2,5})\s*(?:to|-|–|—)\s*(\d{2,5})\s*words?", re.I),
    re.compile(r"(?:about|approximately|around|roughly|~)\s*(\d{2,5})\s*words?", re.I),
    re.compile(r"(\d{2,5})\s*words?", re.I),
]

# Inline stopword list — small enough that no NLTK dependency is justified
_STOPWORDS = frozenset("""
    a an and are as at be been being but by for from had has have having
    he her here his how i if in into is it its more most of on or our
    over she should so some such than that the their them then there these
    they this those to too under until very was we were what when where
    which while who why will with would you your
    about above below before after again further once all any both each
    few only own same will just now also like
    write please report reports article articles story stories summary
    paragraph paragraphs sentence sentences word words text title titles
    caption captions short long format formatted formatting include
    including discuss discussing explain explaining explore exploring
    describe describing summarise summarize cover covering use using
    using markdown plaintext brief detailed comprehensive thorough overview
    introduction conclusion focus focusing
""".split())

# Token regex: starts with a letter, ≥4 chars total, allows digits+hyphen
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{3,}")


def parse_prompt(prompt_text: str) -> PromptSignals:
    """Extract length contract + subject token set from a prompt string."""
    target_lo = target_hi = target_mid = None
    if prompt_text:
        for pat in _WORD_RANGE_PATTERNS:
            m = pat.search(prompt_text)
            if not m:
                continue
            if m.lastindex == 2:
                target_lo, target_hi = int(m.group(1)), int(m.group(2))
                target_mid = (target_lo + target_hi) // 2
            else:
                target_mid = int(m.group(1))
                target_lo = target_hi = target_mid
            break

    if prompt_text:
        tokens = _TOKEN_RE.findall(prompt_text.lower())
        subjects = frozenset(t for t in tokens if t not in _STOPWORDS)
    else:
        subjects = frozenset()

    return PromptSignals(target_mid, target_lo, target_hi, subjects)


def report_tokens(text: str) -> frozenset:
    """Return the same shape of token set used by parse_prompt(), for overlap calc."""
    if not text:
        return frozenset()
    return frozenset(_TOKEN_RE.findall(text.lower()))


# ── Calendar context ──────────────────────────────────────────────────────────

def calendar_context() -> str:
    """A short calendar-context block to prepend to AI prompts.

    Without this, AIs whose training-data cutoff predates the current date
    can confidently mis-classify legitimate post-cutoff dates as "future"
    (and therefore "non-existent" / "false").
    """
    today = date.today().isoformat()
    return (
        f"CALENDAR CONTEXT: Today's date is {today}. Any year, study, or "
        f"document with a date on or before {today} is past or present, "
        f"NOT future. Do not characterise such items as future-dated or "
        f"non-existent merely because the date is later than your "
        f"training-data cutoff.\n\n"
    )


# Backwards-compat alias
_today_context_block = calendar_context

