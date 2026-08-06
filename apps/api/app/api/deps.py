"""FastAPI dependencies: DB session, DataHub provider, idempotency."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.database import get_session
from app.models.tables import IdempotencyRecord
from app.services.datahub import get_provider as _get_provider
from app.services.datahub.base import DataHubProvider


async def db_session() -> AsyncSession:  # pragma: no cover - thin wrapper
    async for session in get_session():
        yield session


async def datahub_provider() -> DataHubProvider:
    return await _get_provider()


class IdempotencyGuard:
    """Replay protection for sensitive POSTs (DOCUMENT 06 - section 24)."""

    def __init__(self, session: AsyncSession, request: Request) -> None:
        self.session = session
        self.request = request
        self.key = request.headers.get("Idempotency-Key")
        self.endpoint = f"{request.method} {request.url.path}"

    @staticmethod
    def _hash(payload: Any) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    async def replay(self, payload: Any = None) -> dict[str, Any] | None:
        if not self.key:
            return None
        record = (
            (
                await self.session.execute(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.key == self.key,
                        IdempotencyRecord.endpoint == self.endpoint,
                    )
                )
            )
            .scalars()
            .first()
        )
        if record is None:
            return None
        if record.request_hash != self._hash(payload):
            raise ValidationError(
                "Idempotency-Key was already used with a different request body",
                details={"key": self.key, "endpoint": self.endpoint},
            )
        return record.response

    async def store(self, payload: Any, response: dict[str, Any], status_code: int = 200) -> None:
        if not self.key:
            return
        self.session.add(
            IdempotencyRecord(
                key=self.key,
                endpoint=self.endpoint,
                request_hash=self._hash(payload),
                status_code=status_code,
                response=response,
            )
        )
        await self.session.flush()


async def idempotency(
    request: Request, session: AsyncSession = Depends(db_session)
) -> IdempotencyGuard:
    return IdempotencyGuard(session, request)
