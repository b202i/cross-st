"""
cross_st/discourse_provision.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Client-side Discourse onboarding helpers.

Exported:
  get_tos_versions()                → dict  — returns {"tos_version": ..., "privacy_version": ...}
  discourse_onboard(username, ...)  → dict  — calls provision endpoint, returns credentials
  write_discourse_env(credentials, ...)  → None  — writes keys to ~/.crossenv via set_key()
  display_terms_and_conditions()    → bool  — pages T&C, returns True if accepted
  check_tos_acceptance(username)    → dict  — asks server whether user needs to re-accept T&C
  record_tos_acceptance(username, ...)  → bool  — records a re-acceptance event server-side
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Optional

import requests
from dotenv import set_key

# ── Constants ────────────────────────────────────────────────────────────────

_CROSSENV       = os.path.expanduser("~/.crossenv")
_TOS_PATH       = Path(__file__).parent / "data" / "discourse_tos.txt"

# Package-level credential for crossai.dev provisioning service.
# This is the cross-st package's own key — new users never need to set it.
# Override via PROVISION_SECRET in any .env layer (dev/test only).
_PROVISION_SECRET_DEFAULT = "x5FZXQjpr6Do3BgHWkNJSaNb+lnIKQquNvPf4MmxScI="

# Default production endpoint — override via DISCOURSE_PROVISION_URL in any .env layer
PROVISION_ENDPOINT = os.getenv(
    "DISCOURSE_PROVISION_URL",
    "https://crossai.dev/api/provision-user",
)

# Invite-link endpoint (same base, different path)
_INVITE_ENDPOINT = os.getenv(
    "DISCOURSE_INVITE_URL",
    "https://crossai.dev/api/invite-link",
)

# TOS-check and acceptance endpoints (TAP-4)
_TOS_CHECK_ENDPOINT = os.getenv(
    "DISCOURSE_TOS_CHECK_URL",
    "https://crossai.dev/api/tos-check",
)
_TOS_ACCEPTANCE_ENDPOINT = os.getenv(
    "DISCOURSE_TOS_ACCEPTANCE_URL",
    "https://crossai.dev/api/record-tos-acceptance",
)

# ── Terms & Conditions ───────────────────────────────────────────────────────

_TOS_VERSIONS_PATH = Path(__file__).parent / "data" / "tos_versions.json"

def get_tos_versions() -> dict:
    """
    Return the current T&C version manifest.

    Returns:
        {"tos_version": "YYYY-MM-DD", "privacy_version": "YYYY-MM-DD", "updated_at": "..."}

    Falls back to hardcoded 2026-04-07 if the manifest file is missing
    (e.g. editable install with the file deleted — should not happen in production).
    """
    if _TOS_VERSIONS_PATH.exists():
        return json.loads(_TOS_VERSIONS_PATH.read_text(encoding="utf-8"))
    return {"tos_version": "2026-04-07", "privacy_version": "2026-04-07", "updated_at": "2026-04-07"}


def display_terms_and_conditions(versions: Optional[dict] = None) -> bool:
    """
    Display the crossai.dev T&C to the user, then ask for acceptance.

    Args:
        versions: dict from get_tos_versions(); if None, get_tos_versions() is called.

    Returns:
        True if the user explicitly types "yes", False otherwise.
    """
    if versions is None:
        versions = get_tos_versions()

    if not _TOS_PATH.exists():
        print("  ⚠️  Terms & Conditions file not found. Skipping display.")
    else:
        tos_text = _TOS_PATH.read_text(encoding="utf-8")
        # Strip the machine-readable # VERSION: comment line (first line) before display
        lines = tos_text.splitlines(keepends=True)
        if lines and lines[0].startswith("# VERSION:"):
            tos_text = "".join(lines[1:])
        print()
        print("─" * 78)
        print(tos_text)
        print("─" * 78)
        print("  Full Terms:  https://crossai.dev/tos")
        print("  Privacy:     https://crossai.dev/privacy")
        print(f"  Terms version: {versions.get('tos_version', '—')}"
              f"   |   Privacy version: {versions.get('privacy_version', '—')}")
        print("─" * 78)

    print()
    try:
        ans = input(
            '  Do you accept the crossai.dev Terms of Service? '
            'Type "yes" to accept: '
        ).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return False

    return ans == "yes"

# ── Invite link ───────────────────────────────────────────────────────────────

def get_invite_link(
    provision_secret: Optional[str] = None,
    endpoint: Optional[str] = None,
    timeout: int = 15,
) -> str:
    """
    Ask the crossai.dev provisioning server to generate a single-use
    Discourse invite link.  Users who register via this link are
    auto-approved — no moderator queue.

    Args:
        provision_secret: Override PROVISION_SECRET (defaults to env var).
        endpoint:         Override _INVITE_ENDPOINT (for dev/test).
        timeout:          HTTP timeout in seconds.

    Returns:
        Invite URL string, e.g. "https://crossai.dev/invites/abc123".

    Raises:
        ValueError:              PROVISION_SECRET not set, or bad server response.
        requests.HTTPError:      on 4xx/5xx from the server.
        requests.ConnectionError: if the server is unreachable.
    """
    url    = endpoint or _INVITE_ENDPOINT
    secret = provision_secret or os.getenv("PROVISION_SECRET", _PROVISION_SECRET_DEFAULT)

    if not secret:
        raise ValueError("Could not determine provisioning secret — package may be corrupt.")

    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {secret}"},
        timeout=timeout,
    )

    if resp.status_code == 401:
        raise PermissionError("Provisioning secret rejected by server — contact support at cross@crossai.dev.")

    resp.raise_for_status()

    invite_url = resp.json().get("invite_url", "")
    if not invite_url:
        raise ValueError("Server returned no invite_url.")
    return invite_url


# ── Provisioning ─────────────────────────────────────────────────────────────

def discourse_onboard(
    username: str,
    tos_version: Optional[str] = None,
    privacy_version: Optional[str] = None,
    client_info: Optional[str] = None,
    provision_secret: Optional[str] = None,
    endpoint: Optional[str] = None,
    timeout: int = 30,
) -> dict:
    """
    Call the crossai.dev provisioning endpoint.

    Args:
        username:         Discourse username (must already exist and be email-verified).
        tos_version:      TOS version string accepted by the user (e.g. "2026-04-07").
                          When supplied, the server records the acceptance event.
        privacy_version:  Privacy Policy version string accepted by the user.
        client_info:      Client identifier string for the TOS audit trail
                          (e.g. "cross-st/0.4.0 Python/3.12.3").
        provision_secret: Override PROVISION_SECRET (defaults to env var).
        endpoint:         Override PROVISION_ENDPOINT (for dev/test).
        timeout:          HTTP timeout in seconds.

    Returns:
        Credentials dict:
            {
                "discourse_url":                   "https://crossai.dev",
                "discourse_username":              "alice",
                "discourse_api_key":               "abc123...",
                "discourse_category_id":           42,
                "discourse_private_category_slug": "alice-private",
            }

    Raises:
        requests.HTTPError: on 4xx/5xx from the provisioning server.
        requests.ConnectionError: if the provisioning server is unreachable.
    """
    url = endpoint or PROVISION_ENDPOINT
    secret = provision_secret or os.getenv("PROVISION_SECRET", _PROVISION_SECRET_DEFAULT)

    if not secret:
        raise ValueError("Could not determine provisioning secret — package may be corrupt.")

    body: dict = {"username": username.strip().lower()}
    if tos_version:
        body["tos_version"] = tos_version
    if privacy_version:
        body["privacy_version"] = privacy_version
    if client_info:
        body["client_info"] = client_info

    resp = requests.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {secret}"},
        timeout=timeout,
    )

    if resp.status_code == 400:
        msg = resp.json().get("error", "Bad request")
        raise ValueError(f"Provisioning failed: {msg}")
    if resp.status_code == 401:
        raise PermissionError(
            "Provisioning secret rejected by server — contact support at cross@crossai.dev."
        )

    resp.raise_for_status()
    return resp.json()


def write_discourse_env(
    credentials: dict,
    tos_version: Optional[str] = None,
    privacy_version: Optional[str] = None,
    tos_agreed_at: Optional[str] = None,
) -> None:
    """
    Write Discourse credentials to ~/.crossenv using python-dotenv set_key().

    Only two keys are written:

        DISCOURSE_SITE  — slug of this site (e.g. "crossai.dev"); used as the
                          startup default in st and st-post.

        DISCOURSE       — {"sites": [...]} JSON; the only key discourse.py reads.
                          Each site entry is fully self-contained:
                            slug, url, username, api_key,
                            category_id          (active posting category — mutable),
                            private_category_id  (original private cat — immutable),
                            private_category_slug,
                            tos_version          (TAP-4: version the user accepted),
                            privacy_version      (TAP-4: privacy policy version accepted),
                            tos_agreed_at        (TAP-4: ISO-8601 UTC timestamp)

                          Upserts: any other sites already in DISCOURSE (e.g. a
                          custom self-hosted forum) are preserved unchanged.

    The legacy flat keys (DISCOURSE_URL, DISCOURSE_USERNAME, DISCOURSE_API_KEY,
    DISCOURSE_CATEGORY_ID, DISCOURSE_PRIVATE_CATEGORY_SLUG) are no longer written.
    discourse_manage() migrates them on first run of st-admin --discourse.
    """
    import json as _json

    disc_url  = credentials.get("discourse_url", "")
    disc_user = credentials.get("discourse_username", "")
    disc_key  = credentials.get("discourse_api_key", "")
    disc_cat  = credentials.get("discourse_category_id", 1)
    disc_priv_slug = credentials.get("discourse_private_category_slug", "")

    if not (disc_url and disc_user and disc_key):
        return

    url_slug = disc_url.replace("https://", "").replace("http://", "").rstrip("/")
    try:
        cat_id = int(disc_cat)
    except (TypeError, ValueError):
        cat_id = 1

    new_site: dict = {
        "slug":                  url_slug,
        "url":                   disc_url,
        "username":              disc_user,
        "api_key":               disc_key,
        "category_id":           cat_id,           # active posting category (mutable)
        "private_category_id":   cat_id,           # original private cat (immutable)
        "private_category_slug": disc_priv_slug,
    }

    # Persist TOS acceptance fields when supplied (TAP-4)
    if tos_version:
        new_site["tos_version"] = tos_version
    if privacy_version:
        new_site["privacy_version"] = privacy_version
    if tos_agreed_at:
        new_site["tos_agreed_at"] = tos_agreed_at

    # Upsert: preserve any other sites (e.g. a custom self-hosted forum)
    # already in DISCOURSE JSON.  Replace the entry whose slug or url
    # matches this one; append if it's brand-new.
    existing_json = os.environ.get("DISCOURSE", "")
    if not existing_json:
        try:
            from dotenv import dotenv_values
            existing_json = dotenv_values(_CROSSENV).get("DISCOURSE", "")
        except Exception:
            existing_json = ""

    try:
        existing_data  = _json.loads(existing_json) if existing_json else {}
        existing_sites = (existing_data.get("sites", existing_data)
                          if isinstance(existing_data, dict)
                          else existing_data)
        if not isinstance(existing_sites, list):
            existing_sites = []
    except (ValueError, AttributeError):
        existing_sites = []

    # Replace matching entry (same slug or same url); put this site first
    updated = [s for s in existing_sites
               if s.get("slug") != url_slug and s.get("url") != disc_url]
    updated = [new_site] + updated

    discourse_json = _json.dumps({"sites": updated})
    set_key(_CROSSENV, "DISCOURSE", discourse_json)
    os.environ["DISCOURSE"] = discourse_json

    # DISCOURSE_SITE = startup default slug
    set_key(_CROSSENV, "DISCOURSE_SITE", url_slug)
    os.environ["DISCOURSE_SITE"] = url_slug


# ── TOS acceptance helpers (TAP-4) ───────────────────────────────────────────

def check_tos_acceptance(
    username: str,
    provision_secret: Optional[str] = None,
    endpoint: Optional[str] = None,
    timeout: int = 10,
) -> dict:
    """
    Ask the crossai.dev server whether a user needs to re-accept the current T&C.

    Args:
        username:         Discourse username to check.
        provision_secret: Override PROVISION_SECRET (defaults to env var).
        endpoint:         Override _TOS_CHECK_ENDPOINT (for dev/test).
        timeout:          HTTP timeout in seconds.

    Returns:
        Server response dict, e.g.:
        {
            "username": "alice",
            "needs_reaccept": false,
            "current_tos_version": "2026-04-07",
            "current_privacy_version": "2026-04-07",
            "last_agreed_tos_version": "2026-04-07",
            "last_agreed_at": "2026-04-12T10:00:00.000Z"
        }

    Raises:
        requests.HTTPError:      on 4xx/5xx from the server.
        requests.ConnectionError: if the server is unreachable.
    """
    url    = endpoint or _TOS_CHECK_ENDPOINT
    secret = provision_secret or os.getenv("PROVISION_SECRET", _PROVISION_SECRET_DEFAULT)

    resp = requests.get(
        url,
        params={"username": username.strip().lower()},
        headers={"Authorization": f"Bearer {secret}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def record_tos_acceptance(
    username: str,
    tos_version: str,
    privacy_version: str,
    method: str = "cli_reaccept",
    client_info: Optional[str] = None,
    provision_secret: Optional[str] = None,
    endpoint: Optional[str] = None,
    timeout: int = 10,
) -> bool:
    """
    Record a TOS re-acceptance event for an already-provisioned user.

    Called after the user accepts an updated T&C (version drift detected locally
    or via check_tos_acceptance()).  Non-fatal: returns False on any error so the
    caller can continue without blocking the user.

    Args:
        username:         Discourse username.
        tos_version:      TOS version the user just accepted.
        privacy_version:  Privacy Policy version accepted.
        method:           "cli_reaccept" (default) or "cli_setup".
        client_info:      Client identifier string (e.g. "cross-st/0.4.0 Python/3.12.3").
        provision_secret: Override PROVISION_SECRET (defaults to env var).
        endpoint:         Override _TOS_ACCEPTANCE_ENDPOINT (for dev/test).
        timeout:          HTTP timeout in seconds.

    Returns:
        True on success, False on any error (HTTP or connection).
    """
    url    = endpoint or _TOS_ACCEPTANCE_ENDPOINT
    secret = provision_secret or os.getenv("PROVISION_SECRET", _PROVISION_SECRET_DEFAULT)

    try:
        resp = requests.post(
            url,
            json={
                "username":        username.strip().lower(),
                "tos_version":     tos_version,
                "privacy_version": privacy_version,
                "method":          method,
                "client_info":     client_info or None,
            },
            headers={"Authorization": f"Bearer {secret}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return True
    except Exception:
        return False

