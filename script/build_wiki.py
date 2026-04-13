#!/usr/bin/env python3
"""
script/build_wiki.py — Generate per-command wiki pages from metadata + docstrings.

Each page follows a two-section structure:
  1. User section  — plain-English description, workflow context, examples, options, related links
  2. Developer section — implementation detail (omitted if nothing meaningful to add)

Pages that do NOT contain the auto-generated marker are never overwritten.
Hand-author a page by removing the marker line at the top.

Run from the repo root:
    python script/build_wiki.py
"""

import ast
import glob
import os
import re

REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIKI_DIR   = os.path.join(REPO_ROOT, "docs", "wiki")
DOCS_BASE  = "https://github.com/b202i/cross-st/blob/main/docs/wiki"

os.makedirs(WIKI_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Per-command metadata
# Keys:
#   desc   — plain-English one-paragraph description (user-facing, no jargon)
#   after  — list of command names typically run before this one
#   before — list of command names typically run after this one
#   related — list of command names OR named wiki page slugs (e.g. "ai-providers")
#   dev    — developer notes (implementation detail, internals, extension points)
#            omit the key entirely if there is nothing meaningful to add
# ─────────────────────────────────────────────────────────────────────────────
METADATA: dict[str, dict] = {
    "st": {
        "desc": "The interactive menu launcher. Run `st` in any directory with a `.json` story file and you get a keyboard-driven interface for the full Cross workflow.",
        "related": ["st-new", "st-bang", "Onboarding"],
    },
    "st-admin": {
        "desc": "Manages your Cross settings: default AI provider, per-provider model overrides, TTS voice, editor, and prompt templates. Run once during setup, then whenever you want to switch providers.",
        "related": ["st-new", "ai-providers", "tts-audio"],
        "dev": "Reads and writes `~/.crossenv` (global) and `.env` (repo-local). Model overrides are stored in `.ai_models`, one `provider=model` per line. `--init-templates` seeds `~/.cross_templates/` from the bundled `template/` directory.",
    },
    "st-analyze": {
        "desc": "Generates a narrative summary of the cross-product fact-check results — who scored highest, where AIs disagreed, and which claims were consistently disputed.",
        "after": ["st-cross"],
        "related": ["st-cross", "st-heatmap", "st-verdict"],
        "dev": "Flattens `fact[]` entries via `mmd_data_analysis.get_flattened_fc_data()` and passes the structured data to an AI for a prose summary.",
    },
    "st-bang": {
        "desc": "Generates stories from all AI providers simultaneously, then merges them into one container. Much faster than running `st-gen` once per provider.",
        "after": ["st-new"],
        "before": ["st-cross", "st-merge"],
        "related": ["st-gen", "st-merge", "st-cross"],
        "dev": "Launches one `st-gen --bang N` subprocess per AI. Each writes to `tmp/<story>_N.json` and creates a `.block` file. `st-bang` polls every second until all block files are removed, then merges the tmp files into the main container.",
    },
    "st-cat": {
        "desc": "Prints the raw JSON contents of a story container to the terminal. Useful for debugging or piping to other tools.",
        "related": ["st-ls", "st-edit"],
    },
    "st-cross": {
        "desc": "Runs the full research pipeline in one command: generates a story from every AI, then has every AI fact-check every story. The result is an N×N score matrix saved into the container.",
        "after": ["st-new"],
        "before": ["st-merge", "st-heatmap", "st-verdict", "st-analyze"],
        "related": ["st-bang", "st-fact", "st-heatmap", "st-verdict"],
        "dev": "Step 1 runs `st-gen --prep` per AI in parallel threads. Step 2 fact-checks all N×N pairs — each column (fact-checker AI) is a separate thread, serializing writes per story to avoid JSON corruption. The live ANSI display is updated every second. Ctrl+C preserves results collected so far.",
    },
    "st-domain": {
        # NOTE: docs/wiki/st-domain.md is hand-authored — build_wiki.py will not overwrite it.
        "desc": "Interactive wizard that builds a Cross-Stones benchmark domain prompt. Guides you through naming the domain, describing the topic, and smoke-testing that the AI returns exactly the right number of fact-checkable claims.",
        "related": ["st-stones", "st-cross", "cross-stones"],
        "dev": "Follows DOMAIN_PROMPT_PROCESS.md Phases 2–4. Phase 2: collects slug, display name, topic description, year range, source types. Phase 3: calls AI for 5 aspect suggestions, assembles the `_DOMAIN_PROMPT_TEMPLATE`, previews and saves. Phase 4: smoke-test sends the finished prompt to one AI and checks claim count. `--set` registers the new domain in a benchmark set config via `_add_to_benchmark_set()`.",
    },
    "st-edit": {
        "desc": "Opens any field in a story container — story text, title, spoken version, or a fact-check — in your configured editor. Changes are saved back to the `.json` file.",
        "after": ["st-prep"],
        "related": ["st-prep", "st-fix", "st-admin"],
    },
    "st-fact": {
        "desc": "Sends a single story to an AI and asks it to fact-check every claim, scoring each one true, partially true, or false. Appends the result to the container.",
        "after": ["st-prep"],
        "before": ["st-fix", "st-heatmap"],
        "related": ["st-cross", "st-fix", "st-heatmap"],
        "dev": "Splits the story into segments via `mmd_util.build_segments()`, sends them to the AI, and appends a `fact[]` entry to the container. The entry includes `score`, `counts`, `summary`, `claims[]` (per-segment verdicts), and `timing{}`.",
    },
    "st-fetch": {
        "desc": "Imports external content into a container as a raw data entry — a tweet by ID, a web URL, or a local file. The imported content can then be processed with `st-prep` like any generated story.",
        "before": ["st-prep"],
        "related": ["st-prep", "st-gen"],
        "dev": "`AI_MAKE` is set to `\"url\"` for fetched content; this handler is not in `AI_HANDLER_REGISTRY`. Twitter/X fetches require `X_COM_BEARER_TOKEN` in `.env`.",
    },
    "st-find": {
        "desc": "Searches all `.json` containers in a directory tree for stories matching a keyword. Prints matching titles and file paths.",
        "related": ["st-ls", "st-cat"],
    },
    "st-fix": {
        # NOTE: docs/wiki/st-fix.md is hand-authored — build_wiki.py will not overwrite it.
        # Deep-dive implementation notes are in docs/wiki/st-fix-implementation.md.
        "desc": "Rewrites the weak parts of a story using its fact-check results. Only sentences scored False or Partially False are touched — everything that checked out stays exactly as the AI wrote it.",
        "after": ["st-fact"],
        "before": ["st-post"],
        "related": ["st-fact", "st-merge", "st-post"],
        "dev": "Four modes: `iterate` (default) fixes one sentence at a time with inline verification; `patch` bundles all false claims into one prompt; `best-source` uses other AI stories as reference material; `synthesize` passes all stories and scores to one AI for a full rewrite. Mode set via `--mode`. See [st-fix-implementation.md](st-fix-implementation.md) for architecture details.",
    },
    "st-gen": {
        "desc": "Sends your prompt file to an AI provider and saves the raw response into a `.json` container. This is the first step — the container it creates is used by every other command.",
        "after": ["st-new"],
        "before": ["st-prep"],
        "related": ["st-bang", "st-prep", "ai-providers"],
        "dev": "Writes a new entry to `data[]` in the container. Caching is MD5-keyed on the serialized request payload — two identical prompts to the same model always hit the cache. `--bang N` is used internally by `st-bang` (writes to `tmp/` and creates a block file); don't call it directly.",
    },
    "st-heatmap": {
        "desc": "Generates a color-coded grid showing how every AI-pair scored in the cross-product fact-check. Rows are evaluator AIs, columns are target story authors. Darker cells = higher veracity scores. The diagonal shows self-evaluation scores.",
        "after": ["st-cross"],
        "related": ["st-cross", "st-verdict", "st-speed", "st-analyze"],
        "dev": "Uses `mmd_data_analysis.get_flattened_fc_data()` to build the score matrix, then renders with `mmd_plot`. AI content flags (`--ai-caption` etc.) call `process_prompt()` from `ai_handler` with the flattened score data as context.",
    },
    "st-ls": {
        "desc": "Lists the stories and fact-checks stored inside a `.json` container — titles, AI authors, scores, and timestamps.",
        "related": ["st-cat", "st-edit"],
    },
    "st-man": {
        "desc": "Shows the built-in help page for any `st-*` command, like the Linux `man` command. Add `--web` to open the full documentation page in your browser.",
        "related": ["Home"],
        "dev": "Extracts help text from the module docstring of each `st-*.py` file at runtime — no separate help database. Documentation pages live in `docs/wiki/` and are served directly from the GitHub repo; no wiki plan required.",
    },
    "st-merge": {
        "desc": "Combines multiple AI-generated stories into one cohesive report. When fact-check scores are available it uses the highest-scoring story as the base and pulls in verified facts from the others.",
        "after": ["st-bang"],
        "before": ["st-post"],
        "related": ["st-bang", "st-fix", "st-post"],
        "dev": "Two modes selected automatically: `simple` (no fact data — all stories passed to synthesizer AI) and `quality` (uses fact scores — highest-scoring story is the base; its author AI performs the rewrite for consistent voice). Override with `--simple` or `--quality`.",
    },
    "st-new": {
        "desc": "Creates a fresh prompt file from a template and opens your editor so you can fill in the topic. The starting point for every new research report.",
        "before": ["st-gen", "st-bang"],
        "related": ["st-gen", "st-bang", "st-admin"],
        "dev": "Template resolution order: `./template/` (CWD) → `~/.cross_templates/` → `<script-dir>/template/`. After editing, optionally launches `st-bang` automatically. `st-admin --init-templates` seeds `~/.cross_templates/` for pip/pipx installs.",
    },
    "st-plot": {
        "desc": "Generates charts from cross-product data: score distributions, AI comparisons, and timing breakdowns. Displays in the browser or saves to files.",
        "after": ["st-cross"],
        "related": ["st-cross", "st-heatmap", "st-verdict", "st-speed"],
        "dev": "Chart rendering lives in `mmd_plot.py`. Use `--plot all` to generate every chart type, `--file` to save instead of display, and `--path` to set the output directory.",
    },
    "st-post": {
        "desc": "Publishes a story to your Discourse forum. Optionally attaches an MP3 audio file. Use `--check` to verify your credentials without actually posting.",
        "after": ["st-prep", "st-fix", "st-merge"],
        "related": ["st-prep", "st-speak", "st-admin"],
        "dev": "Site credentials are read from the `DISCOURSE` JSON in `.env`. If an `.mp3` file is provided, it is uploaded first and the Discourse audio-player embed syntax is prepended to the post.",
    },
    "st-prep": {
        "desc": "Converts a raw AI response into a clean, structured story and appends it to the container. Extracts the title and hashtags, and optionally renders an MP3 audio file.",
        "after": ["st-gen", "st-fetch"],
        "before": ["st-fact", "st-post"],
        "related": ["st-gen", "st-fact", "st-speak"],
        "dev": "Called automatically by `st-gen --prep`, `st-cross`, `st-fetch`, and `st-fix`. Writes to `story[]` in the container. TTS rendering (`--mp3`) uses `mmd_voice.py` and requires the TTS extras (`pip install 'cross-ai[tts]'`).",
    },
    "st-print": {
        "desc": "Exports a story as a PDF, or sends it directly to a printer. Use `--save-pdf` to save the file without printing.",
        "after": ["st-prep"],
        "related": ["st-post", "st-edit"],
        "dev": "Pipeline: Markdown → HTML (via `mistune`) → PDF (via `WeasyPrint`). `--preview` opens the PDF in the system viewer before printing.",
    },
    "st-read": {
        "desc": "Shows reading-level metrics for a story: word count, sentence count, average sentence length, and Flesch Reading Ease score.",
        "after": ["st-prep"],
        "related": ["st-edit", "st-prep"],
    },
    "st-rm": {
        "desc": "Removes a story or a fact-check entry from a `.json` container. Use `-s` to specify the story and `-f` to specify the fact-check.",
        "related": ["st-ls", "st-cat"],
    },
    "st-speak": {
        "desc": "Renders a story as an MP3 audio file using text-to-speech. Requires the TTS extras to be installed.",
        "after": ["st-prep"],
        "before": ["st-post"],
        "related": ["st-voice", "st-post", "tts-audio"],
        "dev": "Requires `pip install 'cross-ai[tts]'`. Uses `mmd_voice.py` which connects to a local Piper TTS server (`TTS_HOST`/`TTS_PORT` in `.env`). Exits cleanly with an error message if TTS dependencies are missing.",
    },
    "st-speed": {
        "desc": "Compares AI provider performance across a container: generation time, tokens per second, and time-to-first-token. Useful for choosing a provider when speed matters.",
        "after": ["st-bang", "st-cross"],
        "related": ["st-stones", "st-cross", "st-heatmap"],
        "dev": "Reads `timing{}` dicts from `data[]` entries. Timing is written by `st-gen` on every non-cached call and is absent on cache hits.",
    },
    "st-stones": {
        "desc": "Scores AI providers on the Cross-Stones benchmark: a fixed set of domain prompts, each requiring exactly 10 fact-checkable claims. Produces a composite accuracy + speed leaderboard.",
        "after": ["st-cross"],
        "related": ["st-domain", "st-speed", "cross-stones"],
        "dev": "Score formula: `w1 × (fact_score / max_fact_score) + w2 × (speed_score / max_speed_score)` with defaults `w1=0.7`, `w2=0.3`. The locked benchmark set is `cross_stones/cross-stones-10.json`. Pass `--no-speed` for accuracy-only scoring.",
    },
    "st-verdict": {
        "desc": "Generates a stacked bar chart showing the true / partially-true / false verdict breakdown for each AI author across the cross-product fact-check.",
        "after": ["st-cross"],
        "related": ["st-cross", "st-heatmap", "st-analyze"],
        "dev": "Built on `mmd_plot.py`. Data comes from `mmd_data_analysis.get_flattened_fc_data()`.",
    },
    "st-voice": {
        "desc": "Lists available TTS voices and sets the active voice used by `st-speak`. The selected voice is saved to `TTS_VOICE` in your config.",
        "related": ["st-speak", "st-admin", "tts-audio"],
        "dev": "Voices are discovered from the local Piper TTS server. Run `st-admin` to set `TTS_HOST` and `TTS_PORT` if the server is not on localhost:5000.",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Docstring helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_docstring(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        doc = ast.get_docstring(ast.parse(src))
        if doc:
            return doc.strip()
    except SyntaxError:
        pass
    m = re.search(r'"""(.*?)"""', src, re.DOTALL)
    return m.group(1).strip() if m else ""


def _extract_examples(doc: str) -> tuple[str, str]:
    """Return (examples_block, options_line) extracted from the docstring."""
    # Code block(s)
    code_blocks = re.findall(r'```(?:bash)?\n(.*?)```', doc, re.DOTALL)
    examples = "\n\n".join(b.strip() for b in code_blocks) if code_blocks else ""

    # Options: line
    options = ""
    for line in doc.splitlines():
        if line.strip().startswith("Options:"):
            options = line.strip()
            break
    return examples, options


def _doc_body(doc: str) -> str:
    """Return the non-example, non-options body of a docstring (for dev notes fallback)."""
    lines = []
    in_code = False
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if stripped.startswith("Options:"):
            continue
        lines.append(line)
    text = "\n".join(lines).strip()
    # Remove the first line if it's just the command title (already in h1)
    first = text.splitlines()[0].strip() if text else ""
    if re.match(r'^#+\s*st[- ]', first) or re.match(r'^st[- ]\S+\s*[—–-]', first):
        text = "\n".join(text.splitlines()[1:]).strip()
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Page builder
# ─────────────────────────────────────────────────────────────────────────────

def _md_link(name: str) -> str:
    """Turn a command name or wiki slug into a Markdown link."""
    NAMED = {
        "home":         ("Home",          "Home.md"),
        "onboarding":   ("Onboarding",    "Onboarding.md"),
        "ai-providers": ("AI Providers",  "ai-providers.md"),
        "cross-stones": ("Cross-Stones",  "cross-stones.md"),
        "faq":          ("FAQ",           "faq.md"),
        "tts-audio":    ("TTS Audio",     "tts-audio.md"),
    }
    key = name.lower()
    if key in NAMED:
        display, filename = NAMED[key]
        return f"[{display}]({filename})"
    # st-* commands
    return f"[{name}]({name}.md)"


def build_command_page(name: str, path: str) -> str:
    doc  = get_docstring(path)
    meta = METADATA.get(name, {})

    # ── Headline ──────────────────────────────────────────────────────────────
    # Prefer first line of docstring for the subtitle; fall back to name
    raw_lines = [l.strip() for l in doc.splitlines() if l.strip()] if doc else []
    if raw_lines:
        subtitle = re.sub(r'^#+\s*', '', raw_lines[0])
        # If first line is just the command name with no dash description, use meta desc
        if not re.search(r'[—–-]', subtitle):
            subtitle = name
    else:
        subtitle = name

    page  = f"# {subtitle}\n\n"

    # ── User description ──────────────────────────────────────────────────────
    desc = meta.get("desc", "")
    if not desc and doc:
        body = _doc_body(doc)
        # Use first non-empty paragraph as fallback
        paras = [p.strip() for p in body.split("\n\n") if p.strip()]
        desc  = paras[0] if paras else ""
    if desc:
        page += f"{desc}\n\n"

    # ── Workflow context ──────────────────────────────────────────────────────
    after  = meta.get("after",  [])
    before = meta.get("before", [])
    if after or before:
        parts = []
        if after:
            parts.append("**Run after:** " + " \u00b7 ".join(f"`{c}`" for c in after))
        if before:
            parts.append("**Run before:** " + " \u00b7 ".join(f"`{c}`" for c in before))
        page += "  \u00b7  ".join(parts) + "\n\n"

    # ── Examples ──────────────────────────────────────────────────────────────
    examples, options = _extract_examples(doc)
    if examples:
        page += f"## Examples\n\n```bash\n{examples}\n```\n\n"
    if options:
        # Format as inline code spans
        opts = re.sub(r'Options:\s*', '', options)
        page += "**Options:** " + "  ".join(f"`{o}`" for o in opts.split()) + "\n\n"

    # ── Related ───────────────────────────────────────────────────────────────
    related = meta.get("related", [])
    if related:
        page += "**Related:** " + " \u00b7 ".join(_md_link(r) for r in related) + "\n\n"

    # ── Developer notes ───────────────────────────────────────────────────────
    dev = meta.get("dev", "")
    if not dev:
        # Fall back to docstring body only if it's substantive and not just examples
        body = _doc_body(doc)
        if len(body) > 120:
            dev = body
    if dev:
        page += "---\n\n## For developers\n\n"
        page += dev.strip() + "\n"

    return page


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    scripts = sorted(glob.glob(os.path.join(REPO_ROOT, "st-*.py")))
    scripts += [os.path.join(REPO_ROOT, "st.py")]

    MARKER    = "<!-- auto-generated by build_wiki.py -->"
    generated = []
    skipped   = []

    for path in scripts:
        name     = os.path.basename(path)[:-3]   # e.g. "st-gen"
        out_path = os.path.join(WIKI_DIR, f"{name}.md")

        # Never overwrite hand-authored pages (those without the marker)
        if os.path.exists(out_path):
            with open(out_path, encoding="utf-8") as f:
                if MARKER not in f.read():
                    skipped.append(name)
                    continue

        content = f"{MARKER}\n" + build_command_page(name, path)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        generated.append(name)

    for name in generated:
        print(f"  wrote  docs/wiki/{name}.md")
    for name in skipped:
        print(f"  kept   docs/wiki/{name}.md  (hand-authored)")

    print(f"\n  Done — {len(generated)} pages generated, {len(skipped)} preserved in docs/wiki/")
    print(f"  Push to GitHub with:  bash script/push_wiki.sh")


if __name__ == "__main__":
    main()

