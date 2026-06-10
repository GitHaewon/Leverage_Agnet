"""
Execution Engine 데이터 모델 및 프로토콜.

설계 원칙:
  - 순수 Python dataclass — 외부 의존성 없음
  - RiskValidatorProtocol: RiskEngine과 동일한 인터페이스를 덕 타이핑으로 정의
  - OrderGatewayProtocol: PaperGateway / TestnetGateway / LiveGateway 교체 가능
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from agents.risk.models import (
    AccountState,
    OpenPosition,
    RawSignal,
    UserContext,
    ValidationResult,
)


# ── 주문 지시 ────────────────────────────────────────────────────────────────────

@dataclass
class OrderTicket:
    """단일 주문 지시 — Gateway로 전달되는 주문 단위."""
    symbol: str
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "TAKE_PROFIT_MARKET", "STOP_MARKET"]
    quantity: Decimal
    price: Decimal               # MARKET: 예상 체결가, TP/SL: 트리거가
    reduce_only: bool = False
    purpose: Literal["entry", "take_profit", "stop_loss", "emergency_close"] = "entry"


@dataclass
class FilledOrder:
    """체결된 주문 결과."""
    exchange_order_id: str
    symbol: str
    purpose: Literal["entry", "take_profit", "stop_loss", "emergency_close"]
    side: str
    order_type: str
    quantity: Decimal
    avg_fill_price: Decimal
    fee_usdt: Decimal
    filled_at: datetime


# ── 실행 요청 / 결과 ──────────────────────────────────────────────────────────────

@dataclass
class ExecutionRequest:
    """
    ExecutionEngine.execute() 입력.

    Risk 검증에 필요한 모든 데이터를 호출자가 미리 로드해서 전달한다.
    (I/O는 이 레이어 밖에서 처리 — 도메인 순수성 유지)
    """
    signal: RawSignal
    user_ctx: UserContext
    account: AccountState
    daily_loss_usdt: Decimal
    weekly_loss_usdt: Decimal
    weekly_limit_usdt: Decimal
    consecutive_losses: int
    open_positions_count: int
    same_coin_position: OpenPosition | None


@dataclass
class ExecutionResult:
    """
    ExecutionEngine.execute() 출력.

    approved:  Risk 검증 통과 여부
    executed:  실제 주문 체결 여부 (LIVE_TRADING_ENABLED=false면 항상 False)
    mode:      "paper" | "testnet" | "live"
    tp_sl_failed: entry 체결 후 TP/SL 설정 실패 → 호출자가 긴급 청산 처리 필요
    """
    approved: bool
    executed: bool
    mode: Literal["paper", "testnet", "live"] = "paper"

    rejection_code: str | None = None
    rejection_reason: str | None = None
    validation: ValidationResult | None = None

    entry_order: FilledOrder | None = None
    tp_order: FilledOrder | None = None
    sl_order: FilledOrder | None = None

    tp_sl_failed: bool = False
    # tp_sl_failed 후처리 결과
    emergency_close_order: FilledOrder | None = None   # 긴급 청산 체결 (성공 시)
    emergency_close_failed: bool = False               # 긴급 청산까지 실패 (CRITICAL)
    warnings: list[str] = field(default_factory=list)


# ── 프로토콜 (인터페이스) ─────────────────────────────────────────────────────────

class RiskValidatorProtocol(Protocol):
    """
    RiskEngine과 동일한 validate() 시그니처를 덕 타이핑으로 정의.

    단위 테스트에서는 StubRiskValidator가,
    프로덕션에서는 RiskEngine이 이 프로토콜을 충족한다.
    Redis 의존성을 도메인 레이어 밖으로 격리하는 것이 목적.
    """
    async def validate(
        self,
        signal: RawSignal,
        ctx: UserContext,
        account: AccountState,
        daily_loss_usdt: Decimal,
        weekly_loss_usdt: Decimal,
        weekly_limit_usdt: Decimal,
        consecutive_losses: int,
        open_positions_count: int,
        same_coin_position: OpenPosition | None,
    ) -> ValidationResult: ...


class OrderGatewayProtocol(Protocol):
    """
    주문 실행 게이트웨이 프로토콜.

    구현체:
      PaperGateway   — 실제 API 없음, 로컬 시뮬레이션 (LIVE_TRADING_ENABLED=false)
      TestnetGateway — Binance Testnet (BINANCE_TESTNET=true)
      LiveGateway    — Binance Mainnet (프로덕션)
    """
    async def place_order(self, ticket: OrderTicket) -> FilledOrder: ...
    async def cancel_all_orders(self, symbol: str) -> int: ...


# ── Safety Gate 프로토콜 ───────────────────────────────────────────────────────────

@dataclass
class SafetyDecision:
    """
    SafetyGateProtocol.check_order_allowed() 반환 타입.

    backend/app/safety 의존성 없이 agents/ 레이어에서 사용 가능하도록
    SafetyCheckResult와 별도로 정의한다.
    """
    allowed: bool
    rejection_code: str | None = None
    message: str = ""


class SafetyGateProtocol(Protocol):
    """
    Safety Gate 인터페이스.

    구현체:
      SafetyGateAdapter (backend/app/safety/adapter.py) — SafetyGate 래핑
      StubSafetyGate — 단위 테스트 전용
    """
    async def check_order_allowed(self, user_id: str) -> SafetyDecision: ...
