"""Tests for the parts of the package that don't require Cloudinary API access."""

from __future__ import annotations

from pathlib import Path

from gdrive_video_mcp.cloudinary_client import VIDEO_EXTENSIONS, is_video_file


def test_video_extensions_lowercased_with_dot() -> None:
    for ext in VIDEO_EXTENSIONS:
        assert ext.startswith(".")
        assert ext == ext.lower()


def test_is_video_file(tmp_path: Path) -> None:
    mp4 = tmp_path / "x.mp4"
    mp4.write_bytes(b"x")
    txt = tmp_path / "x.txt"
    txt.write_text("hi")
    assert is_video_file(mp4) is True
    assert is_video_file(txt) is False
    assert is_video_file(tmp_path) is False
