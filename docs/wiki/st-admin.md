# st-admin — Manage settings, API keys, and templates

Settings manager for Cross: API keys, default AI provider, Discourse connection,
prompt templates, TTS voice, and editor.

**Related:** [st-new](st-new.md) · [AI Providers](ai-providers.md) · [TTS Audio](tts-audio.md) · [FAQ](faq.md)

---

## Quick reference

```
st-admin                        # interactive menu
st-admin --setup                # first-time wizard
st-admin --show                 # print current config
st-admin --version              # print installed version
st-admin --get-default-ai       # print current default agent
st-admin --set-default-ai NAME  # switch default agent (e.g. gemini, anthropic-opus)
st-admin --list-aliases         # table of every agent → provider · model
st-admin --add-alias NAME=PROVIDER:MODEL    # e.g. anthropic-opus=anthropic:claude-opus-4-5
st-admin --add-alias NAME=PROVIDER          # uses provider's recommended model
st-admin --remove-alias NAME    # remove a custom agent
st-admin --set-tts-voice VOICE  # set TTS voice string (written to TTS_VOICE)
st-admin --set-template NAME    # set default prompt template name
st-admin --set-editor NAME      # set editor (written to EDITOR)
st-admin --init-templates       # seed ~/.cross_templates/ with bundled .prompt files
st-admin --overwrite-templates  # replace existing template files when seeding
st-admin --upgrade              # upgrade cross-st + platform tools
st-admin --cache-info           # cache path, file count, size
st-admin --cache-clear          # delete all cached AI responses
st-admin --cache-cull DAYS      # delete cache entries older than N days
st-admin --discourse            # view / change Discourse posting category
st-admin --discourse-setup      # one-time Discourse account provisioning
st-admin --check-tos            # check T&C version; prompt re-acceptance if stale
```

---

## Use cases

### First-time setup

```
install  ──▶  st-admin --setup  ──▶  ~/.crossenv written  ──▶  ready
```

```bash
pipx install cross-st
st-admin --setup
```

The wizard checks your environment, collects API keys for the providers you want,
sets `DEFAULT_AGENT`, configures your editor and optional TTS voice, and offers to join
the crossai.dev community.  Everything is saved to `~/.crossenv`.

Once setup is complete, run any command.  A good first test:

```bash
st-new my_first_topic        # create a prompt file
st-gen my_first_topic.json   # generate a story
st-ls  my_first_topic.json   # list what's in the container
```

---

### Adding Discourse after running --setup

If you skipped the community step during setup, run the onboarding independently:

```
st-admin --discourse-setup
  │
  ├─▶  accept Terms of Service
  ├─▶  open crossai.dev/signup in browser
  ├─▶  enter your Discourse username
  └─▶  provision account  ──▶  API key + private category written to ~/.crossenv
```

```bash
st-admin --discourse-setup
```

At the end, five keys are written to `~/.crossenv` and `st-post` is ready to use.

---

### Changing the default Discourse posting category

```
st-admin --discourse
  │
  ├─▶  shows current config (site, username, active category)
  │
  └─▶  Change category?
         1. alice-private  (your private category)
         2. Test (cleared daily)  — cleared nightly, safe for testing
         3. Enter a category ID manually
         q. keep current and exit
```

```bash
st-admin --discourse
```

Use **option 2** (Test category) when you want to verify that `st-post` works
end-to-end without putting posts in your private category.  Posts there are
deleted automatically at 00:05 UTC every night.

> **Tip:** If `st-post` fails immediately after `--discourse-setup`, run
> `st-admin --discourse` once.  It auto-migrates the flat `DISCOURSE_*` keys to
> the `DISCOURSE` JSON that `st-post` reads.

---

### Changing your default AI provider

```bash
st-admin --set-default-ai gemini     # fastest path
```

Or use the interactive menu:

```bash
st-admin           # choose "Default AI" from the menu
```

The change is written as `DEFAULT_AGENT=gemini` to `~/.crossenv` and takes effect
immediately.  You can also edit `~/.crossenv` directly.

Per-call overrides are always available with `--agent`:

```bash
st-gen --agent anthropic my_topic.json   # one-off, doesn't change your default
```

