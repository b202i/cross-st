#!/usr/bin/env python3
"""
st-stones — Run and score the Cross-Stones benchmark

Computes the cross_stone_score — a composite of factual accuracy (w1=0.7)
and generation speed (w2=0.3) — for each AI across all benchmark domain
containers.  Run ``st-cross`` on each domain first (or pass ``--run``).

Usage:
    st-stones                                     # auto-detect ~/cross-stones/ or ./cross_stones/
    st-stones cross_stones/                       # score all domains in directory
    st-stones cross_stones/*.json                 # explicit file list
    st-stones --run cross_stones/                 # run missing domains then score
    st-stones --no-speed cross_stones/            # accuracy-only (w1=1, w2=0)
    st-stones --w1 0.5 --w2 0.5 cross_stones/    # equal-weight
    st-stones --domain cross_stones/              # include per-domain table
    st-stones --init                              # seed ~/cross-stones/ from bundled prompts
    st-stones --init --dir my_domains/            # seed a custom directory

Scoring formula (from README_stones.md):
    domain_fact_score    = Σ (avg_fact_check_score × n_claims)  across domains
    max_fact_score       = n_domains × n_claims × 2
    speed_score          = 1 / (avg_gen_elapsed + avg_fc_elapsed)
    cross_stone_score    = w1 × (domain_fact_score / max_fact_score)
                         + w2 × (speed_score / max_speed_score)

If timing data is absent, the score falls back to accuracy-only with
the combined weight redistributed to w1.

## Configuration

By default, ``st-stones`` (with no arguments) looks for domains in
``./cross_stones/`` (CWD) then ``~/cross-stones/``.  Set
``CROSS_STONES_DIR`` in ``~/.crossenv`` to use a different location::

    CROSS_STONES_DIR=~/research/my-benchmarks

To move an existing directory and update the config::

    mv ~/cross-stones ~/research/my-benchmarks

Then add to ``~/.crossenv``::

    CROSS_STONES_DIR=~/research/my-benchmarks

After that, ``st-stones`` with no arguments will find the new location
automatically.  See ``st-admin --show`` to confirm the active path.
"""

import argparse
import json
import os
import subprocess
import sys
from mmd_startup import load_cross_env, require_config
from pathlib import Path
from datetime import date as _today_date
from statistics import mean
from typing import Optional

from tabulate import tabulate

from ai_handler import process_prompt, get_content, get_default_ai

# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_W1        = 0.7    # accuracy weight
DEFAULT_W2        = 0.3    # speed weight
CLAIMS_PER_DOMAIN = 10     # standard benchmark prompt size; override with --n-claims

# ANSI helpers
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
DIM    = "\033[2m"
YELLOW = "\033[33m"


def _clr(text, *codes) -> str:
    return "".join(codes) + str(text) + RESET


# ── Core scoring (pure functions — no I/O) ────────────────────────────────────

def compute_domain_scores(container: dict) -> dict:
    """
    Extract per-AI fact-check scores and timing from a single domain container.

    Parameters
    ----------
    container : dict
        A loaded Cross JSON container (must have "story" and optionally "data").

    Returns
    -------
    dict
        Keyed by AI make (string).  Each value is a dict:
            fact_avg        : float | None   — mean fact-check score (−2..+2)
                                               averaged over all evaluator AIs
            n_fact_checkers : int            — how many AIs fact-checked this story
            gen_elapsed     : float | None   — story-generation time in seconds
                                               (None if absent or cached)
            fc_elapsed_list : list[float]    — fact-check elapsed times *as evaluator*
                                               (one entry per story this AI checked)

    Only AI makes that appear as story *authors* are returned.  Timing data is
    collected for those same makes, but from their *evaluator* role as well.
    """
    stories = container.get("story", [])
    data    = container.get("data", [])

    # Generation timing: make → elapsed (first non-cached entry wins)
    gen_elapsed_by_make: dict = {}
    for entry in data:
        make   = entry.get("make", "")
        timing = entry.get("timing") or {}
        if make and not timing.get("cached", False):
            el = timing.get("elapsed_seconds")
            if el is not None:
                gen_elapsed_by_make.setdefault(make, el)

    # Fact-check timing: evaluator make → list of elapsed seconds
    fc_elapsed_by_make: dict = {}
    for story in stories:
        for fc in story.get("fact", []):
            fc_make   = fc.get("make", "")
            fc_timing = fc.get("timing") or {}
            if fc_make and not fc_timing.get("cached", False):
                el = fc_timing.get("elapsed_seconds")
                if el is not None:
                    fc_elapsed_by_make.setdefault(fc_make, []).append(el)

    results: dict = {}
    for story in stories:
        author = story.get("make", "")
        if not author:
            continue
        facts       = story.get("fact", [])
        fact_scores = [fc.get("score") for fc in facts if fc.get("score") is not None]
        results[author] = {
            "fact_avg":        mean(fact_scores) if fact_scores else None,
            "n_fact_checkers": len(fact_scores),
            "gen_elapsed":     gen_elapsed_by_make.get(author),
            "fc_elapsed_list": list(fc_elapsed_by_make.get(author, [])),
        }

    return results


