"""
News & Sentiment Scorer — 결정적 뉴스·감성 리스크 필터.

규칙:
  - AI 호출 없음. 주문 없음. 순수 점수 함수.
  - 뉴스/감성은 직접 거래 트리거가 아니라 리스크 필터로 작동한다.
  - Positive news ≠ LONG 강제. Negative news ≠ SHORT 강제.
  - 주요 이벤트(high magnitude news) → no_trade_flag = True.
  - Extreme Greed → 롱 추격 경고 + 리스크 증가.
  - Extreme Fear → 기술적 확인 요구 경고 + 리스크 증가.
  - NEWS_EVENT 국면 → 리스크 증가 + no_trade_flag (설정에 따라).
  - HIGH_VOLATILITY 국면 → 리스크 증가.
  - 데이터 없음 → 안전한 중립 반환 (예외 없음).
  - 모든 출력 범위 클램프:
      sentiment_score: -100 ~ +100
      long/short_score_adjustment: -30 ~ +30
      risk_score: 0 ~ 100
"""
from __future__ import annotations

from typing import Any

from agents.decision.constants import (
    EXTREME_FEAR_RISK_BONUS,
    EXTREME_GREED_RISK_BONUS,
    FEAR_GREED_EXTREME_FEAR,
    FEAR_GREED_EXTREME_GREED,
    FEAR_GREED_FEAR,
    FEAR_GREED_GREED,
    HIGH_VOL_NEWS_RISK_BONUS,
    MAJOR_EVENT_NEWS_THRESHOLD,
    NEWS_EVENT_BLOCK,
    NEWS_EVENT_RISK_BONUS,
    NEWS_MAX_SCORE_ADJUSTMENT,
)
from agents.decision.models import MarketRegime, MarketRegimeResult, NewsSentimentScore


# ── 유틸리티 ─────────────────────────────────────────────────────────────────

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _cfg(config: dict | None, key: str, default: Any) -> Any:
    return config.get(key, default) if config else default


def _as_regime(market_regime: Any) -> MarketRegime:
    if isinstance(market_regime, MarketRegimeResult):
        return market_regime.regime
    if isinstance(market_regime, MarketRegime):
        return market_regime
    if market_regime is None:
        return MarketRegime.UNKNOWN
    try:
        return MarketRegime(str(market_regime))
    except ValueError:
        return MarketRegime.UNKNOWN


# ── 데이터 추출 헬퍼 ──────────────────────────────────────────────────────────

def _extract_news_score(news_data: Any) -> tuple[float, int]:
    """
    다양한 뉴스 데이터 형식에서 (composite_score, item_count) 를 추출한다.

    composite_score: -1.0 ~ +1.0 (양수=긍정, 음수=부정)
    item_count:      분석된 뉴스 아이템 수 (0이면 데이터 없음)

    지원 입력 형식:
      - SentimentResult duck type (.news_score, .news_items)
      - list[NewsItem duck type] (.score 필드)
      - list[dict]              ("score" 키)
      - None                    → (0.0, 0)
    """
    if news_data is None:
        return 0.0, 0

    # SentimentResult duck type (agents.sentiment.models.SentimentResult)
    if hasattr(news_data, "news_score"):
        raw = float(getattr(news_data, "news_score", 0.0) or 0.0)
        items = getattr(news_data, "news_items", []) or []
        return _clamp(raw, -1.0, 1.0), len(items)

    # list of NewsItem or dict
    if isinstance(news_data, (list, tuple)) and news_data:
        scores: list[float] = []
        for item in news_data:
            if hasattr(item, "score"):
                scores.append(float(item.score or 0.0))
            elif isinstance(item, dict):
                scores.append(float(item.get("score", 0.0) or 0.0))

        if not scores:
            return 0.0, 0

        # 역수 가중 평균 (첫 번째 항목 = 가장 최신)
        weights = [1.0 / (i + 1) for i in range(len(scores))]
        total_w = sum(weights)
        composite = sum(s * w for s, w in zip(scores, weights)) / total_w
        return _clamp(composite, -1.0, 1.0), len(scores)

    # dict 형식 ({"news_score": ..., "news_items": [...]})
    if isinstance(news_data, dict):
        raw = float(news_data.get("news_score", 0.0) or 0.0)
        items = news_data.get("news_items", []) or []
        return _clamp(raw, -1.0, 1.0), len(items)

    return 0.0, 0


