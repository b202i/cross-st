#!/usr/bin/env python3
"""
## st-verdict — Which AI wrote the most accurate stories, and why

Renders a stacked verdict bar chart that answers the three key questions:
**which AI author produced the best stories**, which produced the worst,
and **why** — backed by the True / ~True / Opinion / ~False / False breakdown
from the full cross-product fact-check matrix.  Run st-cross first.

Defaults: --display and --ai-short are ON.  Suppress with --no-display / --no-ai-short.

```
st-verdict subject.json                            # display chart + short caption (default)
st-verdict --no-ai-short subject.json              # display chart only, no caption
st-verdict --file subject.json                     # display + short caption + save PNG to ./tmp/
st-verdict --ai-caption subject.json               # display + full caption instead of short
st-verdict --no-display --file subject.json        # save PNG to ./tmp/ only, no screen
st-verdict --file --ai-title --ai gemini s.json    # save PNG + title via gemini
```

Input:  subject.json  — populated story container (run st-cross first)
Output: chart on screen (--display) and/or PNG saved to --path (default ./tmp/)

Options: --display / --no-display   --file  --path
         --ai-title  --ai-short / --no-ai-short  --ai-caption
         --ai  --cache  --no-cache  -v  -q

See also: st-heatmap  (evaluator-vs-target score heatmap)
"""

import argparse
import json
import os
import sys
import threading
from mmd_startup import load_cross_env, require_config
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from ai_handler import get_content, get_default_ai, process_prompt
from mmd_data_analysis import get_flattened_fc_data
from mmd_plot import show_plot


# ── Helpers ───────────────────────────────────────────────────────────────────

def valid_directory(path_str):
    """Validate or create the output directory; return path with trailing separator."""
    path = Path(path_str).resolve()
    if not path.is_dir():
        try:
            os.mkdir(path)
        except OSError as e:
            raise argparse.ArgumentTypeError(f"Cannot create directory {path_str}: {e}")
    return str(path) + os.sep


def extract_story_titles(container):
    """Return a compact make/model: title list from the container."""
    lines = []
    for s in container.get("story", []):
        make  = s.get("make",  "?")
        model = s.get("model", "?")
        title = s.get("title", "")[:90]
        lines.append(f"  {make}/{model}: {title}")
    return "\n".join(lines)


def subject_from_container(container, json_file):
    """Infer a short subject label from the first story title, falling back to filename."""
    for s in container.get("story", []):
        title = s.get("title", "").strip()
        if title:
            words = title.split()
            short = " ".join(words[:7])
            return short + ("…" if len(words) > 7 else "")
    name = os.path.basename(json_file).rsplit(".", 1)[0]
    return name.replace("_", " ").replace("-", " ").title()


def get_verdict_by_target(df):
    """Return a DataFrame of *average* verdict counts per evaluation, indexed by target AI."""
    col_map = {
        "true_count":            "True",
        "partially_true_count":  "~True",
        "opinion_count":         "Opinion",
        "partially_false_count": "~False",
        "false_count":           "False",
    }
    available = {k: v for k, v in col_map.items() if k in df.columns}
    grouped = df.groupby("target")[list(available.keys())].mean()
    grouped.rename(columns=available, inplace=True)
    return grouped


def format_verdicts_for_prompt(df, story_titles):
    """Format per-target average verdict breakdown for the AI prompt."""
    by_target    = get_verdict_by_target(df)
    n_evaluators = df["evaluator"].nunique()
    total_claims = int(df[["true_count", "partially_true_count", "opinion_count",
                            "partially_false_count", "false_count"]].sum().sum())

    lines = [
        f"Per-story average verdict counts (each story evaluated by {n_evaluators} AIs):",
        f"Total claims analysed across all fact-checks: {total_claims}",
        "",
    ]
    categories = ["True", "~True", "Opinion", "~False", "False"]
    for target, row in by_target.iterrows():
        total = sum(row[c] for c in categories if c in row)
        lines.append(f"  {target}:")
        for cat in categories:
            if cat in row:
                val = row[cat]
                pct = 100 * val / total if total else 0
                lines.append(f"    {cat:<10} avg {val:5.1f}  ({pct:.0f}%)")
    lines += ["", "Story titles (infer the subject domain from these):", story_titles]
    return "\n".join(lines)


