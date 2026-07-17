"""Watchable end-to-end demo of the EDT Platform.

Runs the full Design Thinking lifecycle for a business problem and pretty-prints
every artifact — grouped by phase, with producing agent, confidence, and a content
preview — plus the event log and a cost summary.

Two modes:
  * OFFLINE (default): uses a built-in fake Claude client that returns
    schema-conformant, readable output. No API key, no infrastructure required —
    you watch the orchestration, agents, gates, and loops execute.
  * LIVE (`--live`): uses the real Anthropic API (needs EDT_LLM_ANTHROPIC_API_KEY)
    so agents produce genuine content.

Usage:
    python scripts/demo.py                      # offline, standard depth
    python scripts/demo.py --depth deep
    python scripts/demo.py --live               # real Claude calls
    python scripts/demo.py "Your own business problem here"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from types import SimpleNamespace
from typing import Any

# Make `src/` importable when run directly (python scripts/demo.py).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Quiet the per-span debug logs so the demo output stays readable.
import logging  # noqa: E402

import structlog  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))

from edt_platform.agents.crosscutting.critic import CriticAgent  # noqa: E402
from edt_platform.agents.registry import build_registry  # noqa: E402
from edt_platform.core.base_agent import AgentContext  # noqa: E402
from edt_platform.core.llm import LLMClient  # noqa: E402
from edt_platform.eventing.publisher import EventPublisher  # noqa: E402
from edt_platform.memory.memory_agent import MemoryAgent  # noqa: E402
from edt_platform.orchestration.supervisor import RunState, Supervisor  # noqa: E402
from edt_platform.schemas.core import Phase  # noqa: E402
from edt_platform.security.guardrails import GuardrailEngine  # noqa: E402

# --------------------------------------------------------------------------- #
# ANSI colors (disabled if not a TTY)
# --------------------------------------------------------------------------- #
_TTY = sys.stdout.isatty()


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


BOLD, DIM, CYAN, GREEN, YELLOW, MAGENTA, BLUE = "1", "2", "36", "32", "33", "35", "34"

PHASE_COLOR = {
    Phase.DISCOVER: BLUE,
    Phase.DEFINE: MAGENTA,
    Phase.IDEATE: YELLOW,
    Phase.PROTOTYPE: CYAN,
    Phase.VALIDATE: GREEN,
}

# --------------------------------------------------------------------------- #
# Offline fake Claude client — returns readable, schema-conformant output
# --------------------------------------------------------------------------- #
_NICE_STRINGS = {
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
    # string
    if key and key in _NICE_STRINGS:
        return _NICE_STRINGS[key]
    if key:
        return f"{key.replace('_', ' ')} (demo)"
    return "demo value"


class _FakeMessages:
    async def create(self, **kwargs: Any):
        tools = kwargs.get("tools")
        if tools:
            payload = _fake_value(tools[0]["input_schema"])
            content = [SimpleNamespace(type="tool_use", id="t1", name=tools[0]["name"], input=payload)]
        else:
            content = [SimpleNamespace(type="text", text="VERDICT: APPROVE\nSCORE: 0.86")]
        usage = SimpleNamespace(input_tokens=1400, output_tokens=650)
        return SimpleNamespace(content=content, usage=usage, stop_reason="end_turn")


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


# --------------------------------------------------------------------------- #
# Pretty printing
# --------------------------------------------------------------------------- #
def _rule(char: str = "─", width: int = 78) -> str:
    return char * width


def _preview(content: dict[str, Any], limit: int = 240) -> str:
    text = json.dumps(content, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + " …"


def print_run(state: RunState, events: EventPublisher, live: bool) -> None:
    print()
    print(c(_rule("═"), BOLD))
    mode = c("LIVE (real Claude)", GREEN) if live else c("OFFLINE (fake LLM)", YELLOW)
    print(c("  EDT PLATFORM — DESIGN THINKING RUN", BOLD) + f"   [{mode}]")
    print(c(_rule("═"), BOLD))
    print(f"  {c('Problem:', DIM)} {state.problem}")
    print(f"  {c('Run id :', DIM)} {state.run_id}")
    print(f"  {c('Status :', DIM)} {c(state.status.value, GREEN)}   "
          f"{c('Artifacts:', DIM)} {len(state.artifacts)}   "
          f"{c('Loops:', DIM)} {state.loop_count}")
    print()

    for phase in Phase:
        arts = [a for a in state.artifacts if a.phase == phase]
        if not arts:
            continue
        col = PHASE_COLOR[phase]
        print(c(f"▓▓ {phase.value.upper()}  ({len(arts)} artifacts)", col + ";1"))
        print(c(_rule(), col))
        for a in arts:
            conf = a.confidence.score
            conf_col = GREEN if conf >= 0.72 else (YELLOW if conf >= 0.5 else "31")
            print(f"  {c('▸', col)} {c('[' + a.type.value + ']', col)} {c(a.title, BOLD)}")
            print(f"      {c('agent:', DIM)} {a.provenance.producer_agent}"
                  f"    {c('conf:', DIM)} {c(f'{conf:.2f}', conf_col)}"
                  f"    {c('model:', DIM)} {a.provenance.model}")
            print(f"      {c('content:', DIM)} {c(_preview(a.content), DIM)}")
        print()

    # Event log + cost
    print(c("▓▓ EVENT LOG  (CloudEvents)", BOLD))
    print(c(_rule(), DIM))
    for e in events.buffer:
        print(f"  {c(e.type, DIM)}")
    print()
    if state.log:
        print(c("▓▓ SUPERVISOR NOTES", BOLD))
        print(c(_rule(), DIM))
        for line in state.log:
            print(f"  {c('•', YELLOW)} {line}")
        print()
    print(c(_rule("═"), BOLD))
    print(f"  {c('Events emitted:', DIM)} {len(events.buffer)}    "
          f"{c('Est. cost (fake tokens):', DIM)} ${state.cost_usd:.4f}")
    print(c(_rule("═"), BOLD))
    print()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
DEFAULT_PROBLEM = (
    "A regional retail bank is losing Gen-Z customers; reduce churn and grow deposits."
)


async def run_demo(problem: str, depth: str, live: bool) -> int:
    if live:
        if not os.environ.get("EDT_LLM_ANTHROPIC_API_KEY"):
            print(c("--live requires EDT_LLM_ANTHROPIC_API_KEY to be set.", "31"))
            return 2
        llm = LLMClient()  # real Anthropic client
    else:
        llm = LLMClient(client=_FakeClient())

    events = EventPublisher()
    ctx = AgentContext(
        llm=llm,
        memory=MemoryAgent(),
        events=events,
        critic=CriticAgent(llm),
        guardrails=GuardrailEngine(),
    )
    supervisor = Supervisor(ctx, build_registry())
    print(c(f"\nRunning lifecycle (depth={depth})… fan-out across all five phases.\n", DIM))
    state = await supervisor.run(problem=problem, depth=depth, require_approval=False)
    print_run(state, events, live)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="EDT Platform watchable demo")
    p.add_argument("problem", nargs="?", default=DEFAULT_PROBLEM, help="business problem")
    p.add_argument("--depth", default="standard", choices=["lite", "standard", "deep"])
    p.add_argument("--live", action="store_true", help="use the real Anthropic API")
    args = p.parse_args()
    return asyncio.run(run_demo(args.problem, args.depth, args.live))


if __name__ == "__main__":
    raise SystemExit(main())
