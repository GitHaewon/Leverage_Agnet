"""
Live Trading Safety Layer — 공개 API.

프로덕션 사용법:
    from app.core.redis_client import get_redis
    from app.safety import RedisSafetyStateStore, SafetyGate, SafetyConfig

    store  = RedisSafetyStateStore(get_redis())
    config = SafetyConfig(live_trading_enabled=True, daily_loss_limit_pct=0.03)
    gate   = SafetyGate(store, config)

    # 주문 실행 전
    result = await gate.check_order_allowed(user_id)
    if not result.allowed:
        raise OrderRejected(result.message)

    # 거래 종료 후
    await gate.on_trade_closed(user_id, pnl, day_balance, week_balance, current)

    # 긴급 중단
    await gate.trigger_emergency("강제청산 발생", activated_by="system")

단위 테스트:
    store = InMemorySafetyStateStore()  # 테스트 전용 — 재시작 시 초기화됨
    gate  = SafetyGate(store, config)
"""
from .gate import SafetyGate
from .state import InMemorySafetyStateStore, RedisSafetyStateStore, SafetyStateStore
from .types import AlertLevel, HaltReason, SafetyCheckResult, SafetyConfig

__all__ = [
    "SafetyGate",
    "SafetyConfig",
    "SafetyCheckResult",
    "HaltReason",
    "AlertLevel",
    "SafetyStateStore",
    "RedisSafetyStateStore",
    "InMemorySafetyStateStore",
]
