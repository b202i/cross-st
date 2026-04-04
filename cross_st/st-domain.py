#!/usr/bin/env python3
"""
st-domain — Create a Cross-Stones benchmark domain prompt

Guides the user through Phases 2-4 from cross_stones/DOMAIN_PROMPT_PROCESS.md:
  Phase 2 — Name and scope the domain
  Phase 3 — AI suggests 5 aspects; full prompt assembled from template
  Phase 4 — Smoke-test: one AI generates the 10 claims; user validates

Usage:
    st-domain                                      # fully interactive
    st-domain --name supply_chain                  # pre-fill slug
    st-domain --dir my_domains/                    # output dir (default: cross_stones/domains/)
    st-domain --ai anthropic                       # AI for suggestions + smoke-test
    st-domain --n-claims 10                        # claims per domain (default: 10)
    st-domain --no-smoketest                       # skip Phase 4 validation
    st-domain --set cross_stones/cross-stones-10.json  # add to a named benchmark set
"""

import argparse
import json
import os
import re
import sys
import textwrap
from datetime import datetime
from mmd_startup import require_config, load_cross_env
from pathlib import Path

# Load .env before importing ai_handler so API keys are available.
load_cross_env()

from ai_handler import get_content, get_default_ai, process_prompt  # noqa: E402

# ── ANSI helpers ──────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
DIM    = "\033[2m"
YELLOW = "\033[33m"
RED    = "\033[31m"


def _clr(text, *codes) -> str:
    return "".join(codes) + str(text) + RESET


def _section(title: str) -> None:
    pad = max(0, 62 - len(title))
    print(f"\n{_clr('── ' + title + ' ', BOLD)}{'─' * pad}")


def _info(msg: str) -> None:
    print(f"  {msg}")


def _ok(msg: str) -> None:
    print(f"  {_clr('✓', GREEN, BOLD)}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {_clr('⚠', YELLOW, BOLD)}  {msg}")


# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_OUTPUT_DIR  = "cross_stones/domains"
DEFAULT_N_CLAIMS    = 10
_CURRENT_YEAR       = datetime.now().year
DEFAULT_YEAR_RANGE  = f"{_CURRENT_YEAR - 1}–{_CURRENT_YEAR}"

# ── Prompt templates ──────────────────────────────────────────────────────────

_ASPECT_SUGGESTION_PROMPT = """\
I am writing a benchmark prompt to evaluate AI models on the domain of {display_name}.
The prompt will ask each AI to generate {n_claims} specific, fact-checkable claims about:
  {topic_description}

Suggest exactly 5 distinct sub-aspects that together give broad, balanced coverage.
The 5 aspects must span these categories IN ORDER:
  1. Adoption / market data — named surveys, reports, market share, investment figures
  2. Performance / quality benchmarks — empirical, named metrics (accuracy, speed, AUC, etc.)
  3. Leading named tools / platforms / named organisations
  4. Regulatory / ethical / policy landscape — verifiable public record
  5. Limitations / failure modes / open problems — honest, critical framing

Each aspect should be completable in 1–2 verifiable, data-rich, fact-checkable claims.

Return exactly 5 lines, one aspect per line.
Each line: a compact description of 15–25 words, written as a prompt bullet point.
No numbers, no bullets, no headers, no introductory text, no commentary.
"""

_DOMAIN_PROMPT_TEMPLATE = """\
# Cross-Stone Benchmark Prompt — {display_name}

Write exactly {n_claims} specific, fact-checkable claims about {topic_description} as of {year_range}.

Each claim must be a clear, declarative statement that a well-informed analyst could verify — using publicly available sources such as {source_types} — as True, Partially True, Opinion, Partially False, or False.

**Difficulty calibration:** Approximately half of the claims should be verifiable with basic research (widely reported statistics or named platforms), and half should require consulting primary sources, empirical studies, or detailed {domain_adjective} data published in {recent_year_range}.

**Claims must not be vague generalizations.** Each claim should include specific data points, named tools or systems, percentages, benchmark scores, or named organizations where relevant.

Distribute your {n_claims} claims across the following aspects:
{aspects_block}
**Format:** Return a numbered list of exactly {n_claims} claims with no introductory text, section headers, summaries, or commentary.
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def _suggest_source_types(topic: str) -> str:
    """Heuristic: return tailored source-type language based on topic keywords."""
    t = topic.lower()
    if any(k in t for k in ("health", "medical", "clinical", "fda", "pharma", "diagnos")):
        return ("peer-reviewed journals, FDA databases, hospital system reports, "
                "or reputable health news outlets")
    if any(k in t for k in ("financ", "bank", "trading", "invest", "credit", "insur")):
        return ("regulatory filings, industry surveys, academic research, "
                "or reputable financial news outlets")
    if any(k in t for k in ("legal", "law", "regulat", "compliance", "polic", "govern")):
        return ("legislative records, regulatory filings, academic papers, "
                "or reputable legal/policy news outlets")
    if any(k in t for k in ("edu", "school", "student", "learn", "teach", "academ")):
        return ("peer-reviewed education research, institutional reports, "
                "or reputable education news outlets")
    # Default: technology / business
    return ("vendor documentation, benchmark leaderboards, academic papers, "
            "or reputable technology news outlets")


def _slug_from_name(name: str) -> str:
    """Convert any text to a snake_case slug suitable for a filename."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug


