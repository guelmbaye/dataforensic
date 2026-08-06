"""The Knowledge Pattern library.

A resolved incident produces a record. A *pattern* is what emerges when several
records agree: the same failure mode, the symptoms it shows up as, the signals
that prove it, and the remediation that was actually verified. That aggregate is
the organisational asset — one incident is an anecdote, three are a playbook.

Patterns never decide anything. They arrive at the start of an investigation as
a prior, they are cited as evidence, and their verified plan can be reused. The
agent still gathers its own evidence and still scores its own hypotheses; a
pattern that turns out not to match simply fails to be confirmed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.utils import jaccard, tokenize, utcnow
from app.models.tables import Investigation, KnowledgePattern
from app.schemas.pattern import KnowledgePatternOut, PatternMatch

logger = get_logger(__name__)

MAX_SYMPTOMS = 12
MAX_ASSETS = 50
MAX_LOG = 25


def _merge_unique(existing: list[str], incoming: list[str], limit: int) -> list[str]:
    seen = list(existing)
    for item in incoming:
        if item and item not in seen:
            seen.append(item)
    return seen[:limit]


class PatternLibrary:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- reading ----------------------------------------------------------
    async def get(self, pattern: str) -> KnowledgePattern | None:
        return await self.session.get(KnowledgePattern, pattern)

    async def all(self) -> list[KnowledgePattern]:
        rows = await self.session.execute(
            select(KnowledgePattern).order_by(KnowledgePattern.occurrences.desc())
        )
        return list(rows.scalars().all())

    async def match(
        self,
        symptom: str | None = None,
        asset_urn: str | None = None,
        pattern: str | None = None,
        limit: int = 3,
    ) -> list[PatternMatch]:
        """Find patterns that plausibly describe an incident we have not solved yet.

        Similarity is deliberately crude and inspectable — symptom wording,
        asset overlap, and an exact pattern name if the caller already has one.
        A number a judge cannot reconstruct is worse than a simple one.
        """
        candidates = await self.all()
        if not candidates:
            return []

        symptom_tokens = tokenize(symptom or "")
        matches: list[PatternMatch] = []

        for row in candidates:
            score = 0.0
            reasons: list[str] = []

            if pattern and row.pattern == pattern:
                score += 0.5
                reasons.append("same root-cause pattern")

            if asset_urn and asset_urn in (row.affected_asset_urns or []):
                score += 0.25
                reasons.append("this asset was affected before")

            if symptom_tokens and row.symptoms:
                overlap = max(
                    (jaccard(symptom_tokens, tokenize(known)) for known in row.symptoms),
                    default=0.0,
                )
                if overlap > 0:
                    score += overlap * 0.35
                    reasons.append(f"symptom wording overlaps {overlap:.0%}")

            # A pattern seen repeatedly is a slightly better bet than a one-off,
            # but never enough to carry a match on its own.
            if row.occurrences > 1:
                score += min(row.occurrences, 5) * 0.01

            if score <= 0.05:
                continue

            matches.append(
                PatternMatch(
                    pattern=row.pattern,
                    label=row.label or row.pattern.replace("_", " ").title(),
                    similarity=round(min(score, 1.0), 4),
                    occurrences=row.occurrences,
                    average_confidence=round(row.average_confidence, 4),
                    average_trust_score=round(row.average_trust_score, 1),
                    verified_resolutions=row.verified_resolutions,
                    symptoms=list(row.symptoms or [])[:5],
                    evidence_signature=list(row.evidence_signature or []),
                    recommended_remediation=list(row.resolution_steps or []),
                    last_seen=row.last_seen,
                    match_reasons=reasons,
                )
            )

        matches.sort(key=lambda m: m.similarity, reverse=True)
        return matches[:limit]

    # -- writing ----------------------------------------------------------
    async def record(
        self,
        investigation: Investigation,
        symptom: str,
        evidence: list[dict[str, Any]],
        remediation_plan: dict[str, Any] | None,
        affected_assets: list[str],
        verification_passed: bool,
    ) -> KnowledgePattern | None:
        """Fold a finished investigation into the pattern library.

        Only verified resolutions update the recommended plan: an unverified fix
        must never become the thing the next investigation is told to do.
        """
        pattern_key = investigation.root_cause_pattern
        if not pattern_key:
            return None

        row = await self.get(pattern_key)
        now = utcnow()

        signature = sorted(
            {
                str(item.get("type"))
                for item in evidence
                if item.get("type") and item.get("relevance") in {"HIGH", "MEDIUM"}
            }
        )
        steps = [step.get("title", "") for step in (remediation_plan or {}).get("steps", [])]

        if row is None:
            row = KnowledgePattern(
                pattern=pattern_key,
                label=pattern_key.replace("_", " ").title(),
                description=investigation.root_cause_summary or "",
                occurrences=0,
                average_confidence=0.0,
                average_trust_score=0.0,
                verified_resolutions=0,
                first_seen=now,
                last_seen=now,
                symptoms=[],
                evidence_signature=[],
                resolution_steps=[],
                resolution_plan={},
                affected_asset_urns=[],
                occurrences_log=[],
            )
            self.session.add(row)

        previous = int(row.occurrences or 0)
        row.occurrences = previous + 1
        row.last_seen = now
        row.updated_at = now
        row.symptoms = _merge_unique(list(row.symptoms or []), [symptom], MAX_SYMPTOMS)
        row.evidence_signature = _merge_unique(
            list(row.evidence_signature or []), signature, 12
        )
        row.affected_asset_urns = _merge_unique(
            list(row.affected_asset_urns or []), affected_assets, MAX_ASSETS
        )

        confidence = float(investigation.confidence or 0.0)
        trust = float(investigation.trust_score or 0.0)
        row.average_confidence = (
            float(row.average_confidence or 0.0) * previous + confidence
        ) / row.occurrences
        row.average_trust_score = (
            float(row.average_trust_score or 0.0) * previous + trust
        ) / row.occurrences

        if verification_passed:
            row.verified_resolutions = int(row.verified_resolutions or 0) + 1
            if steps:
                row.resolution_steps = steps
                row.resolution_plan = remediation_plan or {}
            if not row.description:
                row.description = investigation.root_cause_summary or ""

        row.occurrences_log = (
            [
                {
                    "incident_id": investigation.incident_id,
                    "investigation_id": investigation.id,
                    "confidence": round(confidence, 4),
                    "trust_score": round(trust, 1),
                    "verified": verification_passed,
                    "duration_ms": int(investigation.duration_ms or 0),
                    "tool_calls": int(investigation.tool_call_count or 0),
                    "recorded_at": now.isoformat(),
                }
            ]
            + list(row.occurrences_log or [])
        )[:MAX_LOG]

        await self.session.flush()
        logger.info(
            "knowledge_pattern_recorded",
            extra={
                "pattern": row.pattern,
                "occurrences": row.occurrences,
                "verified_resolutions": row.verified_resolutions,
            },
        )
        return row

    # -- projection -------------------------------------------------------
    @staticmethod
    def to_public(row: KnowledgePattern) -> KnowledgePatternOut:
        log = list(row.occurrences_log or [])
        durations = [entry.get("duration_ms", 0) for entry in log if entry.get("duration_ms")]
        tool_calls = [entry.get("tool_calls", 0) for entry in log if entry.get("tool_calls")]
        return KnowledgePatternOut(
            pattern=row.pattern,
            label=row.label,
            description=row.description,
            occurrences=row.occurrences,
            verified_resolutions=row.verified_resolutions,
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            symptoms=list(row.symptoms or []),
            evidence_signature=list(row.evidence_signature or []),
            resolution_steps=list(row.resolution_steps or []),
            affected_asset_urns=list(row.affected_asset_urns or []),
            average_confidence=round(row.average_confidence, 4),
            average_trust_score=round(row.average_trust_score, 1),
            first_investigation_ms=durations[-1] if durations else None,
            latest_investigation_ms=durations[0] if durations else None,
            first_investigation_tool_calls=tool_calls[-1] if tool_calls else None,
            latest_investigation_tool_calls=tool_calls[0] if tool_calls else None,
            history=log,
        )
