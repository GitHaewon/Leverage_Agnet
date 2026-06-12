"""
Risk Engine 데이터 모델.

순수 Python dataclass — 외부 의존성 없음.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal


@dataclass
class RawSignal:
    """AI 에이전트 파이프라인이 생성한 원시 시그널."""
    direction: Literal["LONG", "SHORT", "HOLD"]
    coin: str                    # "BTC" | "ETH"
    symbol: str                  # "BTCUSDT" | "ETHUSDT"
    confidence: float            # 0.0 ~ 1.0
    entry_price: Decimal
    take_profit: Decimal | None  # HOLD 시 None 허용
    stop_loss: Decimal | None    # HOLD 시 None 허용 (non-HOLD는 필수)
    leverage: int                # AI 추천 레버리지
    signal_id: uuid.UUID | None = None


@dataclass
class UserContext:
    """Risk 검증에 필요한 사용자 컨텍스트."""
    user_id: uuid.UUID
    plan: str                    # "free" | "pro" | "elite"
    risk_profile: str            # "conservative" | "moderate" | "aggressive"
    risk_per_trade: float        # 사용자 설정 (예: 0.02 = 2%)
    max_leverage: int            # 사용자 설정 최대 레버리지
    max_concurrent_positions: int
    daily_loss_limit_pct: float  # 사용자 설정 일일 손실 한도 (비율)
    is_trading_active: bool
    allowed_hours_start: str | None   # "HH:MM" UTC
    allowed_hours_end: str | None     # "HH:MM" UTC


@dataclass
class AccountState:
    """현재 계좌 상태 스냅샷."""
    available_balance: Decimal
    total_balance: Decimal
    initial_balance: Decimal     # 가입 시 첫 잔고 (긴급청산 임계값용)
    open_positions_count: int
    open_positions_risk_usdt: Decimal  # 오픈 포지션 예상 최대 손실 합계


@dataclass
class PositionSizingResult:
    """포지션 사이징 계산 결과 (§7.1)."""
    quantity: Decimal            # 주문 수량 (코인 단위, lot_size 반올림 후)
    margin_used: Decimal         # 필요 증거금 (USDT)
    position_value: Decimal      # 명목 포지션 가치 (margin × leverage)
    max_loss: Decimal            # 최대 손실 (USDT) = risk_amount
    max_profit: Decimal          # 최대 수익 (USDT) = max_loss × rr_ratio
    final_leverage: int          # 4중 상한 적용 후 최종 레버리지


@dataclass
class ValidationResult:
    """Risk Engine 검증 결과 — TRADING_RULES.md §11.2."""
    approved: bool

    # 거부 시
    rejection_reason: str | None = None
    rejection_code: str | None = None

    # 승인 시 — 주문 실행에 필요한 파라미터
    quantity: Decimal | None = None
    final_leverage: int | None = None
    margin_required_usdt: Decimal | None = None
    max_loss_usdt: Decimal | None = None
    max_profit_usdt: Decimal | None = None
    rr_ratio: Decimal | None = None

    # 특수 사전 처리 액션
    pre_action: Literal["close_existing", "dca"] | None = None
    existing_position_id: uuid.UUID | None = None

    # 경고 (거부 없이 주의 알림)
    warnings: list[str] = field(default_factory=list)

    # Decision-layer candidate 검증 요약 (legacy path 호환을 위해 선택 필드)
    failed_checks: list[str] = field(default_factory=list)
    risk_per_trade_pct: float = 0.0
    expected_net_profit: Decimal | None = None
    expected_net_loss: Decimal | None = None

    @classmethod
    def reject(cls, code: str, reason: str) -> "ValidationResult":
        return cls(
            approved=False,
            rejection_code=code,
            rejection_reason=reason,
            failed_checks=[code],
        )

    @classmethod
    def hold_signal(cls) -> "ValidationResult":
        return cls(approved=False, rejection_code="HOLD", rejection_reason="HOLD 시그널 — 실행 없음")

    @classmethod
    def system_error(cls, error: str) -> "ValidationResult":
        return cls(
            approved=False,
            rejection_code="SYSTEM_ERROR",
            rejection_reason=f"SYSTEM_ERROR: {error}",
        )


@dataclass
class HaltState:
    """거래 중단 상태."""
    is_halted: bool
    trigger: str | None = None     # HaltTrigger value
    reason: str | None = None
    until: str | None = None       # ISO 8601 또는 "manual_resume"
    is_global: bool = False        # 시스템 전체 Kill Switch


@dataclass
class OpenPosition:
    """Risk 검증에 필요한 오픈 포지션 정보."""
    id: uuid.UUID
    coin: str
    symbol: str
    direction: str             # "LONG" | "SHORT"
    entry_price: Decimal
    quantity: Decimal
    stop_loss: Decimal
    leverage: int
    dca_count: int = 0         # 현재까지 DCA 횟수
    original_risk_usdt: Decimal = Decimal("0")
