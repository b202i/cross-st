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
    score_authors(container, weights=None) -> list[AuthorScore]
                                  -> ranked composite "best author" scores (VRD-10)
    parse_score_weights(text)     -> dict | None  (parses --score-weights CLI arg)

Module-level constants kept public for use by callers:
    VERDICT_NORMALISE             -> dict[str, str]
    LENS_VERDICTS                 -> dict[str, set[str] | None]

Backwards-compat agents (st-verdict still imports the leading-underscore
names):
    _VERDICT_NORMALISE = VERDICT_NORMALISE
    _LENS_VERDICTS     = LENS_VERDICTS
    _today_context_block = calendar_context
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date
from statistics import median
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
    # VRD-10g: dedicated "unknown" bucket — was previously aliased to
    # "opinion". Keeping it distinct lets the chart show "I don't know"
    # answers separately from genuine subjective opinions, and stops the
    # calibration sub-score from rewarding evaluators who hide ignorance
    # under the opinion label.
    "unknown":          "unknown",
    "unverifiable":     "unknown",
    "unverified":       "unknown",
}

LENS_VERDICTS = {
    "false":    {"false", "partially_false"},
    "true":     {"true", "partially_true"},
    # "missing"/"howtofix" use the report itself + every verdict — handled separately
    "missing":  None,
    "howtofix": None,
}

# Backwards-compat agents for callers that imported the old names
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
#      cross-internal/st-fact/BUGFIX_anthropic_claims_parse.md)
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


# Backwards-compat agent
_today_context_block = calendar_context


# ── Composite "best author" scoring (VRD-10a) ─────────────────────────────────
#
# Replaces the legacy per-fact `score` in st-ls / st-verdict / st-stones with
# a four-component composite incorporating Coverage, Completeness, Accuracy
# (with min-claim floor) and Calibration. Hard-excludes structurally
# incomplete authors. See cross-internal/st-verdict/VRD-10.md and
# cross-internal/st-verdict/ANALYSIS_scoring_flaws.md for the rationale.
#
# Identity is `make:model` (NEVER `make` alone) so a future world where
# `gemini-2.5-flash` evaluates and `gemini-3.0-pro` authors works without
# any change to this scorer.

DEFAULT_WEIGHTS: dict = {
    "coverage":     0.25,
    "completeness": 0.25,
    "accuracy":     0.40,
    "calibration":  0.10,
}

# Anti-gaming gate: any author whose words / segments / total claim count is
# below this fraction of the cohort median is excluded from "best author"
# selection (see analysis §F.1 Q6).
EXCLUSION_FRACTION = 0.5

# Minimum N_hard floor for accuracy denominator — kills the "few claims = easy
# 100%" exploit (see analysis §C item 1 and §D.1 Accuracy row).
ACCURACY_MIN_FLOOR = 5

# Counts list layout in fact[].counts as written by st-fact / st-cross.
# VRD-10g: legacy containers wrote 5 ints (true … false). Fresh writes after
# 0.8.0 append a 6th slot for the new "unknown" bucket. Readers MUST tolerate
# either length — see ``_fact_counts`` for the padding logic.
_COUNTS_INDEX = {"true": 0, "partially_true": 1, "opinion": 2,
                 "partially_false": 3, "false": 4, "unknown": 5}
_COUNTS_LEN = 6


@dataclass
class AuthorScore:
    """Per-author composite score + component breakdown + exclusion reason.

    `author` is the canonical `make:model` identity used everywhere in the
    new scoring pipeline. `composite` is in roughly [-1, +1]; sub-scores are
    in [0, 1] except `accuracy` which is in [-1, +1].

    `excluded` authors are still returned (so the chart can show them with a
    hatched/grey overlay per VRD-10e) but have rank=None and are listed
    after all included authors.
    """
    author: str
    make: str
    model: str
    rank: int | None
    composite: float
    components: dict
    weights: dict
    words: int
    segments: int
    claims_total: int
    excluded: bool
    excluded_reason: str | None
    narrative: str

    def to_dict(self) -> dict:
        return asdict(self)


def _author_id(make: str, model: str) -> str:
    return f"{(make or '?').strip()}:{(model or '?').strip()}"


def _word_count(story: dict) -> int:
    md = story.get("markdown") or story.get("text") or ""
    return len(md.split())


