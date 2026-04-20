# st-cross — Run all AI providers and cross-check results

Runs the full research pipeline in one command: generates a report from every AI provider, then has every AI fact-check every report. The result is an N×N score matrix saved into the container.

![st-cross pipeline — tool associations](st-cross-pipeline.svg)

`st-cross` is the orchestrator: it calls **[st-gen](st-gen)** to generate every report, then calls **[st-fact](st-fact)** to run every fact-check. The scores land in the Result column, ready for **[st-verdict](st-verdict)** to summarise.


**Run after:** `st-new`    **Run before:** `st-merge`  `st-heatmap`  `st-verdict`  `st-analyze`

**Related:** [st-bang](st-bang)  [st-fact](st-fact)  [st-heatmap](st-heatmap)  [st-verdict](st-verdict)

---

## Examples

```bash
st-cross subject.json                   # full N×N run: generate + fact-check all AIs
st-cross --no-cache subject.json        # bypass cache (no read, no write); does NOT force a re-run on a complete container
st-cross --force subject.json           # clear all existing fact[] entries and re-run every cell — use after a prompt change
st-cross --skip-gen subject.json        # skip generation — only run fact-checking
st-cross --timeout 3600 subject.json    # set a 60-minute per-cell timeout
st-cross --sequential subject.json      # run cells one at a time (debug / low-quota)
st-cross --max-concurrency 1 subject.json   # cap every provider to 1 in-flight cell
st-cross --dry-run subject.json         # preview the Step 2 matrix and exit
st-cross -q subject.json                # minimal output (suppress live table)
```

## Options

| Option | Description |
|--------|-------------|
| `file.json` | Path to the JSON container |
| `--cache` | Enable API cache (default: enabled) |
| `--no-cache` | Disable API cache (no read, no write). Does **not** by itself force a re-fact-check on an already-complete container — see `--force`. |
| `--force` | Bypass resume detection AND clear all existing `fact[]` entries before launching, then re-run every cell. Implies `--no-cache`. Use after changing the fact-check prompt or when you want fresh verdicts. |
| `--skip-gen` | Skip Step 1 (story generation). Auto-detected if all stories already exist. |
| `--dry-run` | Preview the Step 2 matrix (pending vs complete cells) and exit without running anything. Implies `--skip-gen`. |
| `--timeout SECONDS` | Per-cell wall-clock timeout (default: 1800 = 30 min). `0` = no timeout. |
| `-p`, `--parallel` | Run cells in parallel, gated by per-provider rate-limit semaphores (default). |
| `--sequential` | Run cells one at a time. Useful for debugging or very low-quota accounts. |
| `--max-concurrency N` | Override per-provider concurrency cap (default: per-make from `cross_ai_core.get_rate_limit_concurrency()` — xai=3, anthropic=2, openai=3, perplexity=2, gemini=5). |
| `--retry-budget SECONDS` | Per-segment retry budget passed to `st-fact` (default: 45). `0` = unlimited. |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Suppress live table (minimal output) |

## `--timeout` vs `--retry-budget`

The two flags operate at **different scopes** and are independent — you almost always want both set.

- **`--timeout`** caps the wall-clock time of one **cell** — the whole `st-fact` subprocess for a single (story × fact-checker) pair. If the cell takes longer than this, `st-cross` kills it and marks it failed. A cell typically makes ~50 API calls (one per segment), so the timeout must be large enough to cover all of them plus any retries that happen along the way.
- **`--retry-budget`** caps the time a **single API call** inside a cell spends retrying transient errors (rate limits, 503s). It is enforced inside `cross-ai-core`'s `process_prompt()` — when the budget is exhausted, the next segment proceeds without further retries. Setting it low (the default `45` = one ~15+30 s backoff cycle) prevents one rate-limited segment from eating the whole cell's wall-clock budget.

**Rule of thumb:** leave `--timeout` generous (the 30 min default is usually fine) and tune `--retry-budget` down rather than up. `--retry-budget 0` (unlimited) is equivalent to pre-PAR-1 behaviour — a badly rate-limited cell can then spend its entire `--timeout` on one stuck segment. For low-quota accounts, prefer `--sequential` over raising `--retry-budget`.

---

## For developers

Step 1 runs `st-gen --bang` per AI in parallel processes, each writing to its own `_N.json` file so there are no shared-file races. After all jobs finish, st-cross merges them into the main container and runs `st-prep` sequentially to build the `story[]` array. Step 2 launches one daemon thread per cell (N×N total), each calling `st-fact` as a subprocess for crash isolation. A per-provider `threading.Semaphore` (sized by `cross_ai_core.get_rate_limit_concurrency()`) gates how many cells for a given fact-checker AI can be in flight at once — this is what prevents parallel runs from tripping provider rate limits. `--sequential` collapses every provider onto a single `Semaphore(1)`. The live ANSI display is updated every second; Ctrl+C cancels remaining cells while preserving the results collected so far.
