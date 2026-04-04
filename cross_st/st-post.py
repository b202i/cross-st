#!/usr/bin/env python3
"""
st-post — Post a story to Discourse

```
st-post subject.json                    # post story 1 to default site
st-post -s 2 subject.json              # post story 2
st-post --site MySite subject.json     # post to a named Discourse site
st-post --check                        # verify credentials without posting
```

Options: -s story  --site  --fact  --check  -v  -q
"""
import argparse
import json
import os
import subprocess
import sys
from mmd_startup import load_cross_env, require_config

from discourse import get_discourse_slugs_sites, get_discourse_site
from mmd_process_report import add_mp3_player, add_mp3_player_top
from pathlib import Path
from discourse import MmdDiscourseClient


def main():
    require_config()
    load_cross_env()

    slugs, sites = get_discourse_slugs_sites()
    default_site = slugs[0] if slugs else None

    parser = argparse.ArgumentParser(
        prog='st-post',
        description=("Post a story to social media."
                      " At minimum include the story .json file."
                      " The title and body can be tailored by editing the .md and .title files."
                      " The  json can be overridden by .title and .md files.")
    )
    parser.add_argument('files', nargs='*',
                        help="Files of to process")
    parser.add_argument('--site', type=str, choices=slugs or None, default=default_site,
                        help=f"Select Discourse site to use, default is {default_site}")
    # When -s is specified, an integer must follow; if not, argparse will raise an error.
    parser.add_argument('-s', '--story', type=int, default=1,
                        help='Select story to publish: default 1')
    parser.add_argument('-f', '--fact', type=int,
                        help='Reply with fact-check to the post, default: no reply')
    parser.add_argument('--check', action='store_true',
                        help='Validate Discourse credentials and connection without posting')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output, default: verbose off')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Enable minimal output')
    args = parser.parse_args()

    # ── --check: validate credentials without posting ─────────────────────────
    if args.check:
        import requests as _req
        print(f"Checking Discourse site: {args.site}")
        site = get_discourse_site(args.site, sites)
        key = site.get("api_key", "")
        username = site.get("username", "")
        url = site.get("url", "").rstrip("/")
        masked = key[:4] + "…" + key[-4:] if len(key) > 8 else "****"
        print(f"  URL      : {url}")
        print(f"  Username : {username}")
        print(f"  API key  : {masked}  (len={len(key)})")
        print(f"  Category : {site.get('category_id')}")
        print()

        # Raw requests call — bypasses pydiscourse entirely
        # This isolates whether the problem is in the library or the credentials
        test_url = f"{url}/session/current.json"
        print(f"  Testing: GET {test_url}")
        try:
            resp = _req.get(
                test_url,
                headers={
                    "Api-Key": key,
                    "Api-Username": username,
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            print(f"  HTTP status : {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                cuser = data.get("current_user", {})
                print(f"  Auth        : ✓  logged in as {cuser.get('username', '?')}")
                print(f"  Trust level : {cuser.get('trust_level', '?')}")
                print(f"  Admin       : {cuser.get('admin', False)}")
            elif resp.status_code == 403:
                print(f"  Auth        : ✗  403 Forbidden — key is valid JSON but rejected")
                print(f"  Response    : {resp.text[:300]}")
                print()
                print("  Diagnosis:")
                print("    The API key exists but is being rejected. Check:")
                print("    1. Admin panel → API → key must have 'All Users' or your username scope")
                print("    2. The key owner username must exactly match the 'username' field")
                print("    3. Try: Admin → Users → your_user → Permissions → 'allow api access'")
            elif resp.status_code == 404:
                print(f"  Auth        : ✗  404 — URL may be wrong: {url}")
            else:
                print(f"  Auth        : ✗  HTTP {resp.status_code}")
                print(f"  Response    : {resp.text[:300]}")
        except Exception as e:
            print(f"  Connection  : ✗  {e}")
            print("  Check the URL is reachable and correct")

        # ── Test upload endpoint ──────────────────────────────────────────────
        print()
        print(f"  Testing upload endpoint: POST {url}/uploads.json")
        import io as _io
        try:
            # Minimal valid MP3 header — just enough to test the endpoint
            # without uploading a real file
            tiny_mp3 = bytes([
                0xFF, 0xFB, 0x90, 0x00,   # MP3 frame sync + header
                0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            ])
            upload_resp = _req.post(
                f"{url}/uploads.json",
                headers={
                    "Api-Key": key,
                    "Api-Username": username,
                },
                files={"file": ("test.mp3", _io.BytesIO(tiny_mp3), "audio/mpeg")},
                data={"type": "composer", "synchronous": "true"},
                timeout=15,
            )
            print(f"  HTTP status : {upload_resp.status_code}")
            print(f"  Response    : {upload_resp.text[:400]}")
            if upload_resp.status_code == 200:
                print(f"  Upload      : ✓  endpoint accepts uploads")
            elif upload_resp.status_code == 422:
                print()
                print("  Upload      : ✗  422 Unprocessable — file rejected (expected for")
                print("                   a tiny test file — but auth is working)")
            elif upload_resp.status_code == 403:
                print()
                print("  Upload      : ✗  403 on uploads.json specifically")
                print("  This Discourse instance may have uploads restricted.")
                print("  Check: Admin → Settings → Files → 'authorized extensions'")
                print("         and ensure 'mp3' is listed.")
                print("  Also check: Admin → Settings → Files → 'allow staff to upload any file type'")
        except Exception as e:
            print(f"  Upload      : ✗  {e}")
        sys.exit(0)

    # get the site json structure based on user preference
    site = get_discourse_site(args.site, sites)

    file_list = args.files
    if len(file_list) == 0:
        print("Enter at least one file to post.")
        sys.exit(1)

    # Dictionary to hold files by type
    files_by_type = {
        'jpg': [],  # Story image attachment
        'json': [],  # Story container
        'md': [],  # Story markdown content
        'mp3': [],  # Story audio attachment
        'mp4': [],  # Story video attachment
        'png': [],  # Story image attachment
        'title': [],  # Story title
        'txt': [],  # Story text content
    }

    # Classify files by their extension
    for file in file_list:
        _, ext = os.path.splitext(file)
        ext = ext.lstrip('.').lower()  # Remove leading dot and make lowercase
        if ext in files_by_type:
            files_by_type[ext].append(file)
        else:
            print(f"Warning: Unrecognized file extension '{ext}' for file {file}")

    fact_report = ""
    file_json = ""
    file_prefix = ""
    story_markdown = ""
    story_title = ""
    topic_id = None

    # Load content from json container first, override with specific content
    if len(files_by_type['json']) > 0:
        file_json = files_by_type['json'][0]
        try:
            with open(file_json, 'r') as file:
                main_container = json.load(file)

                # Confirm story parameter, get story
                length = len(main_container.get("story", []))
                if 1 <= args.story <= length:
                    select_story = main_container["story"][args.story-1]
                else:
                    if not args.quiet:
                        print(f"Story item out of range: {args.story}")
                    sys.exit(1)

                # Confirm fact parameter, get fact report
                if args.fact is not None:
                    length = len(select_story.get("fact", []))
                    if 1 <= args.fact <= length:  # Validate range
                        fact_obj = select_story["fact"][args.fact-1]
                        fact_report = fact_obj.get("report")
                    else:
                        print(f"Fact item out of range {args.fact}")
            if args.verbose:
                print(f"Story container json successfully read.")

            file_prefix = Path(file_json).stem  # filename no extension
            story_markdown = select_story['markdown']
            # story_text = post_story['text']  # Currently on MD is used
            story_title = select_story['title']
            topic_id = select_story.get('topic_id')

        except FileNotFoundError:
            print(f"Error: The file {args.json_file} does not exist.")
            sys.exit(1)
        except json.JSONDecodeError:
            print(f"Error: The file {file_json} contains invalid JSON.")
            sys.exit(1)
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            sys.exit(1)

    # If there is a title file, override title from story container
    if len(files_by_type['title']) > 0:
        with open(files_by_type['title'][0], 'r') as file:
            story_title = file.read()

    # If there is a md file, override story from story container
    if len(files_by_type['md']) > 0:
        with open(files_by_type['md'][0], 'r') as file:
            story_markdown = file.read()

    # Initialize the client
    base_url = site["url"]
    client = MmdDiscourseClient(
        base_url,
        api_username=site["username"],
        api_key=site["api_key"],
    )
    # If there is a mp3 file, upload it to discourse and keep the url.
    # The url will be referenced in the post
    file_mp3 = file_prefix + '.mp3'
    mp3_created = False
    mp3_url = ""
    post_url = ""

    if len(files_by_type['mp3']) > 0:
        # Create the mp3 audio file if it does not already exist
        if not os.path.isfile(file_mp3):
            if args.fact is not None:
                cmd = f"st-speak -s {args.story-1} --source fact {file_json}".split()
            else:
                cmd = f"st-speak -s {args.story-1} {file_json}".split()
            subprocess.run(cmd)
            mp3_created = True

        # Prepare file and form data for the upload
        try:
            if not args.quiet:
                print(f"Uploading audio file: {file_mp3}")
            upload_resp = client.upload_file(file_mp3)
            mp3_url = upload_resp["url"]
            if not args.quiet:
                print(f"Audio upload complete")
            # When the user supplies an mp3 use it, but if we created
            # it here, delete it after uploading
            if mp3_created:
                os.remove(file_mp3)
        except Exception as e:
            print(f"An upload error occurred: {e}")

    if args.fact is not None:
        if mp3_url:
            fact_report = add_mp3_player_top(fact_report, file_mp3, mp3_url)
    else:
        if mp3_url:
            story_markdown = add_mp3_player(story_markdown, file_mp3, mp3_url)

    if args.fact is None:  # If not a fact-check post, it must be a regular post
        # Create the post
        try:
            print(f"Uploading post to {args.site}")
            post_response = client.create_post(
                story_markdown,
                site['category_id'],
                title=story_title,
            )
            topic_id = post_response['topic_id']
            topic_slug = post_response['topic_slug']
            post_url = f"{base_url}/t/{topic_slug}/{topic_id}"
            if not args.quiet:
                print(f"Post uploaded: {post_url}")
        except Exception as e:
            print(f"An error occurred: {e}")

        # Update story in main container
        select_story["topic_id"] = topic_id
        select_story["post_url"] = post_url
        select_story["mp3_url"] = mp3_url
        with open(file_json, 'w', encoding='utf-8') as f:
            json.dump(main_container, f, ensure_ascii=False, indent=4)
        if not args.quiet and args.verbose:
            print(f"Story container updated: {file_json}")
    else:
        # Not a post but a fact-check reply
        # A story is given a topic_id after it is posted
        if topic_id is not None and fact_report != "":
            # Create the reply
            try:
                print(f"Uploading reply, length: {len(fact_report)}")
                post_response = client.create_post(
                    fact_report,
                    10,
                    topic_id=topic_id,
                )
                response_topic_id = post_response['topic_id']
                print(f"Post uploaded, topic_id: {response_topic_id}")
            except Exception as e:
                print(f"An error occurred: {e}")
        else:
            print("Error: Story not posted or fact check not complete")


if __name__ == "__main__":
    main()
