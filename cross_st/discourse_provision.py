"""
cross_st/discourse_provision.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Client-side Discourse onboarding helpers.

Exported:
  discourse_onboard(username)       → dict  — calls provision endpoint, returns credentials
  write_discourse_env(credentials)  → None  — writes keys to ~/.crossenv via set_key()
  display_terms_and_conditions()    → bool  — pages T&C, returns True if accepted
"""
from __future__ import annotations

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

# Default production endpoint — override via DISCOURSE_PROVISION_URL in any .env layer
PROVISION_ENDPOINT = os.getenv(
    "DISCOURSE_PROVISION_URL",
    "https://crossai.dev/api/provision-user",
)

# ── Terms & Conditions ───────────────────────────────────────────────────────

def display_terms_and_conditions() -> bool:
    """
    Display the crossai.dev T&C to the user, then ask for acceptance.
    Returns True if the user explicitly types "yes", False otherwise.
    """
    if not _TOS_PATH.exists():
        print("  ⚠️  Terms & Conditions file not found. Skipping display.")
    else:
        tos_text = _TOS_PATH.read_text(encoding="utf-8")
        print()
        print("─" * 78)
        print(tos_text)
        print("─" * 78)
        print("  Full Terms:  https://crossai.dev/tos")
        print("  Privacy:     https://crossai.dev/privacy")
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

# ── Provisioning ─────────────────────────────────────────────────────────────

def discourse_onboard(
    username: str,
    provision_secret: Optional[str] = None,
    endpoint: Optional[str] = None,
    timeout: int = 30,
) -> dict:
    """
    Call the crossai.dev provisioning endpoint.

    Args:
        username:         Discourse username (must already exist and be email-verified).
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
    secret = provision_secret or os.getenv("PROVISION_SECRET", "")

    if not secret:
        raise ValueError(
            "PROVISION_SECRET not set. "
            "Add it to ~/.crossenv or pass provision_secret= explicitly."
        )

    resp = requests.post(
        url,
        json={"username": username.strip().lower()},
        headers={"Authorization": f"Bearer {secret}"},
        timeout=timeout,
    )

    if resp.status_code == 400:
        msg = resp.json().get("error", "Bad request")
        raise ValueError(f"Provisioning failed: {msg}")
    if resp.status_code == 401:
        raise PermissionError(
            "Invalid PROVISION_SECRET — check ~/.crossenv on the server."
        )

    resp.raise_for_status()
    return resp.json()


def write_discourse_env(credentials: dict) -> None:
    """
    Write Discourse credentials to ~/.crossenv using python-dotenv set_key().

    Keys written:
        DISCOURSE_URL
        DISCOURSE_USERNAME
        DISCOURSE_API_KEY
        DISCOURSE_CATEGORY_ID
        DISCOURSE_PRIVATE_CATEGORY_SLUG
    """
    mapping = {
        "DISCOURSE_URL":                    credentials.get("discourse_url", ""),
        "DISCOURSE_USERNAME":               credentials.get("discourse_username", ""),
        "DISCOURSE_API_KEY":                credentials.get("discourse_api_key", ""),
        "DISCOURSE_CATEGORY_ID":            str(credentials.get("discourse_category_id", "")),
        "DISCOURSE_PRIVATE_CATEGORY_SLUG":  credentials.get("discourse_private_category_slug", ""),
    }
    for key, value in mapping.items():
        if value:
            set_key(_CROSSENV, key, value)
            os.environ[key] = value

