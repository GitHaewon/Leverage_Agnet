"""
Binance Futures Mock 클라이언트.

실제 API 호출 없이 현실적인 응답을 시뮬레이션한다.
MOCK_TRADING_MODE=true 또는 테스트 환경에서 자동 활성화된다.

목적:
  - 로컬 개발: API Key 없이도 전체 플로우 테스트
  - 단위 테스트: 실제 네트워크 의존 없음
  - E2E 테스트: 시장 상황 완전 제어 가능
"""
from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_DOWN
from typing import Any

from app.clients.binance_base import (
    AccountInfo,
    AssetBalance,
    BinanceAPIError,
    KeyValidationResult,
    OrderResponse,
    PositionRisk,
)

# ── Mock 시장 데이터 ────────────────────────────────────────────────────────────
_MOCK_PRICES: dict[str, Decimal] = {
    "BTCUSDT": Decimal("67450.00"),
    "ETHUSDT": Decimal("3480.00"),
}

_MOCK_USDT_BALANCE = Decimal("10000.00")
_MOCK_LEVERAGE: dict[str, int] = {}
_MOCK_ORDERS: dict[str, OrderResponse] = {}   # order_id → OrderResponse
_MOCK_POSITIONS: list[PositionRisk] = []


class BinanceMockClient:
    """
    Mock Binance Futures 클라이언트.
    실제 API를 호출하지 않고 메모리에서 상태를 관리한다.
    """

    def __init__(self) -> None:
        self._balance = _MOCK_USDT_BALANCE
        self._used_margin = Decimal("0")
        self._positions: list[PositionRisk] = []
        self._orders: dict[str, OrderResponse] = {}
        self._leverage: dict[str, int] = {}

    async def get_account_info(self) -> AccountInfo:
        unrealized = sum(p.unrealized_profit for p in self._positions)
        return AccountInfo(
            total_wallet_balance=self._balance,
            total_unrealized_profit=unrealized,
            total_margin_balance=self._balance + unrealized,
            available_balance=self._balance - self._used_margin,
            total_position_initial_margin=self._used_margin,
            assets=[
                AssetBalance(
                    asset="USDT",
                    wallet_balance=self._balance,
                    unrealized_profit=unrealized,
                    margin_balance=self._balance + unrealized,
                    available_balance=self._balance - self._used_margin,
                )
            ],
            can_trade=True,
            can_deposit=True,
            can_withdraw=False,  # Withdraw 권한 없음 (정상)
        )

    async def get_balance(self) -> list[AssetBalance]:
        info = await self.get_account_info()
        return info.assets

    async def validate_api_key(self) -> KeyValidationResult:
        """Mock: 항상 유효한 Futures-only 키로 응답."""
        return KeyValidationResult(
            can_trade=True,
            can_futures_trade=True,
            has_withdraw=False,    # 출금 권한 없음 → 등록 허용
            ip_restrict=False,
            balance_usdt=self._balance,
        )

    async def get_positions(self, symbol: str | None = None) -> list[PositionRisk]:
        if symbol:
            return [p for p in self._positions if p.symbol == symbol]
        return list(self._positions)

    async def get_current_price(self, symbol: str) -> Decimal:
        price = _MOCK_PRICES.get(symbol)
        if price is None:
            raise BinanceAPIError(-1121, f"Invalid symbol: {symbol}")
        return price

    async def set_leverage(self, symbol: str, leverage: int) -> int:
        if not 1 <= leverage <= 20:
            raise BinanceAPIError(-4003, f"Invalid leverage: {leverage}")
        self._leverage[symbol] = leverage
        return leverage

    async def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal | None = None,
        stop_price: Decimal | None = None,
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> OrderResponse:
        if symbol not in _MOCK_PRICES:
            raise BinanceAPIError(-1121, f"Invalid symbol: {symbol}")

        mark_price = _MOCK_PRICES[symbol]

        # 시장가 주문: 현재 가격으로 즉시 체결
        if order_type in ("MARKET",):
            fill_price = mark_price
            order_id = str(uuid.uuid4().int)[:12]
            coid = client_order_id or f"tc_{uuid.uuid4().hex[:16]}"

            # 포지션 업데이트 (entry 주문)
            if not reduce_only:
                leverage = self._leverage.get(symbol, 1)
                margin = (quantity * fill_price) / leverage
                self._used_margin += margin
                pos_side = "LONG" if side == "BUY" else "SHORT"
                self._positions.append(
                    PositionRisk(
                        symbol=symbol,
                        position_amt=quantity if side == "BUY" else -quantity,
                        entry_price=fill_price,
                        mark_price=fill_price,
                        unrealized_profit=Decimal("0"),
                        liquidation_price=fill_price * (
                            Decimal("1") - Decimal("1") / leverage
                            if side == "BUY"
                            else Decimal("1") + Decimal("1") / leverage
                        ),
                        leverage=leverage,
                        margin_type="cross",
                        isolated_margin=Decimal("0"),
                        notional=quantity * fill_price,
                    )
                )

            order = OrderResponse(
                order_id=order_id,
                client_order_id=coid,
                symbol=symbol,
                status="FILLED",
                side=side,
                order_type=order_type,
                orig_qty=quantity,
                executed_qty=quantity,
                avg_price=fill_price,
            )

        # TP/SL 주문: 대기 상태로 등록
        elif order_type in ("TAKE_PROFIT_MARKET", "STOP_MARKET"):
            order_id = str(uuid.uuid4().int)[:12]
            coid = client_order_id or f"tc_{uuid.uuid4().hex[:16]}"
            order = OrderResponse(
                order_id=order_id,
                client_order_id=coid,
                symbol=symbol,
                status="NEW",
                side=side,
                order_type=order_type,
                orig_qty=quantity,
                executed_qty=Decimal("0"),
                avg_price=None,
            )
        else:
            raise BinanceAPIError(-2010, f"Unsupported order type in mock: {order_type}")

        self._orders[order.order_id] = order
        return order

    async def cancel_order(self, symbol: str, order_id: str) -> OrderResponse:
        order = self._orders.get(order_id)
        if order is None or order.symbol != symbol:
            raise BinanceAPIError(-2013, f"Order not found: {order_id}")
        cancelled = OrderResponse(
            order_id=order.order_id,
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            status="CANCELED",
            side=order.side,
            order_type=order.order_type,
            orig_qty=order.orig_qty,
            executed_qty=order.executed_qty,
            avg_price=order.avg_price,
        )
        self._orders[order_id] = cancelled
        return cancelled

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderResponse]:
        open_orders = [
            o for o in self._orders.values() if o.status in ("NEW", "PARTIALLY_FILLED")
        ]
        if symbol:
            open_orders = [o for o in open_orders if o.symbol == symbol]
        return open_orders

    async def aclose(self) -> None:
        pass
