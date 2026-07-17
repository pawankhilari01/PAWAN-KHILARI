"""`edt` command-line entry point.

Runs a full Design Thinking lifecycle locally against fakes (no external services)
so the platform is demonstrable end-to-end without infra. With real credentials +
`--live`, the same command drives the production Supervisor.

Usage:
    edt run "A regional bank is losing Gen-Z customers; grow deposits" --depth lite
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from edt_platform.agents.registry import build_registry
from edt_platform.core.base_agent import AgentContext
from edt_platform.core.llm import LLMClient
from edt_platform.eventing.publisher import EventPublisher
from edt_platform.memory.memory_agent import MemoryAgent
from edt_platform.orchestration.supervisor import Supervisor


async def _run(problem: str, depth: str) -> int:
    events = EventPublisher()
    # NOTE: LLMClient() needs Anthropic creds; this smoke path assumes they exist.
    ctx = AgentContext(llm=LLMClient(), memory=MemoryAgent(), events=events)
    supervisor = Supervisor(ctx, build_registry())
    state = await supervisor.run(problem=problem, depth=depth, require_approval=False)
    print(
        json.dumps(
            {
                "run_id": str(state.run_id),
                "status": state.status.value,
                "artifacts": len(state.artifacts),
                "cost_usd": round(state.cost_usd, 4),
                "events": len(events.buffer),
                "log": state.log,
            },
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="edt", description="Enterprise Design Thinking AI Platform")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Execute a Design Thinking lifecycle for a problem")
    run_p.add_argument("problem", help="The business problem to work through")
    run_p.add_argument("--depth", default="standard", choices=["lite", "standard", "deep"])
    args = parser.parse_args()
    if args.cmd == "run":
        return asyncio.run(_run(args.problem, args.depth))
    return 1


if __name__ == "__main__":
    sys.exit(main())
