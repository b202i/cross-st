# FAQ — Cross Frequently Asked Questions

## Cross-Stones

### How do I move my `~/cross-stones/` directory to a different location?

Move the directory, then add `CROSS_STONES_DIR` to `~/.crossenv`:

```bash
mv ~/cross-stones ~/research/my-benchmarks
```

Then open `~/.crossenv` in any editor and add:

```
CROSS_STONES_DIR=~/research/my-benchmarks
```

After that, `st-stones` with no arguments will find the new location automatically.
Run `st-admin --show` to confirm the active path is correct.

### Where does Cross store user data?

| Path | Contents |
|------|----------|
| `~/.crossenv` | API keys, `DEFAULT_AI`, `CROSS_STONES_DIR`, and other preferences |
| `~/.cross_api_cache/` | MD5-keyed AI response cache (safe to delete at any time) |
| `~/.cross_templates/` | Prompt templates used by `st-new` |
| `~/cross-stones/` | Benchmark domain `.prompt` files (default; override with `CROSS_STONES_DIR`) |

---

## API Keys & Providers

### Which AI provider is free?

**Google Gemini** is the only provider with a genuinely free API tier — no credit card
required, just a Google account.  Get a key at <https://aistudio.google.com/app/apikey>.

Run `st-admin --setup` to enter your keys and set a default provider.

### How do I change the default AI provider?

```bash
st-admin --set-default-ai gemini   # or xai, anthropic, openai, perplexity
```

Or set `DEFAULT_AI=gemini` in `~/.crossenv` directly.

---

## Cache

### How do I clear the API response cache?

The cache at `~/.cross_api_cache/` is safe to delete at any time — tools simply
re-call the API on the next run.

```bash
rm -rf ~/.cross_api_cache/
```

`st-admin --cache-clear` will be added in a future release (task B4).

### How do I disable caching globally?

Add `CROSS_NO_CACHE=1` to `~/.crossenv` (task B3 — not yet implemented).
Until then, pass `--no-cache` to individual commands:

```bash
st-gen --no-cache my_topic.json
st-fact --no-cache my_topic.json
```

---

← [Wiki Home](https://github.com/b202i/cross-st/wiki)

