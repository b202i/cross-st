#!/usr/bin/env python3
"""
st-fix — Improve a story using fact-check feedback

Modes:
  patch       (default) Bundle all False/Partially_false claims into one prompt.
              The AI edits only those sentences, leaving the rest of the story intact.

  best-source For each false claim, search the other AI stories in the container
              for how they handled the same topic. Present the alternatives to the
              AI and ask it to choose or synthesize the most accurate version.
              Requires multiple stories in the container (i.e. after st-bang).

  synthesize  Give the AI all stories plus their fact-check scores and ask it to
              write the best possible story by drawing on whichever AI got each
              section most accurate. Produces the highest-quality result but uses
              the most tokens.

              DESIGN NOTES (future work):
              ─────────────────────────────────────────────────────────────────
              Goal: produce a single story with a score as close to 2.0 as
              possible, by selecting the best-supported content from each AI.

              ── The data structure problem ────────────────────────────────────
              The current fact entry in the JSON container stores results as a
              single free-text "report" string:

                story["fact"][n] = {
                  "report":  "...Claim 1: '...' Verification:True\nExplanation:...",
                  "summary": "| True | Partially_true | ... |",
                  "counts":  [true, ~true, opinion, ~false, false],
                  "score":   1.52,
                  "make":    "xai",
                  "model":   "grok-4-latest"
                }

              Every downstream tool (st-fix, st-cross, st-analyze, st-ls)
              must RE-PARSE this free-text string to do anything claim-level.
              That parsing is fragile: it relies on "Claim N:" / "Verification:"
              markers that the AI may format inconsistently, especially across
              five different AI and dozens of paragraphs.

              ── Pre-parse: segments as the unit of work ───────────────────────
              The key architectural insight is that st-fact currently conflates
              two separate responsibilities in one sequential loop:

                1. Splitting the story into fact-checkable units  (deterministic)
                2. Sending each unit to an AI for assessment       (expensive, slow)

              These should be separated.  Step 1 produces a "segments" list
              stored on the story itself — it is the same for every AI checker.
              Step 2 consumes that list and populates the "claims" list inside
              each fact entry.

              Proposed story-level structure (added once by st-fact --prep,
              or automatically on first fact-check of any story):

                story["segments"] = [
                  {
                    "id":   0,                    # 0-based, stable forever
                    "text": "The sky is blue.",   # the checkable unit of text
                    "para": 2                     # source paragraph index
                  },
                  ...
                ]

              Once segments exist on a story, any number of AI can fact-check
              it in parallel, each working on the identical list of units.
              The segment IDs are stable — segment 7 is the same text for xai, anthropic, openai,
              perplexity, and gemini.  You can directly compare their
              verdicts on the identical sentence without alignment.

              Each fact entry then stores claims keyed to segment IDs:

                story["fact"][n] = {
                  "make":    "xai",
                  "model":   "grok-4-latest",
                  "score":   1.52,
                  "counts":  [16, 4, 2, 1, 1],
                  "summary": "| True | ...",
                  "report":  "...free-text kept for human reading...",
                  "claims":  [
                    {
                      "seg_id":      7,
                      "verdict":     "False",
                      "explanation": "The S40 Gen 3 weighed 21 lbs, not 19."
                    },
                    ...
                  ]
                }

              Benefits of this design:

                Apples-to-apples parallel checking:
                  All N AI checkers work from the same segment list.
                  Segment 7 is the same text for xai, anthropic, openai,
                  perplexity, and gemini.  You can directly compare their
                  verdicts on the identical sentence without alignment.

                No re-parsing downstream:
                  st-fix filters non-True claims with a list comprehension.
                  st-ls shows per-segment verdict counts directly.
                  st-analyze builds the heat map from claims[].verdict.
                  st-cross aggregates verdicts across the 5×5 matrix by
                  joining on seg_id.

                Progress reporting is accurate:
                  st-cross currently shows n/total based on paragraphs
                  processed.  With segments, that count is known before
                  any AI call is made — the progress bar is exact from
                  the first second.

                Segments are cheap to produce:
                  The split logic already exists in st-fact (the paragraph
                  loop + sentence-ending filter).  Extracting it into a
                  helper function and saving the result adds ~10 lines.
                  Existing .json files without "segments" degrade gracefully;
                  tools generate segments on-the-fly when the key is absent.

                One prompt per segment, not per paragraph:
                  Currently a paragraph with 4 sentences becomes one prompt
                  returning 4 claims mixed together.  One prompt per segment
                  keeps the AI response tightly scoped and easier to parse.
                  It also means a timed-out or errored segment can be retried
                  individually without re-checking the whole paragraph.

              ── The cross-story alignment problem (separate concern) ──────────
              Segments solve the within-story problem: N checkers, same units,
              apples-to-apples.  A different problem remains for st-fix v3:
              five AI wrote five *different* stories about the same topic.
              Segment 7 in story 1 ("The S40 Gen 3 weighed 19 lbs") is not the
              same text as segment 12 in story 3 ("The S40 Gen 3 was 21 lbs"),
              even though both make a claim about the same real-world fact.

              Segments give stable IDs within a story, but there is no segment
              ID that spans stories.  That cross-story alignment still requires
              one of two approaches:

                Semantic matching (embedding-based):
                  Embed all segments from all stories.  Cluster by cosine
                  similarity.  Each cluster = one real-world fact.  Each
                  story's segment in the cluster is its version of that fact.
                  Rigorous, requires an embedding pass (~1 000 tokens total).

                Prompt-based matching (simpler, works now):
                  For each non-True segment in story N, ask one AI to find
                  the passage in each other story that covers the same fact.
                  Less precise but zero infrastructure beyond what exists.
                  This is what best-source mode already does at story level;
                  driving it by segment ID makes it claim-granular.

              ── Fix approach v1 — patch (current) ────────────────────────────
                Bundle all False/~False claims into one prompt.
                The AI edits only those sentences.  Fast, cheap, good for
                isolated errors.  Blind to what other AI wrote correctly.

              ── Fix approach v2 — best-source (current) ──────────────────────
                Provide the other AI stories as reference material per claim.
                The AI picks or synthesises the most accurate wording from
                the pool.  Better than patch, still operates at story level.
                With a structured claims list, this could be driven claim-by-
                claim rather than story-by-story, giving much tighter guidance.

              ── Fix approach v3 — claim-level assembly (future) ──────────────
                The cross-product gives us up to 25 fact-check reports.
                With structured claims and cross-story alignment:

                1. For each claim C in target story S:
                   a. Find the corresponding passage in every other story
                      (via embedding match or prompt).
                   b. Look up how many checkers rated each AI's version True.
                   c. Select the passage with the highest True count across
                      checkers as the "best-supported" version.
                2. Assemble the best-supported passages into a new story,
                   with an AI stitching them into flowing prose.
                3. Run st-fact on the result to verify the score improved.

                This is the most rigorous but requires:
                  — structured claims in every fact entry (see above)
                  — cross-story claim alignment (embedding or prompt)
                  — aggregating verdicts per claim across the 5×5 matrix
                  — a final coherence pass to make the story readable

              ── Token budget ─────────────────────────────────────────────────
                5 stories × ~1500 words ≈ 10 000 tokens input.
                Most frontier models handle this comfortably in one call.
                v3 paragraph alignment would need an extra pass (~2 000 tokens).

              ── After-fix verification ────────────────────────────────────────
                patch/best-source: already re-runs st-fact with the same
                checker AI and shows a before/after table.  Good baseline.

                synthesize: currently skips the comparison.  Better metric:
                run st-fact on the synthesized story with all 5 AI and compare
                the avg score to the avg of the 5 original stories.  That gives
                a true quality delta rather than a single-checker comparison.
              ─────────────────────────────────────────────────────────────────

Usage:
  st-fix -s 1 -f 1 file.json                          # patch mode, story 1, fact-check 1
  st-fix -s 1 -f 1 --mode best-source file.json       # use other AI stories as reference
  st-fix --mode synthesize file.json                   # full synthesis across all stories
"""
import argparse
import hashlib
import json
import os
import subprocess
import re
import sys
from mmd_startup import load_cross_env, require_config
import difflib
import threading
import time

from ai_handler import get_ai_list, get_default_ai, process_prompt, get_content, put_content
from mmd_process_report import remove_markdown


# ── Spinner ───────────────────────────────────────────────────────────────────

class Spinner:
    """
    Display a spinning cursor and elapsed time on a single line while a
    long-running operation is in progress.

    Usage:
        with Spinner("  Calling AI synthesizer"):
            result = some_slow_call()
        # prints: "  Calling AI synthesizer… ✓ 00:42"
    """
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str, quiet: bool = False):
        self.label   = label
        self.quiet   = quiet
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._start  = 0.0

    def _spin(self):
        i = 0
        while not self._stop.is_set():
            elapsed = time.time() - self._start
            mm, ss  = divmod(int(elapsed), 60)
            frame   = self.FRAMES[i % len(self.FRAMES)]
            print(f"\r{self.label}… {frame} {mm:02d}:{ss:02d}", end="", flush=True)
            i += 1
            time.sleep(0.1)

    def __enter__(self):
        if not self.quiet:
            self._start = time.time()
            self._thread.start()
        return self

    def __exit__(self, *_):
        if not self.quiet:
            self._stop.set()
            self._thread.join()
            elapsed = time.time() - self._start
            mm, ss  = divmod(int(elapsed), 60)
            print(f"\r{self.label}… ✓ {mm:02d}:{ss:02d}          ")


