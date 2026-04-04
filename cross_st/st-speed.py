#!/usr/bin/env python3
"""
st-speed — Analyze AI provider performance and speed
Symlinked as st-speed for command-line use

Analyzes timing data from Cross containers to compare AI speed, throughput,
and consistency. Provides apples-to-apples performance comparisons.

Usage:
    st-speed report.json                    # Basic performance summary
    st-speed --ai gemini report.json        # Filter by specific AI
    st-speed --history crypto/*.json        # Analyze trends across files
    st-speed --csv report.json              # Export to CSV
"""

import argparse
import json
import os
import sys
import time
from mmd_startup import load_cross_env, require_config
from pathlib import Path
from statistics import mean, median, stdev
from tabulate import tabulate

# Import AI handler for caption generation
from ai_handler import process_prompt, get_content, get_default_ai


def load_container(file_path):
    """Load a JSON container file."""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error loading {file_path}: {e}")
        return None


def extract_generation_timing(container):
    """
    Extract timing data from story generation (data entries).
    
    Returns: list of dicts with keys: ai, model, elapsed, tokens_total, tok_per_sec, cached
    """
    results = []
    for entry in container.get("data", []):
        if "timing" not in entry:
            continue
        
        timing = entry["timing"]
        results.append({
            "ai": entry.get("make", "unknown"),
            "model": entry.get("model", "unknown"),
            "elapsed_seconds": timing.get("elapsed_seconds", 0),
            "tokens_input": timing.get("tokens_input", 0),
            "tokens_output": timing.get("tokens_output", 0),
            "tokens_total": timing.get("tokens_total", 0),
            "tokens_per_second": timing.get("tokens_per_second", 0),
            "cached": timing.get("cached", False),
        })
    
    return results


def extract_fact_check_timing(container):
    """
    Extract timing data from fact-checks.
    
    Each fact-check involves 20-50+ individual AI calls (one per paragraph segment).
    
    elapsed_seconds returned here is the *best available* metric:
      • If the timing dict contains elapsed_fresh_seconds and n_fresh > 0,
        we extrapolate to a full-run equivalent:
            elapsed_fresh_seconds / n_fresh * n_total
        This gives an apples-to-apples figure even for partially-cached runs
        (where a naive elapsed_seconds would be deflated by near-instant cache hits).
      • Otherwise we fall back to the raw elapsed_seconds (old-format containers
        or fully-fresh runs where both values are identical).
    
    Returns: list of dicts with keys: ai, model, story_index, elapsed_seconds,
             tokens_total, tok_per_sec, cached, segments, n_fresh, n_total
    """
    results = []
    for story_idx, story in enumerate(container.get("story", []), start=1):
        # Get segment count for this story (number of AI calls per fact-check)
        num_segments = len(story.get("segments", []))
        
        for fact in story.get("fact", []):
            if "timing" not in fact:
                continue
            
            timing = fact["timing"]

            # ── Elapsed: prefer fresh-extrapolated over raw wall-clock ──────
            n_fresh       = timing.get("n_fresh")
            n_total_segs  = timing.get("n_total") or num_segments or 1
            elapsed_fresh = timing.get("elapsed_fresh_seconds", 0)
            elapsed_total = timing.get("elapsed_seconds", 0)

            if n_fresh and n_fresh > 0 and elapsed_fresh > 0:
                # Extrapolate: estimate what a fully-fresh run would take.
                # Works for both fully-fresh (n_fresh==n_total → no change)
                # and partially-cached (scales fresh avg × total segments).
                elapsed_best = elapsed_fresh / n_fresh * n_total_segs
            else:
                # Old-format container or fully cached (excluded below anyway)
                elapsed_best = elapsed_total

            results.append({
                "ai":               fact.get("make", "unknown"),
                "model":            fact.get("model", "unknown"),
                "story_index":      story_idx,
                "target_ai":        story.get("make", "unknown"),
                "elapsed_seconds":  elapsed_best,
                "tokens_input":     timing.get("tokens_input", 0),
                "tokens_output":    timing.get("tokens_output", 0),
                "tokens_total":     timing.get("tokens_total", 0),
                "tokens_per_second": timing.get("tokens_per_second", 0),
                "cached":           timing.get("cached", False),
                "score":            fact.get("score", 0),
                "segments":         num_segments,  # Number of AI calls in this fact-check
                "n_fresh":          n_fresh,        # None for old-format containers
                "n_total":          n_total_segs,
            })
    
    return results


