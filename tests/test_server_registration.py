"""Verify the MCP server registers all expected tools."""

from __future__ import annotations

import asyncio

from gdrive_video_mcp.server import mcp


def _tool_names() -> set[str]:
    tools = asyncio.run(mcp.list_tools())
    return {t.name for t in tools}


def test_all_expected_tools_registered() -> None:
    expected = {
        "upload_from_url",
        "list_videos",
        "get_video",
        "delete_video",
        "whoami",
    }
    assert expected.issubset(_tool_names())


def test_no_unexpected_extra_tools() -> None:
    allowed = {
        "upload_from_url",
        "list_videos",
        "get_video",
        "delete_video",
        "whoami",
    }
    extras = _tool_names() - allowed
    assert not extras, f"Unexpected tools registered: {extras}"
