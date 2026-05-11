"""Unit tests for the upload_video tool's base64 handling (no Cloudinary calls)."""

from __future__ import annotations

import base64
from unittest.mock import patch

import pytest

from gdrive_video_mcp.server import upload_video


def _captured_source() -> dict:
    """Returns a holder that captures the source arg passed to upload_from_source."""
    return {"called_with": None}


def test_accepts_plain_base64_and_infers_mp4_mime() -> None:
    payload = b"\x00\x00\x00\x18ftypmp42fake_video_bytes"
    encoded = base64.b64encode(payload).decode()
    captured = _captured_source()

    def fake(src, **kwargs):
        captured["called_with"] = src
        captured["kwargs"] = kwargs
        return {"public_id": "x"}

    with patch("gdrive_video_mcp.server.upload_from_source", side_effect=fake):
        upload_video(file_data_base64=encoded, filename="tires 1.mp4")

    src = captured["called_with"]
    assert src.startswith("data:video/mp4;base64,")
    assert encoded in src
    # filename stem becomes the public_id when none provided.
    assert captured["kwargs"]["public_id"] == "tires 1"


def test_accepts_data_uri_passthrough() -> None:
    uri = "data:video/quicktime;base64,AAAA"
    captured = _captured_source()

    with patch(
        "gdrive_video_mcp.server.upload_from_source",
        side_effect=lambda s, **k: captured.update({"called_with": s}) or {"public_id": "x"},
    ):
        upload_video(file_data_base64=uri)

    assert captured["called_with"] == uri


def test_strips_whitespace_and_newlines() -> None:
    payload = b"hello world"
    encoded = base64.b64encode(payload).decode()
    chunked = "\n".join(encoded[i : i + 4] for i in range(0, len(encoded), 4))
    captured = _captured_source()

    with patch(
        "gdrive_video_mcp.server.upload_from_source",
        side_effect=lambda s, **k: captured.update({"called_with": s}) or {"public_id": "x"},
    ):
        upload_video(file_data_base64=chunked, filename="vid.mp4")

    assert "\n" not in captured["called_with"]
    assert encoded in captured["called_with"]


def test_rejects_empty_base64() -> None:
    with pytest.raises(ValueError):
        upload_video(file_data_base64="")


def test_rejects_invalid_base64() -> None:
    with pytest.raises(ValueError):
        upload_video(file_data_base64="@@@not-base64@@@")


def test_explicit_public_id_overrides_filename() -> None:
    encoded = base64.b64encode(b"data").decode()
    captured = _captured_source()

    with patch(
        "gdrive_video_mcp.server.upload_from_source",
        side_effect=lambda s, **k: captured.update(k) or {"public_id": "x"},
    ):
        upload_video(file_data_base64=encoded, filename="tires.mp4", public_id="custom-id")

    assert captured["public_id"] == "custom-id"