def format_time(seconds):
    """Format seconds as mm:ss."""
    if seconds < 0:
        return "--:--"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"


def summarize_generation(timing_data, ai_filter=None):
    """Summarize story generation performance."""
    if not timing_data:
        return None
    
    # Filter by AI if requested
    if ai_filter:
        timing_data = [t for t in timing_data if t["ai"] == ai_filter]
        if not timing_data:
            return None
    
    # Group by AI
    by_ai = {}
    for entry in timing_data:
        ai = entry["ai"]
        if ai not in by_ai:
            by_ai[ai] = []
        by_ai[ai].append(entry)
    
    # Build summary table
    rows = []
    cached_rows = []   # held separately so they sort after fresh rows
    for ai, entries in sorted(by_ai.items()):
        # Exclude cached entries from performance metrics
        fresh_entries = [e for e in entries if not e["cached"]]
        if fresh_entries:
            avg_time = mean(e["elapsed_seconds"] for e in fresh_entries)
            avg_tokens = mean(e["tokens_total"] for e in fresh_entries)
            avg_tok_per_sec = mean(e["tokens_per_second"] for e in fresh_entries)
            rows.append({
                "AI": ai,
                "Time": format_time(avg_time),
                "Tokens": int(avg_tokens),
                "Tok/s": f"{avg_tok_per_sec:.2f}",
                "Samples": len(fresh_entries),
                "_cached_only": False,
            })
        else:
            # All entries were cache hits — still show the row so users aren't
            # confused by a provider being silently absent from the table.
            cached_entries = [e for e in entries if e["cached"]]
            if cached_entries:
                avg_tokens = mean(e["tokens_total"] for e in cached_entries)
                cached_rows.append({
                    "AI": ai,
                    "Time": "(cache)",
                    "Tokens": int(avg_tokens),
                    "Tok/s": "—",
                    "Samples": len(cached_entries),
                    "_cached_only": True,
                })

    # Sort fresh rows by time (fastest first); cached rows go at the end
    rows.sort(key=lambda r: int(r["Time"].split(':')[0]) * 60 + int(r["Time"].split(':')[1]))
    rows.extend(cached_rows)

    # Strip internal marker before returning
    for r in rows:
        r.pop("_cached_only", None)

    
    return rows


def summarize_fact_checks(timing_data, ai_filter=None):
    """Summarize fact-check performance."""
    if not timing_data:
        return None
    
    # Filter by AI if requested
    if ai_filter:
        timing_data = [t for t in timing_data if t["ai"] == ai_filter]
        if not timing_data:
            return None
    
    # Group by AI
    by_ai = {}
    for entry in timing_data:
        ai = entry["ai"]
        if ai not in by_ai:
            by_ai[ai] = []
        by_ai[ai].append(entry)
    
    # Build summary table
    rows = []
    for ai, entries in sorted(by_ai.items()):
        # Exclude cached entries
        fresh_entries = [e for e in entries if not e["cached"]]
        if not fresh_entries:
            continue
        
        times = [e["elapsed_seconds"] for e in fresh_entries]
        avg_time = mean(times)
        med_time = median(times)
        min_time = min(times)
        max_time = max(times)
        std_time = stdev(times) if len(times) > 1 else 0
        
        # Calculate total segments (AI calls) across all samples
        total_segments = sum(e.get("segments", 0) for e in fresh_entries)
        avg_segments = int(total_segments / len(fresh_entries)) if fresh_entries else 0
        
        rows.append({
            "AI": ai,
            "Avg": format_time(avg_time),
            "Median": format_time(med_time),
            "Min": format_time(min_time),
            "Max": format_time(max_time),
            "StdDev": f"{std_time:.1f}s",
            "Samples": len(fresh_entries),
            "Segments": f"{avg_segments}/job" if avg_segments > 0 else "?",
        })
    
    # Sort by average time
    rows.sort(key=lambda r: int(r["Avg"].split(':')[0]) * 60 + int(r["Avg"].split(':')[1]))
    
    return rows


