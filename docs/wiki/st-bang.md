# st-bang — Run all AI providers in parallel and merge results

Generates stories from all AI providers simultaneously, then merges them into one container. Much faster than running `st-gen` once per provider.

**Run after:** `st-new`    **Run before:** `st-cross`  `st-merge`

---

## Examples

```bash
st-bang subject.prompt                  # run all providers in parallel
st-bang --no-cache subject.prompt       # bypass API cache (fresh calls)
st-bang --force subject.prompt          # regenerate even if stories already exist
st-bang -m subject.prompt               # run all providers then merge into one story
st-bang -s subject.prompt               # run all providers then open the st app
st-bang --timeout 300 subject.prompt    # 5-minute per-job timeout
st-bang -q subject.prompt               # suppress live progress table
```

## Options

| Option | Description |
|--------|-------------|
| `prompt` | Path to the `.prompt` file |
| `--ai {xai,…}` | AI to use for the optional `--merge` step (default: `xai`) |
| `--cache` | Enable API cache (default: enabled) |
| `--no-cache` | Disable API cache |
| `-m`, `--merge` | Merge all stories into a master story via `st-merge` after generation |
| `-s`, `--st` | Open the final `.json` container in the `st` app after completion |
| `--force` | Regenerate all stories even if they already exist in the container |
| `--timeout TIMEOUT` | Per-job timeout in seconds (default: 600 = 10 min). `0` = no timeout. |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Suppress progress table (minimal output) |

**Related:** [st-gen](st-gen)  [st-merge](st-merge)  [st-cross](st-cross)

---

## For developers

Launches one `st-gen --bang N` subprocess per AI. Each writes to `tmp/<story>_N.json` and creates a `.block` file. `st-bang` polls every second until all block files are removed, then merges the tmp files into the main container.
