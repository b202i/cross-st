# The Three Stages — GATHER · VERIFY · INTERPRET

Every Cross workflow belongs to exactly one of three stages. Each stage answers a categorically different question, and each tool is named for the stage it serves. Knowing which stage you're in tells you which tool to reach for next.

| Stage | Question | Tools |
|-------|----------|-------|
| **GATHER** | *Where does the content come from?* | [st-fetch](st-fetch) · [st-gen](st-gen) · [st-bang](st-bang) |
| **VERIFY** | *What are the facts?* | [st-fact](st-fact) · [st-cross](st-cross) |
| **INTERPRET** | *What do the facts mean?* | [st-verdict](st-verdict) (one report) · [st-analyze](st-analyze) (across reports) |

---

## GATHER — *Where does the content come from?*

The content is the substrate the rest of the pipeline operates on. There are three ways to get one into a `subject.json` container:

- **[st-fetch](st-fetch)** — pull external content into a container. Accepts a URL (web article), a file (PDF, Markdown, plain text), the clipboard, or a tweet. Use `--prep` to also extract the prompt so downstream stages know what topic to evaluate against.
- **[st-gen](st-gen)** — ask one AI to write a fresh report from a prompt. The simplest gather: prompt in, single-author report out.
- **[st-bang](st-bang)** — ask **N AIs in parallel** to each write a report from the same prompt. Use this when you want to compare authors before any verification — a wider sample at the GATHER stage makes the VERIFY stage more informative.

After GATHER, your container has at least one entry in `story[]` and (if you used `st-fetch --prep` or `st-gen`) a prompt in `data[0].prompt`.

---

## VERIFY — *What are the facts?*

Verification is purely a data-collection stage: each tool walks the report claim by claim and writes a structured verdict (`true` / `partially_true` / `opinion` / `partially_false` / `false`) into the `fact[]` array on each story. **It does not interpret anything.**

- **[st-fact](st-fact)** — fact-check one report with one AI. Appends one `fact[]` entry per story. The fastest path to a single second opinion.
- **[st-cross](st-cross)** — fact-check **every** report in the container with **every** AI provider configured (the full N×N cross-product matrix). Appends one `fact[]` entry per (story × checker) combination.

After VERIFY, every story has one or more `fact[]` entries with parseable claims and verdicts. The container is now ready for interpretation.

> **Architectural rationale (cross-st 0.7.0):** `st-fact` is now a *pure verifier* — its `--ai-*` interpretive flags moved to `st-verdict` (see the migration table on the [st-fact](st-fact) page). The smell behind the move was that `st-fact --ai-caption` produced an interpretation of the chart, not a fact-check verdict — two categorically different operations conflated under one tool.

---

## INTERPRET — *What do the facts mean?*

Interpretation reads the verdicts produced by VERIFY and turns them into something a human can act on — a chart, a written analysis, or a recommendation for the next step.

- **[st-verdict](st-verdict)** — interpret **one report's** fact-check evidence. Produces the stacked verdict bar chart, AI-written captions / summaries / stories at five word-count contracts, and four focused lenses:
  - `--what-is-false` — focused breakdown of inaccurate / disputed claims
  - `--what-is-true` — focused breakdown of verified / supported claims
  - `--what-is-missing` — what important aspects of the prompt the report omitted
  - `--how-to-fix` — recommend exactly one next action: `st-fix` / `st-bang -N` / `st-merge` / `publish-as-is`
- **[st-analyze](st-analyze)** — interpret patterns **across reports** in a container. Useful when you've run `st-bang` or `st-cross` and want a synthesis that spans every author.

After INTERPRET, you have a chart, a written analysis, or a one-line recommendation. Decide your next step from there.

---

## Three killer workflows

Every common Cross use case is one of these three GATHER + VERIFY + INTERPRET combinations. Full copy-pastable transcripts on the **[Showcase Workflows](Showcase-Workflows)** page.

| Workflow | Question | Pipeline |
|---|---|---|
| **A — "Is this fake news?"** | *What is wrong with this report?* | `st-fetch <url> --prep` → `st-cross` → `st-verdict --what-is-false --ai-summary` |
| **B — "What's missing?"** | *What did the report fail to cover?* | same gather → `st-verdict --what-is-missing --ai-summary` |
| **C — "What can I trust here?"** | *Which claims are well-supported?* | same gather → `st-verdict --what-is-true --ai-caption` |

The fourth lens — `--how-to-fix` — sits one step further down the pipeline; run it after any of the three above to get a concrete next-action recommendation rather than a description.

---

## Why the three stages matter

Before cross-st 0.7.0, the boundaries between VERIFY and INTERPRET were blurred — `st-fact` had interpretive flags that let it generate written analysis, and the same code paths handled both verdict-collection and verdict-interpretation. The result was that **a tool's name no longer told you what it did**. The 0.7.0 refactor fixes that: every tool now answers exactly one of the three questions, every flag belongs to the stage that owns its question, and every workflow is a clean GATHER → VERIFY → INTERPRET pipeline.

If you find yourself wanting a tool to do work from a different stage, you're probably reaching for the wrong tool. Look at the table at the top of this page first.

**Related:** [Showcase Workflows](Showcase-Workflows) · [st-fetch](st-fetch) · [st-cross](st-cross) · [st-verdict](st-verdict) · [Container Format](Container-Format)

