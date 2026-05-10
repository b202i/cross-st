# Multi-Model — running more than one model per provider

*New in `cross-st 0.9.0` (paired with `cross-ai-core 0.7.0`).*

By default Cross runs **one model per provider** — `anthropic` means whichever
Claude model the handler defaults to, `openai` means the default GPT model,
and so on. Agents let you run **more than one model from the same provider
side-by-side** in a single matrix — for example `anthropic-opus` *and*
`anthropic-sonnet` both competing in the same `st-cross` run.

Agents are **opt-in and additive**. If you do nothing, every command works
exactly as before. The moment you add a `~/.cross_ai_models.json` file, the
new agent names become available everywhere `--agent` is accepted.

---

## Quick example

```jsonc
// ~/.cross_ai_models.json
{
  "anthropic-opus":   { "make": "anthropic", "model": "claude-opus-4-5" },
  "anthropic-sonnet": { "make": "anthropic", "model": "claude-sonnet-4-5" },
  "openai":           { "make": "openai",    "model": null },
  "xai":              { "make": "xai",       "model": null },
  "perplexity":       { "make": "perplexity","model": null },
  "gemini":           { "make": "gemini",    "model": null }
}
```

```bash
st-gen --agent anthropic-opus    prompt.json   # writes one Anthropic story
st-gen --agent anthropic-sonnet  prompt.json   # writes a second Anthropic story

st-cross prompt.json
# 6 authors  6 evaluators = 36 fact-check cells
# Both Anthropic rows share one rate-limit semaphore (no 429 storms)

st-verdict prompt.json
# Bar chart shows 6 bars; score_authors() ranks Opus and Sonnet separately
```

The container's `data[]` and `fact[]` entries already carry both `make` and
`model` fields, so no schema migration is required — old reports keep working
byte-for-byte.

---

## File format — `~/.cross_ai_models.json`

| Field   | Required | Notes |
|---------|----------|-------|
| `make`  | yes      | One of the built-in providers — `anthropic`, `gemini`, `openai`, `perplexity`, `xai` |
| `model` | optional | Provider-specific model id (e.g. `claude-opus-4-5`, `gpt-4o-mini`); `null` = use the handler default |

Rules:

- **Each top-level key is the agent name** you use with `--agent`.
- **No auto-seed (since cross-ai-core 0.8.0 / cross-st 0.10.0).** The five
  built-in make names (`anthropic`, `gemini`, `openai`, `perplexity`, `xai`)
  are *not* available as agents unless an explicit entry exists. The AGT-2
  first-run migration creates one starter entry per detected API key (e.g.
  `{"anthropic": {"make": "anthropic", "model": null}}`); after that the
  file is the single source of truth.
- **Collision rule:** an agent whose name shadows a built-in make must
  resolve to that same make (the `model` field can change). Pointing agent
  `anthropic` at `{ "make": "openai", ... }` raises `ValueError` at load
  time.
- **Order matters for menus.** `get_ai_list()` returns agents in JSON
  declaration order; `st.py`'s `A` rotation cycles through them in that
  order.

Override the file path with the `CROSS_AI_AGENTS_FILE` environment variable
(useful for tests and isolated experiments). The legacy
`CROSS_AI_ALIASES_FILE` is no longer honoured as of cross-st 0.11.0.

---

## Resolution order for `--agent <agent> --model …`

When `cross-ai-core` resolves which model string to send to the provider,
it walks this chain (first hit wins):

1. Explicit `model=…` keyword arg passed to `process_prompt()` (library
   callers only — no CLI flag yet).
2. `<ALIAS_UPPER>_MODEL` env var — e.g. `ANTHROPIC_OPUS_MODEL=claude-opus-4-5`.
3. `<MAKE_UPPER>_MODEL` env var — legacy 0.5.0 form, still honoured.
4. The `model` field from `~/.cross_ai_models.json`.
5. The handler's compiled-in default.

This means you can use the agent *file* as the source of truth, but still
override on a per-shell basis with `ANTHROPIC_OPUS_MODEL=claude-opus-5-something
st-cross …` when a new flagship drops.

---

## What changed in each tool

