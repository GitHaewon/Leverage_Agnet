"""Shadow Decision 조회 API — HOLD/REJECT 포함 전체 파이프라인 결정 이력."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, DbDep
from app.repositories.shadow_decision_repository import ShadowDecisionRepository
from app.schemas.common import DataResponse, PaginatedData, PaginatedResponse
from app.schemas.shadow_decisions import ShadowDecisionOut, ShadowDecisionStats

router = APIRouter(prefix="/shadow-decisions", tags=["shadow-decisions"])


@router.get("/stats", response_model=DataResponse[ShadowDecisionStats])
async def get_decision_stats(
    current_user: CurrentUserDep,
    db: DbDep,
) -> DataResponse[ShadowDecisionStats]:
    repo = ShadowDecisionRepository(db)
    stats = await repo.get_stats(str(current_user.id))
    return DataResponse(data=stats)


@router.get("", response_model=PaginatedResponse[ShadowDecisionOut])
async def list_decisions(
    current_user: CurrentUserDep,
    db: DbDep,
    coin: Literal["BTC", "ETH"] | None = Query(default=None),
    final_action: Literal["LONG", "SHORT", "HOLD"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse[ShadowDecisionOut]:
    repo = ShadowDecisionRepository(db)
    decisions, total = await repo.list_decisions(
        str(current_user.id),
        coin=coin,
        final_action=final_action,
        limit=limit,
        offset=offset,
    )
    items = [ShadowDecisionOut.model_validate(d) for d in decisions]
    return PaginatedResponse(
        data=PaginatedData(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            has_next=(offset + limit) < total,
        )
    )
