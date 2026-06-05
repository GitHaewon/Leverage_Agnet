"""
RiskService — HTTP API 계층과 RiskEngine을 연결.

DB에서 필요한 데이터를 로드하고 RiskEngine.validate()에 전달한다.
모든 자동매매 주문은 이 서비스를 통해 사전 승인을 받아야 한다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from agents.risk.constants import (
    DAILY_LOSS_LIMIT_DEFAULTS,
    WEEKLY_LOSS_LIMIT_DEFAULTS,
)
from agents.risk.engine import RiskEngine
from agents.risk.kill_switch import HaltTrigger, KillSwitch
from agents.risk.models import (
    AccountState,
    HaltState,
    RawSignal,
    UserContext,
    ValidationResult,
)
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.repositories.position_repository import PositionRepository
from app.repositories.trade_log_repository import TradeLogRepository
from app.repositories.user_repository import UserRepository


def _get_week_start_utc() -> datetime:
    """이번 주 월요일 00:00 UTC."""
    now = datetime.now(timezone.utc)
    days_since_monday = now.weekday()
    week_start = (now - __import__("datetime").timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return week_start


class RiskService:
    def __init__(self, db: AsyncSession, redis: aioredis.Redis) -> None:
        self._db = db
        self._redis = redis
        self._engine = RiskEngine(redis)
        self._kill_switch = KillSwitch(redis)
        self._users = UserRepository(db)
        self._positions = PositionRepository(db)
        self._trade_logs = TradeLogRepository(db)
        self._accounts = ExchangeAccountRepository(db)

    # ════════════════════════════════════════════════════════════════
    # 주문 사전 승인
    # ════════════════════════════════════════════════════════════════

    async def validate_signal(
        self, user_id: uuid.UUID, signal: RawSignal
    ) -> ValidationResult:
        """
        시그널 실행 전 전체 Risk 검증.
        Risk Engine이 승인하지 않으면 주문 금지.
        """
        # 사용자 컨텍스트 로드
        user = await self._users.get_by_id_with_settings(user_id)
        if user is None:
            return ValidationResult.system_error("User not found")

        settings = user.settings
        if settings is None:
            return ValidationResult.reject(
                "NO_SETTINGS",
                "자동매매 설정이 없습니다. 온보딩을 먼저 완료하세요."
            )

        # 거래소 계좌 & 잔고
        account_model = await self._accounts.get_active_by_user(user_id)
        if account_model is None:
            return ValidationResult.reject(
                "NO_ACCOUNT",
                "연결된 Binance 계좌가 없습니다."
            )

        balance = account_model.cached_balance_usdt or Decimal("0")

        # 손실 데이터 로드
        daily_loss = await self._trade_logs.get_daily_loss_usdt(user_id)
        weekly_loss = await self._trade_logs.get_weekly_loss_usdt(
            user_id, _get_week_start_utc()
        )
        consecutive = await self._trade_logs.get_consecutive_losses(user_id)

        # 포지션 데이터 로드
        open_count = await self._positions.count_open(user_id)
        same_coin_pos = await self._positions.get_open_as_risk_model(user_id, signal.coin)
        open_risk = await self._positions.calculate_open_risk_usdt(user_id)

        # 주간 손실 한도 계산
        risk_profile = user.risk_profile.value if hasattr(user.risk_profile, "value") else str(user.risk_profile)
        plan = user.plan.value if hasattr(user.plan, "value") else str(user.plan)
        weekly_limit_pct = WEEKLY_LOSS_LIMIT_DEFAULTS.get(risk_profile, 0.10)
        weekly_limit_usdt = balance * Decimal(str(weekly_limit_pct))

        # UserContext 구성
        ctx = UserContext(
            user_id=user_id,
            plan=plan,
            risk_profile=risk_profile,
            risk_per_trade=float(settings.risk_per_trade),
            max_leverage=settings.max_leverage,
            max_concurrent_positions=settings.max_concurrent_positions,
            daily_loss_limit_pct=float(
                DAILY_LOSS_LIMIT_DEFAULTS.get(risk_profile, 0.03)
                if settings.daily_loss_limit <= 0
                else settings.daily_loss_limit / balance if balance > 0 else 0.03
            ),
            is_trading_active=settings.is_trading_active,
            allowed_hours_start=(
                settings.allowed_hours_start.strftime("%H:%M")
                if settings.allowed_hours_start else None
            ),
            allowed_hours_end=(
                settings.allowed_hours_end.strftime("%H:%M")
                if settings.allowed_hours_end else None
            ),
        )

        # AccountState 구성
        account_state = AccountState(
            available_balance=balance,
            total_balance=balance,
            initial_balance=balance,  # TODO: 가입 시 최초 잔고 별도 저장 필요
            open_positions_count=open_count,
            open_positions_risk_usdt=open_risk,
        )

        return await self._engine.validate(
            signal=signal,
            ctx=ctx,
            account=account_state,
            daily_loss_usdt=daily_loss,
            weekly_loss_usdt=weekly_loss,
            weekly_limit_usdt=weekly_limit_usdt,
            consecutive_losses=consecutive,
            open_positions_count=open_count,
            same_coin_position=same_coin_pos,
        )

    # ════════════════════════════════════════════════════════════════
    # Kill Switch 관리
    # ════════════════════════════════════════════════════════════════

    async def get_halt_state(self, user_id: uuid.UUID) -> HaltState:
        return await self._kill_switch.get_halt_state(user_id)

    async def activate_kill_switch(self, user_id: uuid.UUID, reason: str) -> None:
        await self._kill_switch.emergency_stop(user_id, reason, HaltTrigger.MANUAL)

    async def deactivate_kill_switch(self, user_id: uuid.UUID) -> None:
        await self._kill_switch.resume_trading(user_id)

    async def activate_global_kill_switch(self, reason: str) -> None:
        await self._kill_switch.activate_global(reason)

    async def deactivate_global_kill_switch(self) -> None:
        await self._kill_switch.deactivate_global()

    # ════════════════════════════════════════════════════════════════
    # Risk 현황 조회
    # ════════════════════════════════════════════════════════════════

    async def get_risk_summary(self, user_id: uuid.UUID) -> dict:
        """현재 Risk 현황 요약 (대시보드용)."""
        daily_loss = await self._trade_logs.get_daily_loss_usdt(user_id)
        weekly_loss = await self._trade_logs.get_weekly_loss_usdt(
            user_id, _get_week_start_utc()
        )
        consecutive = await self._trade_logs.get_consecutive_losses(user_id)
        open_count = await self._positions.count_open(user_id)
        halt_state = await self._kill_switch.get_halt_state(user_id)

        return {
            "halt_state": {
                "is_halted": halt_state.is_halted,
                "trigger": halt_state.trigger,
                "until": halt_state.until,
                "is_global": halt_state.is_global,
            },
            "daily_loss_usdt": str(daily_loss),
            "weekly_loss_usdt": str(weekly_loss),
            "consecutive_losses": consecutive,
            "open_positions_count": open_count,
        }
