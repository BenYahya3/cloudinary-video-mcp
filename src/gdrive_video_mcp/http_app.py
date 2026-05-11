"""HTTP entrypoint: Streamable HTTP MCP at /mcp behind bearer-token / OAuth auth.

Designed to run on Fly.io. Exposes:
- GET  /                                        → service info (no auth)
- GET  /healthz                                 → health probe (no auth)
- GET  /.well-known/oauth-protected-resource    → OAuth discovery (no auth)
- GET  /.well-known/oauth-authorization-server  → OAuth discovery (no auth)
- POST /oauth/register                          → DCR (RFC 7591)
- GET/POST /oauth/authorize                     → consent page
- POST /oauth/token                             → exchange code for access token
- POST /mcp                                     → MCP Streamable HTTP (auth)
- GET  /mcp                                     → MCP Streamable HTTP SSE (auth)

Accepted credentials on /mcp:
- The static MCP_BEARER_TOKEN (used by Claude Desktop / curl), or
- An OAuth-issued access token from /oauth/token (used by claude.ai web).
"""

from __future__ import annotations

import os
import secrets

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from gdrive_video_mcp import __version__
from gdrive_video_mcp.oauth import attach_routes as attach_oauth_routes
from gdrive_video_mcp.oauth import is_valid_access_token
from gdrive_video_mcp.server import mcp


def _wants_oauth_advert(path: str) -> bool:
    """Return True for endpoints where unauthenticated requests should advertise OAuth."""
    return path.startswith("/mcp")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Require a valid bearer token (static or OAuth-issued) on /mcp routes.

    If `expected_token` is empty, the middleware is a no-op (development mode).
    """

    def __init__(
        self,
        app,
        protected_prefix: str = "/mcp",
        expected_token: str | None = None,
    ) -> None:
        super().__init__(app)
        self.protected_prefix = protected_prefix
        self.expected_token = (expected_token or "").strip()

    async def dispatch(self, request: Request, call_next) -> Response:
        if not request.url.path.startswith(self.protected_prefix):
            return await call_next(request)
        if not self.expected_token:
            return await call_next(request)
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return _unauthorized(request, "missing Authorization: Bearer <token>")
        # Accept either the static bearer or an OAuth-issued access token.
        if secrets.compare_digest(token, self.expected_token):
            return await call_next(request)
        if is_valid_access_token(token):
            return await call_next(request)
        return _unauthorized(request, "invalid token")


def _unauthorized(request: Request, message: str) -> JSONResponse:
    """Return 401 with a WWW-Authenticate header pointing Claude at OAuth discovery."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    base = f"{proto}://{host}" if host else ""
    resource_metadata = f"{base}/.well-known/oauth-protected-resource"
    headers = {
        "WWW-Authenticate": (
            f'Bearer realm="gdrive-video-mcp", resource_metadata="{resource_metadata}"'
        )
    }
    return JSONResponse({"error": message}, status_code=401, headers=headers)


def _make_info_route(auth_mode: str):
    async def root(request: Request) -> JSONResponse:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        base = f"{proto}://{host}" if host else ""
        return JSONResponse(
            {
                "name": "gdrive-video-mcp",
                "version": __version__,
                "mcp_endpoint": "/mcp",
                "auth": auth_mode,
                "transport": "streamable-http",
                "oauth": {
                    "authorization_endpoint": f"{base}/oauth/authorize",
                    "token_endpoint": f"{base}/oauth/token",
                    "registration_endpoint": f"{base}/oauth/register",
                },
            }
        )

    return root


async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def build_app(*, bearer_token: str | None = None, include_mcp: bool = True) -> Starlette:
    """Build the ASGI application.

    Args:
        bearer_token: Required token for /mcp routes. Empty/None disables auth.
        include_mcp: If False, omit the MCP mount (used by lightweight tests
            so the StreamableHTTPSessionManager isn't initialized).
    """
    token = (
        bearer_token if bearer_token is not None else os.environ.get("MCP_BEARER_TOKEN", "")
    ).strip()
    auth_mode = "bearer" if token else "none"

    # Build the OAuth + discovery routes first; they must be evaluated BEFORE
    # the catch-all Mount("/") for the MCP app, otherwise Starlette routes
    # /.well-known/... and /oauth/... into the FastMCP app (which returns 404).
    oauth_routes = _oauth_route_list()
    routes: list = [
        Route("/", _make_info_route(auth_mode), methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
        *oauth_routes,
    ]
    lifespan_ctx = None
    if include_mcp:
        mcp_app = mcp.streamable_http_app()
        # FastMCP's app already routes /mcp internally; mount at root so the
        # final URL is /mcp (not /mcp/mcp). The routes above are matched first
        # since Starlette evaluates routes in order.
        routes.append(Mount("/", app=mcp_app))
        # MCP requires its session manager's lifespan to run; otherwise requests hang.
        lifespan_ctx = mcp_app.router.lifespan_context

    return Starlette(
        routes=routes,
        middleware=[
            Middleware(BearerAuthMiddleware, expected_token=token),
        ],
        lifespan=lifespan_ctx,
    )


def _oauth_route_list():
    """Return the OAuth + discovery routes (extracted from oauth.attach_routes)."""
    from starlette.applications import Starlette as _S

    tmp = _S()
    attach_oauth_routes(tmp)
    return list(tmp.router.routes)


# Module-level ASGI app for uvicorn / Fly. Reads token from env at import time.
app = build_app()


def main() -> None:
    """Run the HTTP server (entrypoint for `gdrive-video-mcp` console script)."""
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run(
        "gdrive_video_mcp.http_app:app",
        host=host,
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "info"),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
