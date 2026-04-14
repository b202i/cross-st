# st-stones — Run and score the Cross-Stones benchmark

Scores AI providers on the Cross-Stones benchmark: a fixed set of domain prompts, each requiring exactly 10 fact-checkable claims. Produces a composite accuracy + speed leaderboard.

**Run after:** `st-cross`

**Related:** [st-domain](st-domain)  [st-speed](st-speed)  [Cross-Stones](cross-stones)

---

## Examples

```bash
st-stones                                              # auto-detect ~/cross-stones/ or ./cross_stones/
st-stones cross_st/cross_stones/cross-stones-10.json   # named benchmark set (locked params)
st-stones cross_st/cross_stones/                       # score all domains in a directory
st-stones --run cross_st/cross_stones/cross-stones-10.json    # run missing domains then score
st-stones --no-confirmation --run cross_stones/cross-stones-10.json  # scripted / CI use
st-stones --no-speed cross_stones/cross-stones-10.json # accuracy-only scoring
st-stones --domain cross_stones/cross-stones-10.json   # per-domain score breakdown
st-stones --init                                       # seed ~/cross-stones/ with bundled prompts
st-stones --init --dir my_domains/                     # seed to a custom directory
st-stones --set-baseline cross_stones/cross-stones-10.json     # lock current timing as baseline
st-stones --record-snapshot cross_stones/cross-stones-10.json  # save today's scores as snapshot
st-stones --history cross_stones/cross-stones-10.json          # show year-over-year history
st-stones --ai-caption cross_stones/cross-stones-10.json       # AI caption of leaderboard
```

## Options

| Option | Description |
|--------|-------------|
| `path` | Directory of benchmark `.json`/`.prompt` pairs, explicit `.json` paths, or a named benchmark set config. Omit to auto-detect `~/cross-stones/` or `./cross_stones/`. |
| `--init` | Seed the benchmark domain directory with bundled `.prompt` files, then exit |
| `--dir PATH` | Destination for `--init` (default: `~/cross-stones/`) |
| `--run` | Run `st-cross` for any domain that lacks fact-check data |
| `--confirmation` | Prompt before making API calls with `--run` (default) |
| `--no-confirmation` | Skip the `--run` confirmation prompt (useful for scripting) |
| `--w1 W1` | Accuracy weight 0–1 (default: 0.7) |
| `--w2 W2` | Speed weight 0–1 (default: 0.3) |
| `--no-speed` | Ignore timing data; pure accuracy scoring (sets w1=1.0, w2=0.0) |
| `--n-claims N` | Expected scorable claims per domain (default: from benchmark set config, or 10) |
| `--domain` | Show per-domain fact-score breakdown table |
| `--cache` | Enable API cache for `--run` (default: enabled) |
| `--no-cache` | Disable API cache for `--run` |
| `--timeout TIMEOUT` | Per-job timeout in seconds for `--run` (default: 300 = 5 min) |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Minimal output |

### Historical tracking

| Option | Description |
|--------|-------------|
| `--history` | Display full snapshot history (composite score, speed ratio, accuracy over time) |
| `--set-baseline` | Lock the current run's timing as the speed baseline in the benchmark set config |
| `--record-snapshot` | Append current leaderboard scores as a named snapshot |
| `--snapshot-label LABEL` | Human-readable label for `--record-snapshot` (default: today's ISO date) |

### AI content generation

| Option | Description |
|--------|-------------|
| `--ai-title` | Generate a ≤10-word leaderboard title → stdout |
| `--ai-short` | Generate a 40–80-word leaderboard summary → stdout |
| `--ai-caption` | Generate a 100–160-word two-paragraph caption → stdout |
| `--ai-summary` | Generate a 120–200-word summary → stdout |
| `--ai-story` | Generate an 800–1200-word narrative → stdout |
| `--ai NAME` | AI provider for content generation (default: `xai`) |

---

## For developers

Score formula: `w1 × (fact_score / max_fact_score) + w2 × (speed_score / max_speed_score)` with defaults `w1=0.7`, `w2=0.3`. The locked benchmark set is `cross_stones/cross-stones-10.json`. Pass `--no-speed` for accuracy-only scoring. `--set-baseline` must be run once after the first complete benchmark; subsequent faster runs will have `speed_ratio > 1.0` and `cross_stone_score` may exceed 1.0, indicating genuine improvement.
