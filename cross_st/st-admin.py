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
from mmd_startup import load_cross_env, _PROJECT_ROOT
from mmd_util import (seed_user_templates, _USER_TEMPLATES_DIR, _BUNDLED_TEMPLATES_DIR,
                      seed_stones_domains, _DEFAULT_USER_STONES_DIR, get_default_stones_dir)


# ── Paths ──────────────────────────────────────────────────────────────────────
_CROSSENV    = os.path.expanduser("~/.crossenv")
_models_path = os.path.join(_PROJECT_ROOT, ".ai_models")  # repo root, not cross_st/

load_cross_env()


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
        _row("✅", "~/.crossenv", "exists — will update")
    else:
        _row("⚠️", "~/.crossenv", "will be created")

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
    try:
        ans = input("\n  Continue with API key setup? [Y/n]: ").strip().lower()
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
    print("  At least one key is required.  Press Enter to skip any provider.\n")

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

    # ── Discourse (optional) ──────────────────────────────────────────────────
    print(f"\n  Discourse (optional)\n  {_SEP}")
    try:
        disc_ans = input("  Configure Discourse posting? [y/N]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        disc_ans = "n"

    discourse_json = existing.get("DISCOURSE", "")
    if disc_ans == "y":
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
            discourse_json = json.dumps({"sites": [{"slug": disc_slug,
                                                     "url":  disc_url,
                                                     "username": disc_user,
                                                     "api_key":  disc_key,
                                                     "category_id": int(disc_cat)}]})

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
    if discourse_json:
        _write("DISCOURSE", discourse_json)

    print(f"  ✅  Settings written to ~/.crossenv")

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
    print(f"\n  Setup complete!")
    print(f"  Create your first report:  st-new my_topic.prompt")
    print(f"  For help:                  st-man\n")


def settings_show_all() -> None:
    """Print a formatted summary of all current settings."""
    ai_list = get_ai_list()
    W = 26
    print(f"\n  {'Setting':<{W}}  Value")
    print(f"  {'─' * W}  {'─' * 36}")
    print(f"  {'Default AI':<{W}}  {settings_get_default_ai()}")
    for make in ai_list:
        print(f"  {'AI model: ' + make:<{W}}  {settings_get_ai_model(make)}")
    print(f"  {'TTS voice':<{W}}  {settings_get_tts_voice()}")
    print(f"  {'Default template':<{W}}  {settings_get_default_template()}")
    print(f"  {'Editor':<{W}}  {settings_get_editor()}")
    print(f"  {'Stones dir':<{W}}  {get_default_stones_dir()}")
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

    parser.add_argument(
        "--setup", action="store_true",
        help="Interactive first-run wizard: checks environment, collects API keys, "
             "writes ~/.crossenv",
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

    args = parser.parse_args()

    # ── Non-interactive operations (any flag → run and exit) ──────────────────
    if args.setup:
        setup_wizard()
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

    # ── Interactive mode ──────────────────────────────────────────────────────
    interactive_menu()


if __name__ == "__main__":
    main()

