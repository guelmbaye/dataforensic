"""In-process pub/sub used to stream investigation events over SSE.

Events are persisted (investigation_events table) *and* published on the bus.
An SSE client subscribes first, then replays persisted events, then dedupes by
sequence number - so no event can be lost between replay and subscription.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

QUEUE_MAX_SIZE = 500


class InvestigationEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, investigation_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
        async with self._lock:
            self._subscribers[investigation_id].add(queue)
        return queue

    async def unsubscribe(self, investigation_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers[investigation_id].discard(queue)
            if not self._subscribers[investigation_id]:
                self._subscribers.pop(investigation_id, None)

    async def publish(self, investigation_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(investigation_id, ()))
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - slow consumer protection
                pass

    def subscriber_count(self, investigation_id: str) -> int:
        return len(self._subscribers.get(investigation_id, ()))


event_bus = InvestigationEventBus()
