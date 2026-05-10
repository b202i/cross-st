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

A small curated ``RECOMMENDED_MODELS`` dict provides the "common picks" used
as a fallback when ``cross_ai_core.get_available_models()`` (CAC-10h, shipped
in cross-ai-core 0.7.1) cannot reach a provider.  Users can always type any
model id directly; recommendations are ordering hints, never restrictions.
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
# Curated recommendations — offline fallback for CAC-10h discovery
# ─────────────────────────────────────────────────────────────────────────────
#
# Each entry is an ordered list of (model_id, label, recommended_bool).
# Recommended models are shown first with a ★ marker.  This dict is hand-
# maintained — when a new flagship lands, edit here and ship.
#
# As of cross-ai-core 0.7.1, ``cross_ai_core.get_available_models(make)``
# returns SDK-discovered ids annotated with ``is_recommended`` / ``is_default``
# from ``cross_ai_core.recommendations.RECOMMENDED_MODELS`` (the upstream
# source of truth).  This local dict is kept as a *secondary* fallback for
# offline / SDK-error paths in the interactive add-alias wizard.

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
# Legacy `.ai_models` migration (CST-MM-j)
# ─────────────────────────────────────────────────────────────────────────────
#
# Pre-0.9.x dev installs stored per-provider model overrides as ``make=model``
# lines in ``<project-root>/.ai_models`` (a repo-local file, never present in
# pipx user installs).  The 0.9.x alias system supersedes that file:
#
#   ``~/.cross_ai_models.json`` is the canonical home for ``alias → (make,
#   model)`` mappings, and ``<MAKE>_MODEL`` env vars override on a per-shell
#   basis.
#
# Migration policy:
#   * Run silently on every ``mmd_startup.load_cross_env()`` invocation.
#   * No-op when ``.ai_models`` is absent (covers every pipx user).
#   * For each parseable ``make=model`` line, add a user alias named
#     ``<make>-<short>`` (the bare ``<make>`` name is reserved for the
#     auto-seeded built-in self-alias).  ``<short>`` is a sanitised slice
#     of the model id; collisions get a numeric suffix.
#   * After successful processing, rename ``.ai_models`` to
#     ``.ai_models.migrated`` so the next startup is a fast no-op.  The
#     marker also acts as the audit trail — users can ``cat`` it to see
#     what their old config looked like.
#   * Print a one-line notice naming each new alias so the user knows
#     to switch from ``--agent <make>`` (which now means handler default) to
#     ``--agent <make>-<short>`` (which means the legacy model).
#   * Any error (unreadable file, invalid line) → log to stderr and skip
#     the offending line; never crashes the calling script.

_MODEL_SHORT_MAX = 20


def _model_short_id(model: str) -> str:
    """Sanitise *model* into an alias-safe suffix (``a-z 0-9 -`` only)."""
    out = []
    for ch in model.lower():
        if ch.isalnum() or ch == "-":
            out.append(ch)
        else:
            out.append("-")
    short = "".join(out).strip("-")
    while "--" in short:
        short = short.replace("--", "-")
    return short[:_MODEL_SHORT_MAX] or "custom"


def _legacy_ai_models_path() -> str:
    """Path to the pre-0.9.x ``.ai_models`` file at the project root."""
    from mmd_startup import _PROJECT_ROOT
    return os.path.join(_PROJECT_ROOT, ".ai_models")


def _migrated_marker_path() -> str:
    return _legacy_ai_models_path() + ".migrated"


def _parse_legacy_ai_models(path: str) -> list[tuple[str, str]]:
    """Return ``[(make, model), …]`` from a legacy ``.ai_models`` file.

    Lines starting with ``#`` and blank lines are skipped.  Lines without
    an ``=`` are skipped (no exception — be lenient on user data).
    """
    pairs: list[tuple[str, str]] = []
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except OSError:
        return pairs
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        make, _, model = line.partition("=")
        make, model = make.strip(), model.strip()
        if make and model:
            pairs.append((make, model))
    return pairs


