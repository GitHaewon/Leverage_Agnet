"""
Orchestrator 테스트 공유 픽스처 (결정적 의사결정 플로우).

실제 에이전트를 호출하지 않는 Mock 구현체들.
새 플로우: market_data → technical → strategy → decision → ai_review
           → risk → final_decision → portfolio → position_manager → execution
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from agents.decision.engine import DecisionResult
from agents.decision.models import (
    AIReviewAction,
    AIReviewResult,
    FinalAction,
    StrategyType,
    TradeCandidate,
)
from agents.orchestrator.models import PipelineInput


# ── Mock 반환 타입 ─────────────────────────────────────────────────────────────

@dataclass
class MockTAResult:
    tech_score: float = 0.5
    timeframe_scores: dict = field(default_factory=dict)
    indicators: dict = field(default_factory=dict)
    signals_fired: list = field(default_factory=list)
    support_levels: list = field(default_factory=list)
    resistance_levels: list = field(default_factory=list)
    latest_close: float = 67000.0


@dataclass
class MockAggregatedSignal:
    direction: str = "LONG"
    confidence: float = 0.8
    entry: Decimal = Decimal("67000")
    take_profit: Decimal | None = Decimal("69200")
    stop_loss: Decimal | None = Decimal("66000")
    leverage: int = 5
    rr_ratio: float = 2.2
    reasons: list = field(default_factory=list)
    contributing_strategies: list = field(default_factory=list)
    sentiment_score: float = 0.1
    market_score: float = 0.2
    fear_greed_index: int = 45
    fear_greed_label: str = "Fear"
    dominant_sentiment: str = "neutral"
    news_items: list = field(default_factory=list)
    funding_rate: float = -0.0002
    oi_1h_change_pct: float = 0.8
    long_short_ratio: float = 0.9
    long_account_pct: float = 47.0
    whale_activity: str = "accumulating"


@dataclass
class _MockScore:
    """차트/뉴스/파생 점수 요약 (검토 컨텍스트용)."""
    long_score: float = 80.0
    short_score: float = 10.0
    risk_score: float = 12.0
    sentiment_score: float = 5.0
    no_trade_flag: bool = False
    crowded_side: str = "NONE"
    reasons: list = field(default_factory=list)


@dataclass
class _MockRegime:
    regime: Any = None  # MarketRegime enum or None
    confidence: float = 0.8
    reasons: list = field(default_factory=list)


def make_candidate(
    action: FinalAction = FinalAction.LONG,
    strategy_type: StrategyType = StrategyType.TREND_FOLLOWING,
    *,
    expected_net_profit: Decimal | None = Decimal("95"),
    notional_size: Decimal = Decimal("5000"),
) -> TradeCandidate:
    """실행 가능한 LONG/SHORT TradeCandidate (또는 action=HOLD)."""
    is_long = action == FinalAction.LONG
    entry = Decimal("67000")
    stop_loss = Decimal("66000") if is_long else Decimal("68000")
    take_profit = Decimal("69200") if is_long else Decimal("64600")
    liq = Decimal("60300") if is_long else Decimal("73700")

    if action == FinalAction.HOLD:
        return TradeCandidate(
            action=FinalAction.HOLD, coin="BTC", symbol="BTCUSDT",
            strategy_type=strategy_type, expected_holding_minutes=0,
            entry_price=entry, stop_loss=None, take_profit=None,
            leverage=0, margin_ratio=0.0, notional_size=Decimal("0"),
            actual_rr=0.0, min_required_rr=2.0,
            expected_gross_profit=None, expected_gross_loss=None,
            expected_fees=Decimal("0"), expected_slippage_cost=Decimal("0"),
            expected_net_profit=None, expected_net_loss=None,
            liquidation_price=None, spread_bps=1.0, slippage_bps=3.0,
            reasons=["candidate HOLD"],
        )

    return TradeCandidate(
        action=action, coin="BTC", symbol="BTCUSDT",
        strategy_type=strategy_type, expected_holding_minutes=120,
        entry_price=entry, stop_loss=stop_loss, take_profit=take_profit,
        leverage=5, margin_ratio=0.015, notional_size=notional_size,
        actual_rr=2.2, min_required_rr=2.0,
        expected_gross_profit=Decimal("130"), expected_gross_loss=Decimal("48"),
        expected_fees=Decimal("5"), expected_slippage_cost=Decimal("3"),
        expected_net_profit=expected_net_profit, expected_net_loss=Decimal("56"),
        liquidation_price=liq, spread_bps=1.0, slippage_bps=3.0,
        reasons=[f"{action.value} 후보"],
    )


def make_decision_result(
    candidate: TradeCandidate | None = None,
    confidence: float = 0.8,
) -> DecisionResult:
    return DecisionResult(
        regime=_MockRegime(),
        chart_score=_MockScore(),
        news_score=_MockScore(),
        derivatives_score=_MockScore(),
        strategy_selection=None,
        candidate=candidate if candidate is not None else make_candidate(),
        confidence=confidence,
        reasons=["mock decision"],
    )


def make_review(
    action: AIReviewAction = AIReviewAction.APPROVE,
    confidence: float = 0.85,
    critical: bool = False,
) -> AIReviewResult:
    return AIReviewResult(
        review_action=action,
        confidence=confidence,
        critical_contradiction=critical,
        risk_warnings=[],
        reason_summary="mock review",
    )


def make_safe_reject_review() -> AIReviewResult:
    """파싱 실패 시 ReviewerAgent가 반환하는 안전 REJECT 형태."""
    return AIReviewResult(
        review_action=AIReviewAction.REJECT,
        confidence=0.0,
        critical_contradiction=True,
        risk_warnings=["invalid_json"],
        reason_summary="AI review parse failed",
    )


@dataclass
class MockValidationResult:
    approved: bool = True
    rejection_reason: str | None = None
    rejection_code: str | None = None
    quantity: Decimal | None = Decimal("0.0746")
    final_leverage: int | None = 5
    margin_required_usdt: Decimal | None = Decimal("1000")
    max_loss_usdt: Decimal | None = Decimal("56")
    max_profit_usdt: Decimal | None = Decimal("95")
    rr_ratio: Decimal | None = Decimal("2.2")
    pre_action: str | None = None
    existing_position_id: Any = None
    warnings: list = field(default_factory=list)
    failed_checks: list = field(default_factory=list)


@dataclass
class MockOpenResult:
    position_id: str = "pos_001"
    status: str = "open"


@dataclass
class MockOrder:
    avg_fill_price: Decimal = Decimal("67000")
    quantity: Decimal = Decimal("0.0746")
    exchange_order_id: str = "ord_123"


@dataclass
class MockExecutionResult:
    approved: bool = True
    executed: bool = True
    mode: str = "testnet"
    rejection_code: str | None = None
    rejection_reason: str | None = None
    tp_sl_failed: bool = False
    emergency_close_failed: bool = False
    entry_order: Any = None
    emergency_close_order: Any = None
    placed_real_order: bool = True
    warnings: list = field(default_factory=list)


# ── Mock 에이전트 구현체 ───────────────────────────────────────────────────────

def _default_snapshot(coin: str = "BTC") -> dict:
    return {
        "coin": coin,
        "current_price": 67000.0,
        "ohlcv": {},
        "open_positions": [],
        "funding_rate": -0.0002,
        "open_interest": 28_000_000_000.0,
    }


class MockMarketDataProvider:
    def __init__(self, snapshot: Any = None, fail: bool = False) -> None:
        self._snapshot = snapshot
        self._fail = fail
        self.call_count = 0

    async def get_snapshot(self, coin: str) -> Any:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("MarketData 연결 실패")
        return self._snapshot if self._snapshot is not None else _default_snapshot(coin)


class MockTechnicalProvider:
    def __init__(self, result: Any = None, fail: bool = False) -> None:
        self._result = result or MockTAResult()
        self._fail = fail
        self.call_count = 0

    def run(self, ohlcv_data: dict, coin: str, symbol: str | None = None) -> Any:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("TA 계산 오류")
        return self._result


class MockStrategyProvider:
    def __init__(self, result: Any = None, fail: bool = False) -> None:
        self._result = result or MockAggregatedSignal()
        self._fail = fail
        self.call_count = 0

    def evaluate(self, inp: Any) -> Any:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("Strategy 실패")
        return self._result


class MockDecisionProvider:
    def __init__(self, result: Any = None, fail: bool = False) -> None:
        self._result = result
        self._fail = fail
        self.call_count = 0

    def run(self, **kwargs: Any) -> Any:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("Decision 체인 오류")
        return self._result if self._result is not None else make_decision_result()


class MockReviewerProvider:
    def __init__(self, result: Any = None, fail: bool = False) -> None:
        self._result = result
        self._fail = fail
        self.call_count = 0

    async def review(self, review_input: Any) -> Any:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("OpenAI API 오류")
        return self._result if self._result is not None else make_review()


class MockRiskProvider:
    def __init__(self, result: Any = None, fail: bool = False) -> None:
        self._result = result or MockValidationResult()
        self._fail = fail
        self.call_count = 0

    async def validate_candidate(self, candidate: Any, ctx: Any, account: Any, *args, **kwargs) -> Any:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("RiskEngine DB 오류")
        return self._result


class MockPortfolioProvider:
    def __init__(self, can_add: bool = True, reason: str = "OK", fail: bool = False) -> None:
        self._can_add = can_add
        self._reason = reason
        self._fail = fail
        self.call_count = 0

    def can_add_position(self, positions: Any, account: Any, new_risk_usdt: Any) -> tuple[bool, str]:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("Portfolio 계산 오류")
        return (self._can_add, self._reason)


class MockPositionManagerProvider:
    def __init__(self, result: Any = None, fail: bool = False) -> None:
        self._result = result or MockOpenResult()
        self._fail = fail
        self.call_count = 0

    def open(self, user_id: str, signal: Any, validation: Any) -> Any:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("PositionManager 오류")
        return self._result


class MockExecutionProvider:
    def __init__(self, result: Any = None, fail: bool = False) -> None:
        self._result = result or MockExecutionResult()
        self._fail = fail
        self.call_count = 0
        self.last_request: Any = None

    async def execute(self, req: Any) -> Any:
        self.call_count += 1
        self.last_request = req
        if self._fail:
            raise RuntimeError("Binance API 오류")
        return self._result


class MockShadowExecutionProvider:
    """Shadow 모드: 가상 체결만 기록하고 실제 주문은 절대 넣지 않는다."""
    def __init__(self) -> None:
        self.call_count = 0
        self.real_orders_placed = 0
        self.last_request: Any = None

    async def execute(self, req: Any) -> Any:
        self.call_count += 1
        self.last_request = req
        # 실제 거래소 주문 호출 없음 — 가상 체결 결과만 반환
        return MockExecutionResult(
            mode="shadow",
            executed=True,
            placed_real_order=False,
        )


# ── 공장 함수 ─────────────────────────────────────────────────────────────────

def make_deps(
    *,
    market_data: Any = None,
    technical: Any = None,
    strategy: Any = None,
    decision: Any = None,
    reviewer: Any = None,
    risk: Any = None,
    portfolio: Any = None,
    position_manager: Any = None,
    execution: Any = None,
) -> "OrchestratorDeps":
    from agents.orchestrator.pipeline import OrchestratorDeps
    return OrchestratorDeps(
        market_data=market_data or MockMarketDataProvider(),
        technical=technical or MockTechnicalProvider(),
        strategy=strategy or MockStrategyProvider(),
        decision=decision or MockDecisionProvider(),
        reviewer=reviewer or MockReviewerProvider(),
        risk=risk or MockRiskProvider(),
        portfolio=portfolio or MockPortfolioProvider(),
        position_manager=position_manager or MockPositionManagerProvider(),
        execution=execution or MockExecutionProvider(),
    )


def make_input(coin: str = "BTC") -> PipelineInput:
    return PipelineInput(
        coin=coin,
        user_id="user_001",
        user_ctx=None,
        account_state=None,
        daily_loss_usdt=Decimal("0"),
        weekly_loss_usdt=Decimal("0"),
        weekly_limit_usdt=Decimal("500"),
        consecutive_losses=0,
        open_positions=[],
        portfolio_account=None,
    )
