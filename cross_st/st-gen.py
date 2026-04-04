#!/usr/bin/env python3
"""
st-gen — Generate a report from a prompt

Submits your prompt to your default AI provider, saves the response, and runs
st-prep automatically — so the story is polished and ready to read straight away.

Run after:  st-new   (create the prompt file)
Run before: st-ls    (review what was generated)
            st-fact  (fact-check the story)
            st-cross (cross-check against other AI providers)
            st-print (preview or print the story)

```
st-gen subject.prompt                   # generate with default AI (runs st-prep automatically)
st-gen --ai gemini subject.prompt       # use a specific provider
st-gen --no-cache subject.prompt        # bypass API cache
st-gen --no-prep subject.prompt         # store raw data only, skip st-prep
```

Options: --ai  --no-cache  --no-prep  --bang  -v  -q
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from mmd_startup import require_config, load_cross_env

from ai_handler import process_prompt, get_ai_list, get_default_ai, get_usage, check_api_key, get_content

from mmd_util import create_block_file, tmp_safe_name, get_tmp_dir

USE_CACHE = True


def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-gen',
        description='Generate a report from a prompt')

    # Define positional argument for prompt file
    parser.add_argument('prompt', nargs='?', type=str,
                        help='Path to the prompt file')
    parser.add_argument('--ai', type=str, choices=get_ai_list(), default=get_default_ai(),
                        help=f'Define AI model to use, default is {get_default_ai()}')
    parser.add_argument('--cache', dest='cache', action='store_true', default=True,
                        help='Enable API cache, default: enabled')
    parser.add_argument('--no-cache', dest='cache', action='store_false',
                        help='Disable API cache')
    parser.add_argument('--no-prep', dest='prep', action='store_false',
                        help='Skip st-prep after generation (default: st-prep runs automatically)')
    parser.set_defaults(prep=True)
    parser.add_argument('--bang', type=int, default=-1,
                        help='Parallel AI execution, 0 is first thread, default -1 is serial execution')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output, default is verbose')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Enable minimal output')
    args = parser.parse_args()

    # The user can define an output prefix, otherwise default to the prompt prefix
    file_prefix = args.prompt.rsplit('.', 1)[0]  # Split from the right, only once
    file_prompt = file_prefix + ".prompt"

    if args.bang >= 0:
        # Write bang temp file into tmp/ so it is excluded by .gitignore
        # and never left as a stray file in the story directory
        tmp_dir = get_tmp_dir()
        bang_name = os.path.basename(file_prefix) + "_" + str(args.bang) + ".json"
        file_json = str(tmp_dir / bang_name)
        create_block_file(tmp_safe_name(file_json), args.verbose)
    else:
        file_json = file_prefix + ".json"

    if not args.quiet:
        print(f"Generating story from {file_prefix}.prompt, with AI: {args.ai}, outputting to {file_json}")

    # Use realpath to get the actual path of the script
    load_cross_env()

    _paths_checked = [os.path.expanduser("~/.crossenv"),
                      os.path.join(os.path.dirname(os.path.realpath(__file__)), ".env"),
                      os.path.join(os.getcwd(), ".env")]
    if not check_api_key(args.ai, _paths_checked):
        sys.exit(1)

    gen_response = ""
    try:
        if not os.path.isfile(file_prompt):
            print(f"Error: The file {file_prompt} does not exist.")
            sys.exit(1)
        with open(file_prompt, 'r') as infile:
            prompt_from_file = infile.read()

        if args.verbose:
            print(f"Submitting AI request: {args.ai}")

    except FileNotFoundError:
        print(f"Error: The file {file_prompt} was not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"AI: {args.ai}, an error occurred: {e}", file=sys.stderr)
        # TODO manage an error return when called from another script, st-bang
        sys.exit(1)

    # Capture timing data for performance analysis
    start_time = time.time()
    try:
        result = process_prompt(args.ai, prompt_from_file, verbose=args.verbose, use_cache=args.cache)
        # Backward-compatible unpacking
        gen_payload, client, gen_response, ai_model = result
        # Access cache status from wrapper
        was_cached = result.was_cached
    except KeyError:
        print(f"Invalid AI: {args.ai}")
        sys.exit(1)
    except Exception as e:
        print(f"AI: {args.ai}, cached_response error occurred: {str(e)}")
        sys.exit(1)
    end_time = time.time()
    elapsed_seconds = end_time - start_time

    # Guard against empty responses — these can be cached and silently replayed
    content_check = get_content(args.ai, gen_response)
    if not content_check or not content_check.strip():
        print(f"Error: {args.ai} returned an empty response — nothing saved.", file=sys.stderr)
        if was_cached:
            print("  This looks like a stale cache entry.  "
                  "Re-run with --no-cache to force a fresh API call.", file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        print(f"AI response complete: {args.ai}")

    # Append the new data to the container
    if not os.path.isfile(file_json):
        main_container = {"data": []}
        if args.verbose:
            print("Creating new container")
    else:
        with open(file_json, 'r') as file:
            main_container = json.load(file)
        if not args.quiet:
            print("Loaded existing container")

    # Extract token usage via the centralised handler (provider-agnostic)
    usage = get_usage(args.ai, gen_response)
    tokens_input  = usage["input_tokens"]
    tokens_output = usage["output_tokens"]
    tokens_total  = usage["total_tokens"]

    # Calculate tokens per second (avoid division by zero)
    tokens_per_second = round(tokens_total / elapsed_seconds, 2) if elapsed_seconds > 0 else 0
    
    # Build timing object
    timing = {
        "start_time": start_time,
        "end_time": end_time,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "tokens_total": tokens_total,
        "tokens_per_second": round(tokens_per_second, 2),
        "cached": was_cached,
    }
    
    # Combine and restructure data
    data = {
        "make": args.ai,
        "model": ai_model,
        "prompt": prompt_from_file,
        "gen_payload": gen_payload,
        "gen_response": gen_response,
        "timing": timing,
    }
    # Create an MD5HASH and save it to test for duplicates
    data_str = json.dumps(data, sort_keys=True)
    md5_hash = hashlib.md5(data_str.encode('utf-8')).hexdigest()
    data["md5_hash"] = md5_hash

    duplicate_index = None
    # If this is a cache hit, prefer keeping any existing non-cached entry for
    # the same provider+prompt — it has real timing data that would be lost.
    if was_cached:
        for index, existing_data in enumerate(main_container["data"], start=1):
            if (existing_data.get("make") == args.ai
                    and not existing_data.get("timing", {}).get("cached", False)
                    and existing_data.get("prompt", "").strip() == prompt_from_file.strip()):
                duplicate_index = index
                if not args.quiet:
                    print(f"Non-cached entry already exists for {args.ai} — keeping original timing")
                break

    if duplicate_index is None:
        # Test for exact duplicates by MD5
        for index, existing_data in enumerate(main_container["data"], start=1):
            existing_hash = existing_data.get("md5_hash")
            if existing_hash == md5_hash:
                duplicate_index = index
                if not args.quiet:
                    print("Data already exists, did not add duplicate")
                break  # No need to check further if a duplicate is found

    if duplicate_index is None:
        main_container["data"].append(data)
        if args.verbose:
            print("Added new data")

    # Atomic write — prevents corruption when multiple st-gen processes run in parallel
    tmp_json = file_json + ".tmp"
    with open(tmp_json, 'w', encoding='utf-8') as f:
        json.dump(main_container, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_json, file_json)

    data_select = len(main_container["data"])  # last on the list
    # Set up to use more recent generation, even if it is a duplicate,
    # otherwise use the last one on the list
    if duplicate_index is not None:
        data_select = duplicate_index
        print(f"App complete, AI: {args.ai}, duplicate detected, no changes: {file_json}")
    else:
        print(f"App complete, AI: {args.ai}, container updated: {file_json}")

    if args.prep or args.bang >= 0:
        bang_param = ""
        if args.bang >= 0:  # Pass bang along to the next stage
            bang_param = f"--bang {args.bang}"
        cmd = f"st-prep {bang_param} -d {data_select} {file_json}".split()
        subprocess.run(cmd)


if __name__ == "__main__":
    main()
