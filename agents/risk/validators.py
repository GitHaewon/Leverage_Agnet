"""
Risk 검증 함수 모음 — TRADING_RULES.md §11.1 파이프라인 구현.

각 함수는 독립적으로 테스트 가능한 순수 함수 또는 비동기 함수다.
실패 기본값: 거부 (안전 우선 원칙).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import redis.asyncio as aioredis

from agents.risk.constants import (
    CONSECUTIVE_LOSS_COOLDOWN,
    CONSECUTIVE_LOSS_HALT,
    COOLDOWN_MINUTES,
    DAILY_LOSS_CAUTION_PCT,
    DAILY_LOSS_HALT_PCT,
    DAILY_LOSS_WARNING_PCT,
    MAX_PORTFOLIO_RISK,
    MAX_PORTFOLIO_RISK_AGGRESSIVE,
    MAX_POSITIONS_PER_COIN,
    MIN_CONFIDENCE,
    MIN_RR_RATIO,
    PLAN_MAX_POSITIONS,
    REDIS_KEY_USER_COOLDOWN,
    REDIS_KEY_USER_HALT,
    REDIS_KEY_GLOBAL_KILL_SWITCH,
    REDIS_KEY_USER_KILL_SWITCH,
    WEEKLY_LOSS_HALT_PCT,
    WEEKLY_LOSS_SEMI_AUTO_PCT,
)
from agents.risk.models import (
    AccountState,
    OpenPosition,
    RawSignal,
    UserContext,
    ValidationResult,
)
from agents.risk.sizing import validate_rr_ratio
from agents.position_manager.models import MAX_DCA_COUNT


# ════════════════════════════════════════════════════════════════
# CHECK 0: Kill Switch & Halt 상태
# ════════════════════════════════════════════════════════════════

async def check_kill_switch(
    user_id: uuid.UUID,
    redis: aioredis.Redis,
) -> tuple[bool, str]:
    """
    Kill Switch (전역/사용자 레벨) 및 Halt 상태 확인.
    어떤 다른 검증보다 먼저 실행된다.
    """
    # 전역 Kill Switch
    if await redis.exists(REDIS_KEY_GLOBAL_KILL_SWITCH):
        return False, "KILL_SWITCH: 시스템 전체 거래 중단 상태"

    # 사용자 Kill Switch
    user_key = REDIS_KEY_USER_KILL_SWITCH.format(user_id=user_id)
    if await redis.exists(user_key):
        return False, "KILL_SWITCH: 사용자 거래 중단 상태"

    # 사용자 Halt 상태
    halt_key = REDIS_KEY_USER_HALT.format(user_id=user_id)
    halt_data = await redis.get(halt_key)
    if halt_data:
        import json
        try:
            data = json.loads(halt_data)
            trigger = data.get("trigger", "UNKNOWN")
            until = data.get("until", "")
            return False, f"TRADING_HALTED: {trigger} — {until}까지"
        except Exception:
            return False, "TRADING_HALTED: 거래 중단 상태"

    return True, "OK"


# ════════════════════════════════════════════════════════════════
# CHECK 1: HOLD 시그널 필터
# ════════════════════════════════════════════════════════════════

def check_not_hold(signal: RawSignal) -> tuple[bool, str]:
    if signal.direction == "HOLD":
        return False, "HOLD: 거래 없음"
    return True, "OK"


# ════════════════════════════════════════════════════════════════
# CHECK 2: 자동매매 활성화 여부
# ════════════════════════════════════════════════════════════════

def check_trading_active(ctx: UserContext) -> tuple[bool, str]:
    if not ctx.is_trading_active:
        return False, "TRADING_INACTIVE: 자동매매가 비활성화 상태"
    return True, "OK"


# ════════════════════════════════════════════════════════════════
# CHECK 3: Stop Loss 존재 (절대 규칙)
# ════════════════════════════════════════════════════════════════

def check_stop_loss_exists(signal: RawSignal) -> tuple[bool, str]:
    """CLAUDE.md 절대 규칙: SL 없는 주문 금지."""
    if signal.stop_loss is None:
        return False, "ORDER_003: 손절가(stop_loss)가 없습니다 — SL 없는 주문 절대 금지"
    if signal.stop_loss <= 0:
        return False, "ORDER_003: 손절가가 0 이하입니다"
    return True, "OK"


# ════════════════════════════════════════════════════════════════
# CHECK 4: R:R 비율 (§7.4)
# ════════════════════════════════════════════════════════════════

def check_rr_ratio(signal: RawSignal) -> tuple[bool, Decimal, str]:
    """R:R 최소 2.0 강제."""
    if signal.stop_loss is None:
        return False, Decimal("0"), "ORDER_003: SL 없음"
    return validate_rr_ratio(
        signal.entry_price,
        signal.take_profit,
        signal.stop_loss,
        signal.direction,
    )


# ════════════════════════════════════════════════════════════════
# CHECK 5: 신뢰도 (§3, confidence ≥ 60%)
# ════════════════════════════════════════════════════════════════

def check_confidence(signal: RawSignal) -> tuple[bool, str]:
    if signal.confidence < MIN_CONFIDENCE:
        return False, (
            f"LOW_CONFIDENCE: {signal.confidence:.0%} < {MIN_CONFIDENCE:.0%} 최소 신뢰도"
        )
    return True, "OK"


# ════════════════════════════════════════════════════════════════
# CHECK 6: 거래 허용 시간 (§11.1 C11)
# ════════════════════════════════════════════════════════════════

def check_trading_hours(ctx: UserContext) -> tuple[bool, str]:
    """
    사용자가 설정한 허용 시간 내인지 확인.
    allowed_hours_start / end = None → 24시간 허용.
    """
    if ctx.allowed_hours_start is None or ctx.allowed_hours_end is None:
        return True, "OK"

    now_utc = datetime.now(timezone.utc).strftime("%H:%M")
    start = ctx.allowed_hours_start
    end = ctx.allowed_hours_end

    # 자정 걸치는 케이스 처리 (예: 22:00 ~ 06:00)
    if start <= end:
        in_range = start <= now_utc <= end
    else:
        in_range = now_utc >= start or now_utc <= end

    if not in_range:
        return False, f"TIME_RESTRICTION: 현재 {now_utc} UTC는 허용 시간({start}~{end}) 외"

    return True, "OK"


# ════════════════════════════════════════════════════════════════
# CHECK 7: 일일 손실 한도 (§4)
# ════════════════════════════════════════════════════════════════

def check_daily_loss_limit(
    daily_loss_usdt: Decimal,
    daily_limit_usdt: Decimal,
    projected_new_loss: Decimal,
) -> tuple[bool, str, str | None]:
    """
    Returns: (can_trade, reason, warning_level)
    warning_level: "warning" | "caution" | None
    """
    warning = None
    ratio = float(daily_loss_usdt / daily_limit_usdt) if daily_limit_usdt > 0 else 0.0

    if ratio >= DAILY_LOSS_HALT_PCT:
        return False, (
            f"ORDER_001: 일일 손실 한도 도달 "
            f"(${daily_loss_usdt:.2f} / ${daily_limit_usdt:.2f})"
        ), None

    projected = daily_loss_usdt + projected_new_loss
    if projected > daily_limit_usdt:
        return False, (
            f"ORDER_001: 이 거래 시 일일 손실 한도 초과 예상 "
            f"(현재 ${daily_loss_usdt:.2f} + 예상 ${projected_new_loss:.2f} "
            f"> 한도 ${daily_limit_usdt:.2f})"
        ), None

    if ratio >= DAILY_LOSS_CAUTION_PCT:
        warning = "caution"
    elif ratio >= DAILY_LOSS_WARNING_PCT:
        warning = "warning"

    return True, "OK", warning


# ════════════════════════════════════════════════════════════════
# CHECK 8: 주간 손실 한도 (§5)
# ════════════════════════════════════════════════════════════════

def check_weekly_loss_limit(
    weekly_loss_usdt: Decimal,
    weekly_limit_usdt: Decimal,
) -> tuple[bool, str]:
    if weekly_limit_usdt <= 0:
        return True, "OK"

    ratio = float(weekly_loss_usdt / weekly_limit_usdt)
    if ratio >= WEEKLY_LOSS_HALT_PCT:
        return False, (
            f"WEEKLY_LOSS: 주간 손실 한도 도달 "
            f"(${weekly_loss_usdt:.2f} / ${weekly_limit_usdt:.2f})"
        )
    if ratio >= WEEKLY_LOSS_SEMI_AUTO_PCT:
        # 거부는 아니지만 경고 — 호출자가 반자동 전환 처리
        pass

    return True, "OK"


# ════════════════════════════════════════════════════════════════
# CHECK 9: 연속 손실 (§6)
# ════════════════════════════════════════════════════════════════

async def check_consecutive_losses(
    user_id: uuid.UUID,
    consecutive_count: int,
    redis: aioredis.Redis,
) -> tuple[bool, str]:
    """
    3연속 → 쿨다운 시작
    5연속 → 자동매매 중단 (수동 재활성화 필요)
    """
    cooldown_key = REDIS_KEY_USER_COOLDOWN.format(user_id=user_id)

    # 쿨다운 중 확인
    cooldown_end_str = await redis.get(cooldown_key)
    if cooldown_end_str:
        try:
            cooldown_end = datetime.fromisoformat(cooldown_end_str)
            if cooldown_end > datetime.now(timezone.utc):
                remaining = int((cooldown_end - datetime.now(timezone.utc)).total_seconds() / 60)
                return False, f"COOLDOWN: {remaining}분 후 재개 ({cooldown_end.isoformat()})"
        except ValueError:
            pass

    if consecutive_count >= CONSECUTIVE_LOSS_HALT:
        return False, f"CONSEC_LOSS: {consecutive_count}연속 손실 — 수동 재활성화 필요"

    if consecutive_count >= CONSECUTIVE_LOSS_COOLDOWN:
        cooldown_end = datetime.now(timezone.utc) + timedelta(minutes=COOLDOWN_MINUTES)
        await redis.set(
            cooldown_key,
            cooldown_end.isoformat(),
            ex=COOLDOWN_MINUTES * 60,
        )
        return False, (
            f"CONSEC_LOSS: {consecutive_count}연속 손실 — "
            f"{COOLDOWN_MINUTES}분 쿨다운 ({cooldown_end.isoformat()})"
        )

    return True, "OK"


# ════════════════════════════════════════════════════════════════
# CHECK 10: 동시 포지션 한도 (§2)
# ════════════════════════════════════════════════════════════════

def check_position_count_limit(
    open_count: int,
    ctx: UserContext,
) -> tuple[bool, str]:
    plan_limit = PLAN_MAX_POSITIONS.get(ctx.plan, 1)
    effective = min(ctx.max_concurrent_positions, plan_limit)

    if open_count >= effective:
        return False, (
            f"ORDER_002: 최대 포지션 {effective}개 한도 초과 "
            f"(현재 {open_count}개, 플랜 {ctx.plan})"
        )
    return True, "OK"


# ════════════════════════════════════════════════════════════════
# CHECK 11: 동일 코인 포지션 (§2.2)
# ════════════════════════════════════════════════════════════════

def check_same_coin_position(
    signal: RawSignal,
    existing: OpenPosition | None,
) -> tuple[bool, str, str | None]:
    """
    Returns: (can_proceed, reason, pre_action)
    pre_action: "close_existing" | "dca" | None
    """
    if existing is None:
        return True, "OK", None

    if existing.direction == signal.direction:
        # 동일 방향 → DCA 경로 (별도 DCA 검증 필요)
        if existing.dca_count >= MAX_DCA_COUNT:
            return False, f"DCA_LIMIT: max DCA {MAX_DCA_COUNT} reached", None
        return True, "DCA_ELIGIBLE", "dca"
    else:
        # 반대 방향 → 기존 포지션 먼저 청산 후 신규 진입
        return True, "REVERSE_POSITION", "close_existing"


# ════════════════════════════════════════════════════════════════
# CHECK 12: 포트폴리오 총 리스크 (§3.2)
# ════════════════════════════════════════════════════════════════

def check_portfolio_risk(
    account: AccountState,
    new_trade_risk_usdt: Decimal,
    risk_profile: str,
) -> tuple[bool, str]:
    limit_ratio = (
        MAX_PORTFOLIO_RISK_AGGRESSIVE
        if risk_profile == "aggressive"
        else MAX_PORTFOLIO_RISK
    )
    max_risk = account.total_balance * Decimal(str(limit_ratio))
    total_risk = account.open_positions_risk_usdt + new_trade_risk_usdt

    if total_risk > max_risk:
        return False, (
            f"PORTFOLIO_RISK: 총 위험 ${total_risk:.2f} > "
            f"한도 ${max_risk:.2f} ({limit_ratio:.0%})"
        )
    return True, "OK"
