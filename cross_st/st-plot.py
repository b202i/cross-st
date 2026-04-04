#!/usr/bin/env python3
"""
## st-plot — Plot cross-product fact-check scores

Renders statistical plots from the cross-product fact-check matrix.
Run st-cross first to populate the fact-check data.

```
st-plot --plot all --display subject.json              # show all plots on screen
st-plot --plot evaluator_v_target --display s.json     # single plot on screen
st-plot --plot all --file subject.json                 # save all plots to ./tmp/
st-plot --plot bar_score_target --file --path out/ s.json  # save to custom dir
st-plot --csv subject.json                             # export data as CSV
st-plot --file_kv subject.json                         # JSON map of saved file paths
st-plot --ai-caption subject.json                      # AI caption of score patterns
st-plot --ai-title --ai gemini subject.json            # AI title using Gemini
st-plot --ai-short subject.json                        # AI short summary
```

Plot types:
  counts_v_score       Correlation heatmap: claim counts vs score
  evaluator_v_target   Score heatmap: evaluator AI (rows) vs target story (cols)
  bar_score_evaluator  Bar chart of average scores by evaluator
  bar_score_target     Bar chart of average scores by target
  outlier_detection    Z-score outlier detection on scores
  pivot_table          Pivot table of mean scores (evaluator × target)
  all                  All of the above

Options: --plot  --file  --path  --display  --file_kv
         --csv  --json  --markdown
         --ai  --ai-title  --ai-short  --ai-caption  --no-cache
         -v  -q
"""

from mmd_data_analysis import get_flattened_fc_data, analysis_plots
from ai_handler import process_prompt, get_content, get_default_ai
from pathlib import Path
from scipy import stats
import argparse
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import seaborn as sns
import sys
from mmd_startup import load_cross_env, require_config

from mmd_plot import get_plot_list, show_plot

p_choice, p_type = get_plot_list()


def valid_directory(path_str):
    """Validate if the path is a valid directory or can be created"""
    path = Path(path_str).resolve()
    if not path.is_dir():
        try:
            os.mkdir(path)
        except OSError as e:
            raise argparse.ArgumentTypeError(f"Cannot create directory {path_str}: {e}")
    return str(path) + os.sep


def create_directory(path_str):
    """Create directory if it doesn't exist and return path with separator"""
    path = Path(path_str).resolve()
    if not path.is_dir():
        os.mkdir(path)
    return str(path) + os.sep


# ── AI content generation ──────────────────────────────────────────────────

def _summarise_plot_data(df) -> str:
    """Format cross-product score data as compact text for AI consumption."""
    lines = []

    # Accuracy ranking — avg score received as report author
    target_avg = df.groupby("target_make")["score"].mean().sort_values(ascending=False)
    lines.append("REPORT ACCURACY  (avg peer fact-check score, scale −2 to +2):")
    for ai, score in target_avg.items():
        lines.append(f"  {ai:<14}  {score:>+.3f}")
    lines.append("")

    # Leniency ranking — avg score given as fact-checker
    eval_avg = df.groupby("evaluator_make")["score"].mean().sort_values(ascending=False)
    lines.append("EVALUATOR LENIENCY  (avg score given by each fact-checker):")
    for ai, score in eval_avg.items():
        lines.append(f"  {ai:<14}  {score:>+.3f}")
    lines.append("")

    # Self vs peer scores (bias detection)
    lines.append("SELF-SCORE vs PEER-SCORE  (positive bias = self-serving):")
    lines.append(f"  {'AI':<14}  {'Self':>6}  {'Peers':>6}  {'Bias':>6}")
    for ai in sorted(df["target_make"].unique()):
        s_mask = (df["target_make"] == ai) & (df["evaluator_make"] == ai)
        p_mask = (df["target_make"] == ai) & (df["evaluator_make"] != ai)
        self_s = df.loc[s_mask, "score"].mean() if s_mask.any() else None
        peer_s = df.loc[p_mask, "score"].mean() if p_mask.any() else None
        if self_s is not None and peer_s is not None:
            bias = self_s - peer_s
            lines.append(f"  {ai:<14}  {self_s:>+.3f}  {peer_s:>+.3f}  {bias:>+.3f}")
        elif peer_s is not None:
            lines.append(f"  {ai:<14}  {'n/a':>6}  {peer_s:>+.3f}  {'n/a':>6}")
    lines.append("")

    # Overall verdict mix
    denom = (df["true_count"].sum() + df["partially_true_count"].sum() +
             df["partially_false_count"].sum() + df["false_count"].sum()) or 1
    true_pct  = (df["true_count"].sum() + df["partially_true_count"].sum()) / denom * 100
    false_pct = (df["partially_false_count"].sum() + df["false_count"].sum()) / denom * 100
    lines.append(f"OVERALL VERDICTS  ({len(df)} evaluations):")
    lines.append(f"  True / Partly-true : {true_pct:.0f}%")
    lines.append(f"  Partly-false / False: {false_pct:.0f}%")

    return "\n".join(lines)


