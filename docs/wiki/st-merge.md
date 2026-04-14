# st-merge — Synthesize multiple AI stories into one

Combines multiple AI-generated stories into one cohesive report. When fact-check scores are available it uses the highest-scoring story as the base and pulls in verified facts from the others.

**Run after:** `st-bang`    **Run before:** `st-post`

**Related:** [st-bang](st-bang)  [st-fix](st-fix)  [st-post](st-post)

---

## Examples

```bash
st-merge subject.json                         # auto-mode: merge all stories
st-merge -a subject.json                      # explicitly merge all stories
st-merge --stories 1 3 subject.json           # merge only stories 1 and 3
st-merge --base 2 subject.json                # use story 2 as structural base
st-merge --simple subject.json                # force simple merge (ignore fact scores)
st-merge --quality subject.json               # force quality merge (fail if no scores)
st-merge --min-score 1.5 subject.json         # exclude stories below 1.5 avg score
st-merge --no-post-check subject.json         # skip post-merge fact-check
st-merge --ai gemini subject.json             # use Gemini as the synthesizer AI
st-merge --ai-caption subject.json            # add AI caption after merge
st-merge --no-cache subject.json              # bypass API cache
```

## Options

| Option | Description |
|--------|-------------|
| `file.json` | Path to the JSON container |
| `--ai {xai,…}` | Synthesizer AI for simple mode. In quality mode the base story's author AI is always used. (default: `xai`) |
| `--cache` | Enable API cache (default: enabled) |
| `--no-cache` | Disable API cache |
| `-a`, `--all` | Merge all stories |
| `--stories N [N …]` | Merge selected stories by index (default: all original stories, excluding fix/merge derived) |
| `--base N` | Story number to use as structural base (default: auto — highest score) |
| `--min-score SCORE` | Exclude stories with avg fact-check score below this threshold (e.g. `--min-score 1.2`) |
| `--simple` | Force simple merge — ignore fact-check data |
| `--quality` | Force quality merge — fail if no fact-check data exists |
| `--post-check` | Run `st-fact` on the merged story and show before/after score (default: on) |
| `--no-post-check` | Skip post-merge fact-check |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Minimal output |

### AI content generation

| Option | Description |
|--------|-------------|
| `--ai-title` | Generate a ≤10-word title → stdout |
| `--ai-short` | Generate a ≤80-word summary → stdout |
| `--ai-caption` | Generate a 100–160-word caption → stdout |
| `--ai-summary` | Generate a 120–200-word summary → stdout |
| `--ai-story` | Generate an 800–1200-word narrative → stdout |

---

## For developers

Two modes selected automatically: `simple` (no fact data — all stories passed to synthesizer AI) and `quality` (uses fact scores — highest-scoring story is the base; its author AI performs the rewrite for consistent voice). Override with `--simple` or `--quality`.
