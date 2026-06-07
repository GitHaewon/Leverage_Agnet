"""
ExecutionEngine — Signal → Risk Validation → Position Sizing → Order Execution.

핵심 규칙:
  1. Risk Engine 승인 없이는 주문 절대 금지 (AGENTS.md §7, CLAUDE.md 절대 규칙)
  2. LIVE_TRADING_ENABLED=false 기본값 — 실수로 실거래 실행 방지
  3. entry 체결 후 TP/SL 실패 시 tp_sl_failed=True 반환 (호출자가 긴급 청산)
  4. 예외 발생 시 항상 거부 (안전 우선 원칙)

파이프라인:
  Signal
    → RiskValidatorProtocol.validate()   (HOLD / SL / R:R / 손실 한도 / 사이징 등)
    → LIVE_TRADING_ENABLED gate
    → gateway.place_order(entry)
    → gateway.place_order(take_profit)
    → gateway.place_order(stop_loss)
"""
from __future__ import annotations

import logging
from typing import Literal

from agents.execution.models import (
    ExecutionRequest,
    ExecutionResult,
    FilledOrder,
    OrderGatewayProtocol,
    OrderTicket,
    RiskValidatorProtocol,
)
from agents.risk.models import RawSignal, ValidationResult

logger = logging.getLogger(__name__)

# LONG → BUY (진입), SHORT → SELL (진입)
_ENTRY_SIDE: dict[str, str] = {"LONG": "BUY", "SHORT": "SELL"}
# LONG → SELL (청산), SHORT → BUY (청산)
_CLOSE_SIDE: dict[str, str] = {"LONG": "SELL", "SHORT": "BUY"}


# ── 티켓 빌더 ────────────────────────────────────────────────────────────────────

def build_entry_ticket(signal: RawSignal, validation: ValidationResult) -> OrderTicket:
    """시장가 진입 주문 — reduce_only=False."""
    return OrderTicket(
        symbol=signal.symbol,
        side=_ENTRY_SIDE[signal.direction],
        order_type="MARKET",
        quantity=validation.quantity,   # type: ignore[arg-type]
        price=signal.entry_price,
        reduce_only=False,
        purpose="entry",
    )


def build_tp_ticket(signal: RawSignal, validation: ValidationResult) -> OrderTicket:
    """
    TP(Take Profit) 주문 — reduce_only=True.
    LONG: SELL / SHORT: BUY
    """
    return OrderTicket(
        symbol=signal.symbol,
        side=_CLOSE_SIDE[signal.direction],
        order_type="TAKE_PROFIT_MARKET",
        quantity=validation.quantity,   # type: ignore[arg-type]
        price=signal.take_profit,       # type: ignore[arg-type]
        reduce_only=True,
        purpose="take_profit",
    )


def build_sl_ticket(signal: RawSignal, validation: ValidationResult) -> OrderTicket:
    """
    SL(Stop Loss) 주문 — reduce_only=True.
    LONG: SELL / SHORT: BUY
    """
    return OrderTicket(
        symbol=signal.symbol,
        side=_CLOSE_SIDE[signal.direction],
        order_type="STOP_MARKET",
        quantity=validation.quantity,   # type: ignore[arg-type]
        price=signal.stop_loss,         # type: ignore[arg-type]
        reduce_only=True,
        purpose="stop_loss",
    )


# ── 실행 엔진 ─────────────────────────────────────────────────────────────────────

