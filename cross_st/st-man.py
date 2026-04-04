#!/usr/bin/env python3
"""
st-man — Show help for any st-* command

Display built-in help for any st-* command, or open its documentation page.
Works like the Linux man command: local by default, browser on request.

    st-man                      # list all commands with one-line descriptions
    st-man st-gen               # display full help for st-gen
    st-man gen                  # shorthand — "st-" prefix is optional
    st-man st-gen --web         # open the st-gen docs page in browser
    st-man --web                # open the Cross docs home page
    st-man onboarding           # open the onboarding docs page
"""

import ast
import os
import re
import sys
import webbrowser

# Documentation lives in docs/wiki/ in the main repo — no separate wiki repo needed.
# GitHub renders Markdown files at blob/main URLs for free on any plan.
_DOCS_BASE  = "https://github.com/b202i/cross/blob/main/docs/wiki"
_DOCS_HOME  = f"{_DOCS_BASE}/Home.md"

# Named non-command pages: slug → filename in docs/wiki/
WIKI_PAGES  = {
    "home":         "Home.md",
    "onboarding":   "Onboarding.md",
    "ai-providers": "ai-providers.md",
    "cross-stones": "cross-stones.md",
    "faq":          "faq.md",
    "tts-audio":    "tts-audio.md",
}

# Keep WIKI_BASE as a public alias for any external callers
WIKI_BASE = _DOCS_BASE
_HERE       = os.path.dirname(os.path.abspath(__file__))

# Related commands shown as "See also" links at the bottom of each help page
SEE_ALSO = {
    "st-ls":      ["st-fact", "st-cross", "st-read", "st-cat"],
    "st-fact":    ["st-cross", "st-ls",   "st-fix",  "st-heatmap"],
    "st-cross":   ["st-fact",  "st-ls",   "st-heatmap", "st-verdict"],
    "st-heatmap": ["st-cross", "st-verdict", "st-ls", "st-speed"],
    "st-verdict": ["st-cross", "st-heatmap", "st-ls"],
    "st-fix":     ["st-fact",  "st-merge", "st-ls"],
    "st-merge":   ["st-fix",   "st-ls",    "st-fact"],
    "st-gen":     ["st-bang",  "st-prep",  "st-fact"],
    "st-bang":    ["st-gen",   "st-cross", "st-ls"],
    "st-prep":    ["st-gen",   "st-fact",  "st-read"],
    "st-read":    ["st-ls",    "st-cat",   "st-prep"],
    "st-plot":    ["st-heatmap", "st-verdict", "st-speed"],
    "st-speed":   ["st-plot",  "st-stones"],
    "st-stones":  ["st-cross", "st-domain", "st-speed"],
    "st-domain":  ["st-stones", "st-new"],
    "st-new":     ["st-gen",   "st-bang",  "st-admin"],
    "st-post":    ["st-prep",  "st-fact",  "st-read"],
    "st-fetch":   ["st-gen",   "st-prep"],
    "st-speak":   ["st-voice", "st-prep",  "st-read"],
    "st-voice":   ["st-speak", "st-prep"],
    "st-analyze": ["st-fact",  "st-cross", "st-heatmap"],
}

# Canonical command list — order determines index display
COMMANDS = [
    "st",
    "st-admin",    "st-analyze",  "st-bang",    "st-cat",
    "st-cross",    "st-domain",   "st-edit",    "st-fact",
    "st-fetch",    "st-find",     "st-fix",     "st-gen",
    "st-heatmap",  "st-ls",       "st-man",     "st-merge",
    "st-new",      "st-plot",     "st-post",    "st-prep",
    "st-print",    "st-read",     "st-rm",      "st-speak",
    "st-speed",    "st-stones",   "st-verdict", "st-voice",
]


# ─────────────────────────────────────────────────────────────────────────────
# Docstring extraction
# ─────────────────────────────────────────────────────────────────────────────

