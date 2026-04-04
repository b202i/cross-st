#!/usr/bin/env python3
"""
st-analyze — Analyze cross-product data and synthesize a new story

```
st-analyze subject.json                 # analyze and synthesize
st-analyze --ai gemini subject.json     # use a specific provider
st-analyze --plot bar subject.json      # include a bar chart
```

Options: --ai  --plot  --post  --no-cache  -v  -q
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from mmd_startup import require_config, load_cross_env
import pandas as pd
from ai_handler import process_prompt, get_ai_list, get_content, get_ai_model, \
    get_default_ai
from dotenv import load_dotenv
from mmd_data_analysis import get_flattened_fc_data
from discourse import get_discourse_slugs_sites
from mmd_branding import get_speaking_tagline, get_tagline_for_reading
from mmd_for_speaking import for_speaking
from mmd_plot import post_plot, get_analysis_plot_types, tag_mapper
from mmd_process_report import remove_markdown, remove_story_break, get_hashtags, remove_hashtags, \
    clean_newlines_preserve_paragraphs, extract_title, edit_title, embed_plot_url

cross_heat_map_figure_1 = "cross_heat_map_figure_1"
cross_bar_score_evaluator_figure_2 = "cross_bar_score_evaluator_figure_2"
cross_bar_score_target_figure_3 = "cross_bar_score_target_figure_3"

"""
Using AI, perform an analysis on Cross-Product data and produce a report.
In the .json container, this action creates a new 'data' and a new 'story' item.
The story item can be treated like any other story item, to be edited,
and posted, even converted to audio although not as useful given all of
the tabular data.

The analysis report is created in companion with the st-plot capability,
a visualization of the cross-product matrix and data. Each plot is designed
to view the data a different way.
For each sub-analysis:
1. Present data to be used in a single plot/visualization of the data.
2. Ask the AI to describe what the data and plot mean.
Review the sub-analysis results as a group, identify which sub-analysis stand out
being particuallry useful.
In the summary, mention the one or two best sub-analysis, and why.
"""


def get_prompt(data_frame, prompt_from_file, story_titles, fact_check_raw):
    prompt = f"""
You are an AI designed to analyze data and provide insights. 
I have a dataset of fact-checking scores where different AI models evaluate each other’s outputs. 
Each row represents an evaluation, with columns:
- evaluator_make: The company of the evaluating model (e.g., "openai").
- evaluator_model: The specific evaluating model (e.g., "gpt-4o").
- target_make: The company of the model being evaluated.
- target_model: The specific model being evaluated.
- true_count: Number of "True" ratings.
- partially_true_count: Number of "Partially True" ratings.
- opinion_count: Number of "Opinion" ratings.
- partially_false_count: Number of "Partially False" ratings.
- false_count: Number of "False" ratings.
- score: A numerical fact-check score (higher is better).

Here’s the data in CSV format:
    {data_frame.to_csv()}

1. In a single paragraph provide a overview of what the report is about, 
define what this cross-product experiment is and a bit about the domain
of the reports under study. You can infer this from the report titles.

2. After the overview paragraph, walk the reader through the process 
of scoring: The fact-check score represents the average evaluation of 
all statements in a report. Each statement is scored as follows: 2 points 
for true, 1 point for mostly true, 0 points for opinion (excluded from 
the average), -1 point for mostly false, and -2 points for false. 
For every statement in the document, the AI will restate it and provide 
a detailed explanation justifying the assigned score.

3. After the overview paragraph, insert a heading ## 3. Score Heatmap: Evaluator vs Target
Next, insert the tag \'{cross_heat_map_figure_1}\' on a line by itself. 
This tag will be replaced with the heatmap graphic plot.
Immediately after the tag, write a caption for the plot (100–160 words, 2 paragraphs).

HOW TO READ THE HEATMAP:
- A uniformly dark COLUMN means all evaluators rated that AI's stories as consistently truthful.
- A uniformly light COLUMN means all evaluators were skeptical of that AI's stories.
- A dark ROW means that evaluator is lenient; a light ROW means that evaluator is strict.
- A consistently dark DIAGONAL means self-promotion bias (AIs grade their own work higher).
- A flat or light diagonal means no such bias — AIs are as demanding of themselves as others.