def format_data_for_prompt(summary_rows):
    """Format summary data as text table for AI prompt."""
    if not summary_rows:
        return "No data available"
    return tabulate(summary_rows, headers="keys", tablefmt="simple")


def build_ai_prompt(gen_summary, fact_summary, content_type="caption"):
    """
    Build prompt for AI to generate performance analysis content.
    
    Args:
        gen_summary: List of dicts with generation performance
        fact_summary: List of dicts with fact-check performance
        content_type: One of: title, short, caption, summary, story
    
    Returns:
        str: Prompt for AI
    """
    # Data section (common to all prompts)
    data_parts = []
    if gen_summary:
        data_parts.extend([
            "STORY GENERATION PERFORMANCE:",
            format_data_for_prompt(gen_summary),
            ""
        ])
    
    if fact_summary:
        data_parts.extend([
            "FACT-CHECKING PERFORMANCE:",
            format_data_for_prompt(fact_summary),
            ""
        ])
    
    data_section = "\n".join(data_parts)
    
    # Content-specific prompts
    if content_type == "title":
        return f"""Write a SHORT, punchy title about this AI performance data.

{data_section}

AUDIENCE: General tech readers (browsing headlines)

LENGTH: Maximum 10 words (strict limit)

NUMBER RULES:
• Use 0-2 WHOLE numbers only
• Round: "8x faster" not "7.8x faster"
• Simple comparisons: "3x", "twice as fast", "8x faster"

CONTENT RULES:
• Capture the key finding or comparison
• Mention AI names when relevant
• No articles (a, an, the) unless absolutely necessary
• Punchy and specific

EXAMPLES:

GOOD: "OpenAI Dominates Speed, 8x Faster Than Anthropic"
GOOD: "Perplexity Delivers Fastest, Most Consistent Performance"
GOOD: "Speed Race: OpenAI Leads, Anthropic Lags"

BAD: "Analysis of AI Performance Data Across Providers"
BAD: "OpenAI Achieves 34.2 Second Average Completion Time"

Format: Plain text, single line, no quotes or markdown."""

    elif content_type == "short":
        return f"""Write a SHORT caption about this AI performance data.

{data_section}

AUDIENCE: General technical readers (12th grade+ / college level)

⚠️ CRITICAL: The table shows ALL the numbers. Your job is to INTERPRET, not repeat.

LENGTH: Maximum 80 words (strict)

NUMBER RULES:
• Use 2-3 WHOLE numbers maximum (no decimals!)
• Write naturally: "30 seconds", "under a minute", "around 2 minutes"
• NEVER write: "34.2s", "28.4s StdDev", "avg 49s"
• Qualitative is fine: "much faster", "very consistent", "wildly variable"

CONTENT RULES:
• ONE paragraph only
• Conversational tone
• Tell the story: Who wins? Who's reliable? What should I use?
• Focus on practical takeaway

EXAMPLES:

GOOD: "OpenAI handles most tasks in under a minute, making it the clear winner. Anthropic takes 4-5 minutes and varies wildly. For predictable performance, stick with OpenAI or Perplexity."

BAD: "OpenAI: 34s avg, 35s median, StdDev 28.4s. Perplexity: 49s avg, 51s median, StdDev 25.4s..."

Format: Plain text, single paragraph, conversational."""

    elif content_type == "caption":
        return f"""Write a detailed caption about this AI performance data.

{data_section}

AUDIENCE: Technical readers (12th grade+ / college level) - understand computing but not AI specialists

⚠️ CRITICAL: The table shows ALL detailed numbers. Your job is to INTERPRET the story.

LENGTH: 100-160 words (strict range)

NUMBER RULES:
• Use 4-6 WHOLE numbers maximum across BOTH paragraphs
• Round everything: "30 seconds" not "34.2 seconds"
• Natural phrasing: "under a minute", "around 2 minutes", "5-6 minutes"
• Comparisons OK: "3x faster", "twice as long"
• NEVER write: "34s avg", "28.4s StdDev", "median 35s", "range 3-64s"

STRUCTURE:
• Paragraph 1: Speed story (who wins, rough comparisons, 2-3 numbers)
• Paragraph 2: Hidden insight (consistency, surprises, practical advice, 2-3 numbers)

EXAMPLES:

GOOD: "OpenAI dominates the speed race, typically finishing in well under a minute. Anthropic lags considerably, often taking 5 minutes or more. But raw speed masks an important pattern - OpenAI and Perplexity deliver predictable, consistent performance, while Anthropic swings wildly from fast to extremely slow, making it risky for production use."

BAD: "OpenAI leads with 34s average completion time (median 35s, range 3-64s, StdDev 28.4s). Perplexity: 49s average, 51s median, range 10-78s, StdDev 25.4s..."

Format: Plain text, 2 paragraphs, professional but readable."""

    elif content_type == "summary":
        return f"""Write a technical summary about this AI performance data.

{data_section}

AUDIENCE: Technical/engineering readers (college level) making infrastructure decisions

⚠️ CRITICAL: The table has ALL the statistics. Your summary INTERPRETS and ADVISES.

LENGTH: 120-200 words (strict range)

NUMBER RULES:
• Use 6-10 WHOLE numbers maximum (be selective!)
• Round everything: "30 seconds" not "34 seconds", "2 minutes" not "1:47"
• Natural phrasing: "under a minute", "around 5 minutes", "varies by 3-4x"
• Ranges OK: "30-60 seconds", "2-6 minutes"
• NEVER write: "avg 34s (median 35s, StdDev 28.4s)"

STRUCTURE:
• Paragraph 1: Speed patterns (who's fast, who's slow, why it matters, 3-4 numbers)
• Paragraph 2: Consistency patterns (variance, reliability, predictability, 2-3 numbers)
• Paragraph 3: Practical recommendations (which AI for what use case, 1-2 numbers)

EXAMPLES:

GOOD: "OpenAI completes most fact-checks in well under a minute, establishing itself as the speed leader. Anthropic takes around 5 minutes on average. The hidden story is consistency - OpenAI and Perplexity deliver predictable performance you can build upon, while Anthropic's high variance means tasks might finish in 15 seconds or take 9 minutes, making capacity planning difficult."

BAD: "Performance analysis shows OpenAI: 34s average, 35s median, 3-64s range, 28.4s StdDev, 5 samples, 19 segments/job. Perplexity: 49s average..."

Format: Plain text, 2-3 paragraphs, technical but readable."""

    elif content_type == "story":
        return f"""You are a technical AI investigator writing for a national publication.

{data_section}

AUDIENCE: Technical readers who value clarity and brevity (engineering teams, tech leads)

⚠️ CRITICAL INSTRUCTIONS:
• Include a punchy title (10 words max)
• Make your point and be CONCISE
• AVOID REPETITION - say it once, say it well
• Bring the story to a strong close
• The data is the data - be ACCURATE, be BRIEF, stay on point

LENGTH: 800-1200 words (strict range) - USE EVERY WORD WISELY

NUMBER RULES:
• Use 12-15 WHOLE numbers maximum (be selective!)
• Round everything: "30 seconds" not "34.2 seconds"
• Natural integration: "OpenAI wraps up in under a minute"
• Comparisons: "3x faster" not "3.2x faster"
• NEVER repeat numbers - each data point mentioned ONCE only

WRITING RULES:
• NO repetition - if you've made a point, move on
• NO filler phrases like "let's dive in", "here's the thing", "the verdict is"
• NO dramatic language - stay professional and direct
• NO rehashing - each paragraph adds NEW insight
• Strong conclusion - clear takeaway, no summary of what you just said

STRUCTURE:
1. Title (10 words max, punchy, technical)
2. Why this matters (100-150 words) - set context, no fluff
3. Speed findings (300-400 words) - who's fast, who's slow, patterns, reasons
4. Consistency & tradeoffs (300-400 words) - variance, reliability, architectural choices
5. Bottom line (100-150 words) - clear recommendations, strong close

GOOD EXAMPLE (concise, no repetition):
"Perplexity completes story generation in 15 seconds, 3x faster than Anthropic's 50 seconds. This gap reflects architectural choices: Perplexity's lean inference versus Anthropic's safety-heavy approach."

BAD EXAMPLE (repetitive, verbose):
"Perplexity is the fastest at story generation, completing tasks in just 15 seconds. This makes Perplexity much faster than competitors. In fact, Perplexity's speed—around 15 seconds—is roughly 3 times faster than Anthropic, which takes about 50 seconds..."

Format: Plain text with clear paragraph breaks, blog-post style, no markdown headers."""

    else:
        raise ValueError(f"Unknown content_type: {content_type}")


