"""Tests for OAuth discovery + DCR + consent + token endpoints."""

from __future__ import annotations

import base64
import hashlib

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("MCP_BEARER_TOKEN", "test-bearer")
    from gdrive_video_mcp.http_app import build_app

    return build_app(bearer_token="test-bearer", include_mcp=False)


def test_protected_resource_metadata(app):
    with TestClient(app, base_url="https://example.fly.dev") as client:
        r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"].endswith("/mcp")
    assert isinstance(body["authorization_servers"], list)


def test_protected_resource_metadata_with_mcp_suffix(app):
    with TestClient(app, base_url="https://example.fly.dev") as client:
        r = client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200


def test_authorization_server_metadata(app):
    with TestClient(app, base_url="https://example.fly.dev") as client:
        r = client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    body = r.json()
    assert body["issuer"]
    assert body["authorization_endpoint"].endswith("/oauth/authorize")
    assert body["token_endpoint"].endswith("/oauth/token")
    assert body["registration_endpoint"].endswith("/oauth/register")
    assert "S256" in body["code_challenge_methods_supported"]


def test_dynamic_client_registration(app):
    with TestClient(app) as client:
        r = client.post(
            "/oauth/register",
            json={"redirect_uris": ["https://claude.ai/callback"], "client_name": "Claude"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["client_id"]
    assert body["redirect_uris"] == ["https://claude.ai/callback"]
    assert body["token_endpoint_auth_method"] == "none"


def test_authorize_get_renders_form(app):
    with TestClient(app) as client:
        r = client.get(
            "/oauth/authorize",
            params={
                "client_id": "abc",
                "redirect_uri": "https://claude.ai/cb",
                "state": "xyz",
                "code_challenge": "ch",
                "code_challenge_method": "S256",
            },
        )
    assert r.status_code == 200
    assert "Authorize" in r.text
    assert "abc" in r.text


def test_authorize_post_wrong_bearer_rerenders_form(app):
    with TestClient(app) as client:
        r = client.post(
            "/oauth/authorize",
            data={
                "bearer": "wrong",
                "client_id": "abc",
                "redirect_uri": "https://claude.ai/cb",
                "state": "xyz",
                "code_challenge": "ch",
                "code_challenge_method": "S256",
            },
        )
    assert r.status_code == 200
    assert "Invalid token" in r.text


def test_full_oauth_flow_with_pkce(app):
    verifier = "verifier-string-1234567890abcdefghij"
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    with TestClient(app) as client:
        # Step 1: authorize POST with correct bearer.
        r = client.post(
            "/oauth/authorize",
            data={
                "bearer": "test-bearer",
                "client_id": "claude",
                "redirect_uri": "https://claude.ai/cb",
                "state": "stateZ",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302
        loc = r.headers["location"]
        assert loc.startswith("https://claude.ai/cb")
        # Extract the code.
        from urllib.parse import parse_qs, urlparse

        params = parse_qs(urlparse(loc).query)
        assert params["state"] == ["stateZ"]
        code = params["code"][0]
        # Step 2: exchange code at /oauth/token.
        r = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://claude.ai/cb",
                "code_verifier": verifier,
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["access_token"]
    assert body["expires_in"] > 0


def test_token_endpoint_rejects_wrong_pkce(app):
    verifier = "verifier-string-1234567890abcdefghij"
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    with TestClient(app) as client:
        r = client.post(
            "/oauth/authorize",
            data={
                "bearer": "test-bearer",
                "client_id": "c",
                "redirect_uri": "https://claude.ai/cb",
                "state": "s",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        from urllib.parse import parse_qs, urlparse

        code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]

        r = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://claude.ai/cb",
                "code_verifier": "WRONG-verifier",
            },
        )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_token_endpoint_rejects_garbage_code(app):
    with TestClient(app) as client:
        r = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": "not-a-real-code",
                "redirect_uri": "https://claude.ai/cb",
            },
        )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_unauthorized_mcp_includes_oauth_www_authenticate(monkeypatch):
    from gdrive_video_mcp.http_app import build_app

    app = build_app(bearer_token="test-bearer", include_mcp=False)
    # We need a /mcp route for the bearer middleware to act on.
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def stub(_):
        return JSONResponse({"ok": True})

    app.router.routes.insert(0, Route("/mcp", stub, methods=["POST"]))
    with TestClient(app, base_url="https://example.fly.dev") as client:
        r = client.post("/mcp", json={})
    assert r.status_code == 401
    www = r.headers.get("www-authenticate", "")
    assert 'resource_metadata="https://example.fly.dev/.well-known/oauth-protected-resource"' in www
