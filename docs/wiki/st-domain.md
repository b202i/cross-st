# st-domain — Create a Cross-Stones benchmark domain prompt

Guides you through building a `.prompt` file for a new [Cross-Stones](cross-stones.md) benchmark domain. The prompt tells every AI exactly what 10 fact-checkable claims to generate — the controlled input that makes benchmark scores comparable across time.

**Related:** [st-stones](st-stones.md) · [st-cross](st-cross.md) · [Cross-Stones](cross-stones.md)

---

## Walkthrough — supply chain example

Run the wizard with no flags and answer four prompts:

```bash
st-domain
```

```
── Phase 2  —  Define the domain ─────────────────────────────────
  Domain slug  (e.g. supply_chain): supply_chain
  Display name  (e.g. Supply Chain & Logistics): Supply Chain & Logistics
  Topic description for claims
    (e.g. AI in supply chain management, logistics, and demand forecasting):
    AI in supply chain management, logistics, and demand forecasting
  Year range  [2025–2026]:          ← press Enter to accept default
  Source types  [vendor documentation, ...]:   ← press Enter to accept
```

The slug becomes the filename (`supply_chain.prompt`). The topic description is the sentence the AI uses to scope its claims — be specific.

```
── Phase 3  —  AI-suggested aspects ──────────────────────────────
  Asking gemini for aspect suggestions …

  1.  Adoption rates of AI-powered demand forecasting platforms ...
  2.  Accuracy benchmarks of AI demand sensing vs. traditional ...
  3.  Named AI platforms and tools (e.g., Blue Yonder, o9 Solutions) ...
  4.  Regulatory and ethical considerations around AI in supply chains ...
  5.  Limitations and failure modes of AI in supply chain disruptions ...

  Accept all 5 aspects?  [Y / n / e to edit each]: Y
```

The AI proposes five aspects that span adoption data, benchmarks, named tools, policy, and limitations. Press **Y** to accept, **e** to edit any individually, or **n** to rewrite all five.

The assembled prompt is shown as a preview, then saved:

```
  Save to cross_stones/domains/supply_chain.prompt?  [Y/n]: Y
  ✓  Saved: cross_stones/domains/supply_chain.prompt
```

```
── Phase 4  —  Smoke-test ─────────────────────────────────────────
  Sending prompt to gemini — expecting 10 numbered claims …

  1. Blue Yonder's Luminate Platform, used by 68% of Fortune 500 ...
  2. AI demand sensing reduced forecast error by 20–30% at Walmart ...
  ...

  ✓  Exactly 10 claims returned — format correct.
  Accept smoke-test?  [Y / n / r to retry without cache]: Y
```

The smoke-test sends your finished prompt to one AI and checks that exactly 10 numbered claims come back. If the count is wrong, the wizard tells you — edit the aspects and retry. Use **r** to force a fresh API call (bypasses cache).

At the end:

```
  ✓  Domain prompt ready: cross_stones/domains/supply_chain.prompt
     st-cross cross_stones/domains/supply_chain.json   # run the benchmark
     st-stones cross_stones/domains/                   # score this domain
```

---

## Options

| Option | Description |
|--------|-------------|
| `--name SLUG` | Pre-fill the domain slug (skips that prompt). Use `snake_case`, e.g. `supply_chain`. |
| `--dir DIR` | Output directory for the `.prompt` file (default: `cross_stones/domains`). |
| `--ai NAME` | AI provider for aspect suggestions and smoke-test (default: your configured default). |
| `--n-claims N` | Number of claims per domain (default: 10). Match the benchmark set you're adding to. |
| `--no-smoketest` | Skip Phase 4 — save the prompt without sending it to an AI first. |
| `--set CONFIG.JSON` | Register the new domain in a named benchmark set config after saving. |
| `--no-cache` | Bypass the API cache — useful when retrying a smoke-test after editing. |
| `-v` | Verbose: print raw AI responses. |

### Adding to a benchmark set

To register the new domain in the standard set so `st-stones` picks it up:

```bash
st-domain --name supply_chain --set cross_stones/cross-stones-10.json
```

This appends the domain to the `domains[]` array in the config and recomputes `n_domains` and `max_fact_score` automatically. To build a separate named set instead, point `--set` at any other config file (creating it first if needed).

---

## What's in the prompt file

The saved `.prompt` follows a fixed template — the same structure used by all 10 standard domains:

```
# Cross-Stone Benchmark Prompt — Supply Chain & Logistics

Write exactly 10 specific, fact-checkable claims about AI in supply chain
management, logistics, and demand forecasting as of 2025–2026.

Each claim must be a clear, declarative statement that a well-informed analyst
could verify — using vendor documentation, benchmark leaderboards, academic
papers, or reputable technology news outlets — as True, Partially True,
Opinion, Partially False, or False.

Difficulty calibration: Approximately half of the claims should be verifiable
with basic research, and half should require consulting primary sources ...

Distribute your 10 claims across the following aspects:
- Adoption rates of AI-powered demand forecasting platforms ...
- ...

Format: Return a numbered list of exactly 10 claims with no introductory
text, section headers, summaries, or commentary.
```

The difficulty calibration line and the format instruction are intentionally fixed — do not change them. They control the score distribution and prevent the AI from adding preamble that the fact-checker would misread as claims.