def compute_cross_stone_scores(
    domain_results: list,
    w1: float = DEFAULT_W1,
    w2: float = DEFAULT_W2,
    n_claims: int = CLAIMS_PER_DOMAIN,
    speed_baseline_s: Optional[float] = None,
) -> list:
    """
    Aggregate per-domain scores into the final Cross-Stones leaderboard.

    Parameters
    ----------
    domain_results : list[dict]
        One ``compute_domain_scores()`` output per domain.
    w1 : float
        Accuracy weight (default 0.7).
    w2 : float
        Speed weight (default 0.3).
    n_claims : int
        Expected number of scorable claims per domain per AI (default 10).
    speed_baseline_s : float | None
        Total seconds (gen + fc) locked as the speed baseline when the
        benchmark set was first measured.  When provided, speed is scored
        in **absolute mode**: ``speed_ratio = baseline_s / actual_s``
        (1.0 = at baseline, 2.0 = twice as fast).  ``cross_stone_score``
        may then exceed 1.0, expressing genuine improvement over the
        baseline era.  When None (default), falls back to the original
        **relative mode** where the fastest AI in the current run = 1.0.

    Returns
    -------
    list[dict]
        Sorted descending by ``cross_stone_score``.  Each dict contains:
            make              : str   — AI provider identifier
            fact_score        : float — raw sum of (avg_score × n_claims) across domains
            fact_norm         : float — fact_score / max_possible_fact_score  (0..1)
            speed_score       : float | None — 1 / (avg_gen + avg_fc) seconds
            speed_ratio       : float | None — baseline_s / actual_s (absolute mode
                                               only); 1.0=at baseline, 2.0=2× faster
            speed_norm        : float — absolute mode: speed_ratio; relative mode:
                                        speed_score / max_speed_score.  0 if no timing.
            cross_stone_score : float — composite; may exceed 1.0 in absolute mode
                                        when AI outpaces the baseline era
            n_domains         : int   — domains contributing to this AI's score
            avg_gen_s         : float | None — average generation time (seconds)
            avg_fc_s          : float | None — average fact-check time (seconds)
    """
    n_domains = len(domain_results)
    max_fact  = n_domains * n_claims * 2.0   # all claims True at +2

    # Accumulate per-AI totals across all domains
    totals: dict = {}
    for dr in domain_results:
        for make, info in dr.items():
            if make not in totals:
                totals[make] = {
                    "fact_contributions": [],
                    "gen_elapsed":        [],
                    "fc_elapsed":         [],
                    "n_domains":          0,
                }
            rec = totals[make]
            if info.get("fact_avg") is not None:
                rec["fact_contributions"].append(info["fact_avg"] * n_claims)
                rec["n_domains"] += 1
            if info.get("gen_elapsed") is not None:
                rec["gen_elapsed"].append(info["gen_elapsed"])
            rec["fc_elapsed"].extend(info.get("fc_elapsed_list", []))

    rows = []
    for make, rec in totals.items():
        if not rec["fact_contributions"]:
            continue   # AI authored no stories with fact-checks — skip

        fact_score = sum(rec["fact_contributions"])
        avg_gen    = mean(rec["gen_elapsed"]) if rec["gen_elapsed"] else None
        avg_fc     = mean(rec["fc_elapsed"])  if rec["fc_elapsed"]  else None

        if avg_gen is not None and avg_fc is not None:
            speed_score: Optional[float] = 1.0 / (avg_gen + avg_fc)
        elif avg_gen is not None:
            speed_score = 1.0 / avg_gen
        elif avg_fc is not None:
            speed_score = 1.0 / avg_fc
        else:
            speed_score = None

        # Absolute speed ratio vs baseline:
        #   ratio = 1.0 → AI matches baseline-era speed
        #   ratio = 2.0 → AI is twice as fast as baseline
        speed_ratio: Optional[float] = None
        if speed_score is not None and speed_baseline_s is not None and speed_baseline_s > 0:
            speed_ratio = speed_score * speed_baseline_s   # = baseline_s / actual_s

        rows.append({
            "make":        make,
            "fact_score":  fact_score,
            "speed_score": speed_score,
            "speed_ratio": speed_ratio,
            "n_domains":   rec["n_domains"],
            "avg_gen_s":   avg_gen,
            "avg_fc_s":    avg_fc,
        })

    if not rows:
        return []

    # Normalise fact:  README formula → domain_fact_score / max_fact_score
    for r in rows:
        r["fact_norm"] = r["fact_score"] / max_fact if max_fact > 0 else 0.0

    # Normalise speed
    abs_mode = speed_baseline_s is not None
    if abs_mode:
        # Absolute mode: speed_norm = baseline_s / actual_s
        #   1.0 = at baseline-era speed  |  2.0 = twice as fast
        # cross_stone_score is intentionally allowed to exceed 1.0 in this mode
        # so that year-over-year improvement is visible in the composite score.
        for r in rows:
            r["speed_norm"] = r["speed_ratio"] if r["speed_ratio"] is not None else 0.0
    else:
        # Relative mode: normalise to fastest AI in this run (original behaviour)
        # Works only when multiple AIs are present; single-AI runs get speed_norm=1.0
        speed_vals = [r["speed_score"] for r in rows if r["speed_score"] is not None]
        max_speed  = max(speed_vals) if speed_vals else None
        for r in rows:
            if r["speed_score"] is not None and max_speed and max_speed > 0:
                r["speed_norm"] = r["speed_score"] / max_speed
            else:
                r["speed_norm"] = 0.0

    # Cross-stone composite
    total_w = w1 + w2
    for r in rows:
        if r.get("speed_score") is not None:
            r["cross_stone_score"] = w1 * r["fact_norm"] + w2 * r["speed_norm"]
        else:
            # No timing available: redistribute speed weight to accuracy
            r["cross_stone_score"] = (w1 / total_w * r["fact_norm"]) if total_w > 0 else r["fact_norm"]

    rows.sort(key=lambda r: r["cross_stone_score"], reverse=True)
    return rows


# ── Display helpers ───────────────────────────────────────────────────────────

def display_leaderboard(
    scores: list,
    w1: float,
    w2: float,
    n_domains: int = 0,
    n_claims: int = CLAIMS_PER_DOMAIN,
    speed_baseline_s: Optional[float] = None,
    baseline_date: Optional[str] = None,
) -> None:
    """Print the Cross-Stones leaderboard to stdout."""
    if not scores:
        print("No scores to display.")
        return

    max_fact = n_domains * n_claims * 2
    abs_mode = speed_baseline_s is not None and any(
        r.get("speed_ratio") is not None for r in scores
    )

    if abs_mode:
        headers = ["#", "AI", "Fact Score", f"/±{max_fact:.0f}", "Fact%",
                   "vs Baseline", "Cross-Stone", "Domains"]
    else:
        headers = ["#", "AI", "Fact Score", f"/±{max_fact:.0f}", "Fact%",
                   "Speed (1/s)", "Speed%", "Cross-Stone", "Domains"]

    rows = []
    for i, r in enumerate(scores, 1):
        fact_norm = f"{r.get('fact_norm', 0.0):.1%}"
        if abs_mode:
            ratio      = r.get("speed_ratio")
            speed_col  = f"{ratio:.2f}×" if ratio is not None else "  —  "
            extra_cols = []
        else:
            speed_col  = (f"{r['speed_score']:.4f}"
                          if r.get("speed_score") is not None else "  —  ")
            extra_cols = [f"{r.get('speed_norm', 0.0):.1%}"]
        rows.append([
            i, r["make"],
            f"{r['fact_score']:+.1f}",
            f"+{max_fact:.0f}" if max_fact else "—",
            fact_norm, speed_col, *extra_cols,
            f"{r['cross_stone_score']:.4f}",
            r["n_domains"],
        ])

    print()
    title_line = (f"  Cross-Stones Leaderboard  "
                  f"(w1={w1:.1f} accuracy,  w2={w2:.1f} speed)")
    if abs_mode and baseline_date:
        title_line += f"  [absolute vs {baseline_date}]"
    print(_clr(title_line, BOLD, CYAN))
    if abs_mode:
        ref = baseline_date or "baseline"
        print(_clr(
            f"  vs Baseline: 1.00× = {ref} speed  "
            f"— score > 1.0 means AI surpasses the {ref[:4]} benchmark era",
            DIM,
        ))
    else:
        print(_clr(
            "  ⚠  Speed in relative mode (no baseline set) — "
            "Speed% 100% = fastest in this run only.  "
            "Run  st-stones --set-baseline  after a full run to enable absolute scoring.",
            YELLOW,
        ))
    print()
    print(tabulate(rows, headers=headers, tablefmt="github"))
    print()


