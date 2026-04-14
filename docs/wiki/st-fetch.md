# st-fetch — Import external content into a container

Imports external content into a container as a raw data entry — a tweet by ID, a web URL, or a local file. The imported content can then be processed with `st-prep` like any generated story.

**Run before:** `st-prep`

---

## Examples

```bash
st-fetch <tweet_id> file.json            # fetch X/Twitter post by tweet ID
st-fetch --file report.md file.json      # import a local .txt or .md file
st-fetch --url https://... file.json     # fetch a web page and extract its text
st-fetch --clipboard file.json           # import text from the system clipboard
st-fetch --file report.md file.json --no-prep   # store as raw data entry, skip st-prep
st-fetch <tweet_id> file.json --no-cache        # bypass cache, always fetch live
```

## Options

| Option | Description |
|--------|-------------|
| `tweet_id` | Tweet ID to fetch from X/Twitter (numeric ID from post URL) |
| `file.json` | Path to the `.json` container |
| `--file PATH` | Import a plain text or markdown file from disk |
| `--url URL` | Fetch a web page and extract its text |
| `--clipboard` | Import text from the system clipboard |
| `--cache` | Enable API cache (default: on) |
| `--no-cache` | Disable API cache — always fetch live |
| `--prep` | Run `st-prep` after fetching (default: on) |
| `--no-prep` | Skip `st-prep` — store as raw data entry only |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Minimal output |

**Related:** [st-prep](st-prep)  [st-gen](st-gen)

---

## For developers

`AI_MAKE` is set to `"url"` for fetched content; this handler is not in `AI_HANDLER_REGISTRY`. Twitter/X fetches require `X_COM_BEARER_TOKEN` in `.env`.
