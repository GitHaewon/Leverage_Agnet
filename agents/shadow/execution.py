"""
Shadow Trading 실행 엔진.

기존 ExecutionProvider 프로토콜을 구현한다.
OrchestratorDeps.execution = ShadowExecutionEngine(...) 으로 주입하면
파이프라인 코드 변경 없이 shadow 모드로 동작한다.

실행 순서:
  1. approved_validation 확인 또는 RiskValidatorProtocol.validate()
  2. Virtual FilledOrder 생성          — entry_price로 즉시 체결 가정 (API 없음)
  3. ShadowTradeRecord 저장            — store.save() 호출
  4. ExecutionResult(mode="paper") 반환
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from agents.execution.models import (
    ExecutionRequest,
    ExecutionResult,
    FilledOrder,
    RiskValidatorProtocol,
)
from agents.shadow.models import ShadowTradeRecord

logger = logging.getLogger(__name__)

_ENTRY_SIDE: dict[str, str] = {"LONG": "BUY",  "SHORT": "SELL"}
_CLOSE_SIDE: dict[str, str] = {"LONG": "SELL", "SHORT": "BUY"}


def _direction(signal: object) -> str:
    if hasattr(signal, "direction"):
        return str(getattr(signal, "direction"))
    action = getattr(signal, "action", "")
    return str(getattr(action, "value", action))


class ShadowTradeStoreProtocol(Protocol):
    """ShadowTradeRecord 저장소 인터페이스.

    프로덕션: ShadowTradeRepository (SQLAlchemy AsyncSession 래핑)
    테스트:   InMemoryShadowStore
    """
    async def save(self, record: ShadowTradeRecord) -> None: ...


class ShadowExecutionEngine:
    """
    Shadow Trading 실행 엔진.

    실제 Binance API를 호출하지 않으며, Risk 검증은 실거래와 동일하게 수행한다.
    """

    def __init__(
        self,
        risk_validator: RiskValidatorProtocol,
        store: ShadowTradeStoreProtocol,
    ) -> None:
        self._validator = risk_validator
        self._store = store

    async def execute(self, req: ExecutionRequest) -> ExecutionResult:
        try:
            # ── STEP 1: Risk Validation 확인 ────────────────────────────────
            if req.approved_validation is not None:
                validation = req.approved_validation
                signal = req.candidate or req.signal
            else:
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
                signal = req.signal

            if not validation.approved:
                return ExecutionResult(
                    approved=False,
                    executed=False,
                    mode="paper",
                    rejection_code=validation.rejection_code,
                    rejection_reason=validation.rejection_reason,
                    validation=validation,
                )

            if req.approved_validation is not None:
                if req.final_decision is None or req.candidate is None:
                    return ExecutionResult(
                        approved=False,
                        executed=False,
                        mode="paper",
                        rejection_code="FINAL_DECISION_MISSING",
                        rejection_reason="FinalDecision and TradeCandidate are required",
                        validation=validation,
                    )

            direction = _direction(signal)
            if direction not in ("LONG", "SHORT"):
                return ExecutionResult(
                    approved=False,
                    executed=False,
                    mode="paper",
                    rejection_code="INVALID_DIRECTION",
                    rejection_reason="Execution direction must be LONG or SHORT",
                    validation=validation,
                )
            if getattr(signal, "stop_loss", None) is None:
                return ExecutionResult(
                    approved=False,
                    executed=False,
                    mode="paper",
                    rejection_code="ORDER_003",
                    rejection_reason="stop_loss is required before shadow execution",
                    validation=validation,
                )
            if getattr(signal, "take_profit", None) is None:
                return ExecutionResult(
                    approved=False,
                    executed=False,
                    mode="paper",
                    rejection_code="TAKE_PROFIT_MISSING",
                    rejection_reason="take_profit is required before shadow execution",
                    validation=validation,
                )

            # ── STEP 2: Virtual Fill ─────────────────────────────────────────
            now = datetime.now(timezone.utc)
            qty = validation.quantity
            entry_px: Decimal = signal.entry_price
            tp_px: Decimal = signal.take_profit
            sl_px: Decimal = signal.stop_loss

            record = ShadowTradeRecord.open(
                user_id=str(req.user_ctx.user_id),
                coin=signal.coin,
                symbol=signal.symbol,
                direction=direction,
                entry_price=entry_px,
                tp_price=tp_px,
                sl_price=sl_px,
                quantity=qty,
                leverage=validation.final_leverage,
                opened_at=now,
            )

            # ── STEP 3: Persist ──────────────────────────────────────────────
            await self._store.save(record)

            logger.info(
                "shadow_trade_opened id=%s user=%s %s/%s "
                "entry=%s tp=%s sl=%s qty=%s lev=%dx",
                record.id, req.user_ctx.user_id,
                signal.coin, direction,
                entry_px, tp_px, sl_px, qty, validation.final_leverage,
            )

            def _fill(purpose: str, side: str, order_type: str, price: Decimal) -> FilledOrder:
                return FilledOrder(
                    exchange_order_id=f"shadow-{purpose}-{record.id}",
                    symbol=signal.symbol,
                    purpose=purpose,  # type: ignore[arg-type]
                    side=side,
                    order_type=order_type,
                    quantity=qty,
                    avg_fill_price=price,
                    fee_usdt=Decimal("0"),
                    filled_at=now,
                )

            return ExecutionResult(
                approved=True,
                executed=True,
                mode="paper",
                validation=validation,
                entry_order=_fill(
                    "entry",
                    _ENTRY_SIDE[direction],
                    "MARKET",
                    entry_px,
                ),
                tp_order=_fill(
                    "take_profit",
                    _CLOSE_SIDE[direction],
                    "TAKE_PROFIT_MARKET",
                    tp_px,
                ),
                sl_order=_fill(
                    "stop_loss",
                    _CLOSE_SIDE[direction],
                    "STOP_MARKET",
                    sl_px,
                ),
                warnings=list(validation.warnings),
            )

        except Exception as exc:
            logger.error("ShadowExecutionEngine error: %s", exc, exc_info=True)
            return ExecutionResult(
                approved=False,
                executed=False,
                mode="paper",
                rejection_code="SYSTEM_ERROR",
                rejection_reason=f"SYSTEM_ERROR: {type(exc).__name__}",
            )
