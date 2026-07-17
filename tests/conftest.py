"""Shared test fixtures — a fake Anthropic client so the platform runs offline."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from edt_platform.core.llm import LLMClient


class _FakeMessages:
    """Mimics Anthropic's ``client.messages.create`` for structured + text calls."""

    async def create(self, **kwargs: Any):
        tools = kwargs.get("tools")
        if tools:
            # Return a tool_use block satisfying the emit schema minimally.
            schema = tools[0]["input_schema"]
            payload = _minimal_instance(schema)
            content = [SimpleNamespace(type="tool_use", id="t1", name=tools[0]["name"], input=payload)]
        else:
            content = [SimpleNamespace(type="text", text="VERDICT: APPROVE\nSCORE: 0.9")]
        usage = SimpleNamespace(input_tokens=120, output_tokens=80)
        return SimpleNamespace(content=content, usage=usage, stop_reason="end_turn")


def _minimal_instance(schema: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal object satisfying a (shallow) JSON schema for tests."""
    if schema.get("type") == "object":
        out: dict[str, Any] = {}
        for key, sub in schema.get("properties", {}).items():
            out[key] = _minimal_instance(sub)
        # ensure required keys exist
        for key in schema.get("required", []):
            out.setdefault(key, _minimal_instance(schema["properties"].get(key, {"type": "string"})))
        return out
    if schema.get("type") == "array":
        return [_minimal_instance(schema.get("items", {"type": "string"}))]
    if schema.get("type") == "number":
        return 0.85
    if schema.get("type") == "integer":
        return 3
    if schema.get("type") == "boolean":
        return True
    return "sample"


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


@pytest.fixture
def fake_llm() -> LLMClient:
    return LLMClient(client=_FakeClient())


@pytest.fixture
def sample_problem() -> str:
    return "A regional retail bank is losing Gen-Z customers; reduce churn and grow deposits."
