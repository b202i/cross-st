#!/usr/bin/env python3

import json
import pandas as pd
import json
import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from scipy import stats

# Your JSON data (pasted here for completeness)
json_data = {
    "story": [
        {
            "make": "openai",
            "model": "gpt-4o",
            "fact": [
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     36 |                9 |        23 |                 0 |       0 |cross:xai:grok-2-latest Fact Check Score: 1.80",
                    "counts": [36, 9, 23, 0, 0],
                    "score": 1.8,
                    "make": "xai",
                    "model": "grok-2-latest"
                },
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     26 |                9 |         9 |                 0 |       0 |cross:openai:gpt-4o Fact Check Score: 1.74",
                    "counts": [26, 9, 9, 0, 0],
                    "score": 1.7428571428571429,
                    "make": "openai",
                    "model": "gpt-4o"
                },
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     33 |                7 |         5 |                 0 |       0 |cross:perplexity:sonar Fact Check Score: 1.82",
                    "counts": [33, 7, 5, 0, 0],
                    "score": 1.825,
                    "make": "perplexity",
                    "model": "sonar"
                },
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     42 |               13 |         4 |                 0 |       0 |cross:anthropic:claude-3-7-sonnet-20250219 Fact Check Score: 1.76",
                    "counts": [42, 13, 4, 0, 0],
                    "score": 1.7636363636363637,
                    "make": "anthropic",
                    "model": "claude-3-7-sonnet-20250219"
                }
            ]
        },
        {
            "make": "xai",
            "model": "grok-2-latest",
            "fact": [
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     18 |                5 |        15 |                 0 |       0 |cross:xai:grok-2-latest Fact Check Score: 1.78",
                    "counts": [18, 5, 15, 0, 0],
                    "score": 1.7826086956521738,
                    "make": "xai",
                    "model": "grok-2-latest"
                },
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     19 |                9 |         2 |                 1 |       1 |cross:anthropic:claude-3-7-sonnet-20250219 Fact Check Score: 1.47",
                    "counts": [19, 9, 2, 1, 1],
                    "score": 1.4666666666666666,
                    "make": "anthropic",
                    "model": "claude-3-7-sonnet-20250219"
                },
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     11 |                8 |        10 |                 0 |       0 |cross:openai:gpt-4o Fact Check Score: 1.58",
                    "counts": [11, 8, 10, 0, 0],
                    "score": 1.5789473684210527,
                    "make": "openai",
                    "model": "gpt-4o"
                },
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     10 |                7 |        11 |                 5 |       1 |cross:perplexity:sonar Fact Check Score: 0.87",
                    "counts": [10, 7, 11, 5, 1],
                    "score": 0.8695652173913043,
                    "make": "perplexity",
                    "model": "sonar"
                }
            ]
        },
        {
            "make": "perplexity",
            "model": "sonar",
            "fact": [
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     36 |                5 |        13 |                 0 |       0 |cross:xai:grok-2-latest Fact Check Score: 1.88",
                    "counts": [36, 5, 13, 0, 0],
                    "score": 1.8780487804878048,
                    "make": "xai",
                    "model": "grok-2-latest"
                },
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     28 |                4 |         4 |                 2 |       0 |cross:anthropic:claude-3-7-sonnet-20250219 Fact Check Score: 1.71",
                    "counts": [28, 4, 4, 2, 0],
                    "score": 1.7058823529411764,
                    "make": "anthropic",
                    "model": "claude-3-7-sonnet-20250219"
                },
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     17 |                7 |         7 |                 0 |       0 |cross:openai:gpt-4o Fact Check Score: 1.71",
                    "counts": [17, 7, 7, 0, 0],
                    "score": 1.7083333333333333,
                    "make": "openai",
                    "model": "gpt-4o"
                },
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     25 |                3 |         6 |                 0 |       0 |cross:perplexity:sonar Fact Check Score: 1.89",
                    "counts": [25, 3, 6, 0, 0],
                    "score": 1.8928571428571428,
                    "make": "perplexity",
                    "model": "sonar"
                }
            ]
        },
        {
            "make": "anthropic",
            "model": "claude-3-7-sonnet-20250219",
            "fact": [
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     38 |               10 |         6 |                 1 |       1 |cross:xai:grok-2-latest Fact Check Score: 1.66",
                    "counts": [38, 10, 6, 1, 1],
                    "score": 1.66,
                    "make": "xai",
                    "model": "grok-2-latest"
                },
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     44 |                3 |         1 |                 0 |       0 |cross:anthropic:claude-3-7-sonnet-20250219 Fact Check Score: 1.94",
                    "counts": [44, 3, 1, 0, 0],
                    "score": 1.9361702127659575,
                    "make": "anthropic",
                    "model": "claude-3-7-sonnet-20250219"
                },
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     25 |                6 |         2 |                 0 |       1 |cross:openai:gpt-4o Fact Check Score: 1.69",
                    "counts": [25, 6, 2, 0, 1],
                    "score": 1.6875,
                    "make": "openai",
                    "model": "gpt-4o"
                },
                {
                    "summary": "|   True |   Partially_true |   Opinion |   Partially_false |   False |\n|-------:|-----------------:|----------:|------------------:|--------:|\n|     22 |                9 |         5 |                 8 |       1 |cross:perplexity:sonar Fact Check Score: 1.07",
                    "counts": [22, 9, 5, 8, 1],
                    "score": 1.075,
                    "make": "perplexity",
                    "model": "sonar"
                }
            ]
        }
    ]
}


