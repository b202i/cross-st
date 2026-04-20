# st-verdict — Score AI accuracy and explain the results

Reads fact-check data from a container and produces two outputs: a **stacked bar chart** comparing each AI's accuracy (true · ~true · opinion · ~false · false breakdown per author), and an optional **written analysis** — a short caption on by default, or a longer caption, summary, or story via the `--ai-*` flags. Run after `st-fact` for a single-AI verdict, or after `st-cross` to compare all providers head-to-head.

**Run after:** `st-fact` · `st-cross`

![st-verdict workflow](st-verdict-flow.svg)

## Example output

![st-verdict bar chart](st-verdict-bar-chart.png)

**`st-verdict --ai-caption projector_sonos_options.json`** — example caption (Gemini):

> This chart presents a cross-AI fact-check on stories detailing RV and portable entertainment systems. XAI's Grok-4-1-fast-reasoning emerged as the most accurate AI author, with approximately 82% of its claims verified as True or ~True — significantly outperforming Anthropic's Claude-opus-4-5 at ~66%. Grok's superior performance stems from a high proportion of unequivocally True claims (54%) and a remarkably low False or ~False rate of just 3%, while Claude exhibited a combined inaccuracy rate of 15%.

---

## Options

| Option | Description |
|--------|-------------|
| `file.json` | Path to the JSON container |
| `--cache` | Enable API cache (default: enabled) |
| `--no-cache` | Disable API cache |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Minimal output |

### Chart output

| Option | Description |
|--------|-------------|
| `--display` | Display chart on screen (default: on) |
| `--no-display` | Suppress on-screen display |
| `--file` | Save chart PNG to file (default: off) |
| `--path PATH` | Output directory for PNG (default: `./tmp/`) |

### AI content generation

| Option | Description |
|--------|-------------|
| `--ai-title` | Generate a ≤10-word title → stdout |
| `--ai-short` | Generate a ≤80-word short caption → stdout (**default: on** when no other `--ai-*` flag is given) |
| `--no-ai-short` | Suppress the automatic short caption |
| `--ai-caption` | Generate a 100–160-word detailed caption → stdout |
| `--ai-summary` | Generate a 120–200-word summary → stdout |
| `--ai-story` | Generate an 800–1200-word narrative → stdout |
| `--ai AI` | AI provider for content generation (default: `xai`) |

### What-is lens — focused claim breakdown

Switches the AI from "summarise the chart" to "summarise the **claims** that fall on one side of the truth ledger". Aggregates per-claim verdicts and explanations across **all** fact-checkers in the container, then asks one AI to synthesize them into a focused report. Pair with any `--ai-*` flag to control level of detail; `--ai-summary` is auto-enabled if no detail flag is given.

| Option | Description |
|--------|-------------|
| `--what-is-false` | Aggregate every claim marked `false` / `partially_false` and produce a focused breakdown of what is inaccurate or disputed |
| `--what-is-true` | Aggregate every claim marked `true` / `partially_true` and produce a focused breakdown of what is verified or supported |
| `-s N`, `--story N` | Story index to analyse with the lens (default: `1`) |

```bash
# Detailed breakdown of inaccurate claims (e.g. "is this fake news?")
st-verdict --what-is-false --ai-summary subject.json

# Positive-evidence summary — what the report got right
st-verdict --what-is-true --ai-caption subject.json

# Long-form analysis suitable for sharing as feedback
st-verdict --what-is-false --ai-story --no-display subject.json
```

The lens reads `story[N].fact[]` entries — run `st-cross` first so multiple AIs have fact-checked the report. The more checkers that flagged the same claim, the stronger the signal in the resulting analysis.

**Related:** [st-cross](st-cross)  [st-heatmap](st-heatmap)  [st-analyze](st-analyze)

---

## For developers

Built on `mmd_plot.py`. Data comes from `mmd_data_analysis.get_flattened_fc_data()`.