def _plot_prompt(data_summary: str, content_type: str) -> str:
    """Return an AI prompt for the requested content_type."""
    if content_type == "title":
        return f"""Write a SHORT, punchy title about this AI accuracy data.

{data_summary}

LENGTH: Maximum 10 words (strict)
RULES: Capture the key accuracy finding. Mention AI names. No articles. Punchy.
EXAMPLES:
  GOOD: "Anthropic Tops Accuracy, Gemini Struggles With Facts"
  BAD:  "Analysis of Cross-Product Fact-Check Scores"
Format: Plain text, single line, no quotes or markdown."""

    elif content_type == "short":
        return f"""Write a SHORT paragraph about this AI accuracy data.

{data_summary}

LENGTH: Maximum 80 words (strict)
RULES:
• Interpret — don't restate the numbers
• Use at most 2–3 whole numbers
• One paragraph, conversational tone
• Answer: Who is most accurate? Any self-serving bias?
Format: Plain text, single paragraph."""

    elif content_type == "caption":
        return f"""Write a detailed caption about this AI accuracy data.

{data_summary}

LENGTH: 100–160 words (strict)
NUMBER RULES: 4–6 whole numbers maximum. Round everything. Natural phrasing.
STRUCTURE:
• Paragraph 1: Accuracy ranking — who writes the most verifiable reports
• Paragraph 2: Evaluator patterns — who is lenient or harsh, any self-serving bias
RULES: Interpret, don't repeat the table. Professional but readable.
Format: Plain text, 2 paragraphs."""

    elif content_type == "summary":
        return f"""Write a TECHNICAL SUMMARY (120–200 words, 3 paragraphs) about this AI accuracy data.

{data_summary}

Paragraph 1 — Accuracy ranking: who writes the most verifiable reports and who the least,
  with approximate score ranges for context.
Paragraph 2 — Evaluator patterns: leniency/strictness variation across evaluators,
  and whether the diagonal (self-evaluation) skews darker than off-diagonal cells.
Paragraph 3 — Practical advice: which AI to choose for report generation in this domain
  and which to treat with skepticism, based on the cross-product evidence.

NUMBER RULES: 6–10 whole numbers. Round everything. No raw decimals.
FORMAT: Plain text, 3 paragraphs, professional."""

    elif content_type == "story":
        return f"""Write a COMPREHENSIVE STORY (800–1200 words) about this AI accuracy data.

{data_summary}

STRUCTURE:
1. Title (≤10 words, punchy)
2. Why cross-product accuracy matters (100–150 words)
3. Target AI accuracy analysis (300–400 words) — which AI writes the most and least
   verifiable reports, with score evidence and evaluator agreement
4. Evaluator patterns and self-serving bias (200–300 words) — leniency/strictness,
   diagonal vs off-diagonal, what it means for benchmark integrity
5. Bottom line (100–150 words) — concrete recommendation, what this reveals about AI

NUMBER RULES: 12–18 whole numbers. Round everything. Each data point mentioned once.
WRITING RULES: No repetition. No filler. Strong close.
FORMAT: Plain text, clear paragraph breaks. No markdown headers."""

    else:
        raise ValueError(f"Unknown content_type for --ai-{content_type}")


def _generate_plot_content(df, ai_make: str, content_type: str,
                           use_cache: bool = True, verbose: bool = False) -> str:
    """Call an AI provider and return generated text about the score data."""
    try:
        data_summary = _summarise_plot_data(df)
        prompt = _plot_prompt(data_summary, content_type)
        if verbose:
            print(f"  Calling {ai_make} for {content_type} ({len(prompt)} chars)…")
        result = process_prompt(ai_make, prompt, verbose=False, use_cache=use_cache)
        _, _, response, _ = result
        content = get_content(ai_make, response).strip()
        if verbose:
            print(f"  Generated {len(content.split())} words")
        return content
    except Exception as e:
        print(f"  Content generation failed: {e}")
        return ""


