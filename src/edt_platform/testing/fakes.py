"""Reusable fakes so the platform runs offline (no Anthropic key, no network).

`FakeAnthropicClient` mimics ``anthropic.AsyncAnthropic``'s ``messages.create`` and
returns schema-conformant, human-readable content. It powers both the CLI demo
(`scripts/demo.py`) and the dashboard's demo mode (`api/app.py`), so anyone can see
the full lifecycle execute without credentials.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

# Readable defaults for common field names across the platform's schemas, so the
# offline output reads like a (placeholder) report instead of "sample sample".
_NICE_STRINGS: dict[str, str] = {
    "reframed_problem": "Reframed: the real problem is trust and relevance, not features",
    "statement": "Users need a reason to stay that feels made for them",
    "rationale": "Grounded in the supplied evidence; key assumptions were flagged",
    "name": "Alex Chen",
    "archetype": "Digital-first newcomer",
    "quote": "“I want my money to just make sense.”",
    "title": "Personalized money coach",
    "description": "A concept that meets the user where they already are",
    "what": "Retain and grow a hard-to-reach customer segment",
    "why_now": "Competitive and behavioral shifts make this urgent",
    "decision": "conditional_go",
    "i_want_to": "feel in control of my money without effort",
    "so_i_can": "build a habit that compounds",
    "as_a": "first-time Gen-Z saver",
    "i_want": "guidance that fits my life",
    "so_that": "saving stops feeling like a chore",
}


def _fake_value(schema: dict[str, Any], key: str | None = None) -> Any:
    t = schema.get("type")
    if t == "object":
        out: dict[str, Any] = {}
        props = schema.get("properties", {})
        for k, sub in props.items():
            out[k] = _fake_value(sub, k)
        for k in schema.get("required", []):
            out.setdefault(k, _fake_value(props.get(k, {"type": "string"}), k))
        return out
    if t == "array":
        item = schema.get("items", {"type": "string"})
        return [_fake_value(item, key), _fake_value(item, key)]
    if t == "number":
        return 0.83 if (key and ("score" in key or "confidence" in key)) else 0.8
    if t == "integer":
        return 3
    if t == "boolean":
        return True
    if key and key in _NICE_STRINGS:
        return _NICE_STRINGS[key]
    if key:
        return f"{key.replace('_', ' ')} (demo)"
    return "demo value"


class _FakeMessages:
    async def create(self, **kwargs: Any) -> SimpleNamespace:
        tools = kwargs.get("tools")
        if tools:
            payload = _fake_value(tools[0]["input_schema"])
            content = [SimpleNamespace(type="tool_use", id="t1", name=tools[0]["name"], input=payload)]
        else:
            content = [SimpleNamespace(type="text", text="VERDICT: APPROVE\nSCORE: 0.86")]
        usage = SimpleNamespace(input_tokens=1400, output_tokens=650)
        return SimpleNamespace(content=content, usage=usage, stop_reason="end_turn")


class FakeAnthropicClient:
    """Drop-in stand-in for ``anthropic.AsyncAnthropic`` used in offline/demo mode."""

    def __init__(self) -> None:
        self.messages = _FakeMessages()
