#!/usr/bin/env python3
"""
## st-cat — Print story container fields to stdout

Reads a single story (or fact-check) from a .json container and prints the
requested field(s) to standard output.  Useful for piping story text into
other tools or shell scripts.

```
st-cat -t subject.json              # print title of story 1
st-cat --markdown -s 3 subject.json # print markdown of story 3
st-cat -f 2 -s 1 subject.json       # print fact-check report 2 from story 1
st-cat --text -s 2 subject.json     # print plain text body of story 2
```

Options: -s story  -f fact  --title  --text  --markdown  --hashtags  --spoken
"""

import argparse
import json
import os
import sys
from mmd_startup import require_config


def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-cat',
        description="Read elements of a .json container and print to standard out.")
    parser.add_argument('json_file', type=str,
                        help='Path to the JSON file', metavar='file.json')
    parser.add_argument('-s', '--story', type=int, default=1,
                        help='Story number (integer), default: 1')
    parser.add_argument('-f', '--fact', type=int,
                        help='Fact-check report number (integer), default: none')
    parser.add_argument('--markdown', action='store_true',
                        help='Story markdown, default: off')
    parser.add_argument('--hashtags', action='store_true',
                        help='Story hashtags, default: off')
    parser.add_argument('--spoken', action='store_true',
                        help='Story spoken text, default: off')
    parser.add_argument('--text', action='store_true',
                        help='Story text body, default: off')
    parser.add_argument('-t', '--title', action='store_true',
                        help='Story title, default: off')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output, default: off')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Enable minimal output')
    args = parser.parse_args()

    # Warn early if no output field was requested
    output_requested = any([
        args.title, args.text, args.markdown,
        args.hashtags, args.spoken, args.fact is not None
    ])
    if not output_requested:
        print("No output field specified. Use --title, --text, --markdown, "
              "--hashtags, --spoken, or -f <n>.")
        print("Run 'st-cat --help' for usage.")
        sys.exit(1)

    file_prefix = args.json_file.rsplit('.', 1)[0]  # Split from the right, only once
    file_json = file_prefix + ".json"

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

    if args.verbose:
        print(f"Loaded: {file_json}", file=sys.stderr)

    # Confirm story parameter, get story
    length = len(main_container.get("story", []))
    if 1 <= args.story <= length:
        select_story = main_container["story"][args.story - 1]
    else:
        if not args.quiet:
            print(f"Story item out of range: {args.story}")
        sys.exit(1)

    if args.title:
        print(select_story.get("title"))

    if args.text:
        print(select_story.get("text"))

    if args.spoken:
        print(select_story.get("spoken"))

    if args.markdown:
        print(select_story.get("markdown"))

    if args.hashtags:
        print(select_story.get("hashtags"))

    if args.fact is not None:
        length = len(select_story.get("fact", []))
        if 1 <= args.fact <= length:
            fact_obj = select_story["fact"][args.fact - 1]
            fact_report = fact_obj.get("report")
            print(fact_report)
        else:
            if not args.quiet:
                print(f"Fact item out of range: {args.fact}")
            sys.exit(1)


if __name__ == "__main__":
    main()
