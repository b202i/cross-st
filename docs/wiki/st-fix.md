# st-fix — Improve a story using fact-check feedback

Rewrites the weak parts of a story using its fact-check results. Only sentences
scored False or Partially False are touched — everything that checked out stays
exactly as the AI wrote it.

**Run after:** `st-fact`  ·  **Run before:** `st-post`

**Related:** [st-fact](st-fact.md) · [st-merge](st-merge.md) · [st-post](st-post.md)

---

## How it works

1. You run `st-fact` (or `st-cross`) and a fact-checker AI scores every sentence True, Partially True, Opinion, Partially False, or False.
2. You run `st-fix`. It finds all False / Partially False sentences and sends them to an AI for rewriting.
3. In the default **iterate** mode it checks each fix immediately: if the rewritten sentence scores better, it keeps the change; if not, it leaves the original alone. No change is ever made that makes things worse.
4. The fixed story is saved back to the container, ready for `st-post` or another round of `st-fact`.

---

## Quick start

```bash
# Simplest use — auto-selects the most fixable story + fact-check in the container
st-fix subject.json

# Specify story 1, fact-check 1 explicitly
st-fix -s 1 -f 1 subject.json

# Use a specific AI to rewrite
st-fix -s 1 -f 1 --ai openai subject.json

# After fixing, run st-prep automatically to refresh the title/hashtags
st-fix subject.json --prep
```

---

## Modes

| Mode | When to use it | What it does |
|------|---------------|--------------|
| `iterate` *(default)* | Most cases | Fixes one sentence at a time, checks each fix immediately. Tries every available AI per sentence before giving up — keeps only verified improvements. |
| `patch` | Quick pass; large batches | Bundles all false claims into a single prompt. Faster but no inline verification — the AI rewrites everything at once. |
| `best-source` | After `st-bang` / `st-cross` | Uses the other AI stories in the container as reference material. Good when a different AI got the same fact right. Requires at least 2 stories. |
| `synthesize` | After `st-cross` (full pipeline) | Passes all stories and their scores to one AI and asks for a single best-of-all rewrite. Highest quality but uses the most tokens. |

```bash
st-fix subject.json                            # iterate (default)
st-fix --mode patch subject.json               # one-pass patch
st-fix --mode best-source subject.json         # multi-story reference
st-fix --mode synthesize subject.json          # full synthesis
```

---

## Options

| Option | Description |
|--------|-------------|
| `-s N` / `--story N` | Story to fix (default: auto-select the story with the most false claims) |
| `-f N` / `--fact N` | Fact-check to use (default: auto-select; not used in synthesize mode) |
| `--mode <mode>` | Fix strategy: `iterate` (default), `patch`, `best-source`, `synthesize` |
| `-a` / `--ai <name>` | AI to use for rewriting (default: same AI that wrote the story) |
| `--checker <name>` | AI to use for inline verification in iterate mode (default: original fact-checker) |
| `--prep` | Run `st-prep` after fixing to refresh the title and hashtags |
 `--cache`  Enable API cache (default: enabled) 
 `--no-cache`  Bypass API cache 
 `-v` / `--verbose`  Show a diff of each change 
| `-q` / `--quiet` | Minimal output |

---

## What to expect

When you run `st-fix subject.json` without any flags, it:

- Scans every story+fact-check pair in the container and ranks them by number of fixable claims.
- Picks the combination with the most to fix and prints a summary before making any changes.
- Runs claim-by-claim in **iterate** mode: you see each sentence, which AI rewrote it, and whether the fix improved, kept, or skipped it.

If a story has no False or Partially False claims, `st-fix` exits cleanly and lists any other fact-checks in the container that do have things to fix.

---

## For developers

For implementation details — the data-structure design, how each mode works internally, the inline fact-check loop, and notes on the future claim-level assembly architecture — see **[st-fix: Implementation Details](st-fix-implementation.md)**.
