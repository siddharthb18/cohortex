"""In-process pub/sub that feeds live SSE streams. Stored steps are replayed from Postgres."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

Event = dict[str, Any]  # {"event": "step" | "report" | "error", "data": {...}}


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[Event]]] = defaultdict(set)

    def subscribe(self, investigation_id: str) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers[investigation_id].add(queue)
        return queue

    def unsubscribe(self, investigation_id: str, queue: asyncio.Queue[Event]) -> None:
        subscribers = self._subscribers.get(investigation_id)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                del self._subscribers[investigation_id]

    def publish(self, investigation_id: str, event: Event) -> None:
        for queue in list(self._subscribers.get(investigation_id, ())):
            queue.put_nowait(event)
