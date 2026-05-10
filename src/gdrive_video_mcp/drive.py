"""Google Drive upload helpers."""

from __future__ import annotations

import mimetypes
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# Common video extensions. Lowercase, leading dot included.
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


def iter_videos(folder: Path, recursive: bool = False) -> Iterable[Path]:
    if not folder.exists():
        return
    if not folder.is_dir():
        if is_video_file(folder):
            yield folder
        return
    walker = folder.rglob("*") if recursive else folder.iterdir()
    for entry in walker:
        if is_video_file(entry):
            yield entry


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "video/mp4"


def _share_anyone(service: Resource, file_id: str) -> None:
    try:
        service.permissions().create(
            fileId=file_id,
            body={"role": "reader", "type": "anyone"},
            fields="id",
            supportsAllDrives=True,
        ).execute()
    except HttpError as exc:
        raise RuntimeError(f"Failed to set 'anyone with link' permission: {exc}") from exc


def upload_file(
    service: Resource,
    local_path: Path,
    *,
    name: str | None = None,
    parent_folder_id: str | None = None,
    make_public: bool = True,
) -> dict[str, Any]:
    """Upload a single local file to Drive and (optionally) make it link-shareable.

    Returns a dict with id, name, size, webViewLink, webContentLink.
    """
    if not local_path.exists():
        raise FileNotFoundError(f"File not found: {local_path}")
    if not local_path.is_file():
        raise ValueError(f"Not a regular file: {local_path}")

    metadata: dict[str, Any] = {"name": name or local_path.name}
    if parent_folder_id:
        metadata["parents"] = [parent_folder_id]

    # Resumable for files >5MB; chunked upload is more reliable for big videos.
    file_size = local_path.stat().st_size
    resumable = file_size > 5 * 1024 * 1024
    media = MediaFileUpload(
        str(local_path),
        mimetype=_guess_mime(local_path),
        resumable=resumable,
        chunksize=8 * 1024 * 1024 if resumable else -1,
    )

    request = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, name, size, webViewLink, webContentLink, mimeType",
        supportsAllDrives=True,
    )

    if resumable:
        response: dict[str, Any] | None = None
        while response is None:
            _status, response = request.next_chunk()
        file = response
    else:
        file = request.execute()

    if make_public:
        _share_anyone(service, file["id"])
        # webViewLink is already returned, but refresh to be safe.
        file = (
            service.files()
            .get(
                fileId=file["id"],
                fields="id, name, size, webViewLink, webContentLink, mimeType",
                supportsAllDrives=True,
            )
            .execute()
        )

    return file


def find_folder(service: Resource, name: str, parent_id: str | None = None) -> list[dict[str, Any]]:
    """Find folders by name. Returns all matches (case-sensitive, exact name)."""
    safe_name = name.replace("'", "\\'")
    query = (
        f"mimeType = 'application/vnd.google-apps.folder' and trashed = false "
        f"and name = '{safe_name}'"
    )
    if parent_id:
        query += f" and '{parent_id}' in parents"
    results = (
        service.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id, name, parents, webViewLink)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            pageSize=50,
        )
        .execute()
    )
    return results.get("files", [])


def create_folder(service: Resource, name: str, parent_id: str | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = (
        service.files()
        .create(
            body=metadata,
            fields="id, name, webViewLink, parents",
            supportsAllDrives=True,
        )
        .execute()
    )
    return folder


def human_size(num_bytes: int | str | None) -> str:
    if num_bytes is None:
        return "?"
    try:
        n = float(num_bytes)
    except (TypeError, ValueError):
        return str(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def default_video_dir() -> Path | None:
    env = os.environ.get("GDRIVE_MCP_VIDEO_DIR")
    return Path(env).expanduser() if env else None


def default_drive_folder_id() -> str | None:
    env = os.environ.get("GDRIVE_MCP_DRIVE_FOLDER_ID")
    return env or None
