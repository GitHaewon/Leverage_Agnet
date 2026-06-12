"""
Market Regime Classifier 단위 테스트.

검증 항목:
  - NEWS_EVENT: news_event 플래그 → 즉시 반환, confidence=1.0
  - HIGH_VOLATILITY: BB bandwidth + ATR 동시 초과 → HIGH_VOLATILITY
  - HIGH_VOLATILITY: 단일 신호만으로는 분류 안 됨
  - TREND_UP: EMA 정배열 + tech_score 양수 (2개 이상)
  - TREND_DOWN: EMA 역배열 + tech_score 음수
  - TREND_UP: 전략 방향 LONG이 2번째 신호로 작동
  - RANGE: EMA mixed + BB 좁음
  - RANGE: tech_score ≈ 0 + NO_TRADE 전략
  - UNKNOWN: 데이터 없음
  - UNKNOWN: 단일 신호 부족
  - config 오버라이드: min_signals=1 로 완화
  - reasons 비어있지 않음
  - confidence 범위 0.0~1.0
"""
from __future__ import annotations

import pytest

from agents.decision.models import MarketRegime
from agents.decision.regime import classify_market_regime
from tests.unit.agents._strategy_fixtures import make_ta_result, make_tf_analysis


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────

PRICE = 105_000.0
COIN  = "BTC"
SYM   = "BTCUSDT"


def _ta(
    *,
    ema_align: str = "mixed",
    atr: float = 300.0,
    bb_bw: float = 4.0,
    volume_ratio: float = 1.0,
    tf: str = "1h",
    tech_score: float = 0.0,
) -> object:
    """TechnicalAnalysisResult 헬퍼."""
    bb_middle = PRICE
    bb_upper  = bb_middle * (1 + bb_bw / 200)
    bb_lower  = bb_middle * (1 - bb_bw / 200)

    if ema_align == "bullish":
        ema9, ema21, ema50, ema200 = (
            PRICE * 1.01, PRICE * 1.005, PRICE * 0.99, PRICE * 0.95
        )
    elif ema_align == "bearish":
        ema9, ema21, ema50, ema200 = (
            PRICE * 0.99, PRICE * 0.995, PRICE * 1.01, PRICE * 1.05
        )
    else:  # mixed
        ema9, ema21, ema50, ema200 = PRICE, PRICE, PRICE, PRICE

    tfa = make_tf_analysis(
        close=PRICE,
        ema9=ema9, ema21=ema21, ema50=ema50, ema200=ema200,
        atr=atr,
        bb_upper=bb_upper, bb_middle=bb_middle, bb_lower=bb_lower,
        pct_b=0.5,
        volume_ratio=volume_ratio,
        symbol=SYM,
        timeframe=tf,
    )
    return make_ta_result(
        COIN, SYM, analyses={tf: tfa}, tech_score=tech_score, latest_close=PRICE
    )


def _strat(direction: str = "NO_TRADE") -> object:
    """AggregatedSignal-duck-type 헬퍼."""
    class _Sig:
        pass
    s = _Sig()
    s.direction = direction  # type: ignore[attr-defined]
    return s


def _mkt(price: float = PRICE, news: bool = False) -> dict:
    return {"current_price": price, "news_event": news}


# ── NEWS_EVENT ────────────────────────────────────────────────────────────────

class TestNewsEvent:
    def test_flag_triggers_immediately(self) -> None:
        result = classify_market_regime(
            _mkt(news=True), _ta(), _strat()
        )
        assert result.regime == MarketRegime.NEWS_EVENT

    def test_confidence_is_one(self) -> None:
        result = classify_market_regime(_mkt(news=True), None, None)
        assert result.confidence == 1.0

    def test_overrides_high_volatility(self) -> None:
        # 뉴스 이벤트는 HIGH_VOLATILITY보다 우선
        ta = _ta(atr=5000.0, bb_bw=20.0, volume_ratio=3.0)
        result = classify_market_regime(_mkt(news=True), ta, _strat())
        assert result.regime == MarketRegime.NEWS_EVENT

    def test_reasons_not_empty(self) -> None:
        result = classify_market_regime(_mkt(news=True), None, None)
        assert len(result.reasons) >= 1


# ── HIGH_VOLATILITY ───────────────────────────────────────────────────────────

