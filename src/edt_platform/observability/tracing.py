"""OpenTelemetry-based tracing helpers.

A single ``@traced`` decorator wraps agent/tool/phase calls in OTel spans and
mirrors them to Langfuse for LLM-specific evaluation. The decorator is a no-op if
tracing is not configured, so unit tests need no collector.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger("edt.trace")

_T = TypeVar("_T")

try:  # pragma: no cover - optional at test time
    from opentelemetry import trace

    _tracer = trace.get_tracer("edt-platform")
except Exception:  # noqa: BLE001
    _tracer = None


def traced(span_name: str) -> Callable[[Callable[..., Awaitable[_T]]], Callable[..., Awaitable[_T]]]:
    """Decorate an async method/function to emit an OTel span + structured log."""

    def decorator(fn: Callable[..., Awaitable[_T]]) -> Callable[..., Awaitable[_T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> _T:
            start = time.perf_counter()
            if _tracer is None:
                result = await fn(*args, **kwargs)
                logger.debug("span", name=span_name, ms=round((time.perf_counter() - start) * 1000, 1))
                return result
            with _tracer.start_as_current_span(span_name) as span:
                try:
                    result = await fn(*args, **kwargs)
                    span.set_attribute("edt.ok", True)
                    return result
                except Exception as exc:  # noqa: BLE001
                    span.set_attribute("edt.ok", False)
                    span.record_exception(exc)
                    raise
                finally:
                    span.set_attribute("edt.duration_ms", (time.perf_counter() - start) * 1000)

        return wrapper

    return decorator
