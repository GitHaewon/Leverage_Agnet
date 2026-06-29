"""Shadow Trading 도메인 모델 — 외부 의존성 없음."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional

from agents.shadow.pnl import ShadowCostConfig, calculate_shadow_pnl

ShadowTradeStatus = Literal[
    "OPEN", "TP_HIT", "SL_HIT", "MAX_HOLD", "REJECTED", "CANCELLED"
]


@dataclass
class ShadowTradeRecord:
    """
    가상 거래 도메인 모델.

    실제 주문 없음. Risk 검증은 실거래와 동일하게 통과.
    TP/SL은 monitor worker가 현재가와 비교해 close() 를 호출한다.
    """
    id: str
    user_id: str
    coin: str
    symbol: str
    direction: Literal["LONG", "SHORT"]
    entry_price: Decimal
    tp_price: Decimal
    sl_price: Decimal
    quantity: Decimal
    leverage: int
    opened_at: datetime
    status: ShadowTradeStatus = "OPEN"

    exit_price: Optional[Decimal] = None
    pnl_usdt: Optional[float] = None
    duration_seconds: Optional[float] = None
    closed_at: Optional[datetime] = None
    strategy_version: Optional[str] = None
    experiment_label: Optional[str] = None
    signal_id: Optional[str] = None
    position_size_usdt: Optional[Decimal] = None
    margin_usdt: Optional[Decimal] = None
    tp_distance: Optional[Decimal] = None
    sl_distance: Optional[Decimal] = None
    expected_max_loss_usdt: Optional[Decimal] = None
    actual_max_loss_usdt: Optional[Decimal] = None
    risk_budget_usdt: Optional[Decimal] = None
    risk_budget_utilization: Optional[Decimal] = None
    leverage_reason: Optional[str] = None
    reviewer_input_summary: Optional[dict[str, Any]] = None
    reviewer_result: Optional[str] = None
    reviewer_score: Optional[float] = None
    market_regime: Optional[str] = None
    exit_reason: Optional[str] = None
    gross_pnl_usdt: Optional[Decimal] = None
    entry_fee_usdt: Decimal = Decimal("0")
    exit_fee_usdt: Decimal = Decimal("0")
    entry_slippage_usdt: Decimal = Decimal("0")
    exit_slippage_usdt: Decimal = Decimal("0")
    funding_fee_usdt: Decimal = Decimal("0")
    # Compatibility field:
    # - OPEN records: entry-only slippage estimate captured at virtual fill time.
    # - CLOSED records: total slippage cost from calculate_shadow_pnl()
    #   (= entry_slippage_usdt + exit_slippage_usdt).
    estimated_slippage_usdt: Decimal = Decimal("0")
    net_pnl_usdt: Optional[Decimal] = None
    net_return_on_margin_pct: Optional[Decimal] = None
    pnl_calculation_status: str = "UNKNOWN"
    mfe_usdt: Decimal = Decimal("0")
    mae_usdt: Decimal = Decimal("0")
    data_error: bool = False
    system_error: bool = False
    max_hold_seconds: Optional[int] = None
    rejection_code: Optional[str] = None
    rejection_reason: Optional[str] = None

    @classmethod
    def open(
        cls,
        *,
        user_id: str,
        coin: str,
        symbol: str,
        direction: Literal["LONG", "SHORT"],
        entry_price: Decimal,
        tp_price: Decimal,
        sl_price: Decimal,
        quantity: Decimal,
        leverage: int,
        opened_at: Optional[datetime] = None,
        **metadata: Any,
    ) -> "ShadowTradeRecord":
        return cls(
            id=str(uuid.uuid4()),
            user_id=user_id,
            coin=coin,
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            tp_price=tp_price,
            sl_price=sl_price,
            quantity=quantity,
            leverage=leverage,
            opened_at=opened_at or datetime.now(timezone.utc),
            **metadata,
        )

    def close(
        self,
        exit_price: Decimal,
        status: ShadowTradeStatus,
        closed_at: Optional[datetime] = None,
        cost_config: ShadowCostConfig | None = None,
    ) -> None:
        """
        TP/SL 체결 시 청산 처리.

        LONG PnL = (exit - entry) * qty
        SHORT PnL = (entry - exit) * qty
        """
        assert status != "OPEN", "close() requires a terminal status"
        self.exit_price = exit_price
        self.status = status
        self.closed_at = closed_at or datetime.now(timezone.utc)
        self.duration_seconds = (self.closed_at - self.opened_at).total_seconds()
        result = calculate_shadow_pnl(
            direction=self.direction,
            entry_price=self.entry_price,
            exit_price=exit_price,
            quantity=self.quantity,
            margin_usdt=self.margin_usdt,
            opened_at=self.opened_at,
            closed_at=self.closed_at,
            config=cost_config or ShadowCostConfig(),
        )
        self.pnl_usdt = float(result.gross_pnl_usdt)
        self.exit_reason = status
        self.gross_pnl_usdt = result.gross_pnl_usdt
        self.entry_fee_usdt = result.entry_fee_usdt
        self.exit_fee_usdt = result.exit_fee_usdt
        self.entry_slippage_usdt = result.entry_slippage_usdt
        self.exit_slippage_usdt = result.exit_slippage_usdt
        self.estimated_slippage_usdt = result.slippage_cost_usdt
        self.funding_fee_usdt = result.funding_fee_usdt
        self.net_pnl_usdt = result.net_pnl_usdt
        self.net_return_on_margin_pct = result.net_return_on_margin_pct
        self.pnl_calculation_status = "COST_ADJUSTED"