class TestHighVolatility:
    def test_bb_and_atr_both_high(self) -> None:
        # BB bandwidth 15% (>10) + ATR 4% of price (>3%) → HIGH_VOLATILITY
        ta = _ta(bb_bw=15.0, atr=PRICE * 0.04)
        result = classify_market_regime(_mkt(), ta, _strat())
        assert result.regime == MarketRegime.HIGH_VOLATILITY

    def test_bb_high_and_volume_spike(self) -> None:
        ta = _ta(bb_bw=12.0, volume_ratio=2.5)
        result = classify_market_regime(_mkt(), ta, _strat())
        assert result.regime == MarketRegime.HIGH_VOLATILITY

    def test_all_three_signals(self) -> None:
        ta = _ta(bb_bw=12.0, atr=PRICE * 0.04, volume_ratio=2.5)
        result = classify_market_regime(_mkt(), ta, _strat())
        assert result.regime == MarketRegime.HIGH_VOLATILITY
        assert result.confidence > 0.5

    def test_single_bb_signal_insufficient(self) -> None:
        # BB만 높고 ATR·거래량 정상 → HIGH_VOLATILITY 아님
        ta = _ta(bb_bw=15.0, atr=200.0, volume_ratio=1.0)
        result = classify_market_regime(_mkt(), ta, _strat())
        assert result.regime != MarketRegime.HIGH_VOLATILITY

    def test_single_atr_signal_insufficient(self) -> None:
        ta = _ta(bb_bw=4.0, atr=PRICE * 0.04, volume_ratio=1.0)
        result = classify_market_regime(_mkt(), ta, _strat())
        assert result.regime != MarketRegime.HIGH_VOLATILITY

    def test_confidence_in_range(self) -> None:
        ta = _ta(bb_bw=15.0, atr=PRICE * 0.04, volume_ratio=3.0)
        result = classify_market_regime(_mkt(), ta, _strat())
        assert 0.0 <= result.confidence <= 1.0


# ── TREND_UP ─────────────────────────────────────────────────────────────────

class TestTrendUp:
    def test_bullish_ema_and_positive_tech_score(self) -> None:
        ta = _ta(ema_align="bullish", tech_score=0.60)
        result = classify_market_regime(_mkt(), ta, _strat("NO_TRADE"))
        assert result.regime == MarketRegime.TREND_UP

    def test_bullish_ema_and_long_strategy(self) -> None:
        ta = _ta(ema_align="bullish", tech_score=0.10)  # tech_score 낮음 → 1 신호
        result = classify_market_regime(_mkt(), ta, _strat("LONG"))
        assert result.regime == MarketRegime.TREND_UP

    def test_tech_score_and_long_without_ema(self) -> None:
        ta = _ta(ema_align="mixed", tech_score=0.50)
        result = classify_market_regime(_mkt(), ta, _strat("LONG"))
        assert result.regime == MarketRegime.TREND_UP

    def test_bullish_alone_insufficient(self) -> None:
        # EMA bullish 한 개만 → TREND_UP 아님
        ta = _ta(ema_align="bullish", tech_score=0.10)
        result = classify_market_regime(_mkt(), ta, _strat("NO_TRADE"))
        assert result.regime != MarketRegime.TREND_UP

    def test_confidence_in_range(self) -> None:
        ta = _ta(ema_align="bullish", tech_score=0.70)
        result = classify_market_regime(_mkt(), ta, _strat("LONG"))
        assert 0.0 <= result.confidence <= 1.0


# ── TREND_DOWN ────────────────────────────────────────────────────────────────

class TestTrendDown:
    def test_bearish_ema_and_negative_tech_score(self) -> None:
        ta = _ta(ema_align="bearish", tech_score=-0.60)
        result = classify_market_regime(_mkt(), ta, _strat("NO_TRADE"))
        assert result.regime == MarketRegime.TREND_DOWN

    def test_bearish_ema_and_short_strategy(self) -> None:
        ta = _ta(ema_align="bearish", tech_score=-0.10)
        result = classify_market_regime(_mkt(), ta, _strat("SHORT"))
        assert result.regime == MarketRegime.TREND_DOWN

    def test_tech_score_and_short_without_ema(self) -> None:
        ta = _ta(ema_align="mixed", tech_score=-0.50)
        result = classify_market_regime(_mkt(), ta, _strat("SHORT"))
        assert result.regime == MarketRegime.TREND_DOWN

    def test_bearish_alone_insufficient(self) -> None:
        ta = _ta(ema_align="bearish", tech_score=-0.10)
        result = classify_market_regime(_mkt(), ta, _strat("NO_TRADE"))
        assert result.regime != MarketRegime.TREND_DOWN


# ── RANGE ─────────────────────────────────────────────────────────────────────

class TestRange:
    def test_mixed_ema_and_narrow_bb(self) -> None:
        ta = _ta(ema_align="mixed", bb_bw=3.0, tech_score=0.05)
        result = classify_market_regime(_mkt(), ta, _strat("NO_TRADE"))
        assert result.regime == MarketRegime.RANGE

    def test_neutral_tech_score_and_no_trade(self) -> None:
        ta = _ta(ema_align="mixed", tech_score=0.10)
        result = classify_market_regime(_mkt(), ta, _strat("NO_TRADE"))
        assert result.regime == MarketRegime.RANGE

    def test_narrow_bb_and_neutral_tech_score(self) -> None:
        ta = _ta(ema_align="bullish", bb_bw=3.0, tech_score=0.15)
        result = classify_market_regime(_mkt(), ta, _strat("NO_TRADE"))
        assert result.regime == MarketRegime.RANGE

    def test_single_range_signal_insufficient(self) -> None:
        # EMA mixed 하나만 → RANGE 아님
        ta = _ta(ema_align="mixed", bb_bw=7.0, tech_score=0.25)
        result = classify_market_regime(_mkt(), ta, _strat("LONG"))
        assert result.regime != MarketRegime.RANGE


