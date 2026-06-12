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

from agents.decision.constants import (
    ALLOW_AVERAGING_DOWN,
    ALLOW_MARTINGALE,
    BLOCK_AFTER_FUNDING_MINUTES,
    BLOCK_BEFORE_FUNDING_MINUTES,
    DECISION_MAX_ENTRY_MARGIN_RATIO,
    DECISION_MAX_LEVERAGE,
    DECISION_MAX_SLIPPAGE_BPS,
    GLOBAL_MIN_RISK_REWARD_RATIO,
    HIGH_VOLATILITY_BLOCK,
    ISOLATED_MARGIN_ONLY,
    MIN_EXPECTED_NET_PROFIT_PCT,
    MARGIN_MODE,
    NEWS_EVENT_BLOCK,
    STRATEGY_THRESHOLDS,
)
from agents.decision.models import (
    FinalAction,
    MarketRegime,
    MarketRegimeResult,
    StrategyType,
    TradeCandidate,
)
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


def _cfg(config: object | None, key: str, default: object) -> object:
    if config is None:
        return default
    if isinstance(config, dict):
        decision = config.get("decision")
        if isinstance(decision, dict) and key in decision:
            return decision[key]
        return config.get(key, default)
    decision = getattr(config, "decision", None)
    if decision is not None and hasattr(decision, key):
        return getattr(decision, key)
    return getattr(config, key, default)


def _as_regime(value: object | None) -> MarketRegime:
    if isinstance(value, MarketRegimeResult):
        return value.regime
    if isinstance(value, MarketRegime):
        return value
    if value is None:
        return MarketRegime.UNKNOWN
    try:
        return MarketRegime(str(value))
    except ValueError:
        return MarketRegime.UNKNOWN


def _candidate_direction(candidate: TradeCandidate) -> str:
    return "LONG" if candidate.action == FinalAction.LONG else "SHORT"


