# Cross-Stone Domain Prompt Creation — Process & Tools

This document describes exactly how the 10 benchmark domain prompts were
created for Cross-Stones. It is written so that a human or AI can repeat,
extend, or replace the process at any future date.

**Outputs of this process**

| Artifact | Location |
|----------|----------|
| Domain source research | `st-stones/domain_examples_openai.md`, `st-stones/domain_examples_xai.md` |
| Merged domain table | `st-stones/initial_stones_domains.md` |
| Prompt files (internal / archive) | `st-stones/template/*.prompt` |
| Prompt files (live benchmark) | `cross/cross_stones/*.prompt` |

---

## Why Domain Prompts Exist

Cross-Stones evaluates AI models by having them generate factual reports and
then fact-check each other's reports across a consistent set of topics.
For scores to be meaningful and comparable over time:

- Every model must receive **exactly the same prompt**.
- Prompts must be **domain-neutral** — no topic should structurally favour a
  model trained heavily on that domain's corpus.
- Claims must be **verifiable** — fact-checking only produces signal if a
  claim can be resolved to True/False by a third party with reasonable effort.
- Difficulty must be **calibrated** — all-easy or all-hard prompts compress
  the score distribution and reduce discrimination between models.

---

## Phase 1 — Identify Candidate Domains

The goal is to build a longlist of domains that reflect real-world AI use,
so that benchmark scores are meaningful to actual users of the tool.

### 1.1 Query multiple AI providers

Ask at least two independent AI models the same domain-discovery question.
Querying different providers catches any single model's blind spots and
surfaces a broader picture of what the field considers important.

**The exact prompt used (March 2026):**

```
What are the 10 most popular use cases or domains for using AI?
Such as computer programming, business decision making, medical analysis, etc.
Can you make a table with your results?
Popular might mean number of users, or dollars invested?
```

This query was sent to **OpenAI (GPT-4o)** and **xAI (Grok)**.
The full responses are preserved verbatim in:
- [`domain_examples_openai.md`](domain_examples_openai.md)
- [`domain_examples_xai.md`](domain_examples_xai.md)

When repeating this step, save the raw AI response (including the full table
and any explanatory notes) verbatim into a new `domain_examples_<provider>.md`
file. Do not edit or summarise — the raw response is the audit trail.

### 1.2 What to look for in the responses

A good domain-discovery response should rank domains by a *composite* signal,
not a single metric. The xAI response, for example, cited enterprise adoption
rates, market investment/spending, CAGR, and user reach simultaneously.
Prefer responses that:

- Name specific tools, companies, or statistics (not just vague categories)
- Distinguish between consumer volume and enterprise dollar spend
- Acknowledge that rankings shift depending on the metric chosen

If a response only ranks by one dimension (e.g., "most hyped"), repeat the
query with a more specific instruction, or weight that source less heavily
when merging.

---

## Phase 2 — Merge and Select 10 Domains

### 2.1 Identify overlaps

Lay the two (or more) ranked lists side by side and group entries that
describe the same domain even if the names differ:

| OpenAI name | xAI name | Consolidated name |
|-------------|----------|-------------------|
| Software engineering / programming | Software Development / Computer Programming | Software Development & Programming |
| Customer support / service operations | Customer Service & Support Automation | Customer Service & Support |
| Marketing / sales | Marketing & Content Creation | Marketing & Content Creation |
| Education / tutoring / training | Education & Personalized Learning | Education & Learning |
| Data analysis / reporting | Knowledge Management / Data Analytics & Insights | Data Analytics & Business Intelligence |

Overlapping domains are the strongest candidates — both models independently
identified them as high-impact.

### 2.2 Apply the selection criteria

From the remaining unique entries, select additional domains using these tests:

| Criterion | Question to ask |
|-----------|----------------|
| **Measurability** | Can claims in this domain be resolved True/False with publicly available data? |
| **Breadth** | Does this domain serve a meaningfully different user population than what is already included? |
| **Stability** | Is this domain established enough that primary sources exist (not just hype-cycle press)? |
| **Verifiability pace** | Will claims still be checkable in 6-12 months, or does this domain move too fast? |
| **User relevance** | Do typical `cross` users work in or care about this domain? |

Domains that score well on all five tests should be preferred. Niche or
fast-moving domains (e.g., Supply Chain AI, Retail Personalisation) may be
legitimate but are harder to fact-check reliably — save them for expansion.

