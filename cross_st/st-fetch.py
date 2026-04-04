#!/usr/bin/env python3
"""
## st-fetch — Import external content into a container

Brings existing stories into the Cross pipeline for fact-checking, improvement,
and publishing.  Content is stored as a data entry; run st-prep to convert it
to a story entry visible to all downstream tools (st-fact, st-fix, st-merge,
st-post).

Sources supported:
  tweet_id    Fetch a post from X (Twitter) by numeric tweet ID
  --file      Import a plain text or markdown file from disk
  --url       Fetch a web page by URL (scrapes visible text)
  --clipboard Paste text directly from the system clipboard

```
st-fetch <tweet_id> file.json            # fetch X post by tweet ID
st-fetch --file report.md file.json      # import a local .txt or .md file
st-fetch --url https://... file.json     # fetch a web page
st-fetch --clipboard file.json           # import text from clipboard
st-fetch --clipboard file.json --prep    # clipboard → story entry in one step
st-fetch <tweet_id> file.json --prep     # fetch and run st-prep automatically
st-fetch <tweet_id> file.json --no-cache # bypass cache, always fetch live
```

Full pipeline for refreshing an existing report:
  st-fetch --file old_report.md old_report.json --prep
  st-bang old_report.json          # regenerate with all 5 AI
  st-cross old_report.json         # cross-product fact-check
  st-merge old_report.json         # synthesize best version
  st-post --site myblog old_report.json

See README_fetch.md for full use cases and roadmap.

Requirements:
  X_COM_BEARER_TOKEN=<bearer token>  in .env   (tweet_id source only)

Options: --file  --url  --clipboard  --prep  --no-cache  -v  -q
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from mmd_startup import load_cross_env, require_config


from ai_url import get_url_cached_response, get_title, get_story, AI_MAKE, AI_MODEL
from mmd_branding import get_app_tag
from mmd_process_report import remove_markdown


def _fetch_tweet(tweet_id, verbose, use_cache):
    """Fetch a tweet by ID. Returns (title, text, raw_response)."""
    response = get_url_cached_response(tweet_id, verbose, use_cache)
    title = get_title(response) or f"Tweet {tweet_id}"
    text  = get_story(response) or ""
    return title, text, response


def _fetch_file(filepath, verbose):
    """Import a plain text or markdown file from disk. Returns (title, text, raw_response)."""
    if not os.path.isfile(filepath):
        print(f"Error: file not found: {filepath}")
        sys.exit(1)
    with open(filepath, 'r', encoding='utf-8') as f:
        raw = f.read()
    # Use first non-empty line as title candidate; strip markdown heading markers
    title = ""
    for line in raw.splitlines():
        line = line.strip().lstrip('#').strip()
        if line:
            title = line[:120]
            break
    title = title or os.path.basename(filepath)
    text  = remove_markdown(raw)
    response = {"source": "file", "filepath": filepath, "raw": raw}
    if verbose:
        print(f"  Loaded {len(raw)} chars from {filepath}")
    return title, text, response


def _fetch_url(url, verbose):
    """Fetch a web page and extract visible text. Returns (title, text, raw_response)."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        print("Error: 'requests' and 'beautifulsoup4' are required for --url.")
        print("  pip install requests beautifulsoup4")
        sys.exit(1)

    if verbose:
        print(f"  Fetching URL: {url}")
    try:
        resp = requests.get(url, timeout=15,
                            headers={"User-Agent": "Mozilla/5.0 (compatible; cross-fetch/1.0)"})
        resp.raise_for_status()
    except Exception as e:
        print(f"Error fetching URL: {e}")
        sys.exit(1)

    soup = BeautifulSoup(resp.text, "html.parser")
    # Remove script/style noise
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    page_title = soup.title.string.strip() if soup.title else ""
    # Prefer <h1> as title
    h1 = soup.find("h1")
    if h1:
        page_title = h1.get_text(strip=True) or page_title

    text = soup.get_text(separator="\n", strip=True)
    # Collapse excessive blank lines
    import re
    text = re.sub(r'\n{3,}', '\n\n', text)

    response = {"source": "url", "url": url, "status_code": resp.status_code}
    return page_title or url, text, response


