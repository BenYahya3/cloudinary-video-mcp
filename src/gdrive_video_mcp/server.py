"""FastMCP server exposing Cloudinary video tools.

Transport-agnostic — wired into HTTP by `http_app.py` and used over stdio for
local development with `python -m gdrive_video_mcp.server`.
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from gdrive_video_mcp.cloudinary_client import (
    delete_video as _delete_video,
)
from gdrive_video_mcp.cloudinary_client import (
    get_video as _get_video,
)
from gdrive_video_mcp.cloudinary_client import (
    list_videos as _list_videos,
)
from gdrive_video_mcp.cloudinary_client import (
    upload_from_source,
)
from gdrive_video_mcp.cloudinary_client import (
    whoami as _whoami,
)
from gdrive_video_mcp.upload_link import (
    DEFAULT_TTL_SECONDS,
)
from gdrive_video_mcp.upload_link import (
    create_upload_link as _create_upload_link,
)


def _transport_security() -> TransportSecuritySettings:
    """Build DNS-rebinding-protection settings from MCP_ALLOWED_HOSTS env var.

    Set MCP_ALLOWED_HOSTS to a comma-separated list of Host header values
    (e.g. "cloudinary-video-mcp.fly.dev"). Set it to "*" to disable the check
    entirely (only use this when the endpoint is gated by another auth layer,
    like our bearer middleware).
    """
    raw = os.environ.get("MCP_ALLOWED_HOSTS", "").strip()
    if not raw:
        return TransportSecuritySettings()  # defaults — localhost only
    if raw == "*":
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    # Allow both bare hostnames and http/https origins for those hosts.
    origins: list[str] = []
    for h in hosts:
        origins.extend([f"https://{h}", f"http://{h}"])
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


# stateless_http=True makes the Streamable HTTP transport stateless so it works
# behind Fly's per-request load balancer without sticky sessions.
mcp = FastMCP(
    "gdrive-video-mcp",
    instructions=(
        "Upload videos to Cloudinary and get back permanent CDN URLs. "
        "Use `upload_video` to upload a local file (pass its bytes as base64), "
        "`upload_from_url` for a public source URL, `list_videos` to browse "
        "what's already uploaded, and `get_video` for a specific public_id."
    ),
    stateless_http=True,
    transport_security=_transport_security(),
)


@mcp.tool()
def upload_from_url(
    url: str,
    public_id: str | None = None,
    folder: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Upload a video to Cloudinary by URL. Cloudinary fetches the URL directly.

    Args:
        url: Public HTTP/HTTPS URL of a video file. Cloudinary streams it.
        public_id: Optional Cloudinary public_id (the slug part of the resulting URL).
            If omitted, Cloudinary generates a random one.
        folder: Optional Cloudinary folder to upload into.
        tags: Optional list of tags to attach to the asset.

    Returns the uploaded asset's CDN URL, thumbnail URL, dimensions, duration,
    and Cloudinary public_id.
    """
    return upload_from_source(url, public_id=public_id, folder=folder, tags=tags)


@mcp.tool()
def upload_video(
    file_data_base64: str,
    filename: str = "",
    public_id: str | None = None,
    folder: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Upload a local video file to Cloudinary. Pass the file bytes as base64.

    Use this when you have the video as raw bytes (e.g. a local file the user
    attached) rather than a public URL.

    Args:
        file_data_base64: The video file contents, base64-encoded. May be a raw
            base64 string or a full ``data:video/mp4;base64,...`` data URI.
        filename: Optional original filename. Used to infer MIME type and as a
            fallback for the Cloudinary public_id when one isn't provided.
        public_id: Optional Cloudinary public_id (the slug part of the URL).
        folder: Optional Cloudinary folder.
        tags: Optional list of tags to attach to the asset.

    Returns the uploaded asset's CDN URL, thumbnail URL, dimensions, duration,
    and Cloudinary public_id.
    """
    data = (file_data_base64 or "").strip()
    if not data:
        raise ValueError("file_data_base64 is empty")

    if data.startswith("data:"):
        # Already a data URI — pass straight through.
        source = data
    else:
        # Strip whitespace/newlines that some encoders insert.
        b64 = "".join(data.split())
        try:
            base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"file_data_base64 is not valid base64: {e}") from e
        mime = (mimetypes.guess_type(filename)[0] if filename else None) or "video/mp4"
        source = f"data:{mime};base64,{b64}"

    if public_id is None and filename:
        # Use the filename stem (without extension) as a stable public_id hint.
        stem = os.path.splitext(os.path.basename(filename))[0].strip()
        if stem:
            public_id = stem

    return upload_from_source(source, public_id=public_id, folder=folder, tags=tags)


@mcp.tool()
def list_videos(
    folder: str | None = None,
    tag: str | None = None,
    max_results: int = 50,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    """List videos already on your Cloudinary account.

    Args:
        folder: Filter by Cloudinary folder prefix (e.g. "cowork").
        tag: Filter by a single tag (mutually exclusive with folder).
        max_results: 1-500.
        next_cursor: Pagination cursor from a previous response.
    """
    return _list_videos(folder=folder, tag=tag, max_results=max_results, next_cursor=next_cursor)


@mcp.tool()
def get_video(public_id: str) -> dict[str, Any]:
    """Get metadata + CDN URL + thumbnail URL for a specific Cloudinary video by public_id."""
    return _get_video(public_id)


@mcp.tool()
def delete_video(public_id: str) -> dict[str, Any]:
    """Permanently delete a video from Cloudinary by public_id. This cannot be undone."""
    return _delete_video(public_id)


@mcp.tool()
def whoami() -> dict[str, Any]:
    """Return the configured Cloudinary cloud_name and (when available) usage stats."""
    return _whoami()


@mcp.tool()
def create_upload_link(
    filename: str = "",
    folder: str | None = None,
    tags: list[str] | None = None,
    public_id: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Generate a one-time browser upload URL for files too large to base64-encode.

    Use this when the file is bigger than a few MB. Pass the returned
    `upload_url` to the user; when they open it they get a drag-and-drop page
    that uploads the file directly to Cloudinary via this server (no third
    party). After they upload, look up the resulting asset via `get_video`
    using the returned `public_id`, or poll `<upload_url>/status`.

    Args:
        filename: Original filename. Used to derive the default public_id.
        folder: Optional Cloudinary folder to upload into.
        tags: Optional list of tags.
        public_id: Optional Cloudinary public_id (slug). Defaults to a slugified
            version of the filename stem.
        ttl_seconds: How long the link is valid for. Min 60s, max 24h, default 1h.

    Returns ``{upload_url, public_id, folder, expires_at, expires_in_seconds,
    instructions}``.
    """
    base_url = (
        os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or "https://cloudinary-video-mcp.fly.dev"
    )
    return _create_upload_link(
        base_url=base_url,
        filename=filename,
        folder=folder,
        tags=tags,
        public_id=public_id,
        ttl_seconds=ttl_seconds,
    )


def main() -> None:
    """Run as a stdio MCP server (for local dev / Claude Desktop)."""
    mcp.run()


if __name__ == "__main__":
    main()