def migrate_legacy_ai_models() -> list[tuple[str, str, str]]:
    """Idempotent one-shot migration.  Returns added ``[(alias, make, model), …]``.

    Empty list = nothing migrated (file absent, already migrated, or every
    line was unparseable / unknown make).  Caller may print a notice when
    the list is non-empty.
    """
    legacy = _legacy_ai_models_path()
    if not os.path.isfile(legacy):
        return []

    pairs = _parse_legacy_ai_models(legacy)
    if not pairs:
        # Empty / fully-commented file — still rename so we don't keep
        # checking it on every startup.
        try:
            os.replace(legacy, _migrated_marker_path())
        except OSError:
            pass
        return []

    builtins = set(_builtin_makes())
    file_data = read_alias_file()
    added: list[tuple[str, str, str]] = []

    for make, model in pairs:
        if make not in builtins:
            # Unknown provider — skip silently; user must have hand-edited
            # an exotic name.
            continue
        # Skip if any existing user alias already has this exact (make, model).
        already = any(
            spec.get("make") == make and spec.get("model") == model
            for spec in file_data.values()
        )
        if already:
            continue
        # Generate a unique alias name.
        base  = f"{make}-{_model_short_id(model)}"
        alias = base
        n = 2
        while alias in file_data or alias in builtins:
            alias = f"{base}-{n}"
            n += 1
        file_data[alias] = {"make": make, "model": model}
        added.append((alias, make, model))

    if added:
        try:
            write_alias_file(file_data)
        except Exception:
            # Persist failed → leave the legacy file in place so we'll retry
            # next startup (keeps the user's data safe).
            return []

    # Rename the legacy file regardless of how many lines were actionable —
    # otherwise we'd keep re-parsing the same skip-listed entries.
    try:
        os.replace(legacy, _migrated_marker_path())
    except OSError:
        pass

    return added


