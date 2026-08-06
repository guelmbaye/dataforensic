"""Async SQLAlchemy engine / session management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"echo": settings.db_echo, "future": True}
    return {
        "echo": settings.db_echo,
        "future": True,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
    }


engine = create_async_engine(settings.database_url, **_engine_kwargs(settings.database_url))
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Create tables. The MVP intentionally avoids a migration tool."""
    from app.models import tables  # noqa: F401  (ensure models are imported)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    await engine.dispose()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Session for background tasks (the agent runner)."""
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with session_scope() as session:
        yield session
