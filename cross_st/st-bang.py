#!/usr/bin/env python3
"""
st-bang — Run all AI providers in parallel and merge results

Launches one st-gen subprocess per AI simultaneously, monitors progress,
then merges all responses into the container.

```
st-bang subject.prompt                  # run all providers in parallel
st-bang --ai all subject.prompt         # explicit: all providers
st-bang --no-cache subject.prompt       # bypass API cache
```

Options: --ai  --no-cache  --merge  -v  -q
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from mmd_startup import require_config

from ai_handler import get_ai_list, get_default_ai, get_ai_model, get_ai_make
from mmd_util import get_tmp_dir, tmp_safe_name

"""
## Bang Concept, 2-stage report generation
Stage 1. Submit unique AI report generation calls in parallel.
Stage 2. Optionally merge reports into a single report using AI.

## Performance increase expected
The current serial operation requires the time of N AI calls.
The Bang concept takes the time of 1 AI call + 1 merge call.

## Data storage background
To keep things tidy, the ST system uses 2 files: a .json file and a .prompt file.
Example: subject.json, subject.prompt.
The JSON file contains two top-level arrays:
  ["data"][0..N]  — raw AI responses
  ["story"][0..N] — processed story objects

## Bang story generation
Generate a story from each AI using the same prompt, into separate .json files.
st-bang starts the story generation for each AI while monitoring results:
```bash
st-bang --ai all subject.prompt
```
Launches:
    st-gen --ai xai       subject.prompt --bang 0  → tmp/subject_0.json
    st-gen --ai anthropic subject.prompt --bang 1  → tmp/subject_1.json
    st-gen --ai openai    subject.prompt --bang 2  → tmp/subject_2.json
    st-gen --ai perplexity subject.prompt --bang 3 → tmp/subject_3.json
    st-gen --ai gemini    subject.prompt --bang 4  → tmp/subject_4.json

A block file is created for each st-gen process:
    tmp/subject_0.json.block  ... tmp/subject_4.json.block

When each st-gen process completes, its .block file is removed.
st-bang polls every second and updates the live progress table.

## Cancel / Ctrl+C behaviour
Press Ctrl+C at any time to cancel remaining running jobs.
Any results already written will still be saved into the output .json.

