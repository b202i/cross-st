# st-fix: Implementation Details

> Deep-dive for contributors and developers.
> For the user-facing guide — workflow, modes, options, and examples — see **[st-fix](st-fix.md)**.

---

## Data structure

Each story's fact-check results are stored in `story["fact"][]`. Each entry contains:

```json
{
  "make":    "xai",
  "model":   "grok-3",
  "score":   1.52,
  "counts":  [16, 4, 2, 1, 1],
  "summary": "| True | Partially_true | Opinion | Partially_false | False |",
  "report":  "...free-text fact-check report...",
  "claims":  [
    {
      "seg_id":      7,
      "verdict":     "False",
      "explanation": "The S40 Gen 3 weighed 21 lbs, not 19."
    }
  ]
}
```

`claims[]` contains per-segment structured verdicts. `seg_id` is a stable 0-based index into `story["segments"]`, which lists every fact-checkable sentence in the story. `st-fix` filters `claims[]` for `verdict == "False"` or `"Partially_false"` to build its work list.

---

## Segment design

`story["segments"]` is populated by `mmd_util.build_segments()` the first time a story is fact-checked. Each entry is:

```json
{ "id": 0, "text": "The sky is blue.", "para": 2 }
```

Segment IDs are stable forever — segment 7 is the same sentence for every AI checker that works on this story. This allows direct verdict comparison across checkers without re-parsing free text. Tools that encounter an older container without `"segments"` generate them on-the-fly from the story text.

---

## Mode: iterate (default)

For each non-True claim:

1. Locate the exact sentence in the live story text (string match against `seg.text`).
2. Ask every available AI writer to rewrite just that sentence.
3. After each rewrite, ask the checker AI (default: original fact-checker from `-f`) to fact-check only the candidate sentence vs the original.
4. Parse the inline verdict and score it (`True` = 2, `Partially_true` = 1.5, `Opinion` = 1, `Partially_false` = 0.5, `False` = 0).
5. Keep the first candidate whose score beats the original. Stop trying new writers once we reach a True verdict.
6. If no writer improves the sentence, leave it unchanged ("do no harm" rule).
7. Skip the final whole-document fact-check pass — only changed sentences were touched.

The writer pool defaults to all configured AI providers. `--agent` overrides the pool to a single provider. `--checker` overrides the inline verifier.

---

## Mode: patch

Bundles all False/Partially_false claims into one prompt (up to 10 per batch). The AI returns a JSON array of `[original_sentence, replacement_sentence]` pairs. `st-fix` applies the substitutions via string replacement and shows a diff when `--verbose` is set.

If the AI returns un-parseable JSON for a batch, that batch is skipped with a warning and the story text is left unchanged for those claims.

---

## Mode: best-source

Same batching logic as patch, but the prompt also includes the text of every other story in the container, ranked by average fact-check score. The rewriter AI can reference how a higher-scoring AI handled the same topic. Falls back to patch-style prompts when the container has only one story.

---

## Mode: synthesize

Passes all stories and their average fact-check scores to a single rewriter AI with the instruction to produce the best possible story by drawing on whichever AI got each section most accurate. Uses `get_synthesize_prompt()` which includes the scored story list and an optional per-segment scorecard (available after `st-cross`).

The rewriter AI defaults to the author of the highest-scoring story; `--agent` overrides. A fallback AI is tried on transient 503/429 errors before full retry.

---

## Retry logic

All modes use a shared `_call_ai_with_retry()` helper (patch/best-source) or an inline retry loop (synthesize). Both distinguish:

- **Transient errors** (503, overloaded, rate-limited): retry up to 3 times with a 15-second wait.
- **Permanent billing errors** (credits exhausted, spending limit): exit immediately with an actionable message — no point retrying.

---

## Future: claim-level assembly (v3)

The current modes operate at story level. A planned v3 would work at individual claim level across the full N×N cross-product matrix:

1. For each False/Partially_false claim in the target story, find the passage in every other story that covers the same real-world fact (via embedding similarity or a prompt-based match).
2. Look up how many checkers rated each AI's version True.
3. Select the passage with the highest True count as the "best-supported" version.
4. Assemble the best-supported passages into a new story, with one final AI coherence pass.

This requires structured `claims[]` on every fact entry (already implemented), cross-story claim alignment (not yet built), and aggregation of verdicts per claim across the full matrix. Token budget: approximately 10 000 tokens for 5 stories × 1 500 words, plus an extra alignment pass of roughly 2 000 tokens.

See the design notes in the `st-fix.py` module docstring for full detail.