# ── Diff helper ───────────────────────────────────────────────────────────────

def print_diff(text1, text2):
    """Print a unified diff of two texts, showing only changed lines."""
    diff = difflib.ndiff(text1.splitlines(), text2.splitlines())
    for line in diff:
        if line.startswith("- "):
            print(f"< {line[2:]}")
        elif line.startswith("+ "):
            print(f"> {line[2:]}")


# ── Fact-check extraction ─────────────────────────────────────────────────────

def extract_fact_checks(fact_obj, target_verifications, story=None):
    """
    Return claims matching target_verifications from a fact entry.

    Prefers the structured fact["claims"] list (written by st-fact when
    segments are present).  Falls back to regex-parsing the free-text
    fact["report"] string for legacy entries that predate the claims list.

    Returns list of dicts: {text, claim, verification, explanation, seg_id}
    - text: original story sentence (from story["segments"] via seg_id, or quoted claim)
    - claim: short display label (text[:120] or explanation[:120])

    Args:
        fact_obj: the fact-check entry from story["fact"][n]
        target_verifications: list of verdicts to filter (e.g. ["False", "Partially_false"])
        story: the parent story dict (needed to look up segments when claims have seg_id)
    """
    # ── Structured path (new) ─────────────────────────────────────────────────
    claims_list = fact_obj.get("claims")
    if claims_list:
        # Build a seg_id → text lookup from story["segments"]
        seg_text = {}
        if story:
            for seg in (story.get("segments") or []):
                seg_text[seg["id"]] = seg.get("text", "")

        results = []
        for c in claims_list:
            verdict = c.get("verdict", "")
            norm = _normalise_verdict(verdict)
            if norm in target_verifications:
                seg_id = c.get("seg_id")
                # Get the original story sentence from segments, if available
                original_text = seg_text.get(seg_id, "") if seg_id is not None else ""
                explanation   = c.get("explanation", "")
                results.append({
                    "text":          original_text,  # original story sentence from segments
                    "claim":         (original_text or explanation)[:120],  # display label
                    "verification":  norm,
                    "explanation":   explanation,
                    "seg_id":        seg_id,
                })
        return results

    # ── Legacy path (regex on free-text report) ───────────────────────────────
    fact_report = fact_obj.get("report", "")
    pattern = re.compile(
        r'Claim\s+\d+:\s*"([^"]+)"\s*\n'
        r'Verification:\s*(False|Partially[_ ]false|Partially_false|Partially False)\s*\n'
        r'Explanation:\s*(.*?)\n(?=Claim\s+\d+:|\Z)',
        re.MULTILINE | re.DOTALL | re.IGNORECASE
    )
    results = []
    for claim, verification, explanation in pattern.findall(fact_report):
        norm = _normalise_verdict(verification)
        if norm in target_verifications:
            results.append({
                "text":         claim.strip(),   # quoted verbatim from story
                "claim":        claim.strip(),
                "verification": norm,
                "explanation":  explanation.strip(),
                "seg_id":       None,
            })
    return results


def _normalise_verdict(verdict: str) -> str:
    """Normalise verdict strings to one of the 5 canonical categories."""
    v = verdict.strip().lower()
    if "partial" in v and "false" in v:
        return "Partially_false"
    if "partial" in v and "true" in v:
        return "Partially_true"
    if v == "true":
        return "True"
    if v == "false":
        return "False"
    if "opinion" in v:
        return "Opinion"
    return verdict.strip()  # pass through unknown values unchanged


def summarise_fact_checks(fact_checks):
    """Return a numbered list of claims suitable for inclusion in a prompt."""
    lines = []
    for i, fc in enumerate(fact_checks, 1):
        lines.append(
            f"{i}. Claim: \"{fc['claim']}\"\n"
            f"   Verdict: {fc['verification']}\n"
            f"   Explanation: {fc['explanation']}"
        )
    return "\n\n".join(lines)


def print_before_summary(primary, fact_obj, fact_checks, story_index):
    """Show the before-fix scorecard and the list of claims being fixed."""
    w = 72
    score  = fact_obj.get("score")
    counts = fact_obj.get("counts") or [0, 0, 0, 0, 0]
    n_false   = sum(1 for fc in fact_checks if fc["verification"] == "False")
    n_partial = sum(1 for fc in fact_checks if fc["verification"] == "Partially_false")

    print()
    print("─" * w)
    print(f"  BEFORE  Story {story_index}: "
          f"{primary.get('make')} / {primary.get('model')}")
    print(f"  Fact-checker: {fact_obj.get('make')} / {fact_obj.get('model')}")
    title = primary.get("title", "")[:60]
    if title:
        print(f"  Title: {title}")
    print(f"  Score: {score:.2f}   "
          f"True:{counts[0]}  ~True:{counts[1]}  "
          f"Opinion:{counts[2]}  ~False:{counts[3]}  False:{counts[4]}")
    print(f"  Claims to fix: {len(fact_checks)}  "
          f"({n_false} False, {n_partial} Partially_false)")
    print("─" * w)
    for i, fc in enumerate(fact_checks, 1):
        verdict = "✗ False  " if fc["verification"] == "False" else "~ Partial"
        claim_short = fc["claim"][:63] + ("…" if len(fc["claim"]) > 63 else "")
        print(f"  {i:>2}. [{verdict}]  {claim_short}")
    print("─" * w)
    print()


def run_after_factcheck(file_json, story_index, checker_ai, verbose, cache):
    """
    Run st-fact --ai all on the fixed story for an unbiased multi-checker result.
    Displays the live st-fact progress table — no suppression.
    Returns the fact entry from checker_ai for the before/after count comparison,
    or the last fact entry added if checker_ai is not found.
    """
    cache_flag = "--cache" if cache else "--no-cache"
    print(f"\n  Post-fix fact-check — story {story_index} (all AI, unbiased):")
    print()
    subprocess.run(
        ["st-fact", "--ai", "all", "-s", str(story_index),
         "--timeout", "20", cache_flag, file_json],
        check=False,
    )

    try:
        with open(file_json) as f:
            container = json.load(f)
        story = container["story"][story_index - 1]
        facts = story.get("fact", [])
        # Return the fact entry from the original checker AI for apples-to-apples
        # count comparison in print_comparison()
        for fact in reversed(facts):
            if fact.get("make") == checker_ai:
                return fact
        return facts[-1] if facts else None
    except Exception:
        return None


def print_comparison(before_fact, after_fact, n_claims_before):
    """Show a before/after comparison table and how many claims were resolved."""
    w = 72
    b_score  = before_fact.get("score")
    a_score  = after_fact.get("score") if after_fact else None
    b_counts = before_fact.get("counts") or [0, 0, 0, 0, 0]
    a_counts = after_fact.get("counts") or [0, 0, 0, 0, 0] if after_fact else [0]*5

    # Claims resolved = reduction in False + Partially_false
    b_bad = b_counts[3] + b_counts[4]   # ~False + False before
    a_bad = a_counts[3] + a_counts[4]   # ~False + False after
    resolved = max(0, b_bad - a_bad)

    delta = (a_score - b_score) if (a_score is not None and b_score is not None) else None
    delta_str = (f"+{delta:.2f}" if delta >= 0 else f"{delta:.2f}") if delta is not None else "n/a"

    print()
    print("─" * w)
    print(f"  BEFORE / AFTER COMPARISON")
    print(f"  {'':20} {'True':>6} {'~True':>6} {'Opin':>6} {'~False':>7} {'False':>6} {'Score':>7}")
    print(f"  {'─'*20} {'─'*6} {'─'*6} {'─'*6} {'─'*7} {'─'*6} {'─'*7}")
    b_s = f"{b_score:7.2f}" if b_score is not None else "    n/a"
    print(f"  {'Before':<20} {b_counts[0]:>6} {b_counts[1]:>6} {b_counts[2]:>6} "
          f"{b_counts[3]:>7} {b_counts[4]:>6} {b_s}")
    if after_fact:
        a_s = f"{a_score:7.2f}" if a_score is not None else "    n/a"
        print(f"  {'After':<20} {a_counts[0]:>6} {a_counts[1]:>6} {a_counts[2]:>6} "
              f"{a_counts[3]:>7} {a_counts[4]:>6} {a_s}")
        print(f"  {'Change':<20} "
              f"{a_counts[0]-b_counts[0]:>+6} {a_counts[1]-b_counts[1]:>+6} "
              f"{a_counts[2]-b_counts[2]:>+6} {a_counts[3]-b_counts[3]:>+7} "
              f"{a_counts[4]-b_counts[4]:>+6} {delta_str:>7}")
        print()
        print(f"  Claims submitted for fixing : {n_claims_before}")
        print(f"  False/~False before         : {b_bad}")
        print(f"  False/~False after          : {a_bad}")
        print(f"  Resolved                    : {resolved}  "
              f"({'%.0f' % (100*resolved/n_claims_before if n_claims_before else 0)}%)")
    else:
        print(f"  After fact-check not available — run manually:")
        print(f"    st-ls --fact <file.json>")
    print("─" * w)
    print()


