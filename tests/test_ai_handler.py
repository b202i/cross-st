"""
Tests for ai_handler.py — the cross_st shim that re-exports cross_ai_core.ai_handler.

All tests avoid real API calls.  process_prompt() is never invoked here;
provider functions are exercised with hand-crafted response dicts.
"""
import os
import pytest
from unittest.mock import patch

from ai_handler import (
    AI_LIST,
    AIResponse,
    _API_KEY_ENV_VARS,
    check_api_key,
    get_ai_list,
    get_ai_make,
    get_ai_model,
    get_content,
    get_content_auto,
    get_default_ai,
    put_content,
    put_content_auto,
)


# ── get_ai_list ───────────────────────────────────────────────────────────────

class TestGetAIList:
    def test_returns_list(self):
        assert isinstance(get_ai_list(), list)

    def test_known_providers_present(self):
        ai_list = get_ai_list()
        for provider in ("xai", "anthropic", "openai", "perplexity", "gemini"):
            assert provider in ai_list

    def test_matches_AI_LIST_constant(self):
        assert get_ai_list() == AI_LIST

    def test_non_empty(self):
        assert len(get_ai_list()) > 0


# ── get_default_ai ────────────────────────────────────────────────────────────

class TestGetDefaultAI:
    def test_returns_string(self):
        assert isinstance(get_default_ai(), str)

    def test_result_is_in_ai_list(self):
        assert get_default_ai() in get_ai_list()

    def test_env_override_valid(self):
        with patch.dict(os.environ, {"DEFAULT_AI": "anthropic"}):
            assert get_default_ai() == "anthropic"

    def test_env_override_all_providers(self):
        for provider in get_ai_list():
            with patch.dict(os.environ, {"DEFAULT_AI": provider}):
                assert get_default_ai() == provider

    def test_invalid_env_falls_back_to_first(self):
        with patch.dict(os.environ, {"DEFAULT_AI": "not_a_real_ai"}):
            result = get_default_ai()
        assert result == AI_LIST[0]

    def test_empty_env_uses_first(self):
        env_clean = {k: v for k, v in os.environ.items() if k != "DEFAULT_AI"}
        with patch.dict(os.environ, env_clean, clear=True):
            result = get_default_ai()
        assert result == AI_LIST[0]


# ── get_ai_model ──────────────────────────────────────────────────────────────

class TestGetAIModel:
    def test_known_provider_returns_non_empty_string(self):
        model = get_ai_model("xai")
        assert isinstance(model, str)
        assert len(model) > 0

    def test_all_providers_have_models(self):
        for provider in ("xai", "anthropic", "openai", "perplexity", "gemini"):
            model = get_ai_model(provider)
            assert isinstance(model, str) and len(model) > 0

    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported AI model"):
            get_ai_model("totally_unknown")

    def test_xai_env_override(self):
        with patch.dict(os.environ, {"XAI_MODEL": "grok-3-latest"}):
            assert get_ai_model("xai") == "grok-3-latest"

    def test_anthropic_env_override(self):
        with patch.dict(os.environ, {"ANTHROPIC_MODEL": "claude-sonnet-4-5"}):
            assert get_ai_model("anthropic") == "claude-sonnet-4-5"

    def test_openai_env_override(self):
        with patch.dict(os.environ, {"OPENAI_MODEL": "gpt-5"}):
            assert get_ai_model("openai") == "gpt-5"

    def test_env_var_cleared_returns_default(self):
        """When the env var is empty, the handler default is returned."""
        env_clean = {k: v for k, v in os.environ.items() if k != "XAI_MODEL"}
        with patch.dict(os.environ, env_clean, clear=True):
            model = get_ai_model("xai")
        assert isinstance(model, str) and len(model) > 0


# ── get_ai_make ───────────────────────────────────────────────────────────────

class TestGetAIMake:
    def test_xai_returns_xai(self):
        assert get_ai_make("xai") == "xai"

    def test_all_providers_return_own_make(self):
        for provider in ("xai", "anthropic", "openai", "perplexity", "gemini"):
            assert get_ai_make(provider) == provider

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported AI model"):
            get_ai_make("unknown_ai")


# ── check_api_key ─────────────────────────────────────────────────────────────

class TestCheckAPIKey:
    def test_key_present_returns_true(self):
        with patch.dict(os.environ, {"XAI_API_KEY": "sk-fake-key"}):
            assert check_api_key("xai") is True

    def test_key_absent_returns_false(self, capsys):
        env_clean = {k: v for k, v in os.environ.items() if k != "XAI_API_KEY"}
        with patch.dict(os.environ, env_clean, clear=True):
            result = check_api_key("xai")
        assert result is False

    def test_missing_key_prints_diagnostic(self, capsys):
        env_clean = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        with patch.dict(os.environ, env_clean, clear=True):
            check_api_key("gemini")
        out = capsys.readouterr().out
        assert "GEMINI_API_KEY" in out

    def test_unknown_make_returns_true(self):
        # Unknown providers: let the SDK surface the real error → returns True
        result = check_api_key("totally_unknown_make")
        assert result is True

    def test_api_key_env_vars_covers_all_providers(self):
        for provider in ("xai", "anthropic", "openai", "perplexity", "gemini"):
            assert provider in _API_KEY_ENV_VARS

    def test_all_env_var_names_are_strings(self):
        for make, var_name in _API_KEY_ENV_VARS.items():
            assert isinstance(var_name, str)
            assert "_API_KEY" in var_name