def validate_ai_content(content, content_type="caption"):
    """
    Validate that AI-generated content meets quality requirements.
    
    Args:
        content: Generated content text
        content_type: One of: title, short, caption, summary, story
    
    Returns:
        tuple: (is_valid, word_count, error_message)
    """
    if not content:
        return False, 0, "Empty content"
    
    content = content.strip()
    word_count = len(content.split())
    
    # Word count requirements by content type
    requirements = {
        "title": (1, 10, "title"),
        "short": (1, 80, "short caption"),
        "caption": (100, 160, "detailed caption"),
        "summary": (120, 200, "summary"),
        "story": (800, 1200, "story"),
    }
    
    if content_type not in requirements:
        return False, word_count, f"Unknown content_type: {content_type}"
    
    min_words, max_words, label = requirements[content_type]
    
    # Check word count
    if word_count < min_words:
        return False, word_count, f"{label} too short ({word_count} words, need {min_words}+)"
    
    if word_count > max_words:
        return False, word_count, f"{label} too long ({word_count} words, max {max_words})"
    
    # Additional validation for data-driven content (not titles)
    # For short captions, allow minimal numbers (since we emphasize readability)
    if content_type == "short":
        # Short captions can be valid with just AI names and qualitative comparisons
        # Don't require numbers for short content
        pass
    elif content_type != "title":
        # Other types should still reference some data
        if not any(char.isdigit() for char in content):
            return False, word_count, f"{label} lacks data (no numbers found)"
    
    return True, word_count, None