def _fetch_clipboard(verbose):
    """Read text from the system clipboard. Returns (title, text, raw_response).

    Uses pbpaste on macOS, xclip/xsel on Linux, and PowerShell on Windows.
    Falls back to reading stdin if no clipboard tool is found.
    """
    import platform
    import subprocess as _sp

    system = platform.system()
    raw = ""

    try:
        if system == "Darwin":
            result = _sp.run(["pbpaste"], capture_output=True, text=True, check=True)
            raw = result.stdout
        elif system == "Linux":
            # Try xclip first, then xsel
            for cmd in [["xclip", "-selection", "clipboard", "-o"],
                        ["xsel", "--clipboard", "--output"]]:
                try:
                    result = _sp.run(cmd, capture_output=True, text=True, check=True)
                    raw = result.stdout
                    break
                except (FileNotFoundError, _sp.CalledProcessError):
                    continue
            if not raw:
                print("Error: clipboard tool not found. Install xclip or xsel.")
                print("  sudo apt install xclip")
                import sys as _sys
                _sys.exit(1)
        elif system == "Windows":
            result = _sp.run(
                ["powershell", "-command", "Get-Clipboard"],
                capture_output=True, text=True, check=True
            )
            raw = result.stdout
        else:
            print(f"Error: clipboard not supported on {system}")
            import sys as _sys
            _sys.exit(1)
    except Exception as e:
        print(f"Error reading clipboard: {e}")
        import sys as _sys
        _sys.exit(1)

    if not raw.strip():
        print("Error: clipboard is empty")
        import sys as _sys
        _sys.exit(1)

    if verbose:
        print(f"  Read {len(raw)} chars from clipboard")

    # Infer title from first non-empty line
    title = ""
    for line in raw.splitlines():
        line = line.strip().lstrip('#').strip()
        if line:
            title = line[:120]
            break
    title = title or "Clipboard import"

    text = remove_markdown(raw)
    response = {"source": "clipboard", "raw": raw}
    return title, text, response