### 2.3 Reach exactly 10

The current set uses:
- **5 overlapping domains** (both providers agreed) — automatically included
- **2 from xAI only** — Healthcare, Finance (high investment, verifiable regulatory data)
- **3 from OpenAI only** — Writing/Editing, Research/Q&A, Creative Media
  (broadest consumer use, established benchmarks, rapidly evolving policy landscape)

If you are refreshing the domain set, aim for a similar balance:
- Keep any domain still in the top-10 of both providers
- Replace any domain that has dropped off both providers' lists
- Record the final selection in `initial_stones_domains.md` with the **Sources**
  column populated as `Both`, `<provider-name>`, or `Manual`

---

## Phase 3 — Write the Prompt Files

Each domain requires one `.prompt` file. All 10 current prompts follow an
identical structural template.

### 3.1 Prompt template

```
# Cross-Stone Benchmark Prompt -- <Domain Name>

Write exactly 10 specific, fact-checkable claims about <topic description>
as of <year range>.

Each claim must be a clear, declarative statement that a well-informed analyst
could verify -- using publicly available sources such as <source types> -- as
True, Partially True, Opinion, Partially False, or False.

Difficulty calibration: Approximately half of the claims should be verifiable
with basic research (widely reported statistics or named platforms), and half
should require consulting primary sources, empirical studies, or detailed
<domain-specific> data published in <recent year range>.

Claims must not be vague generalizations. Each claim should include specific
data points, named <tools/platforms/systems>, percentages, <domain-specific
metrics>, or named organizations where relevant.

Distribute your 10 claims across the following aspects:
- <aspect 1>
- <aspect 2>
- <aspect 3>
- <aspect 4>
- <aspect 5>

Format: Return a numbered list of exactly 10 claims with no introductory text,
section headers, summaries, or commentary.
```

### 3.2 Filling in the template

**`<topic description>`** — be specific. `"AI in healthcare, medical
diagnostics, and clinical decision support"` is better than `"AI in healthcare"`
because it sets scope and prevents the AI from filling claims with
administrative trivia.

**`<source types>`** — tailor to the domain. Examples:

| Domain type | Suggested source list |
|-------------|----------------------|
| Regulated / clinical | peer-reviewed journals, FDA databases, hospital system reports, or reputable health news outlets |
| Technology | vendor documentation, benchmark leaderboards, academic papers, or reputable technology news outlets |
| Financial | regulatory filings, industry surveys, academic research, or reputable financial news outlets |
| Consumer / general | usage reports, academic benchmarks, organizational policies, or reputable news outlets |

**`<year range>`** — always specify a concrete recent window (e.g., `2025-2026`)
so the AI does not draw on outdated statistics. Update this when refreshing prompts.

**Difficulty calibration sentence** — keep it word-for-word. The 50/50 split
between basic and primary-source research is the mechanism that prevents score
compression. Do not change the ratio without re-validating the scoring distribution.

**Five aspects** — choose aspects that together span the domain without
redundancy. A proven pattern:

1. **Adoption / market data** — quantitative, named surveys or reports
2. **Performance / quality benchmarks** — empirical, named metrics (sensitivity, AUC, CSAT, etc.)
3. **Leading tools / named systems** — specific product names and versions
4. **Regulatory / ethical / policy landscape** — verifiable public record (laws, guidelines, cases)
5. **Limitations / failure modes / open problems** — honest, critical framing

If your domain does not map cleanly to this pattern, substitute aspects that
satisfy the same goal: some claims from hard data, some from specific named
sources, some from the critical or sceptical literature.

**Format instruction** — always end with the exact sentence:

```
Format: Return a numbered list of exactly 10 claims with no introductory text,
section headers, summaries, or commentary.
```

This prevents the AI from padding the output with preamble that the
fact-checker will parse as claims.

### 3.3 Generating the five aspects using AI

If you are unsure what the five aspects for a new domain should cover, ask
an AI:

```
I am writing a benchmark prompt for evaluating AI models on the domain of
<domain name>. The prompt asks the AI to generate 10 specific, fact-checkable
claims about the state of AI in this domain.

Suggest 5 distinct sub-aspects of this domain that together provide broad
coverage, where each aspect could generate 1-2 verifiable, data-rich claims.
Aspects should span: adoption data, performance benchmarks, named tools,
regulatory/ethical issues, and known limitations.
```

