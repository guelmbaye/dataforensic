"""Structured JSON logging with secret redaction (DOCUMENT 09 - section 20)."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

SENSITIVE_KEYS = {
    "token", "api_key", "apikey", "authorization", "password", "secret",
    "datahub_token", "llm_api_key", "credentials", "cookie",
}

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
    "message", "asctime",
}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if k.lower() in SENSITIVE_KEYS else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = redact(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ContextLogger(logging.LoggerAdapter):
    """A logger that cannot be crashed by one of its own context keys.

    `logging` refuses any `extra` key that collides with a LogRecord attribute
    and raises KeyError inside makeRecord -- at call time, in the caller's stack.
    Structured logs carry arbitrary application fields, so a collision on a name
    like `message`, `module` or `args` is a matter of when, not if, and a log
    line must never be able to take down the code it is describing.

    Colliding keys are renamed rather than dropped: the value is still worth
    reading, it just cannot keep that name.
    """

    def process(
        self, msg: Any, kwargs: dict[str, Any]
    ) -> tuple[Any, dict[str, Any]]:
        extra = kwargs.get("extra")
        if extra:
            kwargs["extra"] = {
                (f"ctx_{key}" if key in _RESERVED else key): value
                for key, value in extra.items()
            }
        return msg, kwargs


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> ContextLogger:
    return ContextLogger(logging.getLogger(name), {})
