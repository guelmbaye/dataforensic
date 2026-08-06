"""Test fixtures: isolated database, isolated fixture-memory store, fresh app."""

from __future__ import annotations

import inspect
import os
import tempfile
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve().parent

# Set at import time, not inside a fixture: pytest imports conftest before the
# test modules, and those modules import the application — which builds the
# database engine from the settings. Waiting for a fixture would let a developer
# .env (or the Compose PostgreSQL URL) reach the engine first.
_TMP = Path(tempfile.mkdtemp(prefix="dataforensic-tests-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP / 'test.db'}"
os.environ["DATAHUB_MODE"] = "fixture"
os.environ["DATAHUB_MEMORY_STORE_PATH"] = str(_TMP / "fixture-memory.json")
os.environ["LLM_PROVIDER"] = "none"
# INFO, not CRITICAL: at CRITICAL, `logger.info` returns before building a
# LogRecord, so a bad `extra=` key never raises and the suite reports green on
# code that crashes in production. Handlers stay unconfigured, so nothing is
# printed unless a test asks for it.
os.environ["LOG_LEVEL"] = "INFO"
os.environ["ENVIRONMENT"] = "ci"


@pytest.fixture(scope="session", autouse=True)
def _environment() -> None:
    """Kept as a fixture so the ordering above is explicit to the reader."""


@pytest.fixture(scope="session")
def settings(_environment: None):
    from app.config import get_settings

    get_settings.cache_clear()
    import app.config as config_module

    config_module.settings = get_settings()
    return config_module.settings


@pytest.fixture(autouse=True)
async def clean_state(settings):
    """Every test starts with an organisation that has learned nothing.

    The product accumulates state on purpose - incidents, memory references,
    knowledge patterns - so without this each test would inherit whatever the
    previous one taught the system, and assertions about "the first
    investigation" would quietly stop meaning anything.
    """
    from sqlalchemy import delete

    from app.models.database import init_db, session_scope
    from app.models.tables import (
        Action,
        Evidence,
        Hypothesis,
        IdempotencyRecord,
        Incident,
        Investigation,
        InvestigationEvent,
        KnowledgePattern,
        MemoryReference,
        ScenarioState,
        ToolCallLog,
        Verification,
    )
    from app.services.datahub import get_provider

    await init_db()
    async with session_scope() as db:
        for table in (
            InvestigationEvent, ToolCallLog, Evidence, Hypothesis, Action,
            Verification, MemoryReference, KnowledgePattern, IdempotencyRecord,
            ScenarioState, Investigation, Incident,
        ):
            await db.execute(delete(table))

    provider = await get_provider()
    reset_memory = getattr(provider, "reset_memory", None)
    if callable(reset_memory):
        outcome = reset_memory()
        if inspect.isawaitable(outcome):
            await outcome
    yield


@pytest.fixture
async def session(settings, clean_state):
    from app.models.database import session_scope

    async with session_scope() as db:
        yield db


@pytest.fixture
async def provider(settings, clean_state):
    from app.services.datahub import get_provider, reset_provider

    await reset_provider()
    yield await get_provider()
    await reset_provider()


@pytest.fixture
async def client(settings, clean_state):
    import httpx
    from httpx import ASGITransport

    from app.main import app

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http_client:
        async with app.router.lifespan_context(app):
            yield http_client
