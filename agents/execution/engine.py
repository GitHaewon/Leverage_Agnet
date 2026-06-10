"""
ExecutionEngine — Signal → Risk Validation → Position Sizing → Order Execution.

핵심 규칙:
  1. Risk Engine 승인 없이는 주문 절대 금지 (AGENTS.md §7, CLAUDE.md 절대 규칙)
  2. LIVE_TRADING_ENABLED=false 기본값 — 실수로 실거래 실행 방지
  3. SafetyGate 거부 시 절대 주문 금지 (손실 한도 / 비상 중단 / 연결 오류)
  4. entry 체결 후 TP/SL 실패 시 tp_sl_failed=True 반환 (호출자가 긴급 청산)
  5. 예외 발생 시 항상 거부 (안전 우선 원칙)

파이프라인:
  Signal
    → RiskValidatorProtocol.validate()   (HOLD / SL / R:R / 손실 한도 / 사이징 등)
    → LIVE_TRADING_ENABLED gate          (paper 모드 → 여기서 종료)
    → SafetyGateProtocol.check_order_allowed()  (live 전용 최종 안전 게이트)
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
    SafetyGateProtocol,
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


def build_emergency_close_ticket(signal: RawSignal, quantity: "Decimal") -> OrderTicket:
    """
    긴급 청산 주문 — 시장가, reduce_only=True.

    TP/SL 재시도까지 실패 시 미보호 포지션을 즉시 청산하기 위해 사용한다.
    """
    from decimal import Decimal as _Decimal
    return OrderTicket(
        symbol=signal.symbol,
        side=_CLOSE_SIDE[signal.direction],
        order_type="MARKET",
        quantity=quantity,
        price=signal.entry_price,   # 참조가 (시장가 주문이므로 실제 체결가와 다를 수 있음)
        reduce_only=True,
        purpose="emergency_close",
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
        safety_gate: SafetyGateProtocol | None = None,
    ) -> None:
        # live_trading_enabled=True인데 mode가 paper이면 설정 오류
        if live_trading_enabled and mode == "paper":
            raise ValueError(
                "live_trading_enabled=True이면 mode는 'testnet' 또는 'live'여야 합니다."
            )
        # live 모드인데 safety_gate 없으면 경고 (주문이 Safety Layer를 우회하게 됨)
        if live_trading_enabled and safety_gate is None:
            logger.warning(
                "ExecutionEngine: live_trading_enabled=True but safety_gate is None. "
                "Orders will bypass SafetyGate — configure SafetyGateAdapter."
            )
        self._validator = risk_validator
        self._gateway = gateway
        self._live = live_trading_enabled
        self._mode: Literal["paper", "testnet", "live"] = mode
        self._safety_gate = safety_gate

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

            # ── STEP 2.5: SafetyGate 최종 확인 ──────────────────────────────
            # live 모드 전용. paper 모드는 STEP 2에서 이미 return되어 여기 도달 불가.
            # SafetyGate 거부 시 절대 주문 금지 — gateway.place_order() 호출 불가.
            if self._safety_gate is not None:
                safety = await self._safety_gate.check_order_allowed(
                    req.user_ctx.user_id
                )
                if not safety.allowed:
                    logger.warning(
                        "SafetyGate blocked order user_id=%s code=%s msg=%s",
                        req.user_ctx.user_id,
                        safety.rejection_code,
                        safety.message,
                    )
                    return ExecutionResult(
                        approved=False,
                        executed=False,
                        mode=self._mode,
                        rejection_code=safety.rejection_code or "SAFETY_GATE_BLOCKED",
                        rejection_reason=safety.message or "SafetyGate blocked this order",
                    )

            # ── STEP 3: 주문 실행 (entry → TP → SL) ──────────────────────────
            entry_ticket = build_entry_ticket(req.signal, validation)
            entry_filled: FilledOrder = await self._gateway.place_order(entry_ticket)

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

            # ── STEP 3a: TP/SL 실패 → 재시도 1회 → 긴급 청산 ──────────────
            if tp_sl_failed:
                logger.warning(
                    "TP/SL failed, retrying once user_id=%s entry_id=%s",
                    req.user_ctx.user_id, entry_filled.exchange_order_id,
                )
                try:
                    if tp_filled is None:
                        tp_filled = await self._gateway.place_order(
                            build_tp_ticket(req.signal, validation)
                        )
                    if sl_filled is None:
                        sl_filled = await self._gateway.place_order(
                            build_sl_ticket(req.signal, validation)
                        )
                    tp_sl_failed = False
                    logger.info(
                        "TP/SL retry succeeded user_id=%s entry_id=%s",
                        req.user_ctx.user_id, entry_filled.exchange_order_id,
                    )
                except Exception as retry_exc:
                    # 재시도도 실패 → 미보호 포지션 → 긴급 청산 필수
                    logger.error(
                        "TP/SL retry failed, initiating emergency close "
                        "user_id=%s entry_id=%s error=%s",
                        req.user_ctx.user_id,
                        entry_filled.exchange_order_id,
                        retry_exc,
                        exc_info=True,
                    )
                    emergency_order: FilledOrder | None = None
                    emergency_failed = False
                    try:
                        close_ticket = build_emergency_close_ticket(
                            req.signal, entry_filled.quantity
                        )
                        emergency_order = await self._gateway.place_order(close_ticket)
                        logger.warning(
                            "Emergency close executed user_id=%s "
                            "entry_id=%s close_id=%s",
                            req.user_ctx.user_id,
                            entry_filled.exchange_order_id,
                            emergency_order.exchange_order_id,
                        )
                    except Exception as emergency_exc:
                        emergency_failed = True
                        logger.critical(
                            "EMERGENCY_CLOSE_FAILED "
                            "user_id=%s entry_id=%s error=%s "
                            "— MANUAL INTERVENTION REQUIRED",
                            req.user_ctx.user_id,
                            entry_filled.exchange_order_id,
                            emergency_exc,
                            exc_info=True,
                        )

                    return ExecutionResult(
                        approved=True,
                        executed=True,
                        mode=self._mode,
                        validation=validation,
                        entry_order=entry_filled,
                        tp_sl_failed=True,
                        emergency_close_order=emergency_order,
                        emergency_close_failed=emergency_failed,
                        warnings=list(validation.warnings),
                    )

            logger.info(
                "Execution completed user_id=%s mode=%s "
                "entry_id=%s qty=%s price=%s",
                req.user_ctx.user_id, self._mode,
                entry_filled.exchange_order_id,
                entry_filled.quantity, entry_filled.avg_fill_price,
            )

            return ExecutionResult(
                approved=True,
                executed=True,
                mode=self._mode,
                validation=validation,
                entry_order=entry_filled,
                tp_order=tp_filled,
                sl_order=sl_filled,
                tp_sl_failed=False,
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
