"""
News & Sentiment Scorer 단위 테스트.

검증 항목:
  1. Positive news → sentiment_score 양수, but LONG 직접 강제 아님
     (long_score_adjustment < NEWS_MAX_SCORE_ADJUSTMENT 이하 소폭)
  2. Major event risk → no_trade_flag = True
  3. Extreme Greed → risk_score 증가, long_score_adjustment 반감
  4. Extreme Fear → no_trade_flag 아님, risk_score 증가, reasons 에 경고 포함
  5. Missing news data → 안전한 중립 반환 (예외 없음)
  6. Missing F&G data → 안전한 중립 반환 (예외 없음)
  7. 점수 유효 범위: sentiment ∈ [-100, 100], risk ∈ [0, 100], adj ∈ [-30, 30]
  8. Negative news → short 소폭 우대, LONG 강제 아님
  9. NEWS_EVENT 국면 → no_trade_flag + risk 증가
  10. HIGH_VOLATILITY 국면 → risk 증가 (no_trade_flag 아님)
  11. config 오버라이드 동작
  12. list[NewsItem duck-type] 형식 지원
  13. list[dict] 형식 지원
  14. SentimentResult duck-type 지원
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from agents.decision.constants import (
    EXTREME_GREED_RISK_BONUS,
    EXTREME_FEAR_RISK_BONUS,
    MAJOR_EVENT_NEWS_THRESHOLD,
    NEWS_MAX_SCORE_ADJUSTMENT,
)
from agents.decision.models import MarketRegime, NewsSentimentScore
from agents.decision.news_sentiment import score_news_sentiment


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────

@dataclass
class _NewsItem:
    score: float
    sentiment: str = "neutral"
    confidence: float = 0.5
    headline: str = "test"
    source: str = "test"
    published_at: str = "2025-01-01"


@dataclass
class _FearGreed:
    index: int
    label: str = "Neutral"
    score: float = 0.0

    def __post_init__(self) -> None:
        if self.score == 0.0:
            self.score = (50 - self.index) / 50.0


@dataclass
class _SentimentResult:
    news_score: float
    news_items: list = field(default_factory=list)
    fear_greed_index: int = 50
    sentiment_score: float = 0.0
    dominant_sentiment: str = "neutral"


def _news(score: float) -> _NewsItem:
    return _NewsItem(score=score, sentiment="positive" if score > 0 else "negative")


def _fg(index: int) -> _FearGreed:
    return _FearGreed(index=index)


# ── 1. Positive news → sentiment 양수, LONG 직접 강제 아님 ──────────────────

class TestPositiveNews:
    def test_positive_news_gives_positive_sentiment(self) -> None:
        items = [_news(0.7), _news(0.6), _news(0.5)]
        result = score_news_sentiment(items, _fg(50), None)
        assert result.sentiment_score > 0

    def test_positive_news_long_adjustment_limited(self) -> None:
        # 아무리 positive해도 max_adj 이하
        items = [_news(0.9), _news(0.9), _news(0.9)]
        result = score_news_sentiment(items, _fg(50), None)
        assert result.long_score_adjustment <= NEWS_MAX_SCORE_ADJUSTMENT

    def test_positive_news_no_trade_flag_false(self) -> None:
        items = [_news(0.5), _news(0.4)]
        result = score_news_sentiment(items, _fg(55), None)
        assert result.no_trade_flag is False

    def test_positive_news_short_adj_not_increased(self) -> None:
        items = [_news(0.7), _news(0.6)]
        result = score_news_sentiment(items, _fg(50), None)
        assert result.short_score_adjustment == 0.0


# ── 2. Major event risk → no_trade_flag = True ──────────────────────────────

class TestMajorEvent:
    def test_high_magnitude_news_sets_no_trade_flag(self) -> None:
        # |news_score| >= MAJOR_EVENT_NEWS_THRESHOLD(0.80) → no_trade_flag
        items = [_news(0.95), _news(0.92), _news(0.90)]
        result = score_news_sentiment(items, _fg(50), None)
        assert result.no_trade_flag is True

    def test_major_event_risk_score_elevated(self) -> None:
        items = [_news(0.95), _news(0.92)]
        result = score_news_sentiment(items, _fg(50), None)
        assert result.risk_score >= 40.0

    def test_below_threshold_no_flag(self) -> None:
        items = [_news(0.50), _news(0.40)]  # 가중평균 < 0.80
        result = score_news_sentiment(items, _fg(50), None)
        assert result.no_trade_flag is False

    def test_negative_major_event_sets_flag(self) -> None:
        items = [_news(-0.95), _news(-0.90), _news(-0.88)]
        result = score_news_sentiment(items, _fg(50), None)
        assert result.no_trade_flag is True

    def test_major_event_reason_in_output(self) -> None:
        items = [_news(0.95), _news(0.92)]
        result = score_news_sentiment(items, _fg(50), None)
        assert any("주요 이벤트" in r for r in result.reasons)


# ── 3. Extreme Greed → risk 증가, long_adj 반감 ──────────────────────────────

class TestExtremeGreed:
    def test_extreme_greed_increases_risk_score(self) -> None:
        result_normal  = score_news_sentiment([_news(0.4)], _fg(50), None)
        result_greedy  = score_news_sentiment([_news(0.4)], _fg(80), None)
        assert result_greedy.risk_score > result_normal.risk_score

    def test_extreme_greed_risk_bonus_applied(self) -> None:
        result = score_news_sentiment([_news(0.3)], _fg(85), None)
        assert result.risk_score >= EXTREME_GREED_RISK_BONUS

    def test_extreme_greed_long_adj_dampened(self) -> None:
        # 같은 긍정 뉴스라도 Extreme Greed 일 때 long_adj 더 낮음
        items = [_news(0.5), _news(0.4)]
        neutral_fg = score_news_sentiment(items, _fg(50), None)
        greed_fg   = score_news_sentiment(items, _fg(82), None)
        assert greed_fg.long_score_adjustment <= neutral_fg.long_score_adjustment

    def test_extreme_greed_reason_in_output(self) -> None:
        result = score_news_sentiment(None, _fg(80), None)
        assert any("탐욕" in r for r in result.reasons)


# ── 4. Extreme Fear → no_trade_flag 아님, risk 증가 ─────────────────────────

class TestExtremeFear:
    def test_extreme_fear_does_not_set_no_trade_flag(self) -> None:
        result = score_news_sentiment([_news(0.3)], _fg(15), None)
        assert result.no_trade_flag is False

    def test_extreme_fear_increases_risk_score(self) -> None:
        result = score_news_sentiment([_news(0.3)], _fg(15), None)
        assert result.risk_score >= EXTREME_FEAR_RISK_BONUS

    def test_extreme_fear_does_not_auto_force_long(self) -> None:
        # F&G 극단 공포 자체가 LONG 트리거가 아님 → short_adj 증가 없어야 함
        result = score_news_sentiment(None, _fg(10), None)
        assert result.short_score_adjustment == 0.0

    def test_extreme_fear_warning_in_reasons(self) -> None:
        result = score_news_sentiment(None, _fg(10), None)
        assert any("공포" in r for r in result.reasons)


# ── 5. Missing news data → 안전한 중립 ───────────────────────────────────────

class TestMissingNewsData:
    def test_none_news_no_exception(self) -> None:
        result = score_news_sentiment(None, _fg(50), None)
        assert isinstance(result, NewsSentimentScore)

    def test_none_news_no_trade_flag_false(self) -> None:
        result = score_news_sentiment(None, _fg(50), None)
        assert result.no_trade_flag is False

    def test_none_news_zero_long_adj(self) -> None:
        result = score_news_sentiment(None, _fg(50), None)
        assert result.long_score_adjustment == 0.0

    def test_none_news_reason_present(self) -> None:
        result = score_news_sentiment(None, _fg(50), None)
        assert any("없음" in r for r in result.reasons)

    def test_empty_list_no_exception(self) -> None:
        result = score_news_sentiment([], _fg(50), None)
        assert isinstance(result, NewsSentimentScore)


# ── 6. Missing F&G data → 안전한 중립 ───────────────────────────────────────

class TestMissingFearGreedData:
    def test_none_fg_no_exception(self) -> None:
        result = score_news_sentiment([_news(0.4)], None, None)
        assert isinstance(result, NewsSentimentScore)

    def test_none_fg_uses_neutral_default(self) -> None:
        result_none    = score_news_sentiment([_news(0.4)], None, None)
        result_neutral = score_news_sentiment([_news(0.4)], _fg(50), None)
        # F&G=50 과 None은 동일한 중립 처리
        assert result_none.sentiment_score == result_neutral.sentiment_score

    def test_none_fg_reason_present(self) -> None:
        result = score_news_sentiment(None, None, None)
        assert any("F&G" in r for r in result.reasons)

    def test_both_none_returns_safe_neutral(self) -> None:
        result = score_news_sentiment(None, None, None)
        assert result.no_trade_flag is False
        assert result.long_score_adjustment == 0.0
        assert result.short_score_adjustment == 0.0


# ── 7. 점수 유효 범위 ─────────────────────────────────────────────────────────

class TestScoreRanges:
    _cases = [
        ([_news(0.9), _news(0.9)], _fg(10),  None),
        ([_news(-0.9), _news(-0.9)], _fg(90), None),
        (None,                        None,    None),
        ([_news(0.5)],                _fg(80), MarketRegime.HIGH_VOLATILITY),
        ([_news(0.95)],               _fg(50), MarketRegime.NEWS_EVENT),
    ]

    @pytest.mark.parametrize("news,fg,regime", _cases)
    def test_sentiment_score_range(self, news, fg, regime) -> None:
        r = score_news_sentiment(news, fg, regime)
        assert -100.0 <= r.sentiment_score <= 100.0

    @pytest.mark.parametrize("news,fg,regime", _cases)
    def test_risk_score_range(self, news, fg, regime) -> None:
        r = score_news_sentiment(news, fg, regime)
        assert 0.0 <= r.risk_score <= 100.0

    @pytest.mark.parametrize("news,fg,regime", _cases)
    def test_long_adj_range(self, news, fg, regime) -> None:
        r = score_news_sentiment(news, fg, regime)
        assert -30.0 <= r.long_score_adjustment <= 30.0

    @pytest.mark.parametrize("news,fg,regime", _cases)
    def test_short_adj_range(self, news, fg, regime) -> None:
        r = score_news_sentiment(news, fg, regime)
        assert -30.0 <= r.short_score_adjustment <= 30.0

    @pytest.mark.parametrize("news,fg,regime", _cases)
    def test_reasons_is_list(self, news, fg, regime) -> None:
        r = score_news_sentiment(news, fg, regime)
        assert isinstance(r.reasons, list)


# ── 8. Negative news → short 소폭 우대, LONG 강제 아님 ──────────────────────

class TestNegativeNews:
    def test_negative_news_gives_negative_sentiment(self) -> None:
        items = [_news(-0.7), _news(-0.6)]
        result = score_news_sentiment(items, _fg(50), None)
        assert result.sentiment_score < 0

    def test_negative_news_short_adj_positive(self) -> None:
        items = [_news(-0.6), _news(-0.5)]
        result = score_news_sentiment(items, _fg(50), None)
        assert result.short_score_adjustment > 0

    def test_negative_news_long_adj_zero(self) -> None:
        items = [_news(-0.6), _news(-0.5)]
        result = score_news_sentiment(items, _fg(50), None)
        assert result.long_score_adjustment == 0.0

    def test_negative_news_short_adj_limited(self) -> None:
        items = [_news(-0.9), _news(-0.9), _news(-0.9)]
        result = score_news_sentiment(items, _fg(50), None)
        assert result.short_score_adjustment <= NEWS_MAX_SCORE_ADJUSTMENT


# ── 9. NEWS_EVENT 국면 ────────────────────────────────────────────────────────

class TestNewsEventRegime:
    def test_news_event_sets_no_trade_flag(self) -> None:
        result = score_news_sentiment(None, _fg(50), MarketRegime.NEWS_EVENT)
        assert result.no_trade_flag is True

    def test_news_event_increases_risk(self) -> None:
        result_normal = score_news_sentiment(None, _fg(50), None)
        result_event  = score_news_sentiment(None, _fg(50), MarketRegime.NEWS_EVENT)
        assert result_event.risk_score > result_normal.risk_score

    def test_news_event_block_false_no_flag(self) -> None:
        result = score_news_sentiment(
            None, _fg(50), MarketRegime.NEWS_EVENT,
            config={"news_event_block": False}
        )
        assert result.no_trade_flag is False

    def test_news_event_reason_present(self) -> None:
        result = score_news_sentiment(None, _fg(50), MarketRegime.NEWS_EVENT)
        assert any("NEWS_EVENT" in r for r in result.reasons)


# ── 10. HIGH_VOLATILITY 국면 ──────────────────────────────────────────────────

class TestHighVolatilityRegime:
    def test_high_vol_increases_risk(self) -> None:
        result_normal = score_news_sentiment(None, _fg(50), None)
        result_hv     = score_news_sentiment(None, _fg(50), MarketRegime.HIGH_VOLATILITY)
        assert result_hv.risk_score > result_normal.risk_score

    def test_high_vol_no_trade_flag_not_set(self) -> None:
        # HIGH_VOLATILITY 단독으로는 no_trade_flag 세우지 않음
        result = score_news_sentiment(None, _fg(50), MarketRegime.HIGH_VOLATILITY)
        assert result.no_trade_flag is False

    def test_high_vol_reason_present(self) -> None:
        result = score_news_sentiment(None, _fg(50), MarketRegime.HIGH_VOLATILITY)
        assert any("HIGH_VOLATILITY" in r for r in result.reasons)


# ── 11. Config 오버라이드 ─────────────────────────────────────────────────────

class TestConfigOverride:
    def test_lower_major_event_threshold(self) -> None:
        # threshold=0.40 으로 낮추면 평범한 뉴스도 major event 트리거
        items = [_news(0.6), _news(0.5)]
        normal  = score_news_sentiment(items, _fg(50), None)
        strict  = score_news_sentiment(
            items, _fg(50), None, config={"major_event_threshold": 0.40}
        )
        assert strict.no_trade_flag is True
        assert normal.no_trade_flag is False

    def test_higher_extreme_greed_threshold(self) -> None:
        # Extreme Greed 임계값을 높여 F&G=80 이 일반 탐욕으로만 처리
        r_default = score_news_sentiment(None, _fg(80), None)
        r_custom  = score_news_sentiment(
            None, _fg(80), None, config={"extreme_greed_threshold": 90}
        )
        # 기본은 Extreme Greed 처리 → 더 높은 risk; custom 은 아님
        assert r_default.risk_score > r_custom.risk_score


# ── 12-14. 입력 형식 지원 ────────────────────────────────────────────────────

class TestInputFormats:
    def test_list_of_newsitem_ducktype(self) -> None:
        items = [_news(0.6), _news(0.5), _news(0.4)]
        result = score_news_sentiment(items, _fg(50), None)
        assert result.sentiment_score > 0

    def test_list_of_dicts(self) -> None:
        items = [
            {"score": 0.7, "sentiment": "positive", "headline": "BTC up"},
            {"score": 0.5, "sentiment": "positive", "headline": "ETH rallies"},
        ]
        result = score_news_sentiment(items, _fg(50), None)
        assert result.sentiment_score > 0

    def test_sentiment_result_ducktype(self) -> None:
        sr = _SentimentResult(
            news_score=0.65,
            news_items=[_news(0.7), _news(0.6)],
        )
        result = score_news_sentiment(sr, _fg(50), None)
        assert result.sentiment_score > 0

    def test_fg_as_dict(self) -> None:
        fg_dict = {"index": 80, "label": "Extreme Greed", "score": -0.6}
        result = score_news_sentiment(None, fg_dict, None)
        assert result.risk_score >= EXTREME_GREED_RISK_BONUS

    def test_regime_as_string(self) -> None:
        result = score_news_sentiment(None, None, "HIGH_VOLATILITY")
        assert any("HIGH_VOLATILITY" in r for r in result.reasons)

    def test_regime_as_marketregime_enum(self) -> None:
        result = score_news_sentiment(None, None, MarketRegime.RANGE)
        assert isinstance(result, NewsSentimentScore)