def _ask(prompt: str, default: str = "") -> str:
    """Print prompt, return user input or default on blank."""
    display = f"  {prompt}"
    if default:
        display += f"  [{_clr(default, DIM)}]"
    display += ": "
    try:
        answer = input(display).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        sys.exit(0)
    return answer if answer else default


def _ask_required(prompt: str) -> str:
    """Ask a question that must not be blank."""
    while True:
        answer = _ask(prompt)
        if answer:
            return answer
        print("  (required — please enter a value)")


def _strip_list_prefix(line: str) -> str:
    """Remove leading numbering or bullets from a line returned by an AI."""
    line = re.sub(r"^\d+[.)]\s*", "", line)   # "1. " or "1) "
    line = re.sub(r"^[-•*]\s*", "", line)      # "- " or "• "
    return line.strip()


# ── Core logic ────────────────────────────────────────────────────────────────

def suggest_aspects(display_name: str, topic_description: str, n_claims: int,
                    ai_make: str, use_cache: bool, verbose: bool) -> list:
    """
    Call the AI with the aspect suggestion prompt and return up to 5 aspect strings.
    Parses one non-empty line per aspect, stripping any list prefix the AI added.
    """
    prompt = _ASPECT_SUGGESTION_PROMPT.format(
        display_name=display_name,
        topic_description=topic_description,
        n_claims=n_claims,
    )
    result   = process_prompt(ai_make, prompt, verbose=verbose, use_cache=use_cache)
    raw_text = get_content(ai_make, result[2]).strip()

    lines   = [_strip_list_prefix(ln) for ln in raw_text.splitlines() if ln.strip()]
    aspects = [ln for ln in lines if ln][:5]
    return aspects


def edit_aspects(aspects: list) -> list:
    """Interactively let the user review and revise each aspect."""
    print()
    edited = []
    for i, aspect in enumerate(aspects, 1):
        print(f"  {_clr(f'Aspect {i}:', BOLD)}")
        print(f"    {aspect}")
        revised = _ask(f"  Edit aspect {i} (Enter to keep)")
        edited.append(revised if revised else aspect)
    return edited


def build_prompt_text(display_name: str, topic_description: str,
                      year_range: str, source_types: str,
                      aspects: list, n_claims: int) -> str:
    """Assemble the complete prompt file text from the template."""
    first_word    = display_name.split()[0].lower() if display_name else "domain"
    domain_adj    = first_word + "-specific"
    # Recent year range is one window behind the claim year range
    recent_range  = f"{_CURRENT_YEAR - 2}–{_CURRENT_YEAR - 1}"
    aspects_block = "\n".join(f"- {a}" for a in aspects) + "\n\n"

    return _DOMAIN_PROMPT_TEMPLATE.format(
        display_name=display_name,
        n_claims=n_claims,
        topic_description=topic_description,
        year_range=year_range,
        source_types=source_types,
        domain_adjective=domain_adj,
        recent_year_range=recent_range,
        aspects_block=aspects_block,
    )


def smoke_test(prompt_text: str, ai_make: str, use_cache: bool, verbose: bool) -> str:
    """Send the assembled prompt to one AI and return the raw claims text."""
    result = process_prompt(ai_make, prompt_text, verbose=verbose, use_cache=use_cache)
    return get_content(ai_make, result[2]).strip()