| Tool            | Behaviour with agents |
|-----------------|------------------------|
| `st-cross`      | Matrix iterates agents; same-make agents share **one** rate-limit semaphore so concurrency caps don't double up. Resume works per-(make, model) cell. |
| `st-fix`        | When `--agent` is omitted, the rewriter defaults to the agent whose (make, model) matches the source story — so an Opus-authored story is rewritten by Opus, not by the bare `anthropic` handler default. |
| `st-speed`      | Adds one row per agent when same-make agents produce distinct timing data; labels are disambiguated as `make:model` when more than one model exists for that make. |
| `st-verdict`    | Chart and `score_authors()` rank each agent as a separate author. Composite scoring is per-(make, model). |
| `st-gen`, `st-bang`, `st-fact`, `st-analyze`, `st-merge`, `st-stones`, etc. | `--agent <agent>` accepted everywhere; argparse `choices=` widens to whatever agents you've defined. |
| `st.py`         | The `A` reserved key cycles through agents (not raw makes). The list grows by however many agents you've added. |

---

## Stamping — `_alias`, `_model`, `_make`

`process_prompt()` stamps three fields on every response it returns
in-memory:

| Field    | Value |
|----------|-------|
| `_make`  | The resolved provider, e.g. `"anthropic"` |
| `_model` | The resolved model string, e.g. `"claude-opus-4-5"` |
| `_alias` | The agent used in the call, e.g. `"anthropic-opus"` |

Cached responses **loaded from disk** carry `_make` and `_model` stamped at
read time but **not** `_alias` (the cache key is content-only). When you
need to dispatch on the make of a fresh-or-cached response, use
`get_content_auto(response)` which reads `_make` only.

---

## Rate-limit shared semaphore — why it matters

Every provider has a per-account concurrency cap (e.g. Anthropic ≈ 2,
xAI ≈ 4). If two agents pointed at the same provider each got their *own*
semaphore, you'd overshoot the cap and trigger 429 storms.

`cross-ai-core 0.7.0` exports `get_rate_limit_group(agent)` which returns
the **resolved make** as the group key — `st-cross._get_provider_semaphore`
keys on that, so `anthropic-opus` and `anthropic-sonnet` *share* one
semaphore and run within the same effective cap. You can still override the
cap globally with `--max-concurrency N` or per-process with
`CROSS_MAX_CONCURRENCY`.

---

## Migration from `.ai_models` (legacy)

Pre-0.9.0 dev installs may have a `.ai_models` file at the repo root with
lines like `xai=grok-3`. That file is honoured for one more release for
backward compatibility, but the agent JSON is now the canonical place.
Hand-migrate by adding the equivalent agent:

```jsonc
// before:  .ai_models contains  xai=grok-3
// after:   ~/.cross_ai_models.json contains
{
  "xai": { "make": "xai", "model": "grok-3" }
}
```

A future `st-admin --models` wizard will write this file directly. For now,
edit it by hand — it's small and stable.

---

## Troubleshooting

**`ValueError: Unsupported AI: anthropic-opuss. Did you mean 'anthropic-opus'?`**
You typo'd the agent name. The library's `did_you_mean()` helper suggests
the closest match; fix the agent and re-run.

**`ValueError: Agent 'anthropic' resolves to make 'openai' which conflicts …`**
You tried to redefine a built-in make agent to point at a different
provider. Pick a different agent name (e.g. `claude-via-openai`).

**Agents not picked up.** Confirm the JSON file parses:
```bash
python -c "import json; print(json.load(open('$HOME/.cross_ai_models.json')))"
```
The library logs a one-line warning at first import if the file is
malformed; check with `python -c "from cross_ai_core import get_alias_load_error; print(get_alias_load_error())"`.

**Cache misses after adding an agent.** Caches are content-keyed and ignore
the agent name, so an agent rename does **not** invalidate cache. But if
you change the *model* a cache entry was generated against, you'll get a
miss — use `st-admin --cache-cull 0` to start fresh, or `--no-cache` for a
one-off bypass.

---

## See also

- [st-cross](st-cross) — full pipeline that benefits most from agents
- [ai-providers](ai-providers) — per-provider strengths and per-make `<MAKE>_MODEL` env var docs
- [Container-Format](Container-Format) — how `make` and `model` are stored on each entry
- `cross-ai-core` [CHANGELOG `[0.7.0]`](https://github.com/b202i/cross-ai-core/blob/master/CHANGELOG.md) — library-level details

