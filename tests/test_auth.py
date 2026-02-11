"""Tests for baidupan.auth."""

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from baidupan.auth import Authenticator, TokenStore
from baidupan.errors import AuthError


class TestTokenStore:
    def test_load_nonexistent(self, tmp_path):
        store = TokenStore(str(tmp_path / "missing.json"))
        assert store.load() is None

    def test_save_and_load(self, tmp_path):
        path = str(tmp_path / "token.json")
        store = TokenStore(path)
        data = {"access_token": "abc", "refresh_token": "xyz", "expires_at": 9999999999}
        store.save(data)

        loaded = store.load()
        assert loaded == data

        # check file permissions
        mode = os.stat(path).st_mode & 0o777
        assert mode == 0o600

    def test_save_creates_dir(self, tmp_path):
        path = str(tmp_path / "subdir" / "token.json")
        store = TokenStore(path)
        store.save({"access_token": "test"})
        assert os.path.exists(path)

    def test_load_corrupt_json(self, tmp_path):
        path = str(tmp_path / "bad.json")
        with open(path, "w") as f:
            f.write("{invalid json")
        store = TokenStore(path)
        assert store.load() is None

    def test_clear(self, tmp_path):
        path = str(tmp_path / "token.json")
        store = TokenStore(path)
        store.save({"access_token": "test"})
        assert os.path.exists(path)
        store.clear()
        assert not os.path.exists(path)

    def test_clear_nonexistent(self, tmp_path):
        store = TokenStore(str(tmp_path / "nope.json"))
        store.clear()  # should not raise


class TestAuthenticator:
    def _make_auth(self, tmp_path, token_data=None):
        store = TokenStore(str(tmp_path / "token.json"))
        if token_data:
            store.save(token_data)
        session = MagicMock()
        return Authenticator(store=store, session=session)

    def test_get_access_token_no_auth(self, tmp_path):
        auth = self._make_auth(tmp_path)
        with pytest.raises(AuthError, match="Not authenticated"):
            auth.get_access_token()

    def test_get_access_token_valid(self, tmp_path):
        token = {
            "access_token": "valid_token",
            "refresh_token": "refresh_tok",
            "expires_at": time.time() + 3600,
        }
        auth = self._make_auth(tmp_path, token)
        assert auth.get_access_token() == "valid_token"

    def test_get_access_token_expired_triggers_refresh(self, tmp_path):
        token = {
            "access_token": "old_token",
            "refresh_token": "refresh_tok",
            "expires_at": time.time() - 100,  # expired
        }
        auth = self._make_auth(tmp_path, token)

        # Mock refresh response
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "new_token",
            "refresh_token": "new_refresh",
            "expires_in": 2592000,
        }
        mock_resp.raise_for_status = MagicMock()
        auth.session.get.return_value = mock_resp

        result = auth.get_access_token()
        assert result == "new_token"
        auth.session.get.assert_called_once()

    def test_auth_authorization_code_success(self, tmp_path):
        auth = self._make_auth(tmp_path)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "new_at",
            "refresh_token": "new_rt",
            "expires_in": 2592000,
        }
        mock_resp.raise_for_status = MagicMock()
        auth.session.get.return_value = mock_resp

        auth.auth_authorization_code("test_code")
        loaded = auth.store.load()
        assert loaded["access_token"] == "new_at"

    def test_auth_authorization_code_failure(self, tmp_path):
        auth = self._make_auth(tmp_path)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": "invalid_code"}
        mock_resp.raise_for_status = MagicMock()
        auth.session.get.return_value = mock_resp

        with pytest.raises(AuthError, match="Auth code exchange failed"):
            auth.auth_authorization_code("bad_code")

    def test_refresh_token_failure(self, tmp_path):
        token = {
            "access_token": "old",
            "refresh_token": "bad_refresh",
            "expires_at": time.time() - 100,
        }
        auth = self._make_auth(tmp_path, token)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": "expired_refresh"}
        mock_resp.raise_for_status = MagicMock()
        auth.session.get.return_value = mock_resp

        with pytest.raises(AuthError, match="Token refresh failed"):
            auth.get_access_token()

    def test_enrich_token(self):
        before = time.time()
        result = Authenticator._enrich_token({"expires_in": 3600})
        after = time.time()
        assert before + 3600 <= result["expires_at"] <= after + 3600

    @patch("baidupan.auth.time.sleep")
    def test_device_code_flow_success(self, mock_sleep, tmp_path):
        auth = self._make_auth(tmp_path)

        # First call: device code request
        device_resp = MagicMock()
        device_resp.json.return_value = {
            "device_code": "dc123",
            "user_code": "UC123",
            "verification_url": "https://example.com/verify",
            "interval": 1,
            "expires_in": 300,
        }
        device_resp.raise_for_status = MagicMock()

        # Second call: pending, Third call: success
        pending_resp = MagicMock()
        pending_resp.json.return_value = {"error": "authorization_pending"}

        success_resp = MagicMock()
        success_resp.json.return_value = {
            "access_token": "device_token",
            "refresh_token": "device_refresh",
            "expires_in": 2592000,
        }

        auth.session.get.side_effect = [device_resp, pending_resp, success_resp]

        with patch("baidupan.auth.webbrowser.open"):
            auth.auth_device_code()

        loaded = auth.store.load()
        assert loaded["access_token"] == "device_token"