def _count_numbered_claims(text: str) -> int:
    """Count lines that look like '1.' or '1)' — proxy for claim count."""
    return len(re.findall(r"^\s*\d+[.)]\s+", text, re.MULTILINE))


def _add_to_benchmark_set(set_path: Path, domain_id: str, display_name: str,
                          n_claims: int) -> bool:
    """
    Append a domain entry to a benchmark set config JSON and recompute
    n_domains / max_fact_score.  Returns True if added, False if already present.
    """
    try:
        with open(set_path) as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _warn(f"Could not read benchmark set {set_path}: {e}")
        return False

    domains = config.get("domains", [])
    if any(d.get("id") == domain_id for d in domains):
        return False   # already present — nothing to do

    domains.append({"id": domain_id, "name": display_name})
    config["domains"]       = domains
    config["n_domains"]     = len(domains)
    config["max_fact_score"] = len(domains) * config.get("n_claims", n_claims) * 2

    with open(set_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    return True


# ── CLI / wizard ──────────────────────────────────────────────────────────────

def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog="st-domain",
        description=textwrap.dedent("""\
            Interactive wizard: create a Cross-Stones benchmark domain prompt.
            Follows cross_stones/DOMAIN_PROMPT_PROCESS.md Phases 2–4.
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--name", type=str, default="", metavar="SLUG",
                        help="Domain slug (snake_case, e.g. supply_chain)")
    parser.add_argument("--dir", type=str, default=DEFAULT_OUTPUT_DIR, metavar="DIR",
                        help=f"Output directory  (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--ai", type=str, default=None, metavar="NAME",
                        help="AI provider for suggestions + smoke-test  "
                             f"(default: {get_default_ai()})")
    parser.add_argument("--n-claims", type=int, default=DEFAULT_N_CLAIMS,
                        help=f"Claims per domain  (default: {DEFAULT_N_CLAIMS})")
    parser.add_argument("--no-smoketest", action="store_true",
                        help="Skip Phase 4 validation smoke-test")
    parser.add_argument("--set", type=str, default="", metavar="CONFIG.JSON",
                        help="Benchmark set config to register the new domain in after saving")
    parser.add_argument("--cache", dest="cache", action="store_true", default=True,
                        help="Enable AI response cache (default: on)")
    parser.add_argument("--no-cache", dest="cache", action="store_false",
                        help="Disable AI response cache")
    parser.add_argument("-v", "--verbose", action="store_true")

    args    = parser.parse_args()
    ai_make = args.ai or get_default_ai()

    print()
    print(_clr("══ Cross-Stones Domain Creator ════════════════════════════════════", BOLD, CYAN))
    print(_clr(f"   st-domain  ·  DOMAIN_PROMPT_PROCESS.md Phases 2–4  ·  AI: {ai_make}", DIM))

    # ── Phase 2: Define the domain ─────────────────────────────────────────────
    _section("Phase 2  —  Define the domain")

    raw_slug     = args.name or _ask_required("Domain slug  (e.g. supply_chain)")
    slug         = _slug_from_name(raw_slug)
    display_name = _ask_required("Display name  (e.g. Supply Chain & Logistics)")
    topic_desc   = _ask_required(
        "Topic description for claims\n  "
        "  (e.g. AI in supply chain management, logistics, and demand forecasting)"
    )
    year_range   = _ask("Year range", default=DEFAULT_YEAR_RANGE)
    source_suggested = _suggest_source_types(topic_desc)
    source_types = _ask("Source types for verification", default=source_suggested)

    # ── Phase 3a: AI suggests 5 aspects ───────────────────────────────────────
    _section("Phase 3  —  AI-suggested aspects")
    _info(f"Asking {_clr(ai_make, BOLD)} for aspect suggestions …")

    try:
        aspects = suggest_aspects(
            display_name, topic_desc, args.n_claims,
            ai_make, args.cache, args.verbose,
        )
    except Exception as e:
        print(f"\n  {_clr('Error', RED, BOLD)} calling AI ({ai_make}): {e}", file=sys.stderr)
        sys.exit(1)

    if len(aspects) < 5:
        _warn(f"AI returned {len(aspects)} aspects (expected 5).  "
              "You can fill in the rest in the edit step.")
        while len(aspects) < 5:
            aspects.append("")

    print()
    for i, a in enumerate(aspects, 1):
        label = _clr(f"{i}.", BOLD)
        print(f"  {label}  {a}")

    choice = _ask(
        "\n  Accept all 5 aspects?  [Y / n / e to edit each]",
        default="y"
    ).lower()
    if choice.startswith(("n", "e")):
        aspects = edit_aspects(aspects)

    # ── Phase 3b: Assemble and preview the prompt ──────────────────────────────
    _section("Phase 3  —  Assembled prompt  (preview)")
    prompt_text = build_prompt_text(
        display_name, topic_desc, year_range, source_types, aspects, args.n_claims
    )
    print()
    print("  " + "─" * 66)
    for line in prompt_text.splitlines():
        print(f"  {line}")
    print("  " + "─" * 66)

    # ── Save ───────────────────────────────────────────────────────────────────
    out_dir  = Path(args.dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}.prompt"

    if out_path.exists():
        overwrite = _ask(
            f"\n  {_clr(str(out_path), BOLD)} already exists.  Overwrite?  [y/N]",
            default="n"
        ).lower()
        if not overwrite.startswith("y"):
            _info("Aborted — existing file not overwritten.")
            sys.exit(0)

    save_choice = _ask(
        f"\n  Save to {_clr(str(out_path), BOLD)}?  [Y/n]",
        default="y"
    ).lower()
    if not save_choice.startswith("y"):
        _info("Prompt not saved.")
        sys.exit(0)

    out_path.write_text(prompt_text)
    _ok(f"Saved: {out_path}")

    # ── Phase 4: Smoke-test ────────────────────────────────────────────────────
    if not args.no_smoketest:
        _section("Phase 4  —  Smoke-test")
        _info(f"Sending prompt to {_clr(ai_make, BOLD)} — "
              f"expecting {args.n_claims} numbered claims …")

        claims_text = ""
        try:
            claims_text = smoke_test(prompt_text, ai_make, args.cache, args.verbose)
        except Exception as e:
            _warn(f"Smoke-test call failed: {e}")

        if claims_text:
            print()
            for line in claims_text.splitlines():
                print(f"  {line}")
            print()

            n_found = _count_numbered_claims(claims_text)
            if n_found == args.n_claims:
                _ok(f"Exactly {n_found} claims returned — format correct.")
            else:
                _warn(f"Expected {args.n_claims} claims, got {n_found}.  "
                      "Consider tightening the Format instruction.")

            smoke_choice = _ask(
                "  Accept smoke-test?  [Y / n / r to retry without cache]",
                default="y"
            ).lower()

            if smoke_choice.startswith("r"):
                _info("Retrying without cache …")
                try:
                    claims_text = smoke_test(
                        prompt_text, ai_make, use_cache=False, verbose=args.verbose
                    )
                    print()
                    for line in claims_text.splitlines():
                        print(f"  {line}")
                    n_found = _count_numbered_claims(claims_text)
                    if n_found == args.n_claims:
                        _ok(f"Retry: exactly {n_found} claims returned.")
                    else:
                        _warn(f"Retry: expected {args.n_claims}, got {n_found}.")
                except Exception as e:
                    _warn(f"Retry failed: {e}")
        else:
            _warn("No text returned from smoke-test — check AI connectivity.")

        _info(
            "Phase 4 checklist (review manually):\n"
            "    □  Exactly 10 numbered items, nothing else\n"
            "    □  Each is a declarative statement, not a question or heading\n"
            "    □  Each contains at least one named entity, statistic, or date\n"
            "    □  A well-informed analyst could verify it with reasonable effort\n"
            "    □  Mix of easy-to-verify and primary-source-required claims"
        )

    # ── Optional: add to benchmark set ────────────────────────────────────────
    if args.set:
        set_path = Path(args.set)
        if set_path.exists():
            added = _add_to_benchmark_set(set_path, slug, display_name, args.n_claims)
            if added:
                _ok(f"Registered '{display_name}' in benchmark set: {set_path}")
            else:
                _info(f"'{slug}' is already listed in benchmark set: {set_path}")
        else:
            _warn(f"Benchmark set config not found: {set_path}  (domain not registered)")

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    _ok(f"Domain prompt ready: {out_path}")
    _info("Next steps:")
    _info(f"  st-cross {out_dir}/{slug}.json          # run the N×N benchmark")
    _info(f"  st-stones {out_dir}/                    # score all domains in that dir")
    if args.set:
        _info(f"  st-stones {args.set}                   # score the named benchmark set")
    print()


if __name__ == "__main__":
    main()

