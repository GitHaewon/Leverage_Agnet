"""
SafetyGateAdapter — SafetyGate를 두 agents 프로토콜에 연결.

  - agents.execution.models.SafetyGateProtocol   (주문 실행 전 check_order_allowed)
  - agents.orchestrator.pipeline.PostTradeHookProvider (체결 후 on_trade_executed)

agents/ 레이어는 backend/app/safety/ 를 직접 import할 수 없다.
이 어댑터가 SafetyGate의 SafetyCheckResult를 agents가 이해하는 타입으로 변환한다.
"""
from __future__ import annotations

import logging

from agents.execution.models import SafetyDecision
from agents.orchestrator.models import PostTradeEvent

from .gate import SafetyGate

logger = logging.getLogger(__name__)


class SafetyGateAdapter:
    """
    SafetyGate → SafetyGateProtocol + PostTradeHookProvider 어댑터.

    사용:
        adapter = SafetyGateAdapter(SafetyGate(store, config))
        ExecutionEngine(..., safety_gate=adapter)
        OrchestratorDeps(..., post_trade_hook=adapter)
    """

    def __init__(self, gate: SafetyGate) -> None:
        self._gate = gate

    async def check_order_allowed(self, user_id: str) -> SafetyDecision:
        result = await self._gate.check_order_allowed(user_id)
        return SafetyDecision(
            allowed=result.allowed,
            rejection_code=result.halt_reason.value if result.halt_reason else None,
            message=result.message,
        )

    async def on_trade_executed(self, event: PostTradeEvent) -> None:
        """
        포지션 청산 완료 후 SafetyGate에 실현 손익을 누적한다.

        pnl 우선순위:
          1. event.realized_pnl_usdt — fill price 기반 확정 P&L (EMERGENCY_CLOSED 등)
          2. -event.max_loss_usdt    — SL 기준 보수적 추정 (fallback)

        Kill switch 발동 시 UserSettings.is_trading_active=False로 DB를 동기화한다.
        """
        pnl = (
            event.realized_pnl_usdt
            if event.realized_pnl_usdt is not None
            else -event.max_loss_usdt
        )
        results = await self._gate.on_trade_closed(
            user_id=event.user_id,
            pnl_usdt=pnl,
            period_start_balance=event.period_start_balance,
            week_start_balance=event.week_start_balance,
            current_balance=event.current_balance,
        )

        # Kill switch 발동 감지 → DB 동기화
        # allowed=False 결과가 있으면 사용자별 kill switch(일일/주간/드로우다운) 발동
        halted = next((r for r in results if not r.allowed), None)
        if halted is not None:
            reason = halted.halt_reason.value if halted.halt_reason else "UNKNOWN"
            logger.warning(
                "kill_switch_triggered user_id=%s reason=%s — disabling auto-trading",
                event.user_id, reason,
            )
            from app.services.user_service import disable_auto_trading
            await disable_auto_trading(event.user_id, reason=reason)
