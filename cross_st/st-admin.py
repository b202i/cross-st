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
            st-speak (render a story container to MP3)
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv, set_key

from ai_handler import get_ai_list, AI_HANDLER_REGISTRY
from base_handler import _get_cache_dir
from mmd_startup import load_cross_env, _PROJECT_ROOT
from mmd_util import (seed_user_templates, _USER_TEMPLATES_DIR, _BUNDLED_TEMPLATES_DIR,
                      seed_stones_domains, _DEFAULT_USER_STONES_DIR, get_default_stones_dir)


# ── Paths ──────────────────────────────────────────────────────────────────────
_CROSSENV    = os.path.expanduser("~/.crossenv")
_models_path = os.path.join(_PROJECT_ROOT, ".ai_models")  # repo root, not cross_st/

load_cross_env()

# ── Discourse constants ────────────────────────────────────────────────────────
_DISCOURSE_TEST_CATEGORY_ID   = 6
_DISCOURSE_TEST_CATEGORY_SLUG = "test-cleared-daily"
_DISCOURSE_TEST_CATEGORY_NAME = "Test (cleared daily)"


# ── Low-level helpers ──────────────────────────────────────────────────────────

def _env_get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_set(key: str, value: str):
    """Write a key to .env and update the running process environment."""
    set_key(_CROSSENV, key, value)
    os.environ[key] = value


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


def _run_discourse_setup() -> None:
    """
    Discourse community onboarding sub-wizard.
    Called from setup_wizard() opt-in prompt, or directly via --discourse-setup.
    """
    from cross_st.discourse_provision import (
        display_terms_and_conditions,
        discourse_onboard,
        write_discourse_env,
    )
    import webbrowser

    print(f"\n  {'─' * 60}")
    print("  crossai.dev Community Onboarding")
    print(f"  {'─' * 60}\n")

    # ── Step 1: Display and accept T&C ────────────────────────────────────
    print("  Step 1/4 — Terms of Service\n")
    accepted = display_terms_and_conditions()
    if not accepted:
        print("\n  ⚠️  You must accept the Terms of Service to join.")
        print("  Run st-admin --discourse-setup at any time to try again.\n")
        return

    print("  ✅  Terms accepted.\n")

    # ── Step 2: Open signup page ───────────────────────────────────────────
    print("  Step 2/4 — Create your crossai.dev account")
    signup_url = "https://crossai.dev/signup"
    print(f"\n  Opening {signup_url} …")
    try:
        webbrowser.open(signup_url)
    except Exception:
        print(f"  (Could not open browser — visit {signup_url} manually)")

    print(
        "\n  Register, verify your email, and make sure you can log in.\n"
        "  Then come back here.\n"
    )
    try:
        input("  Press Enter once you have verified your email and can log in…")
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
        creds = discourse_onboard(username)
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

    write_discourse_env(creds)
    print(
        f"\n  ✅  Your Discourse account is configured. You're ready to use st-post.\n"
        f"\n  Community:  {creds['discourse_url']}"
        f"\n  Username:   {creds['discourse_username']}"
        f"\n  Category:   {creds['discourse_private_category_slug']}"
        f"\n"
    )


