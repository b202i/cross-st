# Agents

An **agent** in cross-st is a short, named (provider, model) pair you can pass to any tool with `--agent`. It is the user-facing replacement for the older `--ai <provider>` flag (cross-st 0.10.0+).

```text
agent name      = anthropic-opus
provider (make) = anthropic
model           = claude-opus-4-5
```

## Why agents?

Before 0.10.0, `--ai anthropic` resolved through a built-in handler default — you had no control over *which* Anthropic model. Agents make the (provider, model) pair first-class: every agent has a name, an explicit model id, and lives in `~/.cross_ai_models.json`.

Common patterns:

| Agent name | Use when… |
|---|---|
| `anthropic-opus` | You want Anthropic's highest-quality model |
| `anthropic-sonnet` | You want Anthropic's balanced/cheaper model |
| `anthropic-haiku` | You want fast/cheap Anthropic |
| `quick` | A personal name pointing at any cheap model |
| `deep` | A personal name pointing at any flagship |
| `vision` | A personal name pointing at a multimodal model |

## Naming rules

- Lowercase letters, digits, and dashes only.
- Cannot start with a digit.
- Cannot collide with a built-in provider name (`anthropic`, `openai`, `xai`, `gemini`, `perplexity`) **unless** it points at the same provider with no explicit model — those names are reserved as auto-seeded "starter" agents.

## Resolution order

When you pass `--agent NAME`:

1. **Exact match** in the agent registry (`~/.cross_ai_models.json` plus any auto-seeded starter agents).
2. **Provider name** with an agent of the same name (e.g. `--agent anthropic` → the auto-seeded `anthropic` starter agent).
3. **Did-you-mean** suggestion: cross-st prints close matches and exits non-zero.

```text
$ st-gen --agent antropic-opus prompt.txt
Error: unknown agent 'antropic-opus'.
Did you mean: anthropic-opus, anthropic-sonnet, anthropic?
```

## Default agent

Set the default with `st-admin --set-default-ai NAME` (the env var written is `DEFAULT_AGENT`). All `st-*` tools fall back to this when `--agent` is omitted.

```text
~/.crossenv:
  DEFAULT_AGENT='gemini'
```

For backward compatibility, cross-ai-core 0.8.0+ also reads the legacy `DEFAULT_AI` if `DEFAULT_AGENT` is unset, so users upgrading from 0.9.x do not need to re-run `st-admin --setup`.

## Worked examples

### A. Two Anthropic models in the same matrix

```bash
st-admin --add-agent anthropic-opus=anthropic:claude-opus-4-5
st-admin --add-agent anthropic-sonnet=anthropic:claude-sonnet-4-5
st-cross prompt.txt   # matrix now includes both as separate columns
```

### B. Personal "quick / deep" pair

```bash
st-admin --add-agent quick=gemini:gemini-2.5-flash
st-admin --add-agent deep=anthropic:claude-opus-4-5

st-gen --agent quick blog.prompt   # cheap first draft
st-fix --agent deep  blog.json     # high-quality rewrite
```

### C. Listing what's configured

```bash
st-admin --list-agents
```

Or interactively: `st-admin` → `a` → `M`.

### D. Switching the default

```bash
st-admin --set-default-ai deep
st-gen blog.prompt    # uses 'deep' (no --agent needed)
```

## How migration works

On first run after upgrading to 0.10.0:

- If `~/.cross_ai_models.json` already exists in the legacy v1 shape, it is upgraded in-place to the v2 envelope. **No agent names change.**
- If the file is absent and you have API keys configured, one starter agent per provider is seeded (e.g. `gemini`, `anthropic`, `openai`) pointing at that provider's recommended model.
- If neither file nor keys exist, no file is written — run `st-admin --setup` to configure keys first.

A one-line notice prints during startup so you know what happened. The migration is idempotent — subsequent startups are a fast no-op.

## See also

- [st-admin](st-admin) — interactive agent management UI (`a` → `m` → `a/r/e/R`)
- [Multi-Model](Multi-Model) — running matrices across multiple agents
- [ai-providers](ai-providers) — vocabulary: provider vs model vs agent