def build_ai_prompt(verdicts_text, n_evaluators, n_targets, content_type):
    """Build an AI prompt for the verdict category data."""
    context = f"""Cross-product AI fact-check verdict breakdown.
{n_evaluators} AI evaluators each fact-checked stories written by {n_targets} AI authors.

Scoring: True=+2  ~True=+1  Opinion=0 (excluded from score average)
         ~False=-1  False=-2.  Score range: -2.0 (all False) to +2.0 (all True).

{verdicts_text}

HOW TO READ THIS CHART:
• Each bar represents one story author (target AI).
• The bar is stacked by verdict category — the colour bands show what fraction of
  that author's claims were True / ~True / Opinion / ~False / False on average.
• A tall green band = high accuracy.  Any red/orange band = notable inaccuracy.
• Compare bar heights to see which author generates more verifiable claims overall.
• The Opinion band is neutral — it counts claims that are subjective, not wrong.

THE KEY QUESTION TO ANSWER:
Which AI author produced the most accurate, fact-verified stories on this topic,
and what in the verdict breakdown explains why?
"""
    audience = "Technical readers (12th grade+) interested in AI report quality."

    if content_type == "title":
        return f"""{context}
Write a punchy title for this chart. Max 10 words.
Infer the subject domain from the story titles.
Name the winning AI author or capture the key finding (who is most accurate, or how large the gap is).
No markdown, no quotes. Plain text, single line."""

    elif content_type == "short":
        return f"""{context}
AUDIENCE: {audience}

Write a SHORT caption (max 80 words, 1 paragraph) for this chart.
Lead with the verdict: name the best-performing AI author and give one concrete
reason WHY (e.g. highest True/~True proportion, or lowest False/~False band).
Name the weakest author if the gap is meaningful.
Infer the subject domain from the story titles.

NUMBER RULES: Round to whole numbers. Max 4 numbers total.
Plain text, conversational tone. One clear winner, one clear reason. Do not list raw counts."""

    elif content_type == "caption":
        return f"""{context}
AUDIENCE: {audience}

Write a DETAILED caption (100–160 words, exactly 2 paragraphs) for this chart.

Paragraph 1 — The verdict:
  State the subject domain (infer from story titles).
  Name the best AI author: which one has the tallest True/~True stack and why
  that makes it the winner. Name the weakest AI author if there is a meaningful
  gap. Give the key numbers that support the verdict (approximate %, rounded).

Paragraph 2 — The WHY and practical takeaway:
  Explain what drove the gap — was it more True claims, fewer False/~False claims,
  or a notably different Opinion fraction? What does the Opinion band reveal about
  content style vs. accuracy? Close with one sentence: which AI should someone
  choose for this domain and why the verdict data supports that choice.

NUMBER RULES: Round to whole numbers. Do not copy the table — synthesize.
Plain text, professional but accessible. No bullet points or sub-headings."""

    elif content_type == "summary":
        return f"""{context}
AUDIENCE: Technical/engineering readers choosing an AI for report generation.

Write a TECHNICAL SUMMARY (120–200 words, 3 paragraphs) for this verdict chart.

Paragraph 1 — The verdict:
  State the domain. Name the winning AI author and the runner-up.
  Give the key numbers: approximate True/~True % for the winner vs. the weakest
  author. State clearly which AI produced the most fact-verifiable stories.

Paragraph 2 — The WHY:
  Break down what drove the difference. Was it more True claims, fewer False/~False
  claims, or a different Opinion fraction? Which author generates the most subjective
  content and what does that signal about reliability?

Paragraph 3 — Practical recommendation:
  Name the AI to choose for this domain and give two specific reasons grounded in
  the verdict data. What should a team watch out for with the weakest author?

NUMBER RULES: 6–10 whole numbers. Round everything. No raw percentages with decimals.
FORMAT: Plain text, 3 paragraphs, professional."""

    elif content_type == "story":
        return f"""{context}
AUDIENCE: Technical readers (engineering teams, AI practitioners) wanting a full analysis.

Write a COMPREHENSIVE STORY (800–1200 words) about this verdict chart.

STRUCTURE:
1. Title (≤10 words, punchy — name the winner or the key finding)
2. The verdict upfront (100–150 words) — which AI won, which lost, and the
   single most important number that explains why
3. Author-by-author accuracy analysis (300–400 words) — True/~True/Opinion/~False/False
   profiles for each story author; which is trustworthy, which is risky, with evidence
4. The Opinion question (150–200 words) — what a high Opinion fraction means, whether
   it is a feature or a bug, and which authors lean into subjective content
5. Bottom line (100–150 words) — concrete recommendation for report generation in
   this domain, and what the verdict pattern says about AI reliability broadly

NUMBER RULES: 12–18 whole numbers. Round everything. No repetition.
WRITING RULES: Lead with the conclusion. Each paragraph adds new insight. No filler. Strong close.
FORMAT: Plain text, clear paragraph breaks. No markdown headers."""

    else:
        raise ValueError(f"Unknown content_type: {content_type}")


