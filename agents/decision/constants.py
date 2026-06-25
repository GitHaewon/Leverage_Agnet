"""
Decision layer 임계값 상수.

이 파일은 agents/decision/ 레이어 전용이다.
agents/risk/constants.py 의 값과 목적이 다르므로 절대 혼용하지 않는다.

레이어 구분:
  agents/risk/constants.py   — Risk Engine 안전 게이트 (TRADING_RULES.md 1:1 매핑)
  agents/decision/constants  — 후보 생성·AI 리뷰·전략 선택 사전 필터

중요: Risk Engine은 agents/risk/constants.py 의 MIN_RR_RATIO = 2.0 을 최종 강제한다.
  여기서 정의하는 GLOBAL_MIN_RISK_REWARD_RATIO(1.2) 는 후보 생성 단계의 사전 필터이며
  Risk Engine 게이트를 대체하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass


# ── Risk 사전 필터 ─────────────────────────────────────────────────────────────
# Risk Engine(agents/risk/)의 hard limit 과 별개인 Decision 레이어 기본값.
# 사용자 플랜·프로파일 설정이 있으면 이 값을 덮어쓸 수 있다.

DECISION_MAX_LEVERAGE: int          = 10
DECISION_MAX_ENTRY_MARGIN_RATIO: float = 0.05     # 계좌 대비 증거금 상한 5%
DECISION_MAX_DAILY_LOSS_PCT: float  = 0.03        # 일일 손실 한도 3%
DECISION_MAX_WEEKLY_LOSS_PCT: float = 0.08        # 주간 손실 한도 8%
DECISION_MAX_CONSECUTIVE_LOSSES: int = 3          # 연속 손실 쿨다운 기준
DECISION_MAX_OPEN_POSITIONS: int    = 1           # 동시 오픈 포지션 상한

# 후보 생성 단계 R:R 하한 — Risk Engine 최종 게이트(MIN_RR_RATIO = 2.0)와 동일하게 설정.
# 1.2/1.5로 만든 TP는 RiskEngine에서 즉시 거부되므로 DOA 후보를 만들지 않는다.
GLOBAL_MIN_RISK_REWARD_RATIO: float = 2.0

MIN_EXPECTED_NET_PROFIT_PCT: float  = 0.001       # 예상 순수익 최소 0.1%
DECISION_MAX_SLIPPAGE_BPS: float    = 3.0         # 진입 허용 최대 슬리피지 (bps)
DECISION_MAX_SPREAD_BPS: float      = 5.0         # 진입 허용 최대 스프레드 (bps)

MARGIN_MODE: str                    = "isolated"  # "isolated" | "cross"
ALLOW_MARTINGALE: bool              = False       # 마틴게일 전략 허용 여부
ALLOW_AVERAGING_DOWN: bool          = False       # 물타기 허용 여부


# ── 수수료 및 슬리피지 ─────────────────────────────────────────────────────────

TAKER_FEE_RATE: float       = 0.0005    # 0.05% — 시장가 주문
MAKER_FEE_RATE: float       = 0.0002    # 0.02% — 지정가 주문
DEFAULT_SLIPPAGE_BPS: float = 3.0       # 기본 슬리피지 추정 (bps)


# ── 점수 및 AI 리뷰 임계값 ─────────────────────────────────────────────────────

MIN_LONG_SCORE: float  = 75.0   # SignalScore.long_score  최소값 (0~100 스케일)
MIN_SHORT_SCORE: float = 75.0   # SignalScore.short_score 최소값
MAX_RISK_SCORE: float  = 55.0   # SignalScore.risk_score  상한 (TREND_FOLLOWING 선택 천장과 정렬)

# AIReviewResult.confidence 는 float 0.0~1.0; 사용자 입력 70 → 0.70 변환
MIN_AI_REVIEW_CONFIDENCE: float          = 0.70
REJECT_ON_CRITICAL_CONTRADICTION: bool   = True


# ── 전략별 임계값 ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StrategyThresholds:
    """전략 유형별 후보 생성 임계값.

    min_risk_reward_ratio: 이 전략에서 요구하는 최소 R:R 사전 필터.
      Risk Engine의 MIN_RR_RATIO(2.0) 가 최종 강제되므로
      여기서 2.0 미만 값을 허용해도 Risk Engine에서 거부된다.
    max_holding_minutes: 이 전략의 예상 최대 보유 시간.
    max_spread_bps: 이 전략에서 허용하는 최대 스프레드 (bps).
    """
    min_risk_reward_ratio: float
    max_holding_minutes:   int
    max_spread_bps:        float


STRATEGY_THRESHOLDS: dict[str, StrategyThresholds] = {
    "SCALPING": StrategyThresholds(
        min_risk_reward_ratio = 2.0,   # RiskEngine MIN_RR_RATIO = 2.0 과 정렬
        max_holding_minutes   = 10,
        max_spread_bps        = 3.0,
    ),
    "INTRADAY": StrategyThresholds(
        min_risk_reward_ratio = 2.0,   # RiskEngine MIN_RR_RATIO = 2.0 과 정렬
        max_holding_minutes   = 60,
        max_spread_bps        = 5.0,
    ),
    "TREND_FOLLOWING": StrategyThresholds(
        min_risk_reward_ratio = 2.0,
        max_holding_minutes   = 240,
        max_spread_bps        = 8.0,
    ),
    "BREAKOUT": StrategyThresholds(
        min_risk_reward_ratio = 2.0,
        max_holding_minutes   = 120,
        max_spread_bps        = 6.0,
    ),
}

# ── 시장 국면별 전략 플레이북 ─────────────────────────────────────────────────
# 문자열 기반 adapter 규칙이다. 기존 StrategyType enum과 AggregatedSignal 구조는
# 유지하면서, ReviewerAgent가 후보 검토 전 사전 필터로 참고한다.

REGIME_ALLOWED_STRATEGIES: dict[str, tuple[str, ...]] = {
    "TREND_UP": (
        "TREND_FOLLOWING",
        "TREND_PULLBACK",
        "BREAKOUT",
        "BREAKOUT_RETEST",
        "INTRADAY",
    ),
    "TREND_DOWN": (
        "TREND_FOLLOWING",
        "TREND_PULLBACK",
        "BREAKOUT",
        "BREAKOUT_RETEST",
        "INTRADAY",
    ),
    "RANGE": (
        "MEAN_REVERSION",
        "RSI_REVERSAL",
        "SCALPING",
        "INTRADAY",
    ),
    "HIGH_VOLATILITY": (),
    "NEWS_EVENT": (),
    "UNKNOWN": (),
}

STRATEGY_MIN_RR: dict[str, float] = {
    "SCALPING": 2.0,
    "INTRADAY": 2.0,
    "TREND_FOLLOWING": 2.0,
    "TREND_PULLBACK": 2.0,
    "BREAKOUT": 2.0,
    "BREAKOUT_RETEST": 2.0,
    "MEAN_REVERSION": 2.0,
    "RSI_REVERSAL": 2.0,
    "UNKNOWN": 999.0,
}


def get_strategy_thresholds(strategy_type: str) -> StrategyThresholds:
    """전략 유형 문자열로 임계값 조회. 미등록 전략은 TREND_FOLLOWING 기준을 적용한다."""
    return STRATEGY_THRESHOLDS.get(
        strategy_type.upper(),
        STRATEGY_THRESHOLDS["TREND_FOLLOWING"],
    )


# ── 펀딩 / 변동성 / 뉴스 필터 ──────────────────────────────────────────────────

BLOCK_BEFORE_FUNDING_MINUTES: int = 10   # 펀딩 시간 N분 전 신규 진입 차단
BLOCK_AFTER_FUNDING_MINUTES: int  = 5    # 펀딩 시간 N분 후까지 신규 진입 차단
HIGH_VOLATILITY_BLOCK: bool       = True  # 고변동성 국면 신규 진입 차단
NEWS_EVENT_BLOCK: bool            = True  # 뉴스 이벤트 국면 신규 진입 차단


# ── 뉴스·감성 점수 임계값 ─────────────────────────────────────────────────────
# score_news_sentiment() 에서 사용. config dict 로 런타임 오버라이드 가능.

# Fear & Greed 구간 기준 (0-100 인덱스)
FEAR_GREED_EXTREME_GREED: int = 75   # ≥ 75 → Extreme Greed (롱 추격 위험)
FEAR_GREED_GREED: int         = 56   # ≥ 56 → Greed 구간
FEAR_GREED_FEAR: int          = 44   # ≤ 44 → Fear 구간
FEAR_GREED_EXTREME_FEAR: int  = 25   # ≤ 25 → Extreme Fear (기술적 확인 필수)

# 주요 이벤트 감지 — |뉴스 종합 점수| 가 이 값 이상이면 no_trade_flag = True
MAJOR_EVENT_NEWS_THRESHOLD: float = 0.80

# 리스크 점수 가산치
EXTREME_GREED_RISK_BONUS: float  = 20.0   # Extreme Greed → 리스크 증가
EXTREME_FEAR_RISK_BONUS: float   = 10.0   # Extreme Fear → 리스크 증가
HIGH_VOL_NEWS_RISK_BONUS: float  = 25.0   # HIGH_VOLATILITY 국면 → 감성 리스크 증가
NEWS_EVENT_RISK_BONUS: float     = 35.0   # NEWS_EVENT 국면 → 감성 리스크 증가

# 뉴스 방향 점수 조정 상한
# 뉴스가 long_score / short_score 에 직접 가할 수 있는 최대 조정치
# 낮게 유지해야 '뉴스 = 트리거'가 되지 않음
NEWS_MAX_SCORE_ADJUSTMENT: float = 15.0

# ── 시장 국면 분류 임계값 ─────────────────────────────────────────────────────
# classify_market_regime() 에서 사용. config dict 로 런타임 오버라이드 가능.

# 고변동성 (HIGH_VOLATILITY) 트리거 — 아래 중 REGIME_MIN_SIGNALS개 이상 동시 만족 시 분류
BB_HIGH_VOL_BANDWIDTH_PCT: float = 10.0   # BB bandwidth > 10% → 고변동 신호
ATR_HIGH_VOL_PCT: float          = 3.0    # ATR/현재가 > 3% → 고변동 신호
VOLUME_SPIKE_RATIO: float        = 2.0    # volume_ratio > 2.0 → 거래량 급증 신호

# 횡보 (RANGE) 트리거
BB_RANGE_BANDWIDTH_PCT: float    = 5.0    # BB bandwidth < 5% → 횡보 신호

# 추세 (TREND_UP / TREND_DOWN) 트리거
TECH_SCORE_TREND_THRESHOLD: float = 0.30  # |tech_score| > 0.30 → 추세 신호
TECH_SCORE_RANGE_THRESHOLD: float = 0.20  # |tech_score| < 0.20 → 횡보 신호

# 최소 신호 합의 수: 이 값 이상 동시 만족해야 해당 국면으로 분류
REGIME_MIN_SIGNALS: int = 2

# ── 전략 선택 임계값 ─────────────────────────────────────────────────────────────
# select_strategy_type() 에서 사용. config dict 로 런타임 오버라이드 가능.

# 통합 리스크 = chart_risk*0.4 + news_risk*0.3 + deriv_risk*0.3

# TREND_FOLLOWING 선택 기준
STRATEGY_MIN_TREND_DIR_SCORE: float     = 55.0  # 방향 점수(long or short) 최소값
STRATEGY_MAX_RISK_FOR_TREND: float      = 55.0  # 통합 리스크 상한

# BREAKOUT 선택 기준
STRATEGY_MIN_BREAKOUT_VOL_RATIO: float  = 1.8   # 거래량 급증 배율 최소값
STRATEGY_MAX_BREAKOUT_PRICE_MOVE: float = 3.0   # 이미 이동한 가격 최대 % (기회 소멸)
STRATEGY_MAX_RISK_FOR_BREAKOUT: float   = 50.0  # 통합 리스크 상한

# INTRADAY 선택 기준
STRATEGY_MIN_INTRADAY_DIR_SCORE: float  = 35.0  # 방향 점수 최소값
STRATEGY_MAX_RISK_FOR_INTRADAY: float   = 60.0  # 통합 리스크 상한

# SCALPING 선택 기준
STRATEGY_MIN_SCALPING_DIR_SCORE: float  = 20.0  # 방향 점수 최소값
STRATEGY_MAX_RISK_FOR_SCALPING: float   = 40.0  # 통합 리스크 상한

# 전략별 예상 보유 시간 (분, 구간 중앙값)
STRATEGY_HOLDING_MINUTES: dict[str, int] = {
    "SCALPING":        5,
    "INTRADAY":        30,
    "TREND_FOLLOWING": 120,
    "BREAKOUT":        60,
    "UNKNOWN":         0,
}


# ── 주문 실행 규칙 ─────────────────────────────────────────────────────────────
# CLAUDE.md 절대 규칙과 1:1 대응. 이 값을 False 로 변경하려면 CTO 승인 필요.

REQUIRE_STOP_LOSS: bool        = True    # SL 없는 주문 금지 (절대 규칙)
REQUIRE_TAKE_PROFIT: bool      = True    # TP 없는 주문 금지
REDUCE_ONLY_EXIT_ORDERS: bool  = True    # TP/SL 주문은 reduce_only=True 강제
CLOSE_IF_SL_TP_FAIL: bool      = True    # TP/SL 설정 실패 시 긴급 청산
ISOLATED_MARGIN_ONLY: bool     = True    # Cross 마진 사용 금지
