"""
tests/test_discourse_provision.py
Unit tests for cross_st.discourse_provision (ONB-C6, TAP-1)

Mocks:
  - requests.post  (HTTP call to provisioning endpoint)
  - dotenv.set_key (env file writes)
  - builtins.input (user prompts)
"""
import os
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Make sure cross_st is importable from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from cross_st.discourse_provision import (
    discourse_onboard,
    write_discourse_env,
    get_tos_versions,
    display_terms_and_conditions,
    PROVISION_ENDPOINT,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

MOCK_CREDS = {
    "discourse_url":                    "https://crossai.dev",
    "discourse_username":               "alice",
    "discourse_api_key":                "fakekey123",
    "discourse_category_id":            42,
    "discourse_private_category_slug":  "alice-private",
}


@pytest.fixture(autouse=True)
def set_provision_secret(monkeypatch):
    monkeypatch.setenv("PROVISION_SECRET", "test-secret-xyz")


# ── discourse_onboard() ───────────────────────────────────────────────────────

class TestDiscourseOnboard:
    def _mock_ok_response(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = MOCK_CREDS
        resp.raise_for_status = MagicMock()
        return resp

    def test_successful_provision(self):
        mock_resp = self._mock_ok_response()
        with patch("cross_st.discourse_provision.requests.post", return_value=mock_resp) as mock_post:
            result = discourse_onboard("alice")

        assert result == MOCK_CREDS
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"] == {"username": "alice"}
        assert "Bearer test-secret-xyz" in call_kwargs[1]["headers"]["Authorization"]

    def test_username_lowercased(self):
        mock_resp = self._mock_ok_response()
        with patch("cross_st.discourse_provision.requests.post", return_value=mock_resp) as mock_post:
            discourse_onboard("Alice")  # mixed case
        assert mock_post.call_args[1]["json"]["username"] == "alice"

    def test_uses_custom_endpoint(self):
        mock_resp = self._mock_ok_response()
        with patch("cross_st.discourse_provision.requests.post", return_value=mock_resp) as mock_post:
            discourse_onboard("alice", endpoint="http://localhost:5000/api/provision-user")
        assert "localhost:5000" in mock_post.call_args[0][0]

    def test_uses_custom_secret(self):
        mock_resp = self._mock_ok_response()
        with patch("cross_st.discourse_provision.requests.post", return_value=mock_resp) as mock_post:
            discourse_onboard("alice", provision_secret="custom-secret")
        assert "Bearer custom-secret" in mock_post.call_args[1]["headers"]["Authorization"]

    def test_400_raises_value_error(self):
        resp = MagicMock()
        resp.status_code = 400
        resp.json.return_value = {"error": "User 'nobody' not found in Discourse"}
        with patch("cross_st.discourse_provision.requests.post", return_value=resp):
            with pytest.raises(ValueError, match="not found"):
                discourse_onboard("nobody")

    def test_401_raises_permission_error(self):
        resp = MagicMock()
        resp.status_code = 401
        resp.json.return_value = {"error": "Unauthorized"}
        with patch("cross_st.discourse_provision.requests.post", return_value=resp):
            with pytest.raises(PermissionError):
                discourse_onboard("alice")

    def test_missing_secret_raises_value_error(self, monkeypatch):
        monkeypatch.delenv("PROVISION_SECRET", raising=False)
        monkeypatch.setattr("cross_st.discourse_provision._PROVISION_SECRET_DEFAULT", "")
        with pytest.raises(ValueError, match="provisioning secret"):
            discourse_onboard("alice")

    def test_default_endpoint_is_production(self):
        assert "crossai.dev" in PROVISION_ENDPOINT


# ── write_discourse_env() ─────────────────────────────────────────────────────

class TestWriteDiscourseEnv:
    def test_writes_all_keys(self, monkeypatch, tmp_path):
        fake_crossenv = str(tmp_path / ".crossenv")
        monkeypatch.setattr("cross_st.discourse_provision._CROSSENV", fake_crossenv)

        written = {}
        def fake_set_key(path, key, value):
            written[key] = value

        with patch("cross_st.discourse_provision.set_key", side_effect=fake_set_key):
            write_discourse_env(MOCK_CREDS)

        # Only two keys written — no legacy flat DISCOURSE_* keys
        assert "DISCOURSE_URL"                   not in written
        assert "DISCOURSE_USERNAME"              not in written
        assert "DISCOURSE_API_KEY"               not in written
        assert "DISCOURSE_CATEGORY_ID"           not in written
        assert "DISCOURSE_PRIVATE_CATEGORY_SLUG" not in written

        # DISCOURSE_SITE points to the slug
        assert written["DISCOURSE_SITE"] == "crossai.dev"

        # DISCOURSE JSON contains fully self-contained site entry
        import json
        disc = json.loads(written["DISCOURSE"])
        site = disc["sites"][0]
        assert site["slug"]                  == "crossai.dev"
        assert site["url"]                   == "https://crossai.dev"
        assert site["username"]              == "alice"
        assert site["api_key"]               == "fakekey123"
        assert site["category_id"]           == 42
        assert site["private_category_id"]   == 42
        assert site["private_category_slug"] == "alice-private"

    def test_also_updates_os_environ(self, monkeypatch, tmp_path):
        fake_crossenv = str(tmp_path / ".crossenv")
        monkeypatch.setattr("cross_st.discourse_provision._CROSSENV", fake_crossenv)

        with patch("cross_st.discourse_provision.set_key"):
            write_discourse_env(MOCK_CREDS)

        assert os.environ.get("DISCOURSE_SITE") == "crossai.dev"
        assert os.environ.get("DISCOURSE") is not None

    def test_skips_incomplete_credentials(self, monkeypatch, tmp_path):
        """If any of url/username/api_key is missing, nothing is written."""
        fake_crossenv = str(tmp_path / ".crossenv")
        monkeypatch.setattr("cross_st.discourse_provision._CROSSENV", fake_crossenv)

        partial_creds = {"discourse_url": "https://crossai.dev", "discourse_username": ""}
        written = {}
        with patch("cross_st.discourse_provision.set_key", side_effect=lambda p, k, v: written.update({k: v})):
            write_discourse_env(partial_creds)

        assert written == {}, "No keys should be written when credentials are incomplete"

    def test_upserts_existing_custom_site(self, monkeypatch, tmp_path):
        """Re-provisioning crossai.dev must preserve any custom forum already in DISCOURSE JSON."""
        import json
        fake_crossenv = str(tmp_path / ".crossenv")
        monkeypatch.setattr("cross_st.discourse_provision._CROSSENV", fake_crossenv)

        # Pre-seed DISCOURSE with two sites: old crossai.dev + a custom forum
        existing = {"sites": [
            {"slug": "crossai.dev", "url": "https://crossai.dev",
             "username": "alice-old", "api_key": "oldkey", "category_id": 10},
            {"slug": "myforum", "url": "https://forum.example.com",
             "username": "alice", "api_key": "customkey", "category_id": 5},
        ]}
        monkeypatch.setenv("DISCOURSE", json.dumps(existing))

        written = {}
        with patch("cross_st.discourse_provision.set_key", side_effect=lambda p, k, v: written.update({k: v})):
            write_discourse_env(MOCK_CREDS)

        disc = json.loads(written["DISCOURSE"])
        sites = disc["sites"]
        slugs = [s["slug"] for s in sites]

        # crossai.dev updated, custom forum preserved
        assert "crossai.dev" in slugs
        assert "myforum" in slugs
        assert len(sites) == 2

        # crossai.dev entry has the NEW credentials
        ca = next(s for s in sites if s["slug"] == "crossai.dev")
        assert ca["username"] == "alice"
        assert ca["api_key"] == "fakekey123"
        assert ca["category_id"] == 42

        # custom forum untouched
        mf = next(s for s in sites if s["slug"] == "myforum")
        assert mf["api_key"] == "customkey"


# ── get_tos_versions() — TAP-1 ───────────────────────────────────────────────

class TestGetTosVersions:
    def test_returns_dict_with_expected_keys(self):
        """Manifest file ships with the package — should always be readable."""
        result = get_tos_versions()
        assert isinstance(result, dict)
        assert "tos_version" in result
        assert "privacy_version" in result

    def test_version_strings_are_date_format(self):
        result = get_tos_versions()
        import re
        date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        assert date_re.match(result["tos_version"])
        assert date_re.match(result["privacy_version"])

    def test_fallback_when_manifest_missing(self, monkeypatch, tmp_path):
        """If tos_versions.json is absent, returns hardcoded 2026-04-07."""
        missing = tmp_path / "tos_versions.json"  # does not exist
        monkeypatch.setattr("cross_st.discourse_provision._TOS_VERSIONS_PATH", missing)
        result = get_tos_versions()
        assert result["tos_version"]     == "2026-04-07"
        assert result["privacy_version"] == "2026-04-07"

    def test_reads_custom_manifest(self, monkeypatch, tmp_path):
        """Reads and parses a custom manifest from disk."""
        manifest = tmp_path / "tos_versions.json"
        manifest.write_text(json.dumps({
            "tos_version": "2026-11-01",
            "privacy_version": "2026-10-15",
            "updated_at": "2026-11-01",
        }), encoding="utf-8")
        monkeypatch.setattr("cross_st.discourse_provision._TOS_VERSIONS_PATH", manifest)
        result = get_tos_versions()
        assert result["tos_version"]     == "2026-11-01"
        assert result["privacy_version"] == "2026-10-15"


# ── display_terms_and_conditions() — TAP-1 ───────────────────────────────────

class TestDisplayTermsAndConditions:
    """Tests that display_terms_and_conditions strips the VERSION comment and shows the footer."""

    def _make_tos_file(self, tmp_path, with_version_line=True):
        content = ""
        if with_version_line:
            content += "# VERSION: tos=2026-04-07 privacy=2026-04-07\n"
        content += "╔══ Terms ══╗\nSome terms here.\n"
        tos_file = tmp_path / "discourse_tos.txt"
        tos_file.write_text(content, encoding="utf-8")
        return tos_file

    def test_strips_version_comment_from_display(self, monkeypatch, tmp_path, capsys):
        tos_file = self._make_tos_file(tmp_path, with_version_line=True)
        monkeypatch.setattr("cross_st.discourse_provision._TOS_PATH", tos_file)
        with patch("builtins.input", return_value="yes"):
            display_terms_and_conditions(versions={"tos_version": "2026-04-07", "privacy_version": "2026-04-07"})
        out = capsys.readouterr().out
        assert "# VERSION:" not in out
        assert "Some terms here." in out

    def test_shows_version_footer(self, monkeypatch, tmp_path, capsys):
        tos_file = self._make_tos_file(tmp_path, with_version_line=True)
        monkeypatch.setattr("cross_st.discourse_provision._TOS_PATH", tos_file)
        with patch("builtins.input", return_value="yes"):
            display_terms_and_conditions(versions={"tos_version": "2026-04-07", "privacy_version": "2026-04-07"})
        out = capsys.readouterr().out
        assert "Terms version: 2026-04-07" in out
        assert "Privacy version: 2026-04-07" in out

    def test_shows_version_footer_with_custom_versions(self, monkeypatch, tmp_path, capsys):
        tos_file = self._make_tos_file(tmp_path, with_version_line=False)
        monkeypatch.setattr("cross_st.discourse_provision._TOS_PATH", tos_file)
        with patch("builtins.input", return_value="no"):
            display_terms_and_conditions(versions={"tos_version": "2026-11-01", "privacy_version": "2026-10-15"})
        out = capsys.readouterr().out
        assert "Terms version: 2026-11-01" in out
        assert "Privacy version: 2026-10-15" in out

    def test_returns_true_on_yes(self, monkeypatch, tmp_path):
        tos_file = self._make_tos_file(tmp_path)
        monkeypatch.setattr("cross_st.discourse_provision._TOS_PATH", tos_file)
        with patch("builtins.input", return_value="yes"):
            assert display_terms_and_conditions() is True

    def test_returns_false_on_no(self, monkeypatch, tmp_path):
        tos_file = self._make_tos_file(tmp_path)
        monkeypatch.setattr("cross_st.discourse_provision._TOS_PATH", tos_file)
        with patch("builtins.input", return_value="no"):
            assert display_terms_and_conditions() is False

    def test_uses_get_tos_versions_when_no_arg(self, monkeypatch, tmp_path, capsys):
        tos_file = self._make_tos_file(tmp_path)
        monkeypatch.setattr("cross_st.discourse_provision._TOS_PATH", tos_file)
        custom = {"tos_version": "2099-01-01", "privacy_version": "2099-01-01"}
        with patch("cross_st.discourse_provision.get_tos_versions", return_value=custom):
            with patch("builtins.input", return_value="yes"):
                display_terms_and_conditions()  # no versions= arg
        out = capsys.readouterr().out
        assert "2099-01-01" in out

