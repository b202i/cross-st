#!/usr/bin/env python3
"""
st-fact — Fact-check stories in a container

```
st-fact subject.json                    # fact-check story 1 with default AI
st-fact -s 2 --ai gemini subject.json  # fact-check story 2 with Gemini
st-fact --no-cache subject.json        # bypass API cache
```

Options: -s story  --ai  --no-cache  -v  -q
"""

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from mmd_startup import require_config, load_cross_env
from ai_handler import process_prompt, get_ai_list, get_content, get_ai_make, get_ai_model, \
    get_default_ai, get_usage
from collections import Counter
from tabulate import tabulate
from tqdm import tqdm

from mmd_branding import get_ai_tag_mini
from mmd_process_report import remove_markdown
from mmd_util import get_tmp_dir, tmp_safe_name, build_segments


def get_fact_check_prompt(paragraph):
    prompt = f"""
    Please fact-check the following paragraph for accuracy:

    {paragraph}

    For each statement in the paragraph:
    
    - Assign a number to each claim (e.g., Claim: 1, Claim: 2).
    - Verify using only these 5 categories: True, False, Partially_true, Partially_false, Opinion.
    - Format as: "Claim [number]: '[claim text]' Verification:[category]"
    - Provide a concise explanation.
    - If a claim is partially true/false, clarify what’s correct/incorrect.
    - If it’s an opinion or unverifiable, state why.
    - If a paragraph is composed of multiple claims, break it into individual claims, and fact check each part.

    Example output:
    Claim 1: "The sky is blue." Verification:True
    Explanation: The sky appears blue due to Rayleigh scattering.

    Additional guidelines:
    - Avoid reproducing the entire paragraph in your response; instead, reference each claim numerically or by quoting key phrases.
    - Use neutral language and do not inject bias into the fact-checking process.
    - If you encounter claims that require expert knowledge or specific data beyond your general knowledge, acknowledge this and suggest where one might find such information.
    """
    return prompt.strip()


def insert_newlines(text):
    # Define the pattern to match the full Verification statement as one unit
    pattern = r'(\s*Verification:\s*(?:True|False|Partially_true|Partially_false|Opinion)\s*)'

    # Split the text, keeping the delimiters
    parts = re.split(pattern, text, flags=re.IGNORECASE)

    # Process each part and reconstruct the string
    result = ''
    for i, part in enumerate(parts):
        stripped_part = part.strip()

        # If this part is a verification statement
        if re.match(r'Verification:\s*(True|False|Partially_true|Partially_false|Opinion)', stripped_part,
                    re.IGNORECASE):
            # Add newline before if previous part doesn't end with one
            if i > 0 and not result.endswith('\n'):
                result += '  \n'
            result += stripped_part
            # Add newline after if next part doesn't start with one
            if i < len(parts) - 1 and not parts[i + 1].startswith('\n'):
                result += '  \n'
        else:
            result += part

    return result


def renumber_claims(text):
    """ Renumbers all occurrences of 'Claim n:' in a text to a sequential order. """
    claim_counter = 1  # Start numbering at 1

    def replace_claim(match):
        """ Replaces each claim with a sequentially numbered claim """
        nonlocal claim_counter
        replacement = f"Claim {claim_counter}:"
        claim_counter += 1
        return replacement

    # Use regex sub to replace each claim occurrence in sequence
    renumbered_text = re.sub(r'Claim\s\d+:', replace_claim, text)

    return renumbered_text


# ── Parallel --ai all dispatcher ─────────────────────────────────────────────

ST_PENDING  = "pending"
ST_RUNNING  = "running"
ST_DONE     = "done"
ST_FAILED   = "failed"