Paragraph 1: Interpret the COLUMN and ROW patterns — which target AI's column is darkest
(trusted by all) and which is lightest (skeptical by all). Which evaluator row is strictest.
Do not just cite the single highest/lowest cell value; explain what the overall column/row
shade says about each AI's reliability in this domain.
Paragraph 2: Interpret the DIAGONAL. State clearly whether self-promotion bias is present or absent.
Name one standout outlier cell and use the count data to explain why it looks different.
Close with one practical implication for choosing an AI in this domain.
Make reference to 'The Heatmap in Figure 1' as necessary.
Throughout the report, when referencing data, please round the data to 1 decimal place.

4. Insert the AI prompt used to generate the reports. 
Use a heading ## 4. AI Prompt Used to Generate Each Report
Paste into report using markdown '> ' for each line. 
> {prompt_from_file}
The caption under the table reads something like: 
"This prompt was used for each AI under study"
Provide some pithy insights into the caption if you like.

5. Insert a table of Report Titles, 
Use a heading ## 5. Table of Report Titles
just paste this into the report using markdown text-block.
```text
{story_titles}
```
The caption under the table reads something like: 
"Make, Model and Report Title used for this analysis."

6. Insert a table of raw fact-check data, just paste this into the report using markdown text-block.
## 6. Fact-Check Raw Data
```text
{fact_check_raw}
```
The caption under the table reads something like: 
"Raw cross-product data for the analysis. Each AI fact-checks stories from each AI, including themselvesi."
Provide some pithy insights into the caption if you like.

7. ## 7. Average Score By Evaluator
Insert the tag \'{cross_bar_score_evaluator_figure_2}\' on a line by itself.
It represents a bar graph of how the evaluators (fact-checkers) performed
across each story/report.
Immediately after the tag, write a caption for the plot. 
Which evaluator model tends to give the highest and lowest average scores?
What other pithy insights do you have about this data and figure?
You may reference Figure 2 throughout the report as Evaluator Bar Chart in Figure 2
or just Figure 2, throughout the report.

8. ## 8. Average Score By Target
Insert the tag \'{cross_bar_score_target_figure_3}\' on a line by itself.
It represents a bar graph of how the target (report-writers) performed
across each story/report.
Immediately after the tag, write a caption for the plot. 
Which target model is rated most favorably and least favorably on average?
What other pithy insights do you have about this data and figure?
You may reference Figure 3 throughout the report as Target Bar Chart in Figure 3
or just Figure 3, throughout the report.

