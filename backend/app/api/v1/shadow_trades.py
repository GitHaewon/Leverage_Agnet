"""Shadow Trading 조회 API."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, DbDep, RedisDep
from app.repositories.shadow_trade_repository import ShadowTradeRepository
from app.schemas.common import DataResponse, PaginatedData, PaginatedResponse
from app.schemas.shadow_trades import ShadowTradeOut, ShadowTradeStats

router = APIRouter(prefix="/shadow-trades", tags=["shadow-trades"])


@router.get("/prices", response_model=DataResponse[dict])
async def get_market_prices(
    current_user: CurrentUserDep,
    redis: RedisDep,
) -> DataResponse[dict]:
    prices: dict[str, float] = {}
    for coin in ["BTC", "ETH"]:
        raw: str | None = await redis.get(f"price:{coin}")
        if raw:
            prices[coin] = float(raw)
    return DataResponse(data=prices)


@router.get("/stats", response_model=DataResponse[ShadowTradeStats])
async def get_shadow_stats(
    current_user: CurrentUserDep,
    db: DbDep,
) -> DataResponse[ShadowTradeStats]:
    repo = ShadowTradeRepository(db)
    stats = await repo.get_stats(str(current_user.id))
    return DataResponse(data=stats)


@router.get("", response_model=PaginatedResponse[ShadowTradeOut])
async def list_shadow_trades(
    current_user: CurrentUserDep,
    db: DbDep,
    status: Literal["OPEN", "TP_HIT", "SL_HIT", "CANCELLED"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse[ShadowTradeOut]:
    repo = ShadowTradeRepository(db)
    trades, total = await repo.list_trades(
        str(current_user.id),
        status=status,
        limit=limit,
        offset=offset,
    )
    items = [ShadowTradeOut.model_validate(t) for t in trades]
    return PaginatedResponse(
        data=PaginatedData(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            has_next=(offset + limit) < total,
        )
    )
