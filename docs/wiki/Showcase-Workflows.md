# Showcase Workflows — three things Cross does well

Three end-to-end workflows that demonstrate the full **[GATHER → VERIFY → INTERPRET](Three-Stages)** pipeline. Each workflow uses the same gather and verify steps and differs only in the [st-verdict](st-verdict) lens at the interpret step.

If you've never run Cross before, do the [Onboarding](Onboarding) first to set up your API keys.

| Workflow | Question | Lens |
|---|---|---|
| **A — "Is this fake news?"** | What's wrong with this report? | `--what-is-false` |
| **B — "What's missing?"** | What did the report fail to cover? | `--what-is-missing` |
| **C — "What can I trust here?"** | Which claims are well-supported? | `--what-is-true` |

After running any of the three, ask **[`st-verdict --how-to-fix`](st-verdict#recommendation-lens---how-to-fix)** for a concrete next-action recommendation.

---

## Workflow A — "Is this fake news?"

**Use when:** you've stumbled on a news article, a forum post, or an AI-generated report and you want to know which specific claims are wrong before citing or sharing it.

```bash
# 1. GATHER — pull the article into a container, extract the prompt
st-fetch https://example.com/article-about-rv-batteries --prep

# 2. VERIFY — fact-check it with every configured AI provider
st-cross article.json

# 3. INTERPRET — focused breakdown of what is false / disputed
st-verdict -s 1 --what-is-false --ai-summary article.json
```

### Sample output

```text
$ st-verdict -s 1 --what-is-false --ai-summary article.json
  Generating Summary [false-lens] with xai…

The most critical inaccuracy in the report is the claim that annual maintenance
costs for lithium RV batteries range from $100 to $200, marked partially_false
by three of five fact-checkers (xai:grok-4-1, anthropic:claude-opus-4-5,
perplexity:sonar). This figure understates typical costs, which manufacturer
data and dealer service plans place between $300 and $700 depending on system
size and inverter integration.

Remaining false-lens claims cluster into two themes: (1) Lifecycle ratings —
the assertion that a 100 Ah lithium pack delivers "10,000+ cycles at 80%
depth-of-discharge" was rated partially_false (xai, gemini); manufacturer
specs cite 3,500–6,000 cycles for that threshold. (2) Charge-controller
compatibility — the article claimed any MPPT controller works with lithium,
which the fact-checkers flagged as misleading because absorption-voltage
profiles must be lithium-specific to avoid undercharging.

Authors and readers should verify all maintenance-cost and lifecycle figures
against current manufacturer datasheets and at least one independent installer
quote before citing this article.
```

The lens names *specific claims*, *names which fact-checkers flagged each one* (signal strength comes from agreement), *groups them into themes*, and *closes with actionable advice*. Compare with the chart-only output of plain `st-verdict article.json`, which only ranks providers.

---

## Workflow B — "What's missing?"

**Use when:** the report seems plausible but you suspect it has gaps — or you're using Cross to evaluate AI authors and want to know what each one *failed to address* relative to the prompt's intent.

```bash
# 1. GATHER (same as Workflow A)
st-fetch https://example.com/article-about-rv-batteries --prep

# 2. VERIFY (same as Workflow A)
st-cross article.json

# 3. INTERPRET — coverage-gap analysis
st-verdict -s 1 --what-is-missing --ai-summary article.json
```

### Sample output

```text
$ st-verdict -s 1 --what-is-missing --ai-summary article.json
  Generating Summary [missing-lens] with xai…

The most important omission in the report is the absence of any discussion of
warranty terms — a knowledgeable reader of the prompt "compare RV battery
options for a six-month trip" would expect to see warranty length and coverage
scope addressed because batteries are the single highest-cost failure point on
long-haul RVs and warranty claims are the primary risk-mitigation lever.

Two secondary gaps stand out. First, there is no mention of cold-weather
performance — lithium iron phosphate (LiFePO4) packs lose 20–40% of usable
capacity below 0°C and most ship without integrated heaters; for a six-month
trip this is critical. Second, the report omits any installation-cost figures
or licensed-installer requirements; readers are left to assume DIY but state
electrical codes vary on whether high-amperage inverter wiring is permitted.

To complete the report, the author should add a warranty-comparison subsection,
a cold-weather performance table, and an installation-cost / regulatory note.
```

The missing lens reads `data[0].prompt` and the report markdown together so the AI can reason about what *should* be there relative to the topic, not just what *is* there. Use this when the chart says "scores are fine" but you have a nagging sense that the report is incomplete.

---

## Workflow C — "What can I trust here?"

**Use when:** you want to extract the trustworthy core of a report — the claims that multiple fact-checkers verified — so you can confidently cite, quote, or re-publish them. The positive counterpart of Workflow A.

```bash
# 1. GATHER (same)
st-fetch https://example.com/article-about-rv-batteries --prep

# 2. VERIFY (same)
st-cross article.json

# 3. INTERPRET — focused breakdown of verified claims
st-verdict -s 1 --what-is-true --ai-caption article.json
```

### Sample output

```text
$ st-verdict -s 1 --what-is-true --ai-caption article.json
  Generating Caption [true-lens] with xai…

The article's strongest verified thread is its energy-density comparison: the
claim that LiFePO4 packs deliver roughly 90–110 Wh/kg versus 30–40 Wh/kg for
flooded lead-acid was rated true by all five fact-checkers, with three citing
the same independent industry datasheet. This is the single most citation-ready
fact in the report.

Supporting verified claims cluster around two themes: depth-of-discharge
(LiFePO4's safe ~80–95% versus lead-acid's ~50%, marked true by four checkers)
and charge efficiency (LiFePO4's ~99% Coulombic versus lead-acid's ~85%, marked
true by three). For a buyer's-guide repost, lead with the energy-density
figure and use the depth-of-discharge claim as the supporting headline; both
clear the multi-checker confidence threshold.
```

A 100–160-word caption is usually the right detail level for this lens — long enough to cite specific evidence, short enough to drop into a Discourse post or a forum reply. Use `--ai-summary` if you want a 3-paragraph technical summary instead.

---

## When to use which lens

| You want to… | Lens | Typical detail flag |
|---|---|---|
| Find errors before citing | `--what-is-false` | `--ai-summary` |
| Find coverage gaps | `--what-is-missing` | `--ai-summary` |
| Extract the trustworthy core | `--what-is-true` | `--ai-caption` |
| Decide what to do next | `--how-to-fix` | `--ai-short` (default) |
| Just see the chart | *(none — default behaviour)* | `--ai-short` (default) |

The four lenses are mutually exclusive — pick one per invocation. Run multiple in sequence to get a full picture; chaining is cheap because [st-cross](st-cross)'s fact-check results are already in the container and [st-verdict](st-verdict) only re-reads them.

**Related:** [Three Stages](Three-Stages) · [st-verdict](st-verdict) · [st-fetch](st-fetch) · [st-cross](st-cross) · [Container Format](Container-Format)