---

## AI providers, models and aliases — what each word means

Three terms come up everywhere in `st-admin`'s AI menu.  They are easy to mix
up because they overlap by default:

| Term | What it is | Example |
|------|-----------|---------|
| **Provider** | The AI company hosting the model. | `anthropic`, `openai`, `xai`, `gemini`, `perplexity` |
| **Model** | A specific LLM that provider sells. New ones ship every few months; older ones are eventually retired. | `claude-opus-4-5`, `gpt-4o`, `grok-4-1-fast-reasoning` |
| **Alias** | A short nickname **you** type in `--agent` or that `st` cycles through. Each alias is a fixed `(provider, model)` pair. | `anthropic`, `anthropic-opus`, `gemini-fast` |

**You always get one alias per provider for free** — its name is the provider's
name (e.g. `anthropic`) and it points at that provider's recommended model.
These are tagged **`default`** in the alias table.  You don't have to do
anything to use them — they appear the moment you have an API key set up.

You can **add custom aliases** when you want to pin a specific model, switch
providers without changing your scripts, or run two models from the same
provider side by side (e.g. `anthropic-opus` vs `anthropic-haiku`).  Custom
aliases are tagged **`custom`** in the table and live in
`~/.cross_ai_models.json` (one JSON file you can also edit by hand).

### Looking at what you have

```bash
st-admin             # then press 'a' (AI)  →  'M' (View aliases)
```

```
  Alias           Provider    Model                                          Type     Env override
  ──────────────  ──────────  ─────────────────────────────────────────────  ───────  ────────────
  xai             xai         grok-4-1-fast-reasoning  (provider default)    default  —
  anthropic       anthropic   claude-opus-4-5  (provider default)            default  —
  openai          openai      gpt-4o  (provider default)                     default  —
  anthropic-opus  anthropic   claude-opus-4-5                                custom   —
  gemini-fast     gemini      gemini-2.5-flash                               custom   —

  Legend:
    Provider  = the AI company (anthropic, openai, xai, gemini, perplexity)
    Model     = a specific LLM that provider hosts (e.g. claude-opus-4-5)
    Alias     = the short name you pass to --agent or that st cycles through;
                each alias is a (provider, model) pair.
    Type      = 'default' means an alias you got for free (one per provider,
                same name as the provider, uses the provider's recommended
                model);  'custom' means an alias you added yourself.

  File: /Users/you/.cross_ai_models.json
```

### Switching the default

```bash
st-admin             # then 'a' (AI)  →  'd' (View / set default)
```

```
  Current default AI: [openai]  →  openai · gpt-4o  (provider default)

  Available aliases (default = recommended model):
    xai             →  xai         grok-4-1-fast-reasoning  (provider default)
    anthropic       →  anthropic   claude-opus-4-5  (provider default)
    openai          →  openai      gpt-4o  (provider default) ←
    perplexity      →  perplexity  sonar-pro  (provider default)
    gemini          →  gemini      gemini-2.5-flash  (provider default)
    anthropic-opus  →  anthropic   claude-opus-4-5

  Type alias name to switch (blank = keep current):
```

The arrow ←  marks the current default.  Type any alias name to switch — the
choice is written to `DEFAULT_AGENT` in `~/.crossenv` and takes effect on the
next command.

### Adding a custom alias

The new-alias wizard does live model discovery against the provider's API,
so you always pick from the models your key can actually reach.

```bash
st-admin             # then 'a' (AI)  →  'm' (Manage aliases)  →  'a' (Add)
```

```
  Add a new AI alias.
  Alias name (e.g. anthropic-opus, blank to cancel): anthropic-haiku
    1. anthropic
    2. openai
    3. xai
    4. gemini
    5. perplexity
  Provider (number, or blank to cancel): 1

  Available models for anthropic:
     1. ★ claude-opus-4-5
     2. ★ claude-sonnet-4-5
     3. ★ claude-3-7-sonnet-latest
     4. ★ claude-3-5-haiku-latest
     5.   claude-3-5-sonnet-20241022
     ... 8 more ...
     0.   <use the provider's recommended default (model = null)>
    Or type any model id directly.
  Choice (blank to cancel): 4

  Confirm: alias 'anthropic-haiku' → anthropic · claude-3-5-haiku-latest
  Save? [Y/n]: y
  ✓  Written to /Users/you/.cross_ai_models.json
```

