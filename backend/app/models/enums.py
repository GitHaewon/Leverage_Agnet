"""
PostgreSQL ENUM 타입 정의.

모든 ENUM은 두 레이어로 관리한다:
  1. Python Enum (타입 안전성)
  2. SQLAlchemy SAEnum (DB 매핑, create_type=False → 마이그레이션에서 생성)
"""
from __future__ import annotations

import enum

from sqlalchemy import Enum as SAEnum


# ── 사용자 & 구독 ────────────────────────────────────────────────────────────────

class PlanType(str, enum.Enum):
    FREE  = "free"
    PRO   = "pro"
    ELITE = "elite"


class RiskProfileType(str, enum.Enum):
    CONSERVATIVE = "conservative"
    MODERATE     = "moderate"
    AGGRESSIVE   = "aggressive"


class BillingPeriodType(str, enum.Enum):
    MONTHLY = "monthly"
    YEARLY  = "yearly"


class SubscriptionStatusType(str, enum.Enum):
    TRIALING           = "trialing"
    ACTIVE             = "active"
    PAST_DUE           = "past_due"
    CANCELLED          = "cancelled"
    INCOMPLETE         = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"


# ── 거래소 & 계좌 ────────────────────────────────────────────────────────────────

class ExchangeType(str, enum.Enum):
    BINANCE = "binance"
    BYBIT   = "bybit"
    OKX     = "okx"


class HealthStatusType(str, enum.Enum):
    HEALTHY      = "healthy"
    DEGRADED     = "degraded"
    DISCONNECTED = "disconnected"


# ── 시그널 ───────────────────────────────────────────────────────────────────────

class SignalDirectionType(str, enum.Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    HOLD  = "HOLD"


class SignalStatusType(str, enum.Enum):
    ACTIVE    = "active"
    EXPIRED   = "expired"
    EXECUTED  = "executed"
    DISMISSED = "dismissed"


# ── 포지션 ───────────────────────────────────────────────────────────────────────

class PositionStatusType(str, enum.Enum):
    OPEN       = "open"
    CLOSED     = "closed"
    LIQUIDATED = "liquidated"
    CANCELLED  = "cancelled"


class CloseReasonType(str, enum.Enum):
    TP_HIT       = "tp_hit"
    SL_HIT       = "sl_hit"
    MANUAL       = "manual"
    LIQUIDATED   = "liquidated"
    EMERGENCY    = "emergency"
    DCA_REVERSAL = "dca_reversal"


# ── 주문 ─────────────────────────────────────────────────────────────────────────

class OrderTypeEnum(str, enum.Enum):
    MARKET            = "market"
    LIMIT             = "limit"
    STOP_MARKET       = "stop_market"
    TAKE_PROFIT_MARKET = "take_profit_market"
    TRAILING_STOP     = "trailing_stop"


class OrderSideType(str, enum.Enum):
    BUY  = "BUY"
    SELL = "SELL"


class OrderPurposeType(str, enum.Enum):
    ENTRY           = "entry"
    TAKE_PROFIT     = "take_profit"
    STOP_LOSS       = "stop_loss"
    EMERGENCY_CLOSE = "emergency_close"
    DCA             = "dca"
    PARTIAL_CLOSE   = "partial_close"


class OrderStatusType(str, enum.Enum):
    PENDING          = "pending"
    OPEN             = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED           = "filled"
    CANCELLED        = "cancelled"
    REJECTED         = "rejected"
    EXPIRED          = "expired"


# ── 자동매매 모드 ────────────────────────────────────────────────────────────────

class TradingModeType(str, enum.Enum):
    FULL_AUTO   = "full_auto"
    SEMI_AUTO   = "semi_auto"
    SIGNAL_ONLY = "signal_only"


# ── 알림 ─────────────────────────────────────────────────────────────────────────

class NotificationTypeEnum(str, enum.Enum):
    SIGNAL_NEW          = "signal_new"
    ORDER_FILLED        = "order_filled"
    ORDER_FAILED        = "order_failed"
    POSITION_CLOSED     = "position_closed"
    LIQUIDATION_WARNING = "liquidation_warning"
    DAILY_SUMMARY       = "daily_summary"
    SYSTEM_ALERT        = "system_alert"
    PAYMENT_FAILED      = "payment_failed"
    API_KEY_ISSUE       = "api_key_issue"


class NotificationChannelType(str, enum.Enum):
    TELEGRAM = "telegram"
    EMAIL    = "email"
    WEB_PUSH = "web_push"


# ── SQLAlchemy ENUM 컬럼 타입 (create_type=False — 마이그레이션에서 생성) ─────────
# 모델에서 import해서 mapped_column() 에 전달한다.

def sa_enum(py_enum: type[enum.Enum], name: str) -> SAEnum:
    """PostgreSQL native ENUM 컬럼 타입 생성 헬퍼."""
    return SAEnum(
        py_enum,
        name=name,
        create_type=False,       # DDL은 Alembic 마이그레이션에서 담당
        values_callable=lambda e: [m.value for m in e],
    )


# 미리 생성된 SA 타입 인스턴스 (모델에서 import해서 재사용)
PLAN_TYPE              = sa_enum(PlanType,              "plan_type")
RISK_PROFILE_TYPE      = sa_enum(RiskProfileType,       "risk_profile_type")
BILLING_PERIOD_TYPE    = sa_enum(BillingPeriodType,     "billing_period_type")
SUBSCRIPTION_STATUS    = sa_enum(SubscriptionStatusType,"subscription_status_type")
EXCHANGE_TYPE          = sa_enum(ExchangeType,          "exchange_type")
HEALTH_STATUS_TYPE     = sa_enum(HealthStatusType,      "health_status_type")
SIGNAL_DIRECTION_TYPE  = sa_enum(SignalDirectionType,   "signal_direction_type")
SIGNAL_STATUS_TYPE     = sa_enum(SignalStatusType,      "signal_status_type")
POSITION_STATUS_TYPE   = sa_enum(PositionStatusType,    "position_status_type")
CLOSE_REASON_TYPE      = sa_enum(CloseReasonType,       "close_reason_type")
ORDER_TYPE_ENUM        = sa_enum(OrderTypeEnum,         "order_type_enum")
ORDER_SIDE_TYPE        = sa_enum(OrderSideType,         "order_side_type")
ORDER_PURPOSE_TYPE     = sa_enum(OrderPurposeType,      "order_purpose_type")
ORDER_STATUS_TYPE      = sa_enum(OrderStatusType,       "order_status_type")
TRADING_MODE_TYPE      = sa_enum(TradingModeType,       "trading_mode_type")
NOTIFICATION_TYPE_ENUM = sa_enum(NotificationTypeEnum,  "notification_type_enum")
NOTIFICATION_CHANNEL   = sa_enum(NotificationChannelType,"notification_channel_type")
