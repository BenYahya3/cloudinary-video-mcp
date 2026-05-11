"""Minimal OAuth 2.1 + RFC 7591 (Dynamic Client Registration) endpoints.

Claude's "Custom Connector" UI requires the OAuth handshake — static bearer
tokens are only supported by Claude Desktop. This module advertises an OAuth
authorization server colocated with the MCP server, lets any client
self-register (DCR), and after the user pastes the shared bearer token on the
consent page issues short-lived access tokens.

Tokens & codes are HMAC-signed (no DB needed). The signing key is
MCP_BEARER_TOKEN itself — so leaking it is equally bad as leaking the bearer.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

# Token lifetimes — access tokens last 30 days; auth codes last 5 min.
ACCESS_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
AUTH_CODE_TTL_SECONDS = 5 * 60


def _signing_key() -> bytes:
    token = os.environ.get("MCP_BEARER_TOKEN", "").strip()
    if not token:
        # Fall back to a per-process random key so endpoints don't crash in
        # dev mode. In production MCP_BEARER_TOKEN is always set.
        return os.environ.setdefault("_GVMCP_DEV_SIGNING", secrets.token_urlsafe(32)).encode()
    return token.encode()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _sign(payload: dict[str, Any]) -> str:
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64url_encode(hmac.new(_signing_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def _verify(token: str) -> dict[str, Any] | None:
    """Return the payload if the token is valid and unexpired, else None."""
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = _b64url_encode(hmac.new(_signing_key(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except Exception:  # noqa: BLE001
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def _issue_access_token() -> str:
    return _sign(
        {
            "type": "at",
            "iat": int(time.time()),
            "exp": int(time.time()) + ACCESS_TOKEN_TTL_SECONDS,
            "jti": secrets.token_urlsafe(8),
        }
    )


def is_valid_access_token(token: str) -> bool:
    """True if `token` was issued by this server's /oauth/token endpoint."""
    payload = _verify(token)
    return bool(payload and payload.get("type") == "at")


def _server_base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return f"{proto}://{host}"


def protected_resource_metadata(request: Request) -> JSONResponse:
    base = _server_base_url(request)
    return JSONResponse(
        {
            "resource": f"{base}/mcp",
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
            "resource_documentation": "https://github.com/BenYahya3/gdrive-video-mcp",
        }
    )


def authorization_server_metadata(request: Request) -> JSONResponse:
    base = _server_base_url(request)
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256", "plain"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": ["mcp"],
        }
    )


async def register(request: Request) -> JSONResponse:
    """RFC 7591 Dynamic Client Registration. Accept anything; issue a public client."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    redirect_uris = body.get("redirect_uris") or []
    client_id = secrets.token_urlsafe(12)
    return JSONResponse(
        {
            "client_id": client_id,
            "client_id_issued_at": int(time.time()),
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "client_name": body.get("client_name", "MCP Client"),
        }
    )


_CONSENT_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>gdrive-video-mcp — Authorize</title>
<style>
  body { font: 15px/1.5 -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif;
         background: #0b0d12; color: #e6e8eb; margin: 0; min-height: 100vh;
         display: flex; align-items: center; justify-content: center; }
  .card { background: #14171d; border: 1px solid #232732; border-radius: 12px;
          padding: 28px 32px; width: 420px; max-width: calc(100% - 32px); }
  h1 { font-size: 18px; margin: 0 0 6px; }
  p { color: #aab1bd; margin: 0 0 18px; }
  label { display: block; font-size: 13px; margin-bottom: 6px; color: #cbd1da; }
  input[type=password] { width: 100%; padding: 10px 12px; border-radius: 8px;
    border: 1px solid #2a3040; background: #0d1017; color: #e6e8eb;
    font: 14px ui-monospace, SFMono-Regular, monospace; box-sizing: border-box; }
  button { margin-top: 16px; width: 100%; padding: 10px 14px; border-radius: 8px;
    background: #4f46e5; color: white; border: 0; font-weight: 600; cursor: pointer; }
  button:hover { background: #6366f1; }
  .err { color: #f87171; margin: 10px 0 0; font-size: 13px; }
  .hint { color: #6b7280; font-size: 12px; margin-top: 14px; }
  code { color: #e6e8eb; background: #1c2030; padding: 1px 6px; border-radius: 4px; }
</style>
</head>
<body>
<form class="card" method="post" action="">
  <h1>Authorize <code>__CLIENT__</code></h1>
  <p>Paste your MCP bearer token to grant this client access to your Cloudinary videos.</p>
  <label for="t">MCP bearer token</label>
  <input id="t" name="bearer" type="password" autocomplete="off" autofocus placeholder="dCyilwq0…">
  __ERROR__
  <input type="hidden" name="state" value="__STATE__">
  <input type="hidden" name="redirect_uri" value="__REDIRECT__">
  <input type="hidden" name="client_id" value="__CLIENT__">
  <input type="hidden" name="code_challenge" value="__CC__">
  <input type="hidden" name="code_challenge_method" value="__CCM__">
  <button type="submit">Authorize</button>
  <p class="hint">This token was generated when the server was deployed; it
    lives in <code>fly secrets</code> as <code>MCP_BEARER_TOKEN</code>.</p>
</form>
</body>
</html>
"""


