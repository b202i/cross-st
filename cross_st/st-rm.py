#!/usr/bin/env python3
"""
## st-rm — Remove items from a story container

Deletes data items, stories, or fact-check reports from a .json container.
Supports bulk-clearing all fact-checks and claim segments from one story or
every story in the container.

```
st-rm -s 3 subject.json              # remove story 3
st-rm -d 2 subject.json              # remove data item 2
st-rm -s 2 -f 1 subject.json         # remove fact-check 1 from story 2
st-rm -F -s 2 subject.json           # clear all fact-checks from story 2
st-rm -F --all-stories subject.json  # clear all fact-checks from every story
```

All index arguments are 1-based, matching the output of st-ls.

Options: -d data  -s story  -f fact  -F clear-facts  --all-stories  -v  -q
"""

import argparse
import json
import os
import sys
from mmd_startup import require_config


def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-rm',
        description='Remove items from a story container')
    parser.add_argument('json_file', type=str,
                        help='Path to the JSON file', metavar='file.json')
    parser.add_argument('-d', '--data', type=int,
                        help='Remove a data item (integer index)')
    parser.add_argument('-s', '--story', type=int,
                        help='Remove a story (integer index)')
    parser.add_argument('-f', '--fact', type=int,
                        help='Remove a fact-check report from a story (integer index)')
    parser.add_argument('-F', '--clear-facts', action='store_true',
                        help='Clear all fact-checks (and segments) from a story (-s) or all stories')
    parser.add_argument('--all-stories', action='store_true',
                        help='Apply --clear-facts to every story in the container')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Enable minimal output')

    args = parser.parse_args()

    # Warn early if no action was requested
    action_requested = any([
        args.data is not None, args.story is not None,
        args.fact is not None, args.clear_facts
    ])
    if not action_requested:
        print("No action specified. Use -d, -s, -f, or -F.")
        print("Run 'st-rm --help' for usage.")
        sys.exit(1)

    file_prefix = args.json_file.rsplit('.', 1)[0]  # Split from the right, only once
    file_json = file_prefix + ".json"
    main_container_updated = False

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

    # Remove an item from list of data in the container
    if args.data is not None:
        if "data" not in main_container:
            print("No data items")
        else:
            length = len(main_container["data"])
            if 1 <= args.data <= length:
                rm_item = main_container["data"][args.data - 1]
                main_container["data"].remove(rm_item)
                if not args.quiet:
                    print(f"Data item {args.data} removed")
                main_container_updated = True
            else:
                print(f"Data item out of range: {args.data}")

    # Remove an item from list of stories in the container
    # Guard against -F -s N: that means "clear facts from story N", not "delete story N"
    if args.story is not None and args.fact is None and not args.clear_facts:
        if "story" not in main_container:
            print("No story items")
        else:
            length = len(main_container["story"])
            if 1 <= args.story <= length:
                rm_item = main_container["story"][args.story - 1]
                main_container["story"].remove(rm_item)
                if not args.quiet:
                    print(f"Story {args.story} removed")
                main_container_updated = True
            else:
                print(f"Story item out of range: {args.story}")

    # Remove fact-check report from a specific story in the container
    if args.fact is not None:
        if args.story is None:
            print("Story index not provided, try -s 1?")
            sys.exit(1)
        if "story" not in main_container:
            print(f"No stories in {file_json}")
            sys.exit(1)
        length = len(main_container["story"])
        if not (1 <= args.story <= length):
            print(f"Story item out of range: {args.story}")
            sys.exit(1)
        story = main_container["story"][args.story - 1]
        if "fact" not in story:
            print(f"Story {args.story} has no fact-checks")
            print(f"To inspect a container, try: st-ls {file_json}")
            sys.exit(1)
        facts = story.get("fact")
        if args.fact < 1 or args.fact > len(facts):
            print(f"Fact item out of range: {args.fact}")
            sys.exit(1)
        fact = facts[args.fact - 1]
        facts.remove(fact)
        if not args.quiet:
            print(f"Removed: s:{args.story} f:{args.fact} from {file_json}")
        main_container_updated = True

    # Clear all fact-checks and segments from one story or all stories
    if args.clear_facts:
        stories = main_container.get("story", [])
        if not stories:
            print("No stories in container.")
        elif args.all_stories:
            for i, s in enumerate(stories, 1):
                n = len(s.get("fact", []))
                s["fact"] = []
                s["segments"] = []
                if not args.quiet:
                    print(f"  Cleared story {i}: {s.get('make')}/{s.get('model')} ({n} facts)")
            main_container_updated = True
        elif args.story is not None:
            if not (1 <= args.story <= len(stories)):
                print(f"Story item out of range: {args.story}")
                sys.exit(1)
            s = stories[args.story - 1]
            n = len(s.get("fact", []))
            s["fact"] = []
            s["segments"] = []
            if not args.quiet:
                print(f"  Cleared story {args.story}: {s.get('make')}/{s.get('model')} ({n} facts)")
            main_container_updated = True
        else:
            print("Specify a story with -s N or use --all-stories to clear all.")
            sys.exit(1)

    if main_container_updated:
        with open(file_json, 'w', encoding='utf-8') as f:
            json.dump(main_container, f, ensure_ascii=False, indent=4)
        if not args.quiet:
            print(f"Container updated: {file_json}")


if __name__ == "__main__":
    main()
