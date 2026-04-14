# st-plot — Plot cross-product fact-check scores

Generates charts from cross-product data: score distributions, AI comparisons, and timing breakdowns. Displays in the browser or saves to files.

**Run after:** `st-cross`

---

## Examples

```bash
st-plot --plot all --display subject.json              # show all plots on screen
st-plot --plot evaluator_v_target --display s.json     # single plot on screen
st-plot --plot all --file subject.json                 # save all plots to ./tmp/
st-plot --plot bar_score_target --file --path out/ s.json  # save to custom dir
st-plot --csv subject.json                             # export data as CSV
st-plot --json subject.json                            # save data as JSON
st-plot --markdown subject.json                        # save data as Markdown
st-plot --ai-caption subject.json                      # AI caption of score patterns
st-plot --ai-title --ai gemini subject.json            # AI title using Gemini
st-plot --ai-short subject.json                        # short AI summary
st-plot --ai-summary subject.json                      # concise AI summary
st-plot --ai-story subject.json                        # full AI narrative
st-plot --no-cache subject.json                        # bypass cache for AI content
```

## Options

| Option | Description |
|--------|-------------|
| `file.json` | Path to the JSON container |
| `--plot TYPE` | Chart type: `all`, `counts_v_score`, `evaluator_v_target`, `bar_score_evaluator`, `bar_score_target`, `outlier_detection`, `pivot_table` (default: `all`) |
| `--file` | Save plots to files (default: no) |
| `--path PATH` | Output directory for saved files (default: `./tmp/`) |
| `--display` | Display plots on screen (default: no) |
| `--file_kv` | Print JSON map of `plot:url` pairs for saved files |
| `--json` | Save data as a JSON file |
| `--csv` | Save data as a CSV file |
| `--markdown` | Save data as a Markdown file |
| `--cache` | Enable API cache for AI content generation (default) |
| `--no-cache` | Bypass API cache for AI content generation |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Minimal output |

### AI content generation

| Option | Description |
|--------|-------------|
| `--ai AI` | AI provider for content generation (default: `DEFAULT_AI`) |
| `--ai-title` | Generate a ≤10-word title → stdout |
| `--ai-short` | Generate a ≤80-word summary → stdout |
| `--ai-caption` | Generate a 100–160-word caption → stdout |
| `--ai-summary` | Generate a 120–200-word summary → stdout |
| `--ai-story` | Generate an 800–1200-word narrative → stdout |

**Related:** [st-cross](st-cross)  [st-heatmap](st-heatmap)  [st-verdict](st-verdict)  [st-speed](st-speed)

---

## For developers

Chart rendering lives in `mmd_plot.py`. Use `--plot all` to generate every chart type, `--file` to save instead of display, and `--path` to set the output directory.
