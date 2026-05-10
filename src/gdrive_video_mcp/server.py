"""MCP server exposing Google Drive video upload tools over stdio."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from gdrive_video_mcp.auth import drive_service
from gdrive_video_mcp.drive import (
    create_folder,
    default_drive_folder_id,
    default_video_dir,
    find_folder,
    human_size,
    is_video_file,
    iter_videos,
    upload_file,
)

mcp = FastMCP(
    "gdrive-video-mcp",
    instructions=(
        "Upload local video files to Google Drive and return shareable links. "
        "Use list_videos to see what's in the configured folder, then "
        "upload_video for a single file or upload_folder to upload everything. "
        "Set GDRIVE_MCP_VIDEO_DIR to point at the default local video folder "
        "and GDRIVE_MCP_DRIVE_FOLDER_ID to upload into a specific Drive folder."
    ),
)


def _resolve_local_folder(folder_path: str | None) -> Path:
    if folder_path:
        p = Path(folder_path).expanduser()
    else:
        default = default_video_dir()
        if default is None:
            raise ValueError(
                "No folder_path provided and GDRIVE_MCP_VIDEO_DIR is not set. "
                "Pass folder_path explicitly or configure the env var."
            )
        p = default
    if not p.exists():
        raise FileNotFoundError(f"Folder not found: {p}")
    if not p.is_dir():
        raise NotADirectoryError(f"Not a directory: {p}")
    return p


def _resolve_drive_folder_id(drive_folder_id: str | None) -> str | None:
    return drive_folder_id or default_drive_folder_id()


@mcp.tool()
def list_videos(folder_path: str | None = None, recursive: bool = False) -> dict[str, Any]:
    """List video files in a local folder.

    Args:
        folder_path: Local folder to scan. If omitted, uses the GDRIVE_MCP_VIDEO_DIR env var.
        recursive: If true, descend into subfolders.

    Returns the folder scanned and a list of {name, path, size_bytes, size_human}.
    """
    folder = _resolve_local_folder(folder_path)
    videos = []
    for path in sorted(iter_videos(folder, recursive=recursive)):
        size = path.stat().st_size
        videos.append(
            {
                "name": path.name,
                "path": str(path),
                "size_bytes": size,
                "size_human": human_size(size),
            }
        )
    return {"folder": str(folder), "count": len(videos), "videos": videos}


@mcp.tool()
def upload_video(
    file_path: str,
    name: str | None = None,
    drive_folder_id: str | None = None,
    make_public: bool = True,
) -> dict[str, Any]:
    """Upload a single local video file to Google Drive.

    Args:
        file_path: Absolute or ~-expanded path to the video file.
        name: Optional name to use for the uploaded file. Defaults to the local filename.
        drive_folder_id: Drive folder ID to upload into. Defaults to GDRIVE_MCP_DRIVE_FOLDER_ID
            if set, otherwise the user's Drive root.
        make_public: If true (default), set permission "anyone with link can view" and
            return the shareable webViewLink.

    Returns metadata including the shareable link (`link`).
    """
    path = Path(file_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not is_video_file(path):
        # Don't hard-fail on weird extensions; just warn via the response.
        warning = f"{path.name} does not have a recognized video extension; uploading anyway."
    else:
        warning = None

    parent = _resolve_drive_folder_id(drive_folder_id)
    service = drive_service()
    file = upload_file(
        service,
        path,
        name=name,
        parent_folder_id=parent,
        make_public=make_public,
    )

    return {
        "id": file["id"],
        "name": file["name"],
        "size_bytes": int(file.get("size") or 0),
        "size_human": human_size(file.get("size")),
        "mime_type": file.get("mimeType"),
        "link": file.get("webViewLink"),
        "download_link": file.get("webContentLink"),
        "drive_folder_id": parent,
        "make_public": make_public,
        "warning": warning,
    }


@mcp.tool()
def upload_folder(
    folder_path: str | None = None,
    drive_folder_id: str | None = None,
    recursive: bool = False,
    make_public: bool = True,
) -> dict[str, Any]:
    """Upload every video file in a local folder to Google Drive.

    Args:
        folder_path: Local folder to scan. Defaults to GDRIVE_MCP_VIDEO_DIR.
        drive_folder_id: Drive folder ID to upload into. Defaults to GDRIVE_MCP_DRIVE_FOLDER_ID.
        recursive: If true, descend into subfolders.
        make_public: If true (default), set "anyone with link can view" on each upload.

    Returns a per-file result list with shareable links and any errors.
    """
    folder = _resolve_local_folder(folder_path)
    parent = _resolve_drive_folder_id(drive_folder_id)
    service = drive_service()

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for path in sorted(iter_videos(folder, recursive=recursive)):
        try:
            file = upload_file(
                service,
                path,
                parent_folder_id=parent,
                make_public=make_public,
            )
            results.append(
                {
                    "source": str(path),
                    "id": file["id"],
                    "name": file["name"],
                    "size_human": human_size(file.get("size")),
                    "link": file.get("webViewLink"),
                }
            )
        except Exception as exc:  # noqa: BLE001 - surface per-file errors
            errors.append({"source": str(path), "error": str(exc)})

    return {
        "folder": str(folder),
        "drive_folder_id": parent,
        "uploaded_count": len(results),
        "error_count": len(errors),
        "uploads": results,
        "errors": errors,
    }


@mcp.tool()
def find_drive_folder(name: str, parent_id: str | None = None) -> dict[str, Any]:
    """Find Google Drive folders by exact name. Returns id, name, and parents for each match."""
    service = drive_service()
    matches = find_folder(service, name, parent_id=parent_id)
    return {"name": name, "count": len(matches), "folders": matches}


@mcp.tool()
def create_drive_folder(name: str, parent_id: str | None = None) -> dict[str, Any]:
    """Create a new folder in Google Drive and return its id and link."""
    service = drive_service()
    folder = create_folder(service, name, parent_id=parent_id)
    return folder


@mcp.tool()
def whoami() -> dict[str, Any]:
    """Return the authenticated Drive user's email and basic quota info."""
    service = drive_service()
    about = (
        service.about()
        .get(fields="user(emailAddress, displayName), storageQuota(limit, usage, usageInDrive)")
        .execute()
    )
    return about


def main() -> None:
    """Entry point for the `gdrive-video-mcp` console script."""
    try:
        mcp.run()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
