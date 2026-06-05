"""
Binance Futures 관련 Request/Response Pydantic 스키마.

금융 데이터: Decimal 사용 (float 절대 금지 — 부동소수점 오차).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderSideType, OrderStatusType, OrderTypeEnum


# ════════════════════════════════════════════════════════════════
# API Key 검증
# ════════════════════════════════════════════════════════════════

class ConnectRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    api_key: str = Field(min_length=10, max_length=100)
    api_secret: str = Field(min_length=10, max_length=100)
    label: str = Field(default="Main Account", max_length=100)
    is_testnet: bool = True


class KeyPermissions(BaseModel):
    can_trade: bool
    can_futures_trade: bool
    has_withdraw_permission: bool   # 반드시 False여야 등록 가능
    ip_restrict: bool


class ConnectData(BaseModel):
    account_id: str
    label: str
    status: str            # "connected"
    is_testnet: bool
    balance_usdt: Decimal
    permissions: list[str]
    connected_at: str


# ════════════════════════════════════════════════════════════════
# 잔고 조회
# ════════════════════════════════════════════════════════════════

class AssetBalance(BaseModel):
    asset: str
    wallet_balance: Decimal
    unrealized_profit: Decimal
    margin_balance: Decimal
    available_balance: Decimal


class AccountBalanceData(BaseModel):
    total_balance: Decimal
    available_balance: Decimal
    total_unrealized_pnl: Decimal
    total_margin_used: Decimal
    margin_ratio: Decimal
    assets: list[AssetBalance]
    fetched_at: str


class AccountStatusData(BaseModel):
    is_connected: bool
    account_id: str | None
    label: str | None
    is_testnet: bool | None
    balance_usdt: Decimal | None
    available_usdt: Decimal | None
    unrealized_pnl: Decimal | None
    margin_used: Decimal | None
    last_checked_at: str | None
    consecutive_failures: int
    status: str            # "healthy" | "degraded" | "disconnected"


# ════════════════════════════════════════════════════════════════
# 포지션 조회
# ════════════════════════════════════════════════════════════════

class PositionInfo(BaseModel):
    symbol: str
    coin: str
    side: Literal["LONG", "SHORT"]
    position_amt: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    leverage: int
    liquidation_price: Decimal
    margin_type: str       # "cross" | "isolated"
    isolated_margin: Decimal
    notional: Decimal


# ════════════════════════════════════════════════════════════════
# 주문 생성
# ════════════════════════════════════════════════════════════════

class MarketOrderRequest(BaseModel):
    """
    시장가 주문 요청 — stop_loss 필수 (TRADING_RULES.md §7, CLAUDE.md 절대 규칙).
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    symbol: Literal["BTCUSDT", "ETHUSDT"] = Field(
        description="거래 심볼 (MVP: BTC/ETH만 지원)"
    )
    side: Literal["BUY", "SELL"]
    quantity: Decimal = Field(gt=0, description="주문 수량 (코인 단위)")
    leverage: int = Field(ge=1, le=20, description="레버리지 배수")

    # TP/SL — stop_loss는 절대 필수
    take_profit: Decimal | None = Field(
        None, gt=0, description="목표가 (선택, HOLD 제외 권장)"
    )
    stop_loss: Decimal = Field(gt=0, description="손절가 (필수 — SL 없는 주문 금지)")

    reduce_only: bool = Field(default=False, description="포지션 감소 전용 주문")


class OrderResult(BaseModel):
    order_id: str
    client_order_id: str
    symbol: str
    status: str            # "NEW" | "FILLED" | "PARTIALLY_FILLED"
    executed_qty: Decimal
    avg_price: Decimal | None
    side: str
    order_type: str


class MarketOrderData(BaseModel):
    """시장가 진입 + TP/SL 주문 결과."""
    entry_order: OrderResult
    tp_order: OrderResult | None
    sl_order: OrderResult
    leverage_set: int
    warning: str | None = None     # TP/SL 설정 중 경고 메시지


# ════════════════════════════════════════════════════════════════
# 주문 취소
# ════════════════════════════════════════════════════════════════

class CancelOrderRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    symbol: Literal["BTCUSDT", "ETHUSDT"]
    order_id: str = Field(min_length=1)


class CancelOrderData(BaseModel):
    order_id: str
    symbol: str
    status: str
    cancelled: bool


# ════════════════════════════════════════════════════════════════
# Mock 모드 알림
# ════════════════════════════════════════════════════════════════

class ModeInfo(BaseModel):
    is_testnet: bool
    live_trading_enabled: bool
    mock_mode: bool
    warning: str | None = None