def _get_help(name: str) -> tuple[str, str]:
    """Return (one_liner, full_doc) by parsing the source file for *name*."""
    path = os.path.join(_HERE, f"{name}.py")
    if not os.path.exists(path):
        return f"{name} — (script not found)", ""

    with open(path, encoding="utf-8") as f:
        src = f.read()

    full_doc = ""

    # 1. Prefer a proper module-level docstring (ast-parsed)
    try:
        doc = ast.get_docstring(ast.parse(src))
        if doc:
            full_doc = doc.strip()
    except SyntaxError:
        pass

    # 2. Fall back to the first triple-quoted block in the file
    if not full_doc:
        m = re.search(r'"""(.*?)"""', src, re.DOTALL)
        if m:
            full_doc = m.group(1).strip()

    if not full_doc:
        full_doc = (
            f"{name}\n\n"
            f"No built-in description available.\n"
            f"Run `{name} --help` for usage information.\n"
            f"Docs: {_DOCS_BASE}/{name}.md"
        )

    # One-liner: first non-empty line, strip leading ## / # markers
    lines = [l.strip() for l in full_doc.splitlines() if l.strip()]
    one_liner = re.sub(r'^#+\s*', '', lines[0]) if lines else name

    return one_liner, full_doc


# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

_WIDTH = 72


def _print_index() -> None:
    print(f"\n  Cross — command reference  ({_DOCS_HOME})\n")
    for cmd in COMMANDS:
        one_liner, _ = _get_help(cmd)
        # Keep only the part after the em-dash for compact display
        parts = re.split(r'\s+[—–-]\s+', one_liner, maxsplit=1)
        desc  = parts[1] if len(parts) > 1 else one_liner
        if len(desc) > 54:
            desc = desc[:51] + "…"
        print(f"  {cmd:<18s}  {desc}")

    print()
    print(f"  Wiki pages:  onboarding  ai-providers  cross-stones  faq")
    print(f"  Usage:       st-man <command>            local help")
    print(f"               st-man <command> --web      open wiki page")
    print(f"               st-man --web                open wiki home")
    print()


def _print_command_help(name: str) -> None:
    one_liner, full_doc = _get_help(name)
    wiki_url = f"{_DOCS_BASE}/{name}.md"

    print()
    print("─" * _WIDTH)
    print(f"  {one_liner}")
    print("─" * _WIDTH)
    print()

    # Strip leading line from body if it is the same as the one-liner summary
    body_lines = full_doc.splitlines()
    if body_lines:
        first_clean = re.sub(r'^#+\s*', '', body_lines[0].strip())
        if first_clean == one_liner:
            body_lines = body_lines[1:]

    for line in body_lines:
        stripped = line.strip()
        if not stripped:
            print()
            continue
        if stripped.startswith("##"):
            heading = stripped.lstrip("#").strip()
            print(f"  {heading}")
            print(f"  {'─' * len(heading)}")
        elif stripped.startswith("#"):
            print(f"  {stripped.lstrip('#').strip()}")
        else:
            print(f"  {line}")

    print()
    print("─" * _WIDTH)
    print(f"  Wiki:  {wiki_url}")
    print(f"  Tip:   st-man {name} --web   opens the wiki page in your browser")
    if name in SEE_ALSO:
        related = SEE_ALSO[name]
        see_line = "  ·  ".join(related)
        print(f"  See also: {see_line}")
    print("─" * _WIDTH)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    open_web = "--web" in args
    args     = [a for a in args if a != "--web"]

    # --help / -h → show the index (st-man has no argparse; handle manually)
    if "--help" in args or "-h" in args:
        _print_index()
        return

    # No argument → index
    if not args:
        if open_web:
            webbrowser.open(_DOCS_HOME)
            print(f"  Opening: {_DOCS_HOME}")
        else:
            _print_index()
        return

    target = args[0].lower()

    # Named wiki pages (not st-* commands)
    if target in WIKI_PAGES:
        filename = WIKI_PAGES[target]
        url = f"{_DOCS_BASE}/{filename}"
        print(f"  Opening: {url}")
        webbrowser.open(url)
        return

    # Normalise shorthand: "gen" → "st-gen", "admin" → "st-admin", "st" → "st"
    if target != "st" and not target.startswith("st-"):
        target = f"st-{target}"

    if target not in COMMANDS:
        print(f"\n  Unknown command: {target!r}")
        print(f"  Run 'st-man' to see all available commands.\n")
        sys.exit(1)

    if open_web:
        url = f"{_DOCS_BASE}/{target}.md"
        print(f"  Opening: {url}")
        webbrowser.open(url)
        return

    _print_command_help(target)


if __name__ == "__main__":
    main()


