"""Tests for the HTTP wrapper — auth middleware + health endpoints.

These tests avoid mounting the real MCP app (StreamableHTTPSessionManager can
only be initialized once per instance, which conflicts with multi-test setup).
The bearer middleware is exercised against a stub `/mcp` route instead.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from gdrive_video_mcp.http_app import BearerAuthMiddleware, build_app


def test_root_returns_service_info_no_auth() -> None:
    app = build_app(bearer_token="", include_mcp=False)
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "gdrive-video-mcp"
    assert body["mcp_endpoint"] == "/mcp"
    assert body["transport"] == "streamable-http"
    assert body["auth"] == "none"


def test_root_reports_bearer_auth_when_configured() -> None:
    app = build_app(bearer_token="secret-token", include_mcp=False)
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    assert r.json()["auth"] == "bearer"


def test_healthz_does_not_require_auth() -> None:
    app = build_app(bearer_token="secret-token", include_mcp=False)
    with TestClient(app) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def _stub_app(token: str | None) -> Starlette:
    """Starlette app with a stub /mcp route, just for middleware testing."""

    async def stub(_):
        return JSONResponse({"stub": True})

    return Starlette(
        routes=[Route("/mcp", stub, methods=["POST", "GET"])],
        middleware=[Middleware(BearerAuthMiddleware, expected_token=token)],
    )


def test_mcp_requires_bearer_when_configured() -> None:
    with TestClient(_stub_app("secret-token")) as client:
        r = client.post("/mcp", json={})
    assert r.status_code == 401
    assert "Authorization" in r.json()["error"]


def test_mcp_rejects_wrong_token() -> None:
    with TestClient(_stub_app("secret-token")) as client:
        r = client.post(
            "/mcp",
            json={},
            headers={"Authorization": "Bearer wrong"},
        )
    assert r.status_code == 403


def test_mcp_accepts_correct_token() -> None:
    with TestClient(_stub_app("secret-token")) as client:
        r = client.post(
            "/mcp",
            json={},
            headers={"Authorization": "Bearer secret-token"},
        )
    assert r.status_code == 200
    assert r.json() == {"stub": True}


def test_mcp_open_when_no_token_configured() -> None:
    with TestClient(_stub_app(None)) as client:
        r = client.post("/mcp", json={})
    assert r.status_code == 200
