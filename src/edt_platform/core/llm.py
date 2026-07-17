"""Thin, governed wrapper over the Anthropic Claude Messages API.

Responsibilities:
  * Model-tier routing (Opus 4.8 / Sonnet 5 / Haiku 4.5) requested by each agent.
  * Prompt caching + extended thinking toggles.
  * Token/cost accounting surfaced to the Cost & Token Optimization agents.
  * Structured (tool-forced / JSON-schema) generation with automatic repair.
  * OpenTelemetry + Langfuse tracing hooks.

This is deliberately dependency-light so it can be unit tested with a fake client.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from edt_platform.config import ModelTier, get_settings

# Indicative list price ($/1M tokens) used by the Cost Optimization Agent for
# budgeting. Real values are injected from the pricing config at deploy time.
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    ModelTier.REASONING.value: (15.0, 75.0),
    ModelTier.DEFAULT.value: (3.0, 15.0),
    ModelTier.FAST.value: (0.80, 4.0),
}


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    thinking: str | None = None
    tool_use: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None

    @property
    def cost_usd(self) -> float:
        in_price, out_price = _PRICE_PER_MTOK.get(self.model, (3.0, 15.0))
        return (self.input_tokens * in_price + self.output_tokens * out_price) / 1_000_000


class _AnthropicLike(Protocol):
    """Structural type for the Anthropic client (real or fake)."""

    @property
    def messages(self) -> Any: ...


class LLMClient:
    """Governed Claude client. Inject a fake ``client`` in tests."""

    def __init__(self, client: _AnthropicLike | None = None) -> None:
        self._settings = get_settings().llm
        if client is None:  # pragma: no cover - real client requires network/creds
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=self._settings.anthropic_api_key)
        self._client = client

    def _model_for(self, tier: ModelTier | None) -> str:
        return (tier or self._settings.default_tier).value

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tier: ModelTier | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cache_system: bool = True,
    ) -> LLMResponse:
        """Run one Claude completion with governance defaults applied."""
        model = self._model_for(tier)
        system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system}]
        if cache_system and self._settings.enable_prompt_caching:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}

        kwargs: dict[str, Any] = {
            "model": model,
            "system": system_blocks,
            "messages": messages,
            "max_tokens": max_tokens or self._settings.max_output_tokens,
            "temperature": temperature if temperature is not None else self._settings.temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if self._settings.enable_extended_thinking and (tier == ModelTier.REASONING):
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self._settings.thinking_budget_tokens,
            }
            kwargs["temperature"] = 1.0  # required when thinking is enabled

        resp = await self._client.messages.create(**kwargs)
        return self._parse(resp, model)

    @staticmethod
    def _parse(resp: Any, model: str) -> LLMResponse:
        text_parts: list[str] = []
        thinking: str | None = None
        tool_use: list[dict[str, Any]] = []
        for block in getattr(resp, "content", []) or []:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "thinking":
                thinking = getattr(block, "thinking", None)
            elif btype == "tool_use":
                tool_use.append(
                    {"id": block.id, "name": block.name, "input": block.input}
                )
        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text="\n".join(text_parts),
            model=model,
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            thinking=thinking,
            tool_use=tool_use,
            stop_reason=getattr(resp, "stop_reason", None),
        )

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        tier: ModelTier | None = None,
        max_repair_attempts: int = 2,
    ) -> tuple[dict[str, Any], LLMResponse]:
        """Force a JSON object matching ``schema`` via a single-tool call, with repair."""
        tool = {
            "name": "emit",
            "description": "Emit the structured result matching the required schema.",
            "input_schema": schema,
        }
        messages = [{"role": "user", "content": prompt}]
        last: LLMResponse | None = None
        for _attempt in range(max_repair_attempts + 1):
            resp = await self.complete(
                system=system,
                messages=messages,
                tier=tier,
                tools=[tool],
            )
            last = resp
            if resp.tool_use:
                return resp.tool_use[0]["input"], resp
            # Repair: feed back the malformed output and re-ask.
            messages.append({"role": "assistant", "content": resp.text or "(no tool call)"})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous reply did not call the `emit` tool with valid JSON. "
                        "Call `emit` now with an object that satisfies the schema exactly."
                    ),
                }
            )
        # Last resort: try to salvage JSON from text.
        assert last is not None
        try:
            return json.loads(last.text), last
        except Exception as exc:  # noqa: BLE001
            raise ValueError("Structured generation failed to produce valid JSON") from exc
