#!/usr/bin/env python3
"""
## st-print — Convert a story to PDF and print or save

Converts a story's Markdown to a high-quality PDF using WeasyPrint.
The PDF is styled with a clean, print-optimised stylesheet.

By default, sends the PDF to the system default printer via `lpr`.
Use `--save-pdf` to write to a file instead, and `--output` to specify
an explicit filename. Use `--preview` to open the PDF after saving.

Run after:  st-gen   (generated a story)
            st-prep  (polished the story text)
Run before: st-post  (publish to Discourse)
            done     (or save/print and you're finished)

```
st-print subject.json                      # print story 1 to default printer
st-print --save-pdf subject.json           # save as subject.pdf (auto-named)
st-print --output report.pdf subject.json  # save to an explicit filename
st-print -s 2 subject.json                # print story 2
st-print --all subject.json               # print all stories (one PDF each)
st-print --preview subject.json           # save PDF then open in viewer
st-print --printer "HP_LaserJet" s.json   # send to a specific printer
```

Options: -s story  --all  --save-pdf  --output FILE  --preview  --printer  -v  -q

Requires: pip install weasyprint
"""

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from mmd_startup import require_config, load_cross_env

try:
    from weasyprint import HTML as _WeasyHTML
except ImportError:
    _WeasyHTML = None  # type: ignore[assignment,misc]

# ── Environment loading (A1 convention) ──────────────────────────────────────
load_cross_env()


# ── CSS stylesheet for printed stories ───────────────────────────────────────

_CSS = """
@page {
    size: letter;
    margin: 1in 1in 0.9in 1in;

    @bottom-center {
        content: counter(page) " / " counter(pages);
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-size: 9pt;
        color: #888;
    }
}

/* ── Base typography ── */
body {
    font-family: Georgia, 'Times New Roman', 'Liberation Serif', serif;
    font-size: 11pt;
    line-height: 1.65;
    color: #1a1a1a;
    max-width: 100%;
}

/* ── Headings ── */
h1 {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 20pt;
    font-weight: 700;
    color: #111;
    line-height: 1.25;
    margin-top: 0;
    margin-bottom: 0.4em;
    page-break-after: avoid;
}

h2 {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 14pt;
    font-weight: 700;
    color: #222;
    margin-top: 1.4em;
    margin-bottom: 0.3em;
    border-bottom: 1px solid #ddd;
    padding-bottom: 0.15em;
    page-break-after: avoid;
}

h3 {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 12pt;
    font-weight: 700;
    color: #333;
    margin-top: 1.2em;
    margin-bottom: 0.25em;
    page-break-after: avoid;
}

h4, h5, h6 {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 11pt;
    font-weight: 700;
    color: #444;
    margin-top: 1em;
    margin-bottom: 0.2em;
    page-break-after: avoid;
}

/* ── Paragraphs and body content ── */
p {
    margin-top: 0;
    margin-bottom: 0.75em;
    orphans: 3;
    widows: 3;
}

/* ── Lists ── */
ul, ol {
    margin-top: 0.2em;
    margin-bottom: 0.75em;
    padding-left: 1.6em;
}

li {
    margin-bottom: 0.2em;
}

/* ── Blockquotes ── */
blockquote {
    border-left: 3px solid #aaa;
    margin-left: 0;
    padding-left: 1em;
    color: #555;
    font-style: italic;
}

/* ── Code ── */
code {
    font-family: 'Courier New', Courier, 'Lucida Console', monospace;
    font-size: 9.5pt;
    background: #f5f5f5;
    padding: 0.1em 0.3em;
    border-radius: 2px;
}

pre {
    background: #f5f5f5;
    border: 1px solid #e0e0e0;
    border-radius: 3px;
    padding: 0.7em 0.9em;
    font-size: 9pt;
    overflow-x: auto;
    page-break-inside: avoid;
}

pre code {
    background: none;
    padding: 0;
}

/* ── Tables ── */
table {
    border-collapse: collapse;
    width: 100%;
    margin-bottom: 1em;
    font-size: 10pt;
    page-break-inside: avoid;
}

th {
    background: #f0f0f0;
    font-weight: 700;
    text-align: left;
    padding: 0.4em 0.6em;
    border: 1px solid #ccc;
}

td {
    padding: 0.35em 0.6em;
    border: 1px solid #ddd;
    vertical-align: top;
}

tr:nth-child(even) td {
    background: #fafafa;
}

/* ── Images ── */
img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 0.5em auto;
}

/* ── Horizontal rule ── */
hr {
    border: none;
    border-top: 1px solid #ccc;
    margin: 1.2em 0;
}

/* ── Metadata header ── */
.story-meta {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 9pt;
    color: #666;
    border-bottom: 1px solid #ccc;
    padding-bottom: 0.5em;
    margin-bottom: 1.2em;
}

.story-meta .meta-row {
    display: inline-block;
    margin-right: 1.2em;
}

/* ── Footer branding ── */
.story-footer {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 8.5pt;
    color: #888;
    border-top: 1px solid #ddd;
    margin-top: 1.5em;
    padding-top: 0.6em;
}

/* ── Strong and emphasis ── */
strong { font-weight: 700; }
em     { font-style: italic; }
"""


