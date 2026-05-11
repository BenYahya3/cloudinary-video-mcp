"""Tests for the browser upload-link tokens, page render, and POST handler."""

from __future__ import annotations

import io
import time
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("MCP_BEARER_TOKEN", "test-bearer")
    from gdrive_video_mcp.http_app import build_app

    return build_app(bearer_token="test-bearer", include_mcp=False)


def test_create_upload_link_returns_signed_url(monkeypatch):
    monkeypatch.setenv("MCP_BEARER_TOKEN", "test-bearer")
    from gdrive_video_mcp.upload_link import create_upload_link, verify_token

    info = create_upload_link(
        base_url="https://cloudinary-video-mcp.fly.dev",
        filename="tires 1.mp4",
        folder="cowork",
        tags=["claude"],
    )
    assert info["upload_url"].startswith("https://cloudinary-video-mcp.fly.dev/upload/")
    assert info["public_id"] == "tires-1"
    assert info["folder"] == "cowork"
    assert info["expires_in_seconds"] > 0

    token = info["upload_url"].rsplit("/", 1)[1]
    payload = verify_token(token)
    assert payload is not None
    assert payload["type"] == "ul"
    assert payload["public_id"] == "tires-1"
    assert payload["folder"] == "cowork"
    assert payload["tags"] == ["claude"]


def test_invalid_token_returns_410(app):
    with TestClient(app) as client:
        r = client.get("/upload/garbage-token", follow_redirects=False)
    assert r.status_code == 410


def test_expired_token_returns_410(monkeypatch):
    monkeypatch.setenv("MCP_BEARER_TOKEN", "test-bearer")
    from gdrive_video_mcp.http_app import build_app
    from gdrive_video_mcp.upload_link import sign_token

    expired = sign_token({"type": "ul", "iat": 0, "exp": int(time.time()) - 1, "public_id": "x"})
    app = build_app(bearer_token="test-bearer", include_mcp=False)
    with TestClient(app) as client:
        r = client.get(f"/upload/{expired}", follow_redirects=False)
    assert r.status_code == 410


def test_page_renders_with_target_info(monkeypatch):
    monkeypatch.setenv("MCP_BEARER_TOKEN", "test-bearer")
    from gdrive_video_mcp.http_app import build_app
    from gdrive_video_mcp.upload_link import create_upload_link

    info = create_upload_link(
        base_url="https://example.fly.dev",
        filename="big-video.mov",
        folder="reviews",
    )
    token = info["upload_url"].rsplit("/", 1)[1]
    app = build_app(bearer_token="test-bearer", include_mcp=False)
    with TestClient(app) as client:
        r = client.get(f"/upload/{token}")
    assert r.status_code == 200
    assert "reviews/big-video" in r.text
    assert 'enctype="multipart/form-data"' in r.text


def test_post_uploads_to_cloudinary(monkeypatch):
    monkeypatch.setenv("MCP_BEARER_TOKEN", "test-bearer")
    from gdrive_video_mcp.http_app import build_app
    from gdrive_video_mcp.upload_link import create_upload_link

    info = create_upload_link(
        base_url="https://example.fly.dev",
        filename="vid.mp4",
        folder="cowork",
        tags=["smoke"],
    )
    token = info["upload_url"].rsplit("/", 1)[1]

    captured = {}

    def fake_upload(path, **kwargs):
        # Read the file the handler streamed to disk so we can verify content.
        with open(path, "rb") as f:
            captured["bytes"] = f.read()
        captured["kwargs"] = kwargs
        captured["filename"] = path.rsplit("/", 1)[-1]
        return {
            "public_id": kwargs.get("public_id"),
            "url": "https://res.cloudinary.com/x/video/upload/v/cowork/vid.mp4",
            "thumbnail_url": "https://res.cloudinary.com/x/video/upload/so_2/cowork/vid.jpg",
            "format": "mp4",
            "duration": 1.0,
            "width": 320,
            "height": 240,
            "bytes": 99,
            "created_at": "now",
            "folder": "cowork",
            "tags": ["smoke"],
            "resource_type": "video",
        }

    with patch("gdrive_video_mcp.upload_link.upload_file_stream", side_effect=fake_upload):
        app = build_app(bearer_token="test-bearer", include_mcp=False)
        with TestClient(app) as client:
            r = client.post(
                f"/upload/{token}",
                files={"file": ("vid.mp4", io.BytesIO(b"hello world bytes"), "video/mp4")},
            )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"].endswith("/cowork/vid.mp4")
    assert captured["bytes"] == b"hello world bytes"
    assert captured["filename"] == "vid.mp4"
    assert captured["kwargs"]["folder"] == "cowork"
    assert captured["kwargs"]["public_id"] == "vid"
    assert captured["kwargs"]["tags"] == ["smoke"]


def test_post_without_file_returns_400(monkeypatch):
    monkeypatch.setenv("MCP_BEARER_TOKEN", "test-bearer")
    from gdrive_video_mcp.http_app import build_app
    from gdrive_video_mcp.upload_link import create_upload_link

    info = create_upload_link(base_url="https://example.fly.dev", filename="v.mp4")
    token = info["upload_url"].rsplit("/", 1)[1]
    app = build_app(bearer_token="test-bearer", include_mcp=False)
    with TestClient(app) as client:
        r = client.post(f"/upload/{token}", data={"something": "else"})
    assert r.status_code == 400
    assert "file" in r.json()["error"]


def test_status_returns_not_ready_before_upload(monkeypatch):
    monkeypatch.setenv("MCP_BEARER_TOKEN", "test-bearer")
    from gdrive_video_mcp.http_app import build_app
    from gdrive_video_mcp.upload_link import create_upload_link

    info = create_upload_link(base_url="https://example.fly.dev", filename="v.mp4", folder="cowork")
    token = info["upload_url"].rsplit("/", 1)[1]

    def fake_get_video(_):
        raise RuntimeError("not found")

    with patch("gdrive_video_mcp.cloudinary_client.get_video", side_effect=fake_get_video):
        app = build_app(bearer_token="test-bearer", include_mcp=False)
        with TestClient(app) as client:
            r = client.get(f"/upload/{token}/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False
    assert body["public_id"] == "cowork/v"


def test_upload_link_routes_do_not_require_bearer(monkeypatch):
    """Upload URLs are themselves the auth — they must NOT also require a bearer."""
    monkeypatch.setenv("MCP_BEARER_TOKEN", "test-bearer")
    from gdrive_video_mcp.http_app import build_app
    from gdrive_video_mcp.upload_link import create_upload_link

    info = create_upload_link(base_url="https://example.fly.dev", filename="v.mp4")
    token = info["upload_url"].rsplit("/", 1)[1]
    app = build_app(bearer_token="test-bearer", include_mcp=False)
    with TestClient(app) as client:
        # No Authorization header — should still get the upload page.
        r = client.get(f"/upload/{token}")
    assert r.status_code == 200
