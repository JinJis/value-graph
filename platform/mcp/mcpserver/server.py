"""MCP server (stdio) exposing the platform's data connectors as tools.

Tools are generated from the data-plane catalog at ``tools/list`` time and
executed through the control-plane gateway with the configured tenant key.
Calling an unactivated connector returns the gateway's 403 in the tool result
(honest, not hidden).
"""

from __future__ import annotations

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mcpserver.tools import build_tools, call_tool, fetch_catalog, tool_index

server = Server("valuegraph-data")
_TOOLS: dict[str, dict] = {}


@server.list_tools()
async def list_tools() -> list[Tool]:
    global _TOOLS
    tools = build_tools(await fetch_catalog())
    _TOOLS = tool_index(tools)
    return [Tool(name=t["name"], description=t["description"], inputSchema=t["inputSchema"]) for t in tools]


@server.call_tool()
async def call(name: str, arguments: dict | None) -> list[TextContent]:
    if name not in _TOOLS:  # client may call before list; refresh once
        _TOOLS.update(tool_index(build_tools(await fetch_catalog())))
    tool = _TOOLS.get(name)
    if tool is None:
        return [TextContent(type="text", text=json.dumps({"error": f"unknown tool '{name}'"}))]
    result = await call_tool(tool, arguments or {})
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


async def _main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def run() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    run()