def display_domain_breakdown(domain_results: list, domain_names: list) -> None:
    """Print a per-domain × per-AI fact score table."""
    if not domain_results:
        return

    all_makes = sorted({m for dr in domain_results for m in dr})
    headers   = ["Domain"] + all_makes
    rows = []
    for name, dr in zip(domain_names, domain_results):
        row = [name[:32]]
        for make in all_makes:
            info = dr.get(make, {})
            fa   = info.get("fact_avg")
            row.append(f"{fa:.2f}" if fa is not None else "  —  ")
        rows.append(row)

    print()
    print(_clr("  Per-Domain Fact Scores  (avg across evaluators,  −2..+2)", BOLD))
    print()
    print(tabulate(rows, headers=headers, tablefmt="github"))
    print()


# ── Historical snapshots ──────────────────────────────────────────────────────

def display_history(config: dict) -> None:
    """
    Display the full Cross-Stones snapshot history stored in a benchmark
    set config, including composite-score, speed-ratio, and accuracy tables.
    """
    snapshots = config.get("snapshots", [])
    set_id    = config.get("id", "?")
    baseline  = config.get("speed_baseline") or {}

    print()
    print(_clr(f"  Cross-Stones Snapshot History  [{set_id}]", BOLD, CYAN))

    if baseline.get("total_seconds"):
        bl_date = baseline.get("recorded_date", "?")
        print(
            f"  Speed baseline : "
            f"{baseline.get('gen_seconds', 0):.1f}s gen + "
            f"{baseline.get('fc_seconds', 0):.1f}s fc = "
            f"{baseline['total_seconds']:.1f}s total  (recorded {bl_date})"
        )
    else:
        print(_clr(
            "  No speed baseline set.  Run  st-stones --set-baseline  after a complete run.",
            DIM,
        ))

    if not snapshots:
        print()
        print(_clr(
            "  No snapshots recorded yet.  "
            "Run  st-stones --record-snapshot  to save the current run.",
            DIM,
        ))
        print()
        return

    # Collect all AI makes (ordered by first appearance)
    all_makes: list = []
    seen: set = set()
    for snap in snapshots:
        for make in snap.get("scores", {}):
            if make not in seen:
                all_makes.append(make)
                seen.add(make)
    all_makes.sort()

    # ── Composite score history ───────────────────────────────────────────────
    print()
    print(_clr("  Composite cross_stone_score over time:", BOLD))
    print()
    cs_headers = ["Date", "Label"] + all_makes + ["🏆 Top AI"]
    cs_rows = []
    for snap in snapshots:
        sc  = snap.get("scores", {})
        top = (max(sc, key=lambda m: sc[m].get("cross_stone_score", -999))
               if sc else "—")
        row = [snap.get("date", "?"), (snap.get("label") or "")[:28]]
        for make in all_makes:
            entry = sc.get(make)
            row.append(f"{entry['cross_stone_score']:.4f}" if entry else "  —  ")
        row.append(top)
        cs_rows.append(row)
    print(tabulate(cs_rows, headers=cs_headers, tablefmt="github"))

    # ── Speed ratio history (only when baseline present) ─────────────────────
    has_ratio = any(
        snap.get("scores", {}).get(make, {}).get("speed_ratio") is not None
        for snap in snapshots
        for make in all_makes
    )
    if has_ratio and baseline.get("recorded_date"):
        bl_year = baseline["recorded_date"][:4]
        print()
        print(_clr(
            f"  Speed ratio vs {baseline['recorded_date']} baseline"
            f"  (1.00× = at baseline,  2.00× = twice as fast,  faster is 🚀):",
            BOLD,
        ))
        print()
        sp_headers = ["Date", "Label"] + all_makes + [f"🚀 Fastest vs {bl_year}"]
        sp_rows = []
        for snap in snapshots:
            sc     = snap.get("scores", {})
            ratios = {
                m: sc[m]["speed_ratio"]
                for m in all_makes
                if sc.get(m, {}).get("speed_ratio") is not None
            }
            fastest = max(ratios, key=ratios.get) if ratios else "—"
            row = [snap.get("date", "?"), (snap.get("label") or "")[:28]]
            for make in all_makes:
                ratio = sc.get(make, {}).get("speed_ratio")
                row.append(f"{ratio:.2f}×" if ratio is not None else "  —  ")
            row.append(fastest)
            sp_rows.append(row)
        print(tabulate(sp_rows, headers=sp_headers, tablefmt="github"))

    # ── Accuracy (fact_norm) history ──────────────────────────────────────────
    print()
    print(_clr("  Accuracy (fact_norm, 0.0–1.0) over time:", BOLD))
    print()
    fa_headers = ["Date", "Label"] + all_makes
    fa_rows = []
    for snap in snapshots:
        sc  = snap.get("scores", {})
        row = [snap.get("date", "?"), (snap.get("label") or "")[:28]]
        for make in all_makes:
            entry = sc.get(make)
            row.append(f"{entry['fact_norm']:.1%}" if entry else "  —  ")
        fa_rows.append(row)
    print(tabulate(fa_rows, headers=fa_headers, tablefmt="github"))
    print()


