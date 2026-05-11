"""FastMCP server exposing Cloudinary video tools.

Transport-agnostic — wired into HTTP by `http_app.py` and used over stdio for
local development with `python -m gdrive_video_mcp.server`.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

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

# stateless_http=True makes the Streamable HTTP transport stateless so it works
# behind Fly's per-request load balancer without sticky sessions.
mcp = FastMCP(
    "gdrive-video-mcp",
    instructions=(
        "Upload videos to Cloudinary and get back permanent CDN URLs. "
        "Use upload_from_url for a public source URL, list_videos to browse "
        "what's already uploaded, and get_video for a specific public_id."
    ),
    stateless_http=True,
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


def main() -> None:
    """Run as a stdio MCP server (for local dev / Claude Desktop)."""
    mcp.run()


if __name__ == "__main__":
    main()