def generate_ai_content(df, story_titles, ai_make, content_type, verbose=False, use_cache=True):
    """Generate an AI-written caption for the verdict data."""
    verdicts_text = format_verdicts_for_prompt(df, story_titles)
    n_evaluators  = df["evaluator"].nunique() if "evaluator" in df.columns else 0
    n_targets     = df["target"].nunique()    if "target"    in df.columns else 0
    prompt        = build_ai_prompt(verdicts_text, n_evaluators, n_targets, content_type)

    if verbose:
        print(f"  Calling {ai_make} for {content_type} ({len(prompt)} chars prompt)…")

    try:
        result = process_prompt(ai_make, prompt, verbose=False, use_cache=use_cache)
        _, _, response, _ = result
        content = get_content(ai_make, response).strip()
        return content
    except Exception as e:
        print(f"  Caption generation failed: {e}")
        if verbose:
            import traceback; traceback.print_exc()
        return ""


# ── Chart ─────────────────────────────────────────────────────────────────────

_VERDICT_CATEGORIES = ["True", "~True", "Opinion", "~False", "False"]
_VERDICT_COLORS     = ["#2ecc71", "#a8d8a8", "#f0e68c", "#f4a460", "#e74c3c"]


def _short_label(target_str):
    """Convert 'make:model_long_name' to a two-line axis label."""
    parts = target_str.split(":", 1)
    if len(parts) == 2:
        make, model = parts
        return f"{make}\n{model[:15]}"
    return target_str[:20]


