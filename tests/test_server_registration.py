"""Verify the MCP server registers all expected tools."""

from __future__ import annotations

import asyncio

from gdrive_video_mcp.server import mcp


def _tool_names() -> set[str]:
    tools = asyncio.run(mcp.list_tools())
    return {t.name for t in tools}


EXPECTED_TOOLS = {
    "upload_from_url",
    "upload_video",
    "create_upload_link",
    "list_videos",
    "get_video",
    "delete_video",
    "whoami",
}


def test_all_expected_tools_registered() -> None:
    assert EXPECTED_TOOLS.issubset(_tool_names())


def test_no_unexpected_extra_tools() -> None:
    extras = _tool_names() - EXPECTED_TOOLS
    assert not extras, f"Unexpected tools registered: {extras}"
