"""
cross_st._alias_admin — DEPRECATED back-compat shim (AGT-9, 0.11.0).

Importing this module emits a :class:`DeprecationWarning`.  Switch to
:mod:`cross_st._agent_admin`.

This shim re-exports every public name that lived in the old
``_alias_admin.py`` module so any external (or test) code that does
``from cross_st._alias_admin import add_alias`` continues to work
unmodified for one release.  Removed in cross-st 0.12.0.
"""
from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "cross_st._alias_admin is deprecated; import from cross_st._agent_admin "
    "instead.  This shim will be removed in cross-st 0.12.0.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export every public name from the renamed module.  The new module
# defines the legacy names as back-compat assignments, so we can pull
# them through as-is.
from cross_st._agent_admin import (  # noqa: F401  (re-export)
    AgentError,
    AliasError,
    RECOMMENDED_MODELS,
    add_agent,
    add_alias,
    agents_file_path,
    aliases_file_path,
    agents_missing_keys,
    edit_agent_model,
    edit_alias_model,
    env_override_for,
    format_agent_table,
    format_alias_table,
    get_recommended_models,
    list_agents,
    list_aliases,
    migrate_legacy_ai_models,
    migrate_to_agents_v2,
    providers_with_unused_keys,
    read_agents_file,
    read_alias_file,
    remove_agent,
    remove_alias,
    run_agents_v2_migration_with_notice,
    run_migration_with_notice,
    write_agents_file,
    write_alias_file,
)

