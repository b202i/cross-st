import os
import re
import shutil
from pathlib import Path


# ── Project-root tmp/ helpers ─────────────────────────────────────────────────

def get_project_root() -> Path:
    """Return the project root — the directory that contains mmd_util.py (and .env)."""
    return Path(os.path.abspath(os.path.dirname(os.path.realpath(__file__))))


def get_tmp_dir() -> Path:
    """Single tmp/ directory at the project root. Created on first use."""
    tmp = get_project_root() / "tmp"
    tmp.mkdir(exist_ok=True)
    return tmp


def tmp_safe_name(file_prefix: str) -> str:
    """
    Convert a (possibly path-containing) file prefix into a flat, collision-safe
    filename component by replacing path separators with '__'.

    Example:
        "story/shang/yubikey_2fa"  →  "story__shang__yubikey_2fa"
        "/abs/path/yubikey_2fa"    →  "yubikey_2fa"   (abs paths use basename only)
    """
    prefix = Path(file_prefix)
    # For absolute paths, make relative to project root when possible
    try:
        rel = prefix.resolve().relative_to(get_project_root())
        return str(rel).replace(os.sep, "__")
    except ValueError:
        # Not under the project root — fall back to basename
        return prefix.name


# ── Block file helpers ────────────────────────────────────────────────────────
# Block files and progress files all live in the single project-root tmp/ dir.
# Callers pass a `safe_name` produced by tmp_safe_name(file_prefix).

def block_file_path(safe_name: str) -> Path:
    """Return the full path for a block file given a tmp_safe_name."""
    return get_tmp_dir() / f"{safe_name}.block"


def create_block_file(safe_name: str, verbose: bool = False) -> None:
    """Touch the block file for `safe_name` in the project-root tmp/ dir."""
    path = block_file_path(safe_name)
    try:
        path.touch()
    except OSError as e:
        print(f"Error: Failed to create block file '{path}': {e}")
        raise
    if verbose:
        print(f"Created block file: {path}")


def remove_block_file(safe_name: str, verbose: bool = False) -> None:
    """Remove the block file for `safe_name` from the project-root tmp/ dir."""
    path = block_file_path(safe_name)
    if path.is_file():
        path.unlink()
        if verbose:
            print(f"Removed block file: {path}")
    else:
        if verbose:
            print(f"Block file not found (already removed?): {path}")


# ── Segment helpers ───────────────────────────────────────────────────────────

# Sentence-ending characters accepted as the last char of a fact-checkable
# paragraph.  Perplexity citation references ([1], [^2]) are stripped first.
_SENTENCE_ENDINGS = ('.', '!', '?')
_QUOTE_ENDINGS    = ('"', "'", '\u201c', '\u201d', '\u2018', '\u2019')
_ENDING_CHARS     = _SENTENCE_ENDINGS + _QUOTE_ENDINGS
_CITATION_RE      = re.compile(r'(\[\^?\d+])+\s*$')


def build_segments(text: str) -> list[dict]:
    """
    Split story *text* (plain text, not markdown) into fact-checkable units
    and return them as a stable, ordered list.

    Each segment is a dict:
        {
            "id":   <int, 0-based, stable for the lifetime of the story>,
            "text": <str, the paragraph text>,
            "para": <int, 0-based index of the source paragraph>
        }

    Rules (identical to the filter logic in st-fact):
      • Split on double newline.
      • Skip blank paragraphs and non-string values.
      • Skip paragraphs that do not end with a sentence-ending character
        (after stripping trailing citation references like [1] or [^2]).

    This function is deterministic: calling it twice on the same text
    always returns the same list with the same IDs.  All AI checkers
    that share this segment list therefore work on identical units,
    enabling true apples-to-apples parallel comparison.
    """
    segments: list[dict] = []
    seg_id = 0
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    for para_idx, para in enumerate(paragraphs):
        if not isinstance(para, str):
            para = str(para)
        stripped = _CITATION_RE.sub('', para).rstrip()
        if not stripped.endswith(_ENDING_CHARS):
            continue
        segments.append({"id": seg_id, "text": para, "para": para_idx})
        seg_id += 1

    return segments


