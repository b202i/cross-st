# st-fact — Fact-check stories in a container

Sends a single story to an AI and asks it to fact-check every claim, scoring each one true, partially true, or false. Appends the result to the container.

**Run after:** `st-prep`    **Run before:** `st-fix`  `st-heatmap`

![st-fact workflow](st-fact-flow.svg)

```bash
st-fact subject.json                    # fact-check story 1 with default AI
st-fact -s 2 --ai gemini subject.json  # fact-check story 2 with Gemini
st-fact --no-cache subject.json        # bypass API cache
st-fact --all subject.json             # fact-check all stories in the container
st-fact --ai all subject.json          # run all AIs in parallel (one per story)
st-fact --timeout 30 subject.json      # 30-second per-paragraph timeout
st-fact --file subject.json            # also write results to a file
st-fact --paragraph subject.json       # write paragraph segments to _paragraph_test_n.txt
st-fact --ai-review subject.json       # AI digest of existing fact-check results
st-fact --ai-title subject.json        # title (≤10 words) from existing fact data
st-fact --ai-short subject.json        # short caption (≤80 words) from existing fact data
st-fact --ai-caption subject.json      # detailed caption (100–160 words)
st-fact --ai-summary subject.json      # concise summary (120–200 words)
st-fact --ai-story subject.json        # comprehensive story (800–1200 words)
```

## Options

| Option | Description |
|--------|-------------|
| `-s N`, `--story N` | Fact-check a single story by number (default: 1) |
| `--all` | Fact-check every story in the container |
| `--ai AI` | AI provider to use, or `all` to run all providers in parallel (default: `xai`) |
| `--cache` | Enable the API response cache (default: enabled) |
| `--no-cache` | Bypass the API response cache |
| `--file` | Also write results to a `.txt` file alongside the container |
| `--paragraph` | Write paragraph segments to `_paragraph_test_N.txt` for debugging |
| `--display` | Write results to the display (default: on) |
| `--silent` | Suppress all output including progress bars; used internally by `st-cross` |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Minimal output |
| `--timeout N` | With `--ai all`: per-job limit in minutes (default: 20). Single-AI mode: per-paragraph limit in seconds (default: 0 = no limit) |

## AI content options

These flags read **existing** fact-check data and generate new AI content — they do not run a new fact-check.

| Option | Output | Length |
|--------|--------|--------|
| `--ai-review` | AI digest of fact-check results (implies `--ai-short` unless another flag is set) | — |
| `--ai-title` | Title → stdout | ≤ 10 words |
| `--ai-short` | Short caption → stdout | ≤ 80 words |
| `--no-ai-short` | Suppress the automatic short caption in review mode | — |
| `--ai-caption` | Detailed caption → stdout | 100–160 words |
| `--ai-summary` | Concise summary → stdout | 120–200 words |
| `--ai-story` | Comprehensive story → stdout | 800–1200 words |

## For developers

Splits the story into segments via `mmd_util.build_segments()`, sends them to the AI, and appends a `fact[]` entry to the container. The entry includes `score`, `counts`, `summary`, `claims[]` (per-segment verdicts), and `timing{}`.
