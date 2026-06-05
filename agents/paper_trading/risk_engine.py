"""
PaperRiskEngine — TRADING_RULES.md §11.2 in-memory 구현.

기존 agents/risk/validators.py의 순수 함수를 최대한 재활용한다.
Redis 의존 함수(check_kill_switch, check_consecutive_losses)는
PaperAccountState의 in-memory 상태로 대체한다.

검증 순서 (§11.1 플로우차트 엄수):
  0. Halt / Kill Switch (in-memory)
  1. HOLD 시그널
  2. 자동매매 활성화
  3. stop_loss 존재
  4. R:R ≥ 2.0
  5. 신뢰도 ≥ 60%
  6. 거래 허용 시간
  7. 일일 손실 한도
  8. 주간 손실 한도
  9. 연속 손실 / 쿨다운
  10. 동시 포지션 한도
  11. 동일 코인 포지션
  12. 포지션 사이징 계산 + 유효성
  13. 포트폴리오 총 리스크
"""
from __future__ import annotations

import logging
from decimal import Decimal

from agents.risk.constants import (
    CONSECUTIVE_LOSS_COOLDOWN,
    CONSECUTIVE_LOSS_HALT,
    COOLDOWN_MINUTES,
    DAILY_LOSS_LIMIT_DEFAULTS,
    WEEKLY_LOSS_LIMIT_DEFAULTS,
)
from agents.risk.models import (
    AccountState,
    OpenPosition,
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
    check_daily_loss_limit,
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
from agents.paper_trading.models import PaperUserSettings
from agents.paper_trading.state import PaperAccountState

logger = logging.getLogger(__name__)


class PaperRiskEngine:
    """
    동기 Risk Engine — Redis 없이 in-memory 상태로 동작.

    agents/risk/engine.py의 async RiskEngine과 동일한 12단계 로직을
    동기(sync)로 구현한다. Paper trading 용도 전용.
    """

    def validate(
        self,
        signal: RawSignal,
        settings: PaperUserSettings,
        account: PaperAccountState,
    ) -> ValidationResult:
        """
        시그널 검증 파이프라인.
        한 단계라도 실패하면 즉시 거부.
        실패 기본값: 거부 (안전 우선).
        """
        warnings: list[str] = []

        try:
            # ── CHECK 0: Halt / Kill Switch (in-memory) ──────────────────────
            if account.is_halted:
                return ValidationResult.reject("KILL_SWITCH", f"KILL_SWITCH: {account.halt_reason}")

            # ── CHECK 1: HOLD 시그널 ──────────────────────────────────────────
            ok, reason = check_not_hold(signal)
            if not ok:
                return ValidationResult.hold_signal()

            # ── CHECK 2: 자동매매 활성화 ──────────────────────────────────────
            ctx = self._build_ctx(settings)
            ok, reason = check_trading_active(ctx)
            if not ok:
                return ValidationResult.reject("TRADING_INACTIVE", reason)

            # ── CHECK 3: Stop Loss 존재 ───────────────────────────────────────
            ok, reason = check_stop_loss_exists(signal)
            if not ok:
                return ValidationResult.reject("ORDER_003", reason)

            # ── CHECK 4: R:R ≥ 2.0 ───────────────────────────────────────────
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
            acc_state = self._build_account_state(account)
            daily_limit_pct = settings.daily_loss_limit_pct
            daily_limit_usdt = acc_state.total_balance * Decimal(str(daily_limit_pct))
            projected_loss = acc_state.total_balance * Decimal(str(settings.risk_per_trade))

            ok, reason, warn_level = check_daily_loss_limit(
                account.daily_loss_usdt, daily_limit_usdt, projected_loss
            )
            if warn_level:
                warnings.append(f"DAILY_LOSS_{warn_level.upper()}")
            if not ok:
                account.halt(f"일일 손실 ${account.daily_loss_usdt:.2f} / 한도 ${daily_limit_usdt:.2f}")
                return ValidationResult.reject("ORDER_001", reason)

            # ── CHECK 8: 주간 손실 한도 ──────────────────────────────────────
            weekly_limit_usdt = acc_state.total_balance * Decimal(str(settings.weekly_loss_limit_pct))
            ok, reason = check_weekly_loss_limit(account.weekly_loss_usdt, weekly_limit_usdt)
            if not ok:
                account.halt(f"주간 손실 ${account.weekly_loss_usdt:.2f} / 한도 ${weekly_limit_usdt:.2f}")
                return ValidationResult.reject("WEEKLY_LOSS", reason)

            # ── CHECK 9: 연속 손실 / 쿨다운 (in-memory) ──────────────────────
            if account.in_cooldown:
                remaining = int(
                    (account.cooldown_until - __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    )).total_seconds() / 60
                )
                return ValidationResult.reject(
                    "CONSEC_LOSS",
                    f"COOLDOWN: {remaining}분 후 재개 ({account.cooldown_until.isoformat()})"
                )

            consecutive = account.consecutive_losses
            if consecutive >= CONSECUTIVE_LOSS_HALT:
                account.halt(f"{consecutive}연속 손실 — 수동 재활성화 필요")
                return ValidationResult.reject(
                    "CONSEC_LOSS",
                    f"CONSEC_LOSS: {consecutive}연속 손실 — 수동 재활성화 필요"
                )
            if consecutive >= CONSECUTIVE_LOSS_COOLDOWN:
                account.set_cooldown(COOLDOWN_MINUTES)
                return ValidationResult.reject(
                    "CONSEC_LOSS",
                    f"CONSEC_LOSS: {consecutive}연속 손실 — {COOLDOWN_MINUTES}분 쿨다운"
                )

            # ── CHECK 10: 동시 포지션 한도 ───────────────────────────────────
            ok, reason = check_position_count_limit(account.open_positions_count, ctx)

            # 동일 코인 포지션 조회
            same_coin_pos = account.get_open_by_coin(signal.coin)
            existing_open_pos: OpenPosition | None = None
            if same_coin_pos:
                existing_open_pos = OpenPosition(
                    id=__import__("uuid").UUID(same_coin_pos.id) if len(same_coin_pos.id) == 36 else __import__("uuid").uuid4(),
                    coin=same_coin_pos.coin,
                    symbol=same_coin_pos.symbol,
                    direction=same_coin_pos.direction,
                    entry_price=same_coin_pos.entry_price,
                    quantity=same_coin_pos.quantity,
                    stop_loss=same_coin_pos.stop_loss,
                    leverage=same_coin_pos.leverage,
                    dca_count=same_coin_pos.dca_count,
                    original_risk_usdt=same_coin_pos.original_risk_usdt,
                )

            if not ok:
                if same_coin_pos is None:
                    return ValidationResult.reject("ORDER_002", reason)

            # ── CHECK 11: 동일 코인 포지션 ───────────────────────────────────
            can_proceed, coin_reason, pre_action = check_same_coin_position(
                signal, existing_open_pos
            )
            if not can_proceed:
                return ValidationResult.reject("POSITION_CONFLICT", coin_reason)

            position_pre_action = pre_action
            existing_pos_id = existing_open_pos.id if existing_open_pos else None
            if pre_action == "dca":
                warnings.append(f"DCA: {signal.coin} 기존 포지션에 DCA 추가")
            elif pre_action == "close_existing":
                warnings.append(f"REVERSE: {signal.coin} 기존 포지션 청산 후 반전")

            # ── CHECK 12: 포지션 사이징 ──────────────────────────────────────
            final_leverage = resolve_final_leverage(
                ai_recommended=signal.leverage,
                user_max=settings.max_leverage,
                plan=settings.plan,
            )
            if final_leverage != signal.leverage:
                warnings.append(f"LEVERAGE_CAPPED: {signal.leverage}x → {final_leverage}x")

            sizing = calculate_position_size(
                account_balance=acc_state.available_balance,
                risk_per_trade=settings.risk_per_trade,
                entry_price=signal.entry_price,
                stop_loss_price=signal.stop_loss,  # type: ignore[arg-type]
                leverage=final_leverage,
                take_profit_price=signal.take_profit,
                symbol=signal.symbol,
            )

            size_ok, size_reason = validate_position_size(
                sizing, acc_state.available_balance, signal.entry_price, signal.symbol
            )
            if not size_ok:
                return ValidationResult.reject("SIZING", size_reason)

            # ── CHECK 13: 포트폴리오 총 리스크 ──────────────────────────────
            ok, reason = check_portfolio_risk(acc_state, sizing.max_loss, settings.risk_profile)
            if not ok:
                return ValidationResult.reject("PORTFOLIO_RISK", reason)

            # ── 모든 검증 통과 ───────────────────────────────────────────────
            logger.info(
                "Paper Risk APPROVED user=%s %s/%s qty=%s lev=%dx margin=$%s",
                settings.user_id, signal.coin, signal.direction,
                sizing.quantity, final_leverage, sizing.margin_used,
            )

            return ValidationResult(
                approved=True,
                quantity=sizing.quantity,
                final_leverage=final_leverage,
                margin_required_usdt=sizing.margin_used,
                max_loss_usdt=sizing.max_loss,
                max_profit_usdt=sizing.max_profit,
                rr_ratio=rr,
                pre_action=position_pre_action,  # type: ignore[arg-type]
                existing_position_id=existing_pos_id,
                warnings=warnings,
            )

        except Exception as exc:
            logger.error("Paper Risk SYSTEM_ERROR: %s", exc, exc_info=True)
            return ValidationResult.system_error(type(exc).__name__)

    # ── 내부 빌더 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_ctx(settings: PaperUserSettings) -> UserContext:
        return UserContext(
            user_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000000"),
            plan=settings.plan,
            risk_profile=settings.risk_profile,
            risk_per_trade=settings.risk_per_trade,
            max_leverage=settings.max_leverage,
            max_concurrent_positions=settings.max_concurrent_positions,
            daily_loss_limit_pct=settings.daily_loss_limit_pct,
            is_trading_active=settings.is_trading_active,
            allowed_hours_start=settings.allowed_hours_start,
            allowed_hours_end=settings.allowed_hours_end,
        )

    @staticmethod
    def _build_account_state(account: PaperAccountState) -> AccountState:
        return AccountState(
            available_balance=account.available_balance,
            total_balance=account.balance,
            initial_balance=account.initial_balance,
            open_positions_count=account.open_positions_count,
            open_positions_risk_usdt=account.open_positions_risk_usdt,
        )