# ── Prompt builders ───────────────────────────────────────────────────────────

def get_patch_prompt(report, fact_checks):
    """
    Patch mode: ask the AI for ONLY the changed sentences as JSON pairs.
    Python applies the substitutions — the AI never sees or returns the full report.
    This prevents any model from expanding, rephrasing, or restructuring content
    it was not asked to touch.

    Each claim is pre-classified:
    - REPLACE: explanation contains an explicit corrected value → swap the wrong value
    - HEDGE:   explanation says "no evidence" / "not found" → add a qualifier word only
    """
    lines = []
    for i, fc in enumerate(fact_checks, 1):
        expl       = fc['explanation'].strip()
        expl_lower = expl.lower()

        no_evidence_phrases = [
            "no evidence", "no search results", "not found", "not mentioned",
            "cannot confirm", "no results mention", "no sources", "not verified",
            "unverified", "no data", "could not find", "no reference",
        ]
        has_no_evidence = any(p in expl_lower for p in no_evidence_phrases)

        correction_patterns = [
            r'\bnot\s+\w',
            r'\bshould be\b',
            r'\bactually\b',
            r'\bcorrect\w*\s+is\b',
            r'\bin fact\b',
            r'\bfounded in\b',
            r'\b\d{4}\b',
            r'https?://',
            r'\$[\d,]+',
        ]
        has_correction = any(re.search(p, expl, re.IGNORECASE)
                             for p in correction_patterns)

        if has_no_evidence:
            action = "HEDGE"
            instruction = (
                'Add one hedging qualifier (e.g. "reportedly", "according to xAI", '
                '"as claimed") to the sentence containing this claim. '
                'Return only the changed sentence — do not add new facts or change anything else.'
            )
        elif has_correction:
            action = "REPLACE"
            instruction = (
                "Substitute only the incorrect value with the corrected value from the explanation. "
                "Change as few words as possible. "
                "Return only the changed sentence."
            )
        else:
            action = "HEDGE"
            instruction = (
                'Add one hedging qualifier (e.g. "reportedly", "as described") to the sentence. '
                "Return only the changed sentence."
            )

        lines.append(
            f"Claim {i} [{action}]: \"{fc['claim']}\"\n"
            f"  Explanation: {fc['explanation']}\n"
            f"  Instruction: {instruction}"
        )

    fc_block = "\n\n".join(lines)

    return f"""You are a surgical text editor making minimal corrections to a report.

For each claim below, find the matching sentence in the report and produce the \
corrected version of THAT SENTENCE ONLY.

Return a JSON array. Each element must have exactly two keys:
  "old": the exact sentence from the report (copied verbatim, character-for-character)
  "new": the corrected sentence (minimum change only)

Rules:
- "old" must be an exact verbatim substring of the report — copy it character-for-character.
- "new" must differ from "old" by as few words as possible.
- Do NOT change any sentence other than the one identified.
- Do NOT add new sentences, paragraphs, facts, URLs, or statistics.
- For HEDGE: add one qualifier word or phrase only. Do not rewrite the sentence.
- For REPLACE: change only the incorrect value. Do not rewrite surrounding context.
- Return valid JSON only — no commentary, no markdown fences, no explanation.

Claims to fix:
{fc_block}

Report:
{report}
"""


def _apply_substitutions(original_text, substitutions):
    """
    Apply a list of (old, new) substitutions to original_text.
    Each substitution is applied once, to the first occurrence.
    Returns (patched_text, applied_count, failed_list).

    Falls back to the original text unchanged if no substitutions could be applied.
    """
    text         = original_text
    applied      = 0
    failed       = []

    for old, new in substitutions:
        old = old.strip()
        new = new.strip()
        if not old or old == new:
            continue
        if old in text:
            text    = text.replace(old, new, 1)
            applied += 1
        else:
            # Try a more lenient match: strip leading/trailing punctuation differences
            old_norm = old.strip('.,;:!?"\'')
            pos = text.find(old_norm)
            if pos != -1:
                # Find the full sentence boundary around this match
                text    = text[:pos] + new.strip('.,;:!?"\'') + text[pos + len(old_norm):]
                applied += 1
            else:
                failed.append(old[:80])

    return text, applied, failed


def _parse_substitutions(ai_response_text):
    """
    Parse the AI's JSON array of {old, new} pairs.
    Returns list of (old, new) tuples, or [] on parse failure.
    """
    text = ai_response_text.strip()

    # Strip markdown fences if the model wrapped it anyway
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'```\s*$', '', text, flags=re.MULTILINE)
    text = text.strip()

    # Find the JSON array
    start = text.find('[')
    end   = text.rfind(']')
    if start == -1 or end == -1:
        return []

    try:
        pairs = json.loads(text[start:end + 1])
        return [(p['old'], p['new']) for p in pairs
                if isinstance(p, dict) and 'old' in p and 'new' in p]
    except (json.JSONDecodeError, KeyError):
        return []


