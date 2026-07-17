"""Tool Registry + Tool Selection (see docs/08-tool-architecture.md).

Tools are the platform's actuators. Each tool has a typed contract, a permission
scope, and either a native Python implementation or a binding to an MCP server tool.
The Tool Selection Agent chooses the minimal necessary tools for a task; the registry
enforces permissions, timeouts, retries, and circuit-breaking.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    scopes: list[str] = field(default_factory=list)     # RBAC scopes required
    mcp_server: str | None = None                        # None => native
    timeout_s: float = 30.0
    max_retries: int = 2
    cost_hint: str = "low"                               # low|medium|high (for selection)


ToolFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class CircuitOpen(RuntimeError):
    """Raised when a tool's circuit breaker is open."""


@dataclass
class _Breaker:
    failures: int = 0
    threshold: int = 5
    open_until: float = 0.0


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._impls: dict[str, ToolFn] = {}
        self._breakers: dict[str, _Breaker] = {}

    def register(self, spec: ToolSpec, impl: ToolFn) -> None:
        self._specs[spec.name] = spec
        self._impls[spec.name] = impl
        self._breakers[spec.name] = _Breaker()

    def catalog(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def select(self, task: str, granted_scopes: set[str], budget: str = "medium") -> list[ToolSpec]:
        """Heuristic tool pre-selection; the Tool Selection Agent refines via LLM.

        Filters by permission scope and cost budget so agents only see tools they
        may use — the actual pick is delegated to the LLM with these candidates.
        """
        order = {"low": 0, "medium": 1, "high": 2}
        cap = order.get(budget, 1)
        return [
            s
            for s in self._specs.values()
            if set(s.scopes).issubset(granted_scopes) and order[s.cost_hint] <= cap
        ]

    async def call(self, name: str, args: dict[str, Any], granted_scopes: set[str]) -> dict[str, Any]:
        spec = self._specs[name]
        if not set(spec.scopes).issubset(granted_scopes):
            raise PermissionError(f"Tool '{name}' requires scopes {spec.scopes}")
        breaker = self._breakers[name]
        loop = asyncio.get_event_loop()
        if breaker.open_until > loop.time():
            raise CircuitOpen(f"Tool '{name}' circuit is open")

        @retry(
            stop=stop_after_attempt(spec.max_retries + 1),
            wait=wait_exponential(multiplier=0.5, max=8),
            reraise=True,
        )
        async def _invoke() -> dict[str, Any]:
            return await asyncio.wait_for(self._impls[name](args), timeout=spec.timeout_s)

        try:
            out = await _invoke()
            breaker.failures = 0
            return out
        except Exception:
            breaker.failures += 1
            if breaker.failures >= breaker.threshold:
                breaker.open_until = loop.time() + 30.0
            raise