# ── get_content / put_content ─────────────────────────────────────────────────

# Minimal hand-crafted provider responses
_OPENAI_RESPONSE = {
    "choices": [{"message": {"content": "Hello from OpenAI"}}]
}
_XAI_RESPONSE = {
    "content": [{"type": "text", "text": "Hello from xAI"}]
}
_ANTHROPIC_RESPONSE = {
    "content": [{"type": "text", "text": "Hello from Anthropic"}]
}


class TestGetContent:
    def test_openai(self):
        assert get_content("openai", _OPENAI_RESPONSE) == "Hello from OpenAI"

    def test_xai(self):
        assert get_content("xai", _XAI_RESPONSE) == "Hello from xAI"

    def test_anthropic(self):
        assert get_content("anthropic", _ANTHROPIC_RESPONSE) == "Hello from Anthropic"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported AI model"):
            get_content("unknown_provider", _OPENAI_RESPONSE)


class TestGetContentAuto:
    def test_with_make_stamp_openai(self):
        response = dict(_OPENAI_RESPONSE)
        response["_make"] = "openai"
        assert get_content_auto(response) == "Hello from OpenAI"

    def test_with_make_stamp_xai(self):
        response = dict(_XAI_RESPONSE)
        response["_make"] = "xai"
        assert get_content_auto(response) == "Hello from xAI"

    def test_missing_make_raises_value_error(self):
        with pytest.raises(ValueError, match="_make"):
            get_content_auto(_OPENAI_RESPONSE)

    def test_empty_make_raises_value_error(self):
        response = dict(_OPENAI_RESPONSE)
        response["_make"] = ""
        with pytest.raises(ValueError, match="_make"):
            get_content_auto(response)


class TestPutContent:
    def test_openai_updates_content(self):
        response = {"choices": [{"message": {"content": "Old"}}]}
        result = put_content("openai", "New content", response)
        assert get_content("openai", result) == "New content"

    def test_xai_updates_content(self):
        response = {"content": [{"type": "text", "text": "Old"}]}
        result = put_content("xai", "New content", response)
        assert get_content("xai", result) == "New content"

    def test_anthropic_updates_content(self):
        response = {"content": [{"type": "text", "text": "Old"}]}
        result = put_content("anthropic", "Replaced", response)
        assert get_content("anthropic", result) == "Replaced"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported AI model"):
            put_content("unknown", "text", {})

    def test_put_then_get_roundtrip(self):
        response = {"choices": [{"message": {"content": "Original"}}]}
        put_content("openai", "Updated", response)
        assert get_content("openai", response) == "Updated"


class TestPutContentAuto:
    def test_updates_content_via_make_stamp(self):
        response = {"_make": "openai", "choices": [{"message": {"content": "Old"}}]}
        result = put_content_auto("New content", response)
        assert get_content("openai", result) == "New content"

    def test_missing_make_raises(self):
        with pytest.raises(ValueError, match="_make"):
            put_content_auto("text", {"choices": [{"message": {"content": "x"}}]})


# ── AIResponse ────────────────────────────────────────────────────────────────

class TestAIResponse:
    """AIResponse tuple-compatibility and attribute access."""

    def _make(self, was_cached: bool = False) -> AIResponse:
        return AIResponse(
            payload={"model": "test-model", "prompt": "hello"},
            client=None,
            response={"content": [{"type": "text", "text": "reply"}]},
            model="test-model",
            was_cached=was_cached,
        )

    def test_tuple_unpacks_as_4(self):
        payload, client, response, model = self._make()
        assert model == "test-model"
        assert payload == {"model": "test-model", "prompt": "hello"}

    def test_was_cached_false(self):
        assert self._make(was_cached=False).was_cached is False

    def test_was_cached_true(self):
        assert self._make(was_cached=True).was_cached is True

    def test_len_is_4(self):
        assert len(self._make()) == 4

    def test_indexing_model_at_3(self):
        r = self._make()
        assert r[3] == "test-model"

    def test_indexing_payload_at_0(self):
        r = self._make()
        assert r[0]["model"] == "test-model"

    def test_payload_attribute(self):
        r = self._make()
        assert r.payload["prompt"] == "hello"

    def test_model_attribute(self):
        r = self._make()
        assert r.model == "test-model"

    def test_response_attribute(self):
        r = self._make()
        assert r.response["content"][0]["text"] == "reply"

    def test_client_attribute(self):
        r = self._make()
        assert r.client is None

