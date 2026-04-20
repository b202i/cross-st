# Changelog

All notable changes to Cross are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
Cross uses [Semantic Versioning](https://semver.org/).

---

## [0.7.0] — Unreleased

> **GATHER → VERIFY → INTERPRET refactor.** `st-fact` is now a pure verifier
> (it produces fact-check verdicts); `st-verdict` owns all interpretation
> (chart + AI-content framework + three `--what-is-*` lenses). This is a
> **breaking** change for anyone who scripted `st-fact --ai-*` against
> 0.6.0; see Removed below for the migration map.

### Added
- **VRD-1 — `st-verdict --what-is-false` / `--what-is-true`.**
  Switches the AI from "summarise the verdict chart" to "summarise the
  **claims** that fall on one side of the truth ledger". Aggregates per-claim
  verdicts and explanations across **all** fact-checkers in the container,
  then asks one AI to synthesise them into a focused report. Pair with
  `--ai-caption/summary/story` to control level of detail (auto-promotes to
  `--ai-summary` if no detail flag is given). Mutually exclusive with each
  other and with `--what-is-missing`. New `-s/--story N` flag selects the
  story index (default: 1).
- **VRD-2 — `--ai-caption/short/summary/story` framework on `st-verdict`.**
  Full parity with the framework that previously lived on `st-fact`: same
  word-count contracts (title ≤10w, short ≤80w, caption 100–160w, summary
  120–200w, story 800–1200w), same `--ai PROVIDER` selector. `--ai-short`
  is the default output when no other `--ai-*` flag is given;
  `--no-ai-short` suppresses it. Threaded so multiple `--ai-*` flags run
  concurrently per the standard progress-message UX rule.
- **VRD-3 — `st-verdict --what-is-missing` (omissions lens).**
  Identifies what important aspects of the prompt the report failed to
  address. Reads `data[0].prompt` plus `story[N].markdown` (trimmed at
  12 000 chars) so the AI can reason about what *should* be there but
  isn't. Tailored prompts per content type — long-form `--ai-story` includes
  theme-by-theme severity ratings (critical / important / nice-to-have)
  and counter-considerations.
- **VRD-6 — `st-verdict --how-to-fix` (recommendation lens).**
  Fourth lens: reads the score breakdown, the verdict mix, and (at
  `--ai-summary` / `--ai-story` detail levels) the report itself, then
  recommends exactly **one** next action — `st-fix`, `st-bang -N`,
  `st-merge`, or `publish-as-is`. Never auto-invokes the recommended tool.
  Output ends with a fixed-shape `Recommendation: <command> — <reason>.`
  line for easy grepping. Default detail: `--ai-short` (single concrete
  sentence). Mutually exclusive with the three `--what-is-*` lenses.
- **VRD-7 — Wiki: `Three-Stages.md`.**
  New hand-authored topic page naming the GATHER → VERIFY → INTERPRET
  architecture and mapping every Cross tool to exactly one stage. Linked
  from Home, `st-fact`, `st-verdict`, `st-analyze`.
- **VRD-8 — Wiki: `Showcase-Workflows.md`.**
  New hand-authored page with copy-pastable transcripts for the three
  killer workflows: "Is this fake news?" (`--what-is-false`), "What's
  missing?" (`--what-is-missing`), and "What can I trust here?"
  (`--what-is-true`). Each includes a realistic AI-output sample. Lens
  rows in `st-verdict.md` are now anchored links into the matching
  workflow section.

### Removed (breaking)
- **VRD-5 — `st-fact --ai-*` flags removed.** Interpretive flags now live
  exclusively on `st-verdict`. `st-fact` intercepts each removed flag
  *before* `argparse` and exits 2 with a one-line migration message
  pointing at `st-verdict`. Mapping:

  | Removed | Replacement |
  |---|---|
  | `st-fact --ai-title` | `st-verdict --ai-title` |
  | `st-fact --ai-short` | `st-verdict --ai-short` (default-on) |
  | `st-fact --no-ai-short` | `st-verdict --no-ai-short` |
  | `st-fact --ai-caption` | `st-verdict --ai-caption` |
  | `st-fact --ai-summary` | `st-verdict --ai-summary` |
  | `st-fact --ai-story` | `st-verdict --ai-story` |
  | `st-fact --ai-review` | `st-verdict --what-is-false / --what-is-true / --what-is-missing` |

  No soft-deprecation cycle was shipped (the friendly removed-flag message
  delivers the same migration guidance; rationale logged in
  `cross-internal/st-fact/IMPLEMENTATION_VRD4_SKIPPED.md`). One-token fix:
  replace `st-fact` with `st-verdict`. For verify-then-interpret pipelines:
  `st-fact report.json && st-verdict --ai-caption report.json`.

### Tests
- `tests/test_st_verdict.py` — +13 tests for parse/collect/lens/missing
  helpers and three-way mutual-exclusion (VRD-1/2/3); +13 more for the
  VRD-6 `--how-to-fix` lens (mutual exclusion vs each other lens, prompt
  enumerates all four candidate actions, recommendation line required at
  every detail level, report-truncation at brief detail levels); +5 more
  for the calendar-anchor regression guard.
- `tests/test_st_fact_removed_flags.py` — new file, 7 parametrised
  regression tests guarding the removed-flag stderr message and exit code.
- `tests/test_calendar_context_in_prompts.py` *(new)* — 3 tests guarding
  `st-fact.get_fact_check_prompt()` includes today's ISO date and the
  post-cutoff guidance.
- `tests/test_update_check_dev_guard.py` *(new)* — 4 tests guarding the
  dev-checkout suppression of the PyPI-upgrade nag.

### Fixed
- **Stale upgrade nag in dev checkouts** — `mmd_startup.check_for_updates()`
  now returns early when either `_in_project_venv()` or the new
  `_running_from_dev_checkout()` (sys.argv[0] inside `_PROJECT_ROOT`)
  is `True`. Previously a stale `pip install cross-st==0.2.0` registered
  in some other Python interpreter's metadata could cause the running
  dev source to print misleading "💡 cross-st X is available
  (installed: 0.2.0)" warnings. Dev users manage their own version via
  `git pull`; they never need the PyPI nag.
- **Calendar anchor in fact-check + lens prompts** — `st-fact`'s
  `get_fact_check_prompt()` now declares today's ISO date and explicitly
  instructs AIs not to flag a claim as `False` purely because the cited
  date is later than their training-data cutoff. The fix also propagates
  to `st-verdict` via a new `_today_context_block()` helper prepended to
  all four lens prompt builders (`_build_missing_prompt`,
  `_build_howtofix_prompt`, and the truth-ledger branch in
  `build_lens_prompt`). Field symptom: gemini's `--what-is-false`
  summary on a 2026-04-19 run mistook every 2025-dated study citation
  as "future-dated, therefore non-existent". Full write-up:
  `cross-internal/st-verdict/BUGFIX_calendar_anchor_and_dev_upgrade_nag.md`.

---

## [0.6.0] — 2026-04-17

### Added
- **PAR-1 — `st-cross` per-provider rate limiting + flag surface.**
  `st-cross` has always run its N×N matrix in parallel (one thread per cell);
  PAR-1 adds a per-provider concurrency cap so the wide-open fan-out can no
  longer trip rate limits on free / starter API tiers.
  - New flags: `--parallel` / `-p` (default), `--sequential`,
    `--max-concurrency N`, `--retry-budget SECONDS` (default 45).
  - Per-provider semaphore sized via `cross_ai_core.get_rate_limit_concurrency()`
    (xai=3, anthropic=2, openai=3, perplexity=2, gemini=5).
  - `--retry-budget` is plumbed through to `st-fact` → `process_prompt(retry_budget=…)`
    so a single transient 503 can no longer park the matrix on a 105 s tail.
  - Removed dead `_run_column()` helper from `st-cross.py`.
- **`st-fact --retry-budget SECONDS`** — passes through to
  `process_prompt(retry_budget=…)`. `0` = unlimited (pre-PAR-1 behaviour, default).
- **`get_rate_limit_concurrency` re-exported** from the `cross_st.ai_handler` shim.

### Changed
- **`cross-ai-core` floor bumped to `>=0.6.0`** (PAR-1 needs `get_rate_limit_concurrency`
  + `process_prompt(retry_budget=…)` from `cross-ai-core` 0.6.0).

### Fixed
- **`discourse.py` — hand-rolled `load_dotenv` chain removed.**
  `get_discourse_slugs_sites()` was rolling its own four-layer `load_dotenv`
  without the `_in_project_venv()` guard, so the dev checkout's `.env` was
  loaded with `override=True` for all users, silently shadowing `~/.crossenv`.
  Symptom: `st-admin --discourse m a` added a site that never appeared in `st`'s
  post-menu. Fix: delegate to `mmd_startup.load_cross_env()` so the venv guard
  is respected by every code path.
- **`st-admin` — writes to the profile-correct settings file.**
  `_env_set()` now resolves `_TARGET_ENV` at startup:
  developer venv (`_in_project_venv()=True`) → `<project>/.env`;
  pipx / system-Python user → `~/.crossenv`.
  `interactive_menu()` prints a banner showing the active file on entry.
- **`st-admin` — `_warn_if_shadowed()` guardrail.**
  After every `_env_set()` write, any higher-priority `.env` file that defines
  the same key triggers a visible `⚠️ Warning` naming the file.

### Tests
- New `tests/test_st_cross.py` — 13 PAR-1 unit tests covering the semaphore
  registry, rate-limit enforcement (real `threading.Semaphore` race), CLI
  surface, and `--parallel/--sequential` mutual exclusion.
- `tests/test_st_admin.py` `tmp_settings` fixture now patches `_TARGET_ENV` —
  fully isolates tests from `~/.crossenv`.
- `tests/test_dotenv_resolution.py::TestDiscoursePathResolution` — R1/R3 guards
  rewritten to assert `discourse.py` delegates to `load_cross_env()`.
- Suite: 696 → **746 passing** (105 skipped, 0 failing).

---

## [0.5.1] — 2026-04-16

### Fixed
- **`st-admin --upgrade` install-type detection** — pipx installs were falsely
  reported as "Editable (dev) install" when the pipx venv had previously been
  set up with `--editable`. Detection now checks whether `sys.executable` lives
  inside the pipx home directory (`~/.local/pipx/` or `$PIPX_HOME`) **before**
  consulting `direct_url.json`. This means:
  - **pipx users** always get `pipx upgrade cross-st` — regardless of any stale
    editable marker.
  - **Dev-venv users** (editable install, `direct_url.json` present) get a clear
    message with the checkout path and exact `git pull` + `pip install -e .`
    instructions.
  - **Plain pip users** (Homebrew Python, system Python, etc.) get
    `pip install --upgrade cross-st` as before.

---

## [0.5.0] — 2026-04-16

### Added
- **`st-post --category reports`** (DA-21) — post to the public "📄 Reports" portfolio category
  (id=16, `crossai.dev/u/<username>/activity/topics`); `_DISCOURSE_REPORTS_CATEGORY_ID = 16`
  constant in `st-admin.py`; `st-admin` category quick-picker (`c` key) now shows three options:
  `1` private · `2` Test (cleared daily) · `3` 📄 Reports

### Changed
- **`st-speed --ai` dual behavior** — when `--ai` is paired with any `--ai-*` content flag
  (`--ai-caption`, `--ai-short`, `--ai-title`, `--ai-summary`, `--ai-story`), `--ai` selects
  which provider *generates the content* only; the performance display table always shows all
  providers (`display_filter=None`). `--ai` alone (no `--ai-*` flag) still filters the display
  to one provider as before.
- **Progress feedback before every AI call** — all `st-*` scripts that call `process_prompt()`
  now print `Generating {label} with {ai}…` immediately before the call (or before launching a
  background thread), unless `--quiet` is active. Affected tools: `st-verdict`, `st-heatmap`,
  `st-analyze`, `st-merge`, `st-plot` (complementing `st-speed` and `st-stones` which already
  complied). Standard format: `print(f"  Generating {label} with {ai_make}…", flush=True)`.
- **`cross-ai-core ≥ 0.5.0` required** — `process_prompt()` now accepts a `model=` keyword arg
  for per-call model overrides; `get_ai_model(make)` checks `<MAKE_UPPER>_MODEL` env vars first
  (e.g. `XAI_MODEL=grok-3-latest`, `ANTHROPIC_MODEL=claude-sonnet-4-5`); `openai>=2.0.0`
  required (was `>=1.70.0`).

### Fixed
- **`st-print` WeasyPrint error handling** — catches `OSError` (missing native Pango/GObject
  libs) in addition to `ImportError`; prints platform-specific install hint (macOS:
  `brew install pango`; Linux: `apt-get install libpango*`).

### Wiki
- **29/29 wiki pages at 100% `--help` coverage** (Part B complete) — all 29 `st-*` command
  pages updated with complete flag tables; four pages are hand-authored (`st-domain`, `st-fix`,
  `st-speed`, `st-heatmap`) and will not be overwritten by `build_wiki.py`.
- **`st-cross` pipeline graphic** — `st-cross-pipeline.svg` added to the `st-cross` wiki page
  showing the N×N cross-product generation and fact-check workflow.
- **`build_wiki.py` / `push_wiki.sh`** — script path fixed post-C1 (`cross_st/` subdirectory);
  wiki links use bare page names (no `.md`); `push_wiki.sh` now copies `*.png` files.

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