def _find_sentence_containing(text, claim_fragment, explanation="", min_match=20):
    """
    Find the sentence in text that best contains the claim fragment.

    Search order:
    1. Exact substring match on claim_fragment (the original story sentence / quoted claim)
    2. Word-overlap match on claim_fragment words
    3. Word-overlap match on key noun phrases extracted from explanation
       (used when claim_fragment is the explanation itself, not the original sentence)

    Splits on sentence-ending punctuation. Returns the sentence string or "".
    """
    # Split into sentences on . ! ? followed by whitespace or end
    sentences = re.split(r'(?<=[.!?])\s+', text)

    def _best_overlap(fragment):
        """Return (best_sentence, overlap_count) for the fragment against all sentences."""
        frag_words = set(re.findall(r'\b\w{4,}\b', fragment.lower()))  # 4+ char words only
        if not frag_words:
            return "", 0
        best_s, best_count = "", 0
        for s in sentences:
            s_words = set(re.findall(r'\b\w{4,}\b', s.lower()))
            overlap = len(frag_words & s_words)
            if overlap > best_count:
                best_count, best_s = overlap, s
        threshold = max(1, len(frag_words) // 2)
        return (best_s, best_count) if best_count >= threshold else ("", 0)

    fragment = claim_fragment.strip()

    # 1. Exact substring match on claim_fragment
    for s in sentences:
        if fragment in s:
            return s

    # 2. Word-overlap on claim_fragment
    best_s, count = _best_overlap(fragment)
    if best_s:
        return best_s

    # 3. The claim_fragment may itself be the explanation (structured path with no
    #    original text stored). Fall back to key terms from the explanation.
    if explanation and explanation.strip() != fragment:
        # Use the first sentence of the explanation as the search fragment —
        # it typically names the incorrect claim value
        expl_first = explanation.split('.')[0].strip()
        for s in sentences:
            if expl_first and expl_first[:30].lower() in s.lower():
                return s
        best_s, count = _best_overlap(explanation)
        if best_s:
            return best_s

    return ""


def _get_sentence_context(text, sentence, n=1):
    """
    Return up to n sentences before and after the given sentence in text.
    Used to give the fix AI context without exposing the full report.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text)
    try:
        idx = next(i for i, s in enumerate(sentences) if sentence in s or s in sentence)
    except StopIteration:
        return "", ""
    before = " ".join(sentences[max(0, idx - n):idx])
    after  = " ".join(sentences[idx + 1:idx + 1 + n])
    return before, after


def _parse_inline_verdict(checker_response: str) -> str:
    """
    Parse the verdict from a single-sentence fact-check response.
    Expected format:  "Verdict: True\nReason: ..."
    Falls back to scanning for verdict keywords.
    """
    for line in checker_response.splitlines():
        line_stripped = line.strip()
        if line_stripped.lower().startswith("verdict:"):
            raw = line_stripped.split(":", 1)[1].strip()
            return _normalise_verdict(raw)

    # Fallback: scan for verdict keywords
    text_lower = checker_response.lower()
    if "partially_false" in text_lower or "partially false" in text_lower:
        return "Partially_false"
    if "partially_true" in text_lower or "partially true" in text_lower:
        return "Partially_true"
    if "false" in text_lower:
        return "False"
    if "true" in text_lower:
        return "True"
    if "opinion" in text_lower:
        return "Opinion"
    return "Partially_false"   # conservative default when unparseable


def get_single_fix_prompt(sentence, explanation, action, context_before="", context_after=""):
    """
    Ask the AI to rewrite ONE sentence.
    Returns the corrected sentence only — not the full report.
    Context lines are provided so the AI understands the surrounding topic
    without being able to rewrite them.
    """
    context_block = ""
    if context_before or context_after:
        context_block = "\nContext (surrounding sentences — do NOT change these):\n"
        if context_before:
            context_block += f"  Before: {context_before.strip()}\n"
        if context_after:
            context_block += f"  After:  {context_after.strip()}\n"

    if action == "HEDGE":
        instruction = (
            "Add one hedging qualifier (e.g. 'reportedly', 'according to xAI', "
            "'as claimed', 'at the time of writing') to soften this claim. "
            "Do NOT add new facts, numbers, URLs, or statistics. "
            "Keep the sentence length similar."
        )
    else:  # REPLACE
        instruction = (
            "Substitute only the incorrect value with the correction stated in the "
            "explanation. Change as few words as possible — only the wrong value."
        )

    return f"""You are a surgical text editor. Rewrite the single sentence below.

Sentence to fix:
  "{sentence}"

Why it is wrong:
  {explanation}

What to do ({action}):
  {instruction}
{context_block}
Return only the corrected sentence — no quotes, no commentary, no explanation."""


def get_single_factcheck_prompt(original_sentence, candidate_sentence, topic_context=""):
    """
    Ask an AI to fact-check ONE candidate sentence against the original.
    Returns a simple verdict: True / Partially_true / Partially_false / False
    plus a one-line explanation.

    This is intentionally a tiny, fast prompt — no web search required.
    We are checking whether the rewrite is factually better than the original,
    not doing a full research pass.
    """
    ctx = f"\nTopic context: {topic_context.strip()}" if topic_context else ""

    return f"""You are a fact-checker. Compare the ORIGINAL sentence and the CANDIDATE \
rewrite below.{ctx}

ORIGINAL:  {original_sentence}
CANDIDATE: {candidate_sentence}

Is the CANDIDATE sentence factually accurate and an improvement over the ORIGINAL?

Respond with exactly this format (two lines, nothing else):
Verdict: <True|Partially_true|Partially_false|False>
Reason: <one sentence>

Verdicts:
  True            — candidate is factually correct and better than the original
  Partially_true  — candidate is mostly correct; minor hedging or uncertainty remains
  Partially_false — candidate still contains an inaccuracy or is overly vague
  False           — candidate introduced a new error or is no better than the original"""


def _verdict_score(verdict: str) -> int:
    """Convert a verdict string to a numeric score for comparison.
    Higher is better."""
    return {"True": 3, "Partially_true": 2, "Partially_false": 1, "False": 0}.get(
        _normalise_verdict(verdict), 0)


def get_best_source_prompt(report, fact_checks, alternate_stories):
    """
    Best-source mode: AI returns JSON substitution pairs just like patch mode,
    but uses alternative AI stories as the source of correct facts.
    Never returns the full report — only the changed sentences.
    """
    fc_summary = summarise_fact_checks(fact_checks)

    alt_block = ""
    for i, (make, model, score, text) in enumerate(alternate_stories, 1):
        score_str = f"{score:.2f}" if score is not None else "n/a"
        alt_block += f"\n--- Alternative {i}: {make}/{model} (score {score_str}) ---\n{text}\n"

    return f"""You are a surgical text editor. For each claim below, find the matching \
sentence in the Primary Report and produce only the corrected sentence.

Use the Alternative versions as your source of correct facts. If an alternative \
covers the same claim more accurately, adopt that fact (in your own minimal wording). \
If no alternative is better, add a hedging qualifier ("reportedly", "according to xAI") \
instead of asserting the claim.

Return a JSON array. Each element must have exactly two keys:
  "old": the exact sentence from the Primary Report (copied verbatim)
  "new": the corrected sentence (minimum change only)

Rules:
- "old" must be a verbatim substring of the Primary Report.
- "new" must differ from "old" by as few words as possible.
- Do NOT invent facts not present in the Primary Report or Alternatives.
- Do NOT add new sentences, paragraphs, or sections.
- Return valid JSON only — no commentary, no markdown fences.

Claims to fix:
{fc_summary}

Primary Report:
{report}

Alternatives for reference:
{alt_block}
"""


def _get_consolidation_prompt(original, batch_versions):
    """
    Consolidation pass for multi-batch fixes.

    Each batch_version is a copy of the report with a different subset of claims
    fixed. The consolidation prompt merges all the corrections into one final
    version by comparing each batch-version against the original.

    Critically: only changes that appear in a batch-version and NOT in the
    original are accepted. Nothing new is added.
    """
    blocks = ""
    for i, bv in enumerate(batch_versions, 1):
        blocks += f"\n--- Patched Version {i} ---\n{bv}\n"

    return f"""You are a merge editor. You have an original report and {len(batch_versions)} \
partially-patched versions of it. Each patched version has fixed a different subset of \
inaccurate claims. Your job is to produce one final version that incorporates all the \
corrections from all the patched versions.

RULES:
1. Start with the original report as your base.
2. For each sentence that differs between a patched version and the original, \
adopt the patched version's wording for that sentence.
3. If two patched versions disagree on the same sentence, prefer the version \
that makes a smaller, more targeted change (fewer words changed).
4. Do NOT add any content that does not appear in either the original or the \
patched versions.
5. Do NOT rewrite, rephrase, or improve any sentence that is identical across \
all versions.
6. Return only the final merged report — no commentary, no tags.

Original Report:
{original}
{blocks}"""


def build_claims_scorecard(stories):
    """
    Build a per-segment trust map across all stories and all AI fact-checkers.

    Returns a list of dicts, one per story, each containing:
      {
        "make":     str,
        "model":    str,
        "avg_score": float | None,
        "segments": [
          {
            "id":       int,
            "text":     str,          # the checkable sentence/paragraph
            "verdicts": {             # keyed by "make/model" of the checker
              "xai/grok-4-latest":        "True",
              "anthropic/claude-opus-4-5": "Partially_false",
              ...
            },
            "true_count":    int,     # number of checkers who said True
            "problem_count": int,     # number of checkers who said False or Partially_false
          },
          ...
        ]
      }

    Only segments that appear in story["segments"] AND have at least one
    verdict in any fact entry are included.  Stories without segments or
    without any fact entries are included with an empty segments list.
    """
    scorecard = []
    for story in stories:
        avg = avg_score_for_story(story)
        segs = story.get("segments") or []
        facts = story.get("fact") or []

        # Build a lookup: seg_id -> {checker_label -> verdict}
        seg_verdicts: dict[int, dict[str, str]] = {}
        for seg in segs:
            seg_verdicts[seg["id"]] = {}

        for fact in facts:
            label = f"{fact.get('make','?')}/{fact.get('model','?')}"
            for claim in (fact.get("claims") or []):
                sid = claim.get("seg_id")
                verdict = claim.get("verdict", "")
                if sid is not None and sid in seg_verdicts:
                    seg_verdicts[sid][label] = verdict

        # Build the segment list with aggregate counts
        seg_id_to_text = {s["id"]: s.get("text", "") for s in segs}
        seg_list = []
        for seg in segs:
            sid = seg["id"]
            verdicts = seg_verdicts.get(sid, {})
            if not verdicts:
                continue   # no checker looked at this segment — skip
            true_count    = sum(1 for v in verdicts.values() if v == "True")
            problem_count = sum(1 for v in verdicts.values()
                                if v in ("False", "Partially_false"))
            seg_list.append({
                "id":            sid,
                "text":          seg_id_to_text.get(sid, ""),
                "verdicts":      verdicts,
                "true_count":    true_count,
                "problem_count": problem_count,
            })

        scorecard.append({
            "make":      story.get("make"),
            "model":     story.get("model"),
            "avg_score": avg,
            "segments":  seg_list,
        })

    return scorecard


def _format_scorecard_block(scorecard):
    """
    Format the scorecard into a compact, human-readable block for inclusion
    in the synthesize prompt.

    Each story section lists its segments with verdicts from every checker,
    flagging problem segments clearly so the AI knows what to avoid.
    """
    VERDICT_ICON = {
        "True":            "✓",
        "Partially_true":  "~",
        "Opinion":         "○",
        "Partially_false": "✗~",
        "False":           "✗",
    }

    lines = []
    for entry in scorecard:
        make  = entry["make"]
        model = entry["model"]
        avg   = entry["avg_score"]
        score_str = f"{avg:.2f}" if avg is not None else "n/a"
        lines.append(f"\n=== {make} / {model}  (avg score {score_str}) ===")

        segs = entry["segments"]
        if not segs:
            lines.append("  (no segment-level fact-check data)")
            continue

        # Show all segments; highlight problems
        for seg in segs:
            text_clip = seg["text"][:80].replace("\n", " ")
            verdict_str = "  ".join(
                f"{lbl.split('/')[0]}:{VERDICT_ICON.get(v, v)}"
                for lbl, v in sorted(seg["verdicts"].items())
            )
            flag = "  ⚠ " if seg["problem_count"] > 0 else "    "
            lines.append(f"{flag}[seg {seg['id']:>2}] {text_clip}")
            lines.append(f"          {verdict_str}")

    return "\n".join(lines)


def get_synthesize_prompt(stories_with_scores, prompt_from_file, scorecard=None,
                          base_make: str = "", base_model: str = ""):
    """
    Synthesize mode: the AI that wrote the highest-scoring story rewrites
    its own report in its own voice, incorporating verified corrections and
    stronger content from the other AI versions.

    The rewriter is told this is its own work — single voice throughout.
    Other stories contribute facts, not prose.

    stories_with_scores: list of (make, model, avg_score, plain_text)
    scorecard:           output of build_claims_scorecard(), or None
    base_make/model:     the author of the highest-scoring story (the rewriter)
    """
    story_block = ""
    for make, model, score, text in stories_with_scores:
        score_str = f"{score:.2f}" if score is not None else "n/a"
        own_label = "  ← YOUR STORY" if make == base_make else ""
        story_block += (
            f"\n--- {make} / {model}  (avg fact-check score {score_str}){own_label} ---\n"
            f"{text}\n"
        )

    scorecard_block = ""
    scorecard_instructions = ""
    if scorecard:
        scorecard_block = (
            "\nPer-segment fact-check scorecard "
            "(✓=True  ~=Partially_true  ○=Opinion  ✗~=Partially_false  ✗=False  "
            "⚠=has one or more False/Partially_false verdicts):\n"
            + _format_scorecard_block(scorecard)
            + "\n"
        )
        scorecard_instructions = (
            "4. Use the per-segment scorecard to identify exactly which sentences "
            "each AI got right or wrong:\n"
            "   • Prefer segments with high true_count (many checkers agreed it is True).\n"
            "   • Avoid or rewrite segments marked ⚠ (one or more checkers flagged False "
            "or Partially_false).\n"
            "   • When two AI disagree on the same fact, favour the version that more "
            "checkers rated True.\n"
        )

    n = len(stories_with_scores)
    base_label = f"{base_make} / {base_model}" if base_make else "the highest-scoring AI"

    return f"""You are {base_label}.

You previously wrote the report marked "YOUR STORY" below. It received the
highest average fact-check score among {n} AI-generated reports on this topic.

Your task is to produce an improved final version of YOUR OWN report.
Write entirely in your own voice — consistent tone, rhythm, and style
throughout. Do not adopt the phrasing or writing style of the other AI.

The other AI reports are provided as reference material. Where they contain
more accurate or better-supported information on a specific claim, incorporate
that fact into your rewrite — expressed in your own words.

Original prompt all reports were written from:
{prompt_from_file}

All reports (YOUR STORY is marked):
{story_block}
{scorecard_block}
Instructions:
1. Use YOUR STORY as the structural backbone — preserve its narrative arc,
   section order, and voice.
2. Where other higher-scoring AI reports cover a claim more accurately,
   incorporate the correct fact — but write it in your own words.
3. Prefer higher-scoring AI versions when accounts conflict on a specific fact.
{scorecard_instructions}4. Do not copy sentences verbatim from other AI reports — translate facts
   into your own prose.
5. Do not mention that corrections were made or that other AI were consulted.
   The output should read as a single authoritative original report.
6. Match the length of YOUR STORY.
7. Return only the improved report — no commentary, no preamble.
"""


# ── Score helpers ─────────────────────────────────────────────────────────────

def avg_score_for_story(story):
    """Return the mean fact-check score across all fact entries for a story."""
    scores = [f["score"] for f in story.get("fact", []) if f.get("score") is not None]
    return sum(scores) / len(scores) if scores else None


# ── Save result ───────────────────────────────────────────────────────────────

def _save_result(container, file_json, args,
                 story_make, story_model, fc_ai_model,
                 revised_text, gen_payload, gen_response, original_story,
                 before_fact=None, n_claims_before=0,
                 skip_after_factcheck=False):
    """
    Save the revised story as a new story entry in the container.
    This makes it visible to st-ls, st-edit, st-post, and st-fact like any other story.
    Also saves the raw generation data entry for auditing.

    skip_after_factcheck: if True, skip the automatic post-fix fact-check
    (used by iterate mode, which verifies each sentence inline).
    """
    container_modified = False

    # ── Data entry (raw generation for audit trail) ───────────────────────────
    # make must match the AI that produced gen_response (the rewriter, args.ai),
    # not story_make — they differ when a story by AI-A is rewritten by AI-B,
    # and mixing them causes get_data_title to parse the wrong response format.
    if gen_response and isinstance(gen_response, dict):
        gen_response_final = put_content(args.ai, revised_text, gen_response)
    else:
        gen_response_final = gen_response   # "" or non-dict — leave as-is
    data = {
        "make":        args.ai,       # AI that wrote gen_response (the rewriter)
        "model":       fc_ai_model,
        "story_make":  story_make,    # original story author (for provenance)
        "story_model": story_model,
        "fc_make":     args.ai,
        "fc_model":    fc_ai_model,
        "mode":        args.mode,
        "gen_payload":  gen_payload,
        "gen_response": gen_response_final,
    }
    data_str = json.dumps(data, sort_keys=True)
    data["md5_hash"] = hashlib.md5(data_str.encode()).hexdigest()

    dup_data = next((i + 1 for i, d in enumerate(container.get("data", []))
                     if d.get("md5_hash") == data["md5_hash"]), None)
    data_index = dup_data
    if dup_data is None:
        container.setdefault("data", []).append(data)
        data_index = len(container["data"])
        container_modified = True

    # ── Story entry ───────────────────────────────────────────────────────────
    story = {
        "make":     story_make,
        "model":    story_model,
        "fixed_by": args.ai,
        "fix_mode": args.mode,
        "title":    original_story.get("title", ""),
        "markdown": revised_text,
        "text":     remove_markdown(revised_text),
        "spoken":   original_story.get("spoken", ""),
        "hashtags": original_story.get("hashtags", []),
        "fact":     [],
    }
    story_str = json.dumps(story, sort_keys=True)
    story["md5_hash"] = hashlib.md5(story_str.encode()).hexdigest()

    dup_story = next((i + 1 for i, s in enumerate(container.get("story", []))
                      if s.get("md5_hash") == story["md5_hash"]), None)
    story_index = dup_story
    if dup_story is None:
        container.setdefault("story", []).append(story)
        story_index = len(container["story"])
        container_modified = True
        if not args.quiet:
            print(f"  Added fixed story as story {story_index}  "
                  f"(make: {story_make}, mode: {args.mode})")
    else:
        if not args.quiet:
            print(f"  Identical result already exists as story {story_index} — no change.")

    if container_modified:
        with open(file_json, 'w', encoding='utf-8') as f:
            json.dump(container, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        if not args.quiet:
            print(f"  Container updated: {file_json}")
        if args.prep and data_index:
            subprocess.run(f"st-prep -d {data_index} {file_json}".split())

        # ── Before/after comparison ───────────────────────────────────────────
        if (not args.quiet and not skip_after_factcheck
                and before_fact is not None and story_index is not None):
            checker_ai = before_fact.get("make", args.ai)
            with Spinner(f"  Fact-checking fixed story with {checker_ai}", quiet=False):
                after_fact = run_after_factcheck(
                    file_json, story_index, checker_ai, args.verbose, args.cache)
            print_comparison(before_fact, after_fact, n_claims_before)
    else:
        if not args.quiet:
            print("  No changes — container not written.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-fix',
        description="Improve a story using fact-check feedback.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  iterate      Claim-by-claim: fix one sentence, fact-check it immediately,
               keep if improved, else try the next AI. Tries all 5 AI per
               claim before giving up. (default)
  patch        Fix all false claims in one pass (fast, less reliable)
  best-source  Use other AI versions as reference material
  synthesize   Merge all AI stories weighted by fact-check score
        """)
    parser.add_argument('-s', '--story', type=int, default=None,
                        help='Story number to fix (default: auto-select most fixable)')
    parser.add_argument('-f', '--fact', type=int, default=None,
                        help='Fact-check number to use (default: auto-select most fixable). '
                             'Not used in synthesize mode.')
    parser.add_argument('--mode', choices=['iterate', 'patch', 'best-source', 'synthesize'],
                        default='iterate',
                        help='Fix strategy (default: iterate)')
    parser.add_argument('json_file', type=str,
                        help='Path to the JSON file', metavar='file.json')
    parser.add_argument('-a', '--ai', type=str, choices=get_ai_list(), default=None,
                        help='AI to use for rewriting (default: same AI that wrote the story)')
    parser.add_argument('--checker', type=str, choices=get_ai_list(), default=None,
                        help='AI to use for inline fact-checking in iterate mode '
                             '(default: the original fact-checker from -f)')
    parser.add_argument('--cache', dest='cache', action='store_true', default=True,
                        help='Enable API cache (default: on)')
    parser.add_argument('--no-cache', dest='cache', action='store_false',
                        help='Disable API cache')
    parser.add_argument('--prep', action='store_true',
                        help='Run st-prep on the result')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show diff of each change')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Minimal output')
    args = parser.parse_args()

    file_prefix = args.json_file.rsplit('.', 1)[0]
    file_json   = file_prefix + ".json"
    file_prompt = file_prefix + ".prompt"

    load_cross_env()

    try:
        if not os.path.isfile(file_json):
            print(f"Error: {file_json} does not exist.")
            sys.exit(1)
        with open(file_json, 'r') as f:
            container = json.load(f)
    except json.JSONDecodeError:
        print(f"Error: {file_json} contains invalid JSON.")
        sys.exit(1)

    stories = container.get("story", [])
    n_stories = len(stories)

    # ── Build ranked fixable table ────────────────────────────────────────────
    def _fixable_candidates():
        """Return list of (n_false, story_idx, fact_idx, story, fact_obj) sorted
        by n_false descending — only entries with at least 1 False/Partially_false."""
        verifications = ["False", "Partially_false"]
        candidates = []
        for si, s in enumerate(stories, 1):
            for fi, f in enumerate(s.get("fact", []), 1):
                fc = extract_fact_checks(f, verifications, story=s)
                if fc:
                    candidates.append((len(fc), si, fi, s, f))
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates

    def _print_fixable_table(candidates, highlight_s=None, highlight_f=None):
        """Print a ranked table of fixable story+fact combos."""
        print()
        print("  Fixable story/fact combinations (ranked by claim count):")
        print(f"  {'':2} {'S':>2}  {'F':>2}  {'Story AI':<12} {'Checker AI':<12} "
              f"{'Score':>6}  {'False':>5}  {'~False':>6}  {'Total':>5}")
        print("  " + "─" * 68)
        for n_f, si, fi, s, fo in candidates:
            counts  = fo.get("counts") or [0, 0, 0, 0, 0]
            score   = fo.get("score")
            sc_str  = f"{score:.2f}" if score is not None else " n/a"
            n_false = counts[4]
            n_pfals = counts[3]
            marker  = " ◀" if si == highlight_s and fi == highlight_f else ""
            print(f"  {'':2} {si:>2}  {fi:>2}  {s.get('make','?'):<12} "
                  f"{fo.get('make','?'):<12} {sc_str:>6}  "
                  f"{n_false:>5}  {n_pfals:>6}  {n_f:>5}{marker}")
        print()
        if candidates:
            best = candidates[0]
            print(f"  Suggestion:  st-fix -s {best[1]} -f {best[2]} "
                  f"{os.path.basename(file_json)}")
        print()

    # ── Auto-select story + fact when not explicitly provided ─────────────────
    auto_selected = (args.story is None and args.fact is None
                     and args.mode != "synthesize")
    if auto_selected:
        candidates = _fixable_candidates()
        if not candidates:
            print("No False or Partially_false claims found in any fact-check.")
            print("Nothing to fix — all stories are clean.")
            sys.exit(0)
        best_n, best_s, best_f, _, _ = candidates[0]
        args.story = best_s
        args.fact  = best_f
        if not args.quiet:
            print(f"  Auto-selected: story {args.story}, "
                  f"fact-check {args.fact}  ({best_n} claims to fix)")
            _print_fixable_table(candidates,
                                 highlight_s=args.story, highlight_f=args.fact)

    # Apply defaults of 1 if still None (synthesize mode or explicit partial args)
    if args.story is None:
        args.story = 1
    if args.fact is None:
        args.fact  = 1

    # ── Validate story selection ──────────────────────────────────────────────
    if not (1 <= args.story <= n_stories):
        print(f"Error: story {args.story} out of range (1–{n_stories})")
        sys.exit(1)
    primary = stories[args.story - 1]
    primary_make  = primary["make"]
    primary_model = primary["model"]
    primary_text  = primary.get("markdown", "")

    # ── Resolve rewriter AI ───────────────────────────────────────────────────
    # Default to the story's own AI (same voice, better results).
    # Fall back to get_default_ai() if the story's AI is not in the registry
    # (e.g. make="url" for fetched stories).
    if args.ai is None:
        if primary_make in get_ai_list():
            args.ai = primary_make
        else:
            args.ai = get_default_ai()
        if not args.quiet and args.mode != "synthesize":
            print(f"  Rewriter: {args.ai} (story author — use -a to override)")

    # ── Synthesize mode ───────────────────────────────────────────────────────
    if args.mode == "synthesize":
        if n_stories < 2:
            print("Error: synthesize mode requires at least 2 stories in the container.")
            sys.exit(1)

        prompt_from_file = ""
        if os.path.isfile(file_prompt):
            with open(file_prompt) as f:
                prompt_from_file = f.read()

        # ── Select base story: highest avg fact-check score ───────────────────
        # The AI that wrote the best story rewrites it in its own voice.
        # Other stories contribute verified facts, not prose.
        scored_for_base = [(avg_score_for_story(s), i, s) for i, s in enumerate(stories)]
        scored_for_base.sort(key=lambda x: x[0] if x[0] is not None else -99, reverse=True)
        base_score_val, base_idx, base_story = scored_for_base[0]
        base_make  = base_story.get("make", "")
        base_model = base_story.get("model", "")

        # Lock the rewriter to the base story's author — single voice throughout
        rewriter_ai = base_make if base_make in get_ai_list() else args.ai
        if rewriter_ai != args.ai and not args.quiet:
            print(f"  Rewriter: {rewriter_ai} (author of best story — overrides --ai)")

        # Build ordered list: (make, model, avg_score, text) with stable story index
        stories_with_scores = []
        for i, s in enumerate(stories):
            avg = avg_score_for_story(s)
            stories_with_scores.append((
                s.get("make"), s.get("model"), avg,
                remove_markdown(s.get("markdown", "")),
                i,          # original index — used for ◀ base marker
            ))

        # Sort best score first so the AI sees the highest-quality work first
        stories_with_scores.sort(key=lambda x: x[2] if x[2] is not None else -99, reverse=True)

        # Build per-segment claims scorecard
        scored_stories = [s for s in stories if s.get("segments") and s.get("fact")]
        scorecard = build_claims_scorecard(scored_stories) if scored_stories else None

        if not args.quiet:
            print(f"Synthesize mode: {n_stories} stories, rewriter: {rewriter_ai}")
            for make, model, score, _, orig_idx in stories_with_scores:
                score_str = f"{score:.2f}" if score is not None else " n/a"
                marker = "◀ base" if orig_idx == base_idx else ""
                print(f"  {make:12} {model:24} avg score: {score_str}  {marker}")
            if scorecard:
                total_segs = sum(len(e["segments"]) for e in scorecard)
                print(f"  Scorecard: {len(scorecard)} stories, {total_segs} scored segments")
            else:
                print("  Scorecard: not available (run st-cross first for best results)")

        # Strip the orig_idx sentinel before passing to prompt builder
        stories_for_prompt = [(make, model, score, text)
                              for make, model, score, text, _ in stories_with_scores]

        prompt = get_synthesize_prompt(
            stories_for_prompt, prompt_from_file, scorecard,
            base_make=base_make, base_model=base_model)

        # Baseline: avg score across all original scored stories
        baseline_scores = [
            avg_score_for_story(s)
            for s in scored_stories
            if avg_score_for_story(s) is not None
        ]
        baseline_avg = sum(baseline_scores) / len(baseline_scores) if baseline_scores else None

        # ── Call AI with retry on transient errors (503, 429, ServerError) ────
        MAX_RETRIES = 3
        RETRY_WAIT  = 15   # seconds between retries
        last_error  = None
        gen_payload = gen_response = fc_ai_model = ""
        active_ai   = rewriter_ai

        PERMANENT_429_SYNTH = (
            "credits", "spending limit", "billing", "quota", "exhausted",
            "payment", "upgrade", "plan", "subscribe",
        )
        TRANSIENT_SYNTH = (
            "503", "UNAVAILABLE", "overloaded", "temporarily",
            "high demand", "try again",
        )

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                label = (f"  Calling AI synthesizer ({active_ai})"
                         if attempt == 1 else
                         f"  Retry {attempt}/{MAX_RETRIES} ({active_ai})")
                with Spinner(label, quiet=args.quiet):
                    gen_payload, client, gen_response, fc_ai_model = (
                        process_prompt(active_ai, prompt, verbose=args.verbose, use_cache=args.cache))
                last_error = None
                break   # success
            except Exception as e:
                last_error = e
                err_str    = str(e).lower()

                is_permanent = any(k in err_str for k in PERMANENT_429_SYNTH)
                is_transient = any(k in err_str for k in TRANSIENT_SYNTH) or (
                    "429" in str(e) and not is_permanent
                )

                if not args.quiet:
                    print(f"\n  {active_ai} error: {str(e)[:140]}")

                if is_permanent:
                    print(f"\n  {active_ai}: API credits exhausted or spending limit reached.")
                    print(f"  Add credits at your {active_ai} dashboard, then retry.")
                    print(f"  Or rewrite with a different AI:  st-fix --mode synthesize -a <ai> ...")
                    sys.exit(1)

                if is_transient and attempt < MAX_RETRIES:
                    # On first transient failure try --ai fallback before waiting
                    if active_ai == rewriter_ai and args.ai != rewriter_ai:
                        active_ai = args.ai
                        if not args.quiet:
                            print(f"  Falling back to --ai {active_ai}")
                    else:
                        if not args.quiet:
                            print(f"  Waiting {RETRY_WAIT}s before retry…")
                        time.sleep(RETRY_WAIT)
                else:
                    break   # non-transient or out of retries

        if last_error is not None:
            print(f"\nError: synthesize failed after {MAX_RETRIES} attempts.")
            print(f"  Last error: {last_error}")
            print(f"  Try again later, or specify a different AI with --ai")
            sys.exit(1)

        revised = get_content(active_ai, gen_response)

        if args.verbose:
            print_diff(primary_text, revised)

        # If we fell back to a different AI, record that in the story make
        save_make  = base_make  if active_ai == rewriter_ai else active_ai
        save_model = base_model if active_ai == rewriter_ai else fc_ai_model

        _save_result(container, file_json, args,
                     save_make, save_model, fc_ai_model,
                     revised, gen_payload, gen_response, base_story)

        # ── After: fact-check with ALL AI for unbiased multi-checker score ────
        try:
            with open(file_json) as fh:
                container2 = json.load(fh)
            synth_index = len(container2.get("story", []))
        except Exception:
            synth_index = None

        if not args.quiet and synth_index:
            print(f"\n  Post-synthesize fact-check — story {synth_index} (all AI, unbiased):")
            print()
            subprocess.run(
                ["st-fact", "--ai", "all", "-s", str(synth_index),
                 "--timeout", "20", file_json],
                check=False,
            )

            # Re-read for per-checker breakdown
            try:
                with open(file_json) as fh:
                    container3 = json.load(fh)
                synth_story = container3["story"][synth_index - 1]
                synth_facts = synth_story.get("fact", [])
                after_avg = avg_score_for_story(synth_story)
            except Exception:
                synth_facts = []
                after_avg = None

            if after_avg is not None:
                w = 72
                delta = (after_avg - baseline_avg) if baseline_avg is not None else None
                delta_str = (f"+{delta:.2f}" if delta >= 0 else f"{delta:.2f}") if delta is not None else "n/a"
                print()
                print("─" * w)
                print("  SYNTHESIZE RESULT")
                if baseline_avg is not None:
                    print(f"  {'Source stories avg score':<32} {baseline_avg:.2f}")
                for fc in synth_facts:
                    fc_score = fc.get("score")
                    fc_make  = fc.get("make", "?")
                    fc_model = fc.get("model", "?")
                    score_str = f"{fc_score:.2f}" if fc_score is not None else " n/a"
                    print(f"  {fc_make:<14} {fc_model:<24} {score_str}")
                print(f"  {'─'*44}")
                print(f"  {'Synthesized story avg score':<32} {after_avg:.2f}")
                if baseline_avg is not None:
                    print(f"  {'Delta vs source avg':<32} {delta_str}")
                print("─" * w)
                print()
        return

    # ── Patch / best-source modes: need a fact-check ──────────────────────────
    facts = primary.get("fact", [])
    n_facts = len(facts)
    if not (1 <= args.fact <= n_facts):
        print(f"Error: fact {args.fact} out of range (1–{n_facts})")
        sys.exit(1)

    fact_obj    = facts[args.fact - 1]
    fact_make   = fact_obj.get("make", "?")
    fact_model  = fact_obj.get("model", "?")

    verifications = ["False", "Partially_false"]
    fact_checks = extract_fact_checks(fact_obj, verifications, story=primary)
    n_false = len(fact_checks)

    if n_false == 0:
        s_make  = primary.get("make", "?")
        f_make  = fact_obj.get("make", "?")
        score   = fact_obj.get("score")
        sc_str  = f"{score:.2f}" if score is not None else "n/a"
        print(f"  Story {args.story} ({s_make}) — fact-check {args.fact} "
              f"({f_make}, score {sc_str}): no False or Partially_false claims.")
        candidates = _fixable_candidates()
        if candidates:
            print("  Other fact-checks do have claims to fix:")
            _print_fixable_table(candidates)
        else:
            print("  All fact-checks are clean — nothing to fix.")
        sys.exit(0)

    if not args.quiet:
        print_before_summary(primary, fact_obj, fact_checks, args.story)

    # ── Shared retry helper for patch / best-source ───────────────────────────
    def _call_ai_with_retry(label, ai, prompt_text):
        """Call process_prompt with retry on transient errors.

        Distinguishes two classes of 429:
          - Rate limited (temporary): retry with backoff
          - Credits exhausted / spending limit: fail immediately, no retry
        """
        _MAX   = 3
        _WAIT  = 15
        _last  = None

        # Keywords that indicate a permanent billing/quota block — no retry
        PERMANENT_429 = (
            "credits", "spending limit", "billing", "quota", "exhausted",
            "payment", "upgrade", "plan", "subscribe",
        )
        # Keywords that indicate transient overload — worth retrying
        TRANSIENT = (
            "503", "UNAVAILABLE", "overloaded", "temporarily",
            "high demand", "try again",
        )

        for attempt in range(1, _MAX + 1):
            lbl = label if attempt == 1 else f"  Retry {attempt}/{_MAX} ({ai})"
            try:
                with Spinner(lbl, quiet=args.quiet):
                    result = process_prompt(ai, prompt_text, verbose=args.verbose, use_cache=args.cache)
                    # Unpack but discard the cached flag for now
                    if len(result) == 5:
                        # New format with cached flag
                        pass
                    return result
            except Exception as e:
                _last   = e
                err_str = str(e).lower()

                is_permanent = any(k in err_str for k in PERMANENT_429)
                is_transient = any(k in err_str for k in TRANSIENT) or (
                    "429" in str(e) and not is_permanent
                )

                if not args.quiet:
                    print(f"\n  {ai} error: {str(e)[:140]}")

                if is_permanent:
                    # No point retrying — credits are gone
                    print(f"\n  {ai}: API credits exhausted or spending limit reached.")
                    print(f"  Add credits at your {ai} dashboard, then retry.")
                    print(f"  Or rewrite with a different AI:  st-fix -a <ai> ...")
                    sys.exit(1)

                if is_transient and attempt < _MAX:
                    if not args.quiet:
                        print(f"  Waiting {_WAIT}s before retry…")
                    time.sleep(_WAIT)
                else:
                    break

        print(f"\nError: {ai} call failed after {_MAX} attempts.")
        print(f"  Last error: {_last}")
        print(f"  Try again later, or specify a different AI:  st-fix -a <ai> ...")
        sys.exit(1)

    # ── Iterate mode (default) ────────────────────────────────────────────────
    # For each non-true claim:
    #   1. Extract the sentence from the live report text
    #   2. Ask each AI in the writer pool to rewrite just that sentence
    #   3. After each rewrite, ask the checker AI to fact-check just that sentence
    #   4. Keep the first version whose verdict score beats the original
    #   5. If no AI improves it, leave the sentence unchanged (do no harm)
    # Final whole-doc fact-check is skipped — only the changed sentences were touched.

    WRITER_AI_ORDER = get_ai_list()   # try all 5 AI as writers, starting with --ai

    if args.mode == "iterate":
        # Checker AI: use --checker if given, else the same AI that did the fact-check
        checker_ai = args.checker or fact_obj.get("make") or args.ai

        # Writer AI pool: --ai first, then all others
        writer_pool = [args.ai] + [a for a in WRITER_AI_ORDER if a != args.ai]

        story_before = primary_text
        revised      = primary_text
        claim_results = []   # (claim_short, original_verdict, final_verdict, ai_used, changed)
        gen_payload = gen_response = fc_ai_model = ""   # ensure always bound

        w = 72
        print()
        print(f"  Iterate mode: {len(fact_checks)} claims  "
              f"checker={checker_ai}  writers={', '.join(writer_pool)}")
        print("─" * w)

        for claim_idx, fc in enumerate(fact_checks, 1):
            claim_short  = fc['claim'][:55] + ('…' if len(fc['claim']) > 55 else '')
            orig_verdict = fc['verification']
            orig_score   = _verdict_score(orig_verdict)

            # Classify fix action
            expl_lower = fc['explanation'].lower()
            no_evidence_phrases = [
                "no evidence", "no search results", "not found", "not mentioned",
                "cannot confirm", "no results mention", "no sources", "not verified",
                "unverified", "no data", "could not find", "no reference",
            ]
            correction_patterns = [
                r'\bnot\s+\w', r'\bshould be\b', r'\bactually\b',
                r'\bcorrect\w*\s+is\b', r'\bin fact\b', r'\bfounded in\b',
                r'\b\d{4}\b', r'https?://', r'\$[\d,]+',
            ]
            has_no_evidence = any(p in expl_lower for p in no_evidence_phrases)
            has_correction  = any(re.search(p, fc['explanation'], re.IGNORECASE)
                                  for p in correction_patterns)
            action = "HEDGE" if (has_no_evidence or not has_correction) else "REPLACE"

            # Use the original story text if stored, else fall back to claim label
            search_fragment = fc.get('text') or fc['claim']

            # Find the sentence in the current (live) report text
            sentence = _find_sentence_containing(
                revised, search_fragment, explanation=fc['explanation'])

            if not sentence:
                print(f"  {claim_idx:>2}/{len(fact_checks)}  [{orig_verdict[:5]:<5}]  "
                      f"SKIP (sentence not located)  {claim_short}")
                if args.verbose:
                    print(f"    searched for: '{search_fragment[:80]}'")
                claim_results.append((claim_short, orig_verdict, orig_verdict, None, False))
                continue

            # Get surrounding context for the fix prompt
            ctx_before, ctx_after = _get_sentence_context(revised, sentence)

            best_sentence   = sentence   # stays as-is unless we find an improvement
            best_verdict    = orig_verdict
            best_score      = orig_score
            best_ai         = None
            improved        = False

            for writer_ai in writer_pool:
                fix_prompt = get_single_fix_prompt(
                    sentence, fc['explanation'], action, ctx_before, ctx_after)

                try:
                    with Spinner(f"  {claim_idx:>2}/{len(fact_checks)}  "
                                 f"[{orig_verdict[:5]:<5}]  fix({writer_ai:<10})  "
                                 f"{claim_short}",
                                 quiet=args.quiet):
                        gen_payload, _, gen_response, fc_ai_model = process_prompt(
                            writer_ai, fix_prompt, verbose=args.verbose, use_cache=args.cache)
                    candidate = get_content(writer_ai, gen_response).strip()

                    # Strip surrounding quotes the AI sometimes adds
                    candidate = candidate.strip('"\'')

                    if not candidate or candidate == sentence:
                        continue   # no change — try next writer

                    # Inline fact-check: is the candidate better than the original?
                    topic_ctx = primary.get("title", "")
                    check_prompt = get_single_factcheck_prompt(
                        sentence, candidate, topic_context=topic_ctx)
                    with Spinner(f"  {claim_idx:>2}/{len(fact_checks)}  "
                                 f"[{orig_verdict[:5]:<5}]  check({checker_ai:<9})  "
                                 f"{claim_short}",
                                 quiet=args.quiet):
                        _, _, check_response, _ = process_prompt(
                            checker_ai, check_prompt, verbose=args.verbose, use_cache=args.cache)
                    check_text = get_content(checker_ai, check_response).strip()

                    # Parse verdict from checker response
                    new_verdict = _parse_inline_verdict(check_text)
                    new_score   = _verdict_score(new_verdict)

                    if args.verbose:
                        print(f"\n    candidate: {candidate[:100]}")
                        print(f"    verdict:   {new_verdict}  (was {orig_verdict})")

                    if new_score > best_score:
                        best_sentence = candidate
                        best_verdict  = new_verdict
                        best_score    = new_score
                        best_ai       = writer_ai
                        improved      = True

                    if best_score >= _verdict_score("True"):
                        break   # True — no need to try more AI

                except Exception as e:
                    if not args.quiet:
                        print(f"\n    {writer_ai} error: {str(e)[:100]}")
                    continue

            # Apply the best result to the live report
            if improved:
                revised = revised.replace(sentence, best_sentence, 1)
                icon = "✓"
            else:
                icon = "—"

            verdict_display = f"{orig_verdict[:5]:<5} → {best_verdict[:5]:<5}" if improved \
                else f"{orig_verdict[:5]:<5} (unchanged)"
            print(f"  {claim_idx:>2}/{len(fact_checks)}  [{verdict_display}]  "
                  f"{icon}  {claim_short}"
                  + (f"  [{best_ai}]" if improved else ""))
            claim_results.append((claim_short, orig_verdict, best_verdict, best_ai, improved))

        print("─" * w)
        n_improved = sum(1 for r in claim_results if r[4])
        n_unchanged = len(claim_results) - n_improved
        print(f"  Resolved: {n_improved}/{len(fact_checks)}  "
              f"Unchanged: {n_unchanged}/{len(fact_checks)}")
        print()

        if args.verbose:
            print_diff(story_before, revised)

        # Save + before/after comparison using the original fact-check as baseline.
        # No whole-document re-fact-check — only the changed sentences were touched.
        # The before_fact is reused as the "after" baseline since individual sentences
        # were already verified inline. A full re-fact-check can be run manually with st-fact.
        _save_result(container, file_json, args,
                     primary_make, primary_model, fc_ai_model,
                     revised, gen_payload, gen_response, primary,
                     before_fact=fact_obj, n_claims_before=n_false,
                     skip_after_factcheck=True)
        return

    # ── Patch mode ────────────────────────────────────────────────────────────
    PATCH_BATCH = 10   # claims per API call — keeps prompts focused and shows progress

    revised = primary_text          # fallback — overwritten by each mode below
    gen_payload = gen_response = fc_ai_model = ""

    if args.mode == "patch":
        story_before = primary_text
        batches      = [fact_checks[i:i + PATCH_BATCH]
                        for i in range(0, len(fact_checks), PATCH_BATCH)]
        n_batches    = len(batches)
        revised      = primary_text   # accumulates substitutions in place

        for b_idx, batch in enumerate(batches, 1):
            c_start = (b_idx - 1) * PATCH_BATCH + 1
            c_end   = c_start + len(batch) - 1
            label   = (f"  Patching claims {c_start}–{c_end} of {n_false}"
                       + (f"  (batch {b_idx}/{n_batches})" if n_batches > 1 else ""))
            prompt  = get_patch_prompt(revised, batch)
            gen_payload, client, gen_response, fc_ai_model = _call_ai_with_retry(
                label, args.ai, prompt)
            raw = get_content(args.ai, gen_response)

            # Parse the JSON substitution pairs the AI returned
            subs = _parse_substitutions(raw)

            if subs:
                revised, applied, failed = _apply_substitutions(revised, subs)
                if not args.quiet and failed:
                    print(f"  ⚠  {len(failed)} substitution(s) could not be located "
                          f"(sentence not found verbatim):")
                    for f_txt in failed:
                        print(f"       '{f_txt}...'")
                if args.verbose:
                    print(f"  Applied {applied}/{len(subs)} substitutions")
            else:
                # AI did not return parseable JSON — fall back to full-report return
                # but warn so we can investigate
                if not args.quiet:
                    print(f"  ⚠  Batch {b_idx}: AI did not return parseable substitutions. "
                          f"Skipping batch (report unchanged for these claims).")
                if args.verbose:
                    print(f"  Raw response (first 400 chars): {raw[:400]}")

        if args.verbose:
            print_diff(story_before, revised)

    # ── Best-source mode ──────────────────────────────────────────────────────
    elif args.mode == "best-source":
        alternates = []   # populated below when n_stories >= 2
        if n_stories < 2:
            print("Warning: best-source mode works best with multiple stories. "
                  "Falling back to patch mode.")
            prompt = get_patch_prompt(primary_text, fact_checks)
        else:
            alternates = []
            for s in stories:
                if s is primary:
                    continue
                avg = avg_score_for_story(s)
                alternates.append((
                    s.get("make"), s.get("model"), avg,
                    remove_markdown(s.get("markdown", ""))
                ))
            # Highest scoring first — the AI will see the best reference first
            alternates.sort(key=lambda x: x[2] if x[2] is not None else -99, reverse=True)

            if not args.quiet:
                print("  Reference stories (by avg fact-check score):")
                for make, model, score, _ in alternates:
                    score_str = f"{score:.2f}" if score is not None else " n/a"
                    print(f"    {make:12} {model:24} avg: {score_str}")

            prompt = get_best_source_prompt(primary_text, fact_checks, alternates)

        story_before = primary_text
        batches      = [fact_checks[i:i + PATCH_BATCH]
                        for i in range(0, len(fact_checks), PATCH_BATCH)]
        n_batches    = len(batches)
        revised      = primary_text

        for b_idx, batch in enumerate(batches, 1):
            c_start = (b_idx - 1) * PATCH_BATCH + 1
            c_end   = c_start + len(batch) - 1
            label   = (f"  Patching claims {c_start}–{c_end} of {n_false}"
                       + (f"  (batch {b_idx}/{n_batches})" if n_batches > 1 else ""))
            if n_stories < 2:
                prompt = get_patch_prompt(revised, batch)
            else:
                prompt = get_best_source_prompt(revised, batch, alternates)
            gen_payload, client, gen_response, fc_ai_model = _call_ai_with_retry(
                label, args.ai, prompt)
            raw  = get_content(args.ai, gen_response)
            subs = _parse_substitutions(raw)

            if subs:
                revised, applied, failed = _apply_substitutions(revised, subs)
                if not args.quiet and failed:
                    print(f"  ⚠  {len(failed)} substitution(s) not located verbatim:")
                    for f_txt in failed:
                        print(f"       '{f_txt}...'")
                if args.verbose:
                    print(f"  Applied {applied}/{len(subs)} substitutions")
            else:
                if not args.quiet:
                    print(f"  ⚠  Batch {b_idx}: no parseable substitutions returned. "
                          f"Report unchanged for these claims.")
                if args.verbose:
                    print(f"  Raw (first 400): {raw[:400]}")

        if args.verbose:
            print_diff(story_before, revised)

    _save_result(container, file_json, args,
                 primary_make, primary_model, fc_ai_model,
                 revised, gen_payload, gen_response, primary,
                 before_fact=fact_obj, n_claims_before=n_false)


if __name__ == "__main__":
    main()

