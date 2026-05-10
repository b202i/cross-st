# AI Providers

Cross supports five AI providers simultaneously. Each brings different strengths, pricing models, and rate limits. This page helps you choose the right provider for each task and shows how to override the default model for any provider.

For first-time setup (getting API keys, running `st-admin --setup`), see [Onboarding](Onboarding.md).

> **Multi-model:** since `cross-st 0.9.0` you can also run **more than one model per provider** in the same matrix (e.g. `anthropic-opus` and `anthropic-sonnet` competing side-by-side). See **[Multi-Model](Multi-Model)** for the agent file format.

---

## Quick-pick guide

| Provider | Best for | Free tier | Cost |
|----------|----------|-----------|------|
| **Gemini** | Daily use, long prompts, getting started | ✅ Yes | Free / pay-as-you-go |
| **xAI (Grok)** | Current events, X/Twitter context | ⚠️ Limited credits | Pay-as-you-go |
| **Anthropic (Claude)** | Long careful reasoning, writing quality | ❌ No | Pay-per-token |
| **OpenAI (GPT)** | Broad general knowledge, reliable baseline | ❌ No | Pay-per-token |
| **Perplexity (Sonar)** | Live web search with citations | ❌ No | Subscription or credits |

**Run all five at once** with `st-bang` or `st-cross` — that's the point of Cross.  
Use the quick-pick above when you want a single provider for a quick job.

---

## Gemini — `gemini`

**Key:** `GEMINI_API_KEY` · **Default model:** `gemini-2.5-flash`  
**Get a key:** [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) — free, no credit card

The only provider with a genuinely free API tier. Recommended as the default for new users and for exploratory work.

**Free tier limits:** 15 req/min · 1,500 req/day · 1M tokens/day — comfortably covers normal Cross usage.

**Strengths for Cross:**
- 1M token context window — handles very long cross-product payloads without truncation
- Fast on `gemini-2.5-flash`; step up to `gemini-2.5-pro` for more careful reasoning
- Reliable JSON and structured output; low hallucination rate on factual domains

**Notes:** Gemini responses occasionally include safety refusals on politically sensitive topics. If a domain prompt triggers one, try rephrasing or use a different provider as primary.

---

## xAI — `xai`

**Key:** `XAI_API_KEY` · **Default model:** `grok-4-1-fast-reasoning`  
**Get a key:** [console.x.ai](https://console.x.ai)

Grok is trained on X/Twitter data in addition to web text, giving it stronger awareness of recent public discourse and named individuals active on social media.

**Strengths for Cross:**
- Often more opinionated and willing to make direct claims — which scores well in fact-checking when the claims are verifiable
- Strong on current-events and technology domains
- `grok-4-1-fast-reasoning` is among the fastest models Cross uses; good speed scores on benchmarks

**Notes:** Free credits for new accounts burn quickly with Cross's multi-call pattern. Set a spending limit in the xAI console.

---

## Anthropic — `anthropic`

**Key:** `ANTHROPIC_API_KEY` · **Default model:** `claude-opus-4-5`  
**Get a key:** [console.anthropic.com](https://console.anthropic.com) — credit card required

Claude is known for long, structured, carefully hedged writing. Reports tend to be well-organized with clear claim structure, which helps fact-checkers parse them.

**Strengths for Cross:**
- Highest-quality prose in `synthesize` and `quality` merge modes (`st-merge`, `st-fix`)
- Excellent at following the Cross prompt format precisely — outputs clean segmented reports
- Lower tendency toward confident false statements than some other models

**Notes:** Claude tends to qualify claims heavily. This can reduce fact-check scores on domains where peer AIs penalize hedged language as "Partially True." `claude-opus-4-5` is the most capable but also the most expensive per token.

---

## OpenAI — `openai`

**Key:** `OPENAI_API_KEY` · **Default model:** `gpt-4o`  
**Get a key:** [platform.openai.com](https://platform.openai.com) — credit card required

GPT-4o is a reliable, well-rounded model. It tends to produce consistent, predictable output — useful as a stable baseline in benchmarks.

**Strengths for Cross:**
- Stable output format makes it reliable for Cross's fact-check parsing pipeline
- Strong performance across most Cross-Stones domains
- `gpt-4o` has a 128K token context window — large enough for all Cross payloads

**Notes:** OpenAI's free tier was removed — a small prepaid credit is required. The API can be slower than Gemini or xAI under load; this shows up in speed scores.

---

## Perplexity — `perplexity`

**Key:** `PERPLEXITY_API_KEY` · **Default model:** `sonar-pro`  
**Get a key:** [perplexity.ai/settings/api](https://www.perplexity.ai/settings/api) — paid plan or API credits

Perplexity's Sonar models do **live web search** with citations before generating a response. This makes them uniquely suited to current-events topics where training data cut-offs matter.

**Strengths for Cross:**
- Grounded responses — citations reduce hallucination on time-sensitive claims
- Excellent on research and Q&A domains (`research_qa` benchmark)
- Naturally produces claim-level structure that works well with `st-fact`

**Notes:** Response times are higher than other providers because each call includes a search step. This shows in speed scores. The citation URLs in the output are preserved in the Cross container but not rendered in the Discourse post.

---

## Overriding the default model

Each provider has a compiled-in default model. To switch to a different model for a provider:

```bash
# Set a model override (persisted to .ai_models in the repo root)
st-admin --set-ai-model anthropic=claude-sonnet-4-5

# View all active models
st-admin --show

# Override for a single command only
st-gen --agent anthropic --model claude-sonnet-4-5 my_topic.prompt
```

Model overrides are stored in `.ai_models` (one `provider=model` line per entry). This file is git-ignored — safe for developer-specific settings.

---

## Using multiple providers

Every command that takes `--agent` also accepts `all`:

```bash
st-gen --agent all my_topic.prompt       # generate once per provider (sequential)
st-bang my_topic.prompt               # generate all providers in parallel (faster)
st-fact --agent all my_topic.json        # fact-check with every provider
st-cross my_topic.json                # full N×N pipeline: generate + fact-check
```

**Related:** [Onboarding](Onboarding.md) · [st-admin](st-admin.md) · [st-bang](st-bang.md) · [st-cross](st-cross.md) · [Cross-Stones](cross-stones.md)

