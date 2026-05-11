"""Companion CLI: upload every video in a local folder to Cloudinary.

Designed to run on the user's machine — talks to Cloudinary directly, no
round-trip through the Fly MCP server.

Usage:
    gdrive-video-mcp-upload /path/to/videos --folder cowork --tag claude
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from gdrive_video_mcp.cloudinary_client import (
    is_video_file,
    upload_from_source,
)


def _iter_videos(folder: Path, recursive: bool) -> list[Path]:
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")
    if folder.is_file():
        return [folder] if is_video_file(folder) else []
    walker = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(p for p in walker if is_video_file(p))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload every video in a local folder to Cloudinary."
    )
    parser.add_argument("path", help="Local folder (or single video file).")
    parser.add_argument(
        "--folder",
        help="Cloudinary folder to upload into (e.g. 'cowork').",
        default=None,
    )
    parser.add_argument(
        "--tag",
        action="append",
        help="Tag to attach to each upload. Repeat for multiple tags.",
        default=None,
    )
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Descend into subfolders.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing Cloudinary assets with the same public_id.",
    )
    args = parser.parse_args()

    if not os.environ.get("CLOUDINARY_URL"):
        print(
            "error: CLOUDINARY_URL is not set. Export it before running, e.g.\n"
            "  export CLOUDINARY_URL='cloudinary://API_KEY:API_SECRET@CLOUD_NAME'",
            file=sys.stderr,
        )
        return 2

    folder = Path(args.path).expanduser()
    try:
        videos = _iter_videos(folder, recursive=args.recursive)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not videos:
        print(f"No video files found under {folder}.")
        return 0

    print(f"Uploading {len(videos)} video(s) to Cloudinary...")
    failures = 0
    for path in videos:
        try:
            result = upload_from_source(
                str(path),
                folder=args.folder,
                tags=args.tag,
                overwrite=args.overwrite,
            )
            print(f"  ✓ {path.name} → {result['url']}")
        except Exception as exc:  # noqa: BLE001 - per-file failure should not abort
            failures += 1
            print(f"  ✗ {path.name}: {exc}", file=sys.stderr)

    if failures:
        print(f"\nDone with {failures} failure(s).", file=sys.stderr)
        return 1
    print("\nAll uploads completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
