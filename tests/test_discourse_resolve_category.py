"""Tests for I1 — Discourse category resolution.

Three accepted forms for ``--category`` (every site):
  * ``private``  — your private area (site.private_category_id)
  * a number     — any Discourse category ID
  * crossai.dev shortcuts — ``test`` / ``reports`` / ``prompt-lab``
                            resolve only when site URL contains crossai.dev
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cross_st"))

import discourse  # noqa: E402


CROSSAI = {
    "url": "https://crossai.dev",
    "category_id": 1,
    "private_category_id": 42,
    "private_category_slug": "alice-private",
}

SELF_HOSTED = {
    "url": "https://forum.example.com",
    "category_id": 77,
    "private_category_id": 88,
}

SELF_HOSTED_NO_PRIV = {
    "url": "https://forum.example.com",
    "category_id": 77,
}


class TestNumericPassthrough:
    def test_int(self):
        assert discourse.resolve_category(SELF_HOSTED, 99) == 99

    def test_digit_string(self):
        assert discourse.resolve_category(SELF_HOSTED, "33") == 33

    def test_works_on_any_site(self):
        assert discourse.resolve_category(CROSSAI, 12345) == 12345


class TestCrossaiShortcuts:
    def test_test_shortcut(self):
        assert discourse.resolve_category(CROSSAI, "test") == 6

    def test_reports_shortcut(self):
        assert discourse.resolve_category(CROSSAI, "reports") == 16

    def test_prompt_lab_shortcut(self):
        assert discourse.resolve_category(CROSSAI, "prompt-lab") == 17

    def test_uppercase_accepted(self):
        assert discourse.resolve_category(CROSSAI, "Reports") == 16


class TestSelfHostedRejectsShortcuts:
    @pytest.mark.parametrize("alias", ["test", "reports", "prompt-lab"])
    def test_alias_rejected(self, alias):
        with pytest.raises(ValueError) as exc:
            discourse.resolve_category(SELF_HOSTED, alias)
        msg = str(exc.value)
        assert "crossai.dev-only" in msg
        assert "numeric" in msg


class TestPrivate:
    def test_uses_private_category_id_on_crossai(self):
        assert discourse.resolve_category(CROSSAI, "private") == 42

    def test_uses_private_category_id_on_self_hosted(self):
        assert discourse.resolve_category(SELF_HOSTED, "private") == 88

    def test_falls_back_to_category_id(self):
        assert discourse.resolve_category(SELF_HOSTED_NO_PRIV, "private") == 77


class TestUnknown:
    def test_unknown_string_errors(self):
        with pytest.raises(ValueError) as exc:
            discourse.resolve_category(SELF_HOSTED, "no-such-thing")
        msg = str(exc.value)
        assert "no-such-thing" in msg
        assert "private" in msg
        assert "numeric" in msg


class TestDefault:
    def test_none_returns_default(self):
        assert discourse.resolve_category(SELF_HOSTED, None) == 77

    def test_blank_returns_default(self):
        assert discourse.resolve_category(SELF_HOSTED, "") == 77

    def test_blank_with_no_default_raises(self):
        with pytest.raises(ValueError):
            discourse.resolve_category({"url": "https://x"}, None)


class TestIsCrossai:
    def test_https(self):
        assert discourse._is_crossai({"url": "https://crossai.dev"})

    def test_subpath(self):
        assert discourse._is_crossai({"url": "https://crossai.dev/path"})

    def test_case_insensitive(self):
        assert discourse._is_crossai({"url": "https://CrossAI.dev"})

    def test_other_site(self):
        assert not discourse._is_crossai({"url": "https://forum.example.com"})

    def test_missing_url(self):
        assert not discourse._is_crossai({})

