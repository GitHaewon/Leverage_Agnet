"""
Orchestrator 테스트 공유 픽스처.

실제 에이전트를 호출하지 않는 Mock 구현체들.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from agents.orchestrator.models import PipelineInput


# ── Mock 반환 타입 ─────────────────────────────────────────────────────────────

@dataclass
class MockMarketSnapshot:
    coin: str = "BTC"
    current_price: float = 67000.0
    ohlcv: dict = field(default_factory=dict)
    open_positions: list = field(default_factory=list)


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
class MockAnalysisDecision:
    decision: str = "LONG"
    confidence: int = 78
    reason: str = "RSI 과매도 + EMA 지지"
    risk_level: str = "MEDIUM"


@dataclass
class MockAnalystResult:
    decision: MockAnalysisDecision = field(default_factory=MockAnalysisDecision)
    entry_price: float = 67000.0
    take_profit: float | None = 69200.0
    stop_loss: float | None = 66000.0
    leverage: int = 5
    rr_ratio: float = 2.2
    raw_reasons: list = field(default_factory=lambda: ["RSI oversold", "EMA support"])
    model_used: str = "claude-sonnet-4-6"
    tokens_input: int = 500
    tokens_output: int = 150
    forced_hold: bool = False
    hold_reason: str = ""

    @property
    def is_actionable(self) -> bool:
        return self.decision.decision != "HOLD"


@dataclass
class MockHoldAnalystResult:
    decision: MockAnalysisDecision = field(
        default_factory=lambda: MockAnalysisDecision(decision="HOLD", confidence=40)
    )
    entry_price: float = 0.0
    take_profit: float | None = None
    stop_loss: float | None = None
    leverage: int = 1
    rr_ratio: float = 0.0
    raw_reasons: list = field(default_factory=list)
    model_used: str = "claude-sonnet-4-6"
    tokens_input: int = 300
    tokens_output: int = 80
    forced_hold: bool = False
    hold_reason: str = "신뢰도 부족"

    @property
    def is_actionable(self) -> bool:
        return False


@dataclass
class MockValidationResult:
    approved: bool = True
    rejection_reason: str | None = None
    rejection_code: str | None = None
    quantity: Decimal | None = Decimal("0.00741")
    final_leverage: int | None = 5
    margin_required_usdt: Decimal | None = Decimal("100")
    max_loss_usdt: Decimal | None = Decimal("48.5")
    max_profit_usdt: Decimal | None = Decimal("131")
    rr_ratio: Decimal | None = Decimal("2.71")
    pre_action: str | None = None
    existing_position_id: Any = None
    warnings: list = field(default_factory=list)


@dataclass
class MockOpenResult:
    position_id: str = "pos_001"
    status: str = "open"


@dataclass
class MockExecutionResult:
    approved: bool = True
    executed: bool = True
    mode: str = "testnet"
    rejection_code: str | None = None
    rejection_reason: str | None = None
    tp_sl_failed: bool = False
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
        self._snapshot = snapshot if snapshot is not None else None
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


class MockAnalystProvider:
    def __init__(self, result: Any = None, fail: bool = False) -> None:
        self._result = result or MockAnalystResult()
        self._fail = fail
        self.call_count = 0

    async def analyze(self, market: Any, technical: Any, strategy: Any) -> Any:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("Claude API 오류")
        return self._result


class MockRiskProvider:
    def __init__(self, result: Any = None, fail: bool = False) -> None:
        self._result = result or MockValidationResult()
        self._fail = fail
        self.call_count = 0

    async def validate(self, signal: Any, user_ctx: Any, account: Any, **kwargs) -> Any:
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

    async def execute(self, req: Any) -> Any:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("Binance API 오류")
        return self._result


# ── 공장 함수 ─────────────────────────────────────────────────────────────────

def make_deps(
    *,
    market_data: Any = None,
    technical: Any = None,
    strategy: Any = None,
    analyst: Any = None,
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
        analyst=analyst or MockAnalystProvider(),
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
