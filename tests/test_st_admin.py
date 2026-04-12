"""
tests/test_st_admin.py — Regression tests for st-admin.py

Coverage:
    _env_get / _env_set
    settings_get_default_ai     — env resolution; fallback to AI_LIST[0]
    settings_set_default_ai     — valid provider accepted; invalid raises ValueError
    settings_get_ai_model       — .ai_models lookup; compiled-in fallback
    settings_set_ai_model       — create / update / append; no duplicate entries
    settings_get_tts_voice      — reads TTS_VOICE; default "en_US-lessac-medium"
    settings_get_default_template — reads DEFAULT_TEMPLATE; default "default"
    settings_get_editor         — reads EDITOR; default "vi"
    settings_show_all           — smoke test: no crash; expected labels in output
    CLI --show                  — prints all settings, returns cleanly
    CLI --get-default-ai        — prints current default AI name
    CLI --set-default-ai        — valid writes + confirmation; invalid exits 1
    CLI --set-ai-model          — valid MAKE=MODEL writes; bad format exits 1
    CLI --set-tts-voice         — writes TTS_VOICE to env
    CLI --set-template          — writes DEFAULT_TEMPLATE to env
    CLI --set-editor            — writes EDITOR to env
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# ── Load st-admin.py as a module (hyphen in filename) ─────────────────────────
_spec = importlib.util.spec_from_file_location(
    "st_admin", Path(__file__).parent.parent / "cross_st" / "st-admin.py"
)
st_admin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st_admin)

# Pull out the public functions under test
settings_get_default_ai       = st_admin.settings_get_default_ai
settings_set_default_ai       = st_admin.settings_set_default_ai
settings_get_ai_model         = st_admin.settings_get_ai_model
settings_set_ai_model         = st_admin.settings_set_ai_model
settings_get_tts_voice        = st_admin.settings_get_tts_voice
settings_get_default_template = st_admin.settings_get_default_template
settings_get_editor           = st_admin.settings_get_editor
settings_show_all             = st_admin.settings_show_all

from ai_handler import get_ai_list
AI_LIST = get_ai_list()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    """
    Redirect st_admin's .env and .ai_models to isolated temporary files so
    no test ever touches the real project settings.

    Returns a dict:
        {"env": Path,    # writable temp .env (initially empty)
         "models": Path} # temp .ai_models (initially absent — created on demand)
    """
    env_file    = tmp_path / ".env"
    models_file = tmp_path / ".ai_models"
    env_file.write_text("")   # set_key requires file to exist

    monkeypatch.setattr(st_admin, "_CROSSENV",    str(env_file))
    monkeypatch.setattr(st_admin, "_models_path", str(models_file))

    return {"env": env_file, "models": models_file}


# ─────────────────────────────────────────────────────────────────────────────
# _env_get / _env_set
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvHelpers:
    def test_get_missing_key_returns_default(self, monkeypatch):
        monkeypatch.delenv("_CROSS_MISSING_KEY_", raising=False)
        assert st_admin._env_get("_CROSS_MISSING_KEY_", "fallback") == "fallback"

    def test_get_present_key_returns_value(self, monkeypatch):
        monkeypatch.setenv("_CROSS_TEST_KEY_", "hello")
        assert st_admin._env_get("_CROSS_TEST_KEY_") == "hello"

    def test_get_empty_default_when_key_absent(self, monkeypatch):
        monkeypatch.delenv("_CROSS_ABSENT_", raising=False)
        assert st_admin._env_get("_CROSS_ABSENT_") == ""

    def test_set_updates_os_environ(self, tmp_settings, monkeypatch):
        monkeypatch.delenv("_CROSS_SET_TEST_", raising=False)
        st_admin._env_set("_CROSS_SET_TEST_", "world")
        assert os.environ.get("_CROSS_SET_TEST_") == "world"

    def test_set_writes_key_to_env_file(self, tmp_settings, monkeypatch):
        monkeypatch.delenv("_CROSS_WRITE_TEST_", raising=False)
        st_admin._env_set("_CROSS_WRITE_TEST_", "persisted")
        content = tmp_settings["env"].read_text()
        assert "_CROSS_WRITE_TEST_" in content
        assert "persisted" in content

    def test_set_overwrites_existing_key_in_file(self, tmp_settings, monkeypatch):
        monkeypatch.delenv("_CROSS_OW_TEST_", raising=False)
        st_admin._env_set("_CROSS_OW_TEST_", "first")
        st_admin._env_set("_CROSS_OW_TEST_", "second")
        content = tmp_settings["env"].read_text()
        assert "second" in content
        assert content.count("_CROSS_OW_TEST_") == 1


# ─────────────────────────────────────────────────────────────────────────────
# settings_get_default_ai
# ─────────────────────────────────────────────────────────────────────────────

class TestGetDefaultAi:
    def test_no_env_var_returns_first_in_list(self, monkeypatch):
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        assert settings_get_default_ai() == AI_LIST[0]

    def test_valid_env_var_returned(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_AI", AI_LIST[1])
        assert settings_get_default_ai() == AI_LIST[1]

    def test_all_valid_providers_accepted(self, monkeypatch):
        for make in AI_LIST:
            monkeypatch.setenv("DEFAULT_AI", make)
            assert settings_get_default_ai() == make

    def test_unknown_env_var_falls_back_to_first(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_AI", "nonexistent_make")
        assert settings_get_default_ai() == AI_LIST[0]

    def test_empty_env_var_falls_back_to_first(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_AI", "")
        assert settings_get_default_ai() == AI_LIST[0]

    def test_whitespace_only_falls_back_to_first(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_AI", "   ")
        assert settings_get_default_ai() == AI_LIST[0]

    def test_return_value_is_always_a_known_provider(self, monkeypatch):
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        result = settings_get_default_ai()
        assert result in AI_LIST


# ─────────────────────────────────────────────────────────────────────────────
# settings_set_default_ai
# ─────────────────────────────────────────────────────────────────────────────

class TestSetDefaultAi:
    def test_valid_provider_writes_to_os_environ(self, tmp_settings, monkeypatch):
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        settings_set_default_ai(AI_LIST[0])
        assert os.environ.get("DEFAULT_AI") == AI_LIST[0]

    def test_all_providers_accepted(self, tmp_settings, monkeypatch):
        for make in AI_LIST:
            monkeypatch.delenv("DEFAULT_AI", raising=False)
            settings_set_default_ai(make)
            assert os.environ.get("DEFAULT_AI") == make

    def test_invalid_provider_raises_value_error(self, tmp_settings):
        with pytest.raises(ValueError, match="Unknown AI provider"):
            settings_set_default_ai("not_a_real_provider")

    def test_invalid_provider_error_names_the_bad_value(self, tmp_settings):
        with pytest.raises(ValueError, match="badmake"):
            settings_set_default_ai("badmake")

    def test_invalid_provider_does_not_write_env(self, tmp_settings, monkeypatch):
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        try:
            settings_set_default_ai("bad_make")
        except ValueError:
            pass
        assert os.environ.get("DEFAULT_AI") is None

    def test_round_trip_set_then_get(self, tmp_settings, monkeypatch):
        target = AI_LIST[-1]
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        settings_set_default_ai(target)
        assert settings_get_default_ai() == target

    def test_overwrite_existing_value(self, tmp_settings, monkeypatch):
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        settings_set_default_ai(AI_LIST[0])
        settings_set_default_ai(AI_LIST[1])
        assert settings_get_default_ai() == AI_LIST[1]

    def test_writes_to_env_file(self, tmp_settings, monkeypatch):
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        settings_set_default_ai(AI_LIST[0])
        content = tmp_settings["env"].read_text()
        assert "DEFAULT_AI" in content
        assert AI_LIST[0] in content


# ─────────────────────────────────────────────────────────────────────────────
# settings_get_ai_model
# ─────────────────────────────────────────────────────────────────────────────

class TestGetAiModel:
    def test_missing_models_file_returns_handler_default(self, tmp_settings):
        # No .ai_models file — falls back to compiled-in handler default
        result = settings_get_ai_model("xai")
        assert isinstance(result, str)
        assert result not in ("", "unknown")

    def test_single_matching_entry(self, tmp_settings):
        tmp_settings["models"].write_text("xai=grok-99\n")
        assert settings_get_ai_model("xai") == "grok-99"

    def test_multiple_entries_correct_value_returned(self, tmp_settings):
        tmp_settings["models"].write_text(
            "xai=grok-3\nanthropic=claude-4\nopenai=gpt-6\n"
        )
        assert settings_get_ai_model("xai")       == "grok-3"
        assert settings_get_ai_model("anthropic") == "claude-4"
        assert settings_get_ai_model("openai")    == "gpt-6"

    def test_make_not_in_file_falls_back_to_handler(self, tmp_settings):
        tmp_settings["models"].write_text("anthropic=claude-test\n")
        result = settings_get_ai_model("xai")
        assert result not in ("", "unknown")
        assert "claude-test" not in result

    def test_comment_lines_are_skipped(self, tmp_settings):
        tmp_settings["models"].write_text("# this is a comment\nxai=grok-comment\n")
        assert settings_get_ai_model("xai") == "grok-comment"

    def test_blank_lines_are_skipped(self, tmp_settings):
        tmp_settings["models"].write_text("\n\nxai=grok-blank\n\n")
        assert settings_get_ai_model("xai") == "grok-blank"

    def test_whitespace_around_equals_stripped(self, tmp_settings):
        tmp_settings["models"].write_text("xai = grok-spaced\n")
        assert settings_get_ai_model("xai") == "grok-spaced"

    def test_unknown_make_with_empty_file_returns_unknown(self, tmp_settings):
        tmp_settings["models"].write_text("")
        assert settings_get_ai_model("nonexistent_make_xyz") == "unknown"

    def test_unknown_make_no_file_returns_unknown(self, tmp_settings):
        # models file absent
        assert settings_get_ai_model("nonexistent_make_xyz") == "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# settings_set_ai_model
# ─────────────────────────────────────────────────────────────────────────────

class TestSetAiModel:
    def test_creates_file_when_absent(self, tmp_settings):
        assert not tmp_settings["models"].exists()
        settings_set_ai_model("xai", "grok-new")
        assert tmp_settings["models"].exists()
        assert "xai=grok-new" in tmp_settings["models"].read_text()

    def test_appends_when_make_not_present(self, tmp_settings):
        tmp_settings["models"].write_text("anthropic=claude-test\n")
        settings_set_ai_model("xai", "grok-append")
        content = tmp_settings["models"].read_text()
        assert "anthropic=claude-test" in content
        assert "xai=grok-append" in content

    def test_updates_existing_entry(self, tmp_settings):
        tmp_settings["models"].write_text("xai=grok-old\n")
        settings_set_ai_model("xai", "grok-new")
        content = tmp_settings["models"].read_text()
        assert "xai=grok-new" in content
        assert "xai=grok-old" not in content

    def test_other_entries_preserved_on_update(self, tmp_settings):
        tmp_settings["models"].write_text(
            "anthropic=claude-ok\nxai=grok-old\nopenai=gpt-fine\n"
        )
        settings_set_ai_model("xai", "grok-updated")
        content = tmp_settings["models"].read_text()
        assert "anthropic=claude-ok" in content
        assert "openai=gpt-fine"     in content
        assert "xai=grok-updated"   in content

    def test_no_duplicate_entry_after_two_sets(self, tmp_settings):
        settings_set_ai_model("xai", "grok-first")
        settings_set_ai_model("xai", "grok-second")
        lines = [
            l for l in tmp_settings["models"].read_text().splitlines()
            if l.startswith("xai=")
        ]
        assert len(lines) == 1
        assert "grok-second" in lines[0]

    def test_round_trip_get_after_set(self, tmp_settings):
        settings_set_ai_model("openai", "gpt-round-trip")
        assert settings_get_ai_model("openai") == "gpt-round-trip"

    def test_all_providers_can_be_set(self, tmp_settings):
        for make in AI_LIST:
            model_name = f"model-{make}-test"
            settings_set_ai_model(make, model_name)
            assert settings_get_ai_model(make) == model_name


# ─────────────────────────────────────────────────────────────────────────────
# settings_get_tts_voice / settings_get_default_template / settings_get_editor
# ─────────────────────────────────────────────────────────────────────────────

class TestOtherGetters:
    # TTS_VOICE
    def test_tts_voice_hardcoded_default(self, monkeypatch):
        monkeypatch.delenv("TTS_VOICE", raising=False)
        assert settings_get_tts_voice() == "en_US-lessac-medium"

    def test_tts_voice_reads_env(self, monkeypatch):
        monkeypatch.setenv("TTS_VOICE", "en_US-ryan-medium")
        assert settings_get_tts_voice() == "en_US-ryan-medium"

    def test_tts_voice_returns_string(self, monkeypatch):
        monkeypatch.delenv("TTS_VOICE", raising=False)
        assert isinstance(settings_get_tts_voice(), str)

    # DEFAULT_TEMPLATE
    def test_template_hardcoded_default(self, monkeypatch):
        monkeypatch.delenv("DEFAULT_TEMPLATE", raising=False)
        assert settings_get_default_template() == "default"

    def test_template_reads_env(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_TEMPLATE", "my_custom_template")
        assert settings_get_default_template() == "my_custom_template"

    # EDITOR
    def test_editor_hardcoded_default(self, monkeypatch):
        monkeypatch.delenv("EDITOR", raising=False)
        assert settings_get_editor() == "vi"

    def test_editor_reads_env(self, monkeypatch):
        monkeypatch.setenv("EDITOR", "nano")
        assert settings_get_editor() == "nano"


# ─────────────────────────────────────────────────────────────────────────────
# settings_show_all
# ─────────────────────────────────────────────────────────────────────────────

class TestSettingsShowAll:
    def test_no_crash(self, tmp_settings, capsys):
        settings_show_all()  # must not raise
        out = capsys.readouterr().out
        assert len(out) > 0

    def test_contains_default_ai_label(self, tmp_settings, capsys):
        settings_show_all()
        assert "Default AI" in capsys.readouterr().out

    def test_contains_every_provider(self, tmp_settings, capsys):
        settings_show_all()
        out = capsys.readouterr().out
        for make in AI_LIST:
            assert make in out, f"Provider {make!r} not found in settings_show_all() output"

    def test_contains_tts_voice_label(self, tmp_settings, capsys):
        settings_show_all()
        assert "TTS voice" in capsys.readouterr().out

    def test_contains_template_label(self, tmp_settings, capsys):
        settings_show_all()
        assert "template" in capsys.readouterr().out.lower()

    def test_contains_editor_label(self, tmp_settings, capsys):
        settings_show_all()
        assert "Editor" in capsys.readouterr().out

    def test_current_default_ai_appears_in_output(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.setenv("DEFAULT_AI", AI_LIST[0])
        settings_show_all()
        out = capsys.readouterr().out
        assert AI_LIST[0] in out

    def test_model_override_appears_in_output(self, tmp_settings, capsys):
        tmp_settings["models"].write_text("xai=grok-show-test\n")
        settings_show_all()
        assert "grok-show-test" in capsys.readouterr().out


# ─────────────────────────────────────────────────────────────────────────────
# CLI — main() via monkeypatched sys.argv
# ─────────────────────────────────────────────────────────────────────────────

class TestCLI:
    """
    Drive the non-interactive CLI by monkeypatching sys.argv and calling
    st_admin.main().  Every test uses tmp_settings so no real .env or
    .ai_models file is touched.
    """

    # ── --show ────────────────────────────────────────────────────────────────

    def test_show_returns_cleanly(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["st-admin", "--show"])
        st_admin.main()          # should return without SystemExit
        assert "Default AI" in capsys.readouterr().out

    def test_show_lists_all_providers(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["st-admin", "--show"])
        st_admin.main()
        out = capsys.readouterr().out
        for make in AI_LIST:
            assert make in out

    # ── --get-default-ai ──────────────────────────────────────────────────────

    def test_get_default_ai_prints_a_known_provider(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        monkeypatch.setattr(sys, "argv", ["st-admin", "--get-default-ai"])
        st_admin.main()
        out = capsys.readouterr().out.strip()
        assert out in AI_LIST

    def test_get_default_ai_reflects_env_var(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.setenv("DEFAULT_AI", AI_LIST[1])
        monkeypatch.setattr(sys, "argv", ["st-admin", "--get-default-ai"])
        st_admin.main()
        assert capsys.readouterr().out.strip() == AI_LIST[1]

    # ── --set-default-ai ─────────────────────────────────────────────────────

    def test_set_default_ai_valid_prints_confirmation(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-default-ai", AI_LIST[0]])
        st_admin.main()
        out = capsys.readouterr().out
        assert "✓" in out
        assert AI_LIST[0] in out

    def test_set_default_ai_valid_persists(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.delenv("DEFAULT_AI", raising=False)
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-default-ai", AI_LIST[0]])
        st_admin.main()
        capsys.readouterr()
        assert settings_get_default_ai() == AI_LIST[0]

    def test_set_default_ai_invalid_exits_1(self, tmp_settings, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-default-ai", "bad_ai_make"])
        with pytest.raises(SystemExit) as exc_info:
            st_admin.main()
        assert exc_info.value.code == 1

    def test_set_default_ai_invalid_prints_error(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-default-ai", "bad_ai_make"])
        with pytest.raises(SystemExit):
            st_admin.main()
        err = capsys.readouterr().err
        assert "✗" in err or "bad_ai_make" in err

    def test_set_default_ai_each_valid_provider(self, tmp_settings, monkeypatch, capsys):
        for make in AI_LIST:
            monkeypatch.delenv("DEFAULT_AI", raising=False)
            monkeypatch.setattr(sys, "argv", ["st-admin", "--set-default-ai", make])
            st_admin.main()
            capsys.readouterr()
            assert settings_get_default_ai() == make

    # ── --set-ai-model ────────────────────────────────────────────────────────

    def test_set_ai_model_valid_prints_confirmation(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-ai-model", "xai=grok-cli"])
        st_admin.main()
        out = capsys.readouterr().out
        assert "✓" in out

    def test_set_ai_model_valid_persists(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-ai-model", "xai=grok-cli-persist"])
        st_admin.main()
        capsys.readouterr()
        assert settings_get_ai_model("xai") == "grok-cli-persist"

    def test_set_ai_model_bad_format_exits_1(self, tmp_settings, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-ai-model", "badformat-no-equals"])
        with pytest.raises(SystemExit) as exc_info:
            st_admin.main()
        assert exc_info.value.code == 1

    def test_set_ai_model_strips_whitespace_around_equals(self, tmp_settings, monkeypatch, capsys):
        # argparse delivers the whole "xai = grok-ws" as a single string
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-ai-model", "xai = grok-ws"])
        st_admin.main()
        capsys.readouterr()
        assert settings_get_ai_model("xai") == "grok-ws"

    # ── --set-tts-voice ───────────────────────────────────────────────────────

    def test_set_tts_voice_prints_confirmation(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.delenv("TTS_VOICE", raising=False)
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-tts-voice", "en_US-ryan-medium"])
        st_admin.main()
        assert "✓" in capsys.readouterr().out

    def test_set_tts_voice_persists(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.delenv("TTS_VOICE", raising=False)
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-tts-voice", "en_US-ryan-medium"])
        st_admin.main()
        capsys.readouterr()
        assert settings_get_tts_voice() == "en_US-ryan-medium"

    # ── --set-template ────────────────────────────────────────────────────────

    def test_set_template_prints_confirmation(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.delenv("DEFAULT_TEMPLATE", raising=False)
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-template", "my_tpl"])
        st_admin.main()
        assert "✓" in capsys.readouterr().out

    def test_set_template_persists(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.delenv("DEFAULT_TEMPLATE", raising=False)
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-template", "my_tpl"])
        st_admin.main()
        capsys.readouterr()
        assert settings_get_default_template() == "my_tpl"

    # ── --set-editor ──────────────────────────────────────────────────────────

    def test_set_editor_prints_confirmation(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-editor", "nano"])
        st_admin.main()
        assert "✓" in capsys.readouterr().out

    def test_set_editor_persists(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.setattr(sys, "argv", ["st-admin", "--set-editor", "nano"])
        st_admin.main()
        capsys.readouterr()
        assert settings_get_editor() == "nano"


# ─────────────────────────────────────────────────────────────────────────────
# discourse_manage  (DIS-3)
# ─────────────────────────────────────────────────────────────────────────────

import builtins
import json as _json  # noqa: F401 — used in test helpers below

_DISCOURSE_TEST_CAT_ID = st_admin._DISCOURSE_TEST_CATEGORY_ID  # 6


def _discourse_env(monkeypatch, *, url="", user="", api_key="",
                   cat_id="", priv_slug="", discourse_json=""):
    """Helper: set all DISCOURSE_* and DISCOURSE env vars via monkeypatch."""
    for var, val in [
        ("DISCOURSE_URL",                    url),
        ("DISCOURSE_USERNAME",               user),
        ("DISCOURSE_API_KEY",               api_key),
        ("DISCOURSE_CATEGORY_ID",           cat_id),
        ("DISCOURSE_PRIVATE_CATEGORY_SLUG", priv_slug),
        ("DISCOURSE",                        discourse_json),
    ]:
        if val:
            monkeypatch.setenv(var, val)
        else:
            monkeypatch.delenv(var, raising=False)


def _make_discourse_json(url="https://crossai.dev", user="alice",
                          api_key="k", cat_id=42, slug="crossai.dev") -> str:
    return _json.dumps({"sites": [{"slug": slug, "url": url,
                                   "username": user, "api_key": api_key,
                                   "category_id": cat_id}]})


class TestDiscourseManage:

    # ── No config ─────────────────────────────────────────────────────────────

    def test_no_config_prints_friendly_message(self, tmp_settings, monkeypatch, capsys):
        _discourse_env(monkeypatch)  # all blank
        st_admin.discourse_manage()
        out = capsys.readouterr().out
        assert "No Discourse configuration" in out

    def test_no_config_suggests_discourse_setup(self, tmp_settings, monkeypatch, capsys):
        _discourse_env(monkeypatch)
        st_admin.discourse_manage()
        assert "--discourse-setup" in capsys.readouterr().out

    def test_no_config_does_not_crash(self, tmp_settings, monkeypatch):
        _discourse_env(monkeypatch)
        st_admin.discourse_manage()  # must not raise

    # ── First-run migration ───────────────────────────────────────────────────

    def test_migration_builds_discourse_json(self, tmp_settings, monkeypatch, capsys):
        """Flat keys present, no DISCOURSE JSON → JSON built and written."""
        _discourse_env(monkeypatch, url="https://crossai.dev", user="alice",
                       api_key="testkey", cat_id="42", priv_slug="alice-private")
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin.discourse_manage()
        capsys.readouterr()
        discourse_val = os.environ.get("DISCOURSE", "")
        assert discourse_val, "DISCOURSE JSON should have been written"
        data = _json.loads(discourse_val)
        sites = data.get("sites", [])
        assert len(sites) == 1
        assert sites[0]["url"] == "https://crossai.dev"
        assert sites[0]["username"] == "alice"
        assert sites[0]["category_id"] == 42

    def test_migration_prints_confirmation(self, tmp_settings, monkeypatch, capsys):
        _discourse_env(monkeypatch, url="https://crossai.dev", user="alice",
                       api_key="key", cat_id="42")
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin.discourse_manage()
        out = capsys.readouterr().out
        assert "initialised" in out

    def test_migration_not_triggered_when_json_already_present(
            self, tmp_settings, monkeypatch, capsys):
        existing = _make_discourse_json(cat_id=99)
        _discourse_env(monkeypatch, url="https://crossai.dev", user="alice",
                       api_key="key", cat_id="42", discourse_json=existing)
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin.discourse_manage()
        out = capsys.readouterr().out
        assert "initialised" not in out

    # ── Display ───────────────────────────────────────────────────────────────

    def test_shows_site_url(self, tmp_settings, monkeypatch, capsys):
        _discourse_env(monkeypatch, discourse_json=_make_discourse_json())
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin.discourse_manage()
        assert "crossai.dev" in capsys.readouterr().out

    def test_shows_username(self, tmp_settings, monkeypatch, capsys):
        _discourse_env(monkeypatch, discourse_json=_make_discourse_json(user="bob"))
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin.discourse_manage()
        assert "bob" in capsys.readouterr().out

    def test_shows_test_category_name_when_active(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json(cat_id=_DISCOURSE_TEST_CAT_ID)
        _discourse_env(monkeypatch, discourse_json=j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin.discourse_manage()
        assert st_admin._DISCOURSE_TEST_CATEGORY_NAME in capsys.readouterr().out

    # ── Category switching ────────────────────────────────────────────────────

    def test_choice_2_sets_test_category(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json(cat_id=42)
        _discourse_env(monkeypatch, cat_id="42", priv_slug="alice-private",
                       discourse_json=j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "2")
        st_admin.discourse_manage()
        capsys.readouterr()
        data = _json.loads(os.environ["DISCOURSE"])
        assert data["sites"][0]["category_id"] == _DISCOURSE_TEST_CAT_ID

    def test_choice_1_restores_private_category(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json(cat_id=_DISCOURSE_TEST_CAT_ID)
        _discourse_env(monkeypatch, cat_id="42", priv_slug="alice-private",
                       discourse_json=j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "1")
        st_admin.discourse_manage()
        capsys.readouterr()
        data = _json.loads(os.environ["DISCOURSE"])
        assert data["sites"][0]["category_id"] == 42

    def test_choice_3_manual_id(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json(cat_id=42)
        _discourse_env(monkeypatch, discourse_json=j)
        responses = iter(["3", "99"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
        st_admin.discourse_manage()
        capsys.readouterr()
        data = _json.loads(os.environ["DISCOURSE"])
        assert data["sites"][0]["category_id"] == 99

    def test_choice_3_invalid_id_no_change(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json(cat_id=42)
        _discourse_env(monkeypatch, discourse_json=j)
        responses = iter(["3", "notanumber"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
        st_admin.discourse_manage()
        capsys.readouterr()
        data = _json.loads(os.environ["DISCOURSE"])
        assert data["sites"][0]["category_id"] == 42  # unchanged

    def test_choice_q_no_change(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json(cat_id=42)
        _discourse_env(monkeypatch, discourse_json=j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin.discourse_manage()
        capsys.readouterr()
        data = _json.loads(os.environ["DISCOURSE"])
        assert data["sites"][0]["category_id"] == 42  # unchanged

    def test_switch_prints_confirmation(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json(cat_id=42)
        _discourse_env(monkeypatch, discourse_json=j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "2")
        st_admin.discourse_manage()
        out = capsys.readouterr().out
        assert "✓" in out

    # ── CLI --discourse ───────────────────────────────────────────────────────

    def test_cli_discourse_flag_no_config(self, tmp_settings, monkeypatch, capsys):
        _discourse_env(monkeypatch)
        monkeypatch.setattr(sys, "argv", ["st-admin", "--discourse"])
        st_admin.main()
        assert "No Discourse configuration" in capsys.readouterr().out

    def test_cli_discourse_flag_switches_category(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json(cat_id=42)
        _discourse_env(monkeypatch, discourse_json=j)
        monkeypatch.setattr(sys, "argv", ["st-admin", "--discourse"])
        monkeypatch.setattr("builtins.input", lambda prompt="": "2")
        st_admin.main()
        capsys.readouterr()
        data = _json.loads(os.environ["DISCOURSE"])
        assert data["sites"][0]["category_id"] == _DISCOURSE_TEST_CAT_ID


# ─────────────────────────────────────────────────────────────────────────────
# check_tos_flag  (TAP-4)
# ─────────────────────────────────────────────────────────────────────────────

from unittest.mock import patch as _patch

_CURRENT_TOS  = "2026-04-07"
_CURRENT_PRIV = "2026-04-07"
_STALE_TOS    = "2025-01-01"


def _site_json(tos_version=None, priv_version=None, tos_agreed_at=None,
               url="https://crossai.dev", user="alice"):
    """Build a DISCOURSE JSON string with an optional TOS version recorded."""
    site = {"slug": "crossai.dev", "url": url, "username": user,
            "api_key": "k", "category_id": 42}
    if tos_version:
        site["tos_version"]     = tos_version
    if priv_version:
        site["privacy_version"] = priv_version
    if tos_agreed_at:
        site["tos_agreed_at"]   = tos_agreed_at
    return _json.dumps({"sites": [site]})


class TestCheckTos:
    """TAP-4: st-admin --check-tos and check_tos_flag()."""

    # ── No config ─────────────────────────────────────────────────────────────

    def test_no_discourse_config_prints_message(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.delenv("DISCOURSE", raising=False)
        st_admin.check_tos_flag()
        assert "No Discourse configuration" in capsys.readouterr().out

    def test_no_crossai_site_prints_message(self, tmp_settings, monkeypatch, capsys):
        j = _json.dumps({"sites": [{"slug": "other", "url": "https://forum.example.com",
                                    "username": "alice", "api_key": "k", "category_id": 1}]})
        monkeypatch.setenv("DISCOURSE", j)
        st_admin.check_tos_flag()
        out = capsys.readouterr().out
        assert "crossai.dev" in out.lower() or "No crossai.dev" in out

    # ── Already up to date ────────────────────────────────────────────────────

    def test_up_to_date_prints_no_action_needed(self, tmp_settings, monkeypatch, capsys):
        j = _site_json(tos_version=_CURRENT_TOS, priv_version=_CURRENT_PRIV)
        monkeypatch.setenv("DISCOURSE", j)
        with _patch("cross_st.discourse_provision.get_tos_versions",
                    return_value={"tos_version": _CURRENT_TOS,
                                  "privacy_version": _CURRENT_PRIV}):
            st_admin.check_tos_flag()
        out = capsys.readouterr().out
        assert "No action needed" in out

    def test_up_to_date_does_not_prompt_acceptance(self, tmp_settings, monkeypatch, capsys):
        j = _site_json(tos_version=_CURRENT_TOS, priv_version=_CURRENT_PRIV)
        monkeypatch.setenv("DISCOURSE", j)
        with _patch("cross_st.discourse_provision.get_tos_versions",
                    return_value={"tos_version": _CURRENT_TOS,
                                  "privacy_version": _CURRENT_PRIV}):
            with _patch("builtins.input") as mock_input:
                st_admin.check_tos_flag()
        mock_input.assert_not_called()

    # ── Stale TOS ─────────────────────────────────────────────────────────────

    def test_stale_version_shows_update_warning(self, tmp_settings, monkeypatch, capsys):
        j = _site_json(tos_version=_STALE_TOS, priv_version=_STALE_TOS)
        monkeypatch.setenv("DISCOURSE", j)
        with _patch("cross_st.discourse_provision.get_tos_versions",
                    return_value={"tos_version": _CURRENT_TOS,
                                  "privacy_version": _CURRENT_PRIV}):
            with _patch("builtins.input", return_value="no"):
                st_admin.check_tos_flag()
        out = capsys.readouterr().out
        assert "updated" in out.lower() or "⚠️" in out

    def test_stale_accepted_updates_discourse_json(self, tmp_settings, monkeypatch, capsys):
        """User accepts → DISCOURSE JSON updated with new TOS version."""
        j = _site_json(tos_version=_STALE_TOS, priv_version=_STALE_TOS)
        monkeypatch.setenv("DISCOURSE", j)
        with _patch("cross_st.discourse_provision.get_tos_versions",
                    return_value={"tos_version": _CURRENT_TOS,
                                  "privacy_version": _CURRENT_PRIV}):
            with _patch("cross_st.discourse_provision.record_tos_acceptance",
                        return_value=True):
                with _patch("builtins.input", return_value="yes"):
                    st_admin.check_tos_flag()
        capsys.readouterr()
        disc = _json.loads(os.environ.get("DISCOURSE", "{}"))
        site = disc["sites"][0]
        assert site["tos_version"] == _CURRENT_TOS

    def test_stale_declined_does_not_update_discourse_json(self, tmp_settings, monkeypatch, capsys):
        """User declines → DISCOURSE JSON NOT updated."""
        j = _site_json(tos_version=_STALE_TOS, priv_version=_STALE_TOS)
        monkeypatch.setenv("DISCOURSE", j)
        with _patch("cross_st.discourse_provision.get_tos_versions",
                    return_value={"tos_version": _CURRENT_TOS,
                                  "privacy_version": _CURRENT_PRIV}):
            with _patch("builtins.input", return_value="no"):
                st_admin.check_tos_flag()
        capsys.readouterr()
        disc = _json.loads(os.environ.get("DISCOURSE", "{}"))
        assert disc["sites"][0]["tos_version"] == _STALE_TOS  # unchanged

    def test_no_stored_tos_shows_info_message(self, tmp_settings, monkeypatch, capsys):
        """Config without tos_version → info banner + T&C displayed."""
        j = _site_json()  # no tos fields
        monkeypatch.setenv("DISCOURSE", j)
        with _patch("cross_st.discourse_provision.get_tos_versions",
                    return_value={"tos_version": _CURRENT_TOS,
                                  "privacy_version": _CURRENT_PRIV}):
            with _patch("cross_st.discourse_provision.record_tos_acceptance",
                        return_value=True):
                with _patch("builtins.input", return_value="yes"):
                    st_admin.check_tos_flag()
        out = capsys.readouterr().out
        assert "accepted" in out.lower() or "✅" in out

    # ── CLI --check-tos flag ──────────────────────────────────────────────────

    def test_cli_check_tos_no_config(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.delenv("DISCOURSE", raising=False)
        monkeypatch.setattr(sys, "argv", ["st-admin", "--check-tos"])
        st_admin.main()
        assert "No Discourse configuration" in capsys.readouterr().out

    def test_cli_check_tos_up_to_date(self, tmp_settings, monkeypatch, capsys):
        j = _site_json(tos_version=_CURRENT_TOS, priv_version=_CURRENT_PRIV)
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr(sys, "argv", ["st-admin", "--check-tos"])
        with _patch("cross_st.discourse_provision.get_tos_versions",
                    return_value={"tos_version": _CURRENT_TOS,
                                  "privacy_version": _CURRENT_PRIV}):
            st_admin.main()
        assert "No action needed" in capsys.readouterr().out


# ─────────────────────────────────────────────────────────────────────────────
# _run_discourse_setup version check  (TAP-4)
# ─────────────────────────────────────────────────────────────────────────────

class TestRunDiscourseSetupVersionCheck:
    """TAP-4: _run_discourse_setup() returns early / re-accepts based on TOS version."""

    def test_returns_early_when_tos_current(self, tmp_settings, monkeypatch, capsys):
        """If crossai.dev already configured with current TOS → 'up to date', no wizard."""
        j = _site_json(tos_version=_CURRENT_TOS, priv_version=_CURRENT_PRIV)
        monkeypatch.setenv("DISCOURSE", j)
        with _patch("cross_st.discourse_provision.get_tos_versions",
                    return_value={"tos_version": _CURRENT_TOS,
                                  "privacy_version": _CURRENT_PRIV}):
            st_admin._run_discourse_setup()
        out = capsys.readouterr().out
        assert "up to date" in out.lower() or "No action needed" in out

    def test_reaccept_flow_when_tos_stale(self, tmp_settings, monkeypatch, capsys):
        """Stale TOS + existing user → re-acceptance banner shown, full wizard skipped."""
        j = _site_json(tos_version=_STALE_TOS, priv_version=_STALE_TOS)
        monkeypatch.setenv("DISCOURSE", j)
        with _patch("cross_st.discourse_provision.get_tos_versions",
                    return_value={"tos_version": _CURRENT_TOS,
                                  "privacy_version": _CURRENT_PRIV}):
            with _patch("cross_st.discourse_provision.record_tos_acceptance",
                        return_value=True):
                with _patch("builtins.input", return_value="yes"):
                    st_admin._run_discourse_setup()
        out = capsys.readouterr().out
        assert "accepted" in out.lower() or "✅" in out
        # Stored TOS version updated
        disc = _json.loads(os.environ.get("DISCOURSE", "{}"))
        assert disc["sites"][0]["tos_version"] == _CURRENT_TOS

    def test_reaccept_declined_prints_warning(self, tmp_settings, monkeypatch, capsys):
        j = _site_json(tos_version=_STALE_TOS, priv_version=_STALE_TOS)
        monkeypatch.setenv("DISCOURSE", j)
        with _patch("cross_st.discourse_provision.get_tos_versions",
                    return_value={"tos_version": _CURRENT_TOS,
                                  "privacy_version": _CURRENT_PRIV}):
            with _patch("builtins.input", return_value="no"):
                st_admin._run_discourse_setup()
        out = capsys.readouterr().out
        assert "must accept" in out.lower() or "⚠️" in out


# ─────────────────────────────────────────────────────────────────────────────
# _discourse_select_site  (POST-2)
# ─────────────────────────────────────────────────────────────────────────────

def _make_multi_site_json(sites=None) -> str:
    if sites is None:
        sites = [
            {"slug": "crossai.dev", "url": "https://crossai.dev",
             "username": "alice", "api_key": "k1", "category_id": 42},
            {"slug": "my-forum", "url": "https://my-forum.example.com",
             "username": "alice", "api_key": "k2", "category_id": 10},
        ]
    return _json.dumps({"sites": sites})


class TestDiscourseSelectSite:
    """POST-2: _discourse_select_site() in interactive menu (D key)."""

    def test_no_config_prints_message(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.delenv("DISCOURSE", raising=False)
        st_admin._discourse_select_site()
        assert "No Discourse configuration" in capsys.readouterr().out

    def test_single_site_prints_nothing_to_switch(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json()
        monkeypatch.setenv("DISCOURSE", j)
        st_admin._discourse_select_site()
        out = capsys.readouterr().out
        assert "Nothing to switch" in out

    def test_multi_site_shows_all_sites(self, tmp_settings, monkeypatch, capsys):
        j = _make_multi_site_json()
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin._discourse_select_site()
        out = capsys.readouterr().out
        assert "crossai.dev" in out
        assert "my-forum" in out

    def test_multi_site_marks_active_site(self, tmp_settings, monkeypatch, capsys):
        j = _make_multi_site_json()
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setenv("DISCOURSE_SITE", "my-forum")
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin._discourse_select_site()
        out = capsys.readouterr().out
        assert "← active" in out

    def test_select_site_writes_discourse_site_env(self, tmp_settings, monkeypatch, capsys):
        j = _make_multi_site_json()
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.delenv("DISCOURSE_SITE", raising=False)
        monkeypatch.setattr("builtins.input", lambda prompt="": "2")
        st_admin._discourse_select_site()
        capsys.readouterr()
        assert os.environ.get("DISCOURSE_SITE") == "my-forum"

    def test_select_site_prints_confirmation(self, tmp_settings, monkeypatch, capsys):
        j = _make_multi_site_json()
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "1")
        st_admin._discourse_select_site()
        assert "✓" in capsys.readouterr().out

    def test_quit_does_not_change_site(self, tmp_settings, monkeypatch, capsys):
        j = _make_multi_site_json()
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setenv("DISCOURSE_SITE", "crossai.dev")
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin._discourse_select_site()
        capsys.readouterr()
        assert os.environ.get("DISCOURSE_SITE") == "crossai.dev"

    def test_invalid_choice_prints_error(self, tmp_settings, monkeypatch, capsys):
        j = _make_multi_site_json()
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "99")
        st_admin._discourse_select_site()
        assert "Invalid" in capsys.readouterr().out


# ─────────────────────────────────────────────────────────────────────────────
# _discourse_select_category  (POST-2)
# ─────────────────────────────────────────────────────────────────────────────

def _make_discourse_json_with_private(url="https://crossai.dev", user="alice",
                                       api_key="k", cat_id=42, priv_id=42,
                                       priv_slug="alice-private",
                                       slug="crossai.dev") -> str:
    return _json.dumps({"sites": [{
        "slug": slug, "url": url, "username": user, "api_key": api_key,
        "category_id": cat_id,
        "private_category_id": priv_id,
        "private_category_slug": priv_slug,
    }]})


class TestDiscourseSelectCategory:
    """POST-2: _discourse_select_category() in interactive menu (c key)."""

    def test_no_config_prints_message(self, tmp_settings, monkeypatch, capsys):
        monkeypatch.delenv("DISCOURSE", raising=False)
        st_admin._discourse_select_category()
        assert "No Discourse configuration" in capsys.readouterr().out

    def test_shows_test_category_option(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json_with_private()
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin._discourse_select_category()
        out = capsys.readouterr().out
        assert st_admin._DISCOURSE_TEST_CATEGORY_NAME in out

    def test_shows_private_category_when_configured(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json_with_private(priv_slug="alice-private")
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin._discourse_select_category()
        out = capsys.readouterr().out
        assert "alice-private" in out

    def test_marks_active_category(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json_with_private(cat_id=_DISCOURSE_TEST_CAT_ID,
                                               priv_id=42)
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin._discourse_select_category()
        out = capsys.readouterr().out
        assert "(current)" in out

    def test_choice_2_sets_test_category(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json_with_private(cat_id=42, priv_id=42)
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "2")
        st_admin._discourse_select_category()
        capsys.readouterr()
        data = _json.loads(os.environ["DISCOURSE"])
        assert data["sites"][0]["category_id"] == _DISCOURSE_TEST_CAT_ID

    def test_choice_1_sets_private_category(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json_with_private(cat_id=_DISCOURSE_TEST_CAT_ID, priv_id=42)
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "1")
        st_admin._discourse_select_category()
        capsys.readouterr()
        data = _json.loads(os.environ["DISCOURSE"])
        assert data["sites"][0]["category_id"] == 42

    def test_choice_q_no_change(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json_with_private(cat_id=42)
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin._discourse_select_category()
        capsys.readouterr()
        data = _json.loads(os.environ["DISCOURSE"])
        assert data["sites"][0]["category_id"] == 42  # unchanged

    def test_switch_prints_confirmation(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json_with_private(cat_id=42, priv_id=42)
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "2")
        st_admin._discourse_select_category()
        assert "✓" in capsys.readouterr().out

    def test_invalid_choice_prints_error(self, tmp_settings, monkeypatch, capsys):
        j = _make_discourse_json_with_private(cat_id=42)
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "9")
        st_admin._discourse_select_category()
        assert "Invalid" in capsys.readouterr().out

    def test_choice_1_without_explicit_private_falls_back_to_active(
            self, tmp_settings, monkeypatch, capsys):
        """No private_category_id → choice 1 falls back to category_id."""
        j = _make_discourse_json(cat_id=42)  # no private_category_id
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "1")
        st_admin._discourse_select_category()
        capsys.readouterr()
        data = _json.loads(os.environ["DISCOURSE"])
        # Falls back to active cat_id — category stays 42
        assert data["sites"][0]["category_id"] == 42

    def test_private_option_always_shown_even_without_private_id(
            self, tmp_settings, monkeypatch, capsys):
        """Option 1 (private) must always appear, even without private_category_id."""
        j = _make_discourse_json(cat_id=42)  # no private_category_id
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin._discourse_select_category()
        out = capsys.readouterr().out
        assert "1." in out  # option 1 always present

    def test_private_label_uses_username_when_no_slug(
            self, tmp_settings, monkeypatch, capsys):
        """With username 'alice' and no slug → label shows 'alice-private'."""
        j = _make_discourse_json(cat_id=42, user="alice")
        monkeypatch.setenv("DISCOURSE", j)
        monkeypatch.setattr("builtins.input", lambda prompt="": "q")
        st_admin._discourse_select_category()
        out = capsys.readouterr().out
        assert "alice-private" in out


