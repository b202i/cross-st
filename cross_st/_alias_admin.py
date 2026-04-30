"""
cross_st._alias_admin — helpers for managing ``~/.cross_ai_models.json``.

Used by ``st-admin.py``'s AI submenu (CST-MM-i).  Provides a thin layer over
the read-only ``cross_ai_core.aliases`` API:

    * read_alias_file()      — return raw user-defined aliases (dict)
    * write_alias_file(data) — atomic write + reload registry
    * add_alias(...)         — validate, persist, reload
    * remove_alias(name)     — delete, persist, reload
    * edit_alias_model(...)  — change the model for an existing alias
    * list_aliases()         — every loaded alias + env override label
    * env_override_for(...)  — which env var (if any) overrides this alias

A small curated ``RECOMMENDED_MODELS`` dict provides the "common picks" the
interactive picker shows when CAC-10h's live ``list_models()`` discovery is
not yet wired up.  Users can always type any model id directly; recommendations
are ordering hints, never restrictions.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import OrderedDict
from typing import Iterable

# These are lazy-imported inside functions to avoid a hard dependency at module
# import time (eases test isolation when cross-ai-core is shimmed).


# ─────────────────────────────────────────────────────────────────────────────
# Path resolution — mirrors cross_ai_core.aliases._aliases_file_path()
# ─────────────────────────────────────────────────────────────────────────────

def aliases_file_path() -> str:
    """Path to the alias JSON file.  Override with ``CROSS_AI_ALIASES_FILE``."""
    override = os.environ.get("CROSS_AI_ALIASES_FILE", "").strip()
    if override:
        return os.path.expanduser(override)
    return os.path.expanduser("~/.cross_ai_models.json")


# ─────────────────────────────────────────────────────────────────────────────
# Curated recommendations — placeholder until CAC-10h ships
# ─────────────────────────────────────────────────────────────────────────────
#
# Each entry is an ordered list of (model_id, label, recommended_bool).
# Recommended models are shown first with a ★ marker.  This dict is hand-
# maintained — when a new flagship lands, edit here and ship.
#
# Resolution: once CAC-10h provides ``get_available_models(make)``, this dict
# becomes a static *override* layer ranking SDK-discovered ids; not the
# source of truth.

RECOMMENDED_MODELS: "OrderedDict[str, list[tuple[str, str, bool]]]" = OrderedDict({
    "anthropic": [
        ("claude-opus-4-5",          "latest flagship",     True),
        ("claude-sonnet-4-5",        "latest balanced",     True),
        ("claude-3-7-sonnet-latest", "previous-gen sonnet", False),
        ("claude-3-5-haiku-latest",  "fast / cheap",        False),
    ],
    "openai": [
        ("gpt-4o",       "latest flagship",      True),
        ("gpt-4o-mini",  "cheap general-purpose", True),
        ("gpt-4-turbo",  "previous flagship",     False),
        ("o1-mini",      "reasoning model",       False),
    ],
    "xai": [
        ("grok-4-1-fast-reasoning",   "latest reasoning",   True),
        ("grok-3",                    "previous flagship",  True),
        ("grok-3-mini",               "cheap",              False),
    ],
    "gemini": [
        ("gemini-2.5-pro",       "latest flagship",   True),
        ("gemini-2.5-flash",     "fast / cheap",      True),
        ("gemini-1.5-pro",       "previous flagship", False),
    ],
    "perplexity": [
        ("sonar-pro",     "flagship search",  True),
        ("sonar",         "balanced",         True),
        ("sonar-reasoning", "reasoning + search", False),
    ],
})


def get_recommended_models(make: str) -> list[tuple[str, str, bool]]:
    """Return curated suggestions for *make*; empty list when unknown."""
    return list(RECOMMENDED_MODELS.get(make, ()))


# ─────────────────────────────────────────────────────────────────────────────
# File I/O
# ─────────────────────────────────────────────────────────────────────────────

def read_alias_file() -> "OrderedDict[str, dict]":
    """Return the raw alias map from disk, preserving declaration order.

    Missing / empty / malformed file → empty OrderedDict.  Callers that need
    to *validate* should call :func:`add_alias` (validates) or trust the
    cross-ai-core registry (validates at load time).
    """
    path = aliases_file_path()
    if not os.path.isfile(path):
        return OrderedDict()
    try:
        with open(path) as f:
            raw = json.load(f, object_pairs_hook=OrderedDict)
    except (OSError, json.JSONDecodeError):
        return OrderedDict()
    if not isinstance(raw, dict):
        return OrderedDict()
    return raw


def write_alias_file(data: "dict[str, dict]") -> None:
    """Atomically write *data* to ``~/.cross_ai_models.json`` and reload.

    Atomicity: write to a sibling temp file in the same directory, then
    ``os.replace()`` — ensures readers never see a half-written file.
    """
    path = aliases_file_path()
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".cross_ai_models.", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    # Re-seed the in-process registry so the new alias is immediately usable
    # without restarting st-admin.
    try:
        from cross_ai_core.aliases import reload_aliases
        reload_aliases()
    except Exception:
        pass  # registry refresh is best-effort; file is already saved


# ─────────────────────────────────────────────────────────────────────────────
# Mutations
# ─────────────────────────────────────────────────────────────────────────────

class AliasError(ValueError):
    """Raised when an alias mutation is rejected (collision, unknown make…)."""


def _builtin_makes() -> list[str]:
    from cross_ai_core.ai_handler import AI_LIST
    return list(AI_LIST)


def add_alias(name: str, make: str, model: "str | None") -> None:
    """Validate and persist a new alias.

    Validation:
      * ``name`` must be non-empty.
      * ``make`` must be a known built-in provider.
      * If ``name`` shadows a built-in make (e.g. ``"anthropic"``), the
        target make must be the same and ``model`` must be ``None`` —
        otherwise we'd silently change what ``--ai anthropic`` means.
        Raise :class:`AliasError` to refuse.
      * ``model`` may be ``None`` (= use handler default) or a non-empty string.

    Existing aliases with the same name are *replaced* (this is also how the
    interactive "edit" flow works).
    """
    name = (name or "").strip()
    make = (make or "").strip()
    if model is not None:
        model = model.strip() or None

    if not name:
        raise AliasError("Alias name cannot be empty.")
    builtins = _builtin_makes()
    if make not in builtins:
        raise AliasError(
            f"Unknown make {make!r}. Known: {', '.join(builtins)}"
        )
    if name in builtins and (name != make or model is not None):
        raise AliasError(
            f"Alias {name!r} would shadow built-in make {name!r} with a "
            f"different mapping. Pick a different alias name "
            f"(e.g. {make}-{model or 'custom'!r})."
        )

    data = read_alias_file()
    data[name] = {"make": make, "model": model}
    write_alias_file(data)


def remove_alias(name: str) -> None:
    """Delete a user-defined alias.  Refuses built-in self-aliases.

    Built-in makes are auto-seeded by the registry — they can't be "removed"
    in the meaningful sense (the next reload re-creates them).  Trying to
    remove one is almost certainly a user error, so raise loudly.
    """
    name = (name or "").strip()
    if not name:
        raise AliasError("Alias name cannot be empty.")
    data = read_alias_file()
    if name not in data:
        if name in _builtin_makes():
            raise AliasError(
                f"{name!r} is a built-in make, not a user alias — cannot remove."
            )
        raise AliasError(f"No alias named {name!r}.")
    del data[name]
    write_alias_file(data)


def edit_alias_model(name: str, model: "str | None") -> None:
    """Change the ``model`` field of an existing user alias.

    To edit the make as well, remove the alias and re-add it.
    """
    name = (name or "").strip()
    data = read_alias_file()
    if name not in data:
        raise AliasError(
            f"No user alias named {name!r}. Use 'Add alias' to create one."
        )
    if model is not None:
        model = model.strip() or None
    data[name]["model"] = model
    write_alias_file(data)


# ─────────────────────────────────────────────────────────────────────────────
# Reads — for the table view
# ─────────────────────────────────────────────────────────────────────────────

def env_override_for(alias: str, make: str) -> "str | None":
    """Return the env-var name overriding this alias's model, or ``None``.

    Resolution chain (matches ``cross_ai_core.ai_handler.get_ai_model``):
        ``<ALIAS_UPPER>_MODEL`` → ``<MAKE_UPPER>_MODEL`` → file → handler
    """
    alias_var = f"{alias.upper().replace('-', '_')}_MODEL"
    make_var  = f"{make.upper()}_MODEL"
    if os.environ.get(alias_var):
        return alias_var
    if os.environ.get(make_var):
        return make_var
    return None


def list_aliases() -> list[dict]:
    """Return one row per loaded alias.

    Each row: ``{"alias", "make", "model_effective", "model_file",
    "env_override", "is_builtin"}``.

    * ``model_effective`` = what would actually be sent to the provider
      (env override → file → handler default placeholder ``"<handler default>"``).
    * ``model_file``      = the value stored in the JSON file (or ``None``).
    * ``env_override``    = env var name overriding the file (or ``None``).
    * ``is_builtin``      = ``True`` for auto-seeded self-aliases.
    """
    from cross_ai_core.aliases import get_aliases

    file_data = read_alias_file()
    builtins  = set(_builtin_makes())
    rows: list[dict] = []
    for alias, spec in get_aliases().items():
        env_var = env_override_for(alias, spec.make)
        if env_var:
            effective = os.environ[env_var]
        elif spec.model:
            effective = spec.model
        else:
            effective = "<handler default>"
        rows.append({
            "alias":           alias,
            "make":            spec.make,
            "model_effective": effective,
            "model_file":      file_data.get(alias, {}).get("model"),
            "env_override":    env_var,
            "is_builtin":      alias in builtins and alias not in file_data,
        })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Pretty-printing helpers (used by st-admin's interactive menu)
# ─────────────────────────────────────────────────────────────────────────────

def format_alias_table(rows: "Iterable[dict]") -> str:
    """Render the alias rows as a fixed-width plain-text table."""
    rows = list(rows)
    if not rows:
        return "  (no aliases loaded)"
    headers = ("Alias", "Make", "Model", "Env override")
    widths  = [
        max(len(headers[0]), max(len(r["alias"])           for r in rows)),
        max(len(headers[1]), max(len(r["make"])            for r in rows)),
        max(len(headers[2]), max(len(r["model_effective"]) for r in rows)),
        max(len(headers[3]), max(len(r["env_override"] or "—") for r in rows)),
    ]
    fmt = f"  {{:<{widths[0]}}}  {{:<{widths[1]}}}  {{:<{widths[2]}}}  {{:<{widths[3]}}}"
    sep = "  " + "  ".join("─" * w for w in widths)
    lines = [fmt.format(*headers), sep]
    for r in rows:
        marker = " (built-in)" if r["is_builtin"] else ""
        lines.append(fmt.format(
            r["alias"] + marker,
            r["make"],
            r["model_effective"],
            r["env_override"] or "—",
        ))
    return "\n".join(lines)

