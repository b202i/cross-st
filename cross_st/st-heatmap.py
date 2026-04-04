#!/usr/bin/env python3
"""
## st-heatmap — Plot a cross-product fact-check score heatmap

Renders a score heatmap: evaluator AI (rows) vs target story author (columns).
Darker cells = higher veracity scores.  Diagonal = self-evaluation.
Run st-cross first to populate the fact-check matrix.

```
st-heatmap --display subject.json                  # show chart on screen
st-heatmap --file subject.json                     # save PNG to ./tmp/
st-heatmap --display --ai-caption subject.json     # chart on screen + AI narrative
st-heatmap --file --ai-title --ai gemini s.json    # save PNG to ./tmp/ + title via gemini
st-heatmap --display --file --ai-caption s.json    # screen + save PNG + caption
```

Input:  subject.json  — populated story container (run st-cross first)
Output: chart on screen (--display) and/or PNG saved to --path (default ./tmp/)

Options: --file  --path  --display
         --ai-title  --ai-short  --ai-caption
         --ai  --cache  --no-cache  -v  -q

See also: st-verdict  (verdict category bar chart)
          st-plot --plot evaluator_v_target  (same heatmap via st-plot)
"""

import argparse
import json
import os
import sys
from mmd_startup import load_cross_env, require_config
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

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


def format_matrix_for_prompt(df):
    """Format the score pivot table (1 decimal) as plain text."""
    pivot = df.pivot_table(index="evaluator", columns="target", values="score")
    pivot.index.name   = "Evaluator \\ Target"
    pivot.columns.name = None
    return pivot.round(1).to_string()


def format_full_data_for_prompt(df):
    """Return per-cell fact-check data (scores + counts) as CSV."""
    cols = ["evaluator", "target",
            "true_count", "partially_true_count", "opinion_count",
            "partially_false_count", "false_count", "score"]
    available = [c for c in cols if c in df.columns]
    return df[available].round(1).to_csv(index=False)


