"""
tests/test_st_speed_alias_rows.py — CST-MM-e: per-alias rows in st-speed.

Verifies that when timing data contains two same-make entries with different
models, st-speed produces one row per (make, model) and labels the rows
distinctly.
"""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def st_speed_mod():
    path = Path(__file__).parent.parent / "cross_st" / "st-speed.py"
    spec = importlib.util.spec_from_file_location("st_speed_alias", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(make, model, elapsed):
    return {
        "ai":               make,
        "model":            model,
        "elapsed_seconds":  elapsed,
        "tokens_input":     100,
        "tokens_output":    100,
        "tokens_total":     200,
        "tokens_per_second": 50.0,
        "cached":           False,
    }


class TestPerAliasRows:
    def test_two_same_make_different_models_get_two_rows(self, st_speed_mod):
        data = [
            _row("anthropic", "claude-opus-4-5",   60),
            _row("anthropic", "claude-sonnet-4-5", 90),
            _row("openai",    "gpt-4o",            45),
        ]
        rows = st_speed_mod.summarize_generation(data)
        ais = [r["AI"] for r in rows]
        assert "anthropic:claude-opus-4-5"   in ais
        assert "anthropic:claude-sonnet-4-5" in ais
        # openai has only one model — label stays bare
        assert "openai" in ais
        assert "openai:gpt-4o" not in ais

    def test_single_model_per_make_uses_bare_make_label(self, st_speed_mod):
        data = [
            _row("anthropic", "claude-opus-4-5", 60),
            _row("openai",    "gpt-4o",          45),
        ]
        rows = st_speed_mod.summarize_generation(data)
        ais = [r["AI"] for r in rows]
        assert ais == ["openai", "anthropic"] or set(ais) == {"openai", "anthropic"}

    def test_filter_by_alias_resolves_to_make_model(self, st_speed_mod, tmp_path, monkeypatch):
        # Register a real alias so the filter has something to resolve against.
        alias_file = tmp_path / "cross_ai_models.json"
        alias_file.write_text(
            '{"anthropic-opus": {"make": "anthropic", "model": "claude-opus-4-5"}}'
        )
        monkeypatch.setenv("CROSS_AI_ALIASES_FILE", str(alias_file))
        from cross_ai_core.aliases import reload_aliases
        reload_aliases()
        try:
            data = [
                _row("anthropic", "claude-opus-4-5",   60),
                _row("anthropic", "claude-sonnet-4-5", 90),
            ]
            rows = st_speed_mod.summarize_generation(data, ai_filter="anthropic-opus")
            assert rows is not None
            # Filter narrows to the one (make, model) matching the alias.
            assert len(rows) == 1
            assert rows[0]["AI"] == "anthropic"  # only one model in surviving set
        finally:
            monkeypatch.delenv("CROSS_AI_ALIASES_FILE", raising=False)
            reload_aliases()

    def test_filter_by_make_keeps_all_models_for_make(self, st_speed_mod):
        data = [
            _row("anthropic", "claude-opus-4-5",   60),
            _row("anthropic", "claude-sonnet-4-5", 90),
            _row("openai",    "gpt-4o",            45),
        ]
        rows = st_speed_mod.summarize_generation(data, ai_filter="anthropic")
        # Filter on bare make: both anthropic models must remain (and get
        # disambiguated labels because there are still two models).
        ais = {r["AI"] for r in rows}
        assert ais == {"anthropic:claude-opus-4-5", "anthropic:claude-sonnet-4-5"}


