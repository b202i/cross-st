#!/usr/bin/env python3
"""
## st-prep — Prepare a raw AI response into a publishable story

Converts a raw AI-generated data entry into a structured, publishable story
and appends it to the .json container.  Called automatically by st-gen,
st-cross, st-fetch, and st-fix; can also be run manually.

```
st-prep subject.json              # process data entry 1, add story to container
st-prep -d 2 subject.json         # process data entry 2
st-prep -d 1 --mp3 subject.json   # also render an MP3 audio file
st-prep -d 1 --all subject.json   # export md, mp3, title, and txt files
```

Options: -d data  -a all  --markdown  --mp3  --title  --txt  --bang  -v  -q
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from mmd_startup import load_cross_env, require_config


from ai_handler import get_data_content
from mmd_branding import get_speaking_tagline, get_tagline_for_reading
from mmd_for_speaking import for_speaking
from mmd_process_report import (
    clean_newlines_preserve_paragraphs, edit_title, extract_title,
    remove_hashtags, remove_markdown, remove_story_break, get_hashtags, )
from mmd_util import remove_block_file, tmp_safe_name

title_truncate_length = 255  # Titles are sometimes paragraph-length; hard cap here


def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-prep',
        description='Prepare a raw AI response for posting and update the JSON container. '
                    'Run st-gen first.')

    parser.add_argument('json_file', type=str,
                        help='Path to the JSON file', metavar='file.json')
    parser.add_argument('-d', '--data', type=int, default=1,
                        help='Data entry to process (integer index), default: 1')
    parser.add_argument('-a', '--all', action='store_true',
                        help='Export all formats: md, mp3, title, txt, default: off')
    parser.add_argument('-md', '--markdown', action='store_true',
                        help='Export story as .md file, default: off')
    parser.add_argument('-mp3', '--mp3', action='store_true',
                        help='Render and export story as .mp3 audio, default: off')
    parser.add_argument('-title', '--title', action='store_true',
                        help='Export story title as .title file, default: off')
    parser.add_argument('-txt', '--txt', action='store_true',
                        help='Export story as .txt file, default: off')
    parser.add_argument('--bang', type=int, default=-1,
                        help='Parallel execution thread index (0 = first thread), default: -1 (serial)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output, default: off')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Minimal output, default: off')

    args = parser.parse_args()

    if args.verbose:
        print(f"st-prep args: {args}")

    file_prefix = args.json_file.rsplit('.', 1)[0]  # Split from the right, only once

    if args.all:
        args.markdown = True
        args.mp3 = True
        args.title = True
        args.txt = True

    file_json  = file_prefix + ".json"
    file_mp3   = file_prefix + ".mp3"
    file_txt   = file_prefix + ".txt"
    file_md    = file_prefix + ".md"
    file_title = file_prefix + ".title"

    # Use realpath to get the actual path of the script
    load_cross_env()

    try:
        if not os.path.isfile(file_json):
            print(f"Error: The file {args.json_file} does not exist.")
            sys.exit(1)

        with open(file_json, 'r') as file:
            main_container = json.load(file)

        if args.verbose:
            print(f"Story container {file_json} successfully read.")

    except json.JSONDecodeError:
        print(f"Error: The file {file_json} contains invalid JSON.")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

    # Collect selected raw story data
    if "data" in main_container:
        length = len(main_container["data"])
        if 1 <= args.data <= length:
            select_data  = main_container["data"][args.data - 1]
            select_make  = select_data["make"]
            select_model = select_data["model"]
            all_raw_story_text = get_data_content(select_make, select_data)
        else:
            print(f"Invalid index: {args.data}")
            sys.exit(1)
    else:
        print("Missing data in container")
        sys.exit(1)

    # Massage raw data into a publishable story
    file_md_content = remove_story_break(all_raw_story_text)

    select_hashtags = get_hashtags(file_md_content)

    # Plain text for audio and non-markdown social media
    hashless_story  = remove_hashtags(file_md_content)
    no_md           = remove_markdown(hashless_story)
    speaking_tagline = get_speaking_tagline(select_make, select_model)
    as_spoken       = for_speaking(no_md, args.verbose) + "\n\n" + speaking_tagline

    ai_tag_reading   = get_tagline_for_reading(select_make, select_model)
    clean_paragraphs = clean_newlines_preserve_paragraphs(no_md)
    file_txt_content = clean_paragraphs + "\n\n" + ai_tag_reading
    file_md_content += "\n\n" + ai_tag_reading

    # Extract and clean the title
    file_title_content = extract_title(file_txt_content)
    file_title_content = edit_title(file_title_content)  # Remove "Title:" prefix etc.
    file_title_content = file_title_content[:title_truncate_length]

    if not args.quiet:
        title_words = file_title_content.split()
        if len(title_words) < 4:
            print(f"Title very short: {file_title_content}")
        elif len(title_words) > 20:
            print(f"Title very long: {file_title_content}")
        elif len(title_words) > 13:
            print(f"Title long: {file_title_content}")
        else:
            print(f"Title: {file_title_content}")

    if args.mp3:
        if not args.quiet:
            print(f"Rendering voice: {file_mp3}")

        try:
            from yakyak import is_server_online, piper_tts_server
        except ImportError:
            print("Error: TTS packages not installed.  "
                  "Run: pipx install --force \"cross-st[tts]\"",
                  file=sys.stderr)
            sys.exit(1)

        host  = os.getenv("TTS_HOST")
        port  = int(os.getenv("TTS_PORT"))
        voice = os.getenv("TTS_VOICE")
        if not is_server_online(host, port):
            print(f"TTS host {host}:{port} is offline")
        else:
            asyncio.run(
                piper_tts_server(host, port, as_spoken, file_mp3, "mp3", voice)
            )
            if not args.quiet:
                print(f"Audio mp3 render complete")

    # Build a new story dictionary from the provided components
    story = {
        "make":     select_make,
        "model":    select_model,
        "title":    file_title_content,
        "markdown": file_md_content,
        "text":     file_txt_content,
        "spoken":   as_spoken,
        "hashtags": select_hashtags,
        "fact":     [],
    }
    # MD5 hash used to detect duplicate stories
    story_str = json.dumps(story, sort_keys=True)
    story["md5_hash"] = hashlib.md5(story_str.encode('utf-8')).hexdigest()

    if "story" not in main_container:
        main_container["story"] = []

    duplicate_found = any(
        s.get("md5_hash") == story["md5_hash"]
        for s in main_container["story"]
    )
    if not duplicate_found:
        main_container["story"].append(story)
        if args.verbose:
            print("Added new story")
    else:
        if args.verbose:
            print("Story already exists; not adding duplicate")

    # Atomic write — concurrent st-gen --prep processes must not corrupt each other
    tmp_json = file_json + ".tmp"
    with open(tmp_json, 'w', encoding='utf-8') as f:
        json.dump(main_container, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_json, file_json)  # atomic on POSIX
    if args.verbose:
        print(f"Story container updated: {file_json}")

    report_content = file_txt_content + "\n\n" + " ".join(select_hashtags) + "\n"
    if args.txt:
        with open(file_txt, 'w', encoding='utf-8') as outfile:
            outfile.write(report_content)
        if not args.quiet:
            print(f"Text saved: {file_txt}")

    if args.markdown:
        with open(file_md, 'w', encoding='utf-8') as outfile:
            outfile.write(file_md_content)
        if not args.quiet:
            print(f"Markdown saved: {file_md}")

    if args.title:
        with open(file_title, 'w', encoding='utf-8') as outfile:
            outfile.write(file_title_content)
        if not args.quiet:
            print(f"Title saved: {file_title}")

    if args.bang >= 0:  # If running a parallel bang operation, remove block file
        remove_block_file(tmp_safe_name(file_json), args.verbose)


if __name__ == "__main__":
    main()
