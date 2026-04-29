"""End-to-end MCP protocol test.

Spawns ``python -m pace.mcp_server`` as a real subprocess, drives it
through the official MCP client, and checks that:

1. All 7 tools register with non-empty descriptions (so the model has
   guidance on when to invoke them).
2. ``pace_status`` round-trips through JSON-RPC and reflects vault state.
3. A capture → search round-trip works through the wire.

The unit tests in ``test_mcp_tools.py`` exercise tool *logic* without
the protocol; this file exercises the *wiring* end-to-end.

Run-time cost: spinning up a subprocess per test is a few seconds, so
we keep the test count small.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# Tools the server is required to expose, per PRD §6.8. Maintenance
# tools (compact/review/archive/reindex/doctor) are intentionally NOT in
# this list — they must not appear over MCP.
EXPECTED_TOOLS = {
    "pace_status",
    "pace_capture",
    "pace_search",
    "pace_load_project",
    "pace_list_projects",
    "pace_create_project",
    "pace_init",
}

FORBIDDEN_TOOLS = {"pace_compact", "pace_review", "pace_archive", "pace_reindex", "pace_doctor"}


def _server_params(vault_root: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "pace.mcp_server"],
        env={**os.environ, "PACE_ROOT": str(vault_root)},
    )


def _result_text(result) -> str:
    """Concatenate text content from a CallToolResult into one string."""
    parts: list[str] = []
    for content in result.content:
        text = getattr(content, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _result_json(result) -> dict:
    """Pull the structured payload out of a CallToolResult.

    FastMCP returns tool output as text content (a JSON-encoded blob) and,
    for typed returns, also as a structured ``structuredContent`` dict.
    Prefer structured if present; fall back to parsing the text.
    """
    if getattr(result, "structuredContent", None):
        return dict(result.structuredContent)
    return json.loads(_result_text(result))


# ---- Tests -------------------------------------------------------------


def test_tools_list_matches_prd_surface(tmp_path: Path) -> None:
    asyncio.run(_check_tools_list(tmp_path))


def test_status_round_trip(tmp_path: Path) -> None:
    asyncio.run(_check_status_round_trip(tmp_path))


def test_capture_then_search_over_protocol(tmp_path: Path) -> None:
    asyncio.run(_check_capture_search_round_trip(tmp_path))


# ---- Async bodies ------------------------------------------------------


async def _check_tools_list(tmp_path: Path) -> None:
    # Vault doesn't need to be initialized — list_tools is metadata-only.
    async with stdio_client(_server_params(tmp_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()

    names = {t.name for t in listed.tools}
    assert EXPECTED_TOOLS <= names, (
        f"Missing tools: {EXPECTED_TOOLS - names}"
    )
    assert names.isdisjoint(FORBIDDEN_TOOLS), (
        f"Maintenance tools must NOT be exposed: {names & FORBIDDEN_TOOLS}"
    )

    # Every exposed tool must carry a non-trivial description — the model
    # uses these to choose when to call. Empty descriptions are a bug.
    for tool in listed.tools:
        if tool.name in EXPECTED_TOOLS:
            assert tool.description, f"{tool.name} has no description"
            assert len(tool.description) > 50, (
                f"{tool.name} description is suspiciously short: "
                f"{tool.description!r}"
            )


async def _check_status_round_trip(tmp_path: Path) -> None:
    # Initialize vault on the client side first so status returns true.
    from pace import vault as vault_ops

    vault_ops.init(tmp_path)

    async with stdio_client(_server_params(tmp_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("pace_status", {})

    payload = _result_json(result)
    assert payload["initialized"] is True
    assert payload["root"] == str(tmp_path.resolve())
    assert payload["files"].get("working") == 1


async def _check_capture_search_round_trip(tmp_path: Path) -> None:
    from pace import vault as vault_ops

    vault_ops.init(tmp_path)

    async with stdio_client(_server_params(tmp_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            cap = await session.call_tool(
                "pace_capture",
                {
                    "kind": "working",
                    "content": "Cowork-launched MCP test fact about widget 42.",
                    "tags": ["test"],
                },
            )
            cap_payload = _result_json(cap)
            assert cap_payload["path"] == "memories/working_memory.md"

            search = await session.call_tool(
                "pace_search", {"query": "widget 42"}
            )
            search_payload = _result_json(search)
            assert len(search_payload["hits"]) == 1
            assert "widget" in search_payload["hits"][0]["snippet"].lower()


# ---- Skip on platforms where the subprocess transport is flaky --------

if sys.platform == "win32":
    # The mcp client on Windows occasionally fails to clean up subprocess
    # transports inside a non-default event loop policy. Force the proactor
    # policy explicitly per test to keep behavior deterministic.
    @pytest.fixture(autouse=True)
    def _proactor_loop_policy() -> None:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