def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-fetch',
        description='Import external content into a Cross container')

    # Source — mutually exclusive: tweet_id positional, --file, --url, or --clipboard
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument('--file', type=str, metavar='PATH',
                               help='Import a plain text or markdown file from disk')
    source_group.add_argument('--url', type=str, metavar='URL',
                               help='Fetch a web page and extract its text')
    source_group.add_argument('--clipboard', action='store_true',
                               help='Import text from the system clipboard')

    parser.add_argument('tweet_id', type=str, nargs='?', default=None,
                        help='Tweet ID to fetch from X (numeric ID from post URL)')
    parser.add_argument('json_file', type=str,
                        help='Path to the .json container', metavar='file.json')
    parser.add_argument('--cache', dest='cache', action='store_true', default=True,
                        help='Enable API cache (default: on)')
    parser.add_argument('--no-cache', dest='cache', action='store_false',
                        help='Disable API cache — always fetch live')
    parser.add_argument('--prep', action='store_true',
                        help='Run st-prep on the container after fetching')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Minimal output')
    args = parser.parse_args()

    # Validate: exactly one source must be given
    if not args.file and not args.url and not args.clipboard and not args.tweet_id:
        parser.error("Specify a tweet_id, --file PATH, --url URL, or --clipboard")

    file_prefix = args.json_file.rsplit('.', 1)[0]
    file_json   = file_prefix + ".json"

    load_cross_env()

    # ── Fetch from source ─────────────────────────────────────────────────────
    source_make  = AI_MAKE    # "url"
    source_model = AI_MODEL   # "bs4"
    source_id    = None

    if args.file:
        if not args.quiet:
            print(f"  Importing file: {args.file}…", end='', flush=True)
        title, text, response = _fetch_file(args.file, args.verbose)
        source_model = "file"
        if not args.quiet:
            print(" ✓")

    elif args.url:
        if not args.quiet:
            print(f"  Fetching URL…", end='', flush=True)
        title, text, response = _fetch_url(args.url, args.verbose)
        source_model = "bs4"
        if not args.quiet:
            print(" ✓")

    elif args.clipboard:
        if not args.quiet:
            print(f"  Reading clipboard…", end='', flush=True)
        title, text, response = _fetch_clipboard(args.verbose)
        source_model = "clipboard"
        if not args.quiet:
            print(" ✓")

    else:
        # tweet_id source — requires bearer token
        if not os.getenv("X_COM_BEARER_TOKEN"):
            print("Error: X_COM_BEARER_TOKEN not set in .env")
            print("  Obtain a bearer token from developer.x.com and add:")
            print("  X_COM_BEARER_TOKEN=<your token>")
            sys.exit(1)
        cache_note = "cache" if args.cache else "live"
        if not args.quiet:
            print(f"  Fetching tweet {args.tweet_id} ({cache_note})…", end='', flush=True)
        try:
            title, text, response = _fetch_tweet(args.tweet_id, args.verbose, args.cache)
        except Exception as e:
            print(f"\nError fetching tweet {args.tweet_id}: {e}")
            sys.exit(1)
        source_model = "twitter-v2"
        if not args.quiet:
            print(" ✓")

    if args.verbose:
        print(json.dumps(response, indent=2))

    if not text:
        print(f"  Warning: no text content found in source")

    if not args.quiet:
        print(f"  {title[:72]}")

    # ── Load or create container ──────────────────────────────────────────────
    container_modified = False
    if os.path.isfile(file_json):
        try:
            with open(file_json, 'r') as f:
                container = json.load(f)
        except json.JSONDecodeError:
            print(f"Error: {file_json} contains invalid JSON.")
            sys.exit(1)
        except Exception as e:
            print(f"An unexpected error occurred reading {file_json}: {e}")
            sys.exit(1)
    else:
        container = {"data": [], "story": []}
        if not args.quiet:
            print(f"  Creating new container: {file_json}")

    # ── Build data entry ──────────────────────────────────────────────────────
    ai_tag = get_app_tag() + f"{source_make}:{source_model}"
    data = {
        "make":         source_make,
        "model":        source_model,
        "title":        title,
        "text":         text,
        "markdown":     text,   # raw — st-prep will format properly
        "tag":          ai_tag,
        "gen_response": response,
    }
    data_str = json.dumps(data, sort_keys=True)
    data["md5_hash"] = hashlib.md5(data_str.encode('utf-8')).hexdigest()

    # ── Deduplicate ───────────────────────────────────────────────────────────
    duplicate = next(
        (i + 1 for i, d in enumerate(container.get("data", []))
         if d.get("md5_hash") == data["md5_hash"]),
        None
    )
    if duplicate is None:
        container.setdefault("data", []).append(data)
        container_modified = True
        data_index = len(container["data"])
        if not args.quiet:
            print(f"  Added as data entry {data_index}")
    else:
        data_index = duplicate
        if not args.quiet:
            print(f"  Already in container as data entry {duplicate} — not added")

    # ── Save container ────────────────────────────────────────────────────────
    if container_modified:
        with open(file_json, 'w', encoding='utf-8') as f:
            json.dump(container, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        if not args.quiet:
            print(f"  Container updated: {file_json}")

    # ── Optional st-prep pass ─────────────────────────────────────────────────
    if args.prep and container_modified:
        if not args.quiet:
            print(f"  Running st-prep on data entry {data_index}…")
        subprocess.run(
            ["st-prep", "-d", str(data_index), file_json],
            check=False
        )


if __name__ == "__main__":
    main()

