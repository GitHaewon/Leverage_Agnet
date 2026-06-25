"""
TradeCandidate generator 단위 테스트.

검증 항목:
  1. UNKNOWN strategy returns HOLD
  2. news no_trade_flag returns HOLD
  3. high risk score returns HOLD
  4. strong long score creates LONG candidate
  5. strong short score creates SHORT candidate
  6. conflicting long/short scores returns HOLD
  7. fees and slippage reduce expected_net_profit
  8. actual_rr is calculated correctly
  9. leverage and margin_ratio respect config limits
  10. missing price data returns HOLD
  11. candidate includes min_required_rr from strategy selection
  12. candidate includes expected_holding_minutes
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from agents.decision.candidate_generator import generate_trade_candidate
from agents.decision.models import (
    DerivativesMarketScore,
    FinalAction,
    MarketRegime,
    NewsSentimentScore,
    SignalScore,
    StrategySelectionResult,
    StrategyType,
)


COIN = "BTC"
SYMBOL = "BTCUSDT"
_DEFAULT = object()


@dataclass
class _Signal:
    entry_price: Decimal = Decimal("100")
    stop_loss: Decimal = Decimal("95")
    take_profit: Decimal = Decimal("110")
    leverage: int = 5
    margin_ratio: float = 0.02


@dataclass
class _Account:
    available_balance: Decimal = Decimal("10000")


@dataclass
class _TF:
    close: float = 100.0
    atr: float = 2.0


@dataclass
class _TA:
    latest_close: float = 100.0
    analyses: dict[str, _TF] = field(default_factory=lambda: {"1h": _TF()})
    support_levels: list[float] = field(default_factory=lambda: [95.0, 90.0])
    resistance_levels: list[float] = field(default_factory=lambda: [110.0, 120.0])


def _chart(long: float = 0.0, short: float = 0.0, risk: float = 0.0) -> SignalScore:
    return SignalScore(
        long_score=long,
        short_score=short,
        no_trade_score=10.0,
        risk_score=risk,
        reasons=[],
    )


def _news(risk: float = 0.0, no_trade: bool = False) -> NewsSentimentScore:
    return NewsSentimentScore(
        sentiment_score=0.0,
        long_score_adjustment=0.0,
        short_score_adjustment=0.0,
        risk_score=risk,
        no_trade_flag=no_trade,
        reasons=[],
    )


def _deriv(
    long_adj: float = 0.0,
    short_adj: float = 0.0,
    risk: float = 0.0,
) -> DerivativesMarketScore:
    return DerivativesMarketScore(
        long_score_adjustment=long_adj,
        short_score_adjustment=short_adj,
        risk_score=risk,
        crowded_side="NONE",
        reasons=[],
    )


def _selection(
    strategy_type: StrategyType = StrategyType.INTRADAY,
    minutes: int = 30,
    rr: float = 2.0,
) -> StrategySelectionResult:
    return StrategySelectionResult(
        strategy_type=strategy_type,
        expected_holding_minutes=minutes,
        min_required_rr=rr,
        reasons=[],
    )


def _market(price: float | None = 100.0) -> dict:
    data = {"spread_bps": 1.0}
    if price is not None:
        data["current_price"] = price
    return data


def _candidate(
    *,
    chart: SignalScore | None = None,
    news: NewsSentimentScore | None = None,
    deriv: DerivativesMarketScore | None = None,
    selection: StrategySelectionResult | None = None,
    signal: object | None = _DEFAULT,
    market: dict | None = _DEFAULT,
    technical: object | None = _DEFAULT,
    config: dict | None = None,
):
    return generate_trade_candidate(
        coin=COIN,
        symbol=SYMBOL,
        market_snapshot=_market() if market is _DEFAULT else market,
        technical_result=_TA() if technical is _DEFAULT else technical,
        strategy_signal=_Signal() if signal is _DEFAULT else signal,
        market_regime=MarketRegime.TREND_UP,
        chart_score=chart if chart is not None else _chart(long=80.0, risk=0.0),
        news_score=news if news is not None else _news(),
        derivatives_score=deriv if deriv is not None else _deriv(),
        strategy_selection=selection if selection is not None else _selection(),
        account_state=_Account(),
        config=config or {"max_risk_score": 80.0},
    )


def test_unknown_strategy_returns_hold() -> None:
    result = _candidate(selection=_selection(StrategyType.UNKNOWN, minutes=0, rr=0.0))

    assert result.action == FinalAction.HOLD
    assert any("리스크" in reason for reason in result.reasons)
    assert result.stop_loss is None
    assert result.take_profit is None


def test_news_no_trade_flag_returns_hold() -> None:
    result = _candidate(news=_news(no_trade=True))

    assert result.action == FinalAction.HOLD
    assert any("no_trade_flag" in reason for reason in result.reasons)


def test_high_risk_score_returns_hold() -> None:
    result = _candidate(
        chart=_chart(long=90.0, risk=100.0),
        news=_news(risk=100.0),
        deriv=_deriv(risk=100.0),
        config={"max_risk_score": 30.0},
    )

    assert result.action == FinalAction.HOLD


def test_shadow_threshold_profile_can_relax_scores_for_virtual_trades() -> None:
    live_default = _candidate(
        chart=_chart(long=62.0, risk=40.0),
        news=_news(risk=30.0),
        deriv=_deriv(risk=30.0),
        config=None,
    )
    shadow_profile = _candidate(
        chart=_chart(long=62.0, risk=40.0),
        news=_news(risk=30.0),
        deriv=_deriv(risk=30.0),
        config={
            "min_long_score": 60.0,
            "min_short_score": 60.0,
            "max_risk_score": 45.0,
        },
    )

    assert live_default.action == FinalAction.HOLD
    assert shadow_profile.action == FinalAction.LONG


def test_strong_long_score_creates_long_candidate() -> None:
    result = _candidate(chart=_chart(long=76.0, short=10.0, risk=0.0))

    assert result.action == FinalAction.LONG
    assert result.stop_loss == Decimal("95.00")
    assert result.take_profit == Decimal("110.00")


def test_strong_short_score_creates_short_candidate() -> None:
    signal = _Signal(
        entry_price=Decimal("100"),
        stop_loss=Decimal("105"),
        take_profit=Decimal("90"),
    )
    result = _candidate(chart=_chart(long=10.0, short=78.0, risk=0.0), signal=signal)

    assert result.action == FinalAction.SHORT
    assert result.stop_loss == Decimal("105.00")
    assert result.take_profit == Decimal("90.00")


def test_conflicting_long_short_scores_returns_hold() -> None:
    result = _candidate(chart=_chart(long=82.0, short=81.0, risk=0.0))

    assert result.action == FinalAction.HOLD
    assert any("충돌" in reason for reason in result.reasons)


def test_fees_and_slippage_reduce_expected_net_profit() -> None:
    result = _candidate(config={"max_risk_score": 80.0, "slippage_bps": 3.0})

    assert result.action == FinalAction.LONG
    assert result.expected_gross_profit is not None
    assert result.expected_net_profit is not None
    assert result.expected_net_profit < result.expected_gross_profit
    assert result.expected_fees > 0
    assert result.expected_slippage_cost > 0


def test_actual_rr_is_calculated_correctly() -> None:
    result = _candidate()

    assert result.action == FinalAction.LONG
    assert result.actual_rr == 2.0


def test_leverage_and_margin_ratio_respect_config_limits() -> None:
    signal = _Signal(leverage=20, margin_ratio=0.10)
    result = _candidate(
        signal=signal,
        config={
            "max_risk_score": 80.0,
            "max_leverage": 6,
            "max_entry_margin_ratio": 0.03,
        },
    )

    assert result.action == FinalAction.LONG
    assert result.leverage == 6
    assert result.margin_ratio == 0.03


def test_missing_price_data_returns_hold() -> None:
    result = _candidate(
        market={},
        technical=None,
        signal=None,
    )

    assert result.action == FinalAction.HOLD
    assert any("가격 데이터 없음" in reason for reason in result.reasons)


def test_candidate_includes_min_required_rr_from_strategy_selection() -> None:
    result = _candidate(selection=_selection(rr=1.5))

    assert result.min_required_rr == 1.5


def test_candidate_includes_expected_holding_minutes() -> None:
    result = _candidate(selection=_selection(minutes=45))

    assert result.expected_holding_minutes == 45
