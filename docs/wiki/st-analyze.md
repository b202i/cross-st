# st-analyze — Analyze cross-product data and synthesize a new story

Generates a narrative summary of the cross-product fact-check results — who scored highest, where AIs disagreed, and which claims were consistently disputed.

**Run after:** `st-cross`

---

## Examples

```bash
st-analyze subject.json                 # analyze and synthesize with default AI
st-analyze --ai gemini subject.json     # use a specific provider
st-analyze --no-cache subject.json      # bypass API cache
st-analyze --ai-caption subject.json    # AI caption of analysis results
st-analyze --ai-story subject.json      # full AI narrative from analysis
```

## Options

| Option | Description |
|--------|-------------|
| `file.json` | Path to the JSON container |
| `--ai {xai,…}` | AI provider to use (default: `gemini`) |
| `--cache` | Enable API cache (default: enabled) |
| `--no-cache` | Disable API cache |
| `--site {MMD,…}` | Discourse site to use (default: `MMD`) |
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

**Related:** [Three Stages](Three-Stages)  [st-cross](st-cross)  [st-heatmap](st-heatmap)  [st-verdict](st-verdict)

---

## For developers

Flattens `fact[]` entries via `mmd_data_analysis.get_flattened_fc_data()` and passes the structured data to an AI for a prose summary.