# ── HTML template ─────────────────────────────────────────────────────────────

def _build_html(story: dict, story_idx: int, total_stories: int,
                source_file: str) -> str:
    """Convert a story dict to a complete HTML document for PDF rendering."""
    import markdown as md_lib

    make   = story.get("make", "")
    model  = story.get("model", "")
    title  = story.get("title", "").strip()
    body_md = story.get("markdown", "").strip()
    tags   = story.get("hashtags", []) or []
    date_str = datetime.today().strftime("%B %-d, %Y")

    # Convert Markdown → HTML (tables and fenced_code extensions add table/code support)
    html_body = md_lib.markdown(
        body_md,
        extensions=["extra", "tables", "fenced_code", "nl2br"],
    )

    # Build metadata row
    meta_parts = []
    if make:
        meta_parts.append(f'<span class="meta-row">AI: <strong>{make}</strong>'
                          + (f' / {model}' if model else '') + '</span>')
    meta_parts.append(f'<span class="meta-row">Date: {date_str}</span>')
    if total_stories > 1:
        meta_parts.append(f'<span class="meta-row">Story {story_idx} of {total_stories}</span>')
    if source_file:
        meta_parts.append(f'<span class="meta-row">Source: {os.path.basename(source_file)}</span>')

    meta_html = '<div class="story-meta">' + "".join(meta_parts) + '</div>'

    # Footer with hashtags + branding
    footer_parts = ["crossai.dev"]
    if tags:
        footer_parts.append(" · " + "  ".join(tags))
    footer_html = f'<div class="story-footer">{" ".join(footer_parts)}</div>'

    # Title — use explicit title field; fall back to h1 extracted from markdown
    if not title:
        import re
        m = re.match(r'^#\s+(.+)$', body_md, re.MULTILINE)
        title = m.group(1).strip() if m else os.path.basename(source_file or "Story")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
{meta_html}
{html_body}
{footer_html}
</body>
</html>
"""


def _esc(text: str) -> str:
    """Minimal HTML entity escaping for attribute/title contexts."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


# ── PDF generation ────────────────────────────────────────────────────────────

def _render_pdf(html: str) -> bytes:
    """Render HTML to PDF bytes using WeasyPrint."""
    if _WeasyHTML is None:
        print("Error: WeasyPrint is not installed. Run: pip install weasyprint")
        sys.exit(1)
    return _WeasyHTML(string=html).write_pdf()


# ── Print / save helpers ──────────────────────────────────────────────────────