# ── Template helpers ──────────────────────────────────────────────────────────

_USER_TEMPLATES_DIR = Path.home() / ".cross_templates"
_BUNDLED_TEMPLATES_DIR = Path(os.path.dirname(os.path.realpath(__file__))) / "template"

# Cross-Stones benchmark domain helpers
_DEFAULT_USER_STONES_DIR    = Path.home() / "cross-stones"
_BUNDLED_STONES_DOMAINS_DIR = Path(os.path.dirname(os.path.realpath(__file__))) / "cross_stones" / "domains"


def get_default_stones_dir() -> Path:
    """
    Return the user's benchmark domain directory.

    Resolution order:
    1. ``CROSS_STONES_DIR`` env var (set in ``~/.crossenv`` to override the default)
    2. ``~/cross-stones/`` — hardcoded home-directory default

    Example ``~/.crossenv`` entry to move the directory::

        CROSS_STONES_DIR=~/research/my-benchmarks
    """
    env_val = os.environ.get("CROSS_STONES_DIR", "").strip()
    if env_val:
        return Path(env_val).expanduser()
    return _DEFAULT_USER_STONES_DIR


def seed_user_templates(
    src_dir: "Path | str | None" = None,
    overwrite: bool = False,
    quiet: bool = True,
) -> tuple[int, int]:
    """
    Copy ``.prompt`` files from *src_dir* into ``~/.cross_templates/``.

    Parameters
    ----------
    src_dir   : source directory (defaults to ``<repo>/template/``).
    overwrite : replace files that already exist; default is non-destructive.
    quiet     : suppress per-file messages; default True.

    Returns
    -------
    (copied, skipped) — counts of files written vs. skipped.
    """
    src = Path(src_dir) if src_dir else _BUNDLED_TEMPLATES_DIR
    dst = _USER_TEMPLATES_DIR

    if not src.is_dir():
        return 0, 0

    dst.mkdir(parents=True, exist_ok=True)

    copied = skipped = 0
    for prompt_file in sorted(src.glob("*.prompt")):
        target = dst / prompt_file.name
        if target.exists() and not overwrite:
            skipped += 1
            if not quiet:
                print(f"  skip  {prompt_file.name}  (already exists)")
            continue
        shutil.copy2(prompt_file, target)
        copied += 1
        if not quiet:
            print(f"  copy  {prompt_file.name}  → {target}")

    return copied, skipped


def seed_stones_domains(
    dst_dir: "Path | str | None" = None,
    overwrite: bool = False,
    quiet: bool = True,
) -> tuple[int, int]:
    """
    Copy ``.prompt`` files from the bundled ``cross_stones/domains/`` directory
    into *dst_dir* (default: ``~/cross-stones/``).

    Parameters
    ----------
    dst_dir   : destination directory (default: ``~/cross-stones/``).
    overwrite : replace files that already exist; default is non-destructive.
    quiet     : suppress per-file messages; default True.

    Returns
    -------
    (copied, skipped) — counts of files written vs. skipped.
    """
    src = _BUNDLED_STONES_DOMAINS_DIR
    dst = Path(dst_dir).expanduser() if dst_dir else get_default_stones_dir()

    if not src.is_dir():
        return 0, 0

    dst.mkdir(parents=True, exist_ok=True)

    copied = skipped = 0
    for prompt_file in sorted(src.glob("*.prompt")):
        target = dst / prompt_file.name
        if target.exists() and not overwrite:
            skipped += 1
            if not quiet:
                print(f"  skip  {prompt_file.name}  (already exists)")
            continue
        shutil.copy2(prompt_file, target)
        copied += 1
        if not quiet:
            print(f"  copy  {prompt_file.name}  → {target}")

    return copied, skipped