# ── UNKNOWN ───────────────────────────────────────────────────────────────────

class TestUnknown:
    def test_none_inputs(self) -> None:
        result = classify_market_regime(None, None, None)
        assert result.regime == MarketRegime.UNKNOWN
        assert result.confidence == 0.0

    def test_empty_market_data(self) -> None:
        result = classify_market_regime({}, None, None)
        assert result.regime == MarketRegime.UNKNOWN

    def test_insufficient_signals_fallback(self) -> None:
        # 모든 지표 중립 → 어떤 분류도 합의 안 됨
        ta = _ta(ema_align="mixed", bb_bw=7.0, tech_score=0.25, volume_ratio=1.0)
        result = classify_market_regime(_mkt(), ta, _strat("LONG"))
        # TREND_UP: EMA mixed(X) tech_score 0.25<0.30(X) LONG(O) → 1개만
        # RANGE: mixed(O) bb 7%>5%(X) tech 0.25>0.20(X) → 1개만
        assert result.regime == MarketRegime.UNKNOWN

    def test_reasons_not_empty(self) -> None:
        result = classify_market_regime(None, None, None)
        assert len(result.reasons) >= 1

    def test_no_exception_on_zero_price(self) -> None:
        # current_price=0 일 때 ATR/price 0-division 방어
        result = classify_market_regime({"current_price": 0}, _ta(), _strat())
        assert result.regime in MarketRegime.__members__.values()


# ── 공통 불변식 ───────────────────────────────────────────────────────────────

class TestInvariants:
    _cases = [
        ("news",     _mkt(news=True), None,                      None),
        ("hv",       _mkt(),          _ta(bb_bw=15.0,
                                          atr=PRICE * 0.04),     _strat()),
        ("trend_up", _mkt(),          _ta(ema_align="bullish",
                                          tech_score=0.70),      _strat("LONG")),
        ("trend_dn", _mkt(),          _ta(ema_align="bearish",
                                          tech_score=-0.70),     _strat("SHORT")),
        ("range",    _mkt(),          _ta(bb_bw=3.0,
                                          tech_score=0.05),      _strat("NO_TRADE")),
        ("unknown",  None,            None,                      None),
    ]

    @pytest.mark.parametrize("label,mkt,ta,sig", _cases)
    def test_confidence_in_range(self, label, mkt, ta, sig) -> None:
        r = classify_market_regime(mkt, ta, sig)
        assert 0.0 <= r.confidence <= 1.0, f"{label}: confidence={r.confidence}"

    @pytest.mark.parametrize("label,mkt,ta,sig", _cases)
    def test_reasons_is_list(self, label, mkt, ta, sig) -> None:
        r = classify_market_regime(mkt, ta, sig)
        assert isinstance(r.reasons, list), f"{label}: reasons must be list"

    @pytest.mark.parametrize("label,mkt,ta,sig", _cases)
    def test_regime_is_valid_enum(self, label, mkt, ta, sig) -> None:
        r = classify_market_regime(mkt, ta, sig)
        assert r.regime in MarketRegime.__members__.values(), f"{label}: invalid regime"


# ── config 오버라이드 ─────────────────────────────────────────────────────────

class TestConfigOverride:
    def test_min_signals_one_allows_single_indicator(self) -> None:
        # 기본값 min_signals=2 에서 실패하는 케이스를 min_signals=1 로 통과
        ta = _ta(bb_bw=15.0, atr=100.0, volume_ratio=1.0)  # BB만 높음
        normal = classify_market_regime(_mkt(), ta, _strat())
        assert normal.regime != MarketRegime.HIGH_VOLATILITY

        relaxed = classify_market_regime(_mkt(), ta, _strat(), config={"min_signals": 1})
        assert relaxed.regime == MarketRegime.HIGH_VOLATILITY

    def test_custom_bb_threshold(self) -> None:
        # bb_high_vol_bw=20 으로 높이면 BB 15%는 트리거 안 됨
        ta = _ta(bb_bw=15.0, atr=PRICE * 0.04)
        result = classify_market_regime(
            _mkt(), ta, _strat(), config={"bb_high_vol_bw": 20.0}
        )
        # BB 신호 제거 → ATR만 남아 HIGH_VOLATILITY 아님
        assert result.regime != MarketRegime.HIGH_VOLATILITY

    def test_custom_tech_trend_threshold(self) -> None:
        # tech_trend_th=0.10 으로 완화 → tech_score 0.20 이 추세 신호로 인정됨
        ta = _ta(ema_align="bullish", tech_score=0.20)
        default = classify_market_regime(_mkt(), ta, _strat("NO_TRADE"))
        assert default.regime != MarketRegime.TREND_UP  # 기본 0.30 미달

        relaxed = classify_market_regime(
            _mkt(), ta, _strat("NO_TRADE"), config={"tech_trend_th": 0.10}
        )
        assert relaxed.regime == MarketRegime.TREND_UP