def main():
    require_config()
    help_display = (
        "  all:                 All plots\n"
        "  counts_v_score:      Correlation heatmap (Counts vs Score)\n"
        "  evaluator_v_target:  Heatmap of scores (Evaluator vs Target)\n"
        "  bar_score_evaluator: Bar plot average scores by evaluator\n"
        "  bar_score_target:    Bar plot average scores by target\n"
        "  outlier_detection:   Z-scores to detect outliers in scores\n"
        "  pivot_table:         Pivot table of scores (Evaluator vs Target)\n"
        f"Default is '{p_choice[0]}'."
    )

    parser = argparse.ArgumentParser(
        prog='st-plot',
        description='Plot cross product-data',
        formatter_class=argparse.RawTextHelpFormatter  # Ensures newlines are preserved
    )

    # Positional argument
    parser.add_argument('json_file', type=str,
                        help='Path to the JSON file', metavar='file.json')

    # Optional arguments
    parser.add_argument('--plot', type=str, choices=p_choice, default=p_choice[1],
                        help=help_display)
    parser.add_argument('--file', action='store_true',
                        help='Write plots to a file, default is no-file')
    parser.add_argument('--path', type=valid_directory, default='./tmp',
                        help='Path for output files, default is ./tmp directory in current location')
    parser.add_argument('--file_kv', action='store_true',
                        help='Print json file_kv with play:url pairs, default is no-print')
    parser.add_argument('--display', action='store_true',
                        help='Display plots on screen, default is no-display')
    parser.add_argument('--json', action='store_true',
                        help='Save data to json file, default is no-file')
    parser.add_argument('--csv', action='store_true',
                        help='Save data to csv file, default is no-file')
    parser.add_argument('--markdown', action='store_true',
                        help='Save data to markdown file, default is no-file')
    parser.add_argument('--no-cache', dest='cache', action='store_false', default=True,
                        help='Bypass the API cache for AI content generation')
    parser.add_argument('--cache', dest='cache', action='store_true',
                        help='Use the API cache for AI content generation (default)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output, default is verbose')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Enable minimal output')

    # AI content generation
    ai_group = parser.add_argument_group('AI content generation')
    ai_group.add_argument('--ai', type=str, default=None,
                          help='AI provider for content generation (default: uses DEFAULT_AI)')
    ai_group.add_argument('--ai-title', action='store_true',
                          help='Generate a short title (max 10 words) → stdout')
    ai_group.add_argument('--ai-short', action='store_true',
                          help='Generate a short paragraph (max 80 words) → stdout')
    ai_group.add_argument('--ai-caption', action='store_true',
                          help='Generate a detailed caption (100–160 words) → stdout')
    ai_group.add_argument('--ai-summary', action='store_true',
                          help='Generate a concise summary (120–200 words) → stdout')
    ai_group.add_argument('--ai-story', action='store_true',
                          help='Generate a comprehensive story (800–1200 words) → stdout')

    # Parse arguments
    args = parser.parse_args()

    if args.verbose:
        print(f"st-plot args: {args}")

    plot_list = []
    if args.plot == "all":
        plot_list = list(p_type.keys())
        plot_list.remove("all")  # All plots except the "all" element remain
    else:
        plot_list.append(args.plot)

    # Special set of plots used by st-analyze.py
    # Print json file_kv with play:url pairs, default is no-print
    file_kv = {}
    if args.file_kv:
        args.file = True
        args.verbose = False
        args.quiet = True
        plot_list = [
            "evaluator_v_target",
            "bar_score_evaluator",
            "bar_score_target",
        ]

    output_path = create_directory(args.path)

    file_prefix = args.json_file.rsplit('.', 1)[0]  # Split from the right, only once
    file_json = file_prefix + ".json"

    try:
        if not os.path.isfile(file_json):
            print(f"Error: The file {args.json_file} does not exist.")
            sys.exit(1)

        with open(file_json, 'r') as file:
            main_container = json.load(file)  # TODO test for fact-check data, error exit if not

    except json.JSONDecodeError:
        print(f"Error: The file {file_json} contains invalid JSON.")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

    # Use realpath to get the actual path of the script
    load_cross_env()

    # Validate fact-check data
    stories = main_container.get("story", [])
    has_facts = any(len(s.get("fact", [])) > 0 for s in stories)
    if not has_facts:
        print(f"No fact-check data found in {file_json}.")
        print(f"Run the cross-product fact-check first:  st-cross {args.json_file}")
        sys.exit(1)

    flattened_data = get_flattened_fc_data(main_container)
    if len(flattened_data) < 4:
        print(f"Insufficient cross-product data ({len(flattened_data)} entries). "
              f"A minimum 2×2 matrix is required.")
        sys.exit(1)

    # Create a Pandas DataFrame
    df = pd.DataFrame(flattened_data)

    # analysis_plots(df)

    # Drop the 'summary' column for analysis (only present when fact-checks exist)
    if "summary" in df.columns:
        df = df.drop(columns=["summary"])

    # Combine make and model for concise labels
    df["evaluator"] = df["evaluator_make"] + ":" + df["evaluator_model"]
    df["target"] = df["target_make"] + ":" + df["target_model"]

    for plot in plot_list:
        if args.verbose:
            print(f" === {plot}: {p_type[plot]} === ")
        match plot:
            case "counts_v_score":
                # Visualize correlation with a heatmap
                plt.figure(figsize=(8, 6))
                correlation_matrix = df[["true_count", "partially_true_count", "opinion_count",
                                         "partially_false_count", "false_count", "score"]].corr()
                sns.heatmap(correlation_matrix, annot=True, cmap="coolwarm", vmin=-1, vmax=1)
                plt.title("Correlation Between Counts and Score")
            case "evaluator_v_target":
                # Heatmap of scores (evaluator vs target)
                plt.figure(figsize=(10, 8))
                pivot_scores = df.pivot_table(index="evaluator", columns="target", values="score")
                sns.heatmap(pivot_scores, annot=True, cmap="YlGnBu", fmt=".2f")
                plt.title("Score Heatmap: Evaluator vs Target")
                plt.xlabel("Target Model")
                plt.ylabel("Evaluator Model")
                plt.xticks(rotation=45, ha="right")
                plt.tight_layout()
            case "bar_score_evaluator":
                # Bar plot of average scores by evaluator and target
                plt.figure(figsize=(12, 6))
                sns.barplot(x="evaluator", y="score", hue="target", data=df)
                plt.title("Average Score by Evaluator")
                plt.xlabel("Evaluator")
                plt.ylabel("Average Score")
                plt.xticks(rotation=45, ha="right")
                plt.legend(title="Target Model", bbox_to_anchor=(1.05, 1), loc="upper left")
                plt.tight_layout()
            case "bar_score_target":
                # Bar plot of average scores by evaluator and target
                plt.figure(figsize=(12, 6))
                sns.barplot(x="target", y="score", hue="evaluator", data=df)
                plt.title("Average Score by Target")
                plt.xlabel("Target")
                plt.ylabel("Average Score")
                plt.xticks(rotation=45, ha="right")
                plt.legend(title="Evaluator Model", bbox_to_anchor=(1.05, 1), loc="upper left")
                plt.tight_layout()
            case "outlier_detection":
                # --- Outlier Detection ---
                # Using Z-scores to detect outliers in 'score'
                df["score_z"] = np.abs(stats.zscore(df["score"]))
                outliers = df[df["score_z"] > 2]  # Threshold of 2 standard deviations
                print("\nOutliers in Score (Z-score > 2):")
                print(outliers[["evaluator", "target", "score", "score_z"]])
            case "pivot_table":
                # --- Pivot Table ---
                print("\nPivot Table of Scores (Evaluator vs Target):")
                pivot_table = df.pivot_table(index="evaluator", columns="target", values="score", aggfunc="mean")
                print(pivot_table)

        if args.display and args.plot:
            show_plot()
        if args.file and args.plot:
            plot_path = output_path + file_prefix + "_" + plot
            plt.savefig(plot_path)
            if args.verbose:
                print(f"Plot: {plot}, saved to: {plot_path}")
            file_kv[plot] = plot_path + ".png"

    if args.file_kv:
        print(json.dumps(file_kv, indent=4))

    if args.csv:
        df.to_csv(f"{output_path+file_prefix}_data.csv", index=False)
        print(f"Data saved to {output_path+file_prefix}_data.csv'")

    if args.markdown:
        df.to_markdown(f"{output_path+file_prefix}_data.md", index=False)
        print(f"Data saved to {output_path+file_prefix}_data.md'")

    if args.json:
        df.to_json(f"{output_path+file_prefix}_data.json", index=False)
        print(f"Data saved to {output_path+file_prefix}_data.json'")

    # ── AI content generation ──────────────────────────────────────────────
    ai_flags = [args.ai_title, args.ai_short, args.ai_caption,
                args.ai_summary, args.ai_story]
    if sum(ai_flags) > 1:
        print("Error: use only one of --ai-title, --ai-short, --ai-caption, "
              "--ai-summary, --ai-story at a time.")
        sys.exit(1)

    ai_content_type = None
    if args.ai_title:   ai_content_type = "title"
    elif args.ai_short:   ai_content_type = "short"
    elif args.ai_caption: ai_content_type = "caption"
    elif args.ai_summary: ai_content_type = "summary"
    elif args.ai_story:   ai_content_type = "story"

    if ai_content_type:
        ai_make = args.ai or get_default_ai()
        label = {
            "title":   "Title",
            "short":   "Short Summary",
            "caption": "Caption",
            "summary": "Summary",
            "story":   "Story",
        }[ai_content_type]
        if not args.quiet:
            print(f"\n{label} (generated by {ai_make}):")
            print("─" * 60)
        content = _generate_plot_content(df, ai_make, ai_content_type, args.cache, args.verbose)
        if content:
            print(content)
        else:
            print("(Content generation failed)")
        if not args.quiet:
            print("─" * 60)


if __name__ == "__main__":
    main()