def _extract_fear_greed(fear_greed_data: Any) -> tuple[int, float]:
    """
    다양한 F&G 형식에서 (index: 0-100, score: -1.0~+1.0 역발상) 를 추출한다.

    FearGreedData.score 는 이미 역발상 정규화된 값:
      index=0 → score=+1.0 (Extreme Fear → 역발상 매수 신호)
      index=50 → score=0.0
      index=100 → score=-1.0 (Extreme Greed → 역발상 매도 신호)
    """
    if fear_greed_data is None:
        return 50, 0.0

    # FearGreedData duck type
    if hasattr(fear_greed_data, "index"):
        idx = int(getattr(fear_greed_data, "index", 50) or 50)
        score = float(getattr(fear_greed_data, "score", 0.0) or 0.0)
        return _clamp_int(idx, 0, 100), _clamp(score, -1.0, 1.0)

    # dict 형식
    if isinstance(fear_greed_data, dict):
        idx = int(fear_greed_data.get("index", 50) or 50)
        score = float(fear_greed_data.get("score", (50 - idx) / 50.0) or 0.0)
        return _clamp_int(idx, 0, 100), _clamp(score, -1.0, 1.0)

    return 50, 0.0


def _clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


# ── 공개 API ─────────────────────────────────────────────────────────────────