def generate_ai_content(gen_summary, fact_summary, ai_make, content_type="caption", verbose=False, use_cache=True):
    """
    Generate AI-written content for performance data.
    
    Args:
        gen_summary: List of dicts (generation performance)
        fact_summary: List of dicts (fact-check performance)
        ai_make: AI provider to use for content generation
        content_type: One of: title, short, caption, summary, story
        verbose: If True, show debugging output
        use_cache: If True, use cached responses when available
    
    Returns:
        str: AI-generated content, or empty string if failed
    """
    if not gen_summary and not fact_summary:
        return ""
    
    try:
        # Build prompt with performance data
        prompt = build_ai_prompt(gen_summary, fact_summary, content_type)
        
        if verbose:
            print(f"  Calling {ai_make} to generate {content_type}...")
            print(f"  Prompt length: {len(prompt)} chars")
            print(f"  Cache: {'enabled' if use_cache else 'disabled'}")
        
        # Call AI to generate content (uses existing ai_handler framework)
        result = process_prompt(ai_make, prompt, verbose=False, use_cache=use_cache)
        gen_payload, client, response, ai_model = result
        
        # Extract content text
        content = get_content(ai_make, response)
        content = content.strip()
        
        # Validate content quality
        is_valid, word_count, error_msg = validate_ai_content(content, content_type)
        
        if verbose:
            print(f"  Generated {word_count} words")
            if content_type != "story":
                print(f"  Preview: {content[:100]}...")
        
        if not is_valid:
            print(f"  Warning: {error_msg}")
            if verbose:
                print(f"  Full content:\n{content}")
            # Return content anyway - let user decide
        
        return content
        
    except Exception as e:
        # Let the error propagate naturally from ai_handler
        print(f"  Content generation failed: {e}")
        print(f"  Hint: Try --ai gemini or --ai anthropic")
        if verbose:
            import traceback
            print(f"  Traceback:")
            traceback.print_exc()
        return ""


