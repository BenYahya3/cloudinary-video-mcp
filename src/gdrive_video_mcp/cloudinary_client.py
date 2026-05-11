"""Cloudinary helpers — upload, list, get, delete videos."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import cloudinary
import cloudinary.api
import cloudinary.uploader

# Common video extensions used to filter local folders.
VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mp4",
        ".mov",
        ".m4v",
        ".mkv",
        ".webm",
        ".avi",
        ".wmv",
        ".flv",
        ".mpeg",
        ".mpg",
        ".3gp",
        ".ts",
        ".mts",
        ".m2ts",
    }
)


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def configure_from_env() -> None:
    """Configure the Cloudinary SDK from the CLOUDINARY_URL env var.

    The cloudinary SDK auto-reads CLOUDINARY_URL at import time, but we call this
    explicitly so callers get a clear error if the variable is missing.
    """
    url = os.environ.get("CLOUDINARY_URL")
    if not url:
        raise RuntimeError(
            "CLOUDINARY_URL is not set. Expected format: "
            "cloudinary://<api_key>:<api_secret>@<cloud_name>"
        )
    # cloudinary.config() picks it up from env on its own, but call to validate.
    cfg = cloudinary.config(secure=True)
    if not cfg.cloud_name:
        raise RuntimeError(
            "CLOUDINARY_URL did not parse into a valid config. Double-check the format."
        )


def _normalize_video(asset: dict[str, Any]) -> dict[str, Any]:
    """Reduce a Cloudinary resource dict to the fields we expose over MCP."""
    public_id = asset.get("public_id")
    secure_url = asset.get("secure_url")
    # Thumbnail: take a still at 2 seconds in, 480px wide.
    thumbnail_url: str | None = None
    if public_id and secure_url:
        thumbnail_url = (
            f"https://res.cloudinary.com/{cloudinary.config().cloud_name}"
            f"/video/upload/so_2,w_480,c_fill,f_jpg/{public_id}.jpg"
        )
    return {
        "public_id": public_id,
        "url": secure_url,
        "thumbnail_url": thumbnail_url,
        "format": asset.get("format"),
        "duration": asset.get("duration"),
        "width": asset.get("width"),
        "height": asset.get("height"),
        "bytes": asset.get("bytes"),
        "created_at": asset.get("created_at"),
        "folder": asset.get("folder") or asset.get("asset_folder"),
        "tags": asset.get("tags") or [],
        "resource_type": asset.get("resource_type"),
    }


def upload_from_source(
    source: str,
    *,
    public_id: str | None = None,
    folder: str | None = None,
    tags: list[str] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Upload a video to Cloudinary.

    `source` may be:
    - A public HTTP/HTTPS URL — Cloudinary fetches it directly.
    - A local file path — uploaded as multipart from the server.
    - A data URL (data:video/mp4;base64,...) — decoded by the SDK.
    """
    configure_from_env()
    upload_args: dict[str, Any] = {
        "resource_type": "video",
        "overwrite": overwrite,
        "unique_filename": public_id is None,
    }
    if public_id:
        upload_args["public_id"] = public_id
    if folder:
        upload_args["folder"] = folder
    if tags:
        upload_args["tags"] = tags

    result = cloudinary.uploader.upload(source, **upload_args)
    return _normalize_video(result)


def list_videos(
    folder: str | None = None,
    tag: str | None = None,
    max_results: int = 50,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    configure_from_env()
    max_results = max(1, min(max_results, 500))

    if tag:
        result = cloudinary.api.resources_by_tag(
            tag,
            resource_type="video",
            max_results=max_results,
            next_cursor=next_cursor,
        )
    else:
        kwargs: dict[str, Any] = {
            "resource_type": "video",
            "type": "upload",
            "max_results": max_results,
        }
        if folder:
            kwargs["prefix"] = folder.rstrip("/") + "/"
        if next_cursor:
            kwargs["next_cursor"] = next_cursor
        result = cloudinary.api.resources(**kwargs)

    return {
        "count": len(result.get("resources", [])),
        "next_cursor": result.get("next_cursor"),
        "videos": [_normalize_video(r) for r in result.get("resources", [])],
    }


def get_video(public_id: str) -> dict[str, Any]:
    configure_from_env()
    result = cloudinary.api.resource(public_id, resource_type="video")
    return _normalize_video(result)


def delete_video(public_id: str) -> dict[str, Any]:
    configure_from_env()
    result = cloudinary.uploader.destroy(public_id, resource_type="video", invalidate=True)
    return {"public_id": public_id, "result": result.get("result")}


def whoami() -> dict[str, Any]:
    configure_from_env()
    cfg = cloudinary.config()
    usage: dict[str, Any] = {}
    try:
        # api.usage works on most plans; ignore failures (free-tier scopes vary).
        usage = cloudinary.api.usage()
    except Exception as exc:  # noqa: BLE001
        usage = {"error": f"usage info unavailable: {exc}"}
    return {
        "cloud_name": cfg.cloud_name,
        "secure": bool(cfg.secure),
        "usage": {
            "plan": usage.get("plan") if isinstance(usage, dict) else None,
            "storage_bytes": (usage.get("storage") or {}).get("usage")
            if isinstance(usage, dict)
            else None,
            "bandwidth_bytes": (usage.get("bandwidth") or {}).get("usage")
            if isinstance(usage, dict)
            else None,
            "credits_usage": (usage.get("credits") or {}).get("usage")
            if isinstance(usage, dict)
            else None,
        },
    }