def score_news_sentiment(
    news_data: Any | None,
    fear_greed_data: Any | None,
    market_regime: Any | None,
    config: dict | None = None,
) -> NewsSentimentScore:
    """
    뉴스·감성 리스크 점수를 계산한다.

    Parameters
    ----------
    news_data:        SentimentResult / list[NewsItem] / list[dict] / None.
    fear_greed_data:  FearGreedData / dict / None.
    market_regime:    MarketRegime / MarketRegimeResult / None.
    config:           런타임 임계값 오버라이드 dict (선택).
                      키:
                        "major_event_threshold" (float, 기본 0.80)
                        "extreme_greed_threshold" (int, 기본 75)
                        "extreme_fear_threshold"  (int, 기본 25)
                        "max_score_adjustment"    (float, 기본 15.0)
                        "news_event_block"        (bool, 기본 True)

    Returns
    -------
    NewsSentimentScore
      sentiment_score (-100~+100), long/short_score_adjustment, risk_score,
      no_trade_flag, reasons
    """
    # ── 데이터 추출 ────────────────────────────────────────────────────────
    news_score, news_count = _extract_news_score(news_data)
    fg_index, fg_score     = _extract_fear_greed(fear_greed_data)
    regime                 = _as_regime(market_regime)

    # ── 임계값 (constants 기본값 + config 오버라이드) ───────────────────────
    major_event_th  = float(_cfg(config, "major_event_threshold",  MAJOR_EVENT_NEWS_THRESHOLD))
    extreme_greed   = int(_cfg(config,   "extreme_greed_threshold", FEAR_GREED_EXTREME_GREED))
    extreme_fear    = int(_cfg(config,   "extreme_fear_threshold",  FEAR_GREED_EXTREME_FEAR))
    max_adj         = float(_cfg(config, "max_score_adjustment",    NEWS_MAX_SCORE_ADJUSTMENT))
    evt_block       = bool(_cfg(config,  "news_event_block",        NEWS_EVENT_BLOCK))

    reasons:    list[str] = []
    risk_score: float     = 0.0
    no_trade_flag:  bool  = False

    # ── 종합 감성 점수 (-100 ~ +100) ──────────────────────────────────────
    # 뉴스 65% + F&G 역발상 35%
    # fg_score 는 이미 역발상 정규화(Extreme Greed → 음수, Extreme Fear → 양수)
    combined_raw   = news_score * 0.65 + fg_score * 0.35
    sentiment_score = round(_clamp(combined_raw * 100, -100.0, 100.0), 1)

    # ── 방향 조정치 (소폭만 허용 — 뉴스는 트리거 아님) ─────────────────────
    long_adj:  float = 0.0
    short_adj: float = 0.0

    if sentiment_score > 10:
        long_adj = min(max_adj, abs(sentiment_score) * 0.12)
        reasons.append(
            f"긍정 감성 {sentiment_score:+.0f} → 롱 소폭 우대 (+{long_adj:.1f}pt, 트리거 아님)"
        )
    elif sentiment_score < -10:
        short_adj = min(max_adj, abs(sentiment_score) * 0.12)
        reasons.append(
            f"부정 감성 {sentiment_score:+.0f} → 숏 소폭 우대 (+{short_adj:.1f}pt, 트리거 아님)"
        )
    else:
        reasons.append(f"중립 감성 {sentiment_score:+.0f}")

    # ── Fear & Greed 분석 ─────────────────────────────────────────────────
    if fg_index >= extreme_greed:
        # Extreme Greed: 모두가 탐욕스러울 때 롱 추격 위험
        risk_score += EXTREME_GREED_RISK_BONUS
        long_adj   *= 0.5   # 롱 조정치 반감 (추격 억제)
        reasons.append(
            f"극단적 탐욕 (F&G {fg_index}) — 롱 추격 경계, "
            f"리스크 +{EXTREME_GREED_RISK_BONUS:.0f}pt"
        )
    elif fg_index >= FEAR_GREED_GREED:
        risk_score += 10.0
        reasons.append(f"탐욕 구간 (F&G {fg_index}) — 과매수 주의")
    elif fg_index <= extreme_fear:
        # Extreme Fear: 기술적 확인 없이 롱 진입 금지
        risk_score += EXTREME_FEAR_RISK_BONUS
        reasons.append(
            f"극단적 공포 (F&G {fg_index}) — 기술적 확인 필수, "
            f"리스크 +{EXTREME_FEAR_RISK_BONUS:.0f}pt"
        )
    elif fg_index <= FEAR_GREED_FEAR:
        risk_score += 5.0
        reasons.append(f"공포 구간 (F&G {fg_index}) — 시장 불안 주의")
    else:
        reasons.append(f"중립 F&G ({fg_index})")

    # ── 주요 이벤트 감지 ─────────────────────────────────────────────────
    # 뉴스 데이터가 실제로 있고, 방향이 강하게 쏠릴 때만 트리거
    if news_count > 0 and abs(news_score) >= major_event_th:
        no_trade_flag = True
        risk_score   += 40.0
        direction     = "긍정" if news_score > 0 else "부정"
        reasons.append(
            f"주요 이벤트 감지: {direction} 뉴스 강도 {abs(news_score):.2f} "
            f"≥ 임계값 {major_event_th:.2f} — no_trade_flag=True"
        )

    # ── 시장 국면 효과 ────────────────────────────────────────────────────
    if regime == MarketRegime.NEWS_EVENT:
        risk_score += NEWS_EVENT_RISK_BONUS
        if evt_block:
            no_trade_flag = True
            reasons.append(
                f"NEWS_EVENT 국면 — 신규 진입 차단, "
                f"리스크 +{NEWS_EVENT_RISK_BONUS:.0f}pt"
            )
        else:
            reasons.append(
                f"NEWS_EVENT 국면 — 리스크 증가 +{NEWS_EVENT_RISK_BONUS:.0f}pt (차단 비활성)"
            )
    elif regime == MarketRegime.HIGH_VOLATILITY:
        risk_score += HIGH_VOL_NEWS_RISK_BONUS
        reasons.append(
            f"HIGH_VOLATILITY 국면 — 감성 리스크 +{HIGH_VOL_NEWS_RISK_BONUS:.0f}pt"
        )
    elif regime == MarketRegime.UNKNOWN:
        risk_score += 10.0
        reasons.append("UNKNOWN 국면 — 감성 보수적 처리")

    # ── 데이터 없음 안내 ─────────────────────────────────────────────────
    if news_data is None:
        reasons.append("뉴스 데이터 없음 — 중립")
    elif news_count == 0:
        reasons.append("분석 가능한 뉴스 없음 — 중립")

    if fear_greed_data is None:
        reasons.append("F&G 데이터 없음 — 중립(50) 기본값 사용")

    return NewsSentimentScore(
        sentiment_score        = sentiment_score,
        long_score_adjustment  = round(_clamp(long_adj,  -30.0, 30.0), 2),
        short_score_adjustment = round(_clamp(short_adj, -30.0, 30.0), 2),
        risk_score             = round(_clamp(risk_score, 0.0, 100.0), 2),
        no_trade_flag          = no_trade_flag,
        reasons                = reasons,
    )
