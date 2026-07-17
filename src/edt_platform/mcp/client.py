"""MCP (Model Context Protocol) client router (see docs/07-mcp-architecture.md).

Agents never talk to external systems directly — they call MCP tools. This router
maintains sessions to the platform's MCP servers (market-research, patent, web,
artifact/filesystem, figma, github, jira/confluence, sql, knowledge-graph,
vector-search) and adapts MCP tools into the internal ToolRegistry so tool calling,
permissions, and tracing are uniform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from edt_platform.tools.registry import ToolFn, ToolRegistry, ToolSpec


@dataclass
class MCPServerConfig:
    name: str
    transport: str            # "stdio" | "streamable-http"
    endpoint: str             # command (stdio) or URL (http)
    auth: str | None = None   # "oauth" | "vault:<path>" | None
    scopes: list[str] = field(default_factory=list)


class MCPRouter:
    """Manages MCP sessions and exposes their tools to the ToolRegistry.

    The reference implementation records configured servers and provides an
    ``adapt`` hook that turns a discovered MCP tool into a native ToolRegistry
    entry. Production replaces ``_open_session`` with the official ``mcp`` SDK.
    """

    def __init__(self, servers: list[MCPServerConfig]) -> None:
        self._servers: dict[str, MCPServerConfig] = {s.name: s for s in servers}
        self._sessions: dict[str, Any] = {}

    @property
    def servers(self) -> list[MCPServerConfig]:
        return list(self._servers.values())

    async def _open_session(self, cfg: MCPServerConfig) -> Any:  # pragma: no cover
        """Open an MCP session using the official SDK (stdio or streamable-HTTP)."""

        raise NotImplementedError(
            "Wire mcp.ClientSession here; see docs/07-mcp-architecture.md for transports."
        )

    async def register_into(self, registry: ToolRegistry) -> None:
        """Discover tools from each MCP server and register them natively."""
        for cfg in self._servers.values():
            for tool in await self.list_tools(cfg.name):
                spec = ToolSpec(
                    name=f"{cfg.name}.{tool['name']}",
                    description=tool.get("description", ""),
                    input_schema=tool.get("input_schema", {"type": "object"}),
                    scopes=cfg.scopes,
                    mcp_server=cfg.name,
                    cost_hint=tool.get("cost_hint", "medium"),
                )
                registry.register(spec, self._bind(cfg.name, tool["name"]))

    async def list_tools(self, server: str) -> list[dict[str, Any]]:
        """Return the tool descriptors exposed by a server (fake: empty)."""
        return []

    def _bind(self, server: str, tool: str) -> ToolFn:
        async def _call(args: dict[str, Any]) -> dict[str, Any]:
            return await self.call_tool(server, tool, args)

        return _call

    async def call_tool(self, server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Invoke a tool on an MCP server (fake echoes the request)."""
        return {"server": server, "tool": tool, "args": args, "result": None}
