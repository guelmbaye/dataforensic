from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.errors import NotFoundError
from app.schemas.pattern import KnowledgePatternOut, PatternListResponse, PatternMatch
from app.services.patterns import PatternLibrary

router = APIRouter(prefix="/patterns", tags=["knowledge"])


@router.get("", response_model=PatternListResponse)
async def list_patterns(session: AsyncSession = Depends(db_session)) -> PatternListResponse:
    """The organisational memory: what this DataHub has learned so far."""
    library = PatternLibrary(session)
    rows = await library.all()
    items = [PatternLibrary.to_public(row) for row in rows]
    return PatternListResponse(items=items, total=len(items))


@router.get("/match", response_model=list[PatternMatch])
async def match_patterns(
    symptom: str | None = Query(default=None),
    asset_urn: str | None = Query(default=None),
    pattern: str | None = Query(default=None),
    limit: int = Query(default=3, ge=1, le=10),
    session: AsyncSession = Depends(db_session),
) -> list[PatternMatch]:
    """What the agent would recognise if this incident arrived right now."""
    return await PatternLibrary(session).match(
        symptom=symptom, asset_urn=asset_urn, pattern=pattern, limit=limit
    )


@router.get("/{pattern}", response_model=KnowledgePatternOut)
async def get_pattern(
    pattern: str, session: AsyncSession = Depends(db_session)
) -> KnowledgePatternOut:
    row = await PatternLibrary(session).get(pattern)
    if row is None:
        raise NotFoundError(f"Knowledge pattern {pattern} not found")
    return PatternLibrary.to_public(row)
