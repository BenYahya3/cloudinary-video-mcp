"""Tests for the parts of the package that don't require Google API access."""

from __future__ import annotations

from pathlib import Path

from gdrive_video_mcp.drive import (
    VIDEO_EXTENSIONS,
    human_size,
    is_video_file,
    iter_videos,
)


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
    assert is_video_file(tmp_path) is False  # directories are not files


def test_iter_videos_flat_and_recursive(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.MOV").write_bytes(b"x")  # case-insensitive
    (tmp_path / "c.txt").write_text("nope")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.webm").write_bytes(b"x")

    flat = sorted(p.name for p in iter_videos(tmp_path))
    assert flat == ["a.mp4", "b.MOV"]

    rec = sorted(p.name for p in iter_videos(tmp_path, recursive=True))
    assert rec == ["a.mp4", "b.MOV", "d.webm"]


def test_iter_videos_missing_folder(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert list(iter_videos(missing)) == []


def test_iter_videos_single_file(tmp_path: Path) -> None:
    f = tmp_path / "solo.mkv"
    f.write_bytes(b"x")
    assert [p.name for p in iter_videos(f)] == ["solo.mkv"]


def test_human_size() -> None:
    assert human_size(0) == "0.0 B"
    assert human_size(1023) == "1023.0 B"
    assert human_size(1024) == "1.0 KB"
    assert human_size(1024 * 1024) == "1.0 MB"
    assert human_size(None) == "?"
    assert human_size("not-a-number") == "not-a-number"
