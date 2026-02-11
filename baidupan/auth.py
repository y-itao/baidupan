"""OAuth2 authentication: Device Code + Authorization Code + Token Refresh."""

import json
import logging
import os
import time
import webbrowser

import requests

from . import config
from .errors import AuthError

log = logging.getLogger(__name__)


class TokenStore:
    """Persist and load OAuth tokens from disk."""

    def __init__(self, path: str = None):
        self.path = path or config.TOKEN_FILE

    def load(self) -> dict | None:
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load token: %s", exc)
            return None

    def save(self, token_data: dict):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(token_data, f, indent=2)
        os.chmod(self.path, 0o600)
        log.debug("Token saved to %s", self.path)

    def clear(self):
        if os.path.exists(self.path):
            os.remove(self.path)


class Authenticator:
    """Handle OAuth2 flows and token lifecycle."""

    def __init__(self, store: TokenStore = None, session: requests.Session = None):
        self.store = store or TokenStore()
        self.session = session or requests.Session()

    # ── Public API ────────────────────────────────────────────────

    def get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        token_data = self.store.load()
        if token_data is None:
            raise AuthError(
                "Not authenticated. Run 'baidupan auth' first."
            )

        # check expiry (with 5-minute buffer)
        expires_at = token_data.get("expires_at", 0)
        if time.time() > expires_at - 300:
            log.info("Token expired or expiring soon, refreshing...")
            token_data = self._refresh_token(token_data["refresh_token"])
            self.store.save(token_data)

        return token_data["access_token"]

    def auth_interactive(self):
        """Run the Authorization Code flow interactively (bypy-style).

        1. Print authorization URL for user to visit in browser
        2. User authorizes and gets a code from the page
        3. User pastes the code back here
        """
        auth_url = (
            f"{config.OAUTH_AUTHORIZE_URL}"
            f"?response_type=code"
            f"&client_id={config.APP_KEY}"
            f"&redirect_uri=oob"
            f"&scope=basic,netdisk"
        )

        print()
        print("Please visit the following URL in your browser to authorize:")
        print()
        print(f"  {auth_url}")
        print()

        try:
            webbrowser.open(auth_url)
        except Exception:
            pass

        auth_code = input("After authorization, paste the code here: ").strip()
        if not auth_code:
            raise AuthError("No authorization code provided.")

        self.auth_authorization_code(auth_code)

    def auth_device_code(self):
        """Run the Device Code flow interactively."""
        # Step 1: get device code
        resp = self.session.get(config.OAUTH_DEVICE_CODE_URL, params={
            "response_type": "device_code",
            "client_id": config.APP_KEY,
            "scope": "basic,netdisk",
        })
        resp.raise_for_status()
        data = resp.json()

        device_code = data["device_code"]
        user_code = data["user_code"]
        verification_url = data["verification_url"]
        interval = data.get("interval", 5)
        expires_in = data.get("expires_in", 300)

        print(f"\n  Please visit: {verification_url}")
        print(f"  And enter code: {user_code}\n")

        try:
            webbrowser.open(verification_url)
        except Exception:
            pass

        # Step 2: poll for token
        deadline = time.time() + expires_in
        while time.time() < deadline:
            time.sleep(interval)
            resp = self.session.get(config.OAUTH_TOKEN_URL, params={
                "grant_type": "device_token",
                "code": device_code,
                "client_id": config.APP_KEY,
                "client_secret": config.SECRET_KEY,
            })
            result = resp.json()

            if "access_token" in result:
                token_data = self._enrich_token(result)
                self.store.save(token_data)
                print("Authentication successful!")
                return

            error = result.get("error")
            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                interval += 1
                continue
            else:
                raise AuthError(f"Device code auth failed: {result.get('error_description', error)}")

        raise AuthError("Device code expired. Please try again.")

    def auth_authorization_code(self, auth_code: str):
        """Exchange an authorization code for tokens."""
        resp = self.session.get(config.OAUTH_TOKEN_URL, params={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": config.APP_KEY,
            "client_secret": config.SECRET_KEY,
            "redirect_uri": "oob",
        })
        resp.raise_for_status()
        result = resp.json()

        if "access_token" not in result:
            raise AuthError(f"Auth code exchange failed: {result}")

        token_data = self._enrich_token(result)
        self.store.save(token_data)
        print("Authentication successful!")

    # ── Internal ──────────────────────────────────────────────────

    def _refresh_token(self, refresh_token: str) -> dict:
        resp = self.session.get(config.OAUTH_TOKEN_URL, params={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": config.APP_KEY,
            "client_secret": config.SECRET_KEY,
        })
        resp.raise_for_status()
        result = resp.json()

        if "access_token" not in result:
            raise AuthError(
                f"Token refresh failed: {result}. Run 'baidupan auth' again."
            )
        return self._enrich_token(result)

    @staticmethod
    def _enrich_token(raw: dict) -> dict:
        """Add computed expires_at to the raw token response."""
        raw["expires_at"] = time.time() + raw.get("expires_in", 2592000)
        return raw