class ExecutionEngine:
    """
    완전한 실행 파이프라인.

    live_trading_enabled=False (기본값):
      Risk 검증까지만 수행. 실제 주문 없음 (paper 모드).
      검증 결과(ValidationResult)는 항상 반환 → 시뮬레이션 / 드라이런 가능.

    live_trading_enabled=True:
      Risk 승인 후 gateway로 실제 주문 실행 (testnet 또는 live).
    """

    def __init__(
        self,
        risk_validator: RiskValidatorProtocol,
        gateway: OrderGatewayProtocol,
        live_trading_enabled: bool = False,
        mode: Literal["paper", "testnet", "live"] = "paper",
    ) -> None:
        # live_trading_enabled=True인데 mode가 paper이면 설정 오류
        if live_trading_enabled and mode == "paper":
            raise ValueError(
                "live_trading_enabled=True이면 mode는 'testnet' 또는 'live'여야 합니다."
            )
        self._validator = risk_validator
        self._gateway = gateway
        self._live = live_trading_enabled
        self._mode: Literal["paper", "testnet", "live"] = mode

    async def execute(self, req: ExecutionRequest) -> ExecutionResult:
        """
        실행 파이프라인.

        Returns:
          approved=False  → Risk 검증 실패 (rejection_code / rejection_reason 참고)
          approved=True, executed=False → LIVE_TRADING_ENABLED=false (paper 모드)
          approved=True, executed=True  → 주문 체결 완료
        """
        try:
            # ── STEP 1: Risk Validation ─────────────────────────────────────
            validation = await self._validator.validate(
                signal=req.signal,
                ctx=req.user_ctx,
                account=req.account,
                daily_loss_usdt=req.daily_loss_usdt,
                weekly_loss_usdt=req.weekly_loss_usdt,
                weekly_limit_usdt=req.weekly_limit_usdt,
                consecutive_losses=req.consecutive_losses,
                open_positions_count=req.open_positions_count,
                same_coin_position=req.same_coin_position,
            )

            if not validation.approved:
                logger.info(
                    "Execution rejected user_id=%s code=%s reason=%s",
                    req.user_ctx.user_id,
                    validation.rejection_code,
                    validation.rejection_reason,
                )
                return ExecutionResult(
                    approved=False,
                    executed=False,
                    mode=self._mode,
                    rejection_code=validation.rejection_code,
                    rejection_reason=validation.rejection_reason,
                    validation=validation,
                )

            # ── STEP 2: LIVE_TRADING gate ────────────────────────────────────
            # LIVE_TRADING_ENABLED=false → 검증은 통과했지만 실제 주문 없음
            if not self._live:
                logger.info(
                    "Execution approved but LIVE_TRADING_ENABLED=false "
                    "user_id=%s signal=%s/%s qty=%s lev=%dx",
                    req.user_ctx.user_id,
                    req.signal.coin, req.signal.direction,
                    validation.quantity, validation.final_leverage,
                )
                return ExecutionResult(
                    approved=True,
                    executed=False,
                    mode="paper",
                    validation=validation,
                    warnings=list(validation.warnings),
                )

            # ── STEP 3: 주문 실행 (entry → TP → SL) ──────────────────────────
            entry_ticket = build_entry_ticket(req.signal, validation)
            entry_filled: FilledOrder = await self._gateway.place_order(entry_ticket)

            # entry 체결 후 TP/SL 실패 시 tp_sl_failed=True 반환
            # 호출자(Application Layer)가 긴급 청산 처리 책임
            tp_filled: FilledOrder | None = None
            sl_filled: FilledOrder | None = None
            tp_sl_failed = False

            try:
                tp_filled = await self._gateway.place_order(
                    build_tp_ticket(req.signal, validation)
                )
                sl_filled = await self._gateway.place_order(
                    build_sl_ticket(req.signal, validation)
                )
            except Exception as tp_sl_exc:
                logger.error(
                    "TP/SL order failed after entry "
                    "user_id=%s entry_id=%s error=%s",
                    req.user_ctx.user_id,
                    entry_filled.exchange_order_id,
                    tp_sl_exc,
                    exc_info=True,
                )
                tp_sl_failed = True

            logger.info(
                "Execution completed user_id=%s mode=%s "
                "entry_id=%s qty=%s price=%s tp_sl_failed=%s",
                req.user_ctx.user_id, self._mode,
                entry_filled.exchange_order_id,
                entry_filled.quantity, entry_filled.avg_fill_price,
                tp_sl_failed,
            )

            return ExecutionResult(
                approved=True,
                executed=True,
                mode=self._mode,
                validation=validation,
                entry_order=entry_filled,
                tp_order=tp_filled,
                sl_order=sl_filled,
                tp_sl_failed=tp_sl_failed,
                warnings=list(validation.warnings),
            )

        except Exception as exc:
            # 예외 발생 시 항상 거부 (안전 우선 원칙)
            logger.error(
                "ExecutionEngine SYSTEM_ERROR user_id=%s error=%s",
                req.user_ctx.user_id, exc, exc_info=True,
            )
            return ExecutionResult(
                approved=False,
                executed=False,
                mode=self._mode,
                rejection_code="SYSTEM_ERROR",
                rejection_reason=f"SYSTEM_ERROR: {type(exc).__name__}",
            )