def build_ai_prompt(matrix_text, full_data_csv, story_titles, n_evaluators, n_targets, content_type):
    """Build an AI prompt for the heatmap data."""
    context = f"""Cross-product AI fact-check score matrix ({n_evaluators} evaluators × {n_targets} targets).
Each cell is the average veracity score one AI (row = evaluator) assigned to stories written by another AI (column = target).

Score scale: +2.0 = all claims True  |  0.0 = neutral/mixed  |  -2.0 = all claims False
Scoring: True=+2, Partially_true=+1, Opinion=0 (excluded from average), Partially_false=-1, False=-2.
Typical observed range for mixed content: -0.5 (poor) to +2.0 (excellent).
Diagonal cells = self-evaluation (the AI that wrote the story also fact-checked it).

HOW TO READ THIS HEATMAP:
• A uniformly DARK column  → that target AI's stories are consistently rated as truthful by all evaluators
• A uniformly LIGHT column → that target AI's stories are consistently rated as less truthful
• A DARK row              → that evaluator is lenient (gives high scores)
• A LIGHT row             → that evaluator is strict (gives low scores)
• A consistently DARK diagonal → self-promotion bias: AIs grade their own work higher
• A flat or light diagonal     → no self-bias; AIs are as harsh on themselves as on others

Score heatmap (evaluator rows × target columns):
{matrix_text}

Full per-cell data (scores + true/false/opinion counts):
{full_data_csv}
Story titles — infer the subject-matter domain from these:
{story_titles}
"""
    audience = "Technical readers (12th grade+) interested in AI reliability for a specific domain."

    if content_type == "title":
        return f"""{context}
Write a punchy title for this heatmap. Max 10 words.
Infer the domain from the story titles and capture the key column or diagonal pattern.
No markdown, no quotes. Plain text, single line."""

    elif content_type == "short":
        return f"""{context}
AUDIENCE: {audience}

Write a SHORT caption (max 80 words) for this heatmap.
Must address:
• The subject domain (infer from story titles)
• Which target AI's column is darkest (most trusted across all evaluators) and which is lightest
• Whether the diagonal shows self-promotion bias or not

NUMBER RULES: Round all values to 1 decimal. Max 4 numbers total.
Plain text, conversational tone. Interpret what the patterns mean — do not just list cell values."""

    elif content_type == "caption":
        return f"""{context}
AUDIENCE: {audience}

Write a DETAILED caption (100–160 words, exactly 2 paragraphs) for this heatmap.

Paragraph 1 — Column and row patterns:
  State the domain (infer from story titles) and overall score range.
  Interpret the COLUMN patterns: which target AI has a consistently dark column
  (all evaluators trust it) and which has a light column (all evaluators skeptical).
  Interpret the ROW patterns: which evaluator is most lenient and which is strictest.
  Do NOT just cite the single highest/lowest cell — explain what the overall column/row
  shade means for that AI's reliability in this domain.

Paragraph 2 — Diagonal and outliers:
  Interpret the DIAGONAL. Does it skew darker than the surrounding cells (self-promotion bias)?
  Or is it flat/mixed (no self-bias)? State explicitly what this means.
  Name one standout outlier cell and use the count data (true_count, false_count, partially_false_count)
  to explain WHY it looks different from its neighbors.
  Close with one practical implication for someone choosing an AI for this domain.

NUMBER RULES: Round to 1 decimal. Synthesize — do not copy the table verbatim.
Plain text, professional but accessible. No bullet points or sub-headings."""

    elif content_type == "summary":
        return f"""{context}
AUDIENCE: Technical/engineering readers making infrastructure decisions.

Write a TECHNICAL SUMMARY (120–200 words, 3 paragraphs) for this heatmap.

Paragraph 1 — Column story (target AI accuracy):
  Which target AI's column is consistently darkest across all evaluators (most trusted)?
  Which is lightest? State the domain. Give the approximate score range in plain numbers.

Paragraph 2 — Row story (evaluator leniency) + diagonal:
  Which evaluator is most lenient (high row average) and which is strictest?
  Does the diagonal skew darker than off-diagonal cells (self-promotion bias)?

Paragraph 3 — Practical advice:
  Given this domain, which AI would you trust to write accurate reports?
  Which would you treat with skepticism? One concrete recommendation.

NUMBER RULES: 6–10 whole numbers. Round everything. No raw decimals.
FORMAT: Plain text, 3 paragraphs, professional."""

    elif content_type == "story":
        return f"""{context}
AUDIENCE: Technical readers (engineering teams, AI researchers) who want a thorough analysis.

Write a COMPREHENSIVE STORY (800–1200 words) about this heatmap.

STRUCTURE:
1. Title (≤10 words, punchy)
2. Why this matrix matters (100–150 words) — what cross-product fact-checking reveals
3. Column analysis (250–350 words) — each target AI's trustworthiness in this domain,
   supported by which evaluators agree (or disagree), with approximate scores
4. Row & diagonal analysis (200–300 words) — evaluator leniency patterns, self-promotion
   bias evidence, any anomalous evaluator
5. Bottom line (100–150 words) — which AI to trust for this domain, which to avoid,
   and what the pattern suggests about self-serving bias broadly

NUMBER RULES: 12–18 whole numbers. Round everything. Each data point mentioned once only.
WRITING RULES: No repetition. No filler. Each paragraph adds new insight.
FORMAT: Plain text, clear paragraph breaks. No markdown headers."""

    else:
        raise ValueError(f"Unknown content_type: {content_type}")


def generate_ai_content(df, story_titles, ai_make, content_type, verbose=False, use_cache=True):
    """Generate an AI-written caption for the heatmap data."""
    matrix_text   = format_matrix_for_prompt(df)
    full_data_csv = format_full_data_for_prompt(df)
    n_evaluators  = df["evaluator"].nunique()
    n_targets     = df["target"].nunique()
    prompt        = build_ai_prompt(matrix_text, full_data_csv, story_titles,
                                    n_evaluators, n_targets, content_type)

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

