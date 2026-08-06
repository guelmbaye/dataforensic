from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import IdempotencyGuard, datahub_provider, db_session, idempotency
from app.core.errors import NotFoundError
from app.models.tables import Action
from app.schemas.remediation import ActionExecuteRequest, RemediationOut
from app.services.datahub.base import DataHubProvider
from app.services.investigation import serialize_action
from app.services.resolution import ResolutionService

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("/{action_id}/execute", response_model=RemediationOut)
async def execute_action(
    action_id: str,
    payload: ActionExecuteRequest | None = None,
    guard: IdempotencyGuard = Depends(idempotency),
    session: AsyncSession = Depends(db_session),
    provider: DataHubProvider = Depends(datahub_provider),
) -> RemediationOut:
    payload = payload or ActionExecuteRequest()
    body = {"action_id": action_id, **payload.model_dump(mode="json")}
    cached = await guard.replay(body)
    if cached:
        return RemediationOut.model_validate(cached)

    action = await session.get(Action, action_id)
    if action is None:
        raise NotFoundError(f"Action {action_id} not found")

    service = ResolutionService(session, provider)
    await service.execute_action(action, approved=payload.approved, approved_by=payload.approved_by)
    result = RemediationOut.model_validate(serialize_action(action))
    await guard.store(body, result.model_dump(mode="json"))
    return result