def save_story_to_container(container, file_path, story_text, ai_make, ai_model, gen_summary, fact_summary):
    """
    Save AI-generated story as a new entry in the JSON container.
    
    Args:
        container: JSON container dict
        file_path: Path to container file
        story_text: Generated story content
        ai_make: AI provider used
        ai_model: AI model used
        gen_summary: Generation performance summary (for metadata)
        fact_summary: Fact-check performance summary (for metadata)
    
    Returns:
        int: Story index, or -1 if failed
    """
    import time
    
    try:
        # Create story entry with Cross-compatible structure
        story_entry = {
            "make": ai_make,
            "model": ai_model,
            "title": f"Performance Analysis: {Path(file_path).stem}",
            "markdown": story_text,  # Cross uses "markdown" not "story"
            "text": story_text,  # Also include as plain text
            "timestamp": time.time(),
            "segments": [],  # Empty for now - not segmented
            "metadata": {
                "content_type": "ai_story",
                "generated_by": "st-speed",
                "data_summary": {
                    "generation_ais": [row["AI"] for row in gen_summary] if gen_summary else [],
                    "fact_check_ais": [row["AI"] for row in fact_summary] if fact_summary else [],
                }
            }
        }
        
        # Add to container
        if "story" not in container:
            container["story"] = []
        
        container["story"].append(story_entry)
        story_index = len(container["story"])
        
        # Save container
        with open(file_path, 'w') as f:
            json.dump(container, f, indent=2)
        
        return story_index
        
    except Exception as e:
        print(f"  Error saving story to container: {e}")
        return -1


def export_to_csv(gen_data, fact_data, output_path):
    """Export timing data to CSV format."""
    import csv
    
    with open(output_path, 'w', newline='') as csvfile:
        # Generation data
        if gen_data:
            writer = csv.DictWriter(csvfile, fieldnames=gen_data[0].keys())
            csvfile.write("# GENERATION TIMING\n")
            writer.writeheader()
            writer.writerows(gen_data)
            csvfile.write("\n")
        
        # Fact-check data
        if fact_data:
            writer = csv.DictWriter(csvfile, fieldnames=fact_data[0].keys())
            csvfile.write("# FACT-CHECK TIMING\n")
            writer.writeheader()
            writer.writerows(fact_data)


# ── Backward-compatible aliases (original simple two-mode API) ─────────────


def build_caption_prompt(gen_summary, fact_summary, short_caption=False):
    """
    Build an AI prompt for performance caption generation.

    Backward-compatible wrapper around build_ai_prompt().
    Maps the simple short_caption bool to a content_type string.

    Args:
        gen_summary: List of dicts (generation performance) or None
        fact_summary: List of dicts (fact-check performance) or None
        short_caption: If True, request a short one-paragraph caption;
                       if False, request a detailed two-paragraph caption.

    Returns:
        str: Prompt ready to send to an AI provider.
    """
    content_type = "short" if short_caption else "caption"
    return build_ai_prompt(gen_summary, fact_summary, content_type)


def validate_caption(content, short_caption=False):
    """
    Validate that an AI-generated caption meets quality requirements.

    Backward-compatible wrapper with simpler word-count semantics than
    validate_ai_content():
        short  → 40–75 words
        standard → 50+ words AND must contain at least one number

    Args:
        content: Caption text to validate.
        short_caption: If True, apply short-caption limits.

    Returns:
        bool: True if the caption meets requirements.
    """
    if not content:
        return False

    content = content.strip()
    word_count = len(content.split())

    if short_caption:
        return 40 <= word_count <= 75
    else:
        if word_count < 50:
            return False
        return any(ch.isdigit() for ch in content)