def run_migration_with_notice() -> None:
    """Run :func:`migrate_legacy_ai_models` and print a friendly one-liner.

    Safe to call from ``mmd_startup.load_cross_env()`` — every failure mode
    is swallowed and reported as a single warning line so the calling
    ``st-*`` script never crashes mid-startup.
    """
    try:
        added = migrate_legacy_ai_models()
    except Exception as exc:  # pragma: no cover — defensive
        print(
            f"  ⚠️  Could not migrate legacy .ai_models: {exc}",
            flush=True,
        )
        return
    if not added:
        return
    aliases = ", ".join(f"{a}" for a, _, _ in added)
    print(
        f"  ✓ Migrated legacy .ai_models → ~/.cross_ai_models.json "
        f"(new aliases: {aliases}). Use --agent <alias> to select; original "
        "file kept as .ai_models.migrated for reference.",
        flush=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# File I/O
# ─────────────────────────────────────────────────────────────────────────────

# Schema constants — kept locally (not imported) so this module stays
# functional even if cross-ai-core is older than 0.8.0.  They mirror
# ``cross_ai_core.aliases.SCHEMA_VERSION`` / ``_MIGRATION_MARKER``.
_SCHEMA_VERSION    = 2
_MIGRATION_MARKER  = "_migrated_to_agents_v2"


def _read_raw_json() -> "dict | None":
    """Return parsed JSON for the alias file, or ``None`` if absent/invalid.

    Used by :func:`migrate_to_agents_v2` to inspect the on-disk envelope
    *before* :func:`read_alias_file` flattens it back to v1 shape.
    """
    path = aliases_file_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            raw = json.load(f, object_pairs_hook=OrderedDict)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def _is_v2_envelope(raw: "dict | None") -> bool:
    return (
        isinstance(raw, dict)
        and raw.get("version") == _SCHEMA_VERSION
        and isinstance(raw.get("agents"), dict)
    )


def read_alias_file() -> "OrderedDict[str, dict]":
    """Return the raw alias map from disk, flattened to v1 shape.

    Always returns ``{name: {"make": …, "model": …}}`` regardless of
    whether the file is v1 (legacy flat dict) or v2 (envelope with
    ``provider``-keyed inner specs).  Existing st-admin / wizard / test
    code is written against the flat shape, so this method preserves
    that contract while the new envelope is the on-disk truth.

    Missing / empty / malformed file → empty OrderedDict.
    """
    raw = _read_raw_json()
    if raw is None:
        return OrderedDict()
    body = raw["agents"] if _is_v2_envelope(raw) else raw
    if not isinstance(body, dict):
        return OrderedDict()
    out: "OrderedDict[str, dict]" = OrderedDict()
    for name, spec in body.items():
        if not isinstance(spec, dict):
            continue
        # Inner schema accepts either ``provider`` (v2) or ``make`` (v1);
        # ``provider`` wins when both are present.
        make = spec.get("provider", spec.get("make"))
        if make is None:
            continue
        out[name] = {"make": make, "model": spec.get("model")}
    return out


def write_alias_file(data: "dict[str, dict]") -> None:
    """Atomically write *data* to ``~/.cross_ai_models.json`` and reload.

    *data* is the v1 flat shape ``{name: {"make": …, "model": …}}``.
    On disk this is wrapped in the v2 envelope (``provider`` inner key,
    ``_migrated_to_agents_v2: True``).

    Atomicity: write to a sibling temp file in the same directory, then
    ``os.replace()`` — ensures readers never see a half-written file.
    """
    path = aliases_file_path()
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    envelope: "OrderedDict[str, object]" = OrderedDict()
    envelope["version"] = _SCHEMA_VERSION
    envelope["agents"] = OrderedDict(
        (name, {"provider": spec["make"], "model": spec.get("model")})
        for name, spec in data.items()
    )
    envelope[_MIGRATION_MARKER] = True
    fd, tmp = tempfile.mkstemp(prefix=".cross_ai_models.", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(envelope, f, indent=2)
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
# AGT-2 — Agents v2 first-run migration
# ─────────────────────────────────────────────────────────────────────────────
#
# Two branches:
#
#   1. *Existing v1 file* (cross-st ≤ 0.9.x writes flat dicts) — re-emit it
#      in the v2 envelope.  No alias names change, no entries are dropped.
#      Idempotent: subsequent runs see ``_migrated_to_agents_v2: true`` and
#      do nothing.
#
#   2. *Fresh install* (no file at all) — for every provider with an API key
#      present, seed one starter agent named after the provider, model from
#      ``cross_ai_core.get_recommended_default(provider)``.  Users get a
#      working setup on first run without touching ``st-admin``.
#
# Either path writes via :func:`write_alias_file`, so the v2 envelope and
# the reload of the in-process registry happen in one place.

def _migrated_v2_marker_seen() -> bool:
    """``True`` when the on-disk file is already v2 with the migration marker."""
    raw = _read_raw_json()
    return _is_v2_envelope(raw) and bool(raw.get(_MIGRATION_MARKER))


def _seed_agents_from_api_keys() -> "OrderedDict[str, dict]":
    """Build the starter-agent map for fresh installs.

    Inspects ``cross_ai_core.PROVIDER_API_KEY_ENV`` and creates one entry
    per provider whose API key is set in the environment.  Model ids come
    from ``get_recommended_default``; ``None`` is left in the spec when no
    curated default exists (the provider's handler default still applies
    at call time).

    Returns an empty mapping when no API keys are present — caller
    interprets that as "fresh install, nothing to do".
    """
    try:
        from cross_ai_core import (
            PROVIDER_API_KEY_ENV, has_api_key, get_recommended_default,
        )
    except ImportError:  # cross-ai-core < 0.8.0 — no Agents v2 support
        return OrderedDict()
    seeded: "OrderedDict[str, dict]" = OrderedDict()
    for provider in PROVIDER_API_KEY_ENV:
        try:
            if not has_api_key(provider):
                continue
        except Exception:
            continue
        try:
            model = get_recommended_default(provider)
        except Exception:
            model = None
        seeded[provider] = {"make": provider, "model": model}
    return seeded


def migrate_to_agents_v2() -> "tuple[str, list[str]]":
    """Idempotent first-run migration to the Agents v2 schema.

    Returns ``(action, agent_names)`` where ``action`` is one of:

      * ``"noop"``   — already migrated; nothing changed.
      * ``"v1_to_v2"`` — existing v1 file re-emitted as a v2 envelope.
      * ``"seeded"`` — fresh install with API keys; starter agents created.
      * ``"empty"``  — fresh install, no API keys; nothing written.

    ``agent_names`` lists the names defined after the call (always empty
    for ``"noop"`` and ``"empty"`` actions).

    All errors are swallowed by the public wrapper
    :func:`run_agents_v2_migration_with_notice`; this function itself
    only catches API-availability errors so callers writing custom flows
    can still see programming mistakes.
    """
    if _migrated_v2_marker_seen():
        return ("noop", [])

    raw = _read_raw_json()
    if raw is not None:
        # v1 → v2 — re-emit through write_alias_file (which envelope-wraps).
        flat = read_alias_file()
        write_alias_file(flat)
        return ("v1_to_v2", list(flat.keys()))

    seeded = _seed_agents_from_api_keys()
    if not seeded:
        return ("empty", [])
    write_alias_file(seeded)
    return ("seeded", list(seeded.keys()))


def run_agents_v2_migration_with_notice() -> None:
    """Run :func:`migrate_to_agents_v2` and print a friendly one-liner.

    Safe to call from ``mmd_startup.load_cross_env()`` — every failure
    mode is swallowed and reported as a single warning line so the
    calling ``st-*`` script never crashes mid-startup.
    """
    try:
        action, names = migrate_to_agents_v2()
    except Exception as exc:  # pragma: no cover — defensive
        print(
            f"  ⚠️  Could not migrate agents file to v2: {exc}",
            flush=True,
        )
        return
    if action == "noop" or action == "empty":
        return
    if action == "v1_to_v2":
        print(
            "  ✓ Upgraded ~/.cross_ai_models.json to Agents v2 schema "
            f"({len(names)} agent{'s' if len(names) != 1 else ''} preserved).",
            flush=True,
        )
        return
    if action == "seeded":
        agents = ", ".join(names)
        print(
            f"  ✓ Created {len(names)} starter agent"
            f"{'s' if len(names) != 1 else ''} from detected API keys: "
            f"{agents}. Manage with `st-admin` → AI menu.",
            flush=True,
        )


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
        otherwise we'd silently change what ``--agent anthropic`` means.
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

    Each row: ``{"alias", "make", "model_effective", "model_label",
    "model_file", "env_override", "is_builtin"}``.

    * ``model_effective`` = what would actually be sent to the provider
      (env override → file → curated provider default → ``"<unknown>"``).
    * ``model_label``      = display string for the wizard:
        - ``"<id>"``                  when an explicit model is set
        - ``"<id> (provider default)"`` when None resolves via curated default
        - ``"<id> (override <ENV_VAR>)"`` when an env var wins
    * ``model_file``      = the value stored in the JSON file (or ``None``).
    * ``env_override``    = env var name overriding the file (or ``None``).
    * ``is_builtin``      = ``True`` for auto-seeded self-aliases (one per
      provider) — i.e. you didn't create this one yourself.
    """
    from cross_ai_core.aliases import get_aliases
    try:
        from cross_ai_core import get_recommended_default
    except ImportError:  # cross-ai-core < 0.7.1
        get_recommended_default = lambda _make: None  # noqa: E731

    file_data = read_alias_file()
    builtins  = set(_builtin_makes())
    rows: list[dict] = []
    for alias, spec in get_aliases().items():
        env_var = env_override_for(alias, spec.make)
        if env_var:
            effective = os.environ[env_var]
            label = f"{effective}  (override {env_var})"
        elif spec.model:
            effective = spec.model
            label = effective
        else:
            # No explicit model — resolve to the provider's curated default
            # so the user sees what will actually run, not "<handler default>".
            curated = get_recommended_default(spec.make)
            if curated:
                effective = curated
                label = f"{curated}  (provider default)"
            else:
                effective = "<unknown>"
                label = "<provider default>"
        rows.append({
            "alias":           alias,
            "make":            spec.make,
            "model_effective": effective,
            "model_label":     label,
            "model_file":      file_data.get(alias, {}).get("model"),
            "env_override":    env_var,
            "is_builtin":      alias in builtins and alias not in file_data,
        })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Pretty-printing helpers (used by st-admin's interactive menu)
# ─────────────────────────────────────────────────────────────────────────────

def format_alias_table(rows: "Iterable[dict]") -> str:
    """Render the alias rows as a fixed-width plain-text table.

    Columns: Agent · Provider · Model · Type · Env override.

    *Agent* is the user-facing name for what the codebase calls an "alias"
    — a short label (e.g. ``anthropic``, ``anthropic-opus``) that resolves
    to one ``(provider, model)`` pair.  *Type* is ``default`` for the
    one-per-provider agents that ship with cross-st and ``custom`` for
    agents the user defined in ``~/.cross_ai_models.json``.  Both call the
    provider's API at the provider's published rate — neither is "free".
    """
    rows = list(rows)
    if not rows:
        return "  (no agents loaded)"
    # Each tuple: (agent_name, provider, model_label, type, env_override)
    cells = [
        (
            r["alias"],
            r["make"],
            r["model_label"],
            "default" if r["is_builtin"] else "custom",
            r["env_override"] or "—",
        )
        for r in rows
    ]
    headers = ("Agent", "Provider", "Model", "Type", "Env override")
    widths  = [
        max(len(headers[i]), max(len(c[i]) for c in cells))
        for i in range(len(headers))
    ]
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
    sep = "  " + "  ".join("─" * w for w in widths)
    lines = [fmt.format(*headers), sep]
    for c in cells:
        lines.append(fmt.format(*c))
    return "\n".join(lines)

