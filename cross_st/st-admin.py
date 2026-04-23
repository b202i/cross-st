#!/usr/bin/env python3
"""
st-admin — Manage settings, API keys, and templates

Manages persistent configuration: default AI provider, AI models per provider,
TTS voice, default prompt template, and editor.

First-time setup:
  st-admin --setup                # interactive wizard: checks environment,
                                  # collects API keys, writes ~/.crossenv

Interactive mode (no flags):
  st-admin                        # full interactive settings panel

Non-interactive (scripting / shell):
  st-admin --show                 # print all settings and exit
  st-admin --get-default-ai       # print the current default AI name
  st-admin --set-default-ai NAME  # set default AI (writes DEFAULT_AI to .env)
  st-admin --set-ai-model MAKE=MODEL  # set the model for a provider
  st-admin --set-tts-voice VOICE  # set TTS voice (writes TTS_VOICE to .env)
  st-admin --set-template NAME    # set default prompt template
  st-admin --set-editor NAME      # set editor (writes EDITOR to .env)
  st-admin --init-templates       # seed ~/.cross_templates/ from bundled defaults
  st-admin --upgrade              # upgrade cross-st from PyPI + macOS platform tools
  st-admin --cache-info           # print cache path, file count, and total size
  st-admin --cache-clear          # delete all cached AI responses
  st-admin --cache-cull DAYS      # delete cache entries older than DAYS days
  st-admin --check-tos            # check T&C acceptance; prompt re-acceptance if stale

Settings are persisted in:
  ~/.crossenv   — DEFAULT_AI, TTS_VOICE, DEFAULT_TEMPLATE, EDITOR, API keys
  .ai_models    — per-provider model overrides (MAKE=model, one per line)

The DEFAULT_AI setting is read by ai_handler.get_default_ai() and used
everywhere a provider is needed but not explicitly specified (captions,
report writing, etc.).  Never hardcode a provider name in code — always
call get_default_ai() or pass --ai on the CLI.

TTS (text-to-speech) — optional, Python 3.10–3.13:
  st-admin --set-tts-voice VOICE  writes the chosen Piper voice name to
  TTS_VOICE in .env.  The interactive V key opens st-voice so you can browse
  and audition available voices before committing to one.
  See also: st-voice (browse / download Piper voices)
            st-speak (render a report container to MP3)
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

try:
    import readline  # noqa: F401 — enables arrow keys & backspace in input() prompts
except ImportError:
    pass  # Windows has no readline; input() still works

from dotenv import load_dotenv, set_key

from ai_handler import get_ai_list, AI_HANDLER_REGISTRY
from base_handler import _get_cache_dir
from mmd_startup import load_cross_env, _PROJECT_ROOT, _in_project_venv
from mmd_util import (seed_user_templates, _USER_TEMPLATES_DIR, _BUNDLED_TEMPLATES_DIR,
                      seed_stones_domains, _DEFAULT_USER_STONES_DIR, get_default_stones_dir)


# ── Paths ──────────────────────────────────────────────────────────────────────
_CROSSENV    = os.path.expanduser("~/.crossenv")
_models_path = os.path.join(_PROJECT_ROOT, ".ai_models")  # repo root, not cross_st/

# Where st-admin reads-and-writes settings.
#
# Profile          | _TARGET_ENV
# -----------------|------------------------------------------------
# pipx user        | ~/.crossenv (the only file that exists)
# Developer        | <project-root>/.env (layer 2, wins via override=True)
#
# Picking the file that actually has the highest priority for the running
# profile prevents the silent-shadow bug where st-admin wrote to ~/.crossenv
# but a dev project-root .env immediately overrode it on next load.
# See `cross-internal/st-admin/BUGFIX_discourse_add_site_shadowed.md` and the
# "Two user types" section in `cross-internal/AGENTS.md`.
_DEV_MODE   = _in_project_venv()
_TARGET_ENV = os.path.join(_PROJECT_ROOT, ".env") if _DEV_MODE else _CROSSENV

load_cross_env()

# ── Discourse constants ────────────────────────────────────────────────────────
_DISCOURSE_TEST_CATEGORY_ID         = 6
_DISCOURSE_TEST_CATEGORY_SLUG       = "test-cleared-daily"
_DISCOURSE_TEST_CATEGORY_NAME       = "Test (cleared daily)"
_DISCOURSE_REPORTS_CATEGORY_ID      = 16
_DISCOURSE_REPORTS_CATEGORY_SLUG    = "reports"
_DISCOURSE_REPORTS_CATEGORY_NAME    = "📄 Reports"
_DISCOURSE_PROMPT_LAB_CATEGORY_ID   = 17
_DISCOURSE_PROMPT_LAB_CATEGORY_SLUG = "prompt-lab"
_DISCOURSE_PROMPT_LAB_CATEGORY_NAME = "🧪 Prompt Lab"


# ── Low-level helpers ──────────────────────────────────────────────────────────

def _env_get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_set(key: str, value: str):
    """Write a key to the active settings file and update os.environ.

    The active file (`_TARGET_ENV`) is chosen at startup based on profile:
      • pipx-installed user → `~/.crossenv`
      • developer (sys.executable inside the project tree) → `<project>/.env`

    Picking the file that already has the highest priority for the loader
    avoids the silent-shadow bug where writes to `~/.crossenv` were
    immediately overridden by the dev project-root `.env` on the next load.
    `_warn_if_shadowed()` still flags any *other* file (e.g. CWD `.env`)
    that overrides our write.
    """
    set_key(_TARGET_ENV, key, value)
    os.environ[key] = value
    _warn_if_shadowed(key)


def _warn_if_shadowed(key: str) -> None:
    """Warn when another .env in the loader chain overrides our write.

    The loader order in mmd_startup.load_cross_env() is:
      1. ~/.crossenv
      2. <project-root>/.env       (override=True; dev checkout only)
      2b. <cross_st-dir>/.env      (override=True; pip-install layout)
      3. <CWD>/.env                (override=True; highest priority)

    A file is "shadowing" only if it is loaded *after* `_TARGET_ENV` and
    contains the same key. The file we just wrote to is excluded.
    """
    try:
        from dotenv import dotenv_values
        from mmd_startup import _PROJECT_ROOT, _CROSS_ST_DIR  # type: ignore
    except Exception:
        return

    # Loader order (later wins). Skip layers 2/2b for non-dev profiles
    # because load_cross_env() skips them too.
    chain = [_CROSSENV]
    if _DEV_MODE:
        chain.append(os.path.join(_PROJECT_ROOT, ".env"))
        chain.append(os.path.join(_CROSS_ST_DIR, ".env"))
    chain.append(os.path.join(os.getcwd(), ".env"))

    target_real = os.path.realpath(_TARGET_ENV)
    try:
        target_index = next(
            i for i, p in enumerate(chain)
            if os.path.realpath(p) == target_real
        )
    except StopIteration:
        target_index = -1  # _TARGET_ENV isn't in the chain (shouldn't happen)

    shadowing = []
    for path in chain[target_index + 1:]:
        if not os.path.isfile(path) or os.path.realpath(path) == target_real:
            continue
        try:
            vals = dotenv_values(path)
        except Exception:
            continue
        if key in vals:
            shadowing.append(path)

    if shadowing:
        print()
        print(f"  ⚠️  Warning: {key} was written to {_TARGET_ENV},")
        print(f"      but the following file(s) shadow it (override=True wins):")
        for path in shadowing:
            print(f"        • {path}")
        print(f"      Remove the {key}= line from those file(s) for the new value to take effect.")
        print()


# ── Settings readers / writers ─────────────────────────────────────────────────

def settings_get_default_ai() -> str:
    """Return the configured default AI, or the first in AI_LIST."""
    ai_list   = get_ai_list()
    configured = _env_get("DEFAULT_AI", "").strip()
    if configured and configured in ai_list:
        return configured
    return ai_list[0]


def settings_set_default_ai(make: str) -> None:
    """Persist DEFAULT_AI to .env.  Raises ValueError for unknown providers."""
    ai_list = get_ai_list()
    if make not in ai_list:
        raise ValueError(
            f"Unknown AI provider: {make!r}.  "
            f"Valid choices: {', '.join(ai_list)}"
        )
    _env_set("DEFAULT_AI", make)


def settings_get_ai_model(make: str) -> str:
    """Return the active model for *make*, preferring .ai_models over compiled-in default."""
    if os.path.isfile(_models_path):
        with open(_models_path) as f:
            for line in f.read().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    if k.strip() == make and v.strip():
                        return v.strip()
    handler = AI_HANDLER_REGISTRY.get(make)
    return handler.get_model() if handler else "unknown"


def settings_set_ai_model(make: str, model: str) -> None:
    """Write a model override to .ai_models (create if absent)."""
    if os.path.isfile(_models_path):
        with open(_models_path) as f:
            lines = f.read().splitlines()
    else:
        lines = []

    new_lines, found = [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{make}=") or stripped.startswith(f"{make} ="):
            new_lines.append(f"{make}={model}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{make}={model}")

    with open(_models_path, "w") as f:
        f.write("\n".join(new_lines) + "\n")


def settings_get_tts_voice() -> str:
    return _env_get("TTS_VOICE", "en_US-lessac-medium")


def settings_get_default_template() -> str:
    return _env_get("DEFAULT_TEMPLATE", "default")


def settings_get_editor() -> str:
    return _env_get("EDITOR", os.environ.get("EDITOR", "vi"))


def init_user_templates(overwrite: bool = False) -> None:
    """
    Copy bundled .prompt files into ~/.cross_templates/.
    Prints a summary of what was copied / skipped.
    """
    src = _BUNDLED_TEMPLATES_DIR
    dst = _USER_TEMPLATES_DIR
    if not src.is_dir():
        print(f"  ✗  Bundled template directory not found: {src}")
        return
    print(f"\n  Source : {src}")
    print(f"  Dest   : {dst}")
    copied, skipped = seed_user_templates(src_dir=src, overwrite=overwrite, quiet=False)
    if copied == 0 and skipped == 0:
        print("  No .prompt files found in source.")
    else:
        print(f"\n  ✓  {copied} copied, {skipped} skipped.")
    print()


def _tool_check(cmd: str, flag: str = "--version") -> tuple[bool, str]:
    """Return (found, trimmed_version_line) for a CLI tool."""
    import shutil as _shutil
    if not _shutil.which(cmd):
        return False, ""
    try:
        r = subprocess.run([cmd, flag], capture_output=True, text=True, timeout=5)
        out = (r.stdout or r.stderr).strip()
        line = out.splitlines()[0] if out else "(installed)"
        return True, line[:48] + "…" if len(line) > 48 else line
    except Exception:
        return True, "(installed)"


def _build_client_info() -> str:
    """
    Assemble a client identifier string for TOS audit trail.

    Returns e.g. "cross-st/0.4.0 Python/3.12.3"
    """
    try:
        from importlib.metadata import version as _pkg_ver
        _cross_ver = _pkg_ver("cross-st")
    except Exception:
        _cross_ver = "unknown"
    return f"cross-st/{_cross_ver} Python/{sys.version.split()[0]}"


def _run_discourse_setup() -> None:
    """
    Discourse community onboarding sub-wizard.
    Called from setup_wizard() opt-in prompt, or directly via --discourse-setup.

    Handles two scenarios:
    - First-time setup: full 4-step wizard (T&C → invite → username → provision).
    - Re-acceptance:    if crossai.dev already configured but TOS is stale, shows
                        updated T&C, records acceptance, updates ~/.crossenv, returns.
    - Already current:  if crossai.dev configured and TOS is current, prints
                        "up to date" and returns immediately.
    """
    from cross_st.discourse_provision import (
        display_terms_and_conditions,
        discourse_onboard,
        get_invite_link,
        write_discourse_env,
        get_tos_versions,
        record_tos_acceptance,
    )
    import json
    import webbrowser
    from datetime import datetime, timezone

    print(f"\n  {'─' * 60}")
    print("  crossai.dev Community Onboarding")
    print(f"  {'─' * 60}\n")

    versions     = get_tos_versions()
    manifest_tos = versions.get("tos_version", "")
    manifest_priv = versions.get("privacy_version", "")

    # ── Check if already configured ───────────────────────────────────────────
    method            = "cli_setup"
    existing_username = None
    disc_json_str     = _env_get("DISCOURSE", "")

    if disc_json_str:
        try:
            existing_data = json.loads(disc_json_str)
            sites = (existing_data.get("sites", [])
                     if isinstance(existing_data, dict) else [])
            crossai_site = next(
                (s for s in sites if "crossai.dev" in s.get("url", "")), None
            )
            if crossai_site:
                existing_username = crossai_site.get("username", "")
                stored_tos  = crossai_site.get("tos_version",  "")
                stored_priv = crossai_site.get("privacy_version", "")

                if (stored_tos and manifest_tos and
                        stored_tos >= manifest_tos and
                        stored_priv and stored_priv >= manifest_priv):
                    # TOS up to date — nothing to do
                    print(
                        f"  ✅  Terms of Service are up to date "
                        f"(version {stored_tos}). No action needed.\n"
                    )
                    return

                if existing_username:
                    # Already provisioned but TOS is stale (or no TOS recorded) —
                    # quick re-acceptance flow; no need to re-run the full wizard.
                    if stored_tos:
                        print(
                            f"  ⚠️  Terms of Service have been updated. "
                            f"Re-acceptance required.\n"
                            f"  Previous version: {stored_tos}  →  Current: {manifest_tos}\n"
                        )
                    method = "cli_reaccept"
        except Exception:
            pass

    # ── Quick re-acceptance (already provisioned, TOS stale) ─────────────────
    if method == "cli_reaccept" and existing_username:
        accepted = display_terms_and_conditions(versions=versions)
        if not accepted:
            print("\n  ⚠️  You must accept the Terms of Service.")
            print(
                "  Run st-admin --discourse-setup or "
                "st-admin --check-tos to accept.\n"
            )
            return
        print("  ✅  Terms accepted.\n")

        ok = record_tos_acceptance(
            existing_username,
            tos_version=manifest_tos,
            privacy_version=manifest_priv,
            method="cli_reaccept",
            client_info=_build_client_info(),
        )
        if ok:
            print(f"  ✓  Acceptance recorded for {existing_username}\n")

        # Update stored TOS version in DISCOURSE JSON
        tos_agreed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        try:
            data  = json.loads(_env_get("DISCOURSE", "{}"))
            sites = data.get("sites", []) if isinstance(data, dict) else []
            for s in sites:
                if "crossai.dev" in s.get("url", ""):
                    s["tos_version"]     = manifest_tos
                    s["privacy_version"] = manifest_priv
                    s["tos_agreed_at"]   = tos_agreed_at
            _env_set("DISCOURSE", json.dumps({"sites": sites}))
            print(f"  ✓  TOS version updated to {manifest_tos} in ~/.crossenv\n")
        except Exception:
            pass
        return

    # ── First-time setup: full 4-step wizard ─────────────────────────────────

    # ── Step 1: Display and accept T&C ────────────────────────────────────
    print("  Step 1/4 — Terms of Service\n")
    accepted = display_terms_and_conditions(versions=versions)
    if not accepted:
        print("\n  ⚠️  You must accept the Terms of Service to join.")
        print("  Run st-admin --discourse-setup at any time to try again.\n")
        return

    print("  ✅  Terms accepted.\n")

    # ── Step 2: Create account via invite link ────────────────────────────
    print("  Step 2/4 — Create your crossai.dev account\n")

    # Try to get a pre-approved invite link from the server.
    # If the server is unreachable (e.g. dev/offline), fall back to /signup.
    signup_url = "https://crossai.dev/signup"
    invite_url = None
    try:
        invite_url = get_invite_link()
    except Exception as exc:
        print(f"  ⚠️  Could not generate invite link: {exc}")
        print(f"  Falling back to the public signup page.\n")

    open_url = invite_url or signup_url

    # ── Important: use a private/incognito window ─────────────────────────
    print(
        "  ⚠️  IMPORTANT: Open the link below in a private / incognito window.\n"
        "  (Chrome/Edge: Ctrl+Shift+N  •  Firefox: Ctrl+Shift+P  •  Safari: ⌘+Shift+N)\n"
        "  Using a private window prevents conflicts with any existing browser session.\n"
    )

    if invite_url:
        print(
            "  Your personal invite link (single-use, expires in 7 days):\n"
            f"\n"
            f"  {invite_url}\n"
            f"\n"
            "  Copy the link above and paste it into your private window.\n"
        )
    else:
        print(f"  Opening signup page: {open_url}\n")

    try:
        webbrowser.open(open_url)
    except Exception:
        print("  (Could not open browser — copy the link above and open it manually)")

    print(
        "  After registering you will receive an activation email.\n"
        "  Open that email link in the same private window to activate your account.\n"
        "  Once activated you can log in and come back here.\n"
    )

    try:
        input("  Press Enter once you have registered AND activated your account…")
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled. Run st-admin --discourse-setup to resume.\n")
        return

    # ── Step 3: Collect username ───────────────────────────────────────────
    print("\n  Step 3/4 — Enter your Discourse username\n")
    try:
        username = input("  Discourse username: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled. Run st-admin --discourse-setup to resume.\n")
        return

    if not username:
        print("  ✗  No username entered. Run st-admin --discourse-setup to try again.\n")
        return

    # ── Step 4: Provision account ──────────────────────────────────────────
    print(f"\n  Step 4/4 — Provisioning your account…")
    try:
        creds = discourse_onboard(
            username,
            tos_version=manifest_tos,
            privacy_version=manifest_priv,
            client_info=_build_client_info(),
        )
    except ValueError as exc:
        print(f"\n  ✗  {exc}\n")
        print("  Make sure your Discourse account exists and email is verified.")
        print("  Then run st-admin --discourse-setup to try again.\n")
        return
    except PermissionError as exc:
        print(f"\n  ✗  {exc}\n")
        return
    except Exception as exc:
        print(f"\n  ✗  Could not reach the provisioning server: {exc}\n")
        print("  Check your internet connection and try st-admin --discourse-setup later.\n")
        return

    tos_agreed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    write_discourse_env(
        creds,
        tos_version=manifest_tos,
        privacy_version=manifest_priv,
        tos_agreed_at=tos_agreed_at,
    )
    print(
        f"\n  ✅  Your Discourse account is configured. You're ready to use st-post.\n"
        f"\n  Community:  {creds['discourse_url']}"
        f"\n  Username:   {creds['discourse_username']}"
        f"\n  Category:   {creds['discourse_private_category_slug']}"
        f"\n"
    )


def check_tos_flag() -> None:
    """
    Check TOS acceptance status for the configured crossai.dev account.

    Compares the TOS version stored in the DISCOURSE site JSON against the
    manifest bundled with the installed cross-st package.

    - If up to date: prints ✅ and exits.
    - If stale (or no version recorded): displays current T&C, prompts
      acceptance, records it via /api/record-tos-acceptance, and updates
      the stored version in ~/.crossenv.

    Called by: st-admin --check-tos
    """
    from cross_st.discourse_provision import (
        get_tos_versions,
        display_terms_and_conditions,
        record_tos_acceptance,
    )
    import json
    from datetime import datetime, timezone

    versions      = get_tos_versions()
    manifest_tos  = versions.get("tos_version", "")
    manifest_priv = versions.get("privacy_version", "")

    # ── Find crossai.dev site in DISCOURSE JSON ───────────────────────────────
    disc_json = _env_get("DISCOURSE", "")
    if not disc_json:
        print("\n  No Discourse configuration found.")
        print("  Run:  st-admin --discourse-setup  to join crossai.dev.\n")
        return

    site  = None
    sites = []
    try:
        data  = json.loads(disc_json)
        sites = data.get("sites", []) if isinstance(data, dict) else []
        site  = next(
            (s for s in sites if "crossai.dev" in s.get("url", "")), None
        )
    except Exception:
        pass

    if not site:
        print("\n  No crossai.dev configuration found in your DISCOURSE settings.")
        print("  Run:  st-admin --discourse-setup  to join crossai.dev.\n")
        return

    username    = site.get("username", "")
    stored_tos  = site.get("tos_version",  "")
    stored_priv = site.get("privacy_version", "")

    # ── Already up to date? ───────────────────────────────────────────────────
    if (stored_tos and manifest_tos and stored_tos >= manifest_tos and
            stored_priv and stored_priv >= manifest_priv):
        print(
            f"\n  ✅  Terms of Service accepted (version {stored_tos}). "
            f"No action needed.\n"
        )
        return

    # ── Stale or not yet recorded → prompt re-acceptance ─────────────────────
    if stored_tos:
        print(
            f"\n  ⚠️  Terms of Service have been updated.\n"
            f"  Previous version: {stored_tos}  →  Current: {manifest_tos}\n"
        )
    else:
        print(f"\n  ℹ️  No stored Terms version found. Displaying current T&C.\n")

    accepted = display_terms_and_conditions(versions=versions)
    if not accepted:
        print("\n  ⚠️  You must accept the Terms of Service.")
        print("  Run st-admin --check-tos at any time to review and accept.\n")
        return

    print("  ✅  Terms accepted.\n")

    # Record server-side (non-fatal)
    if username:
        ok = record_tos_acceptance(
            username,
            tos_version=manifest_tos,
            privacy_version=manifest_priv,
            method="cli_reaccept",
            client_info=_build_client_info(),
        )
        if ok:
            print(f"  ✓  Acceptance recorded for {username}\n")

    # Update stored version in DISCOURSE JSON
    tos_agreed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    try:
        data  = json.loads(_env_get("DISCOURSE", "{}"))
        sites = data.get("sites", []) if isinstance(data, dict) else []
        for s in sites:
            if "crossai.dev" in s.get("url", ""):
                s["tos_version"]     = manifest_tos
                s["privacy_version"] = manifest_priv
                s["tos_agreed_at"]   = tos_agreed_at
        _env_set("DISCOURSE", json.dumps({"sites": sites}))
        print(f"  ✓  TOS version updated to {manifest_tos} in {_TARGET_ENV}\n")
    except Exception:
        pass


def _get_active_discourse_slug() -> str:
    """Return the slug of the currently-active Discourse site, or "" if none.

    Used by the interactive menu to render a live label such as
    "Site manager  (crossai.dev)" so the user always sees which site they
    are about to edit.  Falls back to the first site if DISCOURSE_SITE is
    unset; returns "" if no DISCOURSE config exists at all.
    """
    import json
    raw = _env_get("DISCOURSE", "")
    if not raw:
        return ""
    try:
        data  = json.loads(raw)
        sites = data.get("sites", data) if isinstance(data, dict) else data
        if not sites:
            return ""
        active = _env_get("DISCOURSE_SITE", "")
        if active:
            for s in sites:
                if s.get("slug") == active:
                    return active
        return sites[0].get("slug", "") or ""
    except (ValueError, AttributeError, TypeError):
        return ""


def _fetch_discourse_categories(url: str, api_key: str, username: str) -> list:
    """Fetch the list of categories visible to ``username`` on the Discourse
    site at ``url``.

    Returns a list of dicts ``[{"id": int, "name": str, "slug": str,
    "parent_id": int|None}, ...]`` sorted with parent categories first,
    each followed by its subcategories.  Returns ``[]`` on any error
    (network failure, 403, malformed JSON) — the caller is expected to
    fall back to manual ID entry.

    Uses ``/site.json`` which returns every category the API user can see
    in a single request, including subcategories.
    """
    try:
        import requests  # type: ignore
    except ImportError:
        return []
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Api-Key"]      = api_key
        headers["Api-Username"] = username or "system"
    try:
        r = requests.get(f"{url.rstrip('/')}/site.json", headers=headers, timeout=10)
        if r.status_code != 200:
            return []
        cats = r.json().get("categories", [])
    except Exception:
        return []
    if not isinstance(cats, list):
        return []
    # Build parent-first, subcategory-after ordering
    by_parent: dict = {}
    for c in cats:
        by_parent.setdefault(c.get("parent_category_id"), []).append(c)
    ordered: list = []
    for top in sorted(by_parent.get(None, []), key=lambda c: c.get("position", 0)):
        ordered.append({
            "id":        top.get("id"),
            "name":      top.get("name", ""),
            "slug":      top.get("slug", ""),
            "parent_id": None,
        })
        for sub in sorted(by_parent.get(top.get("id"), []),
                          key=lambda c: c.get("position", 0)):
            ordered.append({
                "id":        sub.get("id"),
                "name":      sub.get("name", ""),
                "slug":      sub.get("slug", ""),
                "parent_id": top.get("id"),
            })
    return ordered


def _pick_discourse_category(url: str, api_key: str, username: str) -> int:
    """Interactive category picker for the Add-a-site flow.

    Tries to fetch the visible categories from the Discourse site; if that
    succeeds, presents a numbered list and lets the user pick by index.
    If the fetch fails (no API key, network error, 403) it falls back to
    asking for a numeric category ID directly.

    Returns the selected category ID as an int (defaults to 1 if the
    user enters nothing in the manual fallback).
    """
    cats = _fetch_discourse_categories(url, api_key, username)
    if not cats:
        print("  (could not fetch categories from site — enter ID manually)")
        cat_raw = input("  Default posting category ID [1]: ").strip() or "1"
        return int(cat_raw) if cat_raw.lstrip("-").isdigit() else 1

    print()
    print(f"  Categories visible to {username or 'this API key'}:")
    for i, c in enumerate(cats, 1):
        indent = "    " if c["parent_id"] else "  "
        print(f"  {i:>3}. {indent}{c['name']}  (id={c['id']})")
    print()
    while True:
        try:
            raw = input(
                f"  Default posting category — pick 1-{len(cats)}, "
                f"or enter a numeric ID directly [1]: "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            return 1
        if not raw:
            return cats[0]["id"]
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(cats):
                return cats[n - 1]["id"]
            # Numeric value outside menu range — treat as a raw category ID
            return n
        print(f"  ✗  Invalid choice — enter 1-{len(cats)} or a category ID.")


def _discourse_manage_sites() -> None:
    """Add or delete a Discourse site stored in the DISCOURSE JSON.

    Shows the list of currently-configured sites with a (current) marker,
    then offers two actions:

      a — Add a new site:  prompts for slug, URL, username, API key and
                           default category ID.  Writes the new site dict
                           to the DISCOURSE JSON in ~/.crossenv.  If this
                           is the first site, also sets it as the default
                           (DISCOURSE_SITE).
      d — Delete a site:   prompts for the site index, removes it after
                           confirmation, and repoints DISCOURSE_SITE if
                           the deleted site was the active one.

    Called from interactive_menu() by pressing m in the Discourse submenu.
    Use the s key (Site manager) to change category / username on an
    existing site instead.
    """
    import json
    from mmd_single_key import get_single_key

    disc_json_str = _env_get("DISCOURSE", "")
    sites: list = []
    if disc_json_str.strip():
        try:
            data  = json.loads(disc_json_str)
            sites = data.get("sites", data) if isinstance(data, dict) else data
            if not isinstance(sites, list):
                sites = []
        except (ValueError, AttributeError):
            print("\n  ✗  DISCOURSE JSON in ~/.crossenv is malformed.")
            print("  Run:  st-admin --discourse-setup  to reconfigure.\n")
            return

    active_slug = _env_get("DISCOURSE_SITE", "")
    if not active_slug and sites:
        active_slug = sites[0].get("slug", "")

    # ── Display ──────────────────────────────────────────────────────────
    print(f"\n  Discourse Sites")
    print(f"  {'─' * 40}")
    if sites:
        for i, s in enumerate(sites, 1):
            slug   = s.get("slug", "?")
            url    = s.get("url",  "")
            user   = s.get("username", "")
            marker = "  (current)" if slug == active_slug else ""
            print(f"    {i}.  {slug}  ({url})  user: {user}{marker}")
    else:
        print("    (none configured)")
    print()
    print("  a: Add a new site")
    if sites:
        print("  d: Delete a site")
    print("  esc: Go back")
    print()

    print(f"  Choice> ", end="", flush=True)
    try:
        choice = get_single_key()
        print(choice)
    except (KeyboardInterrupt, EOFError):
        print()
        return

    # ── Add ──────────────────────────────────────────────────────────────
    if choice in ("a", "A"):
        try:
            slug = input("  Site slug (short name, e.g. crossai.dev): ").strip()
            if not slug:
                print("  Cancelled.\n")
                return
            if any(s.get("slug") == slug for s in sites):
                print(f"  ✗  A site with slug {slug!r} already exists.\n")
                return
            url = input("  Site URL (e.g. https://crossai.dev): ").strip()
            if not url:
                print("  Cancelled.\n")
                return
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            user = input("  Username on this site: ").strip()
            api  = input("  API key (leave blank to add later): ").strip()
            cat_id = _pick_discourse_category(url, api, user)
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.\n")
            return

        sites.append({
            "slug":        slug,
            "url":         url.rstrip("/"),
            "username":    user,
            "api_key":     api,
            "category_id": cat_id,
        })
        _env_set("DISCOURSE", json.dumps({"sites": sites}))
        print(f"\n  ✓  Added site: {slug}  ({url})")
        if len(sites) == 1:
            _env_set("DISCOURSE_SITE", slug)
            print(f"  ✓  Set as default site (DISCOURSE_SITE={slug}).")
        else:
            print(f"  Use 'd' in the Discourse menu to make it the default.")
        print()
        return

    # ── Delete ───────────────────────────────────────────────────────────
    if choice in ("d", "D"):
        if not sites:
            print("  No sites to delete.\n")
            return
        try:
            raw = input(
                f"  Index of site to delete (1-{len(sites)}, blank to cancel): "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.\n")
            return
        if not raw:
            print("  Cancelled.\n")
            return
        if not raw.isdigit() or not (1 <= int(raw) <= len(sites)):
            print(f"  ✗  Invalid index — must be 1..{len(sites)}.\n")
            return
        idx = int(raw) - 1
        victim = sites[idx]
        try:
            confirm = input(
                f"  Really delete site {victim.get('slug', '?')!r} "
                f"({victim.get('url', '')})? [y/N]: "
            ).strip().lower()
        except (KeyboardInterrupt, EOFError):
            confirm = "n"
        if confirm != "y":
            print("  Cancelled.\n")
            return
        deleted_slug = victim.get("slug", "")
        sites.pop(idx)
        _env_set("DISCOURSE", json.dumps({"sites": sites}))
        # Repoint DISCOURSE_SITE if we just deleted the active site
        if deleted_slug and deleted_slug == active_slug:
            new_active = sites[0].get("slug", "") if sites else ""
            _env_set("DISCOURSE_SITE", new_active)
            if new_active:
                print(
                    f"\n  ✓  Deleted {deleted_slug}.  "
                    f"Active site is now: {new_active}\n"
                )
            else:
                print(
                    f"\n  ✓  Deleted {deleted_slug}.  No sites remain — "
                    f"re-run st-admin --discourse-setup to add one.\n"
                )
        else:
            print(f"\n  ✓  Deleted {deleted_slug}.\n")
        return

    if choice in ("ESC", "q", "RETURN", ""):
        return

    print(f"  ✗  Invalid choice: {choice!r}\n")


def discourse_manage() -> None:
    """
    Interactive Discourse site manager.

    Shows the current Discourse configuration and lets the user switch the
    default posting category between three named destinations:

      1. Private    (@username-private)  — visible only to you
      2. Test       (cleared daily)      — safe sandbox, cleared every night
      3. Reports    (📄 Reports, id=16)  — public portfolio on crossai.dev
         Portfolio URL: crossai.dev/u/<username>/activity/topics

    Also accepts a custom category ID for other Discourse sites.

    On first run: if flat DISCOURSE_* keys (written by --discourse-setup) exist
    but no DISCOURSE JSON is present, automatically builds and writes the JSON so
    that st-post can work immediately.

    Called by:  st-admin --discourse
    """
    import json

    _SEP = "─" * 40

    # ── Read current state ────────────────────────────────────────────────────
    disc_url       = _env_get("DISCOURSE_URL", "")
    disc_user      = _env_get("DISCOURSE_USERNAME", "")
    disc_api_key   = _env_get("DISCOURSE_API_KEY", "")
    disc_cat_id    = _env_get("DISCOURSE_CATEGORY_ID", "")
    disc_priv_slug = _env_get("DISCOURSE_PRIVATE_CATEGORY_SLUG", "")
    disc_json_str  = _env_get("DISCOURSE", "")
    disc_site_key  = _env_get("DISCOURSE_SITE", "")

    have_flat = bool(disc_url and disc_user)
    have_json = bool(disc_json_str.strip())

    # ── No config at all ─────────────────────────────────────────────────────
    if not have_flat and not have_json:
        print("\n  No Discourse configuration found.")
        print("  Run:  st-admin --discourse-setup  to join crossai.dev.\n")
        return

    # ── First-run migration: flat keys → DISCOURSE JSON ──────────────────────
    if have_flat and not have_json:
        slug = disc_url.replace("https://", "").replace("http://", "").rstrip("/")
        cat_id_int = int(disc_cat_id) if disc_cat_id.strip().isdigit() else 1
        disc_json_str = json.dumps({"sites": [{
            "slug":                  slug,
            "url":                   disc_url,
            "username":              disc_user,
            "api_key":               disc_api_key,
            "category_id":           cat_id_int,
            "private_category_id":   cat_id_int,
            "private_category_slug": disc_priv_slug,
        }]})
        _env_set("DISCOURSE", disc_json_str)
        if not disc_site_key:
            _env_set("DISCOURSE_SITE", slug)
            disc_site_key = slug
        print("\n  ✓  Discourse configuration initialised from onboarding keys.")
        have_json = True

    # ── Parse DISCOURSE JSON ──────────────────────────────────────────────────
    try:
        data  = json.loads(disc_json_str)
        sites = data.get("sites", data) if isinstance(data, dict) else data
        site  = sites[0] if sites else {}
    except (ValueError, IndexError, AttributeError):
        print("\n  ✗  DISCOURSE JSON in ~/.crossenv is malformed.")
        print("  Run:  st-admin --discourse-setup  to reconfigure.\n")
        return

    # Honour DISCOURSE_SITE for the active site
    if disc_site_key:
        match = next((s for s in sites if s.get("slug") == disc_site_key), None)
        if match:
            site = match

    active_cat_id = site.get("category_id")
    site_url      = site.get("url",      disc_url  or "?")
    username      = site.get("username", disc_user or "?")
    site_slug     = site.get("slug",     disc_site_key or "?")

    # Private category info lives in the site dict (new schema).
    # Fall back to flat keys for configs that predate the migration.
    private_id   = site.get("private_category_id")
    if private_id is None and disc_cat_id.strip().isdigit():
        private_id = int(disc_cat_id)
    priv_slug = site.get("private_category_slug") or disc_priv_slug or ""

    def _cat_label(cat_id, priv_id, p_slug) -> str:
        if cat_id == _DISCOURSE_TEST_CATEGORY_ID:
            return f"{_DISCOURSE_TEST_CATEGORY_NAME}  [id={cat_id}]"
        if cat_id == _DISCOURSE_REPORTS_CATEGORY_ID:
            return f"{_DISCOURSE_REPORTS_CATEGORY_NAME}  [id={cat_id}]"
        if cat_id == _DISCOURSE_PROMPT_LAB_CATEGORY_ID:
            return f"{_DISCOURSE_PROMPT_LAB_CATEGORY_NAME}  [id={cat_id}]"
        if priv_id and cat_id == priv_id:
            return f"{p_slug or 'your-private'}  [id={cat_id}]"
        return f"[id={cat_id}]"

    active_label  = _cat_label(active_cat_id, private_id, priv_slug)
    private_label = (f"{priv_slug}  [id={private_id}]"
                     if priv_slug and private_id else "(not configured)")

    # ── Display ───────────────────────────────────────────────────────────────
    W = 28
    print(f"\n  Discourse Site Management")
    print(f"  {_SEP}")
    if len(sites) > 1:
        all_slugs = ", ".join(
            f"[{s['slug']}]" if s.get("slug") == site_slug else s["slug"]
            for s in sites
        )
        print(f"  {'Sites':<{W}}  {all_slugs}")
        print(f"  {'Active site':<{W}}  {site_slug}")
    print(f"  {'Site URL':<{W}}  {site_url}")
    print(f"  {'Username':<{W}}  {username}")
    print(f"  {'Default posting category':<{W}}  {active_label}")
    print(f"  {'Private category':<{W}}  {private_label}")
    portfolio_url = f"{site_url.rstrip('/')}/u/{username}/activity/topics"
    print(f"  {'Public portfolio':<{W}}  {portfolio_url}")
    print()

    # ── Category picker ───────────────────────────────────────────────────────
    from mmd_single_key import get_single_key

    print("  Change default posting category?")
    if private_id:
        print(f"    1.  {priv_slug or 'your-private'}  (your private category)")
    print(f"    2.  {_DISCOURSE_TEST_CATEGORY_NAME}  — cleared daily, safe for testing")
    print(f"    3.  {_DISCOURSE_REPORTS_CATEGORY_NAME}  — your public portfolio")
    print(f"    4.  {_DISCOURSE_PROMPT_LAB_CATEGORY_NAME}  — share prompts and get community feedback")
    print(f"    5.  Enter a category ID manually")
    print(f"    u.  Change username for this site  (currently: {username})")
    print(f"\n  esc: Escape back to the previous menu")
    print()

    print(f"  Choice> ", end="", flush=True)
    try:
        choice = get_single_key()
        print(choice)
    except (KeyboardInterrupt, EOFError):
        print()
        return

    new_cat_id    = None
    new_cat_label = ""

    if choice in ("ESC", "q", "RETURN", ""):
        return
    elif choice in ("u", "U"):
        # ── Change username for the active site ───────────────────────────────
        # Useful when the user has more than one Discourse account on the same
        # site (e.g. personal + work) and wants to switch between them.
        try:
            new_user = input(
                f"  New username (current: {username}, blank to cancel): "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return
        if not new_user:
            print("  Cancelled.\n")
            return
        if new_user == username:
            print("  ✓  Username unchanged.\n")
            return
        site["username"] = new_user
        # Recompute the auto-generated <username>-private slug if applicable.
        old_priv_slug = site.get("private_category_slug", "")
        if old_priv_slug == f"{username}-private":
            site["private_category_slug"] = f"{new_user}-private"
        _env_set("DISCOURSE", json.dumps({"sites": sites}))
        # Keep the legacy flat key in sync for tools that still read it.
        if _env_get("DISCOURSE_USERNAME", ""):
            _env_set("DISCOURSE_USERNAME", new_user)
        print(
            f"\n  ✓  Username for {site_slug} changed: "
            f"{username} → {new_user}\n"
        )
        new_portfolio = (
            f"{site_url.rstrip('/')}/u/{new_user}/activity/topics"
        )
        print(f"     Public portfolio: {new_portfolio}\n")
        return
    elif choice == "1" and private_id:
        new_cat_id    = private_id
        new_cat_label = f"{priv_slug or 'your-private'}  [id={new_cat_id}]"
    elif choice == "2":
        new_cat_id    = _DISCOURSE_TEST_CATEGORY_ID
        new_cat_label = f"{_DISCOURSE_TEST_CATEGORY_NAME}  [id={new_cat_id}]"
    elif choice == "3":
        new_cat_id    = _DISCOURSE_REPORTS_CATEGORY_ID
        new_cat_label = f"{_DISCOURSE_REPORTS_CATEGORY_NAME}  [id={new_cat_id}]"
        print(f"\n  Your public portfolio: {portfolio_url}")
    elif choice == "4":
        new_cat_id    = _DISCOURSE_PROMPT_LAB_CATEGORY_ID
        new_cat_label = f"{_DISCOURSE_PROMPT_LAB_CATEGORY_NAME}  [id={new_cat_id}]"
    elif choice == "5":
        try:
            raw = input("  Category ID: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return
        if not raw.isdigit() or int(raw) <= 0:
            print("  ✗  Invalid ID — must be a positive integer.\n")
            return
        new_cat_id    = int(raw)
        new_cat_label = f"[id={new_cat_id}]"
    else:
        print("  ✗  Invalid choice.\n")
        return

    if new_cat_id is None:
        return

    # ── Mutate category_id in DISCOURSE JSON and persist ─────────────────────
    site["category_id"] = new_cat_id
    _env_set("DISCOURSE", json.dumps({"sites": sites}))
    print(f"\n  ✓  Default category set to: {new_cat_label}\n")


def _discourse_select_site() -> None:
    """
    Select the default Discourse site from the interactive menu.

    Shows the list of configured sites, lets the user pick one, and writes
    the choice to DISCOURSE_SITE in ~/.crossenv so that st-post / st use it
    as the startup default.

    Called from interactive_menu() by pressing D.
    """
    import json
    from mmd_single_key import get_single_key

    disc_json_str = _env_get("DISCOURSE", "")
    if not disc_json_str:
        print("\n  No Discourse configuration found.")
        print("  Run:  st-admin --discourse-setup  to join crossai.dev.\n")
        return

    try:
        data  = json.loads(disc_json_str)
        sites = data.get("sites", data) if isinstance(data, dict) else data
    except (ValueError, AttributeError):
        print("\n  ✗  DISCOURSE JSON is malformed.\n")
        return

    if not sites:
        print("\n  No sites configured.\n")
        return

    if len(sites) == 1:
        slug = sites[0].get("slug", "?")
        print(f"\n  Only one Discourse site configured: {slug}")
        print("  Nothing to switch.\n")
        return

    current = _env_get("DISCOURSE_SITE", sites[0].get("slug", ""))
    print(f"\n  Configured Discourse sites:")
    for i, s in enumerate(sites, 1):
        slug   = s.get("slug", "?")
        url    = s.get("url",  "")
        marker = "  (current)" if slug == current else ""
        print(f"    {i}.  {slug}  ({url}){marker}")
    print(f"\n  esc: Go back")

    print(f"\n  Site> ", end="", flush=True)
    choice = get_single_key()
    print(choice)

    if choice in ("ESC", "q", "RETURN"):
        return
    if choice.isdigit() and 1 <= int(choice) <= len(sites):
        idx      = int(choice) - 1
        new_slug = sites[idx].get("slug", "")
        _env_set("DISCOURSE_SITE", new_slug)
        print(f"\n  ✓  Default site set to: {new_slug}\n")
    else:
        print("  ✗  Invalid choice.\n")


def _discourse_select_category() -> None:
    """
    Quick default-category picker for the interactive menu (c key).

    Always offers three named options:
      1. Private    (@username-private)  — visible only to you
      2. Test       (cleared daily)      — safe sandbox, cleared every night
      3. Reports    (📄 Reports, id=16)  — public portfolio on crossai.dev
         Portfolio: crossai.dev/u/<username>/activity/topics

    The currently active option is labelled  (current).
    Writes category_id into the active site's DISCOURSE JSON in ~/.crossenv.

    Called from interactive_menu() by pressing c.
    """
    import json
    from mmd_single_key import get_single_key

    disc_json_str = _env_get("DISCOURSE", "")
    if not disc_json_str:
        print("\n  No Discourse configuration found.")
        print("  Run:  st-admin --discourse-setup  to join crossai.dev.\n")
        return

    try:
        data  = json.loads(disc_json_str)
        sites = data.get("sites", data) if isinstance(data, dict) else data
        site  = sites[0] if sites else {}
    except (ValueError, IndexError, AttributeError):
        print("\n  ✗  DISCOURSE JSON is malformed.\n")
        return

    # Honour DISCOURSE_SITE for the active site
    disc_site_key = _env_get("DISCOURSE_SITE", "")
    if disc_site_key:
        match = next((s for s in sites if s.get("slug") == disc_site_key), None)
        if match:
            site = match

    active_cat_id = site.get("category_id")
    # private_category_id may be absent for older configs — fall back to category_id
    private_id = site.get("private_category_id") or active_cat_id
    # Build the private label: slug > username-private > "your-private"
    priv_slug = (site.get("private_category_slug")
                 or (site.get("username", "") + "-private" if site.get("username") else "")
                 or "your-private")

    def _current(cat_id) -> str:
        return "  (current)" if cat_id == active_cat_id else ""

    username = site.get("username", "")
    site_url = site.get("url", "").rstrip("/")
    portfolio_url = f"{site_url}/u/{username}/activity/topics" if username else ""

    print(f"\n  Select default posting category:")
    print(f"    1.  {priv_slug}  (your private category){_current(private_id)}")
    print(f"    2.  {_DISCOURSE_TEST_CATEGORY_NAME}  "
          f"— cleared daily, safe for testing{_current(_DISCOURSE_TEST_CATEGORY_ID)}")
    print(f"    3.  {_DISCOURSE_REPORTS_CATEGORY_NAME}  "
          f"— your public portfolio{_current(_DISCOURSE_REPORTS_CATEGORY_ID)}")
    if portfolio_url:
        print(f"         {portfolio_url}")
    print(f"    4.  {_DISCOURSE_PROMPT_LAB_CATEGORY_NAME}  "
          f"— share prompts, get community feedback{_current(_DISCOURSE_PROMPT_LAB_CATEGORY_ID)}")
    print(f"\n  esc: Go back")

    print(f"\n  Category> ", end="", flush=True)
    choice = get_single_key()
    print(choice)

    if choice in ("ESC", "q", "RETURN"):
        return
    elif choice == "1":
        new_cat_id    = private_id
        new_cat_label = f"{priv_slug}  [id={new_cat_id}]"
    elif choice == "2":
        new_cat_id    = _DISCOURSE_TEST_CATEGORY_ID
        new_cat_label = f"{_DISCOURSE_TEST_CATEGORY_NAME}  [id={new_cat_id}]"
    elif choice == "3":
        new_cat_id    = _DISCOURSE_REPORTS_CATEGORY_ID
        new_cat_label = f"{_DISCOURSE_REPORTS_CATEGORY_NAME}  [id={new_cat_id}]"
    elif choice == "4":
        new_cat_id    = _DISCOURSE_PROMPT_LAB_CATEGORY_ID
        new_cat_label = f"{_DISCOURSE_PROMPT_LAB_CATEGORY_NAME}  [id={new_cat_id}]"
    else:
        print("  ✗  Invalid choice.\n")
        return

    site["category_id"] = new_cat_id
    _env_set("DISCOURSE", json.dumps({"sites": sites}))
    print(f"\n  ✓  Default category set to: {new_cat_label}\n")


def setup_wizard() -> None:
    """
    Interactive first-run setup wizard.

    Detects the OS and currently installed tools, shows a checklist,
    then guides the user through API key entry and writes ~/.crossenv.
    """
    import json
    import platform

    _W   = 58
    _SEP = "─" * _W

    def _row(icon: str, label: str, detail: str = "", hint: str = "") -> None:
        """Print one checklist row with consistent alignment."""
        # ✅ ❌ are single wide chars; ⚠️ renders wide in most terminals — treat all as 2-wide
        line = f"  {icon}  {label:<22}"
        if detail:
            line += f"  {detail}"
        if hint:
            line += f"  ({hint})"
        print(line)

    def _ver(raw: str, stop_at: str = "") -> str:
        """Trim a verbose version string down to just the version number/line."""
        s = raw.strip()
        if stop_at and stop_at in s:
            s = s[:s.index(stop_at)].strip()
        return (s[:46] + "…") if len(s) > 46 else s

    # ── Detect OS ─────────────────────────────────────────────────────────────
    system  = platform.system()   # Darwin | Linux | Windows
    machine = platform.machine()  # arm64 | x86_64

    if system == "Darwin":
        mac_ver = platform.mac_ver()[0]
        arch    = "Apple Silicon" if machine == "arm64" else "Intel"
        os_label = f"macOS {mac_ver} ({arch})"
        is_mac, is_linux = True, False
    elif system == "Linux":
        try:
            with open("/etc/os-release") as _f:
                _d = {k: v.strip('"') for k, _, v in
                      (line.partition("=") for line in _f if "=" in line)}
            os_label = _d.get("PRETTY_NAME", f"Linux ({machine})")
        except Exception:
            os_label = f"Linux ({machine})"
        is_mac, is_linux = False, True
    else:
        os_label = f"{system} ({machine})"
        is_mac, is_linux = False, False

    # ── Python ────────────────────────────────────────────────────────────────
    pv     = sys.version_info
    py_str = f"Python {pv.major}.{pv.minor}.{pv.micro}"
    py_ok  = pv >= (3, 10)

    # ── Tool probes ───────────────────────────────────────────────────────────
    brew_ok,   brew_ver   = (False, "") if not is_mac else _tool_check("brew")
    pipx_ok,   pipx_ver   = _tool_check("pipx")
    ffmpeg_ok, ffmpeg_ver = _tool_check("ffmpeg", "-version")
    aspell_ok, aspell_ver = _tool_check("aspell")
    grip_ok,   grip_ver   = _tool_check("grip")

    # Linux: check libsndfile (soundfile wheel doesn't bundle it on Linux)
    libsndfile_ok, libsndfile_ver = True, ""   # non-issue on macOS
    if is_linux:
        try:
            import soundfile as _sf
            libsndfile_ok  = True
            libsndfile_ver = f"libsndfile {_sf.__libsndfile_version__}"
        except (ImportError, AttributeError):
            r = subprocess.run("ldconfig -p", shell=True,
                               capture_output=True, text=True)
            libsndfile_ok  = "libsndfile" in r.stdout
            libsndfile_ver = "found" if libsndfile_ok else ""

    # TTS Python packages
    try:
        import soundfile as _sf
        tts_ok  = True
        tts_ver = f"soundfile {_sf.__version__}"
    except ImportError:
        tts_ok, tts_ver = False, ""
        _sf = None  # noqa: F841

    crossenv_exists = os.path.exists(_CROSSENV)
    target_exists   = os.path.exists(_TARGET_ENV)

    # ── Print checklist ───────────────────────────────────────────────────────
    print(f"\n  Cross Setup Wizard")
    print(f"  {_SEP}")

    print(f"\n  System\n  {'·' * (_W - 2)}")
    _row("✅", "OS", os_label)
    if py_ok:
        _row("✅", py_str)
    else:
        _row("❌", py_str, hint="3.10+ required")

    if is_mac:
        if brew_ok:
            _row("✅", "Homebrew", _ver(brew_ver))
        else:
            _row("❌", "Homebrew", "not found", "required on macOS")

    if pipx_ok:
        _row("✅", "pipx", _ver(pipx_ver))
    else:
        _row("⚠️", "pipx", "not found", "recommended for user installs")

    print(f"\n  Tools\n  {'·' * (_W - 2)}")
    if ffmpeg_ok:
        _row("✅", "ffmpeg", _ver(ffmpeg_ver, "Copyright"))
    else:
        _row("⚠️", "ffmpeg", "not found", "optional: TTS audio encoding")

    if aspell_ok:
        _row("✅", "aspell", _ver(aspell_ver, "(but"))
    else:
        _row("⚠️", "aspell", "not found", "optional: spell check in st-new")

    if grip_ok:
        _row("✅", "grip", _ver(grip_ver))
    else:
        _row("⚠️", "grip", "not found", "optional: browser preview in st-edit")

    if is_linux:
        if libsndfile_ok:
            _row("✅", "libsndfile", libsndfile_ver or "installed")
        else:
            _row("❌", "libsndfile", "not found", "required for TTS on Linux")

    print(f"\n  Cross\n  {'·' * (_W - 2)}")
    if tts_ok:
        _row("✅", "TTS packages", tts_ver)
    else:
        _row("⚠️", "TTS packages", "not installed", "optional: st-speak, st-voice")

    if target_exists:
        _row("✅", _TARGET_ENV, "exists — will update")
    else:
        _row("⚠️", _TARGET_ENV, "will be created")
    if _DEV_MODE and crossenv_exists and os.path.realpath(_CROSSENV) != os.path.realpath(_TARGET_ENV):
        _row("ℹ️", _CROSSENV, "exists (global) — dev mode writes to project .env instead")

    # ── Install hints for missing items ───────────────────────────────────────
    critical = []
    optional_hints = []

    if not py_ok:
        if is_mac:
            critical.append(("Python 3.10+ required",
                              "brew install python@3.11"))
        else:
            critical.append(("Python 3.10+ required",
                              "sudo apt install python3.11  "
                              "# Debian/Ubuntu\n"
                              "      sudo dnf install python3.11  "
                              "# Fedora/RHEL"))

    if is_mac and not brew_ok:
        critical.append(("Homebrew required on macOS",
                          '/bin/bash -c "$(curl -fsSL '
                          'https://raw.githubusercontent.com/Homebrew/install/'
                          'HEAD/install.sh)"'))

    if is_linux and not libsndfile_ok:
        optional_hints.append(("libsndfile (required for TTS audio on Linux)",
                                "sudo apt install libsndfile1  "
                                "# Debian/Ubuntu\n"
                                "      sudo dnf install libsndfile  "
                                "# Fedora/RHEL"))

    if not ffmpeg_ok:
        cmd = "brew install ffmpeg" if is_mac else "sudo apt install ffmpeg"
        optional_hints.append(("ffmpeg (TTS audio encoding)", cmd))

    if not aspell_ok:
        cmd = "brew install aspell" if is_mac else "sudo apt install aspell"
        optional_hints.append(("aspell (spell check in st-new)", cmd))

    if not grip_ok:
        grip_cmd = 'pipx inject cross-st grip' if using_pipx else 'pip install grip'
        optional_hints.append(("grip (browser preview in st-edit — auto-installs on first use)", grip_cmd))

    if not tts_ok:
        tts_cmd = ('pipx install "cross-ai[tts]"' if pipx_ok
                   else 'pip install "cross-ai[tts]"')
        optional_hints.append(("TTS audio packages (st-speak / st-voice)",
                                tts_cmd))

    if critical or optional_hints:
        print(f"\n  {_SEP}")
        for label, cmd in critical:
            print(f"\n  ❌  {label}:")
            print(f"      {cmd}")
        if optional_hints:
            print(f"\n  To install missing optional tools:")
            for label, cmd in optional_hints:
                print(f"\n    {label}:")
                print(f"      {cmd}")

    print(f"\n  {_SEP}")

    # Bail on critical failures
    if not py_ok:
        print(f"\n  Python {pv.major}.{pv.minor} is below the 3.10 minimum.")
        print("  Upgrade Python and re-run: st-admin --setup\n")
        sys.exit(1)
    if is_mac and not brew_ok:
        print("\n  Homebrew is required on macOS.")
        print("  Install Homebrew (see above) and re-run: st-admin --setup\n")
        sys.exit(1)

    # ── Prompt to continue ────────────────────────────────────────────────────
    print(
        f"\n  Next: set up your AI provider API keys.\n"
        f"  Cross works with up to 5 providers — enter keys for the ones you have:\n"
        f"\n"
        f"    Gemini (Google)  ·  xAI (Grok)  ·  Anthropic (Claude)\n"
        f"    OpenAI (GPT)     ·  Perplexity\n"
        f"\n"
        f"  ⭐  Gemini has a free tier — no credit card needed.\n"
        f"  You need at least one key.  Keys can be added or changed later with st-admin.\n"
        f"  Your keys are stored only in:  {_TARGET_ENV}\n"
        f"  They are never uploaded or shared — sent directly to each provider only.\n"
    )
    try:
        ans = input("  Continue to API key setup? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.")
        sys.exit(0)
    if ans == "n":
        print("  Cancelled.")
        sys.exit(0)

    # ── Read existing keys (so users can keep current values) ─────────────────
    try:
        from dotenv import dotenv_values
        # Merge ~/.crossenv (layer 1) + _TARGET_ENV (layer 2 for devs) so the
        # wizard pre-fills with whichever value is actually active.
        existing = {}
        if crossenv_exists:
            existing.update(dotenv_values(_CROSSENV) or {})
        if target_exists and os.path.realpath(_TARGET_ENV) != os.path.realpath(_CROSSENV):
            existing.update(dotenv_values(_TARGET_ENV) or {})
    except Exception:
        existing = {}

    def _prompt_key(label: str, env_var: str, note: str = "") -> str:
        cur = existing.get(env_var, "").strip()
        suffix = "[Enter to keep existing]" if cur else "[Enter to skip]"
        if note:
            print(f"\n  {note}")
        try:
            val = input(f"  {label} {suffix}: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")
            sys.exit(0)
        return val if val else cur

    # ── API keys ──────────────────────────────────────────────────────────────
    print(f"\n  API Keys\n  {_SEP}")
    print("  Press Enter to skip any provider.\n")

    gemini_key     = _prompt_key("Gemini     ", "GEMINI_API_KEY",
                                 "⭐ Gemini is FREE — no credit card needed.\n"
                                 "     Get key: https://aistudio.google.com/app/apikey")
    xai_key        = _prompt_key("xAI        ", "XAI_API_KEY")
    anthropic_key  = _prompt_key("Anthropic  ", "ANTHROPIC_API_KEY")
    openai_key     = _prompt_key("OpenAI     ", "OPENAI_API_KEY")
    perplexity_key = _prompt_key("Perplexity ", "PERPLEXITY_API_KEY")

    # ── Default AI ────────────────────────────────────────────────────────────
    entered = [m for m, k in [("gemini",     gemini_key),
                               ("xai",        xai_key),
                               ("anthropic",  anthropic_key),
                               ("openai",     openai_key),
                               ("perplexity", perplexity_key)] if k]

    cur_default = existing.get("DEFAULT_AI", "")
    if not entered:
        print("\n  ⚠️  No API keys entered. Add them later with st-admin.")
        default_ai = cur_default or "gemini"
    else:
        suggestion = "gemini" if "gemini" in entered else entered[0]
        pre = cur_default if cur_default in entered else suggestion
        print(f"\n  Keys entered: {', '.join(entered)}")
        try:
            val = input(f"  Default AI provider [{pre}]: ").strip()
        except (KeyboardInterrupt, EOFError):
            val = ""
        default_ai = val if val in entered else pre


    # ── Write ~/.crossenv ─────────────────────────────────────────────────────
    print(f"\n  {_SEP}")

    def _write(var: str, val: str) -> None:
        if val:
            set_key(_TARGET_ENV, var, val)
            os.environ[var] = val

    _write("GEMINI_API_KEY",     gemini_key)
    _write("XAI_API_KEY",        xai_key)
    _write("ANTHROPIC_API_KEY",  anthropic_key)
    _write("OPENAI_API_KEY",     openai_key)
    _write("PERPLEXITY_API_KEY", perplexity_key)
    _write("DEFAULT_AI",         default_ai)

    print(f"  ✅  Settings written to {_TARGET_ENV}")

    # ── Create data directories ───────────────────────────────────────────────
    cache_dir = os.path.expanduser("~/.cross_api_cache")
    os.makedirs(cache_dir, exist_ok=True)
    print(f"  ✅  Cache directory: {cache_dir}")

    # ── Seed prompt templates ─────────────────────────────────────────────────
    if _USER_TEMPLATES_DIR.is_dir() and list(_USER_TEMPLATES_DIR.glob("*.prompt")):
        print(f"  ✅  Templates already in ~/.cross_templates/")
    else:
        copied, _ = seed_user_templates(overwrite=False)
        print(f"  ✅  Seeded {copied} template(s) to ~/.cross_templates/")

    # ── Offer to seed benchmark domains ───────────────────────────────────────
    home_stones = get_default_stones_dir()
    cwd_stones  = Path("cross_stones")
    if home_stones.is_dir() or cwd_stones.is_dir():
        loc = home_stones if home_stones.is_dir() else cwd_stones.resolve()
        print(f"  ✅  Benchmark domains already in {loc}/")
    else:
        try:
            stones_ans = input(
                f"\n  Seed Cross-Stones benchmark domains to {home_stones}/? [Y/n]: "
            ).strip().lower()
        except (KeyboardInterrupt, EOFError):
            stones_ans = "n"
        if stones_ans != "n":
            copied, _ = seed_stones_domains(dst_dir=home_stones, overwrite=False)
            if copied:
                print(f"  ✅  Seeded {copied} domain prompt(s) to {home_stones}/")
            else:
                print("  ⚠️  No bundled domain prompts found — skipping")

    # ── Done ──────────────────────────────────────────────────────────────────
    print(f"\n  {_SEP}")

    # ── Discourse (optional) ──────────────────────────────────────────────────
    print(
        "\n  Discourse (optional)\n"
        f"  {_SEP}\n"
        "  Discourse lets you publish reports from st-post to a forum.\n"
        "  crossai.dev is a free community forum for Cross users — it provisions\n"
        "  a private category for you automatically.\n"
    )
    try:
        disc_ans = input(
            "  Set up crossai.dev community access? [Y/n]: "
        ).strip().lower()
    except (KeyboardInterrupt, EOFError):
        disc_ans = "n"

    if disc_ans != "n":
        _run_discourse_setup()

    # Power users: configure an additional self-hosted Discourse instance
    try:
        extra_ans = input(
            "\n  Configure an additional custom Discourse forum? [y/N]: "
        ).strip().lower()
    except (KeyboardInterrupt, EOFError):
        extra_ans = "n"

    if extra_ans == "y":
        disc_url, disc_user, disc_key, disc_cat, disc_slug = "", "", "", "1", "MySite"
        try:
            disc_url  = input("  Site URL (e.g. https://forum.example.com): ").strip()
            disc_user = input("  Username: ").strip()
            disc_key  = input("  API key: ").strip()
            disc_cat  = input("  Category ID [1]: ").strip() or "1"
            disc_slug = input("  Site slug (short name) [MySite]: ").strip() or "MySite"
        except (KeyboardInterrupt, EOFError):
            disc_url = ""
        if disc_url:
            custom_discourse = json.dumps({"sites": [{"slug": disc_slug,
                                                       "url":  disc_url,
                                                       "username": disc_user,
                                                       "api_key":  disc_key,
                                                       "category_id": int(disc_cat)}]})
            _write("DISCOURSE", custom_discourse)

    # ── Setup complete ────────────────────────────────────────────────────────
    print(f"\n  Setup complete!")
    print(f"  Create your first report:  st-new my_topic.prompt")
    print(f"  For help:                  st-man\n")


def settings_show_all() -> None:
    """Print a formatted summary of all current settings."""
    import json
    from importlib.metadata import version as _pkg_ver, PackageNotFoundError as _PNF
    try:
        _installed_ver = _pkg_ver("cross-st")
    except _PNF:
        _installed_ver = "unknown"

    ai_list = get_ai_list()
    W = 26
    print(f"\n  {'Setting':<{W}}  Value")
    print(f"  {'─' * W}  {'─' * 36}")
    print(f"  {'cross-st version':<{W}}  {_installed_ver}")
    print(f"  {'Default AI':<{W}}  {settings_get_default_ai()}")
    for make in ai_list:
        print(f"  {'AI model: ' + make:<{W}}  {settings_get_ai_model(make)}")
    tts_host = _env_get("TTS_HOST", "(not set)")
    tts_port = _env_get("TTS_PORT", "(not set)")
    print(f"  {'TTS voice':<{W}}  {settings_get_tts_voice()}")
    print(f"  {'TTS host':<{W}}  {tts_host}")
    print(f"  {'TTS port':<{W}}  {tts_port}")
    print(f"  {'Default template':<{W}}  {settings_get_default_template()}")
    print(f"  {'Editor':<{W}}  {settings_get_editor()}")
    print(f"  {'Stones dir':<{W}}  {get_default_stones_dir()}")

    # ── Discourse ─────────────────────────────────────────────────────────────
    def _cat_label_str(cat_id, priv_id, p_slug) -> str:
        if cat_id is None:
            return "(not set)"
        if cat_id == _DISCOURSE_TEST_CATEGORY_ID:
            return f"{_DISCOURSE_TEST_CATEGORY_NAME}  [id={cat_id}]"
        if cat_id == _DISCOURSE_REPORTS_CATEGORY_ID:
            return f"{_DISCOURSE_REPORTS_CATEGORY_NAME}  [id={cat_id}]"
        if cat_id == _DISCOURSE_PROMPT_LAB_CATEGORY_ID:
            return f"{_DISCOURSE_PROMPT_LAB_CATEGORY_NAME}  [id={cat_id}]"
        if priv_id and cat_id == priv_id:
            return f"{p_slug or 'your-private'}  [id={cat_id}]"
        return f"[id={cat_id}]"

    disc_json_str  = _env_get("DISCOURSE", "")
    disc_url_flat  = _env_get("DISCOURSE_URL", "")
    disc_user_flat = _env_get("DISCOURSE_USERNAME", "")

    print(f"\n  {'Discourse':<{W}}  Value")
    print(f"  {'─' * W}  {'─' * 36}")

    if disc_json_str:
        try:
            data  = json.loads(disc_json_str)
            sites = data.get("sites", data) if isinstance(data, dict) else data
            disc_site_key = _env_get("DISCOURSE_SITE", "")
            for idx, site in enumerate(sites):
                if idx > 0:
                    print()
                slug      = site.get("slug", "")
                url       = site.get("url", "")
                username  = site.get("username", "")
                cat_id    = site.get("category_id")
                priv_id   = site.get("private_category_id")
                priv_slug = site.get("private_category_slug", "")
                tos_ver   = site.get("tos_version", "")
                tos_at    = site.get("tos_agreed_at", "")

                is_active = (not disc_site_key and idx == 0) or (slug == disc_site_key)
                site_label = slug or url.replace("https://", "").replace("http://", "").rstrip("/")
                active_marker = "  ✓ active" if len(sites) > 1 and is_active else ""

                print(f"  {'Site':<{W}}  {site_label}{active_marker}")
                print(f"  {'URL':<{W}}  {url}")
                print(f"  {'Username':<{W}}  {username}")
                print(f"  {'Default category':<{W}}  {_cat_label_str(cat_id, priv_id, priv_slug)}")
                if priv_id:
                    print(f"  {'Private category':<{W}}  {priv_slug or 'your-private'}  [id={priv_id}]")
                if tos_ver:
                    tos_info = tos_ver
                    if tos_at:
                        tos_info += f"  (agreed {tos_at[:10]})"
                    print(f"  {'TOS version':<{W}}  {tos_info}")
        except Exception:
            print(f"  {'Status':<{W}}  ✗ DISCOURSE JSON is malformed in ~/.crossenv")
    elif disc_url_flat or disc_user_flat:
        # Flat keys only (pre-DIS-3 migration)
        disc_cat_flat = _env_get("DISCOURSE_CATEGORY_ID", "")
        print(f"  {'URL':<{W}}  {disc_url_flat or '(not set)'}")
        print(f"  {'Username':<{W}}  {disc_user_flat or '(not set)'}")
        if disc_cat_flat:
            print(f"  {'Category ID':<{W}}  {disc_cat_flat}")
        print(f"  {'Note':<{W}}  Run: st-admin --discourse  (migrates to JSON config)")
    else:
        print(f"  {'Status':<{W}}  (not configured — run: st-admin --discourse-setup)")

    # ── Paths ──────────────────────────────────────────────────────────────────
    def _path_line(label: str, path: str) -> str:
        exists = "✓" if os.path.exists(path) else "✗ (not found)"
        return f"  {label:<{W}}  {path}  {exists}"

    print(f"\n  {'Path':<{W}}  Location")
    print(f"  {'─' * W}  {'─' * 36}")
    print(_path_line("Config (active)",          _TARGET_ENV))
    if os.path.realpath(_TARGET_ENV) != os.path.realpath(_CROSSENV):
        print(_path_line("Config (~/.crossenv)",  _CROSSENV))
    print(_path_line("API cache",                 _get_cache_dir()))
    print(_path_line("Templates",                 str(_USER_TEMPLATES_DIR)))
    print()


def upgrade_cross() -> None:
    """Upgrade cross-st from PyPI and macOS platform tools.

    - Detects pipx vs pip install and uses the right upgrade command.
    - Skips the PyPI upgrade for editable (dev) installs.
    - On macOS: runs ``brew upgrade`` for tracked Homebrew tools.
    - On Linux: prints the equivalent apt/dnf commands.
    """
    import importlib.metadata as _im
    import platform
    import shutil

    system = platform.system()
    is_mac   = system == "Darwin"
    is_linux = system == "Linux"

    _W   = 58
    _SEP = "─" * _W

    def _section(title: str) -> None:
        print(f"\n  {title}\n  {'·' * (_W - 2)}")

    print(f"\n  Cross Upgrade")
    print(f"  {_SEP}")

    # ── Current version ───────────────────────────────────────────────────────
    try:
        current_ver = _im.version("cross-st")
    except _im.PackageNotFoundError:
        current_ver = "unknown"

    # ── Detect install type ───────────────────────────────────────────────────
    # Priority order:
    #   1. Is sys.executable inside a pipx venv?  → pipx install
    #   2. Does direct_url.json say editable=true? → dev install
    #   3. Otherwise                               → plain pip install
    import pathlib

    pipx_bin  = shutil.which("pipx")
    using_pipx = False
    is_editable = False

    exe_path  = pathlib.Path(sys.executable).resolve()
    pipx_home = pathlib.Path(
        os.environ.get("PIPX_HOME", os.path.expanduser("~/.local/pipx"))
    )
    try:
        exe_path.relative_to(pipx_home)
        using_pipx = True          # running executable is inside the pipx venv
    except ValueError:
        pass

    if not using_pipx:
        # Only check for editable marker when NOT running from pipx
        try:
            dist = _im.Distribution.from_name("cross-st")
            direct_url_text = dist.read_text("direct_url.json")
            if direct_url_text and '"editable": true' in direct_url_text:
                is_editable = True
        except Exception:
            pass

    # ── Upgrade cross-st ──────────────────────────────────────────────────────
    _section("cross-st")
    print(f"  Installed : cross-st {current_ver}")

    if is_editable:
        # Locate the dev checkout from the dist-info direct_url
        dev_path = ""
        try:
            import json
            dist = _im.Distribution.from_name("cross-st")
            du = json.loads(dist.read_text("direct_url.json") or "{}")
            dev_path = du.get("url", "").removeprefix("file://")
        except Exception:
            pass
        print(f"\n  ⚠️  Dev (editable) install detected — skipping PyPI upgrade.")
        if dev_path:
            print(f"      Checkout : {dev_path}")
        print(f"      To update:")
        print(f"        cd {dev_path or '<your cross-st checkout>'}")
        print(f"        git pull")
        print(f"        pip install -e .")
    else:
        if using_pipx:
            if pipx_bin:
                upgrade_cmd = [pipx_bin, "upgrade", "cross-st"]
            else:
                # pipx not on PATH but executable is inside its venv — find it
                _pipx_guess = pathlib.Path(sys.executable).parent.parent.parent.parent.parent / "bin" / "pipx"
                upgrade_cmd = [str(_pipx_guess) if _pipx_guess.exists()
                               else "pipx", "upgrade", "cross-st"]
        else:
            upgrade_cmd = [sys.executable, "-m", "pip", "install", "--upgrade",
                           "cross-st"]

        print(f"  $ {' '.join(upgrade_cmd)}\n")
        result = subprocess.run(upgrade_cmd)

        # Re-read version in a subprocess so importlib cache is bypassed
        try:
            r2 = subprocess.run(
                [sys.executable, "-c",
                 "from importlib.metadata import version; print(version('cross-st'))"],
                capture_output=True, text=True, timeout=15,
            )
            new_ver = r2.stdout.strip() or current_ver
        except Exception:
            new_ver = current_ver

        if result.returncode == 0:
            if new_ver and new_ver != current_ver:
                print(f"\n  ✅  cross-st upgraded: {current_ver} → {new_ver}")
            else:
                print(f"\n  ✅  cross-st {current_ver} is already up to date")
        else:
            print(f"\n  ❌  cross-st upgrade failed (exit code {result.returncode})")

    # ── Platform tools ────────────────────────────────────────────────────────
    _TRACKED_BREW = ["ffmpeg", "aspell"]   # tools cross-st setup can install

    if is_mac:
        brew_bin = shutil.which("brew")
        if not brew_bin:
            print(f"\n  ⚠️  Homebrew not found — skipping platform tool upgrade")
        else:
            _section("Homebrew platform tools")
            installed_brew = []
            for tool in _TRACKED_BREW:
                r = subprocess.run([brew_bin, "list", "--formula", tool],
                                   capture_output=True, text=True)
                if r.returncode == 0:
                    installed_brew.append(tool)

            if installed_brew:
                print(f"  Installed via Homebrew: {', '.join(installed_brew)}")
                print(f"  $ brew upgrade {' '.join(installed_brew)}\n")
                result = subprocess.run([brew_bin, "upgrade"] + installed_brew)
                if result.returncode == 0:
                    print(f"\n  ✅  Homebrew tools upgraded")
                else:
                    print(f"\n  ⚠️  brew upgrade exited {result.returncode} "
                          "(already up-to-date is normal)")
            else:
                print(f"  No tracked Homebrew tools found — nothing to upgrade")

    elif is_linux:
        _section("Platform tools")
        print(f"  Upgrade tracked platform tools via your package manager:")
        print(f"    sudo apt upgrade {' '.join(_TRACKED_BREW)}     "
              f"# Debian/Ubuntu")
        print(f"    sudo dnf upgrade {' '.join(_TRACKED_BREW)}     "
              f"# Fedora/RHEL")

    print(f"\n  {_SEP}")
    print()


# ── Cache management ───────────────────────────────────────────────────────────

def _cache_files() -> list[Path]:
    """Return all files in the AI response cache directory."""
    cache_dir = Path(_get_cache_dir())
    if not cache_dir.is_dir():
        return []
    return [p for p in cache_dir.iterdir() if p.is_file()]


def cache_info() -> None:
    """Print cache path, file count, and total size."""
    cache_dir = Path(_get_cache_dir())
    files = _cache_files()
    total_bytes = sum(f.stat().st_size for f in files)

    if total_bytes < 1024:
        size_str = f"{total_bytes} B"
    elif total_bytes < 1024 ** 2:
        size_str = f"{total_bytes / 1024:.1f} KB"
    else:
        size_str = f"{total_bytes / 1024 ** 2:.1f} MB"

    W = 18
    print(f"\n  {'Cache path':<{W}}  {cache_dir}")
    print(f"  {'Files':<{W}}  {len(files)}")
    print(f"  {'Total size':<{W}}  {size_str}")
    if not files:
        print(f"  {'Status':<{W}}  (empty)")
    print()


def cache_clear() -> None:
    """Delete all files in the AI response cache."""
    files = _cache_files()
    if not files:
        print("\n  Cache is already empty.\n")
        return
    for f in files:
        try:
            f.unlink()
        except OSError as e:
            print(f"  ⚠️  Could not delete {f.name}: {e}")
    print(f"\n  ✅  Deleted {len(files)} cached file(s).\n")


def cache_cull(days: int) -> None:
    """Delete cache files not accessed (mtime) in the last *days* days."""
    import time
    if days <= 0:
        print("  ✗  DAYS must be a positive integer.", file=sys.stderr)
        sys.exit(1)

    files = _cache_files()
    if not files:
        print("\n  Cache is empty — nothing to cull.\n")
        return

    cutoff = time.time() - days * 86400
    old = [f for f in files if f.stat().st_mtime < cutoff]

    if not old:
        print(f"\n  No cache files older than {days} day(s) found.\n")
        return

    for f in old:
        try:
            f.unlink()
        except OSError as e:
            print(f"  ⚠️  Could not delete {f.name}: {e}")
    print(f"\n  ✅  Culled {len(old)} file(s) older than {days} day(s) "
          f"({len(files) - len(old)} remaining).\n")


# ── Interactive menu ───────────────────────────────────────────────────────────

_MENU = {
    "a": ("AI", {
        "d": "View / set default AI provider",
        "m": "Set AI model for a provider",
        "M": "View all AI models",
        "v": "View TTS voice",
        "V": "Set TTS voice  (launches st-voice)",
    }),
    "t": ("Templates & editor", {
        "t": "View default template",
        "T": "Set default template",
        "e": "View editor",
        "E": "Set editor",
        "i": "Init templates  (seed ~/.cross_templates/ from bundled defaults)",
    }),
    "d": ("Discourse", {
        "d": "Select default site",
        "c": "Select posting category  (private | test-cleared-daily)",
        "s": lambda: f"Site manager  ({_get_active_discourse_slug() or 'no site configured'})",
        "m": "Manage sites  (add / delete)",
        "o": "Community onboarding / re-accept T&C",
    }),
    "c": ("Cache", {
        "i": "Cache info  (path, file count, size)",
        "x": "Cache clear  (delete all cached AI responses)",
        "k": "Cache cull  (delete entries older than N days)",
    }),
    "s": "Show all settings",
    "u": "Upgrade cross-st from PyPI + platform tools",
}


def _print_menu(menu: dict, title: str) -> None:
    print(f"\n=== {title} ===")
    for key, value in menu.items():
        label = value[0] if isinstance(value, tuple) else value
        # Allow callable labels so menu items can show live state (e.g. the
        # currently-selected Discourse site in the "Site manager" line).
        if callable(label):
            try:
                label = label()
            except Exception:
                label = "(error)"
        print(f"  {key}: {label}")
    print()
    print("  esc: Escape back to the previous menu")
    print("  ?: Display this menu")


def interactive_menu() -> None:
    """Full interactive settings panel — 2-level menu, ESC to go back."""
    from mmd_single_key import get_single_key

    # Show which file st-admin is reading/writing so the dev-vs-pipx
    # distinction is never a surprise.
    _profile_label = "developer" if _DEV_MODE else "pipx-installed"
    print(f"  Profile: {_profile_label}  →  settings file: {_TARGET_ENV}")

    ai_list = get_ai_list()
    current_menu = _MENU
    menu_stack: list = []
    menu_names = ["st-admin"]
    show_menu = True

    while True:
        title = ">".join(menu_names)

        if show_menu:
            _print_menu(current_menu, title)
            show_menu = False

        print(f"\n{title}> ", end="", flush=True)
        key = get_single_key()
        print(key)

        # ── Navigation ────────────────────────────────────────────────────────
        if key in ("ESC", "q"):
            if menu_stack:
                current_menu = menu_stack.pop()
                menu_names.pop()
                show_menu = True
            else:
                print("  Exiting st-admin.")
                break

        elif key == "?":
            show_menu = True

        elif key in current_menu:
            item = current_menu[key]
            if isinstance(item, tuple):
                # Navigate into submenu
                menu_stack.append(current_menu)
                menu_names.append(item[0])
                current_menu = item[1]
                show_menu = True
            else:
                # ── Actions ───────────────────────────────────────────────────
                ctx = menu_names[-1]  # "st-admin", "AI", "Templates & editor", etc.
                match (ctx, key):

                    # ── Top-level ─────────────────────────────────────────────
                    case ("st-admin", "s"):
                        settings_show_all()

                    case ("st-admin", "u"):
                        upgrade_cross()

                    # ── AI ────────────────────────────────────────────────────
                    case ("AI", "d"):
                        current = settings_get_default_ai()
                        rotation = "  ".join(
                            f"[{m}]" if m == current else m for m in ai_list
                        )
                        print(f"\n  Current default AI: {current}")
                        print(f"  Available: {rotation}")
                        new_ai = input("  New default AI (blank to cancel): ").strip()
                        if new_ai:
                            try:
                                settings_set_default_ai(new_ai)
                                print(f"  ✓  Default AI set to: {new_ai}  (written to .env)")
                            except ValueError as exc:
                                print(f"  ✗  {exc}")

                    case ("AI", "m"):
                        print(f"\n  Available providers: {', '.join(ai_list)}")
                        make = input("  Provider (blank to cancel): ").strip()
                        if make:
                            if make not in ai_list:
                                print(f"  ✗  Unknown provider: {make!r}")
                            else:
                                current_model = settings_get_ai_model(make)
                                print(f"  Current model for {make}: {current_model}")
                                new_model = input("  New model (blank to cancel): ").strip()
                                if new_model:
                                    settings_set_ai_model(make, new_model)
                                    print(f"  ✓  {make} model set to: {new_model}  (written to .ai_models)")

                    case ("AI", "M"):
                        print(f"\n  {'Provider':<14}  Model")
                        print(f"  {'─' * 14}  {'─' * 36}")
                        for make in ai_list:
                            print(f"  {make:<14}  {settings_get_ai_model(make)}")

                    case ("AI", "v"):
                        print(f"\n  TTS voice: {settings_get_tts_voice()}")

                    case ("AI", "V"):
                        subprocess.run(["st-voice"])

                    # ── Templates & editor ────────────────────────────────────
                    case ("Templates & editor", "t"):
                        print(f"\n  Default template: {settings_get_default_template()}")

                    case ("Templates & editor", "T"):
                        current = settings_get_default_template()
                        print(f"\n  Current default template: {current}")
                        new_tmpl = input("  New template name (blank to cancel): ").strip()
                        if new_tmpl:
                            _env_set("DEFAULT_TEMPLATE", new_tmpl)
                            print(f"  ✓  Default template set to: {new_tmpl}  (written to .env)")

                    case ("Templates & editor", "e"):
                        print(f"\n  Editor: {settings_get_editor()}")

                    case ("Templates & editor", "E"):
                        current = settings_get_editor()
                        print(f"\n  Current editor: {current}")
                        new_editor = input(
                            "  New editor (e.g. nano, code, micro — blank to cancel): "
                        ).strip()
                        if new_editor:
                            _env_set("EDITOR", new_editor)
                            print(f"  ✓  Editor set to: {new_editor}  (written to .env)")

                    case ("Templates & editor", "i"):
                        print("\n  Seeding ~/.cross_templates/ from bundled defaults …")
                        overwrite_ans = input(
                            "  Overwrite existing files? [y/N]: "
                        ).strip().lower()
                        init_user_templates(overwrite=(overwrite_ans == "y"))

                    # ── Discourse ─────────────────────────────────────────────
                    case ("Discourse", "d"):
                        _discourse_select_site()

                    case ("Discourse", "c"):
                        _discourse_select_category()

                    case ("Discourse", "s"):
                        discourse_manage()

                    case ("Discourse", "m"):
                        _discourse_manage_sites()

                    case ("Discourse", "o"):
                        _run_discourse_setup()

                    # ── Cache ─────────────────────────────────────────────────
                    case ("Cache", "i"):
                        cache_info()

                    case ("Cache", "x"):
                        try:
                            ans = input("  Delete ALL cached AI responses? [y/N]: ").strip().lower()
                        except (KeyboardInterrupt, EOFError):
                            ans = "n"
                        if ans == "y":
                            cache_clear()
                        else:
                            print("  Cancelled.")

                    case ("Cache", "k"):
                        try:
                            raw = input("  Delete cache entries older than how many days? ").strip()
                        except (KeyboardInterrupt, EOFError):
                            raw = ""
                        if raw:
                            try:
                                cache_cull(int(raw))
                            except ValueError:
                                print(f"  ✗  Not a valid number: {raw!r}")
                        else:
                            print("  Cancelled.")

                    case _:
                        if key != "RETURN":
                            print(f"  Invalid choice: {key!r}  (press ? for menu)")

        else:
            if key != "RETURN":
                print(f"  Invalid choice: {key!r}  (press ? for menu)")


# ── CLI entry point ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="st-admin",
        description="Cross toolkit settings manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Without flags, opens the interactive settings panel.\n\n"
            "Settings are stored in .env (DEFAULT_AI, TTS_VOICE, DEFAULT_TEMPLATE,\n"
            "EDITOR) and .ai_models (per-provider model overrides).\n\n"
            "The DEFAULT_AI value is used by all st-* tools as the provider for\n"
            "caption / report generation whenever --ai is not explicitly passed."
        ),
    )

    try:
        from importlib.metadata import version as _v
        _ver_str = f"cross-st {_v('cross-st')}"
    except Exception:
        _ver_str = "cross-st (version unknown)"
    parser.add_argument("--version", action="version", version=_ver_str,
                        help="Print the installed cross-st version and exit")

    parser.add_argument(
        "--setup", action="store_true",
        help="Interactive first-run wizard: checks environment, collects API keys, "
             "writes ~/.crossenv",
    )
    parser.add_argument(
        "--discourse-setup", action="store_true",
        help="(Re-)run the crossai.dev community onboarding wizard independently of --setup",
    )
    parser.add_argument(
        "--discourse", action="store_true",
        help="Manage Discourse site connection and default posting category",
    )
    parser.add_argument(
        "--check-tos", action="store_true",
        help="Check whether the stored T&C version is current; prompt re-acceptance if stale",
    )
    parser.add_argument(
        "--show", action="store_true",
        help="Print all current settings and exit",
    )
    parser.add_argument(
        "--get-default-ai", action="store_true",
        help="Print the current default AI provider and exit",
    )
    parser.add_argument(
        "--set-default-ai", metavar="NAME",
        help="Set the default AI provider (e.g. anthropic, xai, gemini)",
    )
    parser.add_argument(
        "--set-ai-model", metavar="MAKE=MODEL",
        help="Set a per-provider model override (e.g. xai=grok-3)",
    )
    parser.add_argument(
        "--set-tts-voice", metavar="VOICE",
        help="Set the TTS voice string (written to TTS_VOICE in .env)",
    )
    parser.add_argument(
        "--set-template", metavar="NAME",
        help="Set the default prompt template name",
    )
    parser.add_argument(
        "--set-editor", metavar="NAME",
        help="Set the editor (written to EDITOR in .env)",
    )
    parser.add_argument(
        "--init-templates", action="store_true",
        help="Seed ~/.cross_templates/ with bundled default .prompt files",
    )
    parser.add_argument(
        "--overwrite-templates", action="store_true",
        help="With --init-templates: replace files that already exist",
    )
    parser.add_argument(
        "--upgrade", action="store_true",
        help="Upgrade cross-st from PyPI (pipx or pip) and macOS Homebrew platform tools",
    )
    parser.add_argument(
        "--cache-info", action="store_true",
        help="Print cache path, file count, and total size",
    )
    parser.add_argument(
        "--cache-clear", action="store_true",
        help="Delete all cached AI responses",
    )
    parser.add_argument(
        "--cache-cull", metavar="DAYS", type=int,
        help="Delete cache entries not accessed in the last DAYS days",
    )

    args = parser.parse_args()

    # ── Non-interactive operations (any flag → run and exit) ──────────────────
    if args.setup:
        setup_wizard()
        return

    if args.discourse_setup:
        _run_discourse_setup()
        return

    if args.discourse:
        discourse_manage()
        return

    if args.check_tos:
        check_tos_flag()
        return

    if args.show:
        settings_show_all()
        return

    if args.get_default_ai:
        print(settings_get_default_ai())
        return

    if args.set_default_ai:
        try:
            settings_set_default_ai(args.set_default_ai)
            print(f"✓  Default AI set to: {args.set_default_ai}")
        except ValueError as exc:
            print(f"✗  {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if args.set_ai_model:
        if "=" not in args.set_ai_model:
            print("✗  Format must be MAKE=MODEL (e.g. xai=grok-3)", file=sys.stderr)
            sys.exit(1)
        make, _, model = args.set_ai_model.partition("=")
        settings_set_ai_model(make.strip(), model.strip())
        print(f"✓  {make.strip()} model set to: {model.strip()}")
        return

    if args.set_tts_voice:
        _env_set("TTS_VOICE", args.set_tts_voice)
        print(f"✓  TTS voice set to: {args.set_tts_voice}")
        return

    if args.set_template:
        _env_set("DEFAULT_TEMPLATE", args.set_template)
        print(f"✓  Default template set to: {args.set_template}")
        return

    if args.set_editor:
        _env_set("EDITOR", args.set_editor)
        print(f"✓  Editor set to: {args.set_editor}")
        return

    if args.init_templates:
        init_user_templates(overwrite=args.overwrite_templates)
        return

    if args.upgrade:
        upgrade_cross()
        return

    if args.cache_info:
        cache_info()
        return

    if args.cache_clear:
        cache_clear()
        return

    if args.cache_cull is not None:
        cache_cull(args.cache_cull)
        return

    # ── Interactive mode ──────────────────────────────────────────────────────
    interactive_menu()


if __name__ == "__main__":
    main()

