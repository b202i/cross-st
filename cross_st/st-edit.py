#!/usr/bin/env python3
"""
st-edit — Edit or view story fields in a container

```
st-edit subject.json                    # edit story 1 in $EDITOR
st-edit -s 2 subject.json              # edit story 2
st-edit --field markdown subject.json  # edit the markdown field
st-edit --view subject.json            # view without editing
```

Options: -s story  --field  --view  -v  -q
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import subprocess
from mmd_startup import load_cross_env, require_config


def main():
    require_config()
    load_cross_env()
    parser = argparse.ArgumentParser(
        prog='st-edit',
        description='Edit or view the title, text, markdown, or spoken text of a story.'
                    '\nRun st-gen first.')

    # A json file is required
    parser.add_argument('json_file', type=str,
                        help='Path to the JSON file', metavar='file.json')
    # Data selection is optional, default select data 1
    parser.add_argument('-s', '--story', type=int, default=1,
                        help='Story data selected (integer), default 1')
    parser.add_argument('-f', '--fact', type=int,
                        help='Fact-check to edit (integer), default None')
    parser.add_argument('-spoken', '--spoken', action='store_true',
                        help='Edit the text to speech source text default: do not edit')
    parser.add_argument('-md', '--markdown', action='store_true',
                        help='Edit the markdown data, default: do not edit')
    parser.add_argument('-title', '--title', action='store_true',
                        help='Edit the title data, default: do not edit')
    parser.add_argument('-text', '--text', action='store_true',
                        help='Edit the text data, default: do not edit')
    parser.add_argument('--view', action='store_true',
                        help='View with Glow and edit with Vi, default: off')
    parser.add_argument('--view-only', action='store_true',
                        help='View with Glow, default: off')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Minimal output, default: quiet on')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output, default: verbose off')

    args = parser.parse_args()
    file_prefix = args.json_file.rsplit('.', 1)[0]  # Split from the right, only once
    file_json = file_prefix + ".json"

    edit_list = []
    if args.title:
        edit_list.append("title")
    if args.markdown:
        edit_list.append("markdown")
    if args.text:
        edit_list.append("text")
    if args.spoken:
        edit_list.append("spoken")
    if args.fact is not None:
        edit_list.append("fact")
    if len(edit_list) == 0:
        print("Nothing to do")
        sys.exit(0)
    if len(edit_list) != 1:
        print(f"Only one edit at a time please: {edit_list}")
        sys.exit(0)

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

    story_index = args.story - 1  # Starts at 1, not 0
    stories = main_container.get("story", [])
    if not stories or story_index >= len(stories) or story_index < 0:
        print(f"No such story: {story_index + 1}")
        sys.exit(1)

    story = stories[story_index]
    ai_tag = f"{story.get('make')}:{story.get('model')}"

    """
    For item to edit
    1. Get the text to edit from the story container
    2. Write the text to a file
    3. Spawn a task for the user the edit the file
    4. When control returns, read the file
    5. Save the data back to the container
    When done with all items, write the container back to disk, exit
    """

    item = edit_list[0]
    text_to_edit = ""
    fact_obj = None
    if args.fact is not None:  # Fact is two-level case, all others are a member of story
        length = len(story.get("fact", []))
        if 1 <= args.fact <= length:  # Validate range
            fact_obj = story["fact"][args.fact - 1]
            text_to_edit = fact_obj.get("report")
        else:
            print(f"Fact item out of range {args.fact}")
    else:
        text_to_edit = story[item]

    # Record the hash, to determine if any mods are made and disk write is necessary
    md5_hash = hashlib.md5(text_to_edit.encode('utf-8')).hexdigest()

    # Create a temporary file that persists after closing
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as temp_file:
        temp_file.write(text_to_edit)
        temp_file.flush()  # Ensure content is written to disk
        temp_path = temp_file.name  # Get the file path

    fact_select = ""
    if item=="fact":
        fact_select = f":{args.fact}"  # When item="fact", title "fact:n"
    editor_was_active = False
    cmd = [
        "grip", "--browser", "--quiet",
        f"--title={file_json} s:{args.story} {item}{fact_select} {ai_tag}",
        temp_path,
        "0",   # address "0" = OS assigns a free port — avoids conflicts on rapid re-use
    ]
    # Known grip startup noise — suppress these, surface anything else as warnings
    _GRIP_NOISE = {
        "* serving flask app",
        "* debug mode:",
        "* running on",
        "* restarting with",
        "* debugger is",
        "* debugger pin:",
        "use a production wsgi server instead",
        # grip dependency SyntaxWarnings under Python 3.13+ (docopt, path_and_address)
        "syntaxwarning",
        "invalid escape sequence",
        "did you mean",
        "a raw string is also an option",
        "docopt.py",
        "path_and_address",
        "validation.py",
        "warnings.warn",
        "site-packages",
        "name = re.findall",
        "value = re.findall",
        "matched = re.findall",
        "split = re.split",
        "_hostname_re = re.compile",
    }

    def _launch_grip(cmd, detach=False):
        """
        Start grip and return (process, port, error_lines).

        Uses a background thread to read stderr so we never block waiting for
        grip's pipe. Waits up to 3 s for grip to either bind a port or fail.

        If detach=True, grip is fully detached from this process (view_only mode):
        stdin/stdout/stderr are redirected to /dev/null, the process is in its
        own session, and st-edit exits without killing it.

        Returns (None, None, [error_msg]) on failure.
        """
        import re as _re
        import threading as _threading

        lines_seen = []
        port_found = [None]
        failed = [False]

        if detach:
            # Fully detached — grip outlives st-edit
            try:
                proc = subprocess.Popen(
                    cmd,
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,   # merge stdout+stderr → single stream
                )
            except FileNotFoundError:
                return None, None, ["grip is not installed or not on PATH.",
                                    "Install with: pip install grip"]
            except OSError as e:
                return None, None, [f"Failed to start grip: {e}"]
        else:
            try:
                proc = subprocess.Popen(
                    cmd,
                    start_new_session=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,   # merge stdout+stderr → single stream
                )
            except FileNotFoundError:
                return None, None, ["grip is not installed or not on PATH.",
                                    "Install with: pip install grip"]
            except OSError as e:
                return None, None, [f"Failed to start grip: {e}"]

        def _read_stderr():
            try:
                for raw in proc.stdout:
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    lines_seen.append(line)
                    m = _re.search(r":(\d{4,5})", line)
                    if m:
                        port_found[0] = m.group(1)
                    if proc.poll() is not None and proc.returncode not in (None, 0):
                        failed[0] = True
            except Exception:
                pass

        t = _threading.Thread(target=_read_stderr, daemon=True)
        t.start()

        # Wait up to 3 s for grip to bind its port or exit with an error
        deadline = time.time() + 3
        while time.time() < deadline:
            if port_found[0] or failed[0]:
                break
            if proc.poll() is not None:
                # Process exited — give reader thread a moment to drain
                t.join(timeout=0.5)
                break
            time.sleep(0.05)

        # Check for startup failure
        if proc.poll() is not None and proc.returncode not in (None, 0):
            error_lines = [f"grip exited with code {proc.returncode}"]
            error_lines += [l for l in lines_seen
                            if l.strip() and not any(n in l.lower() for n in _GRIP_NOISE)]
            return None, None, error_lines

        # Surface any unexpected output as warnings
        warnings = [l for l in lines_seen
                    if l.strip() and not any(n in l.lower() for n in _GRIP_NOISE)]

        port = port_found[0] or "6419"
        return proc, port, warnings

    def _kill_stale_grip():
        """Terminate any grip processes left over from previous view-only calls."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "grip.*--browser"],
                capture_output=True, text=True
            )
            for pid_str in result.stdout.strip().splitlines():
                try:
                    os.kill(int(pid_str), 15)  # SIGTERM
                except (ProcessLookupError, ValueError):
                    pass
        except Exception:
            pass  # pgrep unavailable or other OS issue — not fatal

    if args.view_only:
        # Kill any grip instances left from previous view calls before starting a new one
        _kill_stale_grip()

        # Detach grip fully — it must keep running after st-edit exits so the
        # browser can connect. --port=0 lets the OS assign a free port each time.
        # The temp file stays in /tmp and is cleaned up by the OS.
        grip_process, port, errors = _launch_grip(cmd, detach=True)

        if grip_process is None:
            print("  Error: could not launch grip browser preview.")
            for e in errors:
                print(f"    {e}")
            try:
                os.remove(temp_path)
            except OSError:
                pass
        else:
            if errors:
                print("  grip warning(s):")
                for e in errors:
                    print(f"    {e}")
            print(f"  Displayed on http://localhost:{port}")
            # Do NOT kill grip — it must keep serving until the browser loads.
            # Do NOT delete temp_path — grip is still reading it.

        sys.exit(0)

    if args.view:  # View and edit — grip runs alongside vi, killed when vi exits
        grip_process, port, errors = _launch_grip(cmd, detach=False)

        if grip_process is None:
            print("  Warning: grip browser preview unavailable.")
            for e in errors:
                print(f"    {e}")
            print("  Continuing with editor only.")
        else:
            if errors:
                print("  grip warning(s):")
                for e in errors:
                    print(f"    {e}")
            print(f"  Displayed on http://localhost:{port}")

        try:
            time.sleep(1)  # Brief pause so grip is ready before vi opens
            editor_was_active = True
            subprocess.run([os.getenv("EDITOR", "vi"), temp_path])

        finally:
            if grip_process is not None:
                grip_process.terminate()
                grip_process.wait()
                grip_process.kill()
    else:  # Edit only
        editor_was_active = True
        subprocess.run([os.getenv("EDITOR", "vi"), temp_path])

    if editor_was_active:
        # Editing is complete, read updated content
        with open(temp_path, "r") as temp_file:
            updated_content = temp_file.read()
        updated_content = updated_content.strip()  # vi adds unwanted \n

        os.remove(temp_path)  # Clean up temporary file

        # Test if the content changed
        updated_md5_hash = hashlib.md5(updated_content.encode('utf-8')).hexdigest()
        if updated_md5_hash != md5_hash:
            # Save content to the in-memory container
            if args.fact is not None:
                # data by reference updates the specific story fact item
                fact_obj["report"] = updated_content
            else:
                story[item] = updated_content
            # Save container back to disk
            with open(file_json, 'w', encoding='utf-8') as f:
                json.dump(main_container, f, ensure_ascii=False, indent=4)

            if not args.quiet:
                print(f"Container updated: {file_json}")
        else:
            if not args.quiet:
                print(f"Container unchanged: {file_json}")


if __name__ == "__main__":
    main()
