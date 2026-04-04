#!/usr/bin/env python3

import json
import os
import sys
from pydiscourse.client import DiscourseClient
from dotenv import load_dotenv



class MmdDiscourseClient(DiscourseClient):
    def __init__(self, host_url, api_username, api_key, **kwargs):
        super().__init__(host_url, api_username, api_key, **kwargs)
        # Store explicitly so upload_file never depends on pydiscourse internals
        self._mmd_host     = host_url.rstrip("/")
        self._mmd_username = api_username
        self._mmd_key      = api_key

    def upload_file(self, file_path, upload_type="composer", synchronous=True,
                    content_type="audio/mpeg", **kwargs):
        """
        Upload a file to Discourse via a direct requests call.

        Uses requests directly rather than pydiscourse's _post so that
        the Api-Key and Api-Username headers are set explicitly — pydiscourse
        passes credentials differently for multipart/form-data requests on
        some Discourse versions.
        """
        import requests
        import io

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        resp = requests.post(
            f"{self._mmd_host}/uploads.json",
            headers={
                "Api-Key":      self._mmd_key,
                "Api-Username": self._mmd_username,
            },
            files={"file": (os.path.basename(file_path),
                            io.BytesIO(file_bytes),
                            content_type)},
            data={
                "type":        upload_type,
                "synchronous": "true" if synchronous else "false",
            },
            timeout=60,
        )

        if not resp.ok:
            raise Exception(
                f"Upload failed: HTTP {resp.status_code} — {resp.text[:300]}")

        return resp.json()


"""python
# Example
# Initialize your subclassed client
client = MmdDiscourseClient("https://yourforum.example.com", "your_username", "your_api_key")

# Upload the MP3 file
upload_response = client.upload_file("file.mp3")
audio_url = upload_response.get("url")
print("Uploaded audio URL:", audio_url)

# Create a new post using the uploaded file URL
post_body = f"Listen to this audio file: {audio_url}"
client.create_post(post_body, topic_id=123)
"""


def get_discourse_slugs_sites():
    # Discourse site authentication details remain private in .env
    # Return a list of sites and slug identifier for each site

    # Use realpath to get the actual path of the script
    _basedir  = os.path.dirname(os.path.realpath(__file__))
    _CROSSENV = os.path.expanduser("~/.crossenv")
    load_dotenv(_CROSSENV)                                    # 1. global ~/.crossenv
    load_dotenv(os.path.join(_basedir, ".env"))               # 2. repo-local .env (developer keys)
    load_dotenv(".env", override=True)                        # 3. CWD .env overrides both

    string = os.getenv("DISCOURSE")
    if not string:
        # Check if old lowercase key exists and give a targeted fix message
        old = os.getenv("discourse")
        if old:
            print("Error: .env has 'discourse=' (lowercase) but the app now requires 'DISCOURSE='.")
            print("  Fix: in .env, rename  discourse=...  →  DISCOURSE=...")
            print("  Or re-run:  python3 discourse.py   (from the project root)")
        else:
            print("Error: DISCOURSE environment variable not set in .env.")
            print("  Add your Discourse credentials by running:")
            print("    python3 discourse.py")
            print("  See README_opensource.md for the discourse.json format.")
        sys.exit(1)

    try:
        data = json.loads(string)
    except json.JSONDecodeError as e:
        print(f"Error: DISCOURSE value in .env is not valid JSON: {e}")
        print("  Re-run:  python3 discourse.py   to rebuild the entry.")
        sys.exit(1)

    # Support both {"sites": [...]} and [...] (array directly)
    if isinstance(data, list):
        sites = data
    elif isinstance(data, dict):
        sites = data.get('sites')
        if sites is None:
            print("Error: DISCOURSE JSON has no 'sites' key.")
            print("  Expected format:  {\"sites\": [{\"slug\":..., \"url\":..., "
                  "\"username\":..., \"api_key\":..., \"category_id\":...}]}")
            sys.exit(1)
    else:
        print("Error: DISCOURSE value must be a JSON object or array.")
        sys.exit(1)

    if not sites:
        print("Error: DISCOURSE 'sites' list is empty.")
        sys.exit(1)

    # Validate required fields in each site entry
    required = ("slug", "url", "username", "api_key", "category_id")
    for i, site in enumerate(sites):
        missing = [k for k in required if not site.get(k)]
        if missing:
            print(f"Error: site[{i}] (slug={site.get('slug','?')}) is missing "
                  f"required fields: {', '.join(missing)}")
            print("  Check your discourse.json and re-run:  python3 discourse.py")
            sys.exit(1)

    slugs = [site["slug"] for site in sites]
    return slugs, sites


def get_discourse_site(slug, sites):
    # Search among the Discourse sites, return the one matching the slug
    site = None
    for site_opt in sites:
        if site_opt["slug"] == slug:
            site = site_opt
            break

    return site


def main():
    """
    Write Discourse credentials from discourse.json into .env as DISCOURSE=...
    Replaces any existing DISCOURSE= or discourse= line to avoid duplicates.

    Usage:
        python3 discourse.py          # from the project root
    """
    file_json = "discourse.json"

    if not os.path.isfile(file_json):
        print(f"Error: {file_json} not found in current directory.")
        print("  Create it with your site credentials — see README_opensource.md")
        sys.exit(1)

    with open(file_json, 'r') as file:
        container = json.load(file)

    new_line = "DISCOURSE=" + json.dumps(container) + "\n"

    # Read existing .env, strip any old DISCOURSE= or discourse= lines
    env_path = ".env"
    existing_lines = []
    if os.path.isfile(env_path):
        with open(env_path, "r") as f:
            existing_lines = f.readlines()

    # Remove stale entries (case-insensitive key match)
    filtered = [l for l in existing_lines
                if not l.upper().startswith("DISCOURSE=")]
    filtered.append(new_line)

    with open(env_path, "w") as f:
        f.writelines(filtered)

    print(f"DISCOURSE written to {env_path}")
    slugs = [s["slug"] for s in container.get("sites", container
             if isinstance(container, list) else [])]
    print(f"  Sites: {', '.join(slugs)}")


if __name__ == "__main__":
    main()
