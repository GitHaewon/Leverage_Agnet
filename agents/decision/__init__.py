"""
Decision layer — 결정적 후보 생성 및 AI 리뷰 데이터 모델 + 임계값 상수.

이 패키지는 외부 에이전트 모듈(analyst, risk, strategy)에 의존하지 않는다.
순환 임포트 방지를 위해 agents.* 임포트를 허용하지 않는다.
"""
from agents.decision.models import (
    AIReviewAction,
    AIReviewResult,
    DerivativesMarketScore,
    FinalAction,
    FinalDecision,
    MarketRegime,
    MarketRegimeResult,
    NewsSentimentScore,
    RiskCheckResult,
    SignalScore,
    StrategySelectionResult,
    StrategyType,
    TradeCandidate,
)
from agents.decision.regime import classify_market_regime
from agents.decision.chart_signals import score_chart_signals
from agents.decision.news_sentiment import score_news_sentiment
from agents.decision.derivatives_market import score_derivatives_market
from agents.decision.strategy_selector import select_strategy_type
from agents.decision.candidate_generator import generate_trade_candidate
from agents.decision.constants import (
    # Risk 사전 필터
    DECISION_MAX_LEVERAGE,
    DECISION_MAX_ENTRY_MARGIN_RATIO,
    DECISION_MAX_DAILY_LOSS_PCT,
    DECISION_MAX_WEEKLY_LOSS_PCT,
    DECISION_MAX_CONSECUTIVE_LOSSES,
    DECISION_MAX_OPEN_POSITIONS,
    GLOBAL_MIN_RISK_REWARD_RATIO,
    MIN_EXPECTED_NET_PROFIT_PCT,
    DECISION_MAX_SLIPPAGE_BPS,
    DECISION_MAX_SPREAD_BPS,
    MARGIN_MODE,
    ALLOW_MARTINGALE,
    ALLOW_AVERAGING_DOWN,
    # 수수료
    TAKER_FEE_RATE,
    MAKER_FEE_RATE,
    DEFAULT_SLIPPAGE_BPS,
    # 점수·AI 리뷰
    MIN_LONG_SCORE,
    MIN_SHORT_SCORE,
    MAX_RISK_SCORE,
    MIN_AI_REVIEW_CONFIDENCE,
    REJECT_ON_CRITICAL_CONTRADICTION,
    # 전략
    StrategyThresholds,
    STRATEGY_THRESHOLDS,
    get_strategy_thresholds,
    # 필터
    BLOCK_BEFORE_FUNDING_MINUTES,
    BLOCK_AFTER_FUNDING_MINUTES,
    HIGH_VOLATILITY_BLOCK,
    NEWS_EVENT_BLOCK,
    # 전략 선택 임계값
    STRATEGY_MIN_TREND_DIR_SCORE,
    STRATEGY_MAX_RISK_FOR_TREND,
    STRATEGY_MIN_BREAKOUT_VOL_RATIO,
    STRATEGY_MAX_BREAKOUT_PRICE_MOVE,
    STRATEGY_MAX_RISK_FOR_BREAKOUT,
    STRATEGY_MIN_INTRADAY_DIR_SCORE,
    STRATEGY_MAX_RISK_FOR_INTRADAY,
    STRATEGY_MIN_SCALPING_DIR_SCORE,
    STRATEGY_MAX_RISK_FOR_SCALPING,
    STRATEGY_HOLDING_MINUTES,
    # 실행 규칙
    REQUIRE_STOP_LOSS,
    REQUIRE_TAKE_PROFIT,
    REDUCE_ONLY_EXIT_ORDERS,
    CLOSE_IF_SL_TP_FAIL,
    ISOLATED_MARGIN_ONLY,
)

__all__ = [
    # 분류·점수 함수
    "classify_market_regime",
    "score_chart_signals",
    "score_news_sentiment",
    "score_derivatives_market",
    "select_strategy_type",
    "generate_trade_candidate",
    # 모델
    "AIReviewAction",
    "AIReviewResult",
    "DerivativesMarketScore",
    "FinalAction",
    "FinalDecision",
    "MarketRegime",
    "MarketRegimeResult",
    "NewsSentimentScore",
    "RiskCheckResult",
    "SignalScore",
    "StrategySelectionResult",
    "StrategyType",
    "TradeCandidate",
    # 상수 — Risk 사전 필터
    "DECISION_MAX_LEVERAGE",
    "DECISION_MAX_ENTRY_MARGIN_RATIO",
    "DECISION_MAX_DAILY_LOSS_PCT",
    "DECISION_MAX_WEEKLY_LOSS_PCT",
    "DECISION_MAX_CONSECUTIVE_LOSSES",
    "DECISION_MAX_OPEN_POSITIONS",
    "GLOBAL_MIN_RISK_REWARD_RATIO",
    "MIN_EXPECTED_NET_PROFIT_PCT",
    "DECISION_MAX_SLIPPAGE_BPS",
    "DECISION_MAX_SPREAD_BPS",
    "MARGIN_MODE",
    "ALLOW_MARTINGALE",
    "ALLOW_AVERAGING_DOWN",
    # 상수 — 수수료
    "TAKER_FEE_RATE",
    "MAKER_FEE_RATE",
    "DEFAULT_SLIPPAGE_BPS",
    # 상수 — 점수·AI 리뷰
    "MIN_LONG_SCORE",
    "MIN_SHORT_SCORE",
    "MAX_RISK_SCORE",
    "MIN_AI_REVIEW_CONFIDENCE",
    "REJECT_ON_CRITICAL_CONTRADICTION",
    # 상수 — 전략
    "StrategyThresholds",
    "STRATEGY_THRESHOLDS",
    "get_strategy_thresholds",
    # 상수 — 필터
    "BLOCK_BEFORE_FUNDING_MINUTES",
    "BLOCK_AFTER_FUNDING_MINUTES",
    "HIGH_VOLATILITY_BLOCK",
    "NEWS_EVENT_BLOCK",
    # 상수 — 전략 선택
    "STRATEGY_MIN_TREND_DIR_SCORE",
    "STRATEGY_MAX_RISK_FOR_TREND",
    "STRATEGY_MIN_BREAKOUT_VOL_RATIO",
    "STRATEGY_MAX_BREAKOUT_PRICE_MOVE",
    "STRATEGY_MAX_RISK_FOR_BREAKOUT",
    "STRATEGY_MIN_INTRADAY_DIR_SCORE",
    "STRATEGY_MAX_RISK_FOR_INTRADAY",
    "STRATEGY_MIN_SCALPING_DIR_SCORE",
    "STRATEGY_MAX_RISK_FOR_SCALPING",
    "STRATEGY_HOLDING_MINUTES",
    # 상수 — 실행 규칙
    "REQUIRE_STOP_LOSS",
    "REQUIRE_TAKE_PROFIT",
    "REDUCE_ONLY_EXIT_ORDERS",
    "CLOSE_IF_SL_TP_FAIL",
    "ISOLATED_MARGIN_ONLY",
]
