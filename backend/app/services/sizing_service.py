"""
SizingService — DB 데이터 로드 + PositionSizingEngine 연결.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.risk.kelly import calculate_kelly
from agents.risk.models import AccountState, RawSignal
from agents.risk.sizing_engine import PositionSizingEngine
from agents.risk.sizing_models import (
    KellyResult,
    SizingComparison,
    SizingConfig,
    SizingMethod,
    SizingResult,
    TradeStatistics,
)
from app.models.trade_log import TradeLog
from app.models.user import User
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.repositories.trade_log_repository import TradeLogRepository
from app.utils.exceptions import AppError, NotFoundError


class SizingService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._accounts = ExchangeAccountRepository(db)
        self._trade_logs = TradeLogRepository(db)
        self._engine = PositionSizingEngine()

    # ════════════════════════════════════════════════════════════════
    # 거래 통계 로드
    # ════════════════════════════════════════════════════════════════

    async def get_trade_statistics(
        self,
        user_id: uuid.UUID,
        lookback_days: int = 90,
    ) -> TradeStatistics:
        """거래 이력에서 Kelly 계산용 통계 추출."""
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        result = await self._db.execute(
            select(
                func.count(TradeLog.id).label("total"),
                func.sum(
                    func.case(
                        (TradeLog.net_pnl > 0, 1), else_=0
                    )
                ).label("wins"),
                func.avg(
                    func.case(
                        (TradeLog.net_pnl > 0, TradeLog.net_pnl), else_=None
                    )
                ).label("avg_win"),
                func.avg(
                    func.case(
                        (TradeLog.net_pnl < 0, func.abs(TradeLog.net_pnl)), else_=None
                    )
                ).label("avg_loss"),
                func.sum(
                    func.case(
                        (TradeLog.net_pnl > 0, TradeLog.net_pnl), else_=0
                    )
                ).label("gross_win"),
                func.sum(
                    func.case(
                        (TradeLog.net_pnl < 0, func.abs(TradeLog.net_pnl)), else_=0
                    )
                ).label("gross_loss"),
                func.sum(TradeLog.net_pnl).label("total_pnl"),
            ).where(
                TradeLog.user_id == user_id,
                TradeLog.created_at >= since,
            )
        )
        row = result.one()

        total = row.total or 0
        wins = row.wins or 0

        return TradeStatistics(
            total_trades=total,
            winning_trades=wins,
            losing_trades=total - wins,
            total_pnl=Decimal(str(row.total_pnl or 0)),
            avg_win_usdt=Decimal(str(row.avg_win or 0)),
            avg_loss_usdt=Decimal(str(row.avg_loss or 0)),
            gross_win_usdt=Decimal(str(row.gross_win or 0)),
            gross_loss_usdt=Decimal(str(row.gross_loss or 0)),
            period_days=lookback_days,
        )

    # ════════════════════════════════════════════════════════════════
    # 단일 방법 계산
    # ════════════════════════════════════════════════════════════════

    async def calculate(
        self,
        user: User,
        method: SizingMethod,
        signal_params: dict,
        risk_pct: float | None = None,
        risk_usdt: Decimal | None = None,
        kelly_fraction: float = 0.25,
        kelly_lookback_days: int = 90,
    ) -> SizingResult:
        account_model = await self._accounts.get_active_by_user(user.id)
        if account_model is None:
            raise NotFoundError("연결된 Binance 계좌")

        balance = account_model.cached_balance_usdt or Decimal("0")
        if balance <= 0:
            raise AppError(
                code="BINANCE_004",
                message="계좌 잔고가 없습니다. Binance 잔고를 먼저 조회하세요.",
            )

        account = AccountState(
            available_balance=balance,
            total_balance=balance,
            initial_balance=balance,
            open_positions_count=0,
            open_positions_risk_usdt=Decimal("0"),
        )

        signal = RawSignal(
            direction=signal_params["direction"],
            coin=signal_params["symbol"].replace("USDT", ""),
            symbol=signal_params["symbol"],
            confidence=0.80,
            entry_price=Decimal(str(signal_params["entry_price"])),
            take_profit=Decimal(str(signal_params["take_profit"])) if signal_params.get("take_profit") else None,
            stop_loss=Decimal(str(signal_params["stop_loss"])),
            leverage=signal_params["leverage"],
        )

        # Kelly일 때 거래 통계 로드
        trade_stats = None
        if method == SizingMethod.KELLY:
            trade_stats = await self.get_trade_statistics(user.id, kelly_lookback_days)

        # 사용자 설정 기반 기본 risk_pct
        default_risk_pct = float(user.settings.risk_per_trade) if user.settings else 0.02

        config = SizingConfig(
            method=method,
            risk_pct=risk_pct or default_risk_pct,
            risk_usdt=risk_usdt,
            kelly_fraction=kelly_fraction,
            kelly_lookback_days=kelly_lookback_days,
        )

        return self._engine.calculate(
            config=config,
            signal=signal,
            account=account,
            leverage=signal_params["leverage"],
            symbol=signal_params["symbol"],
            trade_stats=trade_stats,
        )

    # ════════════════════════════════════════════════════════════════
    # 4가지 방법 비교
    # ════════════════════════════════════════════════════════════════

    async def compare_all(
        self,
        user: User,
        signal_params: dict,
        base_risk_pct: float = 0.02,
        kelly_fraction: float = 0.25,
        kelly_lookback_days: int = 90,
    ) -> SizingComparison:
        account_model = await self._accounts.get_active_by_user(user.id)
        if account_model is None:
            raise NotFoundError("연결된 Binance 계좌")

        balance = account_model.cached_balance_usdt or Decimal("10000")
        account = AccountState(
            available_balance=balance,
            total_balance=balance,
            initial_balance=balance,
            open_positions_count=0,
            open_positions_risk_usdt=Decimal("0"),
        )

        signal = RawSignal(
            direction=signal_params["direction"],
            coin=signal_params["symbol"].replace("USDT", ""),
            symbol=signal_params["symbol"],
            confidence=0.80,
            entry_price=Decimal(str(signal_params["entry_price"])),
            take_profit=Decimal(str(signal_params["take_profit"])) if signal_params.get("take_profit") else None,
            stop_loss=Decimal(str(signal_params["stop_loss"])),
            leverage=signal_params["leverage"],
        )

        trade_stats = await self.get_trade_statistics(user.id, kelly_lookback_days)

        return self._engine.compare_all(
            signal=signal,
            account=account,
            leverage=signal_params["leverage"],
            symbol=signal_params["symbol"],
            base_risk_pct=base_risk_pct,
            base_risk_usdt=balance * Decimal(str(base_risk_pct)),
            kelly_fraction=kelly_fraction,
            trade_stats=trade_stats,
        )

    # ════════════════════════════════════════════════════════════════
    # Kelly 통계 조회
    # ════════════════════════════════════════════════════════════════

    async def get_kelly_stats(
        self,
        user: User,
        kelly_fraction: float = 0.25,
        lookback_days: int = 90,
    ) -> dict:
        stats = await self.get_trade_statistics(user.id, lookback_days)
        kelly = calculate_kelly(
            stats=stats,
            kelly_fraction=kelly_fraction,
            min_sample_size=20,
        )
        return {
            "trade_stats": stats.as_dict(),
            "kelly_result": {
                "full_kelly":       round(kelly.full_kelly_fraction, 4),
                "applied_fraction": round(kelly.applied_fraction, 4),
                "multiplier":       kelly.kelly_multiplier,
                "win_rate":         f"{kelly.win_rate:.1%}",
                "avg_odds":         round(kelly.avg_odds, 3),
                "sample_size":      kelly.sample_size,
                "is_valid":         kelly.is_valid,
                "reason":           kelly.reason,
                "recommended_risk_pct": f"{kelly.capped_risk_pct:.2%}",
            },
        }
