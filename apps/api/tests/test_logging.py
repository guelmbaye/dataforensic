"""Logging must never be able to break the code it describes.

Regression: `logger.info(..., extra={"message": ...})` raises KeyError inside
makeRecord, in the caller's stack. It went unnoticed because the suite ran at
CRITICAL level, where `logger.info` returns before building a record. These
tests turn logging on so a collision fails here rather than at runtime.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.core.logging import ContextLogger, JsonFormatter, configure_logging, get_logger
from app.services.events import InvestigationEventWriter


@pytest.fixture
def loud_logging():
    """Run a block with logging actually enabled, then put it back."""
    previous = logging.getLogger().level
    configure_logging("INFO")
    yield
    configure_logging("CRITICAL")
    logging.getLogger().setLevel(previous)


class TestReservedKeys:
    def test_a_colliding_context_key_does_not_raise(self, loud_logging, caplog) -> None:
        logger = get_logger("test.collision")
        with caplog.at_level(logging.INFO):
            logger.info("something_happened", extra={"message": "human readable"})
        assert caplog.records

    @pytest.mark.parametrize("key", ["message", "module", "args", "levelname", "name"])
    def test_every_reserved_attribute_is_survivable(
        self, loud_logging, caplog, key: str
    ) -> None:
        logger = get_logger("test.reserved")
        with caplog.at_level(logging.INFO):
            logger.info("event", extra={key: "value"})
        record = caplog.records[-1]
        assert getattr(record, f"ctx_{key}") == "value"

    def test_safe_keys_keep_their_name(self, loud_logging, caplog) -> None:
        logger = get_logger("test.safe")
        with caplog.at_level(logging.INFO):
            logger.info("event", extra={"investigation_id": "abc", "seq": 3})
        record = caplog.records[-1]
        assert record.investigation_id == "abc"
        assert record.seq == 3

    def test_get_logger_returns_the_protected_adapter(self) -> None:
        assert isinstance(get_logger("test.type"), ContextLogger)


class TestJsonFormatter:
    def _render(self, **extra) -> dict:
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1,
            msg="event", args=(), exc_info=None,
        )
        for key, value in extra.items():
            setattr(record, key, value)
        return json.loads(JsonFormatter().format(record))

    def test_context_fields_are_serialised(self) -> None:
        payload = self._render(investigation_id="abc", seq=2)
        assert payload["message"] == "event"
        assert payload["investigation_id"] == "abc"
        assert payload["level"] == "INFO"

    def test_secrets_are_redacted(self) -> None:
        payload = self._render(config={"datahub_token": "super-secret", "url": "http://x"})
        assert payload["config"]["datahub_token"] == "***REDACTED***"
        assert payload["config"]["url"] == "http://x"


class TestEventWriterUnderRealLogging:
    async def test_emitting_an_investigation_event_survives_info_logging(
        self, session, loud_logging
    ) -> None:
        """The exact call that failed in production."""
        writer = InvestigationEventWriter(session, "investigation-under-test")
        envelope = await writer.emit(
            "evidence_found",
            "null_rate on orders_enriched moved 0.021 -> 0.317",
            {"type": "QUALITY_ANOMALY"},
        )
        assert envelope["seq"] == 1
        assert envelope["message"].startswith("null_rate")

    async def test_sequence_numbers_keep_increasing(self, session, loud_logging) -> None:
        writer = InvestigationEventWriter(session, "investigation-seq-test")
        first = await writer.emit("a", "first")
        second = await writer.emit("b", "second")
        assert second["seq"] == first["seq"] + 1
