#!/usr/bin/env python3
"""
## st-ls — List the contents of a story container

List stories, data, and fact-checks inside a `.json` container.
Default shows the story table — a quick overview of all stories and their
fact-check scores, much like the Linux `ls` command gives a directory listing.
Use `-a` / `--all` to show every section, or combine flags as needed.

Run after:  st-gen   (generated your first story)
            st-bang  (generated from all AI providers)
            st-cross (ran the cross-product fact-check)
            st-fact  (ran a single fact-check)
Run before: st-print  (preview or print a story)
            st-fact   (fact-check a story)
            st-cross  (cross-check all stories)
            st-post   (publish a story)

```
st-ls subject.json              # default: story table (titles, scores, flags)
st-ls -a subject.json           # show all: data, stories, fact-checks, claims
st-ls --data subject.json       # raw API data items only
st-ls --fact subject.json       # fact-check summary table
st-ls -C subject.json           # cross-AI claims comparison table
st-ls --fact -C subject.json    # fact-check table + claims
```

## Story table columns

| Column | Meaning |
|--------|---------|
| S      | Story index (use with -s N in other commands) |
| Flag   | Story origin: blank = original AI output; [fix:patch/best/synth] = improved by st-fix; [merge] = synthesized by st-merge |
| Segs   | Number of fact-checkable segments extracted from the story |
| Score  | Average fact-check score across all evaluators (higher = more accurate; max 200 for 10 claims at 20 pts each) |

Run `st-fact` or `st-cross` to populate the Score column.

## See also

- st-fact   — fact-check a single story against one AI evaluator
- st-cross  — cross-product N×N fact-check (every AI checks every story)
- st-read   — display the full text of a story
- st-cat    — dump the raw JSON container

Options: -d data  -s story  -f fact  -C claims  -c clip-length  -a all
"""

import argparse
import json
import os
import sys
from mmd_startup import require_config
from tabulate import tabulate

from ai_handler import get_data_title

model_clip = 17  # shorten model names to 'claude-3-7-sonnet'


