"""Google OAuth helpers for the gdrive-video-mcp server.

Uses the "Installed application" OAuth flow with a local loopback redirect. The
refresh token is cached on disk so the user only needs to consent once.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

# We request drive.file rather than full drive scope. drive.file lets the app
# read/write only files that the app itself created (or files the user explicitly
# opens with it). This is the principle-of-least-privilege scope for uploaders.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _default_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "gdrive-video-mcp"


def client_secrets_path() -> Path:
    env = os.environ.get("GDRIVE_MCP_CLIENT_SECRETS")
    if env:
        return Path(env).expanduser()
    return _default_config_dir() / "credentials.json"


def token_path() -> Path:
    env = os.environ.get("GDRIVE_MCP_TOKEN_PATH")
    if env:
        return Path(env).expanduser()
    return _default_config_dir() / "token.json"


def load_credentials() -> Credentials:
    """Load cached creds, refresh if needed, or run the consent flow.

    Raises FileNotFoundError with a helpful message if no client secrets file
    is present.
    """
    secrets = client_secrets_path()
    token = token_path()
    token.parent.mkdir(parents=True, exist_ok=True)

    creds: Credentials | None = None
    if token.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token), SCOPES)
        except Exception as exc:  # noqa: BLE001 - report and re-auth
            print(f"[gdrive-video-mcp] Could not load cached token: {exc}", file=sys.stderr)
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token.write_text(creds.to_json())
            return creds
        except Exception as exc:  # noqa: BLE001
            print(
                f"[gdrive-video-mcp] Token refresh failed, re-authorizing: {exc}",
                file=sys.stderr,
            )
            creds = None

    if not secrets.exists():
        raise FileNotFoundError(
            f"Google OAuth client secrets not found at {secrets}. "
            "Create an OAuth client of type 'Desktop app' in Google Cloud Console, "
            "download the JSON, and save it there (or set GDRIVE_MCP_CLIENT_SECRETS)."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
    # port=0 picks a free port; opens a browser for consent and captures the
    # auth code via a local HTTP listener.
    creds = flow.run_local_server(port=0)
    token.write_text(creds.to_json())
    return creds


def drive_service() -> Resource:
    """Return an authenticated Drive v3 API client."""
    creds = load_credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)
