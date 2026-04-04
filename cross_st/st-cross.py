#!/usr/bin/env python3
"""
st-cross — Run all AI providers and cross-check results

Step 1: Generate N stories, one per AI (via st-gen --prep), in parallel.
Step 2: Fact-check all N stories with all N AIs — N×N jobs.
        Each column (fact-check AI) runs as a separate thread, serializing
        its calls per-story to avoid concurrent writes to the same JSON file.
        This gives N-way parallelism while keeping file writes safe.

Result: an N×N cross-product table saved into the .json container.

Live display: a 2D ANSI table updated every second.
  Rows    = stories (report-generator AI)
  Columns = fact-checker AI
  Cell    = status symbol + elapsed mm:ss

Press Ctrl+C at any time to cancel; results collected so far are preserved.
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
from pathlib import Path

from ai_handler import get_ai_list, get_ai_make, get_ai_model
from mmd_util import get_tmp_dir, tmp_safe_name, build_segments

# ── ANSI helpers ──────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
DIM    = "\033[2m"

def _clr(text, *codes):  return "".join(codes) + str(text) + RESET
def _hide_cursor():       sys.stdout.write("\033[?25l"); sys.stdout.flush()
def _show_cursor():       sys.stdout.write("\033[?25h"); sys.stdout.flush()
def _move_up(n):          sys.stdout.write(f"\033[{n}A")
def _clear_line():        sys.stdout.write("\033[2K\r")

# ── Status constants ──────────────────────────────────────────────────────────
ST_PENDING   = "pending"
ST_RUNNING   = "running"
ST_DONE      = "done"
ST_FAILED    = "failed"
ST_WARNED    = "warned"    # non-zero exit but result exists (e.g. duplicate story)
ST_CANCELLED = "cancelled"
ST_SKIP      = "skip"      # row skipped — no story generated for this AI

CELL_SYMBOL = {
    ST_PENDING:   _clr("  ·  ", DIM),
    ST_RUNNING:   _clr("  ●  ", YELLOW, BOLD),
    ST_DONE:      _clr("  ✓  ", GREEN,  BOLD),
    ST_FAILED:    _clr("  ✗  ", RED,    BOLD),
    ST_CANCELLED: _clr("  —  ", DIM),
    ST_SKIP:      _clr("  ·  ", DIM),
}

def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


# ── Step-1 progress bar (simple one-line) ─────────────────────────────────────
def _draw_gen_table(gen_jobs: list, first_draw: bool, row_count: int) -> int:
    """Single-row generation progress table. Returns new row_count."""
    COL = 13
    header  = "  " + _clr("Step 1 — Generating stories (parallel)", BOLD)
    divider = "  " + "─" * (len(gen_jobs) * (COL + 2) + 2)
    ai_row  = "  " + "  ".join(j["make"].ljust(COL) for j in gen_jobs)

    cell_strs = []
    for j in gen_jobs:
        elapsed = 0.0
        if j["start_time"]:
            end = j["end_time"] if j["end_time"] else time.time()
            elapsed = end - j["start_time"]
        t = _fmt(elapsed) if j["status"] in (ST_RUNNING, ST_DONE, ST_FAILED, ST_WARNED) else "--:--"
        if j["status"] == ST_RUNNING:
            plain   = f"● {t}".ljust(COL)
            colored = _clr(plain, YELLOW, BOLD)
        elif j["status"] == ST_DONE:
            plain   = f"✓ {t}".ljust(COL)
            colored = _clr(plain, GREEN, BOLD)
        elif j["status"] == ST_WARNED:
            plain   = f"~ {t}".ljust(COL)   # non-zero exit but story present
            colored = _clr(plain, YELLOW)
        elif j["status"] == ST_FAILED:
            plain   = f"✗ {t}".ljust(COL)
            colored = _clr(plain, YELLOW, BOLD)  # yellow not red — not catastrophic
        else:
            plain   = f"· --:--".ljust(COL)
            colored = _clr(plain, DIM)
        cell_strs.append(colored)

    cell_row = "  " + "  ".join(cell_strs)
    rows = [header, divider, ai_row, cell_row, divider,
            _clr("  Press Ctrl+C to cancel and collect results so far.", DIM)]

    if not first_draw and row_count > 0:
        _move_up(row_count)
    for row in rows:
        _clear_line(); print(row)
    sys.stdout.flush()
    return len(rows)


def _read_progress(file_prefix: str, si: int, fc_ai: str) -> str:
    """Read n/total from a progress file written by st-fact --silent.
    Returns 'n/total' string or '' if not available."""
    safe = tmp_safe_name(file_prefix)
    path = get_tmp_dir() / f"{safe}_s{si + 1}_{fc_ai}.progress"
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


# ── Step-2 cross-product table ────────────────────────────────────────────────
def _draw_cross_table(cells: dict, ai_list: list, file_prefix: str,
                      first_draw: bool, row_count: int, timeout: int = 0) -> int:
    """
    Draw the N×N cross-product table.
    cells[(story_idx, fc_idx)] = {"status": ..., "start_time": ..., "end_time": ...}
    Rows = story AI (report author), Columns = fact-checker AI.
    """
    N       = len(ai_list)
    COL_LBL = 13   # row label visible width
    COL_CEL = 14   # each cell visible width: "● 03:42 17/47" = 13 chars

    makes = [get_ai_make(a) for a in ai_list]

    # Headers: plain-text ljust first, then colorize
    col_headers = "  " + " " * COL_LBL + "  " + "  ".join(
        _clr(m[:COL_CEL].ljust(COL_CEL), BOLD) for m in makes)
    divider  = "  " + "─" * (COL_LBL + 2 + N * (COL_CEL + 2) + 2)
    fc_label = "  " + " " * COL_LBL + "  " + _clr(
        "← fact-checker AI →".center(N * (COL_CEL + 2)), DIM)

    timeout_str = f"timeout {_fmt(timeout)}/job" if timeout > 0 else "no timeout"
    rows = [
        "",
        _clr("  Step 2 — Cross-product fact-checking", BOLD) + _clr(f"  ({timeout_str})", DIM),
        fc_label,
        col_headers,
        divider,
    ]

    for si, story_ai in enumerate(ai_list):
        story_make = get_ai_make(story_ai)
        # Plain-text label first, then colorize
        row_label = _clr(story_make[:COL_LBL].ljust(COL_LBL), BOLD)
        cell_strs = []
        for fi in range(N):
            cell   = cells.get((si, fi), {"status": ST_PENDING, "start_time": None, "end_time": None})
            status = cell["status"]
            elapsed = 0.0
            if cell["start_time"]:
                end     = cell["end_time"] if cell["end_time"] else time.time()
                elapsed = end - cell["start_time"]

            # Build plain visible text (always exactly COL_CEL chars), then colorize
            if status == ST_RUNNING:
                prog    = _read_progress(file_prefix, si, ai_list[fi])
                t_str   = _fmt(elapsed)
                if prog:
                    inner = f"{t_str} {prog}"
                else:
                    inner = f"{t_str} …"
                plain   = f"● {inner}"
                colored = _clr(plain.ljust(COL_CEL), YELLOW, BOLD)
            elif status == ST_DONE:
                if cell["start_time"] == 0.0 and cell["end_time"] == 0.0:
                    plain   = "✓  prior".ljust(COL_CEL)
                    colored = _clr(plain, DIM)
                else:
                    plain   = f"✓ {_fmt(elapsed).rjust(COL_CEL - 2)}"
                    colored = _clr(plain.ljust(COL_CEL), GREEN, BOLD)
            elif status == ST_FAILED:
                plain   = f"✗ {_fmt(elapsed).rjust(COL_CEL - 2)}"
                colored = _clr(plain.ljust(COL_CEL), YELLOW, BOLD)  # yellow = retry-able, not fatal
            elif status == ST_CANCELLED:
                plain   = "—  --:--".ljust(COL_CEL)
                colored = _clr(plain, DIM)
            else:  # pending
                plain   = "·  --:--".ljust(COL_CEL)
                colored = _clr(plain, DIM)

            cell_strs.append(colored)

        rows.append("  " + row_label + "  " + "  ".join(cell_strs))

    rows.append(divider)

    # Column totals — wall-clock span for each fact-checker column
    # (time from first cell start to last cell end in that column)
    totals = []
    for fi in range(N):
        fresh_cells = [
            cells[(si, fi)] for si in range(N)
            if (cells[(si, fi)]["status"] not in (ST_SKIP, ST_PENDING, ST_CANCELLED)
                and cells[(si, fi)]["start_time"] and cells[(si, fi)]["end_time"]
                and not (cells[(si, fi)]["start_time"] == 0.0
                         and cells[(si, fi)]["end_time"] == 0.0))
        ]
        if fresh_cells:
            col_wall = max(c["end_time"] for c in fresh_cells) - min(c["start_time"] for c in fresh_cells)
            plain   = f"Σ {_fmt(col_wall).rjust(COL_CEL - 2)}".ljust(COL_CEL)
            colored = _clr(plain, CYAN)
        else:
            plain   = "Σ  --:--".ljust(COL_CEL)
            colored = _clr(plain, DIM)
        totals.append(colored)

    total_label = _clr("total".ljust(COL_LBL), DIM)
    rows.append("  " + total_label + "  " + "  ".join(totals))

    rows.append(_clr("  Press Ctrl+C to cancel and collect results so far.", DIM))

    if not first_draw and row_count > 0:
        _move_up(row_count)
    for row in rows:
        _clear_line(); print(row)
    sys.stdout.flush()
    return len(rows)


# ── Segment pre-build helper ─────────────────────────────────────────────────

def _ensure_segments(file_json: str, n_stories: int, quiet: bool = False) -> None:
    """
    For each of the first n_stories stories in file_json, build and store
    story["segments"] if the key is absent or empty.  Written atomically.

    Called once before the N×N fact-check loop so that every st-fact
    subprocess inherits the same stable segment list — making progress
    counts accurate from the first second and ensuring all checkers work
    on identical units.
    """
    try:
        with open(file_json) as f:
            container = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    changed = False
    for story in container.get("story", [])[:n_stories]:
        if story.get("segments"):
            continue                           # already built
        text = story.get("text", "")
        if not text:
            continue
        story["segments"] = build_segments(text)
        changed = True

    if not changed:
        return

    tmp = file_json + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(container, f, ensure_ascii=False, indent=4)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, file_json)
    if not quiet:
        built = sum(1 for s in container.get("story", [])[:n_stories] if s.get("segments"))
        print(f"  Segments built for {_clr(built, GREEN, BOLD)} stories.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-cross',
        description=(
            "Cross-product story generation and fact-checking.\n"
            "Generates N stories (one per AI) then fact-checks each story\n"
            "with every AI, producing an N×N result matrix."
        ),
    )
    parser.add_argument("json_file", type=str, metavar="file.json",
                        help="Path to the JSON container file")
    parser.add_argument("--cache", dest="cache", action="store_true", default=True,
                        help="Enable API cache (default: enabled)")
    parser.add_argument("--no-cache", dest="cache", action="store_false",
                        help="Disable API cache")
    parser.add_argument("--timeout", type=int, default=1800,
                        help="Per-job timeout in seconds (default: 1800 = 30 min). 0 = no timeout.")
    parser.add_argument("--skip-gen", action="store_true",
                        help="Skip Step 1 (story generation). Normally auto-detected: "
                             "if all AI stories already exist in the container, "
                             "Step 1 is skipped automatically without this flag.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable verbose output.")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress live table (minimal output).")
    args = parser.parse_args()

    file_prefix = args.json_file.rsplit(".", 1)[0]
    file_json   = file_prefix + ".json"
    file_prompt = file_prefix + ".prompt"
    cache_flag  = "--cache" if args.cache else "--no-cache"

    ai_list = get_ai_list()
    N       = len(ai_list)

    # ── Auto-detect whether all N stories already exist ───────────────────────
    # If the container has a story entry for every AI make, skip Step 1.
    # --skip-gen forces this; without it we check the container automatically.
    def _stories_complete(json_path: str) -> bool:
        """Return True if json_path has a story for every AI in ai_list."""
        try:
            with open(json_path) as f:
                c = json.load(f)
            existing_makes = {s.get("make") for s in c.get("story", [])}
            needed_makes   = {get_ai_make(a) for a in ai_list}
            return needed_makes.issubset(existing_makes)
        except (OSError, json.JSONDecodeError):
            return False

    skip_gen = args.skip_gen or _stories_complete(file_json)

    if not skip_gen and not os.path.isfile(file_prompt):
        print(f"Error: prompt file not found: {file_prompt}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(file_json):
        with open(file_json, "w") as f:
            json.dump({"data": [], "story": []}, f)

    # ── Shared cancel flag ────────────────────────────────────────────────────
    cancelled = threading.Event()
    _table_lock = threading.Lock()   # protect cursor movement

    def _cancel_all(signum=None, frame=None):
        cancelled.set()

    signal.signal(signal.SIGINT, _cancel_all)

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 1 — Generate stories in parallel using --bang pattern
    # Each st-gen writes to its own <prefix>_N.json so there are no shared-file
    # races at all during generation.  After all jobs finish, we merge them into
    # file_json and then run st-prep sequentially to build the story[] array.
    # ══════════════════════════════════════════════════════════════════════════
    gen_jobs = []
    if skip_gen:
        if not args.quiet:
            reason = "all stories already present" if _stories_complete(file_json) else "--skip-gen"
            print(f"\n  {_clr('Step 1 — Skipped', BOLD)} ({reason})\n")
    else:
        base = Path(file_prefix).name

        for i, ai_key in enumerate(ai_list):
            bang_name = base + f"_{i}.json"
            out_file  = str(get_tmp_dir() / bang_name)
            gen_jobs.append({
                "index":      i,
                "ai_key":     ai_key,
                "make":       get_ai_make(ai_key),
                "model":      get_ai_model(ai_key),
                "status":     ST_PENDING,
                "start_time": None,
                "end_time":   None,
                "process":    None,
                "block_file": str(get_tmp_dir() / f"{tmp_safe_name(out_file)}.block"),
                "out_file":   out_file,
            })

        if not args.quiet:
            print()
            _hide_cursor()

        gen_row_count = 0

        # Launch all generation jobs — each writes to its own _N.json
        for j in gen_jobs:
            cmd = ["st-gen", "--bang", str(j["index"]),
                   "--ai", j["ai_key"], cache_flag, "--quiet", file_prompt]
            try:
                proc = subprocess.Popen(cmd,
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE)
                j["process"]    = proc
                j["status"]     = ST_RUNNING
                j["start_time"] = time.time()
            except FileNotFoundError:
                j["status"]   = ST_FAILED
                j["end_time"] = time.time()

        if not args.quiet:
            gen_row_count = _draw_gen_table(gen_jobs, first_draw=True, row_count=0)

        # Poll until all gen jobs complete
        try:
            while not cancelled.is_set():
                for j in gen_jobs:
                    if j["status"] not in (ST_RUNNING, ST_PENDING):
                        continue
                    block_gone  = not os.path.isfile(j["block_file"])
                    out_ready   = os.path.isfile(j["out_file"])
                    proc_exited = j["process"].poll() is not None
                    if proc_exited:
                        j["end_time"] = time.time()
                        rc = j["process"].returncode
                        # Capture any error output now that the process has exited
                        try:
                            stderr_out = j["process"].stderr.read().decode(errors="replace").strip()
                            if stderr_out:
                                j["error"] = stderr_out
                        except Exception:
                            pass
                        if block_gone and out_ready:
                            j["status"] = ST_DONE if rc == 0 else ST_WARNED
                        else:
                            # Process exited without producing output — failed silently
                            j["status"] = ST_FAILED
                            try:          # clean up any stale block file
                                if os.path.isfile(j["block_file"]):
                                    os.remove(j["block_file"])
                            except OSError:
                                pass
                    elif args.timeout > 0 and j["start_time"] and (time.time() - j["start_time"]) > args.timeout:
                        j["status"]   = ST_FAILED
                        j["end_time"] = time.time()
                        try: j["process"].terminate()
                        except OSError: pass
                        # Remove the block file to avoid stale tmp/ entries.
                        try:
                            if os.path.isfile(j["block_file"]):
                                os.remove(j["block_file"])
                        except OSError:
                            pass

                if not args.quiet:
                    with _table_lock:
                        gen_row_count = _draw_gen_table(gen_jobs, first_draw=False, row_count=gen_row_count)

                if all(j["status"] not in (ST_RUNNING, ST_PENDING) for j in gen_jobs):
                    break
                time.sleep(1)

        except KeyboardInterrupt:
            cancelled.set()
            for j in gen_jobs:
                if j["process"] and j["process"].poll() is None:
                    try: j["process"].terminate()
                    except OSError: pass
                if j["status"] in (ST_RUNNING, ST_PENDING):
                    j["status"] = ST_CANCELLED
                    # Remove the block file so it doesn't litter tmp/ on restart.
                    try:
                        if os.path.isfile(j["block_file"]):
                            os.remove(j["block_file"])
                    except OSError:
                        pass

        if not args.quiet:
            _show_cursor()
            n_done   = sum(1 for j in gen_jobs if j["status"] == ST_DONE)
            n_warned = sum(1 for j in gen_jobs if j["status"] == ST_WARNED)
            n_failed = sum(1 for j in gen_jobs if j["status"] == ST_FAILED)
            warn_str = f"  {_clr(n_warned, YELLOW)} warned" if n_warned else ""
            fail_str = f"  {_clr(n_failed, YELLOW, BOLD)} failed" if n_failed else ""
            print(f"\n  Generation: {_clr(n_done, GREEN, BOLD)} done{warn_str}{fail_str}\n")

            # Show any captured error output from failed gen jobs
            for j in gen_jobs:
                if j.get("error") and j["status"] in (ST_FAILED, ST_WARNED):
                    # Show last 3 lines — that's where the actual exception lives
                    tail = "\n    ".join(j["error"].splitlines()[-3:])
                    print(f"  {_clr(j['make'], BOLD)}: {tail}")

        if cancelled.is_set():
            print("Cancelled during generation. Exiting.")
            sys.exit(0)

        # ── Merge bang files into main container ──────────────────────────────
        if not args.quiet:
            print("  Merging results...")
        main_container: dict = {"data": [], "story": []}
        if os.path.isfile(file_json):
            try:
                with open(file_json) as f:
                    main_container = json.load(f)
            except (OSError, json.JSONDecodeError):
                pass

        merged = 0
        already_present = 0
        for j in gen_jobs:
            if j["status"] != ST_DONE:
                continue
            try:
                with open(j["out_file"]) as f:
                    part = json.load(f)
                for entry in part.get("data", []):
                    # Don't replace a non-cached entry with a cached one —
                    # the non-cached entry has the real generation timing.
                    is_cached = entry.get("timing", {}).get("cached", False)
                    non_cached_makes = {
                        e.get("make") for e in main_container["data"]
                        if not e.get("timing", {}).get("cached", False)
                    }
                    if is_cached and entry.get("make") in non_cached_makes:
                        already_present += 1
                        continue
                    # Deduplicate by md5_hash
                    if not any(e.get("md5_hash") == entry.get("md5_hash")
                               for e in main_container["data"]):
                        main_container["data"].append(entry)
                        merged += 1
                    else:
                        already_present += 1
                os.remove(j["out_file"])
            except (OSError, json.JSONDecodeError):
                pass

        tmp_json = file_json + ".tmp"
        with open(tmp_json, 'w', encoding='utf-8') as f:
            json.dump(main_container, f, ensure_ascii=False, indent=4)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp_json, file_json)
        if not args.quiet:
            if already_present and not merged:
                print(f"  Merged {merged} new result(s), {already_present} already present → {file_json}")
            else:
                print(f"  Merged {merged} result(s) → {file_json}")

        # ── Sequential st-prep pass ───────────────────────────────────────────
        if not args.quiet:
            print("  Preparing stories (sequential)...")
        with open(file_json) as f:
            container = json.load(f)
        n_data = len(container.get("data", []))
        for d_idx in range(1, n_data + 1):
            cmd = ["st-prep", "-d", str(d_idx), "--quiet", file_json]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if not args.quiet:
            with open(file_json) as f:
                final = json.load(f)
            n_stories = len(final.get("story", []))
            print(f"  Stories prepared: {_clr(n_stories, GREEN, BOLD)}/{n_data}\n")

        if n_stories == 0:
            print(_clr("  No stories generated — aborting cross-product.", RED, BOLD),
                  file=sys.stderr)
            sys.exit(1)

    # ══════════════════════════════════════════════════════════════════════════
    # PRE-STEP 2 — Build segments for all stories before launching checkers
    # This ensures every st-fact subprocess reads a pre-built segment list,
    # giving accurate n/total progress from the first second and guaranteeing
    # all N checkers for each story work on identical units.
    # ══════════════════════════════════════════════════════════════════════════
    _ensure_segments(file_json, N, quiet=args.quiet)

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 2 — Fact-check cross-product
    # ══════════════════════════════════════════════════════════════════════════
    # cells[(story_idx, fc_idx)] holds status for each cell in the N×N matrix
    cells = {
        (si, fi): {"status": ST_PENDING, "start_time": None, "end_time": None}
        for si in range(N) for fi in range(N)
    }

    # ── Pre-scan: mark cells already present in the JSON as done ─────────────
    # This makes restart after Ctrl+C instant — cached cells skip re-running.
    n_preloaded = 0
    try:
        with open(file_json) as f:
            existing = json.load(f)
        for si, story in enumerate(existing.get("story", [])[:N]):
            for fact in story.get("fact", []):
                fc_make = fact.get("make", "")
                # Match fact-checker make to column index
                for fi, ai_key in enumerate(ai_list):
                    if get_ai_make(ai_key) == fc_make:
                        if cells[(si, fi)]["status"] == ST_PENDING:
                            cells[(si, fi)]["status"]   = ST_DONE
                            cells[(si, fi)]["start_time"] = 0.0
                            cells[(si, fi)]["end_time"]   = 0.0
                            n_preloaded += 1
                        break
    except (OSError, json.JSONDecodeError, KeyError):
        pass  # no existing data — start fresh

    if not args.quiet and n_preloaded:
        print(f"  Resuming: {_clr(n_preloaded, GREEN, BOLD)} cell(s) already complete in {file_json}")

    cross_row_count = [0]   # mutable so threads can update it

    def _redraw_cross(first: bool = False):
        with _table_lock:
            cross_row_count[0] = _draw_cross_table(
                cells, ai_list, file_prefix, first_draw=first,
                row_count=cross_row_count[0], timeout=args.timeout)

    if not args.quiet:
        print()
        _hide_cursor()
        _redraw_cross(first=True)

    # All 25 cells run fully in parallel. st-fact uses fcntl.flock internally
    # to serialise the final JSON read-modify-write, so no locking is needed here.
    cell_errors: dict = {}

    def _run_cell(si: int, fi: int):
        """Run one fact-check cell; serialised per story-row through story_locks."""
        if cancelled.is_set():
            cells[(si, fi)]["status"] = ST_CANCELLED
            return
        if cells[(si, fi)]["status"] == ST_DONE:   # pre-scanned
            return

        cell = cells[(si, fi)]
        cell["status"]     = ST_RUNNING
        cell["start_time"] = time.time()

        cmd = [
            "st-fact",
            "--silent",
            "--ai", ai_list[fi],
            "--story", str(si + 1),
            "--timeout", str(args.timeout),
            cache_flag,
            file_json,
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=args.timeout if args.timeout > 0 else None,
            )
            if result.returncode == 0:
                cell["status"] = ST_DONE
            else:
                cell["status"] = ST_FAILED
                err = result.stderr.decode(errors="replace").strip()
                if err:
                    cell_errors[(si, fi)] = err
        except subprocess.TimeoutExpired:
            cell["status"] = ST_FAILED
            cell_errors[(si, fi)] = "timeout"
        except KeyboardInterrupt:
            cancelled.set()
            cell["status"] = ST_CANCELLED
        except Exception as e:
            cell["status"] = ST_FAILED
            cell_errors[(si, fi)] = str(e)
        finally:
            if cell["end_time"] is None:
                cell["end_time"] = time.time()

    def _run_column(fi: int):
        """Submit all N stories for fact-checker column fi, in story order."""
        for si in range(N):
            _run_cell(si, fi)

    # N×N threads — one per cell — for full parallelism.
    # st-fact uses fcntl.flock internally to serialise the JSON write,
    # so concurrent calls on the same file are safe.
    threads = [
        threading.Thread(target=_run_cell, args=(si, fi), daemon=True)
        for si in range(N) for fi in range(N)
        if cells[(si, fi)]["status"] != ST_DONE   # skip already-done cells
    ]
    for t in threads:
        t.start()

    # Poll and redraw table while threads are running
    try:
        while True:
            if not args.quiet:
                _redraw_cross()

            if not any(t.is_alive() for t in threads):
                break
            if cancelled.is_set():
                # Mark all still-pending/running cells as cancelled
                for si in range(N):
                    for fi in range(N):
                        if cells[(si, fi)]["status"] in (ST_PENDING, ST_RUNNING):
                            cells[(si, fi)]["status"] = ST_CANCELLED
                break
            time.sleep(1)

    except KeyboardInterrupt:
        cancelled.set()
        for si in range(N):
            for fi in range(N):
                if cells[(si, fi)]["status"] in (ST_PENDING, ST_RUNNING):
                    cells[(si, fi)]["status"] = ST_CANCELLED

    finally:
        # Give daemon threads a moment to notice cancellation
        for t in threads:
            t.join(timeout=2.0)

        # Final redraw after all threads finish
        if not args.quiet:
            _redraw_cross()
            _show_cursor()
            print()

    # ── Summary ───────────────────────────────────────────────────────────────
    n_done      = sum(1 for c in cells.values() if c["status"] == ST_DONE)
    n_failed    = sum(1 for c in cells.values() if c["status"] == ST_FAILED)
    n_cancelled = sum(1 for c in cells.values() if c["status"] == ST_CANCELLED)
    n_skipped   = sum(1 for c in cells.values() if c["status"] == ST_SKIP)

    # Wall time: only fresh cells (exclude prior start==end==0 and skipped)
    fresh = [c for c in cells.values()
             if c["start_time"] and c["end_time"]
             and not (c["start_time"] == 0.0 and c["end_time"] == 0.0)]
    wall_time = (max(c["end_time"] for c in fresh) - min(c["start_time"] for c in fresh)
                 ) if fresh else 0.0

    if not args.quiet:
        skip_str = f"  {_clr(n_skipped, DIM)} skipped" if n_skipped else ""
        print(f"  Cross-product: {_clr(n_done, GREEN, BOLD)} done  "
              f"{_clr(n_failed, YELLOW, BOLD)} failed  "
              f"{_clr(n_cancelled, DIM)} cancelled"
              f"{skip_str}  — wall time {_fmt(wall_time)}")
        print(f"  Results saved to: {file_json}\n")

    # Print diagnostics for any failed cells
    if cell_errors:
        print(_clr("  Failed cells:", RED, BOLD))
        for (si, fi), err in sorted(cell_errors.items()):
            story_make = get_ai_make(ai_list[si])
            fc_make    = get_ai_make(ai_list[fi])
            first_line = err.splitlines()[0] if err else "unknown error"
            print(f"    story={story_make} fc={fc_make}: {first_line}")
        print()


if __name__ == "__main__":
    main()