def get_flattened_fc_data_simple(data):
    # Flatten the data into a list of dictionaries
    # Requires N stories with exactly N facts each
    model_max_chars = 17
    flattened_data = []
    for story in data["story"]:
        evaluator_make = story["make"]
        evaluator_model = story["model"][:model_max_chars]
        for fact in story["fact"]:
            flattened_data.append({
                "evaluator_make": evaluator_make,
                "evaluator_model": evaluator_model,
                "target_make": fact["make"],
                "target_model": fact["model"][:model_max_chars],
                "true_count": fact["counts"][0],
                "partially_true_count": fact["counts"][1],
                "opinion_count": fact["counts"][2],
                "partially_false_count": fact["counts"][3],
                "false_count": fact["counts"][4],
                "score": fact["score"],
                "summary": fact["summary"]  # Optional, included for reference
            })
    return flattened_data


def get_flattened_fc_data(data):
    """
How It Works
Collect Data:
Iterate through each story and its facts, storing them temporarily.
Track unique target make:model pairs and which targets each story evaluates.

Determine Maximum Fact-Checks:
Compute the maximum number of targets evaluated by any single story (max_targets_per_story).
Identify all unique targets across the dataset.

Find Largest Square:
Start with the maximum possible square size (minimum of number of stories and unique targets).
Iteratively reduce the size until a valid square is found:
Select the top size most-covered targets.
Find size stories that evaluate all these targets.
Stop when a complete square is achieved.

Filter and Flatten:
Only include fact-checks from the selected stories and for the selected targets.
Return the flattened list of dictionaries.

Key Features
Maximizes Square Size: It tries to use as many evaluators and targets as possible while ensuring a square shape.
Handles Incomplete Data: Skips stories that don’t evaluate all selected targets and ignores extra fact-checks beyond the square.
Efficient: Prioritizes targets with higher coverage to maximize the chance of finding a large square.
    :param data:
    :return: square data set
    """
    model_max_chars = 17
    # Step 1: Collect all fact-check data and track targets per story
    story_data = []
    all_targets = set()  # Unique target make:model pairs
    story_target_counts = {}  # Story ID -> set of targets it evaluates

    for idx, story in enumerate(data["story"]):
        evaluator_make = story["make"]
        evaluator_model = story["model"][:model_max_chars]
        story_targets = set()
        story_facts = []

        for fact in story["fact"]:
            target_key = f"{fact['make']}:{fact['model'][:model_max_chars]}"
            story_targets.add(target_key)
            all_targets.add(target_key)
            story_facts.append({
                "evaluator_make": evaluator_make,
                "evaluator_model": evaluator_model,
                "target_make": fact["make"],
                "target_model": fact["model"][:model_max_chars],
                "true_count": fact["counts"][0],
                "partially_true_count": fact["counts"][1],
                "opinion_count": fact["counts"][2],
                "partially_false_count": fact["counts"][3],
                "false_count": fact["counts"][4],
                "score": fact["score"],
                "summary": fact.get("summary", "")
            })

        story_data.append(story_facts)
        story_target_counts[idx] = story_targets

    # Step 2: Determine the largest possible square
    max_targets_per_story = max(len(targets) for targets in story_target_counts.values())
    unique_targets = list(all_targets)
    target_to_idx = {target: i for i, target in enumerate(unique_targets)}

    # Count how many stories evaluate each target
    target_coverage = {target: 0 for target in unique_targets}
    for targets in story_target_counts.values():
        for target in targets:
            target_coverage[target] += 1

    # Step 3: Find the largest square subset
    n_evaluators = len(story_data)
    n_targets = len(unique_targets)
    max_square_size = min(n_evaluators, n_targets)  # Initial upper bound

    for size in range(max_square_size, 0, -1):
        # Try to find 'size' stories and 'size' targets forming a complete square
        selected_stories = []
        selected_targets = set()

        # Sort targets by coverage to maximize inclusion potential
        sorted_targets = sorted(unique_targets, key=lambda t: target_coverage[t], reverse=True)
        candidate_targets = sorted_targets[:size]

        # Check each story for coverage of candidate targets
        for idx, targets in story_target_counts.items():
            if all(t in targets for t in candidate_targets):
                selected_stories.append(idx)
                if len(selected_stories) == size:
                    selected_targets = set(candidate_targets)
                    break

        if len(selected_stories) == size and len(selected_targets) == size:
            break  # Found the largest square
    else:
        return []  # No square possible

    # Step 4: Flatten data for the selected square
    flattened_data = []
    selected_target_keys = selected_targets

    for story_idx in selected_stories:
        for fact in story_data[story_idx]:
            target_key = f"{fact['target_make']}:{fact['target_model']}"
            if target_key in selected_target_keys:
                flattened_data.append(fact)

    return flattened_data


