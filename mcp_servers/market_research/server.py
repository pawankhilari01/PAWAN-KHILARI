"""Reference MCP server: market-research tools.

A minimal, real Model Context Protocol server exposing market-sizing and competitor
lookup tools that Discover-phase agents call via the MCPRouter. Demonstrates the
contract; production wires real data providers (Statista, Crunchbase, CB Insights)
behind these tool names, with auth brokered by Vault.

Run (stdio):  python mcp_servers/market_research/server.py
Register in:  src/edt_platform/mcp/client.py  ->  MCPServerConfig(name="market-research", ...)
"""

from __future__ import annotations

import asyncio
from typing import Any

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool
except Exception as exc:  # pragma: no cover
    raise SystemExit("Install the MCP SDK: pip install mcp") from exc

server: Server = Server("edt-market-research")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="size_market",
            description="Estimate TAM/SAM/SOM for a market segment with cited sources.",
            inputSchema={
                "type": "object",
                "required": ["segment", "geography"],
                "properties": {
                    "segment": {"type": "string"},
                    "geography": {"type": "string"},
                    "year": {"type": "integer"},
                },
            },
        ),
        Tool(
            name="find_competitors",
            description="Return known competitors for a product category with positioning notes.",
            inputSchema={
                "type": "object",
                "required": ["category"],
                "properties": {
                    "category": {"type": "string"},
                    "region": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    # Reference stub responses. Replace with real provider calls + citations.
    if name == "size_market":
        result = {
            "segment": arguments.get("segment"),
            "geography": arguments.get("geography"),
            "tam_usd": None,
            "sam_usd": None,
            "som_usd": None,
            "note": "Wire a data provider here; always return citations for provenance.",
            "citations": [],
        }
    elif name == "find_competitors":
        result = {"category": arguments.get("category"), "competitors": [], "citations": []}
    else:
        result = {"error": f"unknown tool {name}"}
    return [TextContent(type="text", text=str(result))]


async def main() -> None:  # pragma: no cover
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