def discourse_manage() -> None:
    """
    Interactive Discourse site manager.

    Shows the current Discourse configuration and lets the user switch the
    default posting category between their private category, the shared
    'Test (cleared daily)' sandbox, or a custom category ID.

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
    disc_cat_id    = _env_get("DISCOURSE_CATEGORY_ID", "")      # private cat from onboarding
    disc_priv_slug = _env_get("DISCOURSE_PRIVATE_CATEGORY_SLUG", "")
    disc_json_str  = _env_get("DISCOURSE", "")

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
            "slug":        slug,
            "url":         disc_url,
            "username":    disc_user,
            "api_key":     disc_api_key,
            "category_id": cat_id_int,
        }]})
        _env_set("DISCOURSE", disc_json_str)
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

    active_cat_id = site.get("category_id")
    site_url      = site.get("url",      disc_url  or "?")
    username      = site.get("username", disc_user or "?")

    private_id = int(disc_cat_id) if disc_cat_id.strip().isdigit() else None

    def _cat_label(cat_id, priv_id, priv_slug) -> str:
        if cat_id == _DISCOURSE_TEST_CATEGORY_ID:
            return f"{_DISCOURSE_TEST_CATEGORY_NAME}  [id={cat_id}]"
        if priv_id and cat_id == priv_id:
            return f"{priv_slug or 'your-private'}  [id={cat_id}]"
        return f"[id={cat_id}]"

    active_label  = _cat_label(active_cat_id,  private_id, disc_priv_slug)
    private_label = (f"{disc_priv_slug}  [id={private_id}]"
                     if disc_priv_slug and private_id else "(not configured)")

    # ── Display ───────────────────────────────────────────────────────────────
    W = 28
    print(f"\n  Discourse Site Management")
    print(f"  {_SEP}")
    print(f"  {'Site':<{W}}  {site_url}")
    print(f"  {'Username':<{W}}  {username}")
    print(f"  {'Default posting category':<{W}}  {active_label}")
    print(f"  {'Private category':<{W}}  {private_label}")
    print()

    # ── Category picker ───────────────────────────────────────────────────────
    print("  Change default posting category?")
    if private_id:
        print(f"    1.  {disc_priv_slug or 'your-private'}  (your private category)")
    print(f"    2.  {_DISCOURSE_TEST_CATEGORY_NAME}  — cleared daily, safe for testing")
    print(f"    3.  Enter a category ID manually")
    print(f"    q.  Keep current and exit")
    print()

    try:
        choice = input("  Choice [q]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return

    new_cat_id    = None
    new_cat_label = ""

    if choice in ("q", ""):
        return
    elif choice == "1" and private_id:
        new_cat_id    = private_id
        new_cat_label = f"{disc_priv_slug or 'your-private'}  [id={new_cat_id}]"
    elif choice == "2":
        new_cat_id    = _DISCOURSE_TEST_CATEGORY_ID
        new_cat_label = f"{_DISCOURSE_TEST_CATEGORY_NAME}  [id={new_cat_id}]"
    elif choice == "3":
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

    if crossenv_exists:
        _row("✅", _CROSSENV, "exists — will update")
    else:
        _row("⚠️", _CROSSENV, "will be created")

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
        optional_hints.append(("grip (browser preview in st-edit)",
                                "pip install grip"))

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
        f"  Your keys are stored only in:  {_CROSSENV}\n"
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
        existing = dotenv_values(_CROSSENV) if crossenv_exists else {}
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
            set_key(_CROSSENV, var, val)
            os.environ[var] = val

    _write("GEMINI_API_KEY",     gemini_key)
    _write("XAI_API_KEY",        xai_key)
    _write("ANTHROPIC_API_KEY",  anthropic_key)
    _write("OPENAI_API_KEY",     openai_key)
    _write("PERPLEXITY_API_KEY", perplexity_key)
    _write("DEFAULT_AI",         default_ai)

    print(f"  ✅  Settings written to {_CROSSENV}")

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
        "  Discourse lets you publish stories from st-post to a forum.\n"
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

    # ── Paths ──────────────────────────────────────────────────────────────────
    def _path_line(label: str, path: str) -> str:
        exists = "✓" if os.path.exists(path) else "✗ (not found)"
        return f"  {label:<{W}}  {path}  {exists}"

    print(f"\n  {'Path':<{W}}  Location")
    print(f"  {'─' * W}  {'─' * 36}")
    print(_path_line("Config (~/.crossenv)",      _CROSSENV))
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

    # ── Detect editable (dev) install ─────────────────────────────────────────
    is_editable = False
    try:
        dist = _im.Distribution.from_name("cross-st")
        direct_url_text = dist.read_text("direct_url.json")
        if direct_url_text and '"editable": true' in direct_url_text:
            is_editable = True
    except Exception:
        pass

    # ── Detect pipx install ───────────────────────────────────────────────────
    pipx_bin   = shutil.which("pipx")
    using_pipx = False
    if pipx_bin and not is_editable:
        try:
            r = subprocess.run([pipx_bin, "list", "--short"],
                               capture_output=True, text=True, timeout=10)
            using_pipx = "cross-st" in r.stdout
        except Exception:
            pass

    # ── Upgrade cross-st ──────────────────────────────────────────────────────
    _section("cross-st")
    print(f"  Installed : cross-st {current_ver}")

    if is_editable:
        print(f"\n  ⚠️  Editable (dev) install detected — skipping PyPI upgrade.")
        print(f"      Use  git pull  in your cross-st checkout to update instead.")
    else:
        if using_pipx:
            upgrade_cmd = [pipx_bin, "upgrade", "cross-st"]
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
    "d": "View / set default AI provider",
    "a": "View AI models  (all providers)",
    "m": "Set AI model for a provider",
    "v": "View TTS voice",
    "V": "Set TTS voice  (launches st-voice)",
    "t": "View default prompt template",
    "T": "Set default prompt template",
    "e": "View editor",
    "E": "Set editor",
    "I": "Init templates  (seed ~/.cross_templates/ from bundled defaults)",
    "U": "Upgrade cross-st from PyPI + platform tools",
    "C": "Cache info  (path, file count, size)",
    "X": "Cache clear  (delete all cached AI responses)",
    "K": "Cache cull  (delete entries older than N days)",
    "s": "Show all settings",
    "q": "Quit",
    "?": "Show this menu",
}


def _print_menu():
    print("\n=== st-admin Settings ===")
    for key, label in _MENU.items():
        print(f"  {key}: {label}")


def interactive_menu() -> None:
    """Full interactive settings panel — mirrors the style of st.py."""
    from mmd_single_key import get_single_key

    ai_list = get_ai_list()
    _print_menu()

    while True:
        print("\nst-admin> ", end="", flush=True)
        key = get_single_key()
        print(key)

        if key in ("q", "ESC"):
            print("  Exiting st-admin.")
            break

        elif key == "?":
            _print_menu()

        elif key == "d":
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

        elif key == "a":
            print(f"\n  {'Provider':<14}  Model")
            print(f"  {'─' * 14}  {'─' * 36}")
            for make in ai_list:
                print(f"  {make:<14}  {settings_get_ai_model(make)}")

        elif key == "m":
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

        elif key == "v":
            print(f"\n  TTS voice: {settings_get_tts_voice()}")

        elif key == "V":
            subprocess.run(["st-voice"])

        elif key == "t":
            print(f"\n  Default template: {settings_get_default_template()}")

        elif key == "T":
            current = settings_get_default_template()
            print(f"\n  Current default template: {current}")
            new_tmpl = input("  New template name (blank to cancel): ").strip()
            if new_tmpl:
                _env_set("DEFAULT_TEMPLATE", new_tmpl)
                print(f"  ✓  Default template set to: {new_tmpl}  (written to .env)")

        elif key == "e":
            print(f"\n  Editor: {settings_get_editor()}")

        elif key == "E":
            current = settings_get_editor()
            print(f"\n  Current editor: {current}")
            new_editor = input(
                "  New editor (e.g. nano, code, micro — blank to cancel): "
            ).strip()
            if new_editor:
                _env_set("EDITOR", new_editor)
                print(f"  ✓  Editor set to: {new_editor}  (written to .env)")

        elif key == "I":
            print("\n  Seeding ~/.cross_templates/ from bundled defaults …")
            overwrite_ans = input(
                "  Overwrite existing files? [y/N]: "
            ).strip().lower()
            init_user_templates(overwrite=(overwrite_ans == "y"))

        elif key == "U":
            upgrade_cross()

        elif key == "C":
            cache_info()

        elif key == "X":
            try:
                ans = input("  Delete ALL cached AI responses? [y/N]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                ans = "n"
            if ans == "y":
                cache_clear()
            else:
                print("  Cancelled.")

        elif key == "K":
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

        elif key == "s":
            settings_show_all()

        else:
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