## Stage 2 — Merge
After all jobs finish (or are cancelled), st-bang merges the tmp/_N.json files
into a single subject.json.  Optionally calls st-merge for a master narrative.
"""

# ── ANSI helpers ──────────────────────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
RED     = "\033[31m"
CYAN    = "\033[36m"
DIM     = "\033[2m"

def _clr(text, *codes):
    return "".join(codes) + text + RESET

def _hide_cursor():   sys.stdout.write("\033[?25l"); sys.stdout.flush()
def _show_cursor():   sys.stdout.write("\033[?25h"); sys.stdout.flush()
def _move_up(n):      sys.stdout.write(f"\033[{n}A")
def _clear_line():    sys.stdout.write("\033[2K\r")

# ── Status constants ──────────────────────────────────────────────────────────
ST_PENDING   = "pending"
ST_RUNNING   = "running"
ST_DONE      = "done"
ST_CACHED    = "cached"
ST_FAILED    = "failed"
ST_CANCELLED = "cancelled"

STATUS_LABEL = {
    ST_PENDING:   _clr(" pending   ", DIM),
    ST_RUNNING:   _clr(" running   ", YELLOW, BOLD),
    ST_DONE:      _clr(" done      ", GREEN,  BOLD),
    ST_CACHED:    _clr(" cached    ", CYAN,   BOLD),
    ST_FAILED:    _clr(" failed    ", RED,    BOLD),
    ST_CANCELLED: _clr(" cancelled ", RED,    DIM),
}

# ── Live table ────────────────────────────────────────────────────────────────
COL_AI     = 12   # "xai", "anthropic", "perplexity"
COL_MODEL  = 22   # "claude-opus-4-5", "gemini-2.5-flash"
COL_STATUS = 11   # "done", "running", "failed"
COL_TIME   =  7   # "01:03"

def _fmt_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"

def _draw_table(jobs: list, first_draw: bool = False, row_count: int = 0, args_timeout: int = 0):
    """Render the progress table in-place."""
    # Build header using plain text widths then colorise — avoids ANSI padding inflation
    h_make   = "AI Make"  .ljust(COL_AI)
    h_model  = "Model"    .ljust(COL_MODEL)
    h_status = "Status"   .ljust(COL_STATUS)
    h_time   = "Elapsed"  .ljust(COL_TIME)
    header   = f"  {_clr(h_make, BOLD)}  {_clr(h_model, BOLD)}  {_clr(h_status, BOLD)}  {_clr(h_time, BOLD)}"
    divider  = "  " + "─" * (COL_AI + COL_MODEL + COL_STATUS + COL_TIME + 6)

    rows = [header, divider]
    for j in jobs:
        elapsed = time.time() - j["start_time"] if j["start_time"] else 0.0
        if j["status"] in (ST_DONE, ST_FAILED, ST_CANCELLED) and j["end_time"]:
            elapsed = j["end_time"] - j["start_time"]
        time_str  = _fmt_elapsed(elapsed) if j["status"] in (ST_RUNNING, ST_DONE, ST_FAILED) else "--:--"
        # Build each cell as plain text first so ljust works correctly
        s_make    = j["make"] .ljust(COL_AI)
        s_model   = j["model"].ljust(COL_MODEL)
        s_status  = STATUS_LABEL[j["status"]]   # already colourised; fixed visible width
        s_time    = _clr(time_str.ljust(COL_TIME), CYAN)
        rows.append(f"  {s_make}  {s_model}  {s_status}  {s_time}")

    rows.append(divider)
    timeout_str = f" (timeout: {_fmt_elapsed(args_timeout)})" if args_timeout else ""
    rows.append(_clr(f"  Press Ctrl+C to cancel remaining jobs and collect results so far.{timeout_str}", DIM))

    if not first_draw and row_count > 0:
        _move_up(row_count)

    for row in rows:
        _clear_line()
        print(row)

    sys.stdout.flush()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    require_config()

    parser = argparse.ArgumentParser(
        prog='st-bang',
        description='Run all AI jobs in parallel, show a live progress table,\n'
                    'merge results, and optionally produce a master merged story.')
    parser.add_argument('prompt', nargs='?', type=str,
                        help='Path to the prompt file (e.g. subject.prompt)')
    parser.add_argument('--ai', type=str, choices=get_ai_list(), default=get_default_ai(),
                        help=f'AI to use for the optional merge step (default: {get_default_ai()})')
    parser.add_argument('--cache', dest='cache', action='store_true', default=True,
                        help='Enable API cache (default: enabled)')
    parser.add_argument('--no-cache', dest='cache', action='store_false',
                        help='Disable API cache')
    parser.add_argument('-m', '--merge', action='store_true',
                        help='Merge all stories into a master story via st-merge.')
    parser.add_argument('-s', '--st', action='store_true',
                        help='Load the final .json container into the st app.')
    parser.add_argument('--force', action='store_true',
                        help='Regenerate all stories even if they already exist in the container.')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output.')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Suppress progress table (minimal output).')
    parser.add_argument('--timeout', type=int, default=600,
                        help='Per-job timeout in seconds (default: 600 = 10 min). '
                             '0 = no timeout.')
    args = parser.parse_args()

    if not args.prompt:
        parser.print_help()
        sys.exit(1)

    # ── Resolve file paths ────────────────────────────────────────────────────
    file_prefix = args.prompt.rsplit('.', 1)[0]
    file_prompt = file_prefix + ".prompt"
    file_json   = file_prefix + ".json"

    if not os.path.isfile(file_prompt):
        print(f"Error: prompt file not found: {file_prompt}", file=sys.stderr)
        sys.exit(1)

    # ── Read existing container to detect already-completed stories ──────────
    existing_makes = set()   # set of AI make values that already have a story
                             # whose source prompt matches the current prompt
    existing_container = {"data": [], "story": []}
    prompt_text = ""
    if os.path.isfile(file_prompt):
        with open(file_prompt, 'r') as f:
            prompt_text = f.read().strip()

    if not args.force and os.path.isfile(file_json):
        try:
            with open(file_json, 'r') as f:
                existing_container = json.load(f)
            # A story counts as "done" if:
            #   - the data entry for that AI has a matching prompt, AND
            #   - a corresponding story entry exists for that make
            existing_story_makes = {s.get("make") for s in
                                    existing_container.get("story", [])}
            for d in existing_container.get("data", []):
                d_make   = d.get("make", "")
                d_prompt = d.get("prompt", "").strip()
                if (d_make in existing_story_makes
                        and d_prompt == prompt_text
                        and d_make):
                    existing_makes.add(d_make)
        except (json.JSONDecodeError, Exception) as e:
            print(f"Warning: could not read existing {file_json}: {e}")

    # ── Build per-job metadata ────────────────────────────────────────────────
    ai_list = get_ai_list()
    jobs = []
    n_skipped = 0
    for i, ai_key in enumerate(ai_list):
        bang_name = os.path.basename(file_prefix) + f"_{i}.json"
        out   = str(get_tmp_dir() / bang_name)
        block = str(get_tmp_dir() / f"{tmp_safe_name(out)}.block")
        make  = get_ai_make(ai_key)

        already_done = make in existing_makes
        if already_done:
            n_skipped += 1

        jobs.append({
            "index":      i,
            "ai_key":     ai_key,
            "make":       make,
            "model":      get_ai_model(ai_key),
            "block_file": block,
            "out_file":   out,
            "status":     ST_CACHED if already_done else ST_PENDING,
            "start_time": 0.0 if already_done else None,
            "end_time":   0.0 if already_done else None,
            "process":    None,
            "skipped":    already_done,
        })

    if not args.quiet and n_skipped:
        skipped_makes = [j["make"] for j in jobs if j.get("skipped")]
        print(f"  Skipping {n_skipped} already-complete story/stories: "
              f"{', '.join(skipped_makes)}")
        print(f"  Use --force to regenerate all stories.")

    # ── Pass-through flags ────────────────────────────────────────────────────
    cache_flag   = "" if args.cache else "--no-cache"
    verbose_flag = "--verbose" if args.verbose else ""
    quiet_flag   = "--quiet"   if args.quiet   else ""

    # ── Cancel flag (set by Ctrl+C handler) ──────────────────────────────────
    cancelled = threading.Event()

    def _cancel_all(signum=None, frame=None):
        """Terminate all running subprocesses and mark them cancelled."""
        cancelled.set()
        now = time.time()
        for j in jobs:
            if j["status"] == ST_RUNNING and j["process"]:
                try:
                    j["process"].terminate()
                except OSError:
                    pass
            if j["status"] in (ST_PENDING, ST_RUNNING):
                j["status"]   = ST_CANCELLED
                j["end_time"] = now

    signal.signal(signal.SIGINT, _cancel_all)

    # ── Launch all jobs ───────────────────────────────────────────────────────
    for j in jobs:
        if j["status"] == ST_DONE:   # already complete — skip launch
            continue
        cmd = [
            "st-gen",
            "--ai", j["ai_key"],
            "--bang", str(j["index"]),
        ]
        if cache_flag:   cmd.append(cache_flag)
        if quiet_flag:   cmd.append(quiet_flag)
        cmd.append(file_prompt)

        if args.verbose:
            print(f"Launching: {' '.join(cmd)}")

        try:
            # Redirect child stdout/stderr so it never disrupts the live table.
            # In verbose mode we capture it and print it after the table finishes.
            pipe = subprocess.PIPE if args.verbose else subprocess.DEVNULL
            proc = subprocess.Popen(cmd, stdout=pipe, stderr=pipe)
            j["process"]    = proc
            j["status"]     = ST_RUNNING
            j["start_time"] = time.time()
        except FileNotFoundError:
            j["status"]   = ST_FAILED
            j["end_time"] = time.time()

    # ── Live progress table ───────────────────────────────────────────────────
    if not args.quiet:
        print()   # blank line before table
        _hide_cursor()

    last_row_count = 0   # track how many rows were printed so we move up correctly

    def _redraw(first: bool = False):
        nonlocal last_row_count
        _draw_table(jobs, first_draw=first, row_count=last_row_count,
                    args_timeout=args.timeout)
        # header + divider + N jobs + divider + hint = N + 4
        last_row_count = len(jobs) + 4

    try:
        time.sleep(0.25)   # brief pause to let subprocesses start before first draw

        if not args.quiet:
            _redraw(first=True)

        while not cancelled.is_set():

            for j in jobs:
                if j["status"] not in (ST_RUNNING, ST_PENDING):
                    continue

                proc_exited = j["process"].poll() is not None
                rc          = j["process"].returncode if proc_exited else None

                # Fast-fail: process exited with non-zero return code — don't wait for block/output
                if proc_exited and rc != 0:
                    j["status"]   = ST_FAILED
                    j["end_time"] = time.time()
                    # Clean up stale block file left by a crashed st-gen
                    if os.path.isfile(j["block_file"]):
                        try:
                            os.remove(j["block_file"])
                        except OSError:
                            pass
                    continue

                # Normal completion: block gone + output written + process exited cleanly
                block_gone = j["start_time"] and not os.path.isfile(j["block_file"])
                out_ready  = os.path.isfile(j["out_file"])

                if block_gone and out_ready and proc_exited:
                    j["status"]   = ST_DONE
                    j["end_time"] = time.time()
                    continue

                # Edge case: process exited cleanly but no output file — treat as failure
                if proc_exited and not out_ready:
                    j["status"]   = ST_FAILED
                    j["end_time"] = time.time()
                    continue

                # Per-job timeout
                if args.timeout > 0 and j["start_time"]:
                    if (time.time() - j["start_time"]) > args.timeout:
                        j["status"]   = ST_FAILED
                        j["end_time"] = time.time()
                        try:
                            j["process"].terminate()
                        except OSError:
                            pass

            if not args.quiet:
                _redraw()

            # Exit loop only after drawing the final state
            if all(j["status"] not in (ST_RUNNING, ST_PENDING) for j in jobs):
                break
            time.sleep(1)   # wait 1s between polls; at end so final state draws immediately


    except Exception:
        _cancel_all()

    finally:
        if not args.quiet:
            _show_cursor()
            print()  # blank line after table

    # ── Print captured subprocess output in verbose mode ─────────────────────
    if args.verbose:
        print("── Subprocess output ──")
        for j in jobs:
            if j["process"] and j["process"].stdout:
                try:
                    out, err = j["process"].communicate(timeout=2)
                    if out:
                        print(f"\n[{j['make']}] stdout:\n{out.decode(errors='replace').strip()}")
                    if err:
                        print(f"\n[{j['make']}] stderr:\n{err.decode(errors='replace').strip()}")
                except Exception:
                    pass
        print("───────────────────────")

    # ── Summary line ─────────────────────────────────────────────────────────
    n_done      = sum(1 for j in jobs if j["status"] == ST_DONE)
    n_cached    = sum(1 for j in jobs if j["status"] == ST_CACHED)
    n_failed    = sum(1 for j in jobs if j["status"] == ST_FAILED)
    n_cancelled = sum(1 for j in jobs if j["status"] == ST_CANCELLED)

    # Wall time = from first job launch to last job completion (excludes cached)
    active_jobs = [j for j in jobs if not j.get("skipped")]
    start_times = [j["start_time"] for j in active_jobs if j["start_time"]]
    end_times   = [j["end_time"]   for j in active_jobs if j["end_time"]]
    total_time  = (max(end_times) - min(start_times)) if start_times and end_times else 0.0
    if not args.quiet:
        cached_str = f"  {_clr(str(n_cached), CYAN, BOLD)} cached" if n_cached else ""
        print(
            f"  Results: {_clr(str(n_done), GREEN, BOLD)} done"
            f"{cached_str}  "
            f"{_clr(str(n_failed), RED, BOLD)} failed  "
            f"{_clr(str(n_cancelled), DIM)} cancelled  "
            f"— wall time {_fmt_elapsed(total_time)}"
        )
        print()

    # ── Merge available results into main .json ───────────────────────────────
    main_container = {"data": [], "story": []}
    data_md5_hash  = []
    story_md5_hash = []

    # Load existing container if present
    if os.path.isfile(file_json):
        try:
            with open(file_json, 'r') as f:
                main_container = json.load(f)
            # Ensure both keys exist even if the file is incomplete
            if "data" not in main_container:
                main_container["data"] = []
            if "story" not in main_container:
                main_container["story"] = []
            for d in main_container.get("data",  []):
                data_md5_hash.append(d.get("md5_hash"))
            for s in main_container.get("story", []):
                story_md5_hash.append(s.get("md5_hash"))
            if args.verbose:
                print(f"Loaded existing container: {file_json}")
        except (json.JSONDecodeError, Exception) as e:
            print(f"Warning: could not read existing {file_json}: {e}")
    else:
        if not args.quiet:
            print(f"Creating new container: {file_json}")

    merged_files = []
    skipped = 0
    for j in jobs:
        if j.get("skipped"):          # already in container — nothing to merge
            continue
        if j["status"] != ST_DONE:
            continue
        single = j["out_file"]
        if not os.path.isfile(single):
            if not args.quiet:
                print(f"  Warning: expected result file missing: {single}")
            continue
        try:
            with open(single, 'r') as f:
                part = json.load(f)

            data  = part["data"][0]
            story = part["story"][0]

            # Don't replace a non-cached data entry with a cached one.
            # A cache hit has no useful timing; the existing non-cached entry
            # already has the real elapsed time for this provider.
            is_cached_entry = data.get("timing", {}).get("cached", False)
            non_cached_makes = {
                d.get("make") for d in main_container["data"]
                if not d.get("timing", {}).get("cached", False)
            }
            if is_cached_entry and data.get("make") in non_cached_makes:
                if args.verbose:
                    print(f"  Skipping cached entry for {data.get('make')} "
                          f"(non-cached entry already present)")
                skipped += 1
            elif data["md5_hash"] not in data_md5_hash:
                main_container["data"].append(data)
                data_md5_hash.append(data["md5_hash"])
            else:
                skipped += 1

            if story["md5_hash"] not in story_md5_hash:
                main_container["story"].append(story)
                story_md5_hash.append(story["md5_hash"])
            else:
                skipped += 1

            merged_files.append(single)
            if args.verbose:
                print(f"  Saved: {j['make']} ({single})")

        except (json.JSONDecodeError, KeyError, Exception) as e:
            print(f"  Warning: could not save {single}: {e}")

    # Write merged output
    with open(file_json, 'w', encoding='utf-8') as f:
        json.dump(main_container, f, ensure_ascii=False, indent=4)

    if not args.quiet:
        print(f"  Saved {len(merged_files)} result(s)"
              + (f", skipped {skipped} duplicate(s)" if skipped else "")
              + f" → {file_json}")

    # Purge temporary single-AI .json files
    for fp in merged_files:
        try:
            os.remove(fp)
        except OSError:
            pass
    if args.verbose:
        print(f"  Removed {len(merged_files)} temporary file(s).")

    # ── Stage 2: optional st-merge ────────────────────────────────────────────
    n_stories = len(main_container.get("story", []))
    if args.merge and n_stories > 0:
        if not args.quiet:
            print(f"\n  Running st-merge on {file_json} ({n_stories} stories) …")
        cmd = ["st-merge"]
        if args.ai:
            cmd.extend(["--ai", args.ai])
        if cache_flag:    cmd.append(cache_flag)
        if verbose_flag:  cmd.append(verbose_flag)
        if quiet_flag:    cmd.append(quiet_flag)
        cmd.append(file_json)
        subprocess.run(cmd)

    # ── Stage 3: optional st load ─────────────────────────────────────────────
    if args.st:
        cmd = [x for x in ["st", verbose_flag, quiet_flag, file_json] if x]
        if not args.quiet:
            print(f"  Running: {' '.join(cmd)}")
        subprocess.run(cmd)

    if not args.quiet:
        print()


if __name__ == "__main__":
    main()