`★` marks the provider's recommended models (curated quarterly in
`cross-ai-core`).  You can also type any model id directly — useful for
preview or undocumented model names.

Equivalent non-interactive form:

```bash
st-admin --add-alias anthropic-haiku=anthropic:claude-3-5-haiku-latest
st-admin --add-alias anthropic-default=anthropic         # use provider default
st-admin --remove-alias anthropic-haiku
st-admin --list-aliases
```

### Refreshing the model list

Provider model lists are cached for 7 days at `~/.cross_models_cache/`.  When
a new flagship lands and you don't want to wait for the cache to expire:

```bash
st-admin             # then 'a' → 'm' → 'R' (Refresh)
```

This calls every provider's list-models endpoint and rewrites the cache:

```
  Refreshing model lists from each provider (this may take a few seconds)…
    ✓  xai          15 models (3 recommended)
    ✓  anthropic    13 models (4 recommended)
    ✓  openai       73 models (3 recommended)
    ✓  perplexity    3 models (3 recommended)
    ✓  gemini       38 models (4 recommended)

  Cache: /Users/you/.cross_models_cache/ (7-day TTL)
```

### Per-shell model overrides (advanced)

Two environment variables let you override what a given alias resolves to
without editing the JSON file or `~/.crossenv` — useful for one-off tests
in a single shell:

| Variable | Effect |
|----------|--------|
| `<ALIAS_UPPER>_MODEL` (e.g. `ANTHROPIC_OPUS_MODEL=claude-opus-future`) | Overrides this one alias only. |
| `<PROVIDER_UPPER>_MODEL` (e.g. `ANTHROPIC_MODEL=claude-3-5-haiku-latest`) | Overrides every alias that points at this provider unless the alias has its own var. |

When either is active, the View-aliases table shows the variable name in the
**Env override** column instead of `—`.

---

### Understanding the cache — what is it and why do I want it?

```
st-gen my_topic.json
  │
  ├─ cache miss ──▶  call AI API  ──▶  save to ~/.cross_api_cache/  ──▶  return result
  └─ cache hit  ──▶  return saved result  (instant, free)
```

Cross saves every AI response to `~/.cross_api_cache/` keyed on the exact prompt +
model.  A repeated call with the same inputs returns the saved response instantly —
no API call, no cost, no wait.

This matters most during iteration: re-running `st-fix`, adjusting `st-prep`
options, or re-checking scores all hit the cache and cost nothing.

```bash
st-admin --cache-info          # see how much space the cache uses
st-admin --cache-cull 30       # remove entries older than 30 days
st-admin --cache-clear         # wipe the whole cache (safe — data is in .json files)

st-gen --no-cache my_topic.json   # force a fresh call for one run
```

To disable caching globally: add `CROSS_NO_CACHE=1` to `~/.crossenv`.

---

### Is --upgrade safe? Will I lose my data?

**Yes — your data is never touched.**

```
st-admin --upgrade
  │
  ├─▶  upgrades cross-st package (pip or pipx)
  ├─▶  upgrades cross-ai-core
  ├─▶  on macOS: brew upgrade for platform tools
  └─▶  prints version before → after
```

What `--upgrade` never touches:

| Location | Contains |
|----------|----------|
| `~/.crossenv` | API keys, DEFAULT_AGENT, all preferences |
| `~/.cross_api_cache/` | Cached AI responses |
| `~/.cross_templates/` | Prompt templates |
| `~/cross-stones/` | Benchmark domain prompts |
| Your `.json` story files | Everything you've generated |

If you're on an editable (developer) install, the PyPI step is skipped and you're
told to `git pull` instead.

---

## Community onboarding

