"""Guardrail engine (input/output) — enterprise security + Responsible AI.

Applied by BaseAgent around every agent invocation:
  * Input: prompt-injection heuristics, PII detection/redaction (Presidio), policy/
    jailbreak screening (Llama-Guard-style classifier), scope/authorization checks.
  * Output: schema conformance, PII leak checks, toxicity/safety, hallucination
    flags (unsupported claims without citations), and refusal on policy violations.

The reference implementation ships light heuristics; production plugs in Presidio,
a safety classifier, and NeMo-Guardrails-style policies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from edt_platform.schemas.core import AgentInput, Artifact

_INJECTION_PATTERNS = [
    r"ignore (all|previous) instructions",
    r"disregard the (system|above)",
    r"reveal your (system )?prompt",
    r"you are now",
]
_PII_PATTERNS = {
    "email": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b(?:\d[ -]*?){13,16}\b",
}


class GuardrailViolation(Exception):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


@dataclass
class GuardrailReport:
    ok: bool = True
    findings: list[str] = field(default_factory=list)


class GuardrailEngine:
    def __init__(self, redact_pii: bool = True, block_injection: bool = True) -> None:
        self.redact_pii = redact_pii
        self.block_injection = block_injection

    async def check_input(self, agent: str, task: AgentInput) -> GuardrailReport:
        report = GuardrailReport()
        text = task.task.lower()
        if self.block_injection:
            for pat in _INJECTION_PATTERNS:
                if re.search(pat, text):
                    raise GuardrailViolation("prompt_injection", f"matched /{pat}/ for {agent}")
        for label, pat in _PII_PATTERNS.items():
            if re.search(pat, task.task):
                report.findings.append(f"input_pii:{label}")
        return report

    async def check_output(self, agent: str, artifact: Artifact) -> GuardrailReport:
        report = GuardrailReport()
        blob = str(artifact.content)
        for label, pat in _PII_PATTERNS.items():
            if re.search(pat, blob):
                report.findings.append(f"output_pii:{label}")
        # Responsible-AI: high-stakes claims should be cited.
        if artifact.confidence.score < 0.4 and not artifact.provenance.citations:
            report.findings.append("low_confidence_uncited")
        report.ok = True
        return report

    @staticmethod
    def redact(text: str) -> str:
        for label, pat in _PII_PATTERNS.items():
            text = re.sub(pat, f"[REDACTED:{label}]", text)
        return text