def _reject_candidate(
    code: str,
    reason: str,
    failed: list[str],
    warnings: list[str],
    candidate: TradeCandidate,
    ctx: UserContext,
) -> ValidationResult:
    failed.append(code)
    return ValidationResult(
        approved=False,
        rejection_code=code,
        rejection_reason=reason,
        warnings=warnings,
        failed_checks=failed.copy(),
        risk_per_trade_pct=ctx.risk_per_trade,
        expected_net_profit=candidate.expected_net_profit,
        expected_net_loss=candidate.expected_net_loss,
    )


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

    async def validate_candidate(
        self,
        candidate: TradeCandidate,
        ctx: UserContext,
        account: AccountState,
        daily_loss_usdt: Decimal,
        weekly_loss_usdt: Decimal,
        weekly_limit_usdt: Decimal,
        consecutive_losses: int,
        open_positions_count: int,
        same_coin_position: OpenPosition | None,
        market_regime: object | None = None,
        funding_context: object | None = None,
        config: object | None = None,
    ) -> ValidationResult:
        """
        Deterministic TradeCandidate 검증 파이프라인.

        Legacy RawSignal 검증과 달리 confidence 기반 판단이나 재사이징을 하지
        않는다.
        TradeCandidate가 이미 계산한 손익·비용·R:R 값을 엄격히 검증한다.
        """
        warnings: list[str] = []
        failed: list[str] = []

        try:
            ok, reason = await check_kill_switch(ctx.user_id, self._redis)
            if not ok:
                return _reject_candidate(
                    "KILL_SWITCH", reason, failed, warnings, candidate, ctx
                )

            ok, reason = check_trading_active(ctx)
            if not ok:
                return _reject_candidate(
                    "TRADING_INACTIVE", reason, failed, warnings, candidate, ctx
                )

            if candidate.action not in (FinalAction.LONG, FinalAction.SHORT):
                return _reject_candidate(
                    "HOLD",
                    "candidate.action이 LONG/SHORT가 아닙니다",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            if candidate.stop_loss is None or candidate.stop_loss <= 0:
                return _reject_candidate(
                    "ORDER_003",
                    "ORDER_003: 손절가(stop_loss)가 없습니다",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            if candidate.take_profit is None or candidate.take_profit <= 0:
                return _reject_candidate(
                    "TAKE_PROFIT_MISSING",
                    "목표가(take_profit)가 없습니다",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            if candidate.strategy_type == StrategyType.UNKNOWN:
                return _reject_candidate(
                    "UNKNOWN_STRATEGY",
                    "strategy_type=UNKNOWN 후보는 실행할 수 없습니다",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            strategy_key = candidate.strategy_type.value
            strategy_threshold = STRATEGY_THRESHOLDS.get(strategy_key)
            strategy_min_rr = max(
                float(candidate.min_required_rr),
                strategy_threshold.min_risk_reward_ratio if strategy_threshold else 0.0,
            )
            global_min_rr = float(_cfg(
                config,
                "global_min_risk_reward_ratio",
                GLOBAL_MIN_RISK_REWARD_RATIO,
            ))

            if candidate.actual_rr < strategy_min_rr:
                return _reject_candidate(
                    "STRATEGY_RR",
                    f"R:R {candidate.actual_rr:.2f} < 전략 최소 {strategy_min_rr:.2f}",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            if candidate.actual_rr < global_min_rr:
                return _reject_candidate(
                    "ORDER_004",
                    f"R:R {candidate.actual_rr:.2f} < 전역 최소 {global_min_rr:.2f}",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            max_leverage = min(
                int(_cfg(config, "max_leverage", DECISION_MAX_LEVERAGE)),
                ctx.max_leverage,
            )
            if candidate.leverage > max_leverage:
                return _reject_candidate(
                    "LEVERAGE_LIMIT",
                    f"레버리지 {candidate.leverage}x > 허용 {max_leverage}x",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            max_margin_ratio = float(_cfg(
                config,
                "max_entry_margin_ratio",
                DECISION_MAX_ENTRY_MARGIN_RATIO,
            ))
            if candidate.margin_ratio > max_margin_ratio:
                return _reject_candidate(
                    "MARGIN_RATIO_LIMIT",
                    f"margin_ratio {candidate.margin_ratio:.2%} > 허용 {max_margin_ratio:.2%}",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            projected_loss = candidate.expected_net_loss
            if projected_loss is None:
                projected_loss = account.total_balance * Decimal(str(ctx.risk_per_trade))

            daily_limit_usdt = account.total_balance * Decimal(str(ctx.daily_loss_limit_pct))
            ok, reason, warn_level = check_daily_loss_limit(
                daily_loss_usdt,
                daily_limit_usdt,
                projected_loss,
            )
            if warn_level:
                warnings.append(
                    f"DAILY_LOSS_{warn_level.upper()}: 일일 손실 한도 {warn_level}"
                )
            if not ok:
                await self._kill_switch.halt_trading(
                    ctx.user_id,
                    HaltTrigger.DAILY_LOSS_LIMIT,
                    f"일일 손실 ${daily_loss_usdt:.2f} / 한도 ${daily_limit_usdt:.2f}",
                )
                return _reject_candidate("ORDER_001", reason, failed, warnings, candidate, ctx)

            ok, reason = check_weekly_loss_limit(weekly_loss_usdt, weekly_limit_usdt)
            if not ok:
                await self._kill_switch.halt_trading(
                    ctx.user_id,
                    HaltTrigger.WEEKLY_LOSS_LIMIT,
                    f"주간 손실 ${weekly_loss_usdt:.2f} / 한도 ${weekly_limit_usdt:.2f}",
                )
                return _reject_candidate("WEEKLY_LOSS", reason, failed, warnings, candidate, ctx)

            ok, reason = await check_consecutive_losses(
                ctx.user_id,
                consecutive_losses,
                self._redis,
            )
            if not ok:
                if consecutive_losses >= 5:
                    await self._kill_switch.halt_trading(
                        ctx.user_id,
                        HaltTrigger.CONSECUTIVE_LOSSES,
                        f"{consecutive_losses}연속 손실",
                    )
                return _reject_candidate("CONSEC_LOSS", reason, failed, warnings, candidate, ctx)

            ok, reason = check_position_count_limit(open_positions_count, ctx)
            if not ok and same_coin_position is None:
                return _reject_candidate("ORDER_002", reason, failed, warnings, candidate, ctx)

            if same_coin_position is not None:
                return _reject_candidate(
                    "POSITION_CONFLICT",
                    f"{candidate.coin} 기존 포지션이 있어 신규 후보를 거부합니다",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            min_profit_pct = Decimal(str(_cfg(
                config,
                "min_expected_net_profit_pct",
                MIN_EXPECTED_NET_PROFIT_PCT,
            )))
            min_profit = candidate.notional_size * min_profit_pct
            if candidate.expected_net_profit is None or candidate.expected_net_profit <= min_profit:
                return _reject_candidate(
                    "EXPECTED_PROFIT",
                    f"expected_net_profit {candidate.expected_net_profit} <= 최소 {min_profit}",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            max_loss_allowed = account.total_balance * Decimal(str(ctx.risk_per_trade))
            if (
                candidate.expected_net_loss is None
                or candidate.expected_net_loss > max_loss_allowed
            ):
                return _reject_candidate(
                    "EXPECTED_LOSS",
                    f"expected_net_loss {candidate.expected_net_loss} "
                    f"> 계좌 리스크 한도 {max_loss_allowed}",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            if candidate.liquidation_price is None:
                return _reject_candidate(
                    "LIQUIDATION_PRICE",
                    "liquidation_price가 없어 청산 리스크를 검증할 수 없습니다",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            liq_buffer = Decimal(str(_cfg(config, "min_liq_stop_buffer_pct", 0.001)))
            if candidate.action == FinalAction.LONG:
                max_safe_liq = candidate.stop_loss * (Decimal("1") - liq_buffer)
                liq_safe = candidate.liquidation_price < max_safe_liq
            else:
                min_safe_liq = candidate.stop_loss * (Decimal("1") + liq_buffer)
                liq_safe = candidate.liquidation_price > min_safe_liq
            if not liq_safe:
                return _reject_candidate(
                    "LIQUIDATION_DISTANCE",
                    "청산가가 stop_loss와 충분히 떨어져 있지 않습니다",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            if strategy_threshold and candidate.spread_bps > strategy_threshold.max_spread_bps:
                return _reject_candidate(
                    "SPREAD_LIMIT",
                    f"spread_bps {candidate.spread_bps:.2f} "
                    f"> 전략 한도 {strategy_threshold.max_spread_bps:.2f}",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            max_slippage = float(_cfg(config, "max_slippage_bps", DECISION_MAX_SLIPPAGE_BPS))
            if candidate.slippage_bps > max_slippage:
                return _reject_candidate(
                    "SLIPPAGE_LIMIT",
                    f"slippage_bps {candidate.slippage_bps:.2f} > 허용 {max_slippage:.2f}",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            minutes_to_funding = None
            if funding_context is not None:
                if isinstance(funding_context, dict):
                    minutes_to_funding = funding_context.get("minutes_to_funding")
                    is_funding_window = bool(funding_context.get("is_funding_window", False))
                else:
                    minutes_to_funding = getattr(funding_context, "minutes_to_funding", None)
                    is_funding_window = bool(getattr(funding_context, "is_funding_window", False))
                before = int(_cfg(
                    config,
                    "block_before_funding_minutes",
                    BLOCK_BEFORE_FUNDING_MINUTES,
                ))
                after = int(_cfg(
                    config,
                    "block_after_funding_minutes",
                    BLOCK_AFTER_FUNDING_MINUTES,
                ))
                if is_funding_window or (
                    minutes_to_funding is not None and -after <= float(minutes_to_funding) <= before
                ):
                    return _reject_candidate(
                        "FUNDING_WINDOW",
                        "펀딩 시간 필터에 의해 신규 진입이 차단되었습니다",
                        failed,
                        warnings,
                        candidate,
                        ctx,
                    )

            regime = _as_regime(market_regime)
            if regime == MarketRegime.HIGH_VOLATILITY and bool(_cfg(
                config,
                "high_volatility_block",
                HIGH_VOLATILITY_BLOCK,
            )):
                return _reject_candidate(
                    "HIGH_VOLATILITY",
                    "HIGH_VOLATILITY 국면에서는 신규 진입을 차단합니다",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )
            if regime == MarketRegime.NEWS_EVENT and bool(_cfg(
                config,
                "news_event_block",
                NEWS_EVENT_BLOCK,
            )):
                return _reject_candidate(
                    "NEWS_EVENT",
                    "NEWS_EVENT 국면에서는 신규 진입을 차단합니다",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            if candidate.expected_holding_minutes <= 0:
                return _reject_candidate(
                    "HOLDING_TIME",
                    "expected_holding_minutes가 정의되지 않았습니다",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )
            if (
                strategy_threshold
                and candidate.expected_holding_minutes > strategy_threshold.max_holding_minutes
            ):
                return _reject_candidate(
                    "HOLDING_TIME",
                    f"expected_holding_minutes {candidate.expected_holding_minutes} "
                    f"> 전략 최대 {strategy_threshold.max_holding_minutes}",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            if bool(_cfg(config, "allow_martingale", ALLOW_MARTINGALE)):
                return _reject_candidate(
                    "MARTINGALE_DISABLED",
                    "마틴게일은 허용되지 않습니다",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )
            if bool(_cfg(config, "allow_averaging_down", ALLOW_AVERAGING_DOWN)):
                return _reject_candidate(
                    "AVERAGING_DOWN_DISABLED",
                    "물타기는 허용되지 않습니다",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            margin_mode = str(_cfg(config, "margin_mode", MARGIN_MODE)).lower()
            if margin_mode != "isolated" or not ISOLATED_MARGIN_ONLY:
                return _reject_candidate(
                    "MARGIN_MODE",
                    "Cross margin은 허용되지 않습니다 — isolated만 허용",
                    failed,
                    warnings,
                    candidate,
                    ctx,
                )

            ok, reason = check_portfolio_risk(
                account,
                candidate.expected_net_loss or Decimal("0"),
                ctx.risk_profile,
            )
            if not ok:
                return _reject_candidate("PORTFOLIO_RISK", reason, failed, warnings, candidate, ctx)

            quantity = (
                candidate.notional_size / candidate.entry_price
                if candidate.entry_price > 0
                else None
            )
            return ValidationResult(
                approved=True,
                quantity=quantity,
                final_leverage=candidate.leverage,
                margin_required_usdt=candidate.notional_size / Decimal(str(candidate.leverage)),
                max_loss_usdt=candidate.expected_net_loss,
                max_profit_usdt=candidate.expected_net_profit,
                rr_ratio=Decimal(str(candidate.actual_rr)),
                warnings=warnings,
                failed_checks=[],
                risk_per_trade_pct=ctx.risk_per_trade,
                expected_net_profit=candidate.expected_net_profit,
                expected_net_loss=candidate.expected_net_loss,
            )

        except Exception as exc:
            logger.error(
                "Candidate risk validation SYSTEM_ERROR user_id=%s error=%s",
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