def render_verdict_bar(df, output_path, display, file_out, quiet, subject="", show=True):
    """Render stacked verdict bar chart (avg claims per eval, per target AI).

    When show=True (default) and display=True, blocks until the user closes the
    window.  When show=False and display=True, returns the Figure so the caller
    can arrange a non-blocking show followed by a deferred blocking show.
    """
    by_target    = get_verdict_by_target(df)
    n_evaluators = df["evaluator"].nunique()
    total_claims = int(df[["true_count", "partially_true_count", "opinion_count",
                            "partially_false_count", "false_count"]].sum().sum())

    labels = [_short_label(t) for t in by_target.index]
    x      = range(len(labels))

    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 1.8), 6))

    bottom = [0.0] * len(by_target)
    for cat, color in zip(_VERDICT_CATEGORIES, _VERDICT_COLORS):
        if cat not in by_target.columns:
            continue
        values = by_target[cat].tolist()
        bars = ax.bar(x, values, bottom=bottom, color=color,
                      edgecolor="white", width=0.55, label=cat)
        # Label each segment if tall enough to read
        for bar, val, bot in zip(bars, values, bottom):
            if val >= 2.0:
                txt_color = "white" if color in ("#2ecc71", "#e74c3c") else "#333333"
                ax.text(bar.get_x() + bar.get_width() / 2, bot + val / 2,
                        f"{val:.0f}", ha="center", va="center",
                        fontsize=8, color=txt_color, fontweight="bold")
        bottom = [b + v for b, v in zip(bottom, values)]

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Avg. claims per evaluation", fontsize=11)
    ax.set_xlabel("Story Author (target AI)", fontsize=11)

    title_lines = ["Verdict Breakdown by Story Author"]
    if subject:
        title_lines.insert(0, subject)
    ax.set_title("\n".join(title_lines), fontsize=13, pad=10)

    ax.legend(title="Verdict", loc="upper right", framealpha=0.9, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)

    sub = (f"{n_evaluators} evaluator(s) × {by_target.shape[0]} author(s)"
           f"  ·  {total_claims} total claims")
    fig.text(0.5, 0.01, sub, ha="center", fontsize=8, color="gray")

    fig.tight_layout(rect=[0, 0.04, 1, 1])

    if file_out:
        out = output_path + "verdict_categories.png"
        fig.savefig(out, dpi=150)
        if not quiet:
            print(f"Saved: {out}")

    if display:
        if show:
            show_plot(fig)
            plt.close(fig)
        else:
            return fig   # caller takes ownership; must close it
    else:
        plt.close(fig)
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-verdict',
        description='Which AI wrote the most accurate stories — and why',
        epilog='AI Content: --ai-title  --ai-short  --ai-caption  --ai-summary  --ai-story')

    parser.add_argument('json_file', type=str,
                        help='Path to the JSON file', metavar='file.json')

    chart_group = parser.add_argument_group('Chart output')
    chart_group.add_argument('--display', action='store_true', default=True,
                             help='Display chart on screen (default: on)')
    chart_group.add_argument('--no-display', dest='display', action='store_false',
                             help='Suppress on-screen display')
    chart_group.add_argument('--file', action='store_true',
                             help='Save chart PNG to file, default: off')
    chart_group.add_argument('--path', type=valid_directory, default='./tmp',
                             help='Output directory for PNG file, default: ./tmp')

    ai_group = parser.add_argument_group('AI content generation')
    ai_group.add_argument('--ai-title',   action='store_true',
                          help='Generate a title (max 10 words) → stdout')
    ai_group.add_argument('--ai-short',   action='store_true', default=None,
                          help='Generate a short caption (max 80 words) → stdout  [default: on when no other --ai-* flag is given]')
    ai_group.add_argument('--no-ai-short', dest='ai_short', action='store_false',
                          help='Suppress the automatic short caption')
    ai_group.add_argument('--ai-caption', action='store_true',
                          help='Generate a detailed caption (100–160 words) → stdout')
    ai_group.add_argument('--ai-summary', action='store_true',
                          help='Generate a concise summary (120–200 words) → stdout')
    ai_group.add_argument('--ai-story',   action='store_true',
                          help='Generate a comprehensive story (800–1200 words) → stdout')
    ai_group.add_argument('--ai', type=str, default=None,
                          help=f'AI to use for content generation (default: {get_default_ai()})')

    parser.add_argument('--cache', dest='cache', action='store_true', default=True,
                        help='Enable API cache, default: enabled')
    parser.add_argument('--no-cache', dest='cache', action='store_false',
                        help='Disable API cache')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.add_argument('-q', '--quiet',   action='store_true', help='Minimal output')

    args = parser.parse_args()

    # Resolve ai_short: default-on only when no other --ai-* flag is explicitly given
    if args.ai_short is None:
        args.ai_short = not (args.ai_title or args.ai_caption or args.ai_summary or args.ai_story)

    ai_requested    = args.ai_title or args.ai_short or args.ai_caption or args.ai_summary or args.ai_story
    chart_requested = args.display or args.file

    if not chart_requested and not ai_requested:
        print("No output requested. Use --display, --file, and/or --ai-caption.")
        print("Run 'st-verdict --help' for usage.")
        sys.exit(1)

    # Always load .env — ai-short is on by default when no other --ai-* flag is given
    load_cross_env()

    file_prefix = args.json_file.rsplit('.', 1)[0]
    file_json   = file_prefix + ".json"

    try:
        if not os.path.isfile(file_json):
            print(f"Error: File not found: {file_json}")
            sys.exit(1)
        with open(file_json, 'r') as f:
            container = json.load(f)
    except json.JSONDecodeError:
        print(f"Error: {file_json} contains invalid JSON.")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

    stories   = container.get("story", [])
    has_facts = any(len(s.get("fact", [])) > 0 for s in stories)
    if not has_facts:
        print(f"No fact-check data found in {file_json}.")
        print(f"Run the cross-product fact-check first:  st-cross {args.json_file}")
        sys.exit(1)

    flattened = get_flattened_fc_data(container)
    if len(flattened) < 4:
        print(f"Insufficient cross-product data ({len(flattened)} entries). "
              f"A minimum 2×2 matrix is required.")
        sys.exit(1)

    df = pd.DataFrame(flattened)
    if "summary" in df.columns:
        df = df.drop(columns=["summary"])

    df["evaluator"] = df["evaluator_make"] + ":" + df["evaluator_model"]
    df["target"]    = df["target_make"]    + ":" + df["target_model"]

    if args.verbose:
        print(f"Loaded {len(df)} fact-check entries from {file_json}")

    subject       = subject_from_container(container, args.json_file)
    story_titles  = extract_story_titles(container)

    ai_content: dict[str, str] = {}
    ai_threads: list = []

    # ── Start AI generation in background threads ────────────────────────────
    if ai_requested:
        content_ai = args.ai or get_default_ai()
        content_type_map = [
            (args.ai_title,   "title",   "Title"),
            (args.ai_short,   "short",   "Short Caption"),
            (args.ai_caption, "caption", "Caption"),
            (args.ai_summary, "summary", "Summary"),
            (args.ai_story,   "story",   "Story"),
        ]
        for flag, ctype, label in content_type_map:
            if not flag:
                continue
            def _generate(ctype=ctype):
                ai_content[ctype] = generate_ai_content(
                    df, story_titles, content_ai, ctype, args.verbose, args.cache)
            t = threading.Thread(target=_generate, daemon=True)
            ai_threads.append((t, ctype, label))
            t.start()

    # ── Render chart (save PNG if requested, get Figure back) ────────────────
    fig = None
    if chart_requested:
        output_path = args.path if args.path.endswith(os.sep) else args.path + os.sep
        fig = render_verdict_bar(df, output_path, args.display, args.file, args.quiet,
                                 subject=subject, show=False)

    # ── Display chart ─────────────────────────────────────────────────────────
    if fig is not None:
        if ai_requested:
            # A canvas timer fires every 100 ms inside matplotlib's own event
            # loop (the one that plt.show() blocks on).  When all AI threads are
            # done the callback prints the captions to the terminal — the chart
            # window is still open so both are visible simultaneously.
            caption_done = [False]

            def _ai_ready_check():
                if caption_done[0]:
                    return
                if any(t.is_alive() for t, _, _ in ai_threads):
                    return                    # still waiting
                caption_done[0] = True
                _caption_timer.stop()
                for t, ctype, label in ai_threads:
                    content = ai_content.get(ctype, "")
                    if not args.quiet:
                        print(f"\n{label} (generated by {content_ai}):")
                        print("─" * 70)
                    if content:
                        print(content)
                    else:
                        print("(Caption generation failed)")
                    if not args.quiet:
                        print("─" * 70)
                print("  [Close the chart window or press Ctrl+C to exit]", flush=True)

            _caption_timer = fig.canvas.new_timer(interval=100)
            _caption_timer.add_callback(_ai_ready_check)
            _caption_timer.start()
        else:
            print("  [Close the chart window or press Ctrl+C to exit]", flush=True)

        try:
            plt.show()
        except KeyboardInterrupt:
            print()
            plt.close("all")

    elif ai_requested:
        # No chart — just wait for the threads and print
        for t, ctype, label in ai_threads:
            t.join()
            content = ai_content.get(ctype, "")
            if not args.quiet:
                print(f"\n{label} (generated by {content_ai}):")
                print("─" * 70)
            if content:
                print(content)
            else:
                print("(Caption generation failed)")
            if not args.quiet:
                print("─" * 70)

    if not args.quiet and chart_requested and not ai_requested:
        print("Done.")


if __name__ == "__main__":
    main()

