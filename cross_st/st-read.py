#!/usr/bin/env python3
"""
## st-read — Evaluate readability metrics for stories

Computes nine standard readability scores for every story and displays them
in a compact table.  Use `--legend` for metric descriptions and scoring scales.

```
st-read subject.json           # readability table for all stories
st-read --legend subject.json  # table + metric legend
```

Metrics: Dale-Chall  FK-Ease  Auto-Read  Coleman-Liau  FK-Grade
         Gunning-Fog  Smog  Poly-syl  Mono-syl  (via textstat)

Grade-level metrics share a scale: 6–8 middle school, 9–12 high school,
12+ college.  FK-Ease: 70+ easy, 60–69 standard, below 50 difficult.

Options: -l legend  -v  -q
"""

import argparse
import json
import os
import sys
from mmd_startup import require_config
import textstat
from tabulate import tabulate


def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-read',
        description='Evaluate story reading metrics')
    parser.add_argument('json_file', type=str,
                        help='Path to the JSON file', metavar='file.json')
    parser.add_argument('-l', '--legend', action='store_true',
                        help='Print legend')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output, default is verbose')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Enable minimal output')

    args = parser.parse_args()
    file_prefix = args.json_file.rsplit('.', 1)[0]  # Split from the right, only once
    file_json = file_prefix + ".json"

    if args.verbose:
        print(f"st-ls args: {args}")

    try:
        if not os.path.isfile(file_json):
            print(f"Error: The file {args.json_file} does not exist.")
            sys.exit(1)

        with open(file_json, 'r') as file:
            main_container = json.load(file)

    except json.JSONDecodeError:
        print(f"Error: The file {file_json} contains invalid JSON.")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

    if "story" not in main_container or len(main_container["story"]) == 0:
        print("story list empty")
    else:
        table_data = []
        for i, story in enumerate(main_container["story"], start=1):
            test_data = story.get("text")
            table_data.append([
                i,
                story.get("make"),
                story.get("model"),
                textstat.dale_chall_readability_score(test_data),
                textstat.flesch_reading_ease(test_data),
                textstat.automated_readability_index(test_data),
                textstat.coleman_liau_index(test_data),
                textstat.flesch_kincaid_grade(test_data),
                textstat.gunning_fog(test_data),
                textstat.smog_index(test_data),
                textstat.polysyllabcount(test_data),
                textstat.monosyllabcount(test_data),
            ])
        print(
            tabulate(
                table_data,
                headers=["S", "Make", "Model",
                         "Dale\nChall",
                         "FK\nEase",
                         "Auto\nRead",
                         "Coleman\nLiau",
                         "FK\nGrade",
                         "Gunning\nFog",
                         "Smog",
                         "Poly\nsyl",
                         "Mono\nsyl"],
                tablefmt="plain",
                floatfmt=".1f"))

        if args.legend:
            print()
            metrics = [
                ["Dale-Chall",   "Word difficulty vs. 3,000 common 4th-grade words"],
                ["FK-Ease",      "Flesch-Kincaid Reading Ease (higher = easier)"],
                ["Auto-Read",    "Automated Readability Index — characters, words, sentences"],
                ["Coleman-Liau", "Character-based grade level (no syllable counting)"],
                ["FK-Grade",     "Flesch-Kincaid Grade Level"],
                ["Gunning-Fog",  "Years of education to understand on first read"],
                ["Smog",         "Simple Measure of Gobbledygook — education years needed"],
                ["Poly-syl",     "Count of words with 3+ syllables"],
                ["Mono-syl",     "Count of single-syllable words"],
            ]
            print(tabulate(metrics, headers=["Metric", "Description"], tablefmt="plain"))

            print()
            print("Dale-Chall scale:")
            print(tabulate([
                ["≤ 4.9", "4th grade or below"],
                ["5–6",   "5th–6th grade"],
                ["7–8",   "7th–8th grade"],
                ["9–10",  "9th–10th grade"],
                ["≥ 9.0", "College"],
            ], headers=["Score", "Level"], tablefmt="plain"))

            print()
            print("FK-Ease scale:")
            print(tabulate([
                ["90–100", "Very easy"],
                ["70–89",  "Easy / fairly easy"],
                ["60–69",  "Standard"],
                ["50–59",  "Fairly difficult"],
                ["30–49",  "Difficult"],
                ["0–29",   "Very confusing"],
            ], headers=["Score", "Level"], tablefmt="plain"))

            print()
            print("Grade level (FK-Grade, Gunning-Fog, Smog, ARI, Coleman-Liau):")
            print(tabulate([
                ["0–3",  "Elementary",   "5–8"],
                ["3–6",  "Elementary",   "8–11"],
                ["6–9",  "Middle school","11–14"],
                ["9–12", "High school",  "14–17"],
                ["12–15","College",      "17–20"],
                ["15+",  "Post-grad",    "20+"],
            ], headers=["Grade", "Level", "Age (US)"], tablefmt="plain"))

            print()
            print("Reference: https://readable.com/readability/")


if __name__ == "__main__":
    main()
