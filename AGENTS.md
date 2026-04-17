# AGENTS.md — Cross Codebase Guide

## What This Project Does
Cross generates research reports using 5 AI providers simultaneously, then cross-checks each report against all others (5×5 fact-check matrix). Reports publish to Discourse. The entry point is `st` (interactive menu) or any `st-*` command directly.

## Architecture

**All runtime code lives in `cross_st/` renamed to cross_st/ (C1 complete).** The repo root contains only `pyproject.toml`, `requirements*.txt`, `docs/`, `tests/`, `script/`, and config files. All `st-*.py` scripts, support modules, and data directories are inside `cross_st/`.


```
cross_st/                ← Python package; all runtime code lives here (C1)
cross_st/st.py           ← Menu/command builder ONLY — no business logic
cross_st/st-*.py         ← 28 individual CLI tools (each owns its own logic)
cross_st/st-admin.py     ← Settings manager: DEFAULT_AI, model overrides, TTS voice, editor, --init-templates
cross_st/st-domain.py    ← Interactive wizard: create a new Cross-Stones domain prompt (Phases 2–4)
cross_st/st-fetch.py     ← Import external content into a container (tweet_id / --file / --url / --clipboard)
cross_st/st-find.py      ← Keyword search across .json containers and .prompt files; boolean operators (+required, ^excluded) + wildcards
cross_st/st-fix.py       ← Improve a story via fact-check feedback (modes: iterate [default] / patch / best-source / synthesize)
cross_st/st-merge.py     ← Synthesize multiple AI stories (auto: simple mode or quality mode using fact scores)
cross_st/st-man.py       ← Man-page viewer: local help from docstrings + --web opens GitHub Wiki
cross_st/st-new.py       ← Create a new prompt from template/; opens editor; `-g`/`--gen` auto-runs st-gen+st-prep after editing; `--bang` runs st-bang (all AIs); `--ai` selects provider (defaults to `get_default_ai()`)
cross_st/st-print.py     ← Convert a story to PDF; print to system printer or --save-pdf / --output file
cross_st/st-heatmap.py   ← Cross-product fact-check score heatmap (evaluator vs target)
cross_st/st-verdict.py   ← Verdict category bar chart (stacked per author AI)
cross_st/st-speed.py     ← AI performance/speed analysis and timing comparison
cross_st/st-stones.py    ← Cross-Stones benchmark leaderboard aggregator
cross_st/ai_handler.py      ← Compatibility shim → cross_ai_core.ai_handler (see cross-ai-core repo)
cross_st/ai_error_handler.py ← Compatibility shim → cross_ai_core.ai_error_handler
cross_st/base_handler.py    ← Compatibility shim → cross_ai_core.ai_base
cross_st/ai_url.py          ← X/Twitter + web URL fetch handler for st-fetch (AI_MAKE="url"; NOT in AI_HANDLER_REGISTRY)
cross_st/mmd_*.py           ← Support modules: util, process_report, branding, plot, voice, for_speaking, single_key
cross_st/mmd_data_analysis.py ← Flattened fact-check data helpers used by heatmap/verdict/analyze
cross_st/mmd_startup.py     ← First-run detection: `require_config()` called near the top of every `st-*.py` (except `st-admin`, `st-man`); `load_cross_env()` also calls `check_for_updates()` (background PyPI poll, TTY-only, max once per 24 h)
cross_st/mmd_web_server.py  ← Candidate Markdown preview server (currently unused; candidate to replace grip)
cross_st/discourse.py       ← Discourse API client (MmdDiscourseClient wraps pydiscourse)
cross_st/commands.py        ← Entry-point dispatch for pyproject.toml; maps `st_*` functions → `st-*.py` via runpy; also inserts `cross_st/` onto sys.path
cross_st/cross_stones/                    ← Cross-Stones benchmark suite
cross_st/cross_stones/cross-stones-10.json  ← Named benchmark set: locked params (n_claims, max_fact_score)
cross_st/cross_stones/domains/            ← 10 standard domain prompts + result containers
cross_st/data/              ← Package data directory (shipped with the package via VCS include)
cross_st/data/discourse_tos.txt   ← T&C text displayed to new users during setup; top line is `# VERSION: <date>`
cross_st/data/tos_versions.json   ← T&C version manifest: `{"tos_version": "...", "privacy_version": "...", "updated_at": "..."}`; `get_tos_versions()` falls back to hardcoded `2026-04-07` if file is missing
cross_st/template/         ← Prompt templates for st-new; template/*.prompt files; default.prompt is the baseline
api_cache/         ← MD5-keyed cached API responses (legacy local path; ~/.cross_api_cache/ for installed use)
tmp/               ← Transient parallel coordination files
docs/wiki/         ← GitHub Wiki source files (version-controlled); auto-built by script/build_wiki.py
../cross-ai-core/  ← Sibling repo: the extracted AI provider stack (published to PyPI as cross-ai-core)
```

**AI stack lives in `cross-ai-core`.** The files `cross_st/ai_handler.py`, `cross_st/ai_error_handler.py`, and `cross_st/base_handler.py` are thin compatibility shims. The actual provider implementations (`ai_anthropic.py`, `ai_xai.py`, etc.) live in `~/github/cross-ai-core/cross_ai_core/`. All `st-*.py` imports continue to work unchanged through the shims.

**`process_prompt()` stamps `_make` into every response it returns (≥ 0.4.2).** The key `_make` holds the provider string (e.g. `"gemini"`) so the response dict is self-describing. Use `get_content_auto(response)` and `put_content_auto(report, response)` from `ai_handler` whenever you hold a fresh response from `process_prompt()` — these dispatch to the correct provider without you needing to pass `make`. Fall back to `get_content(make, response)` / `put_content(make, report, response)` only when reading from old containers that lack `_make`.

**Never hardcode AI provider names or model strings in code.** Always call `get_default_ai()` from `ai_handler` when a default provider is needed, and `get_ai_model(make)` / `settings_get_ai_model(make)` when a model string is needed. Use `--ai` CLI flags to let callers override. Hardcoded names like `"xai"` or `"anthropic"` in code are a bug.

## JSON Container Format (`.json` files)
Every story lives in a single `.json` container with two top-level arrays:
```json
{
  "data":  [{ "make": "xai", "model": "...", "prompt": "...", "gen_payload": {},
              "gen_response": {}, "timing": {}, "md5_hash": "..." }],
  "story": [{ "make": "xai", "model": "...", "title": "...", "markdown": "...",
              "text": "...", "spoken": "...", "hashtags": [], "fact": [] }]
}
```
- `data[]` — raw AI API responses written by `st-gen`; each entry includes a `timing{}` dict (`elapsed_seconds`, `tokens_input`, `tokens_output`, `tokens_total`, `tokens_per_second`, `cached`) and an `md5_hash` of the payload
- `story[]` — processed output written by `st-prep`; includes `hashtags[]` extracted from the report
- `fact[]` — appended by `st-fact`/`st-cross`; each entry: `{ make, model, score, counts, summary, report, claims[], timing{} }` where `claims[]` holds per-segment verdict details and `timing{}` is present on fresh (non-cached) runs

## Adding a New AI Provider
1. Work in the `cross-ai-core` repo (`~/github/cross-ai-core/`), not here
2. Create `cross_ai_core/ai_<name>.py` implementing all methods from `BaseAIHandler` (`get_payload`, `get_client`, `get_cached_response`, `get_model`, `get_make`, `get_content`, `put_content`, `get_data_content`, `get_title`, `get_usage`)
3. Register in `cross_ai_core/ai_handler.py`: add to `AI_HANDLER_REGISTRY` dict and `AI_LIST`
4. Bump the version in `cross-ai-core/pyproject.toml`, reinstall (`pip install -e ../cross-ai-core/`)

## Parallel Execution (`st-bang`)
`st-bang` launches one `st-gen --bang N` subprocess per AI. Each writes to `tmp/<story>_N.json` and creates a block file `tmp/<story>_N.json.block`. `st-bang` polls every second until all block files are removed, then merges results into the main `.json`. Use `mmd_util.tmp_safe_name()` to convert file paths to collision-safe flat names for `tmp/`.

## API Response Cache
All AI calls are cached by default. Cache key = MD5 of the serialized payload → `api_cache/<hash>.json`. Pass `--no-cache` to bypass. Set `CROSS_NO_CACHE=1` in `~/.crossenv` or `.env` to disable caching globally without per-command flags (implemented in cross-ai-core ≥ 0.4.1). The cache makes development fast — replay expensive API calls instantly.

**Note:** `_make` is stamped into the in-memory response by `process_prompt()` at runtime but is **not** written to cache files on disk. Cached responses loaded from disk won't carry `_make`; use `get_content(make, response)` / `put_content(make, report, response)` when reading from cache directly. Responses returned by `process_prompt()` always have `_make` regardless of whether they came from cache or a live API call.

## Setup (Python 3.10+ required; 3.11 recommended)
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .              # installs cross_st package + creates st-* entry points in .venv/bin
```
The old `bash script/symbolic_links.bash` step is obsolete — `pip install -e .` generates all entry points via `[project.scripts]` in `pyproject.toml`. The script still exists but references root-level `st-*.py` files that moved to `cross_st/` (C1) and will not work.

For pipx installs (recommended for end users):
```bash
pipx install cross-st              # no TTS
pipx install "cross-st[tts]"       # with text-to-speech (st-speak, st-voice)
st-admin --setup                   # configure API keys on first run
```
Audio packages (`soundfile`, `yakyak`) have wheels for Python 3.10–3.13 on macOS ARM — **there is no Python 3.11 upper limit for TTS**. The minimum is 3.10 (numpy 2.x, scipy 1.15.x, and `match` syntax in st-plot.py/st-voice.py require it). 3.9 is not supported. Note: numpy 2.3+ requires Python 3.11+; on 3.10 pip auto-resolves to numpy 2.2.x. See `tests/test_tts_stack.py` for a live install+import test across all versions.

## Environment
`.env` (never commit) holds API keys, Discourse config, and user preferences:
```
ANTHROPIC_API_KEY=...  XAI_API_KEY=...  OPENAI_API_KEY=...
PERPLEXITY_API_KEY=... GEMINI_API_KEY=...
DISCOURSE={"sites":[{"slug":"MySite","url":"...","username":"...","api_key":"...","category_id":1}]}
DEFAULT_AI=xai          # provider used when --ai is not passed (set via st-admin)
XAI_MODEL=grok-3-latest         # optional: override compiled-in default per provider (≥ 0.5.0)
ANTHROPIC_MODEL=claude-sonnet-4-5  # same pattern for all five providers
OPENAI_MODEL=gpt-4o-mini           # GEMINI_MODEL, PERPLEXITY_MODEL also supported
TTS_VOICE=...           # piper TTS voice string
TTS_HOST=localhost      # Piper TTS server host (used by st-speak, st-voice)
TTS_PORT=5000           # Piper TTS server port
DEFAULT_TEMPLATE=...    # default prompt template name
EDITOR=vi               # editor launched by st-edit
X_COM_BEARER_TOKEN=...  # X/Twitter bearer token (st-fetch tweet_id source only)
CROSS_STONES_DIR=...    # custom benchmark domain directory (default: ~/cross-stones/)
```
`.ai_models` (never commit) holds per-provider model overrides: `xai=grok-3` one per line.
All scripts load config in this 4-layer order (A1 convention). **Project `.env` overrides `~/.crossenv`** — later layers always win:
```python
_CROSSENV = os.path.expanduser("~/.crossenv")
load_dotenv(_CROSSENV)                                              # 1. global fallback (lowest priority)
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"), override=True)    # 2. repo-local .env — wins over global
load_dotenv(os.path.join(_CROSS_ST_DIR, ".env"), override=True)    # 2b. cross_st/.env (pip install layout)
load_dotenv(os.path.join(os.getcwd(),    ".env"), override=True)   # 3. CWD .env — highest priority
```
Per-repo settings (`DEFAULT_AI`, `DISCOURSE`, model overrides, etc.) in a project `.env` take effect
without touching the global file. `~/.crossenv` acts as a fallback for keys not set in any project file.

`DEFAULT_AI` is read by `ai_handler.get_default_ai()` — the single source of truth for the default provider.

### Home-directory conventions (A1)
| Path | Purpose |
|------|---------|
| `~/.crossenv` | API keys + preferences (global config) |
| `~/.cross_api_cache/` | MD5-keyed API response cache |
| `~/.cross_templates/` | Prompt templates for `st-new` (pip/pipx installs) |
| `~/cross-stones/` | Benchmark domain `.prompt` files for pipx users (seeded by `st-stones --init` or `st-admin --setup`); override with `CROSS_STONES_DIR` in `~/.crossenv` |

`st-new` resolves templates with this priority: `./template/` (CWD developer override) → `~/.cross_templates/` → `<script-dir>/template/` (repo fallback).

## Testing
```bash
pytest                        # runs tests/ with config from pytest.ini
pytest tests/test_mmd_process_report.py -v
```
Tests live in `tests/` with fixtures in `tests/fixtures/` (e.g. `pizza_dough.json`). **Never call real AI APIs in tests** — use fixtures and mocks. Suite at v0.4.0: **676 passing, 57 skipped**. Current HEAD: **754 collected (695 passing, 57 skipped, 0 failing)** — `TestDiscourseManage` expanded to 36 tests with full DA-21 (Reports category) coverage.

Current test files: `test_mmd_process_report.py`, `test_container_loading.py`, `test_st_admin.py`, `test_st_plot.py`, `test_st_speed.py`, `test_st_stones.py`, `test_dotenv_resolution.py`, `test_tts_stack.py`, `test_cache_timing_preservation.py`, `test_cli_help.py`, `test_imports.py`, `test_st_bang.py`, `test_st_verdict.py`, `test_mmd_util.py`, `test_ai_handler.py`, `test_mmd_data_analysis.py`, `test_ai_options.py`, `test_discourse_provision.py`.

## Cross-Stones Benchmark (`st-stones`)
`cross_st/cross_stones/domains/` contains 10 benchmark domain prompts + result containers. `cross_st/cross_stones/cross-stones-10.json` is the **named benchmark set config** — it locks the domain list, `n_claims`, and `max_fact_score` so scores are directly comparable across runs over time. Do not add or remove domains from that file; create a new named set for variants.

Each domain prompt asks every AI to generate exactly 10 fact-checkable claims. After running `st-cross` on each domain, `st-stones` computes a composite `cross_stone_score`:

```
cross_stone_score = w1 × (fact_score / max_fact_score) + w2 × (speed_score / max_speed_score)
```

Default weights: accuracy `w1=0.7`, speed `w2=0.3`. Speed score is `1 / (avg_gen_elapsed + avg_fc_elapsed)`.

```bash
# Named set (uses locked n_claims=10, max_fact_score=200 from the config)
st-stones cross_st/cross_stones/cross-stones-10.json

# Directory (auto-discovers domains/ subdirectory)
st-stones cross_st/cross_stones/

# No argument — auto-detects ./cross_stones/ then ~/cross-stones/
st-stones

# Seed ~/cross-stones/ from bundled prompts (pipx users, first run)
st-stones --init
st-stones --init --dir my_domains/    # custom destination

# With options
st-stones --no-speed cross_st/cross_stones/cross-stones-10.json      # accuracy-only
st-stones --domain --ai-caption cross_st/cross_stones/cross-stones-10.json  # breakdown + caption
st-stones --run cross_st/cross_stones/cross-stones-10.json           # run missing domains then score
```

When a benchmark set config is passed, `st-stones` prints the set id and uses its `n_claims` value (overridable with `--n-claims`). When a plain directory is passed, it looks for `.prompt` files directly, then falls back to a `domains/` subdirectory.

### Creating a custom domain (`st-domain`)

```bash
st-domain                                        # fully interactive wizard
st-domain --name supply_chain                    # pre-fill slug
st-domain --dir my_domains/                      # custom output directory
st-domain --set cross_st/cross_stones/cross-stones-10.json  # register in a benchmark set
```

`st-domain` follows `DOMAIN_PROMPT_PROCESS.md` Phases 2–4:
- **Phase 2** — collects slug, display name, topic description, year range, source types
- **Phase 3** — calls AI to suggest 5 aspects; assembles the prompt from template; shows preview
- **Phase 4** — smoke-tests by sending the prompt to one AI; user validates 10 claims returned

Prompts are saved to `cross_st/cross_stones/domains/` by default. After saving, run:
```bash
st-cross cross_st/cross_stones/domains/<slug>.json   # run the N×N benchmark
st-stones cross_st/cross_stones/domains/             # score all domains in that dir
```

Benchmark domains (standard set): `software_development`, `customer_service`, `marketing_content`, `education_learning`, `data_analytics`, `healthcare_medical`, `finance_business`, `writing_editing`, `research_qa`, `creative_media`.

## Known Regression Traps

These patterns have each caused a real regression. Read before touching env loading or module init.

### R1 — `discourse.py` (and any file with its own `load_dotenv`) must use `_project_root`

After the C1 migration, `cross_st/` became a subdirectory.  Any file that does its own
`load_dotenv` and computes a base path with `os.path.dirname(__file__)` now gets `cross_st/`,
**not** the project root where `.env` lives.  It must walk up one level:

```python
# WRONG — gives cross_st/, .env is never found from non-repo CWD
_basedir = os.path.dirname(os.path.realpath(__file__))

# CORRECT — gives project root (parent of cross_st/)
_cross_st_dir = os.path.dirname(os.path.realpath(__file__))
_project_root = os.path.dirname(_cross_st_dir)
```

The canonical loader is `mmd_startup.load_cross_env()`.  Prefer calling it over reimplementing the layers.

### R2 — Module-level code in `st.py` must not read env before `load_cross_env()`

`st.py` calls `get_discourse_slugs_sites()` at module level.  That call reads `DISCOURSE` from
the environment.  `load_cross_env()` **must** run first, or the call silently sees an empty
environment when the CWD has no `.env` (e.g. running `st` from `~/mmd/`).

```python
# WRONG — DISCOURSE unset if CWD != repo root
slugs, sites = get_discourse_slugs_sites()

# CORRECT
load_cross_env()
slugs, sites = get_discourse_slugs_sites()
```

Test: `tests/test_dotenv_resolution.py::TestStPyInitOrder::test_load_cross_env_called_before_discourse`

### R3 — Layer 2 must use `override=True` so project `.env` wins over `~/.crossenv`

The old code loaded both `~/.crossenv` and the project `.env` without `override=True`.
Because `load_dotenv` (without override) never overwrites an already-set key, `~/.crossenv`
silently won every collision — the opposite of the stated intent.

```python
# WRONG — ~/.crossenv wins any collision
load_dotenv(crossenv)
load_dotenv(project_env)          # no-op for keys already set by crossenv

# CORRECT — project .env wins
load_dotenv(crossenv)
load_dotenv(project_env, override=True)   # clobbers crossenv values intentionally
```

Test: `tests/test_dotenv_resolution.py::TestDotenvResolution::test_layer2_overrides_layer1`

> **Warning:** `st-admin --set-default-ai` and `st-admin` model-setting commands write to
> `~/.crossenv`.  If your project `.env` also sets those keys, the project `.env` wins and
> `st-admin` changes appear to have no effect.  Remove the key from the project `.env` to
> let `~/.crossenv` control it.

## Error Handling Convention
All API errors go through `ai_error_handler.handle_api_error()`. It distinguishes quota/billing errors (permanent — exit) from rate-limit/503 errors (transient — retry). Import from `ai_error_handler` rather than catching raw exceptions per-script.

## Lazy-Import Convention (optional heavy dependencies)

Some `st-*` scripts lazy-import optional libraries so the base `cross-st` install stays lightweight. The guiding principle is **zero friction for the user** — if a feature needs an extra package, install it automatically on first use rather than throwing an error and asking the user to run a separate command.

### Policy: auto-install on first use

Any optional Python package that is **fully self-contained** (install it → feature works immediately) must use the auto-install pattern:

```python
try:
    import some_package
except ImportError:
    print("  Feature X not installed — installing now (one-time, ~N MB)…", flush=True)
    import subprocess as _sp
    result = _sp.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "some_package"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("Error: auto-install failed.")
        print(result.stderr[-400:].strip() if result.stderr else "(no output)")
        sys.exit(1)
    import some_package  # noqa: F811
    print("  Feature X installed. ✓", flush=True)
```

**Why `sys.executable -m pip install`?** It always targets the correct environment — pipx venv, regular venv, system Python — with no environment detection needed. The package persists; subsequent runs import it directly at zero cost.

**When NOT to auto-install:**
- **TTS** (`yakyak`, etc.) — requires a running Wyoming Piper server; auto-installing the Python package alone leaves a broken experience. Use the `[tts]` extras pattern with a clear error pointing to setup docs.
- **Native OS libraries** (Pango/GObject for WeasyPrint) — `pip install` cannot provide these; platform-specific OS hints are the only option.
- **Module-level imports** — auto-install requires the import to be inside a function so it can be retried after install.

**Size communication rule:** If the install will take more than a few seconds (anything over ~5 MB), print the approximate size so the user knows what's happening:
```
  PDF support not installed — installing now (one-time, ~22 MB)…
```
Small packages (<2 MB) can use a generic message without the size.

### Current lazy-install inventory

| Script | Feature | Package(s) | Size | Treatment |
|--------|---------|-----------|------|-----------|
| `st-fetch.py` | PDF `--file` | `pymupdf4llm` (+ `pymupdf`) | ~22 MB | **Auto-install** ✅ |
| `st-fetch.py` | Web `--url` | `beautifulsoup4` | ~1 MB | **Auto-install** ✅ |
| `st-edit.py` | Browser preview | `grip` | ~2 MB | **Auto-install** ✅ |
| `st-print.py` | Markdown → PDF | `weasyprint` | core dep | Native OS libs required — platform hints |
| `st-speak.py` `st-voice.py` `st-prep.py` | TTS audio | `yakyak` + 5 others | varies | Server required — `[tts]` extras + error message |

### Rule for new optional dependencies

1. Import inside the function that needs it, inside `try/except ImportError`.
2. Apply the auto-install pattern if the package is self-contained.
3. Print the size in the "installing now" message if > ~5 MB.
4. Add a row to the inventory table above.
5. If the package has a hard external dependency (server, native libs, etc.), use the extras pattern and document the full setup path instead.

## pipx vs dev install — UX differences

This section records all known behavioural differences between a `pipx install cross-st` user install and the `pip install -e .` developer checkout. Knowing these prevents surprises when testing or writing new code.

### ✅ Handled correctly (no action needed)

| Area | pipx behaviour | dev behaviour | How it's handled |
|------|----------------|---------------|------------------|
| **Env loading (layer 2)** | Repo `.env` is **skipped** — only `~/.crossenv` and CWD `.env` apply | Repo `.env` loaded with `override=True` | `load_cross_env()` wraps layer 2 in `_in_project_venv()` guard |
| **`st-admin --upgrade`** | Runs `pipx upgrade cross-st` | Runs `git pull && pip install -e .` | `--upgrade` logic detects pipx via `pathlib.relative_to(pipx_home)` |
| **Lazy-import auto-install** | Packages auto-install into the pipx venv on first use via `sys.executable -m pip install` | Same behaviour | Works correctly in both contexts |
| **`st-admin` grip hint** | Shows `pipx inject cross-st grip` | Shows `pip install grip` | Uses existing `using_pipx` flag |
| **Data files** (`data/`, `template/`, `cross_stones/`) | Served from `site-packages/cross_st/` | Served from repo checkout | `__file__`-relative paths work correctly in both contexts because scripts are installed as `.py` files in both |
| **`st-man` source parsing** | Reads `.py` files from `site-packages/cross_st/` | Reads from repo checkout | `_HERE = dirname(__file__)` resolves correctly in both |
| **Update notice** | Compares installed version vs PyPI; shows nag if behind | Same — but local version is typically ≥ PyPI so nag is suppressed | `check_for_updates()` uses `importlib.metadata`; suppressed in non-TTY |

### ⚠️ Fixed issues (previously wrong)

| Area | Bug | Fix |
|------|-----|-----|
| **`st.py` env loading (R3)** | Had bare `load_dotenv(__file__/'.env')` without `override=True` — `~/.crossenv` silently won over repo `.env` in dev | Removed the redundant manual calls; env is already loaded by the `load_cross_env()` at line 27 |
| **`mmd_plot.py` env loading (R3)** | Same pattern — bare `load_dotenv` without `override=True` for layer 2 | Replaced with `load_cross_env()` |
| **`st-gen.py` error message** | Showed a `__file__`-relative `.env` path that doesn't exist in a pipx install | Removed from the `check_api_key` path list; only `~/.crossenv` and CWD `.env` shown |

### Developer-only behaviours (intentional, not bugs)

- **`DEFAULT_AI`, model overrides, `DISCOURSE` settings in repo `.env`** — only take effect when the dev venv is active. pipx users must put these in `~/.crossenv`.
- **`st-admin --upgrade` prints a `git pull` hint** — only in editable install mode.
- **`CROSS_NO_CACHE=1` and `XAI_MODEL=...` in repo `.env`** — same: dev-only. Document any per-project settings in `~/.crossenv` for user testing.

## Active Sprint

Sprint tracking has moved to `cross-internal/SPRINT_CURRENT.md` (private). A1–A9, B1–B5, C1, C2, C3 are complete. `cross-st 0.5.0` is live at https://pypi.org/project/cross-st/0.5.0/.

### ✅ cross-st 0.5.1 — released 2026-04-16

See `CHANGELOG.md [0.5.1]` for details. **Bug fix**: `st-admin --upgrade` install-type detection — pipx installs were falsely reported as "Editable (dev) install" when the venv had previously been set up with `--editable`. Now detects by checking whether `sys.executable` lives inside `PIPX_HOME` first; editable check only runs for non-pipx installs. Dev installs now show checkout path + `git pull` / `pip install -e .` instructions.

### ✅ cross-st 0.5.0 — released 2026-04-16

See `CHANGELOG.md [0.5.0]` for the full list. Key changes: `st-post --category reports` (DA-21), `st-speed --ai` dual behavior, progress feedback before every AI call (all tools), `st-print` WeasyPrint OSError handling, wiki 29/29 at 100%, `cross-ai-core ≥ 0.5.0` required (`process_prompt(model=)`, `<MAKE>_MODEL` env vars, `openai>=2.0.0`).

### Post-0.5.0 (unreleased, HEAD → 0.6.0)

- **DA-21** — `--category reports` added to `st-post` (id=16, "📄 Reports" — public portfolio at `crossai.dev/u/<username>/activity/topics`). The `st-admin` category quick-picker now has three named options: `1` private · `2` Test (cleared daily) · `3` 📄 Reports. `_DISCOURSE_REPORTS_CATEGORY_ID = 16` constant in `st-admin.py`.
- **`st-speed --ai` fix** — `--ai` paired with `--ai-*` content flags now selects the generation provider only; performance display always shows all providers (`display_filter=None`). `--ai` alone still filters the display as before.
- **Progress feedback** — `Generating {label} with {ai_make}…` printed before every `process_prompt()` call in `st-verdict`, `st-heatmap`, `st-analyze`, `st-merge`, `st-plot`. Completes the UX rule for all 29 tools.
- **`st-print` WeasyPrint errors** — catches `OSError` (missing native Pango/GObject libs) in addition to `ImportError`; `_print_weasyprint_install_hint()` prints platform-specific fix for macOS (`brew install pango`) and Linux (`apt-get libpango*`).
- **`docs/wiki/st-speed.md` and `docs/wiki/st-heatmap.md` are now hand-authored** — `build_wiki.py` will not overwrite them. Four hand-authored pages total: `st-domain`, `st-fix`, `st-speed`, `st-heatmap`. All other wiki pages carry the `<!-- auto-generated by build_wiki.py -->` marker and are safe to regenerate.
- **Wiki 29/29 at 100%** — all 29 `st-*` wiki pages have complete `--help` flag documentation (Part B).
- **`build_wiki.py`** — scripts path fixed (`cross_st/` post-C1); wiki links no longer append `.md` (GitHub wiki uses bare page names).
- **`cross-ai-core ≥ 0.5.0` required** — `process_prompt(model=)` per-call override; `<MAKE>_MODEL` env vars; `openai>=2.0.0`.


---

### cross-ai-core 0.5.0 is live on PyPI

`cross-st` requires `cross-ai-core>=0.5.0`. Both `pyproject.toml` and `requirements*.txt` files are updated. The local venv is running cross-ai-core 0.5.0 (editable install from `../cross-ai-core/`).

**What changed in cross-ai-core 0.5.0:**
- `process_prompt()` accepts a new `model=` keyword arg — per-call model override
- `get_ai_model(make)` now checks `<MAKE_UPPER>_MODEL` env var first (e.g. `XAI_MODEL=grok-3-latest`)
- Both resolve: explicit arg → `<MAKE_UPPER>_MODEL` env var → compiled-in handler default
- **Breaking**: `openai>=2.0.0` is now required (was `>=1.70.0`); all SDKs bumped to latest tested versions

## Key Files for Context
| File | Why It Matters |
|------|----------------|
| `cross_st/st.py` | Menu structure and `POST_CMD_REFRESH` set — **reserved keys: `A` `S` `F` cycle global AI/Story/Fact selectors at ALL menu levels; never use these as menu item keys in `st.py`** |
| `cross_st/st-admin.py` | Settings manager — `DEFAULT_AI`, model overrides, TTS voice, editor, `--init-templates`; `--overwrite-templates` replaces existing template files |
| `cross_st/st-domain.py` | Interactive wizard: create a new Cross-Stones domain prompt (Phases 2–4) |
| `cross_st/st-find.py` | Keyword search: `parse_boolean_pattern()` handles `+required ^excluded` operators; `wildcard_to_regex()` expands `*`/`?`; searches titles, prompts, and story text |
| `cross_st/ai_handler.py` | Compatibility shim → `cross_ai_core.ai_handler`; exposes `process_prompt`, `get_default_ai`, `get_content_auto`, `put_content_auto`, etc. |
| `cross_st/base_handler.py` | Compatibility shim → `cross_ai_core.ai_base.BaseAIHandler` |
| `cross_st/ai_url.py` | X/Twitter fetch handler for `st-fetch`; uses `AI_MAKE="url"`, not registered in `AI_HANDLER_REGISTRY` |
| `cross_st/mmd_startup.py` | `require_config()` — first-run guard; called near top of every `st-*.py` except `st-admin` and `st-man`; `load_cross_env()` calls `check_for_updates()` automatically (TTY-only nag, max once/24 h, cached in `~/.cross_api_cache/update_check.json`) |
| `cross_st/mmd_util.py` | `tmp/` path helpers, block file protocol, `build_segments()` for fact-check units |
| `cross_st/mmd_process_report.py` | Text pipeline helpers: `remove_markdown`, `extract_title`, `get_hashtags`, `clean_for_platform` |
| `cross_st/mmd_data_analysis.py` | `get_flattened_fc_data()` — flattens fact[] into a DataFrame used by heatmap/verdict/analyze |
| `cross_st/commands.py` | Entry-point dispatch: `runpy.run_path()` wrappers for every `st-*.py`; inserts `cross_st/` onto `sys.path`; target of `pyproject.toml [project.scripts]` |
| `pyproject.toml` | Package metadata, `[project.scripts]` entry points (`cross_st.commands:*`), optional `[tts]` extras, package data declarations |
| `cross_st/st-stones.py` | Cross-Stones scoring: `compute_domain_scores()`, `compute_cross_stone_scores()` |
| `cross_st/st-speed.py` | AI performance/speed analysis. **`--ai` dual behavior (post-0.4.0):** when paired with an `--ai-*` content flag, `--ai` selects which provider *generates the content* but the performance table always shows all providers (`display_filter=None`). Without any `--ai-*` flag, `--ai` filters the display to one provider as before. |
| `cross_st/st-print.py` | PDF export: Markdown → HTML → PDF via WeasyPrint; `--save-pdf` / `--output` / `--preview` / `--printer`; catches `OSError` (missing native Pango/GObject libs) with platform-specific install hints |
| `README_stones.md` | Cross-Stones benchmark documentation: scoring formula, historical tracking, domain table |
| `cross_st/cross_stones/cross-stones-10.json` | Named benchmark set: locked `n_claims`, `max_fact_score`, domain list |
| `cross_st/template/default.prompt` | Baseline prompt template (1200–1500 word Markdown report); add files here for `st-new --template` |
| `tests/fixtures/pizza_dough.json` | Canonical example of a populated container |
| `docs/wiki/` | GitHub Wiki source files; `script/build_wiki.py` auto-generates per-command pages from docstrings; `script/push_wiki.sh` publishes |