def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-ls',
        description='List the contents of a JSON container')
    parser.add_argument('json_file', type=str,
                        help='Path to the JSON file', metavar='file.json')
    parser.add_argument('-a', '--all', action='store_true', default=False,
                        help='Display all sections: data, stories, fact-checks, and claims')
    parser.add_argument('-d', '--data', action='store_true',
                        help='Display container data')
    parser.add_argument('-s', '--story', action='store_true',
                        help='Display container stories')
    parser.add_argument('-f', '--fact', action='store_true',
                        help='Display container fact-check data')
    parser.add_argument('-C', '--claims', action='store_true',
                        help='Display cross-AI claims comparison table (seg x AI verdict)')
    parser.add_argument('-c', '--clip', type=int, default=60,
                        help='Clip title length (integer), default 60')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output, default is verbose')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Enable minimal output')

    args = parser.parse_args()
    file_prefix = args.json_file.rsplit('.', 1)[0]  # Split from the right, only once
    file_json = file_prefix + ".json"

    # Default (no flags): show stories only — like `ls` for a directory
    if not (args.data or args.story or args.fact or args.claims or args.all):
        args.story = True

    if args.all:
        args.data = True
        args.story = True
        args.fact = True
        args.claims = True

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

    # Display the detailed list of data in the container
    # Data is stored in native formats, must be extracted
    newline = ""
    if args.data:
        if "data" not in main_container or len(main_container["data"]) == 0:
            print("data list empty")
        else:
            print("DATA")
            newline = "\n"
            story_data = []
            for i, data in enumerate(main_container["data"], start=1):
                make = data.get("make")
                model = (data.get("model") or "")[:model_clip]
                try:
                    title = get_data_title(make, data)
                except Exception:
                    title = data.get("mode", "(fix/merge entry)")
                story_data.append([i, make, model, title[:args.clip]])
            print(tabulate(story_data, headers=["D", "Make", "Model", "Raw Title"], tablefmt="github"))

    stories = main_container.get("story", [])

    if not stories:
        print("Story list empty")
    else:
        story_data = []
        fact_data = []
        for i, story in enumerate(main_container["story"], start=1):
            fix_mode   = story.get("fix_mode", "")
            merge_mode = story.get("merge_mode", "")

            # Short flag labels — keep them terse so the column stays narrow
            _FIX_LABEL = {
                "patch":       "fix:patch",
                "best-source": "fix:best",
                "synthesize":  "fix:synth",
            }
            _MERGE_LABEL = {
                "quality": "merge",
                "simple":  "merge:simple",
            }
            if fix_mode:
                flag = f"[{_FIX_LABEL.get(fix_mode, fix_mode)}]"
            elif merge_mode:
                sources = story.get("merge_sources", [])
                src_str = f":{sources[0]}-{sources[-1]}" \
                    if sources and sources == list(range(sources[0], sources[-1]+1)) \
                    else (":" + ",".join(str(s) for s in sources) if sources else "")
                label = _MERGE_LABEL.get(merge_mode, merge_mode)
                flag = f"[{label}{src_str}]"
            else:
                flag = ""
            n_segs = len(story.get("segments") or [])
            segs_str = str(n_segs) if n_segs else "-"

            # Avg fact-check score across all fact entries for this story
            fact_scores = [f.get("score") for f in story.get("fact", [])
                           if f.get("score") is not None]
            avg_score_str = f"{sum(fact_scores)/len(fact_scores):.2f}" \
                if fact_scores else "-"

            story_data.append([
                i,
                story.get("make"),
                story.get("model")[:model_clip],
                flag,
                segs_str,
                avg_score_str,
                story.get("title")[:args.clip]
            ])
            for j, fact in enumerate(story.get("fact", []), start=1):
                counts = fact.get("counts") or [0, 0, 0, 0, 0]
                score  = fact.get("score")
                fact_score = f"{score:>7.2f}" if score is not None else "   n/a"
                n_claims = len(fact.get("claims") or [])
                fact_data.append([
                    i,
                    j,
                    fact.get("make"),
                    fact.get("model")[:model_clip],
                    counts[0],  # True
                    counts[1],  # Mostly True
                    counts[2],  # Opinion
                    counts[3],  # Mostly False
                    counts[4],  # False
                    fact_score,
                    n_claims if n_claims else "-",
                ])

        if args.story:
            print(f"{newline}STORY")
            newline = "\n"
            print(tabulate(story_data,
                           headers=["S", "Make", "Model", "Flag", "Segs", "Score", "Title"],
                           tablefmt="github"))

        if args.fact and len(fact_data) > 0:
            print(f"{newline}FACT CHECK")
            newline = "\n"
            headers = ["S", "F", "Make", "Model", "True", "M.True", "Opinion", "M.False", "False", "Score", "Claims"]
            print(tabulate(fact_data, headers=headers, tablefmt="plain"))

        if args.fact and len(fact_data) == 0:
            print("No fact-check records")

        if args.claims:
            print(f"{newline}CLAIMS")
            newline = "\n"
            for i, story in enumerate(main_container["story"], start=1):
                facts = story.get("fact", [])
                if not facts:
                    continue

                # Build per-AI label and seg_id -> claim lookup
                ai_labels = []
                ai_claims = []   # list of dicts: seg_id -> claim entry
                for fact in facts:
                    label = f"{fact.get('make','?')}/{(fact.get('model') or '')[:model_clip]}"
                    by_seg = {}
                    for claim in (fact.get("claims") or []):
                        sid = claim.get("seg_id")
                        if sid is not None:
                            by_seg[sid] = claim
                    ai_labels.append(label)
                    ai_claims.append(by_seg)

                # Collect all seg_ids in order across all checkers
                all_seg_ids = sorted(set(
                    sid
                    for by_seg in ai_claims
                    for sid in by_seg
                ))

                if not all_seg_ids:
                    print(f"\n  Story {i}: no structured claims yet")
                    continue

                # Build segment text index from story["segments"]
                seg_text = {
                    seg.get("id"): seg.get("text", "")
                    for seg in (story.get("segments") or [])
                }

                title = (story.get("title") or "")[:args.clip]
                make  = story.get("make", "")
                model = (story.get("model") or "")[:model_clip]
                print(f"\n  Story {i}: [{make}/{model}] {title}")

                rows = []
                for sid in all_seg_ids:
                    text_clip = seg_text.get(sid, "")[:48]
                    row = [sid, text_clip]
                    for by_seg in ai_claims:
                        claim = by_seg.get(sid)
                        row.append(claim.get("verdict", "-") if claim else "-")
                    rows.append(row)

                headers = ["Seg", "Segment"] + ai_labels
                print(tabulate(rows, headers=headers, tablefmt="plain"))


if __name__ == "__main__":
    main()