def render_heatmap(df, output_path, display, file_out, quiet):
    """Render evaluator-vs-target score heatmap."""
    pivot = df.pivot_table(index="evaluator", columns="target", values="score")

    fig, ax = plt.subplots(figsize=(10, 8))
    sns.heatmap(pivot, annot=True, cmap="YlGnBu", fmt=".2f", ax=ax,
                linewidths=0.5, linecolor="white")
    ax.set_title("Score Heatmap: Evaluator vs Target", fontsize=14, pad=12)
    ax.set_xlabel("Target Story (author)", fontsize=11)
    ax.set_ylabel("Evaluator AI", fontsize=11)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    fig.tight_layout()

    if file_out:
        out = output_path + "heatmap_scores.png"
        fig.savefig(out, dpi=150)
        if not quiet:
            print(f"Saved: {out}")

    if display:
        show_plot(fig)

    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-heatmap',
        description='Cross-product fact-check score heatmap',
        epilog='AI Content: --ai-title  --ai-short  --ai-caption  --ai-summary  --ai-story')

    parser.add_argument('json_file', type=str,
                        help='Path to the JSON file', metavar='file.json')

    # Chart output
    chart_group = parser.add_argument_group('Chart output')
    chart_group.add_argument('--display', action='store_true',
                             help='Display heatmap on screen, default: off')
    chart_group.add_argument('--file', action='store_true',
                             help='Save heatmap PNG to file, default: off')
    chart_group.add_argument('--path', type=valid_directory, default='./tmp',
                             help='Output directory for PNG file, default: ./tmp')

    # AI content generation
    ai_group = parser.add_argument_group('AI content generation')
    ai_group.add_argument('--ai-title',   action='store_true',
                          help='Generate a title for the heatmap (max 10 words) → stdout')
    ai_group.add_argument('--ai-short',   action='store_true',
                          help='Generate a short caption (max 80 words) → stdout')
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

    ai_requested    = args.ai_title or args.ai_short or args.ai_caption or args.ai_summary or args.ai_story
    chart_requested = args.display or args.file

    if not chart_requested and not ai_requested:
        print("No output requested. Use --display, --file, and/or --ai-caption.")
        print("Run 'st-heatmap --help' for usage.")
        sys.exit(1)

    # Always load .env — ai-short is on by default when no other --ai-* flag is given
    load_cross_env()

    # Load container
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

    # Validate fact-check data
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

    # ── AI content generation ────────────────────────────────────────────────
    # Must happen BEFORE rendering so the caption can be embedded in the figure.
    # (plt.show() blocks the process; generating after means the user sees the
    # chart window first and must close it before reading the caption.)
    ai_content: dict[str, str] = {}   # ctype → generated text

    if ai_requested:
        content_ai = args.ai or get_default_ai()
        content_type_map = [
            (args.ai_title,   "title",   "Title"),
            (args.ai_short,   "short",   "Short Caption"),
            (args.ai_caption, "caption", "Caption"),
            (args.ai_summary, "summary", "Summary"),
            (args.ai_story,   "story",   "Story"),
        ]
        story_titles = extract_story_titles(container)
        for flag, ctype, label in content_type_map:
            if not flag:
                continue
            if not args.quiet:
                print(f"\n{label} (generated by {content_ai}):")
                print("─" * 70)
            content = generate_ai_content(df, story_titles, content_ai, ctype,
                                          args.verbose, args.cache)
            ai_content[ctype] = content
            if content:
                print(content)
            else:
                print("(Caption generation failed)")
            if not args.quiet:
                print("─" * 70)

    # ── Chart rendering ──────────────────────────────────────────────────────
    # AI content is generated and printed to the terminal first (above), so
    # when the heatmap window opens the caption is already on screen.
    # The user can position the terminal and the chart window side by side.
    if chart_requested:
        output_path = args.path if args.path.endswith(os.sep) else args.path + os.sep
        render_heatmap(df, output_path, args.display, args.file, args.quiet)

    if not args.quiet and chart_requested and not ai_requested:
        print("Done.")


if __name__ == "__main__":
    main()
