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
cross_st/st-new.py       ← Create a new prompt from template/; opens editor; optionally launches st-bang
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
cross_st/mmd_startup.py     ← First-run detection: `require_config()` called near the top of every `st-*.py` (except `st-admin`, `st-man`)
cross_st/mmd_web_server.py  ← Candidate Markdown preview server (currently unused; candidate to replace grip)
cross_st/discourse.py       ← Discourse API client (MmdDiscourseClient wraps pydiscourse)
cross_st/commands.py        ← Entry-point dispatch for pyproject.toml; maps `st_*` functions → `st-*.py` via runpy; also inserts `cross_st/` onto sys.path
cross_st/cross_stones/                    ← Cross-Stones benchmark suite
cross_st/cross_stones/cross-stones-10.json  ← Named benchmark set: locked params (n_claims, max_fact_score)
cross_st/cross_stones/domains/            ← 10 standard domain prompts + result containers
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
All scripts load config in this 3-layer order (A1 convention):
```python
_CROSSENV = os.path.expanduser("~/.crossenv")
load_dotenv(_CROSSENV)                                    # 1. global ~/.crossenv
load_dotenv(os.path.join(_basedir, ".env"))               # 2. repo-local .env (developer keys)
load_dotenv(".env", override=True)                        # 3. CWD .env — highest priority
```
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
Tests live in `tests/` with fixtures in `tests/fixtures/` (e.g. `pizza_dough.json`). **Never call real AI APIs in tests** — use fixtures and mocks. Current test coverage is minimal; unit tests for `mmd_util.py`, `ai_handler.py`, and `mmd_data_analysis.py` are the highest-priority gaps.

Current test files: `test_mmd_process_report.py`, `test_container_loading.py`, `test_st_admin.py`, `test_st_plot.py`, `test_st_speed.py`, `test_st_stones.py`, `test_dotenv_resolution.py`, `test_tts_stack.py`, `test_cache_timing_preservation.py`, `test_cli_help.py`, `test_imports.py`, `test_st_bang.py`, `test_st_verdict.py`.

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

## Error Handling Convention
All API errors go through `ai_error_handler.handle_api_error()`. It distinguishes quota/billing errors (permanent — exit) from rate-limit/503 errors (transient — retry). Import from `ai_error_handler` rather than catching raw exceptions per-script.

## Active Sprint

Sprint tracking has moved to `cross-internal/SPRINT_CURRENT.md` (private). A1–A9, B1–B5, C1, C2, C3 are complete. `cross-st 0.2.0` is live at https://pypi.org/project/cross-st/0.2.0/.

### ⏳ Next release: cross-st 0.3.0 — ready to ship

Everything is green. **All that's needed is to update CHANGELOG and bump the version.**

**What's accumulated since 0.2.0 (tag v0.2.0):**

| Area | Change |
|------|--------|
| `st-fix` | `_save_result()` uses `put_content_auto` + `_gen_make` from `_make` stamp — fixes `KeyError: 'content'` crash in `--mode synthesize` when best-story author ≠ `--ai` |
| `st-new` | `-g` / `--gen` flag: auto-runs `st-gen` + `st-prep` after editing the prompt |
| `st-new` | `--prep` flag: auto-runs `st-prep` only after editing |
| `st-gen`, `st-merge`, `st-analyze` | `--ai-title` / `--ai-short` / `--ai-caption` / `--ai-summary` / `--ai-story` flags; AI-caption expansion |
| `st-admin` | `--version` flag; version line in `--show` output |
| `ai_handler` shim | Exports `get_content_auto`, `put_content_auto` (required by `st-fix`) |
| Dependencies | `cross-ai-core>=0.5.0` (model env vars, `model=` per-call arg, openai 2.x) |
| Dependencies | `openai==2.31.0`, `anthropic==0.92.0`, `google-genai==1.71.0` |
| Tests | 45 new tests in `test_ai_options.py`; CI fix (`require_config` patched in `TestMainCLI`) |
| Docs/Wiki | `st-domain.md` rewrite + SVG flow diagram; `st-fix.md` user walkthrough |

