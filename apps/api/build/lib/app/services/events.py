"""Investigation event writer: persist + publish (SSE)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.logging import get_logger
from app.core.utils import to_iso, utcnow
from app.models.tables import InvestigationEvent

logger = get_logger(__name__)

TERMINAL_EVENTS = {"investigation_completed", "investigation_failed", "investigation_blocked"}


class InvestigationEventWriter:
    def __init__(self, session: AsyncSession, investigation_id: str) -> None:
        self.session = session
        self.investigation_id = investigation_id
        self._seq: int | None = None

    async def _next_seq(self) -> int:
        if self._seq is None:
            current = await self.session.scalar(
                select(func.max(InvestigationEvent.seq)).where(
                    InvestigationEvent.investigation_id == self.investigation_id
                )
            )
            self._seq = int(current or 0)
        self._seq += 1
        return self._seq

    async def emit(
        self,
        event: str,
        message: str = "",
        payload: dict[str, Any] | None = None,
        level: str = "info",
    ) -> dict[str, Any]:
        seq = await self._next_seq()
        created_at = utcnow()
        row = InvestigationEvent(
            investigation_id=self.investigation_id,
            seq=seq,
            event=event,
            level=level,
            message=message,
            payload=payload or {},
            created_at=created_at,
        )
        self.session.add(row)
        await self.session.commit()

        envelope = {
            "seq": seq,
            "event": event,
            "level": level,
            "message": message,
            "payload": payload or {},
            "created_at": to_iso(created_at),
            "investigation_id": self.investigation_id,
        }
        await event_bus.publish(self.investigation_id, envelope)
        logger.info(
            "investigation_event",
            extra={
                "investigation_id": self.investigation_id,
                "event": event,
                "seq": seq,
                "message": message,
            },
        )
        return envelope