def _render_consent(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    error: str | None = None,
) -> HTMLResponse:
    err_html = f'<div class="err">{error}</div>' if error else ""
    html = (
        _CONSENT_PAGE.replace("__CLIENT__", client_id or "client")
        .replace("__STATE__", state)
        .replace("__REDIRECT__", redirect_uri)
        .replace("__CC__", code_challenge)
        .replace("__CCM__", code_challenge_method)
        .replace("__ERROR__", err_html)
    )
    return HTMLResponse(html)


async def authorize(request: Request) -> HTMLResponse | RedirectResponse:
    """GET: show the consent page. POST: validate bearer, redirect with code."""
    if request.method == "GET":
        return _render_consent(
            client_id=request.query_params.get("client_id", ""),
            redirect_uri=request.query_params.get("redirect_uri", ""),
            state=request.query_params.get("state", ""),
            code_challenge=request.query_params.get("code_challenge", ""),
            code_challenge_method=request.query_params.get("code_challenge_method", "S256"),
        )

    form = await request.form()
    bearer = (form.get("bearer") or "").strip()
    expected = os.environ.get("MCP_BEARER_TOKEN", "").strip()
    client_id = form.get("client_id", "")
    redirect_uri = form.get("redirect_uri", "")
    state = form.get("state", "")
    code_challenge = form.get("code_challenge", "")
    code_challenge_method = form.get("code_challenge_method", "S256")

    if not expected or not bearer or not hmac.compare_digest(bearer, expected):
        return _render_consent(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            error="Invalid token. Try again.",
        )

    code = _sign(
        {
            "type": "code",
            "iat": int(time.time()),
            "exp": int(time.time()) + AUTH_CODE_TTL_SECONDS,
            "ru": redirect_uri,
            "cc": code_challenge,
            "ccm": code_challenge_method,
            "cid": client_id,
            "jti": secrets.token_urlsafe(8),
        }
    )

    params = {"code": code}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)


def _verify_pkce(code_challenge: str, method: str, verifier: str) -> bool:
    if not code_challenge:
        return True  # PKCE not used in the authorize step → don't enforce
    if not verifier:
        return False
    if method == "plain":
        return hmac.compare_digest(code_challenge, verifier)
    if method == "S256":
        digest = hashlib.sha256(verifier.encode()).digest()
        return hmac.compare_digest(code_challenge, _b64url_encode(digest))
    return False


async def token(request: Request) -> JSONResponse:
    """Exchange an auth code for an access token."""
    form = await request.form()
    grant_type = form.get("grant_type", "")
    if grant_type != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    code = form.get("code", "")
    redirect_uri = form.get("redirect_uri", "")
    code_verifier = form.get("code_verifier", "")

    payload = _verify(code)
    if not payload or payload.get("type") != "code":
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    if payload.get("ru") and redirect_uri and payload["ru"] != redirect_uri:
        return JSONResponse(
            {"error": "invalid_grant", "error_description": "redirect_uri mismatch"},
            status_code=400,
        )
    if not _verify_pkce(payload.get("cc", ""), payload.get("ccm", "S256"), code_verifier):
        return JSONResponse(
            {"error": "invalid_grant", "error_description": "PKCE failed"}, status_code=400
        )

    access_token = _issue_access_token()
    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_TTL_SECONDS,
            "scope": "mcp",
        }
    )


def attach_routes(app: Starlette) -> None:
    """Attach OAuth + discovery routes to the Starlette app's router."""
    app.router.routes.extend(
        [
            Route(
                "/.well-known/oauth-protected-resource",
                protected_resource_metadata,
                methods=["GET"],
            ),
            # Claude probes the resource-specific path too.
            Route(
                "/.well-known/oauth-protected-resource/mcp",
                protected_resource_metadata,
                methods=["GET"],
            ),
            Route(
                "/.well-known/oauth-authorization-server",
                authorization_server_metadata,
                methods=["GET"],
            ),
            Route("/oauth/register", register, methods=["POST"]),
            Route("/register", register, methods=["POST"]),
            Route("/oauth/authorize", authorize, methods=["GET", "POST"]),
            Route("/oauth/token", token, methods=["POST"]),
        ]
    )
