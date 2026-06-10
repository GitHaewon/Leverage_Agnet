"""Shadow Trading 도메인 모델 — 외부 의존성 없음."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Optional

ShadowTradeStatus = Literal["OPEN", "TP_HIT", "SL_HIT", "CANCELLED"]


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
        )

    def close(
        self,
        exit_price: Decimal,
        status: ShadowTradeStatus,
        closed_at: Optional[datetime] = None,
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
        if self.direction == "LONG":
            self.pnl_usdt = float((exit_price - self.entry_price) * self.quantity)
        else:
            self.pnl_usdt = float((self.entry_price - exit_price) * self.quantity)
