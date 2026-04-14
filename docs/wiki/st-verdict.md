# st-verdict — Which AI wrote the most accurate stories, and why

Generates a stacked bar chart showing the true / partially-true / false verdict breakdown for each AI author across the cross-product fact-check.

**Run after:** `st-cross`

---

## Examples

```bash
st-verdict subject.json                            # display chart + short caption (default)
st-verdict --no-ai-short subject.json              # display chart only, no caption
st-verdict --file subject.json                     # save PNG to ./tmp/ + short caption
st-verdict --no-display --file subject.json        # save PNG only, no screen display
st-verdict --ai-caption subject.json               # detailed caption instead of short
st-verdict --ai-summary subject.json               # technical summary
st-verdict --ai-story subject.json                 # full narrative
st-verdict --ai-title --ai gemini subject.json     # title via Gemini
st-verdict --no-cache subject.json                 # bypass API cache
```

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

**Related:** [st-cross](st-cross)  [st-heatmap](st-heatmap)  [st-analyze](st-analyze)

---

## For developers

Built on `mmd_plot.py`. Data comes from `mmd_data_analysis.get_flattened_fc_data()`.