def _segment_count(story: dict) -> int:
    # Container shape uses `segments` (plural) per the figma fixture; some
    # older containers used `segment` (singular) — accept either.
    segs = story.get("segments")
    if segs is None:
        segs = story.get("segment", [])
    return len(segs or [])


def _fact_counts(fact: dict) -> tuple:
    """Return (true, partially_true, opinion, partially_false, false, unknown)
    for one evaluator's fact-check.

    Uses fact['counts'] when present — accepts either the legacy 5-int form
    (zero-padded to 6 for the new "unknown" slot) or the new 6-int form.
    Falls back to re-parsing fact['report'] otherwise.
    """
    counts = fact.get("counts")
    if isinstance(counts, list) and len(counts) >= 5:
        try:
            ints = [int(x) for x in counts]
        except (TypeError, ValueError):
            ints = None
        if ints is not None:
            # Pad legacy 5-element counts with a zero "unknown" bucket so all
            # consumers can index ints[5] safely.
            if len(ints) < _COUNTS_LEN:
                ints = ints + [0] * (_COUNTS_LEN - len(ints))
            return tuple(ints[:_COUNTS_LEN])
    tally = [0] * _COUNTS_LEN
    for _n, _claim, verdict, _explanation in parse_claims(fact.get("report", "")):
        idx = _COUNTS_INDEX.get(verdict)
        if idx is not None:
            tally[idx] += 1
    return tuple(tally)


def _coverage(prompt_subjects: frozenset, story_markdown: str) -> float:
    if not prompt_subjects:
        return 1.0
    tokens = report_tokens(story_markdown)
    if not tokens:
        return 0.0
    hit = sum(1 for s in prompt_subjects if s in tokens)
    return hit / len(prompt_subjects)


def _completeness(words: int, segments: int,
                  target_lo, median_segments: float,
                  truncated: bool) -> float:
    """Geometric mean of (word ratio, segment ratio, non-truncation).

    word ratio  : 1.0 if words ≥ target_lo (or no contract); else words/target_lo
    seg ratio   : 1.0 if segments ≥ cohort median; else segments/median
    non-trunc   : 1.0 unless truncated, then 0.0 (kills the score)
    """
    if target_lo and target_lo > 0:
        word_ratio = min(1.0, words / target_lo) if words > 0 else 0.0
    else:
        word_ratio = 1.0
    if median_segments > 0:
        seg_ratio = min(1.0, segments / median_segments) if segments > 0 else 0.0
    else:
        seg_ratio = 1.0
    trunc_factor = 0.0 if truncated else 1.0
    product = word_ratio * seg_ratio * trunc_factor
    if product <= 0:
        return 0.0
    return product ** (1.0 / 3.0)


def _accuracy(per_evaluator_counts: list, k_floor: int) -> float:
    """Volume-weighted accuracy across evaluators with min-claim denominator.

    Per evaluator: (2T + ~T − ~F − 2F) / max(N_hard, k_floor).
    Aggregate: weight each evaluator's per-claim score by its N_hard so a
    thorough evaluator contributes more than a sparse one. Returns 0.0 if no
    evaluator produced any hard claims. Clamped to [-1, +1].
    """
    if not per_evaluator_counts:
        return 0.0
    total_signed = 0.0
    total_weight = 0.0
    for c in per_evaluator_counts:
        # Accept 5- or 6-element tuples (legacy / VRD-10g). "unknown" is
        # neutral and never enters the accuracy formula.
        t, pt, _op, pf, f = c[0], c[1], c[2], c[3], c[4]
        n_hard = t + pt + pf + f
        if n_hard <= 0:
            continue
        signed = 2 * t + pt - pf - 2 * f
        denom = max(n_hard, k_floor)
        per_eval = signed / denom
        total_signed += per_eval * n_hard
        total_weight += n_hard
    if total_weight <= 0:
        return 0.0
    raw = total_signed / total_weight
    return max(-1.0, min(1.0, raw))


def _calibration(per_evaluator_counts: list,
                 cohort_median_opinion_share: float) -> float:
    """1 − |opinion_share − cohort_median_opinion_share|, clamped to [0, 1].

    Penalises both vagueness (high opinion share vs cohort) and
    overconfidence (very low opinion share). Cohort median is the natural
    neutral point because it reflects the prompt's intrinsic subjectivity.
    """
    total = 0
    op = 0
    for c in per_evaluator_counts:
        # 5- or 6-element tuples (VRD-10g). Unknown counts toward total
        # (it represents real evaluator output) but is not the same axis as
        # opinion for the calibration target.
        t, pt, o, pf, f = c[0], c[1], c[2], c[3], c[4]
        u = c[5] if len(c) >= 6 else 0
        total += t + pt + o + pf + f + u
        op += o
    if total <= 0:
        return 0.5
    share = op / total
    return max(0.0, min(1.0, 1.0 - abs(share - cohort_median_opinion_share)))