## Detailed Analysis
9. Are there any noticeable patterns or biases (e.g., does an evaluator rate itself higher)?
10. How do the counts (true, partially_true, etc.) relate to the score? Are there strong correlations?
11. Identify any outliers or anomalies in the scores and suggest possible reasons.
12. Provide a concise and informative report summary.
Return your analysis in a clear, structured format with explanations.
Make sure to include a pithy and informative title for the report.
    """
    return prompt.strip()


def main():
    require_config()
    slugs, sites = get_discourse_slugs_sites()
    default_site = slugs[0] if slugs else None

    parser = argparse.ArgumentParser(
        prog='st-analyze',
        description='Analyze cross product-data. Produce a new data item and a new story item.')
    parser.add_argument('json_file', type=str,
                        help='Path to the JSON file', metavar='file.json')
    parser.add_argument('--ai', type=str, choices=get_ai_list(), default=get_default_ai(),
                        help=f'Define AI to use, default is {get_default_ai()}')
    parser.add_argument('--cache', dest='cache', action='store_true', default=True,
                        help='Enable API cache, default: enabled')
    parser.add_argument('--no-cache', dest='cache', action='store_false',
                        help='Disable API cache')
    parser.add_argument('--site', type=str, choices=slugs or None, default=default_site,
                        help=f"Select Discourse site to use, default is {default_site}")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output, default is verbose')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Enable minimal output')

    args = parser.parse_args()
    if args.verbose:
        print(f"st-analyze args: {args}")

    file_prefix = args.json_file.rsplit('.', 1)[0]  # Split from the right, only once
    file_json = file_prefix + ".json"
    file_prompt = file_prefix + ".prompt"

    # Use realpath to get the actual path of the script
    load_cross_env()

    container_modified = False
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

    if not os.path.isfile(file_prompt):
        print(f"Error: The file {file_prompt} does not exist.")
        sys.exit(1)
    with open(file_prompt, 'r') as infile:
        prompt_from_file = infile.read()

    cmd = f"st-ls -s --clip 100 {file_json}".split()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )
    story_titles = result.stdout

    cmd = f"st-ls -f {file_json}".split()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )
    fact_check_raw = result.stdout

    flattened_data = get_flattened_fc_data(main_container)
    num_fc = len(flattened_data)
    if not args.quiet:
        print(f"Number of fact-checks: {num_fc}")
    if num_fc < 2:
        print(f"\nError: Analysis requires at least 2 fact-checks, found {num_fc} in {args.json_file}")
        print(f"Please run the cross-product fact-check first:")
        print(f"  st-cross {args.json_file}")
        print(f"\nAfter the cross-product completes, you can analyze the results with:")
        print(f"  st-analyze {args.json_file}")
        sys.exit(1)

    # Create a Pandas DataFrame
    df = pd.DataFrame(flattened_data)
    # Drop the 'summary' column for analysis (only present in flattened data when fact-checks exist)
    if "summary" in df.columns:
        df = df.drop(columns=["summary"])

    prompt = get_prompt(df, prompt_from_file, story_titles, fact_check_raw)

    # Single AI call — can take 30–90 seconds depending on model and load.
    # Show a live elapsed timer so the user knows it's working.
    _result: dict = {}
    _exc: list = []

    def _run_prompt():
        try:
            _result["value"] = process_prompt(args.ai, prompt, verbose=args.verbose, use_cache=args.cache)
        except Exception as e:
            _exc.append(e)

    ai_model_name = get_ai_model(args.ai)
    if not args.quiet:
        print(f"  Generating analysis report: {args.ai} / {ai_model_name}")

    _thread = threading.Thread(target=_run_prompt, daemon=True)
    _t0 = time.time()
    _thread.start()

    if not args.quiet:
        _spin = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        _i = 0
        while _thread.is_alive():
            elapsed = time.time() - _t0
            mins, secs = divmod(int(elapsed), 60)
            print(f"\r  {_spin[_i % len(_spin)]}  {mins:02d}:{secs:02d}", end="", flush=True)
            _i += 1
            time.sleep(0.1)
        elapsed = time.time() - _t0
        mins, secs = divmod(int(elapsed), 60)
        print(f"\r  ✓  {mins:02d}:{secs:02d}  ({args.ai})", flush=True)
    else:
        _thread.join()

    if _exc:
        print(f"Error during analysis: {_exc[0]}", file=sys.stderr)
        sys.exit(1)

    gen_payload, client, response, ai_model = _result["value"]

    # THe user can edit a paragraph that is inserted into the prompt and report

    # Follow the same process as st-gen and st-prep,
    # Append (if unique) the data to the json container,
    # and append (if unique) the story to the json container.
    data = {
        "make": args.ai,
        "model": get_ai_model(args.ai),
        "prompt": prompt,
        "gen_payload": gen_payload,
        "gen_response": response,
    }
    # Create an MD5HASH to test for duplicates
    data_str = json.dumps(data, sort_keys=True)
    md5_hash = hashlib.md5(data_str.encode('utf-8')).hexdigest()
    data["md5_hash"] = md5_hash

    duplicate_index = None
    # Test for duplicates
    for index, existing_data in enumerate(main_container["data"], start=1):
        existing_hash = existing_data.get("md5_hash")
        if existing_hash == md5_hash:
            duplicate_index = index
            if not args.quiet:
                print("Data item already exists, did not add duplicate")
            break  # No need to check further if a duplicate is found
    if duplicate_index is None:
        main_container["data"].append(data)
        container_modified = True
        if not args.quiet:
            print("Added new analysis data")

    all_raw_story_text = get_content(args.ai, response)
    make = args.ai
    model = get_ai_model(make)

    # Massage select raw data into a publishable story
    file_md_content = remove_story_break(all_raw_story_text)

    select_hashtags = get_hashtags(file_md_content)

    # Plain text for audio translation and non MD social media
    hashless_story = remove_hashtags(file_md_content)
    no_md = remove_markdown(hashless_story)
    speaking_tagline = get_speaking_tagline(make, model)
    as_spoken = for_speaking(no_md, args.verbose) + "\n\n" + speaking_tagline

    ai_tag_reading = get_tagline_for_reading(make, model)
    clean_paragraphs = clean_newlines_preserve_paragraphs(no_md)
    file_txt_content = clean_paragraphs + "\n\n" + ai_tag_reading

    # Integrate graphical plots into the report
    # 1. Generate the plots, save file_kv for posting to discourse
    cmd = f"st-plot --file_kv {file_json}".split()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )
    file_kv = json.loads(result.stdout)
    if not args.quiet:
        print(f"Plots created: {file_kv.keys()}")
    # 2. Upload plots to discourse, save url_kv for insertion into the report
    # key is plot type : value is url of the plot
    url_kv = post_plot(args.site, file_kv, args.verbose)

    # 3. Map from plot:url to tag:md_url
    # The tag is descriptive to help the AI, md_url displays plot in md
    evaluator_v_target, bar_score_evaluator, bar_score_target = get_analysis_plot_types()
    tag_kv = {
        # key is the tag in AI prompt : value is plot type
        cross_heat_map_figure_1: evaluator_v_target,
        cross_bar_score_evaluator_figure_2: bar_score_evaluator,
        cross_bar_score_target_figure_3: bar_score_target
    }

    # Replace the plot type with the plot url
    # key is the md tag : value is the url of the plot
    md_kv = tag_mapper(tag_kv, url_kv)

    file_md_content = embed_plot_url(file_md_content, md_kv)
    file_md_content += "\n\n" + ai_tag_reading

    file_title_content = extract_title(file_txt_content)
    file_title_content = edit_title(file_title_content)  # Clean title, remove "Title:"
    title_words = file_title_content.split()
    if not args.quiet:
        if len(title_words) < 4:
            print(f"Title very short: {file_title_content}")
        elif len(title_words) > 13:
            print(f"Title very long: {file_title_content}")
        elif len(title_words) > 9:
            print(f"Title long: {file_title_content}")
        else:
            print(f"Title: {file_title_content}")

    # Build a new story dictionary from the provided components.
    story = {
        "make": make,
        "model": model,
        "title": file_title_content,
        "markdown": file_md_content,
        "text": file_txt_content,
        "spoken": as_spoken,
        "hashtags": select_hashtags,
        "fact": [],
    }
    # Create an MD5HASH and save it to test for duplicates
    story_str = json.dumps(story, sort_keys=True)
    md5_hash = hashlib.md5(story_str.encode('utf-8')).hexdigest()
    story["md5_hash"] = md5_hash

    # Ensure that main_container has a 'story' key with an empty list
    if "story" not in main_container:
        main_container["story"] = []

    duplicate_index = None
    for index, existing_story in enumerate(main_container["story"], start=1):
        existing_hash = existing_story.get("md5_hash")
        if existing_hash == md5_hash:
            duplicate_index = index
            break  # No need to check further if a duplicate is found
    if duplicate_index is None:
        main_container["story"].append(story)
        container_modified = True
        if not args.quiet:
            print("Added new story")
    else:
        if args.verbose:
            print("Story already exists; not adding duplicate")

    if container_modified:
        with open(file_json, 'w', encoding='utf-8') as f:
            json.dump(main_container, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        if not args.quiet:
            print(f"Story container updated: {file_json}")


if __name__ == "__main__":
    main()