def save_snapshot(
    config_path: Path,
    scores: list,
    label: str,
    w1: float,
    w2: float,
    n_domains: int,
    n_claims: int,
) -> None:
    """
    Append the current leaderboard results as a named snapshot in the
    benchmark set config file, enabling year-over-year comparison.
    """
    with open(config_path) as f:
        config = json.load(f)

    today = _today_date.today().isoformat()
    snapshot: dict = {
        "date":      today,
        "label":     label,
        "w1":        w1,
        "w2":        w2,
        "n_domains": n_domains,
        "n_claims":  n_claims,
        "scores":    {},
    }
    for r in scores:
        make = r["make"]
        snapshot["scores"][make] = {
            "fact_score":        round(r["fact_score"], 3),
            "fact_norm":         round(r.get("fact_norm", 0.0), 4),
            "speed_ratio":       (round(r["speed_ratio"], 4)
                                  if r.get("speed_ratio") is not None else None),
            "avg_gen_s":         (round(r["avg_gen_s"], 2)
                                  if r.get("avg_gen_s") is not None else None),
            "avg_fc_s":          (round(r["avg_fc_s"], 2)
                                  if r.get("avg_fc_s") is not None else None),
            "cross_stone_score": round(r["cross_stone_score"], 4),
            "n_domains":         r["n_domains"],
        }

    if "snapshots" not in config:
        config["snapshots"] = []
    config["snapshots"].append(snapshot)

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    n = len(scores)
    print(f"  ✓  Snapshot '{label}' saved  "
          f"({n} AI{'s' if n != 1 else ''}, {today})  →  {config_path.name}")


def set_baseline_in_config(
    config_path: Path,
    avg_gen_s: float,
    avg_fc_s: float,
) -> None:
    """
    Record the current run's average timing as the locked speed baseline in
    the benchmark set config.  Future runs scoring faster will have
    speed_ratio > 1.0 and cross_stone_score may exceed 1.0.
    """
    with open(config_path) as f:
        config = json.load(f)

    total_s = avg_gen_s + avg_fc_s
    today   = _today_date.today().isoformat()
    config["speed_baseline"] = {
        "gen_seconds":   round(avg_gen_s, 2),
        "fc_seconds":    round(avg_fc_s, 2),
        "total_seconds": round(total_s, 2),
        "recorded_date": today,
        "notes": (
            f"Baseline recorded {today} — average across all AI providers.  "
            f"Future runs faster than {total_s:.1f}s total will have "
            f"speed_ratio > 1.0 and cross_stone_score may exceed 1.0, "
            f"reflecting genuine improvement over the {today[:4]} benchmark era."
        ),
    }

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(
        f"  ✓  Speed baseline recorded: "
        f"gen={avg_gen_s:.1f}s + fc={avg_fc_s:.1f}s = {total_s:.1f}s total"
    )
    print(f"     Saved to {config_path.name}  (use --history to review over time)")


# ── AI content generation — prompts for --ai-title / --ai-short / --ai-caption ──

def validate_ai_content(content: str, content_type: str = "caption"):
    """
    Validate that AI-generated content meets word-count and data requirements.

    Parameters
    ----------
    content      : Generated text to validate.
    content_type : 'title' | 'short' | 'caption'

    Returns
    -------
    tuple (is_valid: bool, word_count: int, error_msg: str | None)
    """
    if not content:
        return False, 0, "Empty content"

    content    = content.strip()
    word_count = len(content.split())

    requirements = {
        "title":   (1,   10,  "title"),
        "short":   (40,  80,  "short caption"),
        "caption": (100, 160, "detailed caption"),
        "summary": (120, 200, "summary"),
        "story":   (800, 1200, "story"),
    }

    if content_type not in requirements:
        return False, word_count, f"Unknown content_type: {content_type!r}"

    min_words, max_words, label = requirements[content_type]

    if word_count < min_words:
        return False, word_count, f"{label} too short ({word_count} words, need {min_words}+)"
    if word_count > max_words:
        return False, word_count, f"{label} too long ({word_count} words, max {max_words})"

    # Captions must reference at least one number (proves data was used)
    if content_type == "caption" and not any(ch.isdigit() for ch in content):
        return False, word_count, f"{label} lacks data (no numbers found)"

    return True, word_count, None


def _format_leaderboard_for_prompt(
    scores: list,
    w1: float,
    w2: float,
    n_domains: int,
    n_claims: int,
    speed_baseline_s: Optional[float] = None,
) -> str:
    """Render the leaderboard as plain text suitable for embedding in an AI prompt."""
    if not scores:
        return "No leaderboard data available."
    max_fact = n_domains * n_claims * 2
    abs_mode = speed_baseline_s is not None and any(
        r.get("speed_ratio") is not None for r in scores
    )
    if abs_mode:
        headers = ["#", "AI", "Fact Score", f"/±{max_fact}", "Fact%",
                   "vs Baseline", "Cross-Stone", "Domains"]
    else:
        headers = ["#", "AI", "Fact Score", f"/±{max_fact}", "Fact%",
                   "Speed(1/s)", "Speed%", "Cross-Stone", "Domains"]
    rows = []
    for i, r in enumerate(scores, 1):
        if abs_mode:
            ratio     = r.get("speed_ratio")
            speed_col = f"{ratio:.2f}×" if ratio is not None else "—"
            extra     = []
        else:
            speed_col = (f"{r['speed_score']:.4f}"
                         if r.get("speed_score") is not None else "—")
            extra     = [f"{r.get('speed_norm', 0.0):.1%}"]
        rows.append([
            i, r["make"],
            f"{r['fact_score']:+.1f}", f"+{max_fact}",
            f"{r.get('fact_norm', 0.0):.1%}",
            speed_col, *extra,
            f"{r['cross_stone_score']:.4f}",
            r["n_domains"],
        ])
    return tabulate(rows, headers=headers, tablefmt="simple")