def _run_all_parallel(args, ai_list):
    """
    Spawn one st-fact --silent subprocess per AI in parallel.
    Display a live status table with segment progress (n/total) and elapsed
    time.  Kill any job that exceeds --timeout minutes.
    Ctrl+C cancels remaining jobs and exits cleanly.
    """
    cache_flag  = "--cache" if args.cache else "--no-cache"
    story_flag  = ["-s", str(args.story)] if args.story else []
    # per-job timeout in seconds; --timeout sets minutes (default: 20 minutes)
    job_timeout = (args.timeout * 60) if args.timeout > 0 else 1200

    file_prefix = args.json_file.rsplit('.', 1)[0]
    safe        = tmp_safe_name(file_prefix)
    story_index = args.story if args.story else 1

    ST_TIMEOUT  = "timed out"

    jobs = {}
    for ai in ai_list:
        cmd = (["st-fact", "--silent", "--ai", ai, cache_flag]
               + story_flag
               + [args.json_file])
        jobs[ai] = {
            "cmd":           cmd,
            "status":        ST_PENDING,
            "start":         0.0,
            "elapsed":       0.0,
            "proc":          None,
            "progress":      "",          # "n/total" string read from .progress file
            "progress_file": str(get_tmp_dir() / f"{safe}_s{story_index}_{ai}.progress"),
        }

    lock = threading.Lock()

    def _worker(ai):
        with lock:
            jobs[ai]["status"] = ST_RUNNING
            jobs[ai]["start"]  = time.time()
        try:
            proc = subprocess.Popen(
                jobs[ai]["cmd"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with lock:
                jobs[ai]["proc"] = proc

            # Poll until done or timeout
            while True:
                ret = proc.poll()
                if ret is not None:
                    break
                elapsed = time.time() - jobs[ai]["start"]
                if elapsed > job_timeout:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        proc.kill()
                    with lock:
                        jobs[ai]["status"]  = ST_TIMEOUT
                        jobs[ai]["elapsed"] = elapsed
                    return
                time.sleep(0.5)

            elapsed = time.time() - jobs[ai]["start"]
            with lock:
                jobs[ai]["elapsed"] = elapsed
                jobs[ai]["status"]  = ST_DONE if proc.returncode == 0 else ST_FAILED
        except Exception:
            with lock:
                jobs[ai]["status"]  = ST_FAILED
                jobs[ai]["elapsed"] = time.time() - jobs[ai]["start"]

    def _read_progress(ai):
        """Read n/total from the progress file written by the child process."""
        pf = jobs[ai]["progress_file"]
        try:
            if os.path.exists(pf):
                txt = open(pf).read().strip()
                if "/" in txt:
                    return txt
        except OSError:
            pass
        return ""

    # Launch all workers
    threads = [threading.Thread(target=_worker, args=(ai,), daemon=True)
               for ai in ai_list]
    for t in threads:
        t.start()

    STATUS_ICON = {
        ST_PENDING:  "·",
        ST_RUNNING:  "●",
        ST_DONE:     "✓",
        ST_FAILED:   "✗",
        ST_TIMEOUT:  "⏱",
        "cancelled": "—",
    }

    def _status_cell(ai):
        st = jobs[ai]["status"]
        if st == ST_RUNNING:
            prog = _read_progress(ai)
            return f"running {prog}" if prog else "running"
        return {
            ST_PENDING:  "pending",
            ST_DONE:     "done",
            ST_FAILED:   "failed",
            ST_TIMEOUT:  f"timed out (>{job_timeout//60}m)",
            "cancelled": "cancelled",
        }.get(st, st)

    def _fmt_elapsed(ai):
        st = jobs[ai]["status"]
        if st == ST_PENDING:
            return "--:--"
        elapsed = (time.time() - jobs[ai]["start"]
                   if st == ST_RUNNING
                   else jobs[ai]["elapsed"])
        mm, ss = divmod(int(elapsed), 60)
        return f"{mm:02d}:{ss:02d}"

    def _draw_table():
        rows = []
        for ai in ai_list:
            st = jobs[ai]["status"]
            rows.append([
                STATUS_ICON.get(st, "?"),
                ai,
                _status_cell(ai),
                _fmt_elapsed(ai),
            ])
        return tabulate(rows,
                        headers=["", "AI", "Status", "Elapsed"],
                        tablefmt="plain")

    n_lines = 0
    try:
        while any(jobs[ai]["status"] in (ST_PENDING, ST_RUNNING) for ai in ai_list):
            table  = _draw_table()
            lines  = table.splitlines()
            if n_lines:
                print(f"\033[{n_lines}A", end="")
            for line in lines:
                print(f"  {line:<70}")
            n_lines = len(lines)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n  Cancelling…")
        for ai in ai_list:
            proc = jobs[ai].get("proc")
            if proc and jobs[ai]["status"] == ST_RUNNING:
                proc.terminate()
                jobs[ai]["status"] = "cancelled"
        for t in threads:
            t.join(timeout=5)

    # Final table
    if n_lines:
        print(f"\033[{n_lines}A", end="")
    for line in _draw_table().splitlines():
        print(f"  {line:<70}")
    print()

    done     = sum(1 for ai in ai_list if jobs[ai]["status"] == ST_DONE)
    failed   = sum(1 for ai in ai_list if jobs[ai]["status"] in (ST_FAILED, ST_TIMEOUT, "cancelled"))
    story_str = f" (story {args.story})" if args.story else ""
    timeout_note = f"  (timeout {job_timeout//60}m/job)" if any(
        jobs[ai]["status"] == ST_TIMEOUT for ai in ai_list) else ""
    print(f"  Fact-check{story_str}: {done} done  {failed} failed{timeout_note}")
    print()


def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-fact',
        description='Fact check stories')
    parser.add_argument('json_file', type=str,
                        help='Path to the JSON file', metavar='file.json')
    parser.add_argument('--all', action='store_true',
                        help='Fact check all stories in container')
    parser.add_argument('--ai', type=str, default=get_default_ai(),
                        help=f'AI to use, or "all" to run all AIs in parallel '
                             f'(default: {get_default_ai()})')
    parser.add_argument('--cache', dest='cache', action='store_true', default=True,
                        help='Enable API cache, default: enabled')
    parser.add_argument('--no-cache', dest='cache', action='store_false',
                        help='Disable API cache')
    parser.add_argument('-s', '--story', type=int,
                        help='Fact check a single story (integer), default 1')
    parser.add_argument('--file', action='store_true',
                        help='Write to a file, default is no-file')
    parser.add_argument('--paragraph', action='store_true',
                        help='Write paragraphs a _paragraph_test_n.txt file, default is no')
    parser.add_argument('--display', action='store_true',
                        help='Write results to the display, default is yes-display')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output, default is verbose')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Enable minimal output')
    parser.add_argument('--silent', action='store_true',
                        help='Suppress all output including tqdm progress bars; '
                             'used when called from st-cross as a child process.')
    parser.add_argument('--timeout', type=int, default=0,
                        help='Timeout value: with --ai all, sets per-job limit in minutes '
                             '(default: 20). In single-AI mode, sets per-paragraph limit '
                             'in seconds (default: 0 = no timeout).')
    args = parser.parse_args()

    # ── Validate --ai choice ──────────────────────────────────────────────────
    ai_list = get_ai_list()
    if args.ai != "all" and args.ai not in ai_list:
        parser.error(f"argument --ai: invalid choice: '{args.ai}' "
                     f"(choose from {', '.join(ai_list)}, all)")

    # ── --ai all: spawn one st-fact per AI in parallel, show live table ───────
    if args.ai == "all":
        _run_all_parallel(args, ai_list)
        return

    # --silent implies --quiet and suppresses tqdm
    if args.silent:
        args.quiet = True

    file_prefix = args.json_file.rsplit('.', 1)[0]
    file_json = file_prefix + ".json"
    ai_tag = get_ai_tag_mini(args.ai)


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

    load_cross_env()

    for story_index, story in enumerate(main_container["story"], start=1):
        if args.story is not None and args.story != story_index:
            continue
        make = story.get("make")
        model = story.get("model")
        title = story.get("title")
        text = story.get("text")

        header = f"{file_json} s:{args.story} {make} {model}\n\n"
        if args.verbose:
            print(header)
        report_lines = [header]
        report_summary = ""
        fact_check_counts = None
        fact_check_score = None
        paragraph_test = ""

        # ── Step 1: build (or reuse) the stable segment list ─────────────────
        # Segments are deterministic — identical for every AI checker.
        # Build once, write to the story, reuse on every subsequent call.
        if "segments" not in story or not story["segments"]:
            segments = build_segments(text)
            story["segments"] = segments          # written to JSON at the end
            segments_are_new = True
        else:
            segments = story["segments"]
            segments_are_new = False

        total_para = len(segments)

        # Progress file: written each segment so st-cross can display n/total.
        # Lives in project-root tmp/  e.g. tmp/story__shang__yubikey_2fa_s1_openai.progress
        progress_file = None
        if args.silent:
            safe = tmp_safe_name(file_prefix)
            progress_file = str(get_tmp_dir() / f"{safe}_s{story_index}_{args.ai}.progress")

        overall_tally = Counter()
        structured_claims: list[dict] = []   # populated per-segment, stored in fact["claims"]
        
        # Timing — wall-clock and fresh-only tracked separately so st-speed
        # can compute apples-to-apples comparisons even on partially-cached runs.
        fact_check_start_time = time.time()
        n_fresh  = 0        # segments answered by a live API call
        n_cached = 0        # segments served from cache
        fresh_elapsed_accum  = 0.0   # sum of elapsed time for fresh calls only
        total_tokens_input   = 0     # tokens from fresh calls only
        total_tokens_output  = 0
        total_tokens_total   = 0

        # ── Step 2: iterate segments, call AI, collect structured results ─────
        for n, seg in enumerate(tqdm(segments,
                                     desc="Processing",
                                     ncols=80,
                                     disable=args.silent)):

            # Write progress fraction for st-cross to read
            if progress_file:
                try:
                    with open(progress_file, "w") as _pf:
                        _pf.write(f"{n + 1}/{total_para}")
                except OSError:
                    pass

            para = seg["text"]

            if args.paragraph:
                paragraph_test += para
                paragraph_test += "\n----end para----\n"

            prompt = get_fact_check_prompt(para)
            seg_start_time = time.time()
            try:
                if args.timeout > 0:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        future = ex.submit(
                            process_prompt, args.ai, prompt,
                            verbose=args.verbose, use_cache=args.cache
                        )
                        result = future.result(timeout=args.timeout)
                        gen_payload, client, response, ai_model = result
                        was_cached = result.was_cached
                else:
                    result = process_prompt(args.ai, prompt, verbose=args.verbose, use_cache=args.cache)
                    gen_payload, client, response, ai_model = result
                    was_cached = result.was_cached
                
                seg_elapsed = time.time() - seg_start_time

                # Accumulate timing + tokens only for fresh (non-cached) calls.
                # Cached calls return near-instantly and skew elapsed/tok-per-sec.
                if was_cached:
                    n_cached += 1
                else:
                    n_fresh += 1
                    fresh_elapsed_accum += seg_elapsed
                    seg_usage = get_usage(args.ai, response)
                    total_tokens_input  += seg_usage["input_tokens"]
                    total_tokens_output += seg_usage["output_tokens"]
                    total_tokens_total  += seg_usage["total_tokens"]
                    
            except concurrent.futures.TimeoutError:
                if not args.quiet:
                    print(f"  Timeout on segment {n + 1}/{total_para}, skipping.")
                continue
            except Exception as e:
                if not args.quiet:
                    print(f"  Error on segment {n + 1}/{total_para}: {e}, skipping.")
                continue

            fact_check_text = get_content(args.ai, response) + "  "

            valid_words = ["True", "False", "Partially_true", "Partially_false", "Opinion"]
            if not any(word in fact_check_text for word in valid_words):
                continue

            if args.display:
                print(fact_check_text)
            report_lines.append("\n" + fact_check_text)

            verdict_pattern = r'[\*]*\s*Verification:\s*(True|False|Partially_true|Partially_false|Opinion)\s*[\*]*'
            statuses = re.findall(verdict_pattern, fact_check_text)
            overall_tally.update(status.strip() for status in statuses)

            # ── Step 3: parse AI response into structured claims keyed to seg_id
            # Two formats observed in the wild:
            #   Format A (anthropic/gemini) — Verification on its own line:
            #     Claim 1: "text"
            #     Verification: True
            #     Explanation: ...
            #   Format B (xai/openai) — Verification inline after claim text:
            #     Claim 1: "text" Verification:True
            #     Explanation: ...
            claim_pattern = re.compile(
                r'Claim\s+\d+:\s*'                                       # "Claim N:"
                r'["\u201c]?'                                             # optional open quote
                r'(.*?)'                                                  # claim text (non-greedy)
                r'["\u201d]?'                                             # optional close quote
                r'\s*Verification:\s*'                                    # Verification: (inline or next line)
                r'(True|False|Partially_true|Partially_false|Opinion)'   # verdict
                r'\s*\n\s*Explanation:\s*'                                # Explanation: on next line
                r'(.*?)(?=\nClaim\s+\d+:|\Z)',                           # explanation text
                re.DOTALL | re.IGNORECASE
            )
            for claim_text, verdict, explanation in claim_pattern.findall(fact_check_text):
                structured_claims.append({
                    "seg_id":      seg["id"],
                    "verdict":     verdict.strip(),
                    "explanation": explanation.strip(),
                })


        if args.paragraph:
            with open(file_prefix + f"_paragraph_test_{story_index}.txt", "w") as f:
                f.write(paragraph_test)

        if overall_tally:
            custom_order = ["True", "Partially_true", "Opinion", "Partially_false", "False"]
            score_mapping = {"True": 2, "Partially_true": 1, "Opinion": 0, "Partially_false": -1, "False": -2}
            overall_tally = {k: overall_tally.get(k, 0) for k in custom_order}
            headers_list = custom_order
            counts = [overall_tally[h] for h in headers_list]
            summary_table = tabulate([counts], headers=headers_list, tablefmt="pipe")
            summary_header = "SUMMARY:"
            if not args.quiet:
                print('\n' + summary_header)
                print(summary_table)
            report_lines.append(summary_header)
            report_summary = tabulate([counts], headers=headers_list, tablefmt="pipe")
            report_lines.append(report_summary)
            fact_checked_categories = ["True", "Partially_true", "Opinion", "Partially_false", "False"]
            fact_check_counts = [overall_tally[h] for h in fact_checked_categories]
            total_fact_checked = sum(fact_check_counts) - fact_check_counts[2]
            if total_fact_checked > 0:
                fact_check_score = sum(
                    score_mapping[h] * overall_tally[h] for h in fact_checked_categories) / total_fact_checked
            else:
                fact_check_score = 0
            score_message = f"{ai_tag} Fact Check Score: {fact_check_score:.2f}"
            if args.verbose:
                print(score_message)
            report_lines.append("\n\n" + score_message)
            report_summary += score_message
        else:
            report_lines.append("No verification data found.")

        filename = f"{file_prefix}_{story_index}_fact_check.txt"
        if args.file:
            with open(filename, "w") as f:
                f.write("\n".join(report_lines))

        if "fact" not in story:
            story["fact"] = []

        renumbered_claims = renumber_claims("\n".join(report_lines))
        with_newlines = insert_newlines(renumbered_claims)
        
        # Calculate final timing metrics
        fact_check_end_time  = time.time()
        fact_check_elapsed   = fact_check_end_time - fact_check_start_time
        # tok/s: fresh calls only — avoids inflation from near-instant cache hits
        tok_per_sec = (round(total_tokens_total / fresh_elapsed_accum, 2)
                       if fresh_elapsed_accum > 0 else 0)
        
        # Build timing object.
        # elapsed_seconds       = total wall-clock (includes cache-hit overhead)
        # elapsed_fresh_seconds = cumulative time for live API calls only
        # n_fresh / n_cached    = segment counts; used by st-speed for fair comparisons
        timing = {
            "start_time":             fact_check_start_time,
            "end_time":               fact_check_end_time,
            "elapsed_seconds":        round(fact_check_elapsed, 3),
            "elapsed_fresh_seconds":  round(fresh_elapsed_accum, 3),
            "n_total":                total_para,
            "n_fresh":                n_fresh,
            "n_cached":               n_cached,
            "tokens_input":           total_tokens_input,
            "tokens_output":          total_tokens_output,
            "tokens_total":           total_tokens_total,
            "tokens_per_second":      tok_per_sec,
            "cached":                 n_fresh == 0,   # True only when every segment was cached
        }

        fact_check = {
            "report":  with_newlines,
            "summary": report_summary,
            "counts":  fact_check_counts,
            "score":   fact_check_score,
            "make":    get_ai_make(args.ai),
            "model":   get_ai_model(args.ai),
            "claims":  structured_claims,       # structured list, keyed by seg_id
            "timing":  timing,
        }
        # Hash from content only (excluding timing) so that re-running with
        # updated timing fields does not create phantom duplicates.
        hash_source = {k: v for k, v in fact_check.items() if k != "timing"}
        data_str = json.dumps(hash_source, sort_keys=True)
        md5_hash = hashlib.md5(data_str.encode('utf-8')).hexdigest()
        fact_check["md5_hash"] = md5_hash

        # ── Exclusive file lock: serialise the read-modify-write so concurrent
        # st-fact processes (from st-cross) don't clobber each other's results.
        # The AI call above runs fully in parallel — only this final write step
        # is serialised. Lock file lives in project-root tmp/.
        lock_path = str(get_tmp_dir() / f"{tmp_safe_name(file_prefix)}.lock")
        with open(lock_path, "w") as lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                # Re-read the latest container under the lock so we don't
                # overwrite results written by another process since we started.
                with open(file_json, 'r') as f:
                    main_container = json.load(f)
                story = main_container["story"][story_index - 1]
                if "fact" not in story:
                    story["fact"] = []

                # Write segments to the story if this is the first checker to run.
                if segments_are_new or "segments" not in story or not story["segments"]:
                    story["segments"] = segments

                duplicate_index = None
                for index, existing_fc in enumerate(story["fact"], start=1):
                    if existing_fc.get("md5_hash") == md5_hash:
                        duplicate_index = index
                        if args.verbose:
                            print("Fact check already exists, did not add duplicate")
                        break
                if duplicate_index is None:
                    story["fact"].append(fact_check)
                    if args.verbose:
                        print("Added new fact check")

                    tmp_json = file_json + ".tmp"
                    with open(tmp_json, 'w', encoding='utf-8') as f:
                        json.dump(main_container, f, ensure_ascii=False, indent=4)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_json, file_json)   # atomic on POSIX
                    if args.verbose:
                        print(f"Story container updated: {file_json}")
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)

        # Clean up progress file now that this story is complete
        if progress_file and os.path.exists(progress_file):
            try:
                os.remove(progress_file)
            except OSError:
                pass


if __name__ == "__main__":
    main()