**Pre-publish checklist:**
```bash
# 1. Update CHANGELOG.md — add [0.3.0] section summarising the table above
# 2. Bump version in pyproject.toml: 0.2.0 → 0.3.0
# 3. Full test suite
pytest                         # must be 0 failures
bash script/smoke_test.sh      # optional but recommended
# 4. Push any unpushed commits
git push
# 5. Build + check
rm -rf dist/ && python -m build && twine check dist/*
# 6. Publish
twine upload dist/*
# 7. Tag
git tag v0.3.0 && git push --tags
```

**No blockers.** cross-ai-core 0.5.0 is live on PyPI; all 456 cross-st tests pass.

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
| `cross_st/st.py` | Menu structure and `POST_CMD_REFRESH` set |
| `cross_st/st-admin.py` | Settings manager — `DEFAULT_AI`, model overrides, TTS voice, editor, `--init-templates`; `--overwrite-templates` replaces existing template files |
| `cross_st/st-domain.py` | Interactive wizard: create a new Cross-Stones domain prompt (Phases 2–4) |
| `cross_st/st-find.py` | Keyword search: `parse_boolean_pattern()` handles `+required ^excluded` operators; `wildcard_to_regex()` expands `*`/`?`; searches titles, prompts, and story text |
| `cross_st/ai_handler.py` | Compatibility shim → `cross_ai_core.ai_handler`; exposes `process_prompt`, `get_default_ai`, `get_content_auto`, `put_content_auto`, etc. |
| `cross_st/base_handler.py` | Compatibility shim → `cross_ai_core.ai_base.BaseAIHandler` |
| `cross_st/ai_url.py` | X/Twitter fetch handler for `st-fetch`; uses `AI_MAKE="url"`, not registered in `AI_HANDLER_REGISTRY` |
| `cross_st/mmd_startup.py` | `require_config()` — first-run guard; called near top of every `st-*.py` except `st-admin` and `st-man` |
| `cross_st/mmd_util.py` | `tmp/` path helpers, block file protocol, `build_segments()` for fact-check units |
| `cross_st/mmd_process_report.py` | Text pipeline helpers: `remove_markdown`, `extract_title`, `get_hashtags`, `clean_for_platform` |
| `cross_st/mmd_data_analysis.py` | `get_flattened_fc_data()` — flattens fact[] into a DataFrame used by heatmap/verdict/analyze |
| `cross_st/commands.py` | Entry-point dispatch: `runpy.run_path()` wrappers for every `st-*.py`; inserts `cross_st/` onto `sys.path`; target of `pyproject.toml [project.scripts]` |
| `pyproject.toml` | Package metadata, `[project.scripts]` entry points (`cross_st.commands:*`), optional `[tts]` extras, package data declarations |
| `cross_st/st-stones.py` | Cross-Stones scoring: `compute_domain_scores()`, `compute_cross_stone_scores()` |
| `cross_st/st-print.py` | PDF export: Markdown → HTML → PDF via WeasyPrint; `--save-pdf` / `--output` / `--preview` / `--printer` |
| `README_stones.md` | Cross-Stones benchmark documentation: scoring formula, historical tracking, domain table |
| `cross_st/cross_stones/cross-stones-10.json` | Named benchmark set: locked `n_claims`, `max_fact_score`, domain list |
| `cross_st/template/default.prompt` | Baseline prompt template (1200–1500 word Markdown report); add files here for `st-new --template` |
| `tests/fixtures/pizza_dough.json` | Canonical example of a populated container |
| `docs/wiki/` | GitHub Wiki source files; `script/build_wiki.py` auto-generates per-command pages from docstrings; `script/push_wiki.sh` publishes |

