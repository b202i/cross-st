# FAQ — Cross Frequently Asked Questions

---

## Setup & configuration

### How do I run first-time setup?

```bash
pipx install cross-st        # or: pip install cross-st
st-admin --setup             # interactive wizard
```

`--setup` walks you through:
- Checking Python version and Homebrew (macOS)
- Entering API keys for each provider you want to use
- Setting your default AI provider (`DEFAULT_AI`)
- Setting your editor and TTS voice (optional)
- Optionally joining the [crossai.dev](https://crossai.dev) community

All settings are written to `~/.crossenv`.  Run `st-admin --show` at any time
to see the current configuration.

### I skipped the Discourse step during --setup. How do I add it later?

```bash
st-admin --discourse-setup
```

This runs the full Discourse onboarding independently: accepts the Terms of Service,
opens the crossai.dev signup page, provisions your account, and writes the required
keys to `~/.crossenv`.  You do not need to re-run `--setup`.

### How do I change which Discourse category st-post uses by default?

```bash
st-admin --discourse
```

This opens an interactive manager showing your current site, username, and default
posting category.  You can switch between:

1. Your private category (created during onboarding — visible only to you)
2. **Test (cleared daily)** — a public sandbox on crossai.dev; all posts are
   automatically deleted at 00:05 UTC every night.  Safe for testing `st-post`.
3. Any other category ID (enter manually)

The change takes effect immediately for the next `st-post` call.

> **First-run note:** If `--discourse-setup` completed but `st-post` still fails,
> run `st-admin --discourse` once.  It will automatically migrate the flat
> `DISCOURSE_*` keys to the `DISCOURSE` JSON format that `st-post` needs.

### How do I change my default AI provider?

Quick one-liner:

```bash
st-admin --set-default-ai gemini      # or: xai  anthropic  openai  perplexity
```

Or run the full interactive menu:

```bash
st-admin
```

and choose **Default AI**.  The setting is written as `DEFAULT_AI=gemini` in
`~/.crossenv`.  You can also edit `~/.crossenv` directly in any text editor.

**Available providers:**

| Provider | Key variable | Free tier? |
|----------|-------------|------------|
| `gemini` | `GEMINI_API_KEY` | ✅ Yes — [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| `xai` | `XAI_API_KEY` | Free credits on signup |
| `anthropic` | `ANTHROPIC_API_KEY` | Paid only |
| `openai` | `OPENAI_API_KEY` | Paid only |
| `perplexity` | `PERPLEXITY_API_KEY` | Paid only |

---

## Cache

### What is the cache and why do I want it?

Every time Cross calls an AI, the response is saved to `~/.cross_api_cache/` using
an MD5 key derived from the exact prompt and model.  On the next run with the same
prompt and model, Cross returns the saved response instantly — no API call, no cost,
no wait.

**Why this matters:**

- `st-cross` runs up to 25 AI calls for a single topic (5 providers × 5 fact-checks).
  Without the cache, re-running any step re-bills every one of those calls.
- Iterating on `st-fix` or `st-prep` options is free once the story is cached.
- The cache is transparent — you never need to manage it to get the benefit.

**To bypass the cache** (force a fresh API call):

```bash
st-gen --no-cache my_topic.json
st-fact --no-cache my_topic.json
```

**To disable caching globally**, add to `~/.crossenv`:

```
CROSS_NO_CACHE=1
```

### How do I see how much space the cache is using?

```bash
st-admin --cache-info
```

Prints the cache path, number of files, and total size.

### How do I clear the cache?

```bash
st-admin --cache-clear          # delete all cached responses
st-admin --cache-cull 30        # delete entries older than 30 days
```

The cache at `~/.cross_api_cache/` is **safe to delete at any time** — Cross will
simply re-call the API on the next run.  Your story files (`.json` containers) are
not affected.

---

## Upgrades

### Is st-upgrade safe? Will I lose my data?

**Short answer: yes, completely safe.**

`st-admin --upgrade` upgrades the Cross software only.  It does not touch any of
your data or configuration:

| Location | Contains | Touched by --upgrade? |
|----------|----------|----------------------|
| `~/.crossenv` | API keys, DEFAULT_AI, preferences | ❌ Never |
| `~/.cross_api_cache/` | Cached AI responses | ❌ Never |
| `~/.cross_templates/` | Prompt templates | ❌ Never |
| `~/cross-stones/` | Benchmark domain prompts | ❌ Never |
| Your `.json` story files | Stories, fact-checks | ❌ Never |

The upgrade only replaces the Python package (`cross-st` and `cross-ai-core`).
After upgrading, all your API keys, stories, benchmarks, and cached responses are
exactly where you left them.

**What --upgrade does:**

- Detects whether you installed with `pipx` or `pip` and uses the right command
- Skips the PyPI step if you're on an editable (developer) install
- On macOS, also runs `brew upgrade` for tracked Homebrew tools (e.g. `piper-tts`)
- Prints the version before and after so you can confirm the upgrade succeeded

**If anything looks wrong after an upgrade**, your config is in `~/.crossenv` and
is always readable/editable in a plain text editor.

---

## Data & file locations

### Where does Cross store user data?

| Path | Contents |
|------|----------|
| `~/.crossenv` | API keys, `DEFAULT_AI`, `CROSS_STONES_DIR`, and other preferences |
| `~/.cross_api_cache/` | MD5-keyed AI response cache (safe to delete at any time) |
| `~/.cross_templates/` | Prompt templates used by `st-new` |
| `~/cross-stones/` | Benchmark domain `.prompt` files (default; override with `CROSS_STONES_DIR`) |

### How do I move my ~/cross-stones/ directory?

Move the directory, then set `CROSS_STONES_DIR` in `~/.crossenv`:

```bash
mv ~/cross-stones ~/research/my-benchmarks
```

Open `~/.crossenv` in any editor and add:

```
CROSS_STONES_DIR=~/research/my-benchmarks
```

`st-stones` will find the new location automatically.  Run `st-admin --show` to
confirm the active path is correct.

---

## Providers & API keys

### Which AI provider is free?

**Google Gemini** is the only provider with a genuinely free API tier — no credit
card required, just a Google account.  Get a key at
<https://aistudio.google.com/app/apikey>.

Run `st-admin --setup` to enter your keys and set a default provider.

---

## Uninstalling

### How do I completely uninstall Cross?

**Step 1 — Remove the package**

```bash
pipx uninstall cross-st        # if installed with pipx (recommended)
pip uninstall cross-st         # if installed with pip
```

**Step 2 — Remove user data**

Cross stores data in four locations under your home directory.  Remove whichever
you want to clean up:

```bash
rm -f  ~/.crossenv                 # API keys, DEFAULT_AI, all preferences
rm -rf ~/.cross_api_cache/         # cached AI responses (safe to delete any time)
rm -rf ~/.cross_templates/         # prompt templates seeded by st-admin
rm -rf ~/cross-stones/             # benchmark domain prompts (if you ran st-stones)
```

If you moved your benchmark directory with `CROSS_STONES_DIR`, remove that path
instead of `~/cross-stones/`.

One-liner to remove everything at once:

```bash
rm -f ~/.crossenv && rm -rf ~/.cross_api_cache/ ~/.cross_templates/ ~/cross-stones/
```

> **Your `.json` story files are not touched** — they live wherever you created
> them (your working directory) and are never stored in the home-directory paths
> above.  Keep or delete them as you choose.

---

← [Wiki Home](Home)
