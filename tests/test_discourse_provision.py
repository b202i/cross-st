"""
tests/test_discourse_provision.py
Unit tests for cross_st.discourse_provision (ONB-C6)

Mocks:
  - requests.post  (HTTP call to provisioning endpoint)
  - dotenv.set_key (env file writes)
  - builtins.input (user prompts)
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Make sure cross_st is importable from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from cross_st.discourse_provision import (
    discourse_onboard,
    write_discourse_env,
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
        with pytest.raises(ValueError, match="PROVISION_SECRET not set"):
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

        assert written["DISCOURSE_URL"] == "https://crossai.dev"
        assert written["DISCOURSE_USERNAME"] == "alice"
        assert written["DISCOURSE_API_KEY"] == "fakekey123"
        assert written["DISCOURSE_CATEGORY_ID"] == "42"
        assert written["DISCOURSE_PRIVATE_CATEGORY_SLUG"] == "alice-private"

    def test_also_updates_os_environ(self, monkeypatch, tmp_path):
        fake_crossenv = str(tmp_path / ".crossenv")
        monkeypatch.setattr("cross_st.discourse_provision._CROSSENV", fake_crossenv)

        with patch("cross_st.discourse_provision.set_key"):
            write_discourse_env(MOCK_CREDS)

        assert os.environ.get("DISCOURSE_USERNAME") == "alice"
        assert os.environ.get("DISCOURSE_API_KEY") == "fakekey123"

    def test_skips_empty_values(self, monkeypatch, tmp_path):
        fake_crossenv = str(tmp_path / ".crossenv")
        monkeypatch.setattr("cross_st.discourse_provision._CROSSENV", fake_crossenv)

        partial_creds = {"discourse_url": "https://crossai.dev", "discourse_username": ""}
        written = {}
        with patch("cross_st.discourse_provision.set_key", side_effect=lambda p, k, v: written.update({k: v})):
            write_discourse_env(partial_creds)

        assert "DISCOURSE_USERNAME" not in written
        assert "DISCOURSE_URL" in written

