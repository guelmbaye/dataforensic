"""Small shared helpers (ids, time, text)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def ensure_aware(value: datetime | None) -> datetime | None:
    """Normalise a datetime to timezone-aware UTC.

    SQLite (and any non-timezone-aware column) returns naive datetimes. Mixing
    them with the aware datetimes parsed from the context graph raises at
    comparison time, so every datetime crossing into the reasoning layer goes
    through here.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_STOPWORDS = {
    "the", "a", "an", "of", "on", "in", "for", "to", "and", "is", "was", "by",
    "de", "la", "le", "les", "des", "un", "une", "du", "au", "aux", "et",
}


def tokenize(text: str | None) -> set[str]:
    if not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2 and t not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def urn_name(urn: str | None) -> str:
    """Human readable short name for a DataHub URN.

    URN shapes differ by entity, and assuming the dataset shape everywhere
    produced names like `PROD)` for a data job and `looker,taxi_operations` for
    a dashboard — visible in the evidence list and in the pattern library.

        dataset   (urn:li:dataPlatform:snowflake,DB.SCHEMA.TABLE,PROD) -> TABLE
        dataJob   (urn:li:dataFlow:(dbt,flow,PROD),orders_enriched)    -> orders_enriched
        dashboard (looker,revenue_overview)                            -> revenue_overview
        corpGroup urn:li:corpGroup:analytics-engineering               -> analytics-engineering
    """
    if not urn:
        return ""

    if not urn.endswith(")"):
        return urn.split(":")[-1].strip() or urn

    inner = urn[urn.index("(") + 1 : -1] if "(" in urn else urn

    # A data job nests its flow URN, and the job's own name is what follows the
    # closing parenthesis of that nested URN.
    if "(" in inner and ")" in inner:
        tail = inner[inner.rindex(")") + 1 :].lstrip(",").strip()
        if tail:
            return tail

    parts = [part.strip() for part in inner.split(",")]
    if len(parts) >= 3:
        # dataset: (platform, name, env)
        candidate = parts[1]
    elif len(parts) == 2:
        # dashboard / chart: (tool, id)
        candidate = parts[1]
    else:
        candidate = parts[0]

    return candidate.split(".")[-1].strip() or candidate


def urn_entity_type(urn: str | None) -> str:
    if not urn or not urn.startswith("urn:li:"):
        return "UNKNOWN"
    return urn.split(":")[2].upper()
