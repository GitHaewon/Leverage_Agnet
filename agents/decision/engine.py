"""
Decision Engine — 결정적 의사결정 체인 조립.

6개 순수 함수를 하나의 결과로 묶는다. AI 호출·주문·I/O 없음.

체인:
  1. classify_market_regime
  2. score_chart_signals
  3. score_news_sentiment
  4. score_derivatives_market
  5. select_strategy_type
  6. generate_trade_candidate

OrchestratorPipeline은 이 엔진을 단일 의존성으로 주입받아 한 스텝에서 실행한다.
체인 내부 예외는 호출자(파이프라인)가 HOLD로 처리하도록 그대로 전파한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.decision.candidate_generator import generate_trade_candidate
from agents.decision.chart_signals import score_chart_signals
from agents.decision.derivatives_market import score_derivatives_market
from agents.decision.news_sentiment import score_news_sentiment
from agents.decision.regime import classify_market_regime
from agents.decision.constants import STRATEGY_HOLDING_MINUTES, STRATEGY_MIN_RR
from agents.decision.models import StrategySelectionResult, StrategyType
from agents.decision.strategy_selector import select_strategy_type
from agents.strategy.engine import build_strategy_candidates


@dataclass
class DecisionResult:
    """결정적 의사결정 체인의 전체 산출물."""
    regime: Any                 # MarketRegimeResult
    chart_score: Any            # SignalScore
    news_score: Any             # NewsSentimentScore
    derivatives_score: Any      # DerivativesMarketScore
    strategy_selection: Any     # StrategySelectionResult
    candidate: Any              # TradeCandidate
    strategy_candidates: list[Any] = field(default_factory=list)
    selected_strategy_candidate: Any | None = None
    confidence: float = 0.0     # 차트 우세 점수 기반 결정적 신뢰도 (0.0~1.0)
    reasons: list[str] = field(default_factory=list)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_news_data(market_snapshot: Any, strategy_signal: Any) -> Any:
    news = _get(market_snapshot, "news")
    if news:
        return news
    return _get(strategy_signal, "news_items")


def _extract_fear_greed(market_snapshot: Any, strategy_signal: Any) -> Any:
    fg = _get(market_snapshot, "fear_greed")
    if fg is not None:
        return fg
    index = _get(strategy_signal, "fear_greed_index")
    if index is None:
        return None
    return {
        "index": index,
        "label": _get(strategy_signal, "fear_greed_label", "Neutral"),
    }


def _extract_derivatives(market_snapshot: Any, strategy_signal: Any) -> dict:
    return {
        "funding_rate": _get(market_snapshot, "funding_rate", _get(strategy_signal, "funding_rate")),
        "open_interest": _get(market_snapshot, "open_interest"),
        "oi_change_pct": _get(market_snapshot, "oi_change_pct", _get(strategy_signal, "oi_1h_change_pct")),
        "long_short_ratio": _get(market_snapshot, "long_short_ratio", _get(strategy_signal, "long_short_ratio")),
        "long_account_pct": _get(market_snapshot, "long_account_pct", _get(strategy_signal, "long_account_pct")),
        "short_account_pct": _get(market_snapshot, "short_account_pct"),
        "liquidation_usdt": _get(market_snapshot, "liquidation_usdt"),
    }


def _extract_price_data(market_snapshot: Any) -> dict:
    return {
        "price_change_pct": _get(market_snapshot, "price_change_pct"),
        "volume_change_pct": _get(market_snapshot, "volume_change_pct"),
    }


def _strategy_candidates(strategy_signal: Any, regime: Any) -> list[Any]:
    candidates = _get(strategy_signal, "candidates", None)
    if candidates:
        return [
            c for c in candidates
            if _candidate_allowed(c, regime)
        ]
    signals = list(_get(strategy_signal, "all_signals", []) or [])
    if not signals:
        return []
    return build_strategy_candidates(signals, regime)


def _candidate_allowed(candidate: Any, regime: Any) -> bool:
    from agents.decision.strategy_selector import is_strategy_allowed_for_regime
    return is_strategy_allowed_for_regime(_get(candidate, "strategy_name"), regime)


def _candidate_strategy_type(candidate: Any) -> StrategyType:
    name = str(_get(candidate, "strategy_name", "") or "").upper()
    if "BREAKOUT" in name:
        return StrategyType.BREAKOUT
    if "SCALPING" in name:
        return StrategyType.SCALPING
    if "MEAN_REVERSION" in name or "RSI_REVERSAL" in name:
        return StrategyType.INTRADAY
    if "TREND" in name:
        return StrategyType.TREND_FOLLOWING
    return StrategyType.UNKNOWN


def _selection_from_candidate(candidate: Any) -> StrategySelectionResult:
    strategy_type = _candidate_strategy_type(candidate)
    name = str(_get(candidate, "strategy_name", strategy_type.value) or strategy_type.value)
    min_rr = STRATEGY_MIN_RR.get(name, STRATEGY_MIN_RR.get(strategy_type.value, 2.0))
    return StrategySelectionResult(
        strategy_type=strategy_type,
        expected_holding_minutes=STRATEGY_HOLDING_MINUTES.get(strategy_type.value, 0),
        min_required_rr=float(min_rr),
        reasons=[f"StrategyCandidate selected: {name}"],
    )


class DecisionEngine:
    """결정적 의사결정 체인을 실행하는 순수 엔진 (의존성 주입용)."""

    def run(
        self,
        *,
        coin: str,
        symbol: str,
        market_snapshot: Any | None,
        technical_result: Any | None,
        strategy_signal: Any | None,
        account_state: Any | None,
        config: Any | None = None,
    ) -> DecisionResult:
        regime = classify_market_regime(
            market_snapshot, technical_result, strategy_signal, config
        )
        chart_score = score_chart_signals(
            regime, technical_result, market_snapshot, config
        )
        news_score = score_news_sentiment(
            _extract_news_data(market_snapshot, strategy_signal),
            _extract_fear_greed(market_snapshot, strategy_signal),
            regime,
            config,
        )
        derivatives_score = score_derivatives_market(
            _extract_derivatives(market_snapshot, strategy_signal),
            _extract_price_data(market_snapshot),
            regime,
            config,
        )
        strategy_selection = select_strategy_type(
            regime, chart_score, news_score, derivatives_score, market_snapshot, config
        )
        candidates = _strategy_candidates(strategy_signal, regime)
        selected_candidate = candidates[0] if candidates else None
        candidate_strategy_signal = selected_candidate or strategy_signal
        if selected_candidate is not None:
            strategy_selection = _selection_from_candidate(selected_candidate)
        candidate = generate_trade_candidate(
            coin,
            symbol,
            market_snapshot,
            technical_result,
            candidate_strategy_signal,
            regime,
            chart_score,
            news_score,
            derivatives_score,
            strategy_selection,
            account_state,
            config,
        )

        long_score = float(_get(chart_score, "long_score", 0.0) or 0.0)
        short_score = float(_get(chart_score, "short_score", 0.0) or 0.0)
        confidence = round(_clamp(max(long_score, short_score) / 100.0, 0.0, 1.0), 4)

        return DecisionResult(
            regime=regime,
            chart_score=chart_score,
            news_score=news_score,
            derivatives_score=derivatives_score,
            strategy_selection=strategy_selection,
            candidate=candidate,
            strategy_candidates=candidates,
            selected_strategy_candidate=selected_candidate,
            confidence=confidence,
            reasons=list(getattr(candidate, "reasons", []) or []),
        )
