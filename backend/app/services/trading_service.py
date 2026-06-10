"""
Trading Service — 자동매매 재개 비즈니스 로직.

레이어 규칙: Service는 비즈니스 로직만 담당한다.
SafetyGate(Redis) + UserSettings(DB) 양쪽을 원자적으로 복원한다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.safety.gate import SafetyGate
from app.utils.exceptions import ConflictError

logger = logging.getLogger(__name__)


async def resume_auto_trading(user_id: str, gate: SafetyGate) -> dict:
    """
    자동매매 재개.

    Kill switch 중단 기간이 만료된 경우에만 재개를 허용한다.
    아직 중단 기간이 남아 있으면 ConflictError(409)를 발생시킨다.

    순서:
      1. SafetyGate.get_halt_status() — Redis 상태 읽기 (부작용 없음)
      2. 중단 중 → ConflictError
      3. 중단 해제 상태 → reset_daily/weekly (stale Redis 정리)
      4. DB: is_trading_active=True

    본인 계정만 호출 가능 — user_id는 JWT sub에서 가져와 Route에서 주입한다.
    """
    uid_str = str(user_id)

    # STEP 1: 현재 kill switch 상태 확인 (읽기 전용 — Redis 상태 불변)
    halt_status = await gate.get_halt_status(uid_str)

    if halt_status.is_halted:
        reason = halt_status.halt_reason.value if halt_status.halt_reason else "UNKNOWN"
        halt_until_iso = (
            halt_status.halt_until.isoformat() if halt_status.halt_until else None
        )
        raise ConflictError(
            code="TRADING_001",
            message="손실 한도 중단 기간 중입니다. 만료 후 재개할 수 있습니다.",
            detail={"halt_reason": reason, "halt_until": halt_until_iso},
        )

    # STEP 2: Kill switch Redis 상태 초기화 (만료된 잔여 상태 정리, idempotent)
    await gate.reset_daily_switch(uid_str)
    await gate.reset_weekly_switch(uid_str)

    # STEP 3: DB 동기화
    from app.services.user_service import enable_auto_trading
    await enable_auto_trading(uid_str)

    now = datetime.now(timezone.utc)
    logger.info("auto_trading_resumed user_id=%s", uid_str)

    return {
        "is_trading_active": True,
        "resumed_at": now.isoformat(),
        "message": "자동매매가 재개되었습니다.",
    }