Review the suggestions, consolidate or replace any that overlap, and write
the final five into the prompt.

### 3.4 Naming convention

```
<snake_case_domain_name>.prompt
```

Examples: `software_development.prompt`, `healthcare_medical.prompt`

Use underscores, all lowercase, no spaces. The filename without the `.prompt`
extension becomes the JSON container name when running `st-cross`
(e.g., `st-cross cross_stones/healthcare_medical.json`).

### 3.5 Where to save

Save copies in **both** locations:

| Copy | Path | Purpose |
|------|------|---------|
| Internal / archive | `cross-internal/st-stones/template/` | Audit trail, version history |
| Live benchmark | `cross/cross_stones/` | Read by `st-cross` at runtime |

The `cross/cross_stones/` copy is what `st-cross` reads. Keep both in sync
whenever a prompt is updated.

---

## Phase 4 — Validate Each Prompt

Before running a full benchmark, smoke-test each new prompt:

1. Send the prompt to **one** AI manually (via the web UI or `st-gen`).
2. Read the 10 claims and check each one:

| Check | Pass condition |
|-------|---------------|
| Count | Exactly 10 numbered items, nothing else |
| Format | Declarative statement — not a question, bullet, or heading |
| Specificity | Contains at least one named entity, statistic, or date |
| Verifiability | A well-informed analyst could look it up with reasonable effort |
| Difficulty mix | Not all trivially easy, not all obscure or unresolvable |

3. If more than 2 claims fail any check, revise the prompt:
   - **Too vague** — add specificity to the five aspects list
   - **Too easy** — raise the bar in the difficulty calibration sentence
   - **Too hard** — broaden the source types or loosen the recency window
   - **Wrong format** — verify the format instruction is the final line

4. Once the smoke test passes, run the full `st-cross` benchmark.

---

## Phase 5 — Updating the Domain Set Over Time

Review the domain set approximately **annually**, or whenever a major shift in
AI adoption patterns is evident.

### Refreshing the discovery survey

Repeat Phase 1 with the same discovery prompt, adding a date anchor:

```
What are the 10 most popular use cases or domains for using AI as of <year>?
Such as computer programming, business decision making, medical analysis, etc.
Can you make a table with your results?
Popular might mean number of users, or dollars invested?
```

Compare the new ranked lists to `initial_stones_domains.md`. Any domain that
has dropped off both providers' top-10 is a candidate for replacement.

### Versioning

- Append a new dated section to `initial_stones_domains.md` rather than
  overwriting the previous table. This preserves score comparability across
  benchmark runs over time.
- When a prompt file changes materially, rename the old file
  `<name>_v1.prompt` before writing the new version so that historical
  benchmark results remain reproducible.
- Update the year range in all prompt files at each refresh cycle even if
  the aspects themselves do not change.

### Expanding beyond 10 domains

Add new domains by repeating Phases 2-4. The scoring formulas scale linearly.
Update the `max_fact_score` notation (currently 200 for 10 x 10 x 2) and the
domain count references in `README_cross_stones.md` and
`cross/README_stones.md`.

---

## Quick-Reference Checklist

Use this checklist each time a domain prompt is created or updated.

### Domain selection
- [ ] Discovery prompt sent to at least 2 AI providers
- [ ] Raw responses saved verbatim to `domain_examples_<provider>.md`
- [ ] Overlapping domains identified and consolidated
- [ ] Selection criteria applied: measurability, breadth, stability, verifiability pace, user relevance
- [ ] Final set recorded in `initial_stones_domains.md` with Sources and Rationale populated

### Prompt authoring
- [ ] Title: `# Cross-Stone Benchmark Prompt -- <Domain Name>`
- [ ] Year range is current
- [ ] Source types tailored to domain
- [ ] Difficulty calibration sentence unchanged from template
- [ ] Five aspects listed, covering: adoption, performance, named tools, policy/ethics, limitations
- [ ] Format instruction is the final line

### File management
- [ ] Filename: `snake_case.prompt`, lowercase, no spaces
- [ ] Saved to `cross-internal/st-stones/template/` (archive copy)
- [ ] Saved to `cross/cross_stones/` (live copy)
- [ ] Smoke test passed: one AI returned exactly 10 clean, specific, verifiable claims
- [ ] `initial_stones_domains.md` table updated
- [ ] `cross/README_stones.md` domain table updated