def build_stones_prompt(
    scores: list,
    w1: float,
    w2: float,
    n_domains: int,
    n_claims: int,
    domain_names: list,
    content_type: str = "caption",
    speed_baseline_s: Optional[float] = None,
    baseline_date: Optional[str] = None,
) -> str:
    """
    Build an AI prompt for interpreting the Cross-Stones leaderboard.

    Parameters
    ----------
    scores           : output of compute_cross_stone_scores()
    w1, w2           : accuracy / speed weights used for this run
    n_domains        : number of benchmark domains scored
    n_claims         : expected claims per domain (default 10)
    domain_names     : human-readable domain names for context
    content_type     : 'title' | 'short' | 'caption'
    speed_baseline_s : total baseline seconds if absolute speed mode is active
    baseline_date    : ISO date string when the baseline was recorded
    """
    table    = _format_leaderboard_for_prompt(
        scores, w1, w2, n_domains, n_claims, speed_baseline_s
    )
    max_fact    = n_domains * n_claims * 2
    domains_str = (", ".join(domain_names) if domain_names
                   else f"{n_domains} benchmark domain(s)")
    abs_mode    = speed_baseline_s is not None

    if abs_mode:
        ref         = baseline_date or "baseline"
        speed_def   = (
            f"  vs Baseline — speed ratio vs the {ref} baseline:\n"
            f"                1.00× = matched {ref[:4]} speed,  2.00× = twice as fast.\n"
            f"  Score       — composite (w1 × Fact% + w2 × vs-Baseline); may exceed 1.0\n"
            f"                when the AI outperforms the {ref[:4]} benchmark era."
        )
        baseline_ln = f"Speed baseline    : {speed_baseline_s:.1f}s total  (recorded {ref})\n"
    else:
        speed_def   = (
            f"  Speed (1/s) — 1 / (avg generation time + avg fact-check time in seconds).\n"
            f"                Higher is faster.\n"
            f"  Score       — composite: w1 × Fact% + w2 × Speed%"
        )
        baseline_ln = ""

    # Shared context block — included in every prompt variant
    context = f"""\
CROSS-STONES BENCHMARK LEADERBOARD
Accuracy weight (w1): {w1:.1f}    Speed weight (w2): {w2:.1f}
Domains evaluated   : {domains_str}
Claims per domain   : {n_claims}
{baseline_ln}Max possible fact score: ±{max_fact}  (all claims rated True = +{max_fact}, all False = −{max_fact})

KEY DEFINITIONS
  Fact Score  — sum of (avg peer rating × {n_claims}) per domain.
                NEGATIVE means the AI's benchmark stories contained claims
                which, on balance, the other AIs rated as FALSE.
{speed_def}

LEADERBOARD
{table}
"""

    if content_type == "title":
        return f"""Write a SHORT, punchy title summarising this AI benchmark leaderboard result.

{context}
LENGTH : Maximum 10 words (strict).
STYLE  : Name the winner. Capture the key finding (accuracy vs speed tension if interesting).
         No articles (a/an/the) unless essential.
FORMAT : Plain text, single line, no quotes or markdown.

GOOD: "Anthropic Leads Accuracy; Perplexity Wins Speed Race"
GOOD: "Benchmark: Accuracy Trumps Speed in AI Fact-Checking"
BAD : "An Analysis of the AI Benchmark Performance Results Today"
"""

    elif content_type == "short":
        return f"""Write a SHORT one-paragraph caption summarising this AI benchmark leaderboard.

{context}
AUDIENCE: Technical readers who understand AI but not this specific benchmark.
LENGTH  : 40–80 words (strict).

NUMBER RULES
• 2–4 whole numbers maximum. Round all figures.
• Natural phrasing: "two-thirds accurate", "under a minute", "3× faster"
• NEVER copy raw decimals from the table (avoid "0.0327", "0.519", "-0.2021")

CONTENT
• Who leads overall and why (accuracy weight dominates at {w1:.0%}).
• Note if the speed leader and accuracy leader are different AIs.
• A negative Fact Score = that AI's claims were mostly rejected by peer fact-checkers.

FORMAT: Plain text, one paragraph, no markdown.
"""

    elif content_type == "caption":
        return f"""Write a detailed two-paragraph caption explaining this AI benchmark leaderboard.

{context}
AUDIENCE: Technical readers (engineers, researchers) familiar with AI evaluation.
LENGTH  : 100–160 words (strict).

NUMBER RULES
• 4–8 whole numbers across both paragraphs. Round everything.
• Natural phrasing: "two-thirds of claims verified", "30 seconds per fact-check"
• NEVER copy raw decimals ("0.0327", "0.519", "-0.2021")
• Comparisons welcome: "3× faster", "twice as accurate"

STRUCTURE
Paragraph 1 — Accuracy story:
  Who leads, who lags, what negative scores mean (claims rejected by peer AIs),
  how many domains contributed (more = more reliable verdict).

Paragraph 2 — Speed and composite story:
  Fastest vs slowest fact-checker column, how the {w1:.0%}/{w2:.0%} accuracy/speed
  weighting shaped the final ranking, any counter-intuitive result
  (e.g. slow-but-accurate AI outranking fast-but-inaccurate one).

FORMAT: Plain text, two paragraphs, professional but readable tone.
"""

    elif content_type == "summary":
        return f"""Write a TECHNICAL SUMMARY (120–200 words, 3 paragraphs) for this AI benchmark leaderboard.

{context}
AUDIENCE: Technical readers (engineers, researchers) making AI infrastructure decisions.

Paragraph 1 — Accuracy story:
  Who leads on fact accuracy and who lags? What does a negative Fact Score mean in practice?
  How many domains contributed (affects reliability of the verdict)?

Paragraph 2 — Speed and composite story:
  Who is fastest and slowest? How does the {w1:.0%}/{w2:.0%} accuracy/speed weighting shape
  the final ranking? Any AI that trades speed for accuracy (or vice versa)?

Paragraph 3 — Practical recommendation:
  For everyday report generation and fact-checking, which AI would you choose and why?
  Any caveat about the runner-up or a surprising result?

NUMBER RULES: 6–10 whole numbers. Round everything. No raw decimals.
FORMAT: Plain text, 3 paragraphs, professional."""

    elif content_type == "story":
        return f"""You are a technical AI investigator writing for an engineering publication.

{context}
AUDIENCE: Technical readers (engineering teams, AI researchers) who want a thorough benchmark analysis.

Write a COMPREHENSIVE STORY (800–1200 words) about this Cross-Stones leaderboard.

STRUCTURE:
1. Title (≤10 words, punchy)
2. What Cross-Stones measures and why it matters (100–150 words)
3. Accuracy deep-dive (300–400 words) — leader, laggard, what negative scores mean,
   domain breadth and its effect on confidence
4. Speed and composite analysis (200–300 words) — fastest vs slowest fact-checker,
   how the {w1:.0%}/{w2:.0%} weighting shaped final ranks, counter-intuitive results
5. Bottom line (100–150 words) — which AI to use and when, what this benchmark reveals
   about the state of AI accuracy and reliability

NUMBER RULES: 12–18 whole numbers. Round everything. Each data point mentioned once.
WRITING RULES: No repetition. No filler. Strong close. Professional tone.
FORMAT: Plain text, clear paragraph breaks. No markdown headers."""

    else:
        raise ValueError(f"Unknown content_type for build_stones_prompt: {content_type!r}")


# ── File helpers ──────────────────────────────────────────────────────────────

def collect_json_files(paths: list) -> list:
    """
    Expand a list of directory/file path strings into a sorted list of Paths.

    Directories are searched for ``*.prompt`` files (genuine benchmark domains).
    If none are found directly in the directory, a ``domains/`` subdirectory is
    checked (the standard Cross-Stones layout after file reorganisation).
    Plain ``.json`` paths are accepted as-is.
    """
    result = []
    for p_str in paths:
        p = Path(p_str)
        if p.is_dir():
            prompts = sorted(p.glob("*.prompt"))
            if not prompts:
                prompts = sorted((p / "domains").glob("*.prompt"))
            for prompt in prompts:
                result.append(prompt.with_suffix(".json"))
        elif p_str.endswith(".json"):
            result.append(p)
        else:
            result.append(p.with_suffix(".json"))
    return result


