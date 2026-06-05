"""
RiskEngine — TRADING_RULES.md §11.2 완전 구현.

메인 엔트리포인트: RiskEngine.validate()
실패 기본값: 거부 (안전 우선 원칙)
예외 발생 시: 보수적으로 거부 (SYSTEM_ERROR)

검증 순서 (§11.1 플로우차트 엄수):
  0. Kill Switch / Halt 상태
  1. HOLD 시그널
  2. 자동매매 활성화
  3. stop_loss 존재 (절대 규칙)
  4. R:R 비율 ≥ 2.0
  5. 신뢰도 ≥ 60%
  6. 거래 허용 시간
  7. 일일 손실 한도
  8. 주간 손실 한도
  9. 연속 손실 쿨다운
  10. 동시 포지션 한도
  11. 동일 코인 포지션 (DCA / 반전)
  12. 잔고 충분성 + 포지션 사이징
  13. 포트폴리오 총 리스크
  14. 사이징 유효성 최종 검증
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import redis.asyncio as aioredis

from agents.risk.constants import (
    DAILY_LOSS_LIMIT_DEFAULTS,
    WEEKLY_LOSS_LIMIT_DEFAULTS,
)
from agents.risk.kill_switch import HaltTrigger, KillSwitch
from agents.risk.models import (
    AccountState,
    OpenPosition,
    PositionSizingResult,
    RawSignal,
    UserContext,
    ValidationResult,
)
from agents.risk.sizing import (
    calculate_position_size,
    resolve_final_leverage,
    validate_position_size,
)
from agents.risk.validators import (
    check_confidence,
    check_consecutive_losses,
    check_daily_loss_limit,
    check_kill_switch,
    check_not_hold,
    check_portfolio_risk,
    check_position_count_limit,
    check_rr_ratio,
    check_same_coin_position,
    check_stop_loss_exists,
    check_trading_active,
    check_trading_hours,
    check_weekly_loss_limit,
)

logger = logging.getLogger(__name__)


class RiskEngine:
    """
    Risk 검증 파이프라인 실행기.

    모든 데이터는 호출자가 미리 로드해서 전달한다.
    (DB 쿼리는 호출자 책임 — 이 클래스는 순수 검증 로직)
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis
        self._kill_switch = KillSwitch(redis)

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
    ) -> ValidationResult:
        """
        12단계 검증 파이프라인.
        한 단계라도 실패하면 즉시 거부 반환.
        """
        warnings: list[str] = []

        try:
            # ── CHECK 0: Kill Switch / Halt ──────────────────────────────────
            ok, reason = await check_kill_switch(ctx.user_id, self._redis)
            if not ok:
                return ValidationResult.reject("KILL_SWITCH", reason)

            # ── CHECK 1: HOLD 시그널 ─────────────────────────────────────────
            ok, reason = check_not_hold(signal)
            if not ok:
                return ValidationResult.hold_signal()

            # ── CHECK 2: 자동매매 활성화 ─────────────────────────────────────
            ok, reason = check_trading_active(ctx)
            if not ok:
                return ValidationResult.reject("TRADING_INACTIVE", reason)

            # ── CHECK 3: Stop Loss 존재 (절대 규칙) ──────────────────────────
            ok, reason = check_stop_loss_exists(signal)
            if not ok:
                return ValidationResult.reject("ORDER_003", reason)

            # ── CHECK 4: R:R 비율 ≥ 2.0 ─────────────────────────────────────
            ok, rr, reason = check_rr_ratio(signal)
            if not ok:
                return ValidationResult.reject("ORDER_004", reason)

            # ── CHECK 5: 신뢰도 ≥ 60% ────────────────────────────────────────
            ok, reason = check_confidence(signal)
            if not ok:
                return ValidationResult.reject("LOW_CONFIDENCE", reason)

            # ── CHECK 6: 거래 허용 시간 ──────────────────────────────────────
            ok, reason = check_trading_hours(ctx)
            if not ok:
                return ValidationResult.reject("TIME_RESTRICTION", reason)

            # ── CHECK 7: 일일 손실 한도 ──────────────────────────────────────
            daily_limit_pct = ctx.daily_loss_limit_pct
            daily_limit_usdt = account.total_balance * Decimal(str(daily_limit_pct))
            # 신규 거래 예상 손실 = risk_per_trade × balance
            projected_loss = account.total_balance * Decimal(str(ctx.risk_per_trade))

            ok, reason, warn_level = check_daily_loss_limit(
                daily_loss_usdt, daily_limit_usdt, projected_loss
            )
            if warn_level:
                warnings.append(f"DAILY_LOSS_{warn_level.upper()}: 일일 손실 한도 {warn_level}")
            if not ok:
                await self._kill_switch.halt_trading(
                    ctx.user_id, HaltTrigger.DAILY_LOSS_LIMIT,
                    f"일일 손실 ${daily_loss_usdt:.2f} / 한도 ${daily_limit_usdt:.2f}"
                )
                return ValidationResult.reject("ORDER_001", reason)

            # ── CHECK 8: 주간 손실 한도 ──────────────────────────────────────
            ok, reason = check_weekly_loss_limit(weekly_loss_usdt, weekly_limit_usdt)
            if not ok:
                await self._kill_switch.halt_trading(
                    ctx.user_id, HaltTrigger.WEEKLY_LOSS_LIMIT,
                    f"주간 손실 ${weekly_loss_usdt:.2f} / 한도 ${weekly_limit_usdt:.2f}"
                )
                return ValidationResult.reject("WEEKLY_LOSS", reason)

            # ── CHECK 9: 연속 손실 / 쿨다운 ─────────────────────────────────
            ok, reason = await check_consecutive_losses(
                ctx.user_id, consecutive_losses, self._redis
            )
            if not ok:
                if consecutive_losses >= 5:
                    await self._kill_switch.halt_trading(
                        ctx.user_id, HaltTrigger.CONSECUTIVE_LOSSES,
                        f"{consecutive_losses}연속 손실"
                    )
                return ValidationResult.reject("CONSEC_LOSS", reason)

            # ── CHECK 10: 동시 포지션 한도 ──────────────────────────────────
            ok, reason = check_position_count_limit(open_positions_count, ctx)
            position_pre_action: str | None = None
            existing_pos_id: uuid.UUID | None = None

            if not ok:
                # 한도 초과여도 동일 코인 처리가 있을 수 있음 → 계속 진행
                # 동일 코인 포지션이 한도 원인이면 아래 CHECK 11에서 처리
                if same_coin_position is None:
                    return ValidationResult.reject("ORDER_002", reason)

            # ── CHECK 11: 동일 코인 포지션 ──────────────────────────────────
            can_proceed, coin_reason, pre_action = check_same_coin_position(
                signal, same_coin_position
            )
            if not can_proceed:
                return ValidationResult.reject("POSITION_CONFLICT", coin_reason)

            if pre_action:
                position_pre_action = pre_action
                existing_pos_id = same_coin_position.id if same_coin_position else None

                if pre_action == "dca":
                    warnings.append(f"DCA: {signal.coin} 기존 포지션에 DCA 추가 진입")
                elif pre_action == "close_existing":
                    warnings.append(f"REVERSE: {signal.coin} 기존 포지션 청산 후 반전 진입")

            # ── CHECK 12: 포지션 사이징 계산 ────────────────────────────────
            final_leverage = resolve_final_leverage(
                ai_recommended=signal.leverage,
                user_max=ctx.max_leverage,
                plan=ctx.plan,
            )
            if final_leverage != signal.leverage:
                warnings.append(
                    f"LEVERAGE_CAPPED: AI 추천 {signal.leverage}x → 최종 {final_leverage}x"
                )

            sizing = calculate_position_size(
                account_balance=account.available_balance,
                risk_per_trade=ctx.risk_per_trade,
                entry_price=signal.entry_price,
                stop_loss_price=signal.stop_loss,  # type: ignore[arg-type]
                leverage=final_leverage,
                take_profit_price=signal.take_profit,
                symbol=signal.symbol,
            )

            size_ok, size_reason = validate_position_size(
                sizing, account.available_balance, signal.entry_price, signal.symbol
            )
            if not size_ok:
                return ValidationResult.reject("SIZING", size_reason)

            # ── CHECK 13: 포트폴리오 총 리스크 ──────────────────────────────
            ok, reason = check_portfolio_risk(account, sizing.max_loss, ctx.risk_profile)
            if not ok:
                return ValidationResult.reject("PORTFOLIO_RISK", reason)

            # ── 모든 검증 통과 ───────────────────────────────────────────────
            logger.info(
                "Risk validation APPROVED user_id=%s signal=%s/%s "
                "qty=%s leverage=%dx margin=$%s max_loss=$%s rr=%.2f",
                ctx.user_id, signal.coin, signal.direction,
                sizing.quantity, final_leverage, sizing.margin_used,
                sizing.max_loss, rr,
            )

            return ValidationResult(
                approved=True,
                quantity=sizing.quantity,
                final_leverage=final_leverage,
                margin_required_usdt=sizing.margin_used,
                max_loss_usdt=sizing.max_loss,
                max_profit_usdt=sizing.max_profit,
                rr_ratio=rr,
                pre_action=position_pre_action,          # type: ignore[arg-type]
                existing_position_id=existing_pos_id,
                warnings=warnings,
            )

        except Exception as exc:
            # 예외 발생 시 항상 거부 (안전 우선)
            logger.error(
                "Risk validation SYSTEM_ERROR user_id=%s error=%s",
                ctx.user_id, exc, exc_info=True,
            )
            return ValidationResult.system_error(type(exc).__name__)

    # ── Kill Switch 접근자 (편의 메서드) ──────────────────────────────────────

    async def activate_kill_switch(
        self, user_id: uuid.UUID, reason: str
    ) -> None:
        """즉각 거래 중단 (별도 승인 없이 호출 가능)."""
        await self._kill_switch.emergency_stop(
            user_id, reason, HaltTrigger.MANUAL
        )
        logger.warning("Kill switch activated by operator user_id=%s reason=%s", user_id, reason)

    async def deactivate_kill_switch(self, user_id: uuid.UUID) -> None:
        await self._kill_switch.resume_trading(user_id)

    async def get_halt_state(self, user_id: uuid.UUID):
        return await self._kill_switch.get_halt_state(user_id)

    async def activate_global_kill_switch(self, reason: str) -> None:
        await self._kill_switch.activate_global(reason)

    async def deactivate_global_kill_switch(self) -> None:
        await self._kill_switch.deactivate_global()
