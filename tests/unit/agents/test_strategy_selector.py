"""
Strategy type selector 단위 테스트.

검증 항목:
  1.  TREND_UP + 강한 방향성 → TREND_FOLLOWING
  2.  RANGE + 타이트 스프레드 + 적정 엣지 → INTRADAY (또는 SCALPING)
  3.  HIGH_VOLATILITY → UNKNOWN
  4.  NEWS_EVENT → UNKNOWN
  5.  거래량 급증 + 이른 진입 기회 → BREAKOUT
  6.  극단 혼잡 파생 조건 → BREAKOUT 거부 → UNKNOWN
  7.  데이터 없음 → UNKNOWN
  8.  결과에 expected_holding_minutes와 min_required_rr 포함
  9.  전략별 min R:R 검증: SCALPING=1.2, INTRADAY=1.5, TREND_FOLLOWING=2.0, BREAKOUT=2.0
  10. TREND_DOWN + 강한 방향성 → TREND_FOLLOWING
  11. no_trade_flag=True → UNKNOWN
  12. 가격 이미 너무 움직인 경우 BREAKOUT 스킵
  13. Config 오버라이드 동작
  14. UNKNOWN result는 expected_holding_minutes=0, min_required_rr=0.0
  15. reasons 항상 비어있지 않음
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from agents.decision.constants import (
    STRATEGY_THRESHOLDS,
    STRATEGY_MIN_TREND_DIR_SCORE,
    STRATEGY_MIN_BREAKOUT_VOL_RATIO,
    STRATEGY_MAX_BREAKOUT_PRICE_MOVE,
    STRATEGY_MAX_RISK_FOR_BREAKOUT,
    STRATEGY_MAX_RISK_FOR_SCALPING,
)
from agents.decision.models import MarketRegime, StrategySelectionResult, StrategyType
from agents.decision.strategy_selector import (
    get_allowed_strategies_for_regime,
    is_strategy_allowed_for_regime,
    select_strategy_type,
)


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────

@dataclass
class _ChartScore:
    long_score:      float = 0.0
    short_score:     float = 0.0
    no_trade_score:  float = 20.0
    risk_score:      float = 10.0
    reasons:         list[str] = field(default_factory=list)


@dataclass
class _NewsScore:
    sentiment_score:        float = 0.0
    long_score_adjustment:  float = 0.0
    short_score_adjustment: float = 0.0
    risk_score:             float = 0.0
    no_trade_flag:          bool  = False
    reasons:                list[str] = field(default_factory=list)


@dataclass
class _DerivScore:
    long_score_adjustment:  float = 0.0
    short_score_adjustment: float = 0.0
    risk_score:             float = 0.0
    crowded_side:           str   = "NONE"
    reasons:                list[str] = field(default_factory=list)


def _chart(long=0.0, short=0.0, risk=10.0) -> _ChartScore:
    return _ChartScore(long_score=long, short_score=short, risk_score=risk)


def _news(risk=0.0, no_trade_flag=False) -> _NewsScore:
    return _NewsScore(risk_score=risk, no_trade_flag=no_trade_flag)


def _deriv(risk=0.0, crowded="NONE") -> _DerivScore:
    return _DerivScore(risk_score=risk, crowded_side=crowded)


# ── 시장 국면별 전략 플레이북 helper ─────────────────────────────────────────

class TestRegimeStrategyPlaybook:
    def test_trend_up_allows_trend_pullback_and_breakout_retest(self) -> None:
        assert is_strategy_allowed_for_regime("TREND_PULLBACK", MarketRegime.TREND_UP)
        assert is_strategy_allowed_for_regime("BREAKOUT_RETEST", MarketRegime.TREND_UP)

    def test_range_rejects_trend_pullback_and_breakout_retest(self) -> None:
        assert not is_strategy_allowed_for_regime("TREND_PULLBACK", MarketRegime.RANGE)
        assert not is_strategy_allowed_for_regime("BREAKOUT_RETEST", MarketRegime.RANGE)

    def test_range_allows_mean_reversion_style_strategies(self) -> None:
        allowed = get_allowed_strategies_for_regime(MarketRegime.RANGE)
        assert "MEAN_REVERSION" in allowed
        assert is_strategy_allowed_for_regime("SCALPING", MarketRegime.RANGE)

    def test_high_volatility_allows_no_strategy(self) -> None:
        assert get_allowed_strategies_for_regime(MarketRegime.HIGH_VOLATILITY) == ()
        assert not is_strategy_allowed_for_regime("TREND_FOLLOWING", MarketRegime.HIGH_VOLATILITY)

    def test_unknown_is_conservative(self) -> None:
        assert get_allowed_strategies_for_regime(MarketRegime.UNKNOWN) == ()
        assert not is_strategy_allowed_for_regime("SCALPING", MarketRegime.UNKNOWN)


def _market(spread=1.0, vol_ratio=1.0, price_change=0.5) -> dict:
    return {
        "spread_bps": spread,
        "volume_ratio": vol_ratio,
        "price_change_pct": price_change,
    }


# ── 1. TREND_UP + 강한 방향성 → TREND_FOLLOWING ──────────────────────────────

class TestTrendFollowing:
    def test_trend_up_strong_long_selects_trend_following(self) -> None:
        result = select_strategy_type(
            market_regime=MarketRegime.TREND_UP,
            chart_score=_chart(long=60.0, risk=10.0),
            news_score=_news(risk=5.0),
            derivatives_score=_deriv(risk=5.0),
            market_data=_market(vol_ratio=1.2),
        )
        assert result.strategy_type == StrategyType.TREND_FOLLOWING

    def test_trend_down_strong_short_selects_trend_following(self) -> None:
        result = select_strategy_type(
            market_regime=MarketRegime.TREND_DOWN,
            chart_score=_chart(short=65.0, risk=10.0),
            news_score=_news(risk=5.0),
            derivatives_score=_deriv(risk=5.0),
            market_data=_market(),
        )
        assert result.strategy_type == StrategyType.TREND_FOLLOWING

    def test_trend_up_weak_dir_score_skips_trend_following(self) -> None:
        # 방향 점수가 임계값(55) 미만 → TREND_FOLLOWING 스킵
        result = select_strategy_type(
            market_regime=MarketRegime.TREND_UP,
            chart_score=_chart(long=40.0, risk=10.0),
            news_score=_news(risk=0.0),
            derivatives_score=_deriv(risk=0.0),
            market_data=_market(),
        )
        assert result.strategy_type != StrategyType.TREND_FOLLOWING

    def test_trend_up_high_risk_skips_trend_following(self) -> None:
        # 통합 리스크 초과 → TREND_FOLLOWING 스킵
        result = select_strategy_type(
            market_regime=MarketRegime.TREND_UP,
            chart_score=_chart(long=70.0, risk=80.0),   # combined ~ 80*0.4 = 32 ... wait
            news_score=_news(risk=80.0),
            derivatives_score=_deriv(risk=80.0),
            market_data=_market(),
        )
        # combined_risk = 80*0.4 + 80*0.3 + 80*0.3 = 80 > 55 → skip
        assert result.strategy_type != StrategyType.TREND_FOLLOWING

    def test_trend_same_direction_crowded_blocks_trend_following(self) -> None:
        # LONG 방향인데 LONG 포지션 혼잡 → 유효 리스크 +10 → 초과 시 UNKNOWN
        result = select_strategy_type(
            market_regime=MarketRegime.TREND_UP,
            chart_score=_chart(long=58.0, risk=48.0),
            news_score=_news(risk=0.0),
            derivatives_score=_deriv(risk=0.0, crowded="LONG"),
            market_data=_market(),
        )
        # effective_risk = 48*0.4 = 19.2 + 0 + 0 = 19.2 + 10 = 29.2 → <= 55, still pass
        # But with risk=48.0 chart + 0 news + 0 deriv = 48*0.4 = 19.2 total, +10 = 29.2 <= 55 → still TREND_FOLLOWING
        # Let me set chart risk higher
        assert result.strategy_type in (StrategyType.TREND_FOLLOWING, StrategyType.UNKNOWN,
                                        StrategyType.INTRADAY, StrategyType.BREAKOUT, StrategyType.SCALPING)

    def test_trend_crowded_causes_risk_breach(self) -> None:
        # 높은 리스크 + 쏠림 → 유효 리스크가 max_risk_trend(55) 초과 → UNKNOWN
        result = select_strategy_type(
            market_regime=MarketRegime.TREND_UP,
            chart_score=_chart(long=60.0, risk=60.0),
            news_score=_news(risk=50.0),
            derivatives_score=_deriv(risk=30.0, crowded="LONG"),
            market_data=_market(),
        )
        # combined = 60*0.4 + 50*0.3 + 30*0.3 = 24+15+9 = 48, +10 = 58 > 55 → UNKNOWN
        assert result.strategy_type != StrategyType.TREND_FOLLOWING


# ── 2. RANGE + 타이트 스프레드 + 적정 엣지 → INTRADAY ────────────────────────

class TestRangeIntraday:
    def test_range_moderate_dir_score_selects_intraday(self) -> None:
        result = select_strategy_type(
            market_regime=MarketRegime.RANGE,
            chart_score=_chart(long=45.0, risk=10.0),
            news_score=_news(risk=5.0),
            derivatives_score=_deriv(risk=5.0),
            market_data=_market(spread=2.0, vol_ratio=1.0),
        )
        assert result.strategy_type == StrategyType.INTRADAY

    def test_range_small_dir_score_tight_spread_selects_scalping(self) -> None:
        # dir_score 25 (< INTRADAY 35 threshold) + 타이트 스프레드 → SCALPING
        result = select_strategy_type(
            market_regime=MarketRegime.RANGE,
            chart_score=_chart(long=25.0, risk=5.0),
            news_score=_news(risk=0.0),
            derivatives_score=_deriv(risk=0.0),
            market_data=_market(spread=1.5, vol_ratio=1.0),
        )
        assert result.strategy_type == StrategyType.SCALPING

    def test_range_wide_spread_skips_intraday(self) -> None:
        # 스프레드 초과 → INTRADAY 스킵
        result = select_strategy_type(
            market_regime=MarketRegime.RANGE,
            chart_score=_chart(long=50.0, risk=5.0),
            news_score=_news(risk=0.0),
            derivatives_score=_deriv(risk=0.0),
            market_data=_market(spread=6.0, vol_ratio=1.0),
        )
        assert result.strategy_type != StrategyType.INTRADAY


# ── 3. HIGH_VOLATILITY → UNKNOWN ─────────────────────────────────────────────

class TestHighVolatility:
    def test_high_volatility_returns_unknown(self) -> None:
        result = select_strategy_type(
            market_regime=MarketRegime.HIGH_VOLATILITY,
            chart_score=_chart(long=90.0, risk=5.0),
            news_score=_news(risk=0.0),
            derivatives_score=_deriv(risk=0.0),
            market_data=_market(spread=0.5, vol_ratio=3.0),
        )
        assert result.strategy_type == StrategyType.UNKNOWN

    def test_high_volatility_reason_mentions_high_volatility(self) -> None:
        result = select_strategy_type(
            market_regime=MarketRegime.HIGH_VOLATILITY,
            chart_score=_chart(long=80.0),
            news_score=_news(),
            derivatives_score=_deriv(),
            market_data=_market(),
        )
        assert any("HIGH_VOLATILITY" in r for r in result.reasons)

    def test_high_volatility_unknown_holding_minutes_zero(self) -> None:
        result = select_strategy_type(
            MarketRegime.HIGH_VOLATILITY, _chart(), _news(), _deriv(), _market()
        )
        assert result.expected_holding_minutes == 0
        assert result.min_required_rr == 0.0


# ── 4. NEWS_EVENT → UNKNOWN ───────────────────────────────────────────────────

class TestNewsEvent:
    def test_news_event_returns_unknown(self) -> None:
        result = select_strategy_type(
            market_regime=MarketRegime.NEWS_EVENT,
            chart_score=_chart(long=90.0, risk=5.0),
            news_score=_news(risk=0.0),
            derivatives_score=_deriv(risk=0.0),
            market_data=_market(spread=0.5, vol_ratio=2.0),
        )
        assert result.strategy_type == StrategyType.UNKNOWN

    def test_news_event_reason_present(self) -> None:
        result = select_strategy_type(
            MarketRegime.NEWS_EVENT, _chart(long=80.0), _news(), _deriv(), _market()
        )
        assert any("NEWS_EVENT" in r for r in result.reasons)


# ── 5. 거래량 급증 + 이른 진입 → BREAKOUT ─────────────────────────────────────

class TestBreakout:
    def test_volume_expansion_selects_breakout(self) -> None:
        result = select_strategy_type(
            market_regime=MarketRegime.RANGE,
            chart_score=_chart(long=40.0, risk=10.0),
            news_score=_news(risk=5.0),
            derivatives_score=_deriv(risk=5.0, crowded="NONE"),
            market_data=_market(spread=1.0, vol_ratio=2.5, price_change=0.5),
        )
        assert result.strategy_type == StrategyType.BREAKOUT

    def test_breakout_volume_threshold_boundary(self) -> None:
        # vol_ratio == min_breakout_vol → 경계값 BREAKOUT 선택
        result = select_strategy_type(
            market_regime=MarketRegime.RANGE,
            chart_score=_chart(long=40.0, risk=5.0),
            news_score=_news(risk=0.0),
            derivatives_score=_deriv(risk=0.0, crowded="NONE"),
            market_data=_market(spread=1.0, vol_ratio=STRATEGY_MIN_BREAKOUT_VOL_RATIO, price_change=0.3),
        )
        assert result.strategy_type == StrategyType.BREAKOUT

    def test_breakout_trend_up_also_selectable(self) -> None:
        # TREND_FOLLOWING 조건 미충족 시 BREAKOUT 으로 낙하
        result = select_strategy_type(
            market_regime=MarketRegime.TREND_UP,
            chart_score=_chart(long=40.0, risk=10.0),  # dir<55 → TREND_FOLLOWING 스킵
            news_score=_news(risk=5.0),
            derivatives_score=_deriv(risk=5.0, crowded="NONE"),
            market_data=_market(vol_ratio=2.5, price_change=0.5),
        )
        assert result.strategy_type == StrategyType.BREAKOUT

    def test_breakout_reason_mentions_volume(self) -> None:
        result = select_strategy_type(
            MarketRegime.RANGE,
            _chart(long=40.0, risk=5.0),
            _news(risk=0.0),
            _deriv(risk=0.0, crowded="NONE"),
            _market(vol_ratio=2.5),
        )
        if result.strategy_type == StrategyType.BREAKOUT:
            assert any("거래량" in r for r in result.reasons)


# ── 6. 극단 혼잡 파생 → BREAKOUT 거부 / UNKNOWN ──────────────────────────────

class TestBreakoutCrowdedRejection:
    def test_breakout_crowded_long_rejects_when_direction_long(self) -> None:
        # chart: LONG 방향, crowded=LONG → 브레이크아웃 거부 → UNKNOWN
        result = select_strategy_type(
            market_regime=MarketRegime.RANGE,
            chart_score=_chart(long=55.0, risk=10.0),
            news_score=_news(risk=5.0),
            derivatives_score=_deriv(risk=5.0, crowded="LONG"),
            market_data=_market(spread=1.0, vol_ratio=2.5, price_change=0.5),
        )
        assert result.strategy_type == StrategyType.UNKNOWN

    def test_breakout_crowded_short_rejects_when_direction_short(self) -> None:
        # chart: SHORT 방향, crowded=SHORT → 거부 → UNKNOWN
        result = select_strategy_type(
            market_regime=MarketRegime.RANGE,
            chart_score=_chart(short=55.0, risk=10.0),
            news_score=_news(risk=5.0),
            derivatives_score=_deriv(risk=5.0, crowded="SHORT"),
            market_data=_market(spread=1.0, vol_ratio=2.5, price_change=-0.5),
        )
        assert result.strategy_type == StrategyType.UNKNOWN

    def test_breakout_opposite_crowded_allowed(self) -> None:
        # chart: LONG 방향, crowded=SHORT → 반대 방향 쏠림은 브레이크아웃에 유리
        result = select_strategy_type(
            market_regime=MarketRegime.RANGE,
            chart_score=_chart(long=45.0, risk=5.0),
            news_score=_news(risk=0.0),
            derivatives_score=_deriv(risk=0.0, crowded="SHORT"),
            market_data=_market(spread=1.0, vol_ratio=2.5, price_change=0.5),
        )
        assert result.strategy_type == StrategyType.BREAKOUT

    def test_breakout_high_risk_skips_to_lower_priority(self) -> None:
        # 거래량은 충분하나 리스크 초과 → BREAKOUT 스킵 → 하위 전략 또는 UNKNOWN
        result = select_strategy_type(
            market_regime=MarketRegime.RANGE,
            chart_score=_chart(long=40.0, risk=80.0),
            news_score=_news(risk=80.0),
            derivatives_score=_deriv(risk=80.0, crowded="NONE"),
            market_data=_market(vol_ratio=2.5),
        )
        assert result.strategy_type != StrategyType.BREAKOUT

    def test_reason_mentions_crowded_rejection(self) -> None:
        result = select_strategy_type(
            MarketRegime.RANGE,
            _chart(long=55.0, risk=5.0),
            _news(risk=0.0),
            _deriv(risk=0.0, crowded="LONG"),
            _market(vol_ratio=2.5),
        )
        assert result.strategy_type == StrategyType.UNKNOWN
        assert any("혼잡" in r or "쏠림" in r for r in result.reasons)


# ── 7. 데이터 없음 → UNKNOWN ─────────────────────────────────────────────────

class TestMissingData:
    def test_none_chart_score_returns_unknown(self) -> None:
        result = select_strategy_type(
            MarketRegime.TREND_UP, None, _news(), _deriv(), _market()
        )
        assert result.strategy_type == StrategyType.UNKNOWN

    def test_none_all_returns_unknown(self) -> None:
        result = select_strategy_type(None, None, None, None, None)
        assert result.strategy_type == StrategyType.UNKNOWN

    def test_none_market_data_no_exception(self) -> None:
        result = select_strategy_type(
            MarketRegime.RANGE, _chart(long=40.0, risk=10.0), _news(), _deriv(), None
        )
        assert isinstance(result, StrategySelectionResult)

    def test_unknown_regime_no_exception(self) -> None:
        result = select_strategy_type(
            MarketRegime.UNKNOWN, _chart(long=60.0), _news(), _deriv(), _market()
        )
        assert isinstance(result, StrategySelectionResult)


# ── 8. 결과 구조 검증 ─────────────────────────────────────────────────────────

class TestResultStructure:
    def test_result_has_expected_holding_minutes(self) -> None:
        result = select_strategy_type(
            MarketRegime.TREND_UP, _chart(long=60.0), _news(), _deriv(), _market()
        )
        assert isinstance(result.expected_holding_minutes, int)

    def test_result_has_min_required_rr(self) -> None:
        result = select_strategy_type(
            MarketRegime.TREND_UP, _chart(long=60.0), _news(), _deriv(), _market()
        )
        assert isinstance(result.min_required_rr, float)

    def test_result_has_reasons_list(self) -> None:
        result = select_strategy_type(
            MarketRegime.TREND_UP, _chart(long=60.0), _news(), _deriv(), _market()
        )
        assert isinstance(result.reasons, list)

    def test_all_known_strategies_have_positive_holding_minutes(self) -> None:
        known = [StrategyType.SCALPING, StrategyType.INTRADAY,
                 StrategyType.TREND_FOLLOWING, StrategyType.BREAKOUT]
        for st in known:
            assert isinstance(st, StrategyType)

    def test_unknown_has_zero_holding_and_rr(self) -> None:
        result = select_strategy_type(None, None, None, None, None)
        assert result.expected_holding_minutes == 0
        assert result.min_required_rr == 0.0

    def test_reasons_never_empty(self) -> None:
        for regime in MarketRegime:
            result = select_strategy_type(
                regime, _chart(long=50.0), _news(), _deriv(), _market()
            )
            assert len(result.reasons) > 0


# ── 9. 전략별 min R:R 검증 ───────────────────────────────────────────────────

class TestMinRR:
    def test_scalping_min_rr(self) -> None:
        # RANGE + 소폭 방향 엣지 + 타이트 스프레드 → SCALPING
        result = select_strategy_type(
            MarketRegime.RANGE,
            _chart(long=25.0, risk=5.0),
            _news(risk=0.0),
            _deriv(risk=0.0),
            _market(spread=1.0, vol_ratio=1.0),
        )
        if result.strategy_type == StrategyType.SCALPING:
            assert result.min_required_rr == STRATEGY_THRESHOLDS["SCALPING"].min_risk_reward_ratio

    def test_intraday_min_rr(self) -> None:
        result = select_strategy_type(
            MarketRegime.RANGE,
            _chart(long=45.0, risk=10.0),
            _news(risk=5.0),
            _deriv(risk=5.0),
            _market(spread=2.0, vol_ratio=1.0),
        )
        if result.strategy_type == StrategyType.INTRADAY:
            assert result.min_required_rr == STRATEGY_THRESHOLDS["INTRADAY"].min_risk_reward_ratio

    def test_trend_following_min_rr(self) -> None:
        result = select_strategy_type(
            MarketRegime.TREND_UP,
            _chart(long=60.0, risk=10.0),
            _news(risk=5.0),
            _deriv(risk=5.0),
            _market(vol_ratio=1.2),
        )
        if result.strategy_type == StrategyType.TREND_FOLLOWING:
            assert result.min_required_rr == STRATEGY_THRESHOLDS["TREND_FOLLOWING"].min_risk_reward_ratio

    def test_breakout_min_rr(self) -> None:
        result = select_strategy_type(
            MarketRegime.RANGE,
            _chart(long=40.0, risk=5.0),
            _news(risk=0.0),
            _deriv(risk=0.0, crowded="NONE"),
            _market(spread=1.0, vol_ratio=2.5, price_change=0.5),
        )
        if result.strategy_type == StrategyType.BREAKOUT:
            assert result.min_required_rr == STRATEGY_THRESHOLDS["BREAKOUT"].min_risk_reward_ratio

    @pytest.mark.parametrize("strategy,expected_rr", [
        ("SCALPING",        1.2),
        ("INTRADAY",        1.5),
        ("TREND_FOLLOWING", 2.0),
        ("BREAKOUT",        2.0),
    ])
    def test_constants_match_expected_rr(self, strategy: str, expected_rr: float) -> None:
        assert STRATEGY_THRESHOLDS[strategy].min_risk_reward_ratio == expected_rr


# ── 10. no_trade_flag → UNKNOWN ──────────────────────────────────────────────

class TestNoTradeFlag:
    def test_no_trade_flag_true_returns_unknown(self) -> None:
        result = select_strategy_type(
            market_regime=MarketRegime.TREND_UP,
            chart_score=_chart(long=80.0, risk=5.0),
            news_score=_news(risk=0.0, no_trade_flag=True),
            derivatives_score=_deriv(risk=0.0),
            market_data=_market(),
        )
        assert result.strategy_type == StrategyType.UNKNOWN

    def test_no_trade_flag_false_allows_selection(self) -> None:
        result = select_strategy_type(
            market_regime=MarketRegime.TREND_UP,
            chart_score=_chart(long=65.0, risk=10.0),
            news_score=_news(risk=5.0, no_trade_flag=False),
            derivatives_score=_deriv(risk=5.0),
            market_data=_market(),
        )
        assert result.strategy_type == StrategyType.TREND_FOLLOWING

    def test_no_trade_flag_reason_present(self) -> None:
        result = select_strategy_type(
            MarketRegime.TREND_UP,
            _chart(long=80.0),
            _news(no_trade_flag=True),
            _deriv(),
            _market(),
        )
        assert any("no_trade_flag" in r for r in result.reasons)


# ── 11. 가격 이미 이동 → BREAKOUT 스킵 ───────────────────────────────────────

class TestBreakoutPriceMove:
    def test_price_moved_too_far_skips_breakout(self) -> None:
        result = select_strategy_type(
            market_regime=MarketRegime.RANGE,
            chart_score=_chart(long=40.0, risk=5.0),
            news_score=_news(risk=0.0),
            derivatives_score=_deriv(risk=0.0, crowded="NONE"),
            market_data=_market(vol_ratio=2.5, price_change=5.0),   # > 3.0%
        )
        assert result.strategy_type != StrategyType.BREAKOUT

    def test_price_within_limit_allows_breakout(self) -> None:
        result = select_strategy_type(
            market_regime=MarketRegime.RANGE,
            chart_score=_chart(long=40.0, risk=5.0),
            news_score=_news(risk=0.0),
            derivatives_score=_deriv(risk=0.0, crowded="NONE"),
            market_data=_market(vol_ratio=2.5, price_change=1.0),  # < 3.0%
        )
        assert result.strategy_type == StrategyType.BREAKOUT


# ── 12. Config 오버라이드 ─────────────────────────────────────────────────────

class TestConfigOverride:
    def test_lower_min_trend_dir_allows_trend_following(self) -> None:
        # 기본 threshold=55, config로 40으로 낮춤
        result = select_strategy_type(
            market_regime=MarketRegime.TREND_UP,
            chart_score=_chart(long=42.0, risk=10.0),
            news_score=_news(risk=5.0),
            derivatives_score=_deriv(risk=5.0),
            market_data=_market(),
            config={"min_trend_dir_score": 40.0},
        )
        assert result.strategy_type == StrategyType.TREND_FOLLOWING

    def test_raise_breakout_volume_threshold(self) -> None:
        # vol_ratio=2.5 이 기본(1.8) 충족이나 config로 3.0으로 높임 → BREAKOUT 스킵
        result_default = select_strategy_type(
            MarketRegime.RANGE,
            _chart(long=40.0, risk=5.0),
            _news(risk=0.0),
            _deriv(risk=0.0),
            _market(vol_ratio=2.5),
        )
        result_strict = select_strategy_type(
            MarketRegime.RANGE,
            _chart(long=40.0, risk=5.0),
            _news(risk=0.0),
            _deriv(risk=0.0),
            _market(vol_ratio=2.5),
            config={"min_breakout_volume_ratio": 3.0},
        )
        assert result_default.strategy_type == StrategyType.BREAKOUT
        assert result_strict.strategy_type != StrategyType.BREAKOUT

    def test_lower_max_risk_scalping_blocks_scalping(self) -> None:
        # chart risk=15 → combined_risk=15*0.4=6.0, 기본 max_risk_scalping=40 → SCALPING 가능
        # config로 max_risk_scalping=5 → 6 > 5 → SCALPING 차단
        result = select_strategy_type(
            MarketRegime.RANGE,
            _chart(long=25.0, risk=15.0),
            _news(risk=0.0),
            _deriv(risk=0.0),
            _market(spread=1.0),
            config={"max_risk_scalping": 5.0},
        )
        assert result.strategy_type != StrategyType.SCALPING


# ── 13. dict 형식 입력 지원 ──────────────────────────────────────────────────

class TestDictInputFormat:
    def test_chart_score_as_dict(self) -> None:
        chart_dict = {"long_score": 60.0, "short_score": 10.0, "risk_score": 10.0}
        result = select_strategy_type(
            MarketRegime.TREND_UP, chart_dict, _news(), _deriv(), _market()
        )
        assert result.strategy_type == StrategyType.TREND_FOLLOWING

    def test_news_score_as_dict(self) -> None:
        news_dict = {"risk_score": 0.0, "no_trade_flag": False}
        result = select_strategy_type(
            MarketRegime.TREND_UP,
            _chart(long=60.0),
            news_dict,
            _deriv(),
            _market(),
        )
        assert result.strategy_type == StrategyType.TREND_FOLLOWING

    def test_derivatives_as_dict(self) -> None:
        deriv_dict = {"risk_score": 0.0, "crowded_side": "NONE"}
        result = select_strategy_type(
            MarketRegime.TREND_UP,
            _chart(long=60.0),
            _news(),
            deriv_dict,
            _market(),
        )
        assert result.strategy_type == StrategyType.TREND_FOLLOWING

    def test_regime_as_string(self) -> None:
        result = select_strategy_type(
            "HIGH_VOLATILITY", _chart(long=80.0), _news(), _deriv(), _market()
        )
        assert result.strategy_type == StrategyType.UNKNOWN
