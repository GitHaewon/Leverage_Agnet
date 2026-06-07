"""
주문 게이트웨이 구현체.

PaperGateway:
  LIVE_TRADING_ENABLED=false 시 기본 사용.
  Binance API 호출 없음 — 순수 로컬 계산.
  슬리피지 시뮬레이션 및 Taker 수수료 적용.

TestnetGateway / LiveGateway:
  I/O 레이어 — 통합 테스트 범주. 이 파일에는 포함하지 않음.
  (BINANCE_TESTNET=true / false 환경변수로 제어)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from agents.execution.models import FilledOrder, OrderTicket

# Binance Futures Taker 수수료 (0.04%)
TAKER_FEE_RATE: Decimal = Decimal("0.0004")


class PaperGateway:
    """
    페이퍼 트레이딩 게이트웨이 — 실제 API 호출 없음.

    MARKET 주문: price ± slippage 로 즉시 체결 시뮬레이션.
    TAKE_PROFIT_MARKET / STOP_MARKET: 트리거가(price) 그대로 기록.

    단위 테스트 및 LIVE_TRADING_ENABLED=false 시 사용.
    """

    def __init__(self, slippage_bps: int = 5) -> None:
        """
        slippage_bps: basis points (기본값 5 = 0.05%).
        0이면 정확히 price에 체결.
        """
        self._slippage = Decimal(str(slippage_bps)) / Decimal("10000")

    async def place_order(self, ticket: OrderTicket) -> FilledOrder:
        """
        MARKET → slippage 적용 체결.
        TP/SL → stop_price(ticket.price) 그대로 기록.
        """
        if ticket.order_type == "MARKET":
            fill_price = self._apply_slippage(ticket.price, ticket.side)
        else:
            fill_price = ticket.price

        fee = (ticket.quantity * fill_price * TAKER_FEE_RATE).quantize(Decimal("0.00001"))

        return FilledOrder(
            exchange_order_id=str(uuid.uuid4()),
            symbol=ticket.symbol,
            purpose=ticket.purpose,
            side=ticket.side,
            order_type=ticket.order_type,
            quantity=ticket.quantity,
            avg_fill_price=fill_price.quantize(Decimal("0.01")),
            fee_usdt=fee,
            filled_at=datetime.now(timezone.utc),
        )

    async def cancel_all_orders(self, symbol: str) -> int:
        """페이퍼 모드: 취소할 실제 주문 없음."""
        return 0

    def _apply_slippage(self, price: Decimal, side: str) -> Decimal:
        """
        BUY: price × (1 + slippage) — 더 높은 가격에 체결 (불리).
        SELL: price × (1 − slippage) — 더 낮은 가격에 체결 (불리).
        """
        if price == Decimal("0"):
            return price
        if side == "BUY":
            return price * (Decimal("1") + self._slippage)
        return price * (Decimal("1") - self._slippage)
