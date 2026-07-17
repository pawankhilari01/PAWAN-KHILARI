"""CloudEvents publisher over Kafka (see docs/14-event-model.md).

Every meaningful state change is a CloudEvent published to a partitioned Kafka
topic keyed by ``run_id`` (ordering per run). Consumers include the Supervisor,
Observability, Cost, Compliance, and the Web console's live progress stream.
The reference implementation buffers in memory for local/testing use.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from edt_platform.config import get_settings


@dataclass
class CloudEvent:
    type: str
    source: str
    subject: str
    data: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid4()))
    specversion: str = "1.0"
    datacontenttype: str = "application/json"

    def to_json(self) -> str:
        return json.dumps(self.__dict__)


class EventPublisher:
    def __init__(self, producer: Any | None = None) -> None:
        self._producer = producer                    # aiokafka producer or None
        self._prefix = get_settings().event.topic_prefix
        self.buffer: list[CloudEvent] = []           # test/local sink
        # Live in-process subscribers (e.g. the dashboard SSE stream). Each is a
        # callable receiving the CloudEvent as it is published.
        self._subscribers: list[Callable[[CloudEvent], None]] = []

    def subscribe(self, callback: Callable[[CloudEvent], None]) -> Callable[[], None]:
        """Register a live subscriber; returns an unsubscribe function."""
        self._subscribers.append(callback)

        def _unsub() -> None:
            with suppress(ValueError):
                self._subscribers.remove(callback)

        return _unsub

    def _topic_for(self, event_type: str) -> str:
        # edt.discover.persona.created -> edt.discover
        parts = event_type.split(".")
        return ".".join(parts[:2]) if len(parts) >= 2 else self._prefix

    async def publish(self, event_type: str, subject: str, data: dict[str, Any]) -> CloudEvent:
        evt = CloudEvent(
            type=event_type,
            source=f"//edt-platform/{get_settings().obs.service_name}",
            subject=subject,
            data=data,
        )
        if self._producer:  # pragma: no cover - requires Kafka
            await self._producer.send_and_wait(
                self._topic_for(event_type),
                key=subject.encode(),
                value=evt.to_json().encode(),
            )
        else:
            self.buffer.append(evt)
        for cb in list(self._subscribers):
            with suppress(Exception):
                cb(evt)
        return evt
