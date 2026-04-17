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

Options: --ai  --no-cache  --no-prep  --bang  --ai-title  --ai-short  --ai-caption  --ai-summary  --ai-story  -v  -q
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


# ── AI content-generation helpers (--ai-title / --ai-short / etc.) ────────────

def _build_story_ai_prompt(context: str, content_type: str) -> str:
    """Build an AI prompt for story-based content generation."""
    base = f"{context}\n\n---\n"
    if content_type == "title":
        return base + (
            "Write a TITLE for this article. Max 10 words. "
            "Capture the core topic and key insight. "
            "No markdown, no quotes. Plain text, single line."
        )
    elif content_type == "short":
        return base + (
            "Write a SHORT SUMMARY (max 80 words, 1 paragraph). "
            "Lead with the main finding or takeaway. "
            "Plain text, no markdown, no headers."
        )
    elif content_type == "caption":
        return base + """Write a CAPTION (100–160 words, exactly 2 paragraphs).

Paragraph 1 — Context and main findings:
  Introduce the topic and state the key result.
  What question does this article address, and what is the answer?

Paragraph 2 — Significance and implications:
  Why does this matter? Close with a strong, specific sentence.

Plain text, no markdown headers."""
    elif content_type == "summary":
        return base + """Write a SUMMARY (120–200 words, 3 short paragraphs).

Paragraph 1 — Topic and purpose: What is this about?
Paragraph 2 — Key findings: What are the main results or arguments?
  Be specific — cite numbers or named claims where relevant.
Paragraph 3 — Bottom line: One clear sentence on the takeaway.

Plain text, no markdown headers."""
    elif content_type == "story":
        return base + """Write a COMPREHENSIVE ARTICLE (800–1200 words).

STRUCTURE:
1. Title (≤10 words, punchy)
2. Introduction — hook the reader with the key finding
3. Body sections (use ## headers) — key themes, findings, implications
4. Conclusion — clear takeaway

Reference specific facts or figures from the source material above.
Plain text with ## headers."""
    else:
        raise ValueError(f"Unknown content_type: {content_type}")


def _run_story_ai_content(args, story_text: str, story_title: str, ai_make: str):
    """Generate and print AI content from a story. Dispatches over enabled flags."""
    from ai_handler import process_prompt, get_content
    context = f"ARTICLE TITLE: {story_title}\n\nARTICLE TEXT:\n{story_text}"
    content_type_map = [
        (args.ai_title,   "title",   "Title"),
        (args.ai_short,   "short",   "Short Summary"),
        (args.ai_caption, "caption", "Caption"),
        (args.ai_summary, "summary", "Summary"),
        (args.ai_story,   "story",   "Story"),
    ]
    for flag, ctype, label in content_type_map:
        if not flag:
            continue
        if not args.quiet:
            print(f"\n{label}:")
            print("─" * 70)
        prompt = _build_story_ai_prompt(context, ctype)
        try:
            result  = process_prompt(ai_make, prompt, use_cache=args.cache)
            _, _, response, _ = result
            content = get_content(ai_make, response).strip()
            print(content)
        except Exception as e:
            print(f"  Generation failed ({ctype}): {e}")
        if not args.quiet:
            print("─" * 70)


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

    ai_group = parser.add_argument_group(
        'AI content generation (runs after generation, uses story text)')
    ai_group.add_argument('--ai-title',   action='store_true',
                          help='Generate a title (max 10 words) → stdout')
    ai_group.add_argument('--ai-short',   action='store_true',
                          help='Generate a short summary (max 80 words) → stdout')
    ai_group.add_argument('--ai-caption', action='store_true',
                          help='Generate a caption (100–160 words) → stdout')
    ai_group.add_argument('--ai-summary', action='store_true',
                          help='Generate a summary (120–200 words) → stdout')
    ai_group.add_argument('--ai-story',   action='store_true',
                          help='Generate a comprehensive story (800–1200 words) → stdout')

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

    # ── AI content generation (appended after story is generated + prepped) ──
    ai_requested = (args.ai_title or args.ai_short or args.ai_caption
                    or args.ai_summary or args.ai_story)
    if ai_requested and args.bang < 0:
        # Prefer prepped story text from container; fall back to raw API content
        story_text  = content_check
        story_title = ""
        try:
            with open(file_json) as _f:
                _out = json.load(_f)
            _stories = _out.get("story", [])
            if _stories:
                _last = _stories[-1]
                story_text  = _last.get("text", content_check)
                story_title = _last.get("title", "")
        except Exception:
            pass
        _run_story_ai_content(args, story_text, story_title, args.ai)


if __name__ == "__main__":
    main()
