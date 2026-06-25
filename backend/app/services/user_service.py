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
from datetime import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import logging

from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import selectinload

from agents.portfolio.models import AccountContext
from agents.risk.models import AccountState
from app.core.config import settings as app_settings
from app.core.database import AsyncSessionLocal, celery_session
from app.models.enums import TradingModeType
from app.models.user import User
from app.models.user_settings import UserSettings

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass


@dataclass
class UserTradingContext:
    """
    Aggregated user context passed to OrchestratorPipeline.

    Shadow/Paper mode uses a virtual account balance so the deterministic
    decision/risk pipeline can produce executable virtual trades.
    """
    id: uuid.UUID
    plan: str
    risk_profile: str = "moderate"
    risk_per_trade: float = 0.01
    max_leverage: int = 5
    max_concurrent_positions: int = 1
    daily_loss_limit_pct: float = 0.01
    is_trading_active: bool = True
    allowed_hours_start: str | None = None
    allowed_hours_end: str | None = None
    account_state: AccountState | None = None
    daily_loss_usdt: Decimal = field(default_factory=lambda: Decimal("0"))
    weekly_loss_usdt: Decimal = field(default_factory=lambda: Decimal("0"))
    weekly_limit_usdt: Decimal = field(default_factory=lambda: Decimal("500"))
    consecutive_losses: int = 0
    open_positions: list = field(default_factory=list)
    portfolio_account: AccountContext | None = None
    settings: Any = None

    @property
    def user_id(self) -> uuid.UUID:
        """Risk/Execution 레이어가 기대하는 사용자 ID 필드."""
        return self.id

    @classmethod
    def from_user(cls, user: User) -> "UserTradingContext":
        plan = user.plan.value if hasattr(user.plan, "value") else str(user.plan)
        risk_profile = (
            user.risk_profile.value
            if hasattr(user.risk_profile, "value")
            else str(user.risk_profile)
        )
        user_settings = user.settings
        virtual_balance = _virtual_balance()

        if user_settings is None:
            return cls(
                id=user.id,
                plan=plan,
                risk_profile=risk_profile,
                account_state=(
                    _account_state(virtual_balance)
                    if virtual_balance is not None
                    else None
                ),
                portfolio_account=(
                    _portfolio_account(virtual_balance, risk_profile)
                    if virtual_balance is not None
                    else None
                ),
                settings=None,
            )

        daily_loss_limit = Decimal(str(user_settings.daily_loss_limit))
        balance_for_limits = virtual_balance or daily_loss_limit
        daily_loss_pct = _safe_pct(daily_loss_limit, balance_for_limits)

        return cls(
            id=user.id,
            plan=plan,
            risk_profile=risk_profile,
            risk_per_trade=float(user_settings.risk_per_trade),
            max_leverage=int(user_settings.max_leverage),
            max_concurrent_positions=int(user_settings.max_concurrent_positions),
            daily_loss_limit_pct=daily_loss_pct,
            is_trading_active=bool(user_settings.is_trading_active),
            allowed_hours_start=_time_to_hhmm(user_settings.allowed_hours_start),
            allowed_hours_end=_time_to_hhmm(user_settings.allowed_hours_end),
            account_state=(
                _account_state(virtual_balance)
                if virtual_balance is not None
                else None
            ),
            weekly_limit_usdt=daily_loss_limit * Decimal("5"),
            portfolio_account=(
                _portfolio_account(virtual_balance, risk_profile)
                if virtual_balance is not None
                else None
            ),
            settings=user_settings,
        )


def _virtual_balance() -> Decimal | None:
    if app_settings.LIVE_TRADING_ENABLED and not app_settings.SHADOW_TRADING_ENABLED:
        return None
    return Decimal(str(app_settings.SHADOW_INITIAL_BALANCE_USDT))


def _account_state(balance: Decimal) -> AccountState:
    return AccountState(
        available_balance=balance,
        total_balance=balance,
        initial_balance=balance,
        open_positions_count=0,
        open_positions_risk_usdt=Decimal("0"),
    )


def _portfolio_account(balance: Decimal, risk_profile: str) -> AccountContext:
    known_profiles = {"conservative", "moderate", "aggressive"}
    profile = risk_profile if risk_profile in known_profiles else "moderate"
    return AccountContext(
        available_balance=balance,
        initial_balance=balance,
        risk_profile=profile,  # type: ignore[arg-type]
    )


def _safe_pct(amount: Decimal, basis: Decimal) -> float:
    if basis <= 0:
        return 0.01
    return float(amount / basis)


def _time_to_hhmm(value: time | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%H:%M")


async def enable_auto_trading(user_id: str) -> None:
    """
    Kill switch 해제 후 UserSettings.is_trading_active를 True로 복원한다.

    is_trading_active=False인 경우에만 UPDATE를 실행(idempotent).
    """
    uid = uuid.UUID(user_id)
    async with AsyncSessionLocal() as session:
        stmt = (
            sa_update(UserSettings)
            .where(UserSettings.user_id == uid)
            .where(UserSettings.is_trading_active.is_(False))
            .values(is_trading_active=True)
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(stmt)
        await session.commit()
    if result.rowcount > 0:
        logger.info("auto_trading_enabled user_id=%s", user_id)


async def disable_auto_trading(user_id: str, reason: str = "") -> None:
    """
    Kill switch 발동 시 UserSettings.is_trading_active를 False로 설정한다.

    is_trading_active=True인 경우에만 UPDATE를 실행(idempotent).
    이후 get_auto_trading_users()가 이 사용자를 즉시 제외하도록 보장한다.
    재활성화는 사용자가 UI에서 수동으로 수행한다.
    """
    uid = uuid.UUID(user_id)
    async with AsyncSessionLocal() as session:
        stmt = (
            sa_update(UserSettings)
            .where(UserSettings.user_id == uid)
            .where(UserSettings.is_trading_active.is_(True))
            .values(is_trading_active=False)
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(stmt)
        await session.commit()
    if result.rowcount > 0:
        logger.warning(
            "auto_trading_disabled user_id=%s reason=%s",
            user_id, reason,
        )


async def get_auto_trading_users() -> list[UserTradingContext]:
    """Return users where trading is active and mode is full_auto or semi_auto."""
    async with celery_session() as db:
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
    async with celery_session() as db:
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