def _collect_author_signals(container: dict) -> list:
    """One row per story author: identity, words, segments, per-eval counts."""
    out = []
    data_authors = {_author_id(d.get("make", ""), d.get("model", ""))
                    for d in container.get("data", []) if isinstance(d, dict)}
    for story in container.get("story", []):
        if not isinstance(story, dict):
            continue
        make = story.get("make", "?")
        model = story.get("model", "?")
        author = _author_id(make, model)
        per_eval = []
        truncated_any = False
        for fact in story.get("fact", []):
            if not isinstance(fact, dict):
                continue
            per_eval.append(_fact_counts(fact))
            if fact.get("_truncated") or fact.get("_error"):
                truncated_any = True
        out.append({
            "author": author,
            "make": make,
            "model": model,
            "in_data": author in data_authors,
            "words": _word_count(story),
            "segments": _segment_count(story),
            "per_eval_counts": per_eval,
            "markdown": story.get("markdown") or story.get("text") or "",
            "truncated": truncated_any,
        })
    return out


def _resolve_weights(weights):
    if not weights:
        return dict(DEFAULT_WEIGHTS)
    out = dict(DEFAULT_WEIGHTS)
    for k, v in weights.items():
        if k not in DEFAULT_WEIGHTS:
            raise ValueError(
                f"Unknown score weight key: {k!r} "
                f"(allowed: {sorted(DEFAULT_WEIGHTS)})")
        if v is None or v < 0:
            raise ValueError(
                f"Score weight {k!r} must be non-negative, got {v!r}")
        out[k] = float(v)
    if sum(out.values()) <= 0:
        raise ValueError("At least one score weight must be > 0")
    return out


