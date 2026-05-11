"""HTTP entrypoint: Streamable HTTP MCP at /mcp behind a bearer-token check.

Designed to run on Fly.io. Exposes:
- GET  /           → service info (no auth)
- GET  /healthz    → health probe (no auth)
- POST /mcp        → MCP Streamable HTTP transport (requires bearer token)
- GET  /mcp        → MCP Streamable HTTP transport (SSE; requires bearer token)
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
from gdrive_video_mcp.server import mcp


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Require `Authorization: Bearer <token>` on the protected prefix.

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
            return JSONResponse(
                {"error": "missing Authorization: Bearer <token>"},
                status_code=401,
            )
        if not secrets.compare_digest(token, self.expected_token):
            return JSONResponse({"error": "invalid token"}, status_code=403)
        return await call_next(request)


def _make_info_route(auth_mode: str):
    async def root(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "name": "gdrive-video-mcp",
                "version": __version__,
                "mcp_endpoint": "/mcp",
                "auth": auth_mode,
                "transport": "streamable-http",
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

    routes: list = [
        Route("/", _make_info_route(auth_mode), methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
    ]
    lifespan_ctx = None
    if include_mcp:
        mcp_app = mcp.streamable_http_app()
        # FastMCP's app already routes /mcp internally; mount at root so the
        # final URL is /mcp (not /mcp/mcp). Other routes above are matched first
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