def generate_performance_caption(gen_summary, fact_summary, ai_make,
                                 short_caption=False, verbose=False, use_cache=True):
    """
    Generate an AI-written performance caption.

    Backward-compatible wrapper around generate_ai_content().

    Args:
        gen_summary: List of dicts (generation performance)
        fact_summary: List of dicts (fact-check performance)
        ai_make: AI provider to use for generation
        short_caption: If True, generate a short one-paragraph caption
        verbose: If True, show debugging output
        use_cache: If True, allow cached API responses

    Returns:
        str: AI-generated caption, or empty string on failure.
    """
    content_type = "short" if short_caption else "caption"
    return generate_ai_content(gen_summary, fact_summary, ai_make,
                               content_type, verbose, use_cache)


# ─────────────────────────────────────────────────────────────────────────────


def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-speed',
        description='Analyze AI performance and speed from timing data',
        epilog='AI Content Options: Generate analysis in various formats (--ai-title, --ai-short, --ai-caption, --ai-summary, --ai-story)')
    parser.add_argument('json_file', type=str, nargs='+',
                        help='Path to JSON file(s)', metavar='file.json')
    parser.add_argument('--ai', type=str, default=None,
                        help='AI to use for content generation (default: xai); also filters performance data')
    
    # AI Content Generation Options (Standardized Framework)
    ai_group = parser.add_argument_group('AI Content Generation')
    ai_group.add_argument('--ai-title', action='store_true',
                        help='Generate short title (max 10 words) → stdout')
    ai_group.add_argument('--ai-short', action='store_true',
                        help='Generate short caption (max 80 words) → stdout')
    ai_group.add_argument('--ai-caption', action='store_true',
                        help='Generate detailed caption (100-160 words) → stdout')
    ai_group.add_argument('--ai-summary', action='store_true',
                        help='Generate concise summary (120-200 words) → stdout')
    ai_group.add_argument('--ai-story', action='store_true',
                        help='Generate comprehensive story (800-1200 words) → new story in JSON')
    
    # Other options
    parser.add_argument('--csv', type=str, default=None,
                        help='Export raw data to CSV file')
    parser.add_argument('--history', action='store_true',
                        help='Analyze trends across multiple files')
    parser.add_argument('--cache', action='store_true', default=False,
                        help='Enable API response caching (default for AI content generation)')
    parser.add_argument('--no-cache', action='store_true', default=False,
                        help='Disable API response caching (forces fresh AI calls)')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Minimal output')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output (show generation details)')
    
    args = parser.parse_args()
    
    # Handle cache flags (--no-cache overrides --cache, default is cache enabled for AI content)
    use_cache = not args.no_cache
    
    # Determine which content type to generate
    content_types = []
    if args.ai_title:
        content_types.append("title")
    if args.ai_short:
        content_types.append("short")
    if args.ai_caption:
        content_types.append("caption")
    if args.ai_summary:
        content_types.append("summary")
    if args.ai_story:
        content_types.append("story")
    
    # Validate: only one AI content type at a time
    if len(content_types) > 1:
        print(f"Error: Cannot use multiple AI content options simultaneously")
        print(f"       Choose one: --ai-title, --ai-short, --ai-caption, --ai-summary, --ai-story")
        sys.exit(1)
    
    # Get AI for content generation
    content_ai = args.ai if args.ai else get_default_ai()
    
    # Load .env file for API keys (same as st-gen, st-fact, etc.)
    load_cross_env()
    
    # Load container(s)
    containers = []
    for file_path in args.json_file:
        container = load_container(file_path)
        if container:
            containers.append((file_path, container))
    
    if not containers:
        print("Error: No valid containers loaded")
        sys.exit(1)
    
    # Process each container
    all_gen_data = []
    all_fact_data = []
    
    for file_path, container in containers:
        gen_data = extract_generation_timing(container)
        fact_data = extract_fact_check_timing(container)
        
        all_gen_data.extend(gen_data)
        all_fact_data.extend(fact_data)
        
        # Single file summary
        if len(containers) == 1 and not args.quiet:
            print(f"\nPerformance Summary: {Path(file_path).name}\n")
            print("=" * 70)
            
            # Generation summary (filtered for display)
            gen_summary_display = summarize_generation(gen_data, args.ai)
            if gen_summary_display:
                print("\nStory Generation:")
                print(tabulate(gen_summary_display, headers="keys", tablefmt="simple"))
            else:
                print("\nStory Generation: No timing data found")
            
            # Fact-check summary (filtered for display)
            fact_summary_display = summarize_fact_checks(fact_data, args.ai)
            if fact_summary_display:
                print("\nFact-Checking Performance:")
                print(tabulate(fact_summary_display, headers="keys", tablefmt="simple"))
                print("\nNote: Each sample is one complete fact-check job.")
                print("      'Segments' shows avg AI calls per job (typically 20-50 paragraphs).")
            else:
                print("\nFact-Checking Performance: No timing data found")
            
            # Generate AI content if requested
            if content_types:
                content_type = content_types[0]
                
                # For AI analysis, use UNFILTERED data (full comparison context)
                # This allows AI to make meaningful comparisons even when display is filtered
                gen_summary_ai = summarize_generation(gen_data, ai_filter=None)
                fact_summary_ai = summarize_fact_checks(fact_data, ai_filter=None)
                
                # Story type creates a new story in the JSON
                if content_type == "story":
                    print(f"\nGenerating {content_type} with {content_ai}...")
                    if not use_cache:
                        print(f"  Cache disabled (--no-cache)")
                    content = generate_ai_content(gen_summary_ai, fact_summary_ai, content_ai, content_type, args.verbose, use_cache)
                    
                    if content:
                        # Save story to container
                        # Extract model from last AI call
                        result = process_prompt(content_ai, "", verbose=False, use_cache=use_cache)
                        _, _, _, ai_model = result
                        
                        story_index = save_story_to_container(
                            container, file_path, content,
                            content_ai, ai_model,
                            gen_summary_ai, fact_summary_ai
                        )
                        
                        if story_index > 0:
                            word_count = len(content.split())
                            print(f"  ✓ Story saved as story {story_index} ({word_count} words)")
                            print(f"  File updated: {file_path}")
                        else:
                            print(f"  ✗ Failed to save story")
                    else:
                        print(f"  ✗ Story generation failed")
                
                # Other types output to stdout
                else:
                    label_map = {
                        "title": "Title",
                        "short": "Short Caption",
                        "caption": "Detailed Caption",
                        "summary": "Summary"
                    }
                    label = label_map.get(content_type, content_type.title())
                    
                    print(f"\n{label} (generated by {content_ai}):")
                    if not use_cache:
                        print(f"  Cache disabled (--no-cache)")
                    print("─" * 70)
                    
                    content = generate_ai_content(gen_summary_ai, fact_summary_ai, content_ai, content_type, args.verbose, use_cache)
                    if content and content.strip():
                        print(content)
                        if args.verbose:
                            print(f"  ({len(content.split())} words)")
                    else:
                        print("(Content generation failed or returned empty content)")
                        if args.verbose:
                            print(f"  Debug: content='{content}' length={len(content) if content else 0}")
                    
                    print("─" * 70)
            
            print("\n" + "=" * 70)
    
    # Multi-file history analysis
    if args.history and len(containers) > 1:
        if not args.quiet:
            print(f"\n\nPerformance History ({len(containers)} files)\n")
            print("=" * 70)
        
        # Aggregate analysis
        gen_summary = summarize_generation(all_gen_data, args.ai)
        if gen_summary:
            print("\nAggregate Story Generation:")
            print(tabulate(gen_summary, headers="keys", tablefmt="simple"))
        
        fact_summary = summarize_fact_checks(all_fact_data, args.ai)
        if fact_summary:
            print("\nAggregate Fact-Checking:")
            print(tabulate(fact_summary, headers="keys", tablefmt="simple"))
        
        print("\n" + "=" * 70)
    
    # CSV export
    if args.csv:
        export_to_csv(all_gen_data, all_fact_data, args.csv)
        if not args.quiet:
            print(f"\nExported timing data to: {args.csv}")


if __name__ == "__main__":
    main()