def _is_benchmark_set_config(path: Path) -> bool:
    """Return True if *path* is a benchmark set config (has 'id' + 'domains' list)."""
    if not path.is_file() or path.suffix != ".json":
        return False
    try:
        with open(path) as f:
            data = json.load(f)
        return "id" in data and isinstance(data.get("domains"), list)
    except (OSError, json.JSONDecodeError):
        return False


def _load_benchmark_set(path: Path) -> tuple:
    """
    Load a benchmark set config and return (domain_json_paths, config_dict).

    Domain paths are resolved relative to the config file's directory using the
    ``domains_dir`` field (default: ``domains``).
    """
    with open(path) as f:
        config = json.load(f)
    domains_dir = path.parent / config.get("domains_dir", "domains")
    domain_paths = [
        domains_dir / f"{d['id']}.json"
        for d in config.get("domains", [])
    ]
    return domain_paths, config


def domain_is_complete(json_path: Path) -> bool:
    """
    Return True if the container at *json_path* exists and every story
    has at least one fact-check entry.
    """
    if not json_path.exists():
        return False
    try:
        with open(json_path) as f:
            c = json.load(f)
        stories = c.get("story", [])
        return bool(stories) and all(bool(s.get("fact")) for s in stories)
    except (OSError, json.JSONDecodeError):
        return False


# ── CLI ───────────────────────────────────────────────────────────────────────

def _stones_first_run() -> None:
    """
    Interactive first-run prompt shown when no cross-stones directory is found.
    Offers to seed ~/cross-stones/ or ./cross_stones/ from bundled domain prompts.
    """
    from mmd_util import seed_stones_domains, get_default_stones_dir

    home_stones = get_default_stones_dir()
    cwd_stones  = Path("cross_stones").resolve()

    print()
    print("  No cross-stones directory found.")
    print()
    print("  Where would you like to create it?")
    print(f"    [1] {home_stones}/  (home directory — recommended)")
    print(f"    [2] {cwd_stones}/  (current directory)")
    print( "    [3] Cancel")
    print()
    try:
        ans = input("  Choice [1]: ").strip() or "1"
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.")
        return

    if ans == "1":
        dst = home_stones
    elif ans == "2":
        dst = cwd_stones
    else:
        print("  Cancelled.")
        return

    copied, _ = seed_stones_domains(dst_dir=dst, overwrite=False, quiet=False)
    if copied == 0:
        print("\n  Bundled domain prompts not found.", file=sys.stderr)
        print("  Run from the repo root or after installing cross-ai.", file=sys.stderr)
        return

    print(f"\n  ✓  Created {dst}/ with {copied} standard domain prompts.")
    print()
    print("  Next steps:")
    print(f"    st-cross  {dst}/<domain>.json  # run fact-checks on a domain first")
    print(f"    st-stones {dst}/               # score all domains")
    print(f"    st-domain --dir {dst}/         # create a custom domain")


