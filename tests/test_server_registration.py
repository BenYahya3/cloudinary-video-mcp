"""Verify the MCP server registers all expected tools."""

from __future__ import annotations

import asyncio

from gdrive_video_mcp.server import mcp


def _tool_names() -> set[str]:
    tools = asyncio.run(mcp.list_tools())
    return {t.name for t in tools}


def test_all_expected_tools_registered() -> None:
    expected = {
        "list_videos",
        "upload_video",
        "upload_folder",
        "find_drive_folder",
        "create_drive_folder",
        "whoami",
    }
    assert expected.issubset(_tool_names())


def test_no_unexpected_extra_tools() -> None:
    # If new tools are added, update this list intentionally.
    allowed = {
        "list_videos",
        "upload_video",
        "upload_folder",
        "find_drive_folder",
        "create_drive_folder",
        "whoami",
    }
    extras = _tool_names() - allowed
    assert not extras, f"Unexpected tools registered: {extras}"
