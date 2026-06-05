"""
Binance 클라이언트 공통 타입 및 Protocol.

Real 클라이언트와 Mock 클라이언트가 동일한 인터페이스를 구현한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol, runtime_checkable

# ── 공유 데이터 클래스 ──────────────────────────────────────────────────────────

@dataclass
class AssetBalance:
    asset: str
    wallet_balance: Decimal
    unrealized_profit: Decimal
    margin_balance: Decimal
    available_balance: Decimal


@dataclass
class AccountInfo:
    total_wallet_balance: Decimal
    total_unrealized_profit: Decimal
    total_margin_balance: Decimal
    available_balance: Decimal
    total_position_initial_margin: Decimal
    assets: list[AssetBalance] = field(default_factory=list)
    can_trade: bool = True
    can_deposit: bool = True
    can_withdraw: bool = False   # 출금 권한 없어야 정상


@dataclass
class PositionRisk:
    symbol: str
    position_amt: Decimal       # 양수=LONG, 음수=SHORT
    entry_price: Decimal
    mark_price: Decimal
    unrealized_profit: Decimal
    liquidation_price: Decimal
    leverage: int
    margin_type: str            # "cross" | "isolated"
    isolated_margin: Decimal
    notional: Decimal


@dataclass
class OrderResponse:
    order_id: str
    client_order_id: str
    symbol: str
    status: str                 # "NEW" | "FILLED" | "PARTIALLY_FILLED" | "CANCELED"
    side: str                   # "BUY" | "SELL"
    order_type: str
    orig_qty: Decimal
    executed_qty: Decimal
    avg_price: Decimal | None


@dataclass
class KeyValidationResult:
    can_trade: bool
    can_futures_trade: bool
    has_withdraw: bool          # True → 등록 거부
    ip_restrict: bool
    balance_usdt: Decimal


# ── Binance 에러 ────────────────────────────────────────────────────────────────

class BinanceAPIError(Exception):
    """Binance API에서 반환한 에러."""
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"Binance API Error [{code}]: {message}")


BINANCE_ERROR_CODES = {
    -1000: "UNKNOWN",
    -1003: "TOO_MANY_REQUESTS",
    -1021: "INVALID_TIMESTAMP",
    -1100: "ILLEGAL_CHARS",
    -1121: "INVALID_SYMBOL",
    -2010: "NEW_ORDER_REJECTED",
    -2011: "CANCEL_REJECTED",
    -2013: "NO_SUCH_ORDER",
    -4003: "LEVERAGE_NOT_VALID",
    -4028: "LEVERAGE_EXCEEDS_LIMIT",
}


# ── 클라이언트 프로토콜 ──────────────────────────────────────────────────────────

@runtime_checkable
class BinanceClientProtocol(Protocol):
    """Real과 Mock 클라이언트가 공통으로 구현해야 하는 인터페이스."""

    async def get_account_info(self) -> AccountInfo: ...

    async def get_balance(self) -> list[AssetBalance]: ...

    async def get_positions(self, symbol: str | None = None) -> list[PositionRisk]: ...

    async def set_leverage(self, symbol: str, leverage: int) -> int: ...

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
    ) -> OrderResponse: ...

    async def cancel_order(self, symbol: str, order_id: str) -> OrderResponse: ...

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderResponse]: ...

    async def validate_api_key(self) -> KeyValidationResult: ...

    async def get_current_price(self, symbol: str) -> Decimal: ...