def score_authors(container: dict, weights=None) -> list:
    """Composite "best author" scoring (VRD-10).

    Returns a list of AuthorScore, sorted by composite descending. Excluded
    authors are appended after all included authors and have rank=None.

    Identity is `make:model` (never `make` alone), so the scorer is
    forward-compatible with multi-model-per-make in cross-ai-core.
    """
    w = _resolve_weights(weights)
    signals = _collect_author_signals(container)
    if not signals:
        return []

    prompt_text = get_prompt_text(container)
    psig = parse_prompt(prompt_text)

    # Cohort medians — computed across ALL signals (incl. would-be excluded)
    # so a single tiny outlier doesn't pull the median down and accidentally
    # promote another bad author.
    word_med = median([s["words"] for s in signals])
    seg_med = median([s["segments"] for s in signals])
    # VRD-10g: per-eval count tuples are now 6-wide. Sum all categories
    # (incl. "unknown") for the total-claims cohort statistic.
    claim_totals = [sum(sum(c) for c in s["per_eval_counts"])
                    for s in signals]
    claim_med = median(claim_totals) if claim_totals else 0

    n_hard_per_author = [
        sum(c[0] + c[1] + c[3] + c[4] for c in s["per_eval_counts"])
        for s in signals
    ]
    n_hard_med = median(n_hard_per_author) if n_hard_per_author else 0
    k_floor = max(ACCURACY_MIN_FLOOR, int(0.5 * n_hard_med))

    # Cohort median opinion share — the Calibration neutral point.
    opinion_shares = []
    for s in signals:
        total = 0
        op = 0
        for c in s["per_eval_counts"]:
            t, pt, o, pf, f = c[0], c[1], c[2], c[3], c[4]
            u = c[5] if len(c) >= 6 else 0
            total += t + pt + o + pf + f + u
            op += o
        if total > 0:
            opinion_shares.append(op / total)
    median_opinion_share = median(opinion_shares) if opinion_shares else 0.0

    results = []
    for s, total_claims in zip(signals, claim_totals):
        # ---- exclusion gate ----
        reasons = []
        if not s["in_data"]:
            reasons.append("not present in container.data[] (evaluator-only)")
        if word_med > 0 and s["words"] < EXCLUSION_FRACTION * word_med:
            reasons.append(
                f"words {s['words']} < {EXCLUSION_FRACTION:g}·median "
                f"({word_med:g})")
        if seg_med > 0 and s["segments"] < EXCLUSION_FRACTION * seg_med:
            reasons.append(
                f"segments {s['segments']} < {EXCLUSION_FRACTION:g}·median "
                f"({seg_med:g})")
        if claim_med > 0 and total_claims < EXCLUSION_FRACTION * claim_med:
            reasons.append(
                f"claims {total_claims} < {EXCLUSION_FRACTION:g}·median "
                f"({claim_med:g})")
        if s["truncated"]:
            reasons.append("truncation marker present")
        excluded = bool(reasons)
        excluded_reason = "; ".join(reasons) if reasons else None

        # ---- sub-scores ----
        cov = _coverage(psig.subjects, s["markdown"])
        comp = _completeness(s["words"], s["segments"],
                             psig.target_lo, seg_med, s["truncated"])
        acc = _accuracy(s["per_eval_counts"], k_floor)
        cal = _calibration(s["per_eval_counts"], median_opinion_share)

        composite = (w["coverage"] * cov
                     + w["completeness"] * comp
                     + w["accuracy"] * acc
                     + w["calibration"] * cal)

        narrative = (
            f"coverage={cov:.2f} of {len(psig.subjects)} prompt subjects; "
            f"completeness={comp:.2f} (words={s['words']}/"
            f"target_lo={psig.target_lo}, segments={s['segments']}/"
            f"cohort_median={seg_med:g}); "
            f"accuracy={acc:+.2f} over {len(s['per_eval_counts'])} evaluators "
            f"(min-claim floor K={k_floor}); "
            f"calibration={cal:.2f} (opinion share vs cohort median "
            f"{median_opinion_share:.2f})"
        )

        results.append(AuthorScore(
            author=s["author"],
            make=s["make"],
            model=s["model"],
            rank=None,
            composite=composite,
            components={"coverage": cov, "completeness": comp,
                        "accuracy": acc, "calibration": cal},
            weights=dict(w),
            words=s["words"],
            segments=s["segments"],
            claims_total=total_claims,
            excluded=excluded,
            excluded_reason=excluded_reason,
            narrative=narrative,
        ))

    included = sorted([r for r in results if not r.excluded],
                      key=lambda r: r.composite, reverse=True)
    excluded_list = sorted([r for r in results if r.excluded],
                           key=lambda r: r.composite, reverse=True)
    for i, r in enumerate(included, start=1):
        r.rank = i
    return included + excluded_list


# ── CLI helper: parse --score-weights ─────────────────────────────────────────

# Short agents accepted on the command line so users can write
#   --score-weights cov=0.3,comp=0.3,acc=0.3,cal=0.1
# instead of spelling out the full sub-score names.
_WEIGHT_ALIASES = {
    "cov":          "coverage",
    "coverage":     "coverage",
    "comp":         "completeness",
    "completeness": "completeness",
    "acc":          "accuracy",
    "accuracy":     "accuracy",
    "cal":          "calibration",
    "calibration":  "calibration",
}


def parse_score_weights(text):
    """Parse a ``--score-weights`` CLI argument into a dict for ``score_authors``.

    Format: ``cov=0.25,comp=0.25,acc=0.40,cal=0.10``. Keys may use either the
    short agent (``cov``/``comp``/``acc``/``cal``) or the full sub-score name.
    Returns ``None`` for an empty/None input. Raises ``ValueError`` for any
    malformed pair, unknown key, non-numeric or negative value, or weight set
    that sums to zero.
    """
    if not text or not text.strip():
        return None
    out: dict = {}
    for pair in text.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(
                f"--score-weights entry {pair!r} must be in 'key=value' form")
        k_raw, v_raw = pair.split("=", 1)
        k = k_raw.strip().lower()
        if k not in _WEIGHT_ALIASES:
            raise ValueError(
                f"Unknown --score-weights key: {k!r} "
                f"(allowed: cov, comp, acc, cal)")
        try:
            v = float(v_raw.strip())
        except ValueError:
            raise ValueError(
                f"--score-weights value for {k!r} must be numeric, "
                f"got {v_raw!r}")
        if v < 0:
            raise ValueError(
                f"--score-weights value for {k!r} must be non-negative, "
                f"got {v}")
        out[_WEIGHT_ALIASES[k]] = v
    if not out:
        return None
    if sum(out.values()) <= 0:
        raise ValueError(
            "--score-weights must sum to > 0 across the supplied keys")
    return out