def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog="st-stones",
        description=(
            "Cross-Stones benchmark aggregator.\n\n"
            "Scores AI providers across multiple benchmark domain containers\n"
            "using a composite of factual accuracy (w1) and speed (w2).\n\n"
            "Run 'st-cross cross_stones/<domain>.json' for each domain first,\n"
            "or pass --run to have st-stones do it automatically.\n\n"
            "Historical tracking:\n"
            "  st-stones --set-baseline cross_stones/cross-stones-10.json\n"
            "      Lock the current run timing as the speed baseline.\n"
            "  st-stones --record-snapshot cross_stones/cross-stones-10.json\n"
            "      Save today's scores as a named snapshot.\n"
            "  st-stones --history cross_stones/cross-stones-10.json\n"
            "      Display year-over-year snapshot tables."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths", nargs="*", metavar="path",
        help=(
            "Directory containing benchmark .json/.prompt pairs, "
            "or explicit .json file paths.  "
            "If omitted, ~/cross-stones/ or ./cross_stones/ is used automatically."
        ),
    )
    parser.add_argument(
        "--init", action="store_true",
        help=(
            "Seed the benchmark domain directory with bundled .prompt files "
            "and exit.  Default destination: ~/cross-stones/."
        ),
    )
    parser.add_argument(
        "--dir", metavar="PATH",
        help="Destination directory for --init  (default: ~/cross-stones/)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Run st-cross for any domain that lacks fact-check data",
    )
    parser.add_argument(
        "--confirmation", dest="confirmation", action="store_true", default=True,
        help="Prompt for confirmation before making API calls with --run (default)",
    )
    parser.add_argument(
        "--no-confirmation", dest="confirmation", action="store_false",
        help="Skip the --run confirmation prompt (useful for scripting)",
    )
    parser.add_argument(
        "--w1", type=float, default=DEFAULT_W1,
        help=f"Accuracy weight 0..1  (default {DEFAULT_W1})",
    )
    parser.add_argument(
        "--w2", type=float, default=DEFAULT_W2,
        help=f"Speed weight 0..1  (default {DEFAULT_W2})",
    )
    parser.add_argument(
        "--no-speed", action="store_true",
        help="Ignore timing data; pure accuracy scoring (sets w1=1.0, w2=0.0)",
    )
    parser.add_argument(
        "--n-claims", type=int, default=None,
        help=f"Expected scorable claims per domain prompt  "
             f"(default: value from benchmark set config, or {CLAIMS_PER_DOMAIN})",
    )
    parser.add_argument(
        "--domain", action="store_true",
        help="Show per-domain fact-score breakdown table",
    )
    parser.add_argument(
        "--cache", dest="cache", action="store_true", default=True,
        help="Enable API response cache for --run  (default: enabled)",
    )
    parser.add_argument("--no-cache", dest="cache", action="store_false")
    parser.add_argument(
        "--timeout", type=int, default=300,
        help="Per-job timeout in seconds passed to st-cross --run  "
             "(default: 300 = 5 min).  0 = no timeout.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")

    # ── Historical tracking ────────────────────────────────────────────────────
    hist_group = parser.add_argument_group("historical tracking")
    hist_group.add_argument(
        "--history", action="store_true",
        help=(
            "Display the full snapshot history stored in the benchmark set config "
            "(composite score, speed ratio, and accuracy over time)"
        ),
    )
    hist_group.add_argument(
        "--set-baseline", action="store_true",
        help=(
            "Lock the current run's average timing as the speed baseline in the "
            "benchmark set config.  Run once after the first complete benchmark. "
            "Future runs scoring faster will have speed_ratio > 1.0 and "
            "cross_stone_score may exceed 1.0, showing genuine improvement."
        ),
    )
    hist_group.add_argument(
        "--record-snapshot", action="store_true",
        help=(
            "Append the current leaderboard scores as a named snapshot in the "
            "benchmark set config, building a year-over-year history."
        ),
    )
    hist_group.add_argument(
        "--snapshot-label", type=str, default=None, metavar="LABEL",
        help=(
            "Human-readable label for --record-snapshot  "
            "(default: today's ISO date, e.g. '2026-03-27')"
        ),
    )

    # ── AI content generation ──────────────────────────────────────────────────
    ai_group = parser.add_argument_group("AI content generation")
    ai_group.add_argument(
        "--ai-title", action="store_true",
        help="Generate a ≤10-word leaderboard title → stdout",
    )
    ai_group.add_argument(
        "--ai-short", action="store_true",
        help="Generate a 40-80-word leaderboard summary → stdout",
    )
    ai_group.add_argument(
        "--ai-caption", action="store_true",
        help="Generate a 100-160-word two-paragraph caption → stdout",
    )
    ai_group.add_argument(
        "--ai-summary", action="store_true",
        help="Generate a concise summary (120–200 words) → stdout",
    )
    ai_group.add_argument(
        "--ai-story", action="store_true",
        help="Generate a comprehensive story (800–1200 words) → stdout",
    )
    ai_group.add_argument(
        "--ai", type=str, default=None, metavar="NAME",
        help=f"AI provider to use for content generation  (default: {get_default_ai()})",
    )

    args = parser.parse_args()

    # Load .env (API keys etc.)
    load_cross_env()

    if args.no_speed:
        args.w1, args.w2 = 1.0, 0.0

    # ── --init: seed benchmark domain prompts and exit ─────────────────────────
    if args.init:
        from mmd_util import seed_stones_domains, get_default_stones_dir
        dst = Path(args.dir).expanduser() if args.dir else get_default_stones_dir()
        copied, skipped = seed_stones_domains(dst_dir=dst, overwrite=False, quiet=False)
        if copied == 0 and skipped == 0:
            print("  Bundled domain prompts not found.", file=sys.stderr)
            print("  Run from the repo root or after installing cross-ai.", file=sys.stderr)
            sys.exit(1)
        parts = [f"{copied} prompt(s) seeded to {dst}"]
        if skipped:
            parts.append(f"{skipped} already existed")
        print(f"\n  ✓  {';  '.join(parts)}")
        print()
        print("  Next steps:")
        print(f"    st-cross  {dst}/<domain>.json  # run fact-checks on a domain first")
        print(f"    st-stones {dst}/               # score all domains")
        print(f"    st-domain --dir {dst}/         # create a custom domain")
        sys.exit(0)

    # ── Auto-resolve paths: CWD cross_stones/ → ~/cross-stones/ → first-run ───
    if not args.paths:
        from mmd_util import get_default_stones_dir
        cwd_stones  = Path("cross_stones")
        home_stones = get_default_stones_dir()
        if cwd_stones.is_dir():
            args.paths = [str(cwd_stones)]
        elif home_stones.is_dir():
            args.paths = [str(home_stones)]
        else:
            _stones_first_run()
            sys.exit(0)

    # ── Resolve benchmark set configs in args.paths ────────────────────────────
    # A benchmark set config (e.g. cross-stones-10.json) is expanded to its
    # individual domain paths and its n_claims / max_fact_score are used as
    # defaults (overridable by --n-claims on the CLI).
    set_config:      dict          = {}
    set_config_path: Optional[Path] = None
    resolved_paths:  list          = []
    for p_str in args.paths:
        p = Path(p_str)
        if _is_benchmark_set_config(p):
            if set_config:
                print("Warning: multiple benchmark set configs supplied; "
                      "only the first is used.", file=sys.stderr)
            else:
                domain_paths, set_config = _load_benchmark_set(p)
                set_config_path = p
                resolved_paths.extend(str(dp) for dp in domain_paths)
        else:
            resolved_paths.append(p_str)

    # ── --history: show snapshot history and optionally exit ──────────────────
    if args.history:
        if not set_config:
            print("Error: --history requires a benchmark set config path "
                  "(e.g. cross_stones/cross-stones-10.json)", file=sys.stderr)
            sys.exit(1)
        display_history(set_config)
        # If there are no domain paths to score, exit after showing history
        if not resolved_paths:
            sys.exit(0)

    # ── Extract speed baseline from benchmark set config ──────────────────────
    speed_baseline_s: Optional[float] = None
    baseline_date:    Optional[str]   = None
    if set_config:
        sb = set_config.get("speed_baseline") or {}
        if sb.get("total_seconds"):
            speed_baseline_s = float(sb["total_seconds"])
            baseline_date    = sb.get("recorded_date")

    # Resolve n_claims: CLI flag > benchmark set config > built-in default
    if args.n_claims is not None:
        n_claims = args.n_claims
    elif set_config:
        n_claims = set_config.get("n_claims", CLAIMS_PER_DOMAIN)
    else:
        n_claims = CLAIMS_PER_DOMAIN

    json_files = collect_json_files(resolved_paths if resolved_paths else args.paths)
    if not json_files:
        print("Error: no .json benchmark files found.", file=sys.stderr)
        sys.exit(1)

    # ── Optional: run missing domains ─────────────────────────────────────────
    if args.run:
        # Count domains that actually need work (have a .prompt and are incomplete)
        needs_run = [
            jf for jf in json_files
            if not domain_is_complete(jf) and jf.with_suffix(".prompt").exists()
        ]

        if needs_run and args.confirmation:
            from ai_handler import get_ai_list as _get_ai_list
            n_ai      = len(_get_ai_list())
            n_domains = len(needs_run)
            # Each domain: N generation calls + N² fact-check calls
            n_calls   = n_domains * (n_ai + n_ai * n_ai)
            print()
            print(_clr("  ⚠  Cross-Stones --run will make API calls", BOLD, YELLOW))
            print(f"     Incomplete domains : {n_domains}")
            print(f"     AI providers       : {n_ai}")
            print(f"     Estimated API calls: ~{n_calls}  "
                  f"({n_domains} × ({n_ai} gen + {n_ai}² fact-checks))")
            print( "     This may consume significant API quota.")
            print()
            try:
                answer = input("  Do you wish to continue? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  Cancelled.")
                sys.exit(0)
            if answer not in ("y", "yes"):
                print("  Cancelled.")
                sys.exit(0)

    cache_flag   = "--cache" if args.cache else "--no-cache"
    timeout_flag = ["--timeout", str(args.timeout)]
    for jf in json_files:
        if domain_is_complete(jf):
            if args.verbose:
                print(f"  ✓  Already complete: {jf.name}")
            continue
        prompt = jf.with_suffix(".prompt")
        if not prompt.exists():
            if args.verbose:
                print(f"  —  No prompt file for: {jf.name}  (skipping)")
            continue
        if not args.quiet:
            print(f"\n  Running st-cross for {jf.name} ...")
        proc = None
        try:
            # Use Popen (not subprocess.run) so we keep the process handle and
            # can wait for st-cross to finish its own graceful cleanup if the
            # user presses Ctrl+C while it is running.
            proc = subprocess.Popen(["st-cross", cache_flag, *timeout_flag, str(jf)])
            proc.wait()
            if proc.returncode != 0:
                print(f"  Warning: st-cross exited {proc.returncode} for {jf.name}",
                      file=sys.stderr)
        except KeyboardInterrupt:
            # The terminal sent SIGINT to the whole process group, so st-cross
            # already received it and is saving partial results before exiting.
            # Wait up to 30 s for it to finish, then move on to scoring whatever
            # data has been collected so far.
            if proc is not None:
                try:
                    proc.wait(timeout=30)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    try:
                        proc.terminate()
                    except OSError:
                        pass
            print("\n  Interrupted.  Scoring results collected so far.")
            break

    # ── Load containers ────────────────────────────────────────────────────────
    domain_results: list = []
    domain_names:   list = []
    n_missing = 0

    for jf in json_files:
        if not jf.exists():
            if args.verbose:
                print(f"  Missing: {jf}  (use --run to generate)")
            n_missing += 1
            continue
        try:
            with open(jf) as f:
                container = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  Warning: failed to load {jf}: {e}", file=sys.stderr)
            continue

        scores = compute_domain_scores(container)
        has_facts = any(
            info.get("fact_avg") is not None
            for info in scores.values()
        )
        if not has_facts:
            if args.verbose:
                print(f"  Empty: {jf.name}  (no fact-check data yet)")
            continue

        domain_results.append(scores)
        domain_names.append(jf.stem.replace("_", " ").title())

    if not args.quiet:
        msg = f"  Loaded {len(domain_results)} domain(s)"
        if set_config:
            msg += f"  [{set_config['id']}]"
        if speed_baseline_s:
            msg += f"  [baseline {baseline_date}]"
        if n_missing:
            msg += f"  ({n_missing} missing — use --run to generate)"
        print(msg)

    if not domain_results:
        print("\nNo domains with fact-check results found.")
        print("  • Run  st-cross cross_stones/domains/<domain>.json  for each domain, or")
        print("  • Use  st-stones --run cross_stones/domains/        to run them all.")
        sys.exit(0)

    # ── Compute composite scores ───────────────────────────────────────────────
    final_scores = compute_cross_stone_scores(
        domain_results,
        w1=args.w1,
        w2=args.w2,
        n_claims=n_claims,
        speed_baseline_s=speed_baseline_s,
    )

    # ── Display ────────────────────────────────────────────────────────────────
    if set_config:
        set_label = (f"  Benchmark set: {set_config['id']}  "
                     f"({n_claims} claims/domain, "
                     f"max ±{set_config.get('max_fact_score', n_claims * len(domain_results) * 2)})")
        print(set_label)

    if args.domain:
        display_domain_breakdown(domain_results, domain_names)

    display_leaderboard(
        final_scores,
        w1=args.w1,
        w2=args.w2,
        n_domains=len(domain_results),
        n_claims=n_claims,
        speed_baseline_s=speed_baseline_s,
        baseline_date=baseline_date,
    )

    # ── --set-baseline: record current run timing as the speed baseline ────────
    if args.set_baseline:
        if not set_config_path:
            print("Error: --set-baseline requires a benchmark set config path "
                  "(e.g. cross_stones/cross-stones-10.json)", file=sys.stderr)
        else:
            gen_times = [r["avg_gen_s"] for r in final_scores
                         if r.get("avg_gen_s") is not None]
            fc_times  = [r["avg_fc_s"]  for r in final_scores
                         if r.get("avg_fc_s")  is not None]
            if gen_times or fc_times:
                overall_gen = mean(gen_times) if gen_times else 0.0
                overall_fc  = mean(fc_times)  if fc_times  else 0.0
                set_baseline_in_config(set_config_path, overall_gen, overall_fc)
                # Reload to pick up the new baseline for subsequent display
                with open(set_config_path) as f:
                    set_config = json.load(f)
            else:
                print("  Warning: no timing data available; cannot set baseline.",
                      file=sys.stderr)
                print("  Run st-cross without --no-cache to collect timing data.")

    # ── --record-snapshot: save current scores as a named snapshot ────────────
    if args.record_snapshot:
        if not set_config_path:
            print("Error: --record-snapshot requires a benchmark set config path "
                  "(e.g. cross_stones/cross-stones-10.json)", file=sys.stderr)
        else:
            label = (args.snapshot_label
                     or _today_date.today().isoformat())
            save_snapshot(
                set_config_path,
                final_scores,
                label=label,
                w1=args.w1,
                w2=args.w2,
                n_domains=len(domain_results),
                n_claims=n_claims,
            )

    # ── AI content generation ─────────────────────────────────────────────────
    content_type: Optional[str] = None
    if args.ai_title:     content_type = "title"
    elif args.ai_short:   content_type = "short"
    elif args.ai_caption: content_type = "caption"
    elif args.ai_summary: content_type = "summary"
    elif args.ai_story:   content_type = "story"

    if content_type is not None:
        ai_make = args.ai if args.ai else get_default_ai()
        if not args.quiet:
            print(f"  Generating {content_type} with {ai_make} ...")
        prompt = build_stones_prompt(
            final_scores, args.w1, args.w2,
            len(domain_results), n_claims,
            domain_names, content_type,
            speed_baseline_s=speed_baseline_s,
            baseline_date=baseline_date,
        )
        result  = process_prompt(ai_make, prompt, verbose=False, use_cache=args.cache)
        content = get_content(ai_make, result[2]).strip()
        is_valid, word_count, error_msg = validate_ai_content(content, content_type)
        if not is_valid:
            print(f"  Warning: {error_msg}", file=sys.stderr)
        print(content)


if __name__ == "__main__":
    main()

