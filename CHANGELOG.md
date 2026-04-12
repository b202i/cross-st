# Changelog

All notable changes to Cross are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
Cross uses [Semantic Versioning](https://semver.org/).

---

## [0.4.0] — 2026-04-12

### Added
- **`st-post --category private|test`** — explicit posting-category flag;
  `test` (sandbox, cleared daily) is now the default, keeping new users safe
  from accidentally posting to their private area
- **`st-admin` 2-level interactive menu** — top level: `a` AI, `t` Templates
  & editor, `d` Discourse, `c` Cache, `s` show all settings, `u` upgrade;
  each letter navigates into a submenu; ESC goes back; breadcrumb title shown
  (`st-admin>AI>` etc.)
- **`st-admin` Discourse D/c quick-pickers** — `d` selects default Discourse
  site; `c` switches posting category (private | Test cleared daily) with
  immediate single-keypress UX; both support ESC to go back
- **T&C versioning (TAP-1)** — `cross_st/data/tos_versions.json` manifest
  ships with the package; `get_tos_versions()` in `discourse_provision.py`;
  version footer shown at the end of `display_terms_and_conditions()` output
- **`st-admin --check-tos`** — compares stored vs manifest T&C version;
  prompts re-acceptance and updates `DISCOURSE` JSON if stale
- **@mention escaping in `st-post`** — Discourse posts with 10+ `@username`
  mentions are now escaped before posting to avoid the moderation auto-flag

### Changed
- **`st.py` Settings submenu removed** — the 3-item Settings submenu is gone;
  `x` now launches `st-admin` directly (no submenu)
- **Setup wizard restructured** — mid-wizard "Configure a custom Discourse
  forum?" prompt removed; wizard ends with two clear questions:
  (1) crossai.dev community access (default Y) and
  (2) additional self-hosted forum (default N); setup checklist shows the
  resolved `~/.crossenv` path (not the literal `~` string); API key privacy
  notice moved before the "Continue?" prompt
- **T&C display** — pager (`less`) replaced with direct `print` to terminal;
  no hidden exit key, works on all platforms without external tools
- **Terminology** — user-visible text uses "report/reports" consistently;
  renamed docstrings and CLI prompts (`story container` → `report container`,
  `stories` → `reports` in Discourse prompt)

### Fixed
- **`st-gen` exit message** — suppressed redundant "file does not exist" error
  when `st-gen` exits non-zero (API error already printed)
- **`st-prep` filename hint** — shows the correct missing `.json` filename;
  hints `st-gen` when a `.prompt` file is passed instead of `.json`
- **`st.py` gen calls** — removed erroneous `--prep` flag from gen calls;
  `st-gen` has `--no-prep` only (`prep=True` is the default)
- **`st-admin --discourse-setup`** — UX messaging updated to give explicit
  private/incognito window instructions at both the invite step and the
  activation-email step; keyboard shortcuts shown for Chrome/Edge/Firefox/Safari

### Tests
- **COV-1** — 122 new unit tests across three previously untested modules:
  - `test_mmd_util.py` (52 tests) — `get_project_root`, `tmp_safe_name`,
    block-file helpers, `build_segments` (14 cases), `seed_*` helpers
  - `test_ai_handler.py` (40 tests) — `get_default_ai`, `get_ai_model`
    (env-var override), `get_content/put_content`, `get_content_auto/
    put_content_auto`, `AIResponse` wrapper
  - `test_mmd_data_analysis.py` (30 tests) — `get_flattened_fc_data`,
    square-matrix logic, malformed-entry skipping, non-square trimming
  - Suite: **676 passing, 57 skipped** (was 554)

---

## [0.3.0] — 2026-04-08

### Added
- **`st-new -g` / `--gen`** — after editing the prompt, automatically runs
  `st-gen` (all providers) then `st-prep`; combines prompt editing and report
  generation into a single command
- **`st-new --prep`** — after editing, runs `st-prep` only (re-processes an
  existing generation without re-calling the APIs)
- **`st-new --ai`** — override the provider used by the auto-gen step
- **`st-gen`, `st-merge`, `st-analyze` AI narrative flags** — `--ai-title`,
  `--ai-short`, `--ai-caption`, `--ai-summary`, `--ai-story`: generate
  AI-written headlines, summaries, or full narrative from analysis results;
  AI-caption expansion for richer chart annotations
- **`st-admin --version`** — print the installed cross-st version; version line
  also shown in `st-admin --show` output

### Fixed
- **`st-fix --mode synthesize` crash** (`KeyError: 'content'`) — `_save_result()`
  now derives the rewriter AI from `gen_response["_make"]` (stamped by
  `process_prompt()`) instead of always using `args.ai`; fixes the case where
  the best-story author differs from the `--ai` flag

### Dependencies
- **`cross-ai-core>=0.5.0`** (was `>=0.4.2`) — adds `model=` per-call override
  and `<MAKE>_MODEL` env-var model switching; set e.g. `XAI_MODEL=grok-3-latest`
  in `~/.crossenv` to change models globally without touching code
- **`openai==2.31.0`** (was `1.70.0`) — major SDK version; `openai 2.x` is now
  the minimum required
- **`anthropic==0.92.0`** (was `0.84.0`)
- **`google-genai==1.71.0`** (was `1.65.0`)

---

## [0.2.0] — 2026-04-04

### Added
- **`st-admin --cache-info`** — print `~/.cross_api_cache/` path, file count, and
  total disk usage (auto-scaled B / KB / MB)
- **`st-admin --cache-clear`** — delete all cached AI responses
- **`st-admin --cache-cull DAYS`** — delete cache entries older than *N* days
  (uses `mtime`; rejects `DAYS ≤ 0`)
- Interactive menu keys `C` (cache info), `X` (cache clear, with confirmation),
  `K` (cache cull) added to `st-admin`
- **`st-admin --upgrade`** — upgrade `cross-st` from PyPI (auto-detects pipx vs
  pip, skips editable installs) and Homebrew platform tools (`ffmpeg`, `aspell`)
  on macOS; prints equivalent `apt`/`dnf` commands on Linux
- **Auto update-check** in `mmd_startup.py` (`check_for_updates()`): background
  daemon thread polls PyPI once per 24 h, caches result to
  `~/.cross_api_cache/update_check.json`, prints
  `💡 cross-st X.Y.Z is available → st-admin --upgrade` to stderr on the next
  interactive run (TTY-only, suppressed in pipes/CI)

### Changed
- Package directory renamed from `cross_ai/` to `cross_st/` — all imports,
  entry points, `pyproject.toml`, `mmd_startup.py`, and tests updated;
  `_CROSS_AI_DIR` kept as a legacy alias in `mmd_startup.py`
- `[tts]` extra is the opt-in install path for TTS/audio (`pipx install
  "cross-st[tts]"`); bare `pipx install cross-st` remains the fast
  no-audio default

### Security / Dependencies
- `pillow>=12.1.1` — CVE-2025-48379, CVE-2026-25990
- `requests>=2.32.4` — CVE-2024-47081
- `setuptools>=78.1.1` — CVE-2025-47273
- `urllib3>=2.6.3` — CVE-2025-50181, CVE-2025-50182

---

## [0.1.0] — 2026-04-03 — First public release on PyPI (`cross-st`)

> Published to https://pypi.org/project/cross-st/0.1.0/
> Install: `pipx install cross-st` or `pipx install "cross-st[tts]"`

### Added
- **PyPI distribution** (`cross-st`) — `pipx install cross-st`; all `st-*`
  entry points created automatically via `[project.scripts]` in `pyproject.toml`
- **`st-admin --setup`** — interactive first-run wizard: configures API keys,
  `DEFAULT_AI`, TTS voice, editor in `~/.crossenv`
- **`st-admin --init-templates` / `--overwrite-templates`** — seed or refresh
  `~/.cross_templates/` from the bundled `template/` directory
- **`st-stones --init`** — seed `~/cross-stones/` from bundled benchmark prompts
- **`st-domain`** — interactive wizard to create new Cross-Stones domain prompts
  (Phases 2–4 of `DOMAIN_PROMPT_PROCESS.md`)
- **`mmd_startup.require_config()`** — first-run guard in every `st-*.py`;
  redirects to `st-admin --setup` when config is missing
- **`~/.crossenv`** — global config convention; `~/.cross_api_cache/` for cache;
  `~/.cross_templates/` for templates; `~/cross-stones/` for benchmark domains
- **`CROSS_NO_CACHE=1`** env var honored in all AI handlers (via cross-ai-core ≥ 0.4.1)
- **`commands.py`** — `runpy.run_path()` dispatch for all `st-*.py` entry points;
  inserts `cross_ai/` onto `sys.path`
- **AI stack extracted to `cross-ai-core`** — thin shims in `cross_ai/` keep all
  imports working; actual provider code lives in the `cross-ai-core` sibling repo
- `st-speed` — AI performance benchmarking with `--ai-caption`, `--ai-short`,
  `--ai-title`, `--ai-summary` options for AI-generated narrative
- `st-find` — keyword search across prompts, stories, and titles with boolean
  operators (`+required`, `^excluded`), wildcards, and context preview
- `st-fix --mode iterate` — iterative per-claim fixing: each claim is rewritten
  and immediately fact-checked before moving to the next
- `st-fact --ai all` — fact-check with all configured AI providers in parallel
- Timing data collected automatically during `st-cross` and `st-fact` runs
- `CONTRIBUTING.md`, `CHANGELOG.md`, `CODE_OF_CONDUCT.md`
- GitHub Issue Templates and PR template

### Fixed
- `st-bang` merge failure: "Warning: could not save … 'story'" when tmp files
  lacked a `story` key
- `st-analyze` crash on `KeyError: 'summary'` when no fact-checks present —
  now gives a friendly message suggesting `st-cross` first
- `st-read` numbers now rounded to one decimal place
- `ModuleNotFoundError: No module named 'pkg_resources'` in `textstat` —
  resolved by pinning `setuptools` in `requirements.txt`
- `st-fix --mode iterate` `UnboundLocalError: fc_ai_model` when all claims
  were skipped
- `st-speed` AI calls now go through `ai_handler.py` (caching, .env keys,
  error handling) instead of direct SDK calls
- `ai_gemini.py` `TypeError: 'str' object does not support item assignment`
  in `put_content`

### Changed
- All runtime code moved to `cross_ai/` package (C1); repo root contains only
  config files, docs, tests, and scripts
- Package renamed from `crossai-cli` to `cross-st` (C2)
- `st-fix`: post-fix fact-check now scoped to changed claims only, not the
  entire document (avoids inflating the false-claim count)

### Known Issues
- `requirements.txt`: `wyoming==1.6.3` is yanked; `google-auth==2.38.0`
  conflicts with `google-genai>=1.65.0`. Fix: see `README_opensource.md`.

---

## [0.0.1] — 2025-03-01 (initial private release)

### Added
- `st-gen` — generate a story from a `.prompt` file using a selected AI
- `st-bang` — generate stories from all 5 AI providers in parallel
- `st-cross` — cross-product fact-check: every AI fact-checks every story
- `st-fact` — fact-check a specific story
- `st-merge` — synthesize the best-scoring stories into one
- `st-fix` — rewrite false/partial claims using AI
- `st-analyze` — statistical analysis and visualization of fact-check results
- `st-edit` — view and edit story text in terminal or markdown
- `st-read` — readability metrics table (Flesch-Kincaid, Gunning Fog, etc.)
- `st-ls` — list stories and fact-checks in a JSON container
- `st-cat` — cat raw story text to stdout
- `st-post` — post stories to Discourse with optional audio attachment
- `st-speak` / `st-voice` — generate MP3 audio from story text
- `st-fetch` — fetch and summarize web content into a prompt
- `st-new` — create a new prompt from the default template
- `st-rm` — remove a story from a container
- `st-heatmap` — render fact-check score heatmap
- `st-plot` — plot fact-check scores
- `st` — interactive TUI menu
- Support for 5 AI providers: xAI (Grok), Anthropic (Claude),
  OpenAI (GPT-4o), Perplexity (Sonar), Google (Gemini)
- API response caching (`api_cache/`) with `--cache` / `--no-cache` flags
- `.env`-based API key management
- Discourse multi-site posting support