def analysis_plots(df):
    # Drop the 'summary' column for analysis
    df = df.drop(columns=["summary"])

    # Combine make and model for concise labels
    df["evaluator"] = df["evaluator_make"] + ":" + df["evaluator_model"]
    df["target"] = df["target_make"] + ":" + df["target_model"]

    # --- 1. Statistical Summary ---
    print("Statistical Summary of Scores and Counts:")
    print(df[["score", "true_count", "partially_true_count", "opinion_count",
              "partially_false_count", "false_count"]].describe())

    # --- 2. Correlation Analysis ---
    print("\nCorrelation Matrix (Counts vs Score):")
    correlation_matrix = df[["true_count", "partially_true_count", "opinion_count",
                             "partially_false_count", "false_count", "score"]].corr()
    print(correlation_matrix)

    # Visualize correlation with a heatmap
    plt.figure(figsize=(8, 6))
    sns.heatmap(correlation_matrix, annot=True, cmap="coolwarm", vmin=-1, vmax=1)
    plt.title("Correlation Between Counts and Score")
    plt.show()

    # --- 3. Visualization ---
    # Heatmap of scores (evaluator vs target)
    plt.figure(figsize=(10, 8))
    pivot_scores = df.pivot_table(index="evaluator", columns="target", values="score")
    sns.heatmap(pivot_scores, annot=True, cmap="YlGnBu", fmt=".2f")
    plt.title("Score Heatmap: Evaluator vs Target")
    plt.xlabel("Target Model")
    plt.ylabel("Evaluator Model")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.show()

    # Bar plot of average scores by evaluator and target
    plt.figure(figsize=(12, 6))
    sns.barplot(x="evaluator", y="score", hue="target", data=df)
    plt.title("Average Score by Evaluator and Target")
    plt.xlabel("Evaluator")
    plt.ylabel("Average Score")
    plt.xticks(rotation=45, ha="right")
    plt.legend(title="Target Model", bbox_to_anchor=(1.05, 1), loc="upper left")
    plt.tight_layout()
    plt.show()

    # --- 4. Outlier Detection ---
    # Using Z-scores to detect outliers in 'score'
    df["score_z"] = np.abs(stats.zscore(df["score"]))
    outliers = df[df["score_z"] > 2]  # Threshold of 2 standard deviations
    print("\nOutliers in Score (Z-score > 2):")
    print(outliers[["evaluator", "target", "score", "score_z"]])

    # --- 5. Pivot Table ---
    print("\nPivot Table of Scores (Evaluator vs Target):")
    pivot_table = df.pivot_table(index="evaluator", columns="target", values="score", aggfunc="mean")
    print(pivot_table)


def print_basics(df):
    # Display the first few rows of the DataFrame
    print("First 5 rows of the DataFrame:")
    print(df.head())

    # Basic Analysis Examples
    print("\nAverage score by evaluator:")
    print(df.groupby(["evaluator_make", "evaluator_model"])["score"].mean())

    print("\nAverage score by target model:")
    print(df.groupby(["target_make", "target_model"])["score"].mean())

    # Optional: Drop the 'summary' column if not needed for analysis
    df = df.drop(columns=["summary"])
    print("\nDataFrame without summary column:")
    print(df.head())


def main():
    flattened_data = get_flattened_fc_data(json_data)
    # Create a Pandas DataFrame
    df = pd.DataFrame(flattened_data)

    # print_basics(df)
    analysis_plots(df)


if __name__ == "__main__":
    main()
