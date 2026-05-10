"""
cross_st.cli_agent — shared ``--agent`` CLI helper (AGT-9, 0.11.0).

Provides two helpers used by every ``st-*`` command that takes
``--agent``:

  * :func:`add_agent_arg(parser, **kwargs)` — register the ``--agent``
    argument with consistent help text.  ``kwargs`` (e.g. ``default=``,
    ``choices=``) override the helper's defaults so scripts that need
    custom fallback semantics (``default=None`` for "use the
    content-type default") can still opt in.

  * :func:`resolve_agent(value)` — delegate to
    :func:`cross_ai_core.resolve_agent` and re-raise its
    :class:`ValueError` with a uniform "no such agent" hint.

Per-script adoption is rolling: the 12 scripts whose ``--agent`` flag
was renamed in AGT-3 each have slightly different argparse stanzas
(distinct defaults, with/without ``choices=``) and were left untouched
by AGT-9 to minimise regression risk.  New code should call
:func:`add_agent_arg` so future scripts share one canonical surface.
"""
from __future__ import annotations

import argparse
from typing import Any


_DEFAULT_HELP = "Agent name (defined in ~/.cross_ai_models.json via st-admin)"


def add_agent_arg(
    parser: argparse.ArgumentParser,
    *,
    default: Any = None,
    choices: "list[str] | None" = None,
    help: str = _DEFAULT_HELP,
    **extra: Any,
) -> argparse.Action:
    """Register ``--agent`` on *parser* with shared help / metadata.

    Args:
        parser:  The :class:`argparse.ArgumentParser` to mutate.
        default: Default agent name; if ``None``, the script must fall
                 back to :func:`cross_ai_core.get_default_ai` after
                 parsing.  Most scripts pass ``get_default_ai()``.
        choices: Optional list of valid agent names.  When omitted the
                 helper does not constrain choices at parse time —
                 rely on :func:`resolve_agent` for the friendly error.
        help:    Help text shown by ``--help``.
        **extra: Extra kwargs forwarded to ``add_argument``.

    Returns:
        The :class:`argparse.Action` returned by ``add_argument`` so
        callers can mutate it further.
    """
    kwargs: dict[str, Any] = {
        "type": str,
        "default": default,
        "metavar": "NAME",
        "help": help,
    }
    if choices is not None:
        kwargs["choices"] = choices
    kwargs.update(extra)
    return parser.add_argument("--agent", **kwargs)


def resolve_agent(value: str):
    """Resolve *value* to an :class:`AgentSpec` via ``cross_ai_core``.

    Re-raises :class:`ValueError` with the upstream message, which
    already includes the ``did_you_mean`` hint and the list of defined
    agents.  Callers that want to print a custom error should catch
    :class:`ValueError`.
    """
    from cross_ai_core import resolve_agent as _resolve  # lazy import
    return _resolve(value)