def _print_pdf(pdf_bytes: bytes, printer: str | None, verbose: bool) -> None:
    """Send PDF bytes to a printer via lpr (macOS / Linux)."""
    lpr_args = ["lpr"]
    if printer:
        lpr_args += ["-P", printer]

    if verbose:
        dest = printer if printer else "default printer"
        print(f"  Sending to {dest} via lpr …")

    proc = subprocess.run(
        lpr_args,
        input=pdf_bytes,
        capture_output=True,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip()
        print(f"Error: lpr failed — {err}")
        sys.exit(1)


def _open_pdf(path: str) -> None:
    """Open a PDF file in the system viewer."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", path], check=True)
        elif system == "Linux":
            subprocess.run(["xdg-open", path], check=True)
        elif system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
    except Exception as e:
        print(f"Could not open viewer: {e}")


def _default_pdf_path(json_file: str, story_idx: int, total: int) -> str:
    """Auto-generate a PDF filename from the container path."""
    base = Path(json_file).stem
    if total > 1:
        return f"{base}_story{story_idx}.pdf"
    return f"{base}.pdf"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog="st-print",
        description="Convert a story to PDF and print or save it.",
    )
    parser.add_argument(
        "json_file", type=str, metavar="file.json",
        help="Path to the story container JSON file",
    )
    parser.add_argument(
        "-s", "--story", type=int, default=1,
        help="Story number to print (1-based, default: 1)",
    )
    parser.add_argument(
        "--all", dest="all_stories", action="store_true",
        help="Print / save all stories in the container",
    )
    parser.add_argument(
        "--save-pdf", dest="save_pdf", action="store_true",
        help="Save PDF to a file instead of printing (auto-names from container)",
    )
    parser.add_argument(
        "--output", dest="output", type=str, default=None, metavar="FILE.pdf",
        help="Explicit output PDF filename (implies --save-pdf)",
    )
    parser.add_argument(
        "--preview", action="store_true",
        help="Save PDF and open it in the system PDF viewer",
    )
    parser.add_argument(
        "--printer", type=str, default=None, metavar="NAME",
        help="Send to a named printer (passed to lpr -P); default printer if omitted",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress informational output",
    )

    args = parser.parse_args()

    file_prefix = args.json_file.rsplit(".", 1)[0]
    file_json   = file_prefix + ".json"

    if not os.path.isfile(file_json):
        print(f"Error: File not found: {file_json}")
        sys.exit(1)

    try:
        with open(file_json, "r", encoding="utf-8") as f:
            container = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {file_json}: {e}")
        sys.exit(1)

    stories = container.get("story", [])
    if not stories:
        print("Error: No stories found in container (run st-prep first).")
        sys.exit(1)

    # Determine which stories to process
    if args.all_stories:
        indices = list(range(1, len(stories) + 1))
    else:
        idx = args.story
        if idx < 1 or idx > len(stories):
            print(f"Error: Story {idx} does not exist (container has {len(stories)} stories).")
            sys.exit(1)
        indices = [idx]

    # Determine output mode
    do_save  = args.save_pdf or args.output or args.preview
    do_print = not do_save  # print by default unless saving

    explicit_pdf = args.output  # str or None

    for story_idx in indices:
        story = stories[story_idx - 1]

        make  = story.get("make", "unknown")
        model = story.get("model", "")
        title_short = (story.get("title") or f"story {story_idx}")[:60]

        if not args.quiet:
            print(f"  Building PDF — story {story_idx}/{len(stories)}  [{make}]  {title_short}")

        html = _build_html(
            story=story,
            story_idx=story_idx,
            total_stories=len(stories),
            source_file=file_json,
        )

        if args.verbose:
            print(f"    Rendering HTML → PDF …")

        pdf_bytes = _render_pdf(html)

        if not args.quiet:
            print(f"    PDF size: {len(pdf_bytes) / 1024:.1f} KB")

        if do_save or args.preview:
            # Determine output path
            if explicit_pdf and len(indices) == 1:
                # Single story with explicit name: use it directly
                out_path = explicit_pdf
            else:
                out_path = _default_pdf_path(file_json, story_idx, len(indices))

            with open(out_path, "wb") as f:
                f.write(pdf_bytes)

            if not args.quiet:
                print(f"    Saved: {out_path}")

            if args.preview:
                _open_pdf(out_path)
        else:
            # Print mode — use a temp file (lpr reads stdin)
            _print_pdf(pdf_bytes, args.printer, args.verbose)
            if not args.quiet:
                dest = f"printer '{args.printer}'" if args.printer else "default printer"
                print(f"    Sent to {dest}")


if __name__ == "__main__":
    main()

