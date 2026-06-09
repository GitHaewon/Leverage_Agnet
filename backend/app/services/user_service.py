"""
User Service — auto-trading user context assembly.

get_auto_trading_users() 와 get_user_context() 는 analysis_worker에서
OrchestratorPipeline 에 주입할 UserTradingContext 를 조립한다.

계좌 잔고(account_state) 및 포지션(open_positions, portfolio_account)은
현재 None/빈 값으로 반환된다. 실거래 활성화(C-02) 시 Binance API 로
채워야 한다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.enums import TradingModeType
from app.models.user import User
from app.models.user_settings import UserSettings

if TYPE_CHECKING:
    pass


@dataclass
class UserTradingContext:
    """
    Aggregated user context passed to OrchestratorPipeline.

    account_state / open_positions / portfolio_account remain None/empty until
    C-02 (live Binance account fetching) is implemented.
    """
    id: uuid.UUID
    plan: str
    account_state: Any = None
    daily_loss_usdt: Decimal = field(default_factory=lambda: Decimal("0"))
    weekly_loss_usdt: Decimal = field(default_factory=lambda: Decimal("0"))
    weekly_limit_usdt: Decimal = field(default_factory=lambda: Decimal("500"))
    consecutive_losses: int = 0
    open_positions: list = field(default_factory=list)
    portfolio_account: Any = None
    settings: Any = None

    @classmethod
    def from_user(cls, user: User) -> "UserTradingContext":
        plan = user.plan.value if hasattr(user.plan, "value") else str(user.plan)
        return cls(id=user.id, plan=plan, settings=user.settings)


async def get_auto_trading_users() -> list[UserTradingContext]:
    """Return users where trading is active and mode is full_auto or semi_auto."""
    async with AsyncSessionLocal() as db:
        stmt = (
            select(User)
            .join(UserSettings, User.id == UserSettings.user_id)
            .where(
                UserSettings.is_trading_active.is_(True),
                UserSettings.mode.in_([
                    TradingModeType.FULL_AUTO,
                    TradingModeType.SEMI_AUTO,
                ]),
            )
            .options(selectinload(User.settings))
        )
        result = await db.execute(stmt)
        users = result.scalars().all()
    return [UserTradingContext.from_user(u) for u in users]


async def get_user_context(user_id: str) -> UserTradingContext:
    """Return trading context for a single user. Raises ValueError if not found."""
    uid = uuid.UUID(user_id)
    async with AsyncSessionLocal() as db:
        stmt = (
            select(User)
            .where(User.id == uid)
            .options(selectinload(User.settings))
        )
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f"User {user_id} not found")
    return UserTradingContext.from_user(user)