`st-admin --setup` will offer to join the [crossai.dev](https://crossai.dev) community at the end of the wizard. You can also run it independently at any time:

```bash
st-admin --discourse-setup
```

This walks you through:
1. Displaying and accepting the crossai.dev Terms of Service
2. Opening `crossai.dev/signup` (or printing the URL) to create your account
3. Collecting your Discourse username
4. Provisioning your account (generates a per-user API key and private category)

The following keys are written to `~/.crossenv` on success:

| Key | Description |
|-----|-------------|
| `DISCOURSE_URL` | `https://crossai.dev` |
| `DISCOURSE_USERNAME` | Your Discourse username |
| `DISCOURSE_API_KEY` | Your per-user API key (for `st-post`) |
| `DISCOURSE_CATEGORY_ID` | Your private category ID |
| `DISCOURSE_PRIVATE_CATEGORY_SLUG` | Your private category slug |

To use a different provisioning server (dev/test):
```bash
DISCOURSE_PROVISION_URL=http://localhost:5000/api/provision-user st-admin --discourse-setup
```

---

## Discourse site manager

After completing `--discourse-setup`, use `--discourse` at any time to view your current Discourse configuration and switch the default posting category used by [`st-post`](st-post.md):

```bash
st-admin --discourse
```

You can also change the default site and default posting category directly from the interactive `st-admin` menu — press `D` to select a site or `c` to select a category without running the full `--discourse` manager:

```bash
st-admin          # then press D or c
```

### Interactive display (`--discourse`)

```
  Discourse Site Management
  ────────────────────────────────────────
  Site                          https://crossai.dev
  Username                      alice
  Default posting category      alice-private  [id=42]
  Private category              alice-private  [id=42]

  Change default posting category?
    1.  alice-private  (your private category)
    2.  Test (cleared daily)  — cleared nightly, safe for testing
    3.  📄 Reports  (id=16)  — public portfolio at crossai.dev/u/alice/activity/topics
    ESC.  Keep current and exit

  Choice [esc]: _
```

Selecting an option immediately updates `category_id` inside the `DISCOURSE` JSON in `~/.crossenv`. The change takes effect for the next `st-post` call — no restart required.

### Quick-select from the interactive menu

From `st-admin` (no flags), two new keys are available:

 Key  Action 
-------------
 `D`  Select default Discourse site (when you have multiple sites configured) 
 `c`  Select default posting category: **private**, **Test (cleared daily)**, or **📄 Reports** 

```
=== st-admin Settings ===
  D: Select default Discourse site
  c: Select default Discourse posting category  (private | test-cleared-daily)
  ...
```

`D` writes the chosen slug to `DISCOURSE_SITE` in `~/.crossenv`.
`c` writes the chosen `category_id` into the active site's `DISCOURSE` JSON — same effect as using `--discourse`, but faster for day-to-day category switching.

### Test (cleared daily) category

Option 2 targets the shared **`Test (cleared daily)`** sandbox on `crossai.dev` (category id=6):

- **Public read** — anyone can view posts without logging in
- **Login required to post** — you must have a registered account
- **Cleared nightly** — all posts are automatically deleted at 00:05 UTC by a server cron job
- The category name includes `(cleared daily)` so the behaviour is self-documenting

Use this category when you want to verify that `st-post` is working end-to-end without cluttering your private category.

### First-run migration

If you completed `--discourse-setup` but `st-post` is still failing, run `--discourse` once. On first run, if the flat `DISCOURSE_*` keys exist in `~/.crossenv` but the `DISCOURSE` JSON array (required by `st-post`) is absent, it is built and written automatically:

```
  ✓  Discourse configuration initialised from onboarding keys.
```

This closes the gap between provisioning and posting without requiring you to re-run setup.

### Flag / key comparison

| Flag / Key | Purpose | When to use |
|-----------|---------|-------------|
| `--discourse-setup` | One-time account provisioning (T&C, API key, private category) | Once per user |
| `--discourse` | Show full config; switch default posting category (incl. custom ID) | Any time |
| `D` (interactive menu) | Select default Discourse site | When you have multiple sites |
| `c` (interactive menu) | Quick-switch posting category: private or test-cleared-daily | Day-to-day use |

---

## For developers

Reads and writes `~/.crossenv` (global) and `.env` (repo-local). Model overrides are stored in `.ai_models`, one `provider=model` per line. `--init-templates` seeds `~/.cross_templates/` from the bundled `template/` directory.

