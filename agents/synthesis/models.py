"""
AI Reviewer 입력 모델.

설계 원칙:
  - ReviewInput: AI에게 전달하는 간결한 컨텍스트 (평문 요약만, raw 원문 없음)
  - AI는 TradeCandidate를 수정하지 않는다. APPROVE / REJECT만 반환한다.
  - 출력 타입 AIReviewResult는 agents/decision/models.py에 정의되어 있다.

레이어 의존:
  synthesis → decision.models (AIReviewResult)
  synthesis → (외부 없음 — synthesis는 agent 레이어 끝단)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReviewInput:
    """
    AI 리뷰어에게 전달하는 간결한 컨텍스트.

    AI는 이 정보를 바탕으로 TradeCandidate를 APPROVE 또는 REJECT한다.
    방향·가격·레버리지·사이즈는 수정 불가 — 검토 의견(review_action)만 반환한다.

    [시장 국면]
    market_regime:      MarketRegime enum 값 (예: "TREND_UP")
    regime_confidence:  국면 분류 신뢰도 0.0 ~ 1.0

    [점수 요약 — raw 뉴스 원문 불포함]
    chart_long_score:   차트 롱 점수 (0~100)
    chart_short_score:  차트 숏 점수
    chart_risk_score:   차트 리스크 점수
    chart_reasons:      최대 5개 근거 문자열

    news_sentiment_score: 뉴스+F&G 종합 감성 (-100~+100)
    news_risk_score:    감성 리스크 점수 (0~100)
    news_no_trade_flag: True이면 주요 이벤트로 진입 금지

    deriv_risk_score:   파생 리스크 점수 (0~100)
    deriv_crowded_side: "LONG" / "SHORT" / "NONE"
    deriv_reasons:      최대 3개 근거 문자열

    [전략]
    strategy_type:           선택된 전략 (예: "TREND_FOLLOWING")
    expected_holding_minutes: 예상 보유 시간 (분)

    [거래 후보 — AI 수정 불가]
    action:              "LONG" / "SHORT" / "HOLD"
    entry_price:         진입가 (USDT)
    stop_loss:           손절가 (USDT) — LONG/SHORT 필수
    take_profit:         익절가 (USDT)
    leverage:            레버리지 (배수)
    notional_size:       명목 포지션 크기 (USDT)
    margin_ratio:        계좌 대비 증거금 비율 (예: 0.02 = 2%)
    actual_rr:           실제 R:R
    min_required_rr:     전략 요구 최소 R:R
    expected_net_profit: 수수료·슬리피지 차감 후 예상 순수익 (USDT)
    expected_net_loss:   수수료·슬리피지 가산 후 예상 순손실 (USDT)
    spread_bps:          현재 스프레드 (bps)
    slippage_bps:        예상 슬리피지 (bps)
    liquidation_price:   청산가 추정 (USDT, 없으면 None)
    """
    coin: str
    symbol: str

    # 시장 국면
    market_regime: str
    regime_confidence: float

    # 차트 점수 요약
    chart_long_score: float
    chart_short_score: float
    chart_risk_score: float
    chart_reasons: list[str] = field(default_factory=list)

    # 뉴스·감성 요약
    news_sentiment_score: float = 0.0
    news_risk_score: float = 0.0
    news_no_trade_flag: bool = False
    news_reasons: list[str] = field(default_factory=list)

    # 파생 데이터 요약
    deriv_risk_score: float = 0.0
    deriv_crowded_side: str = "NONE"
    deriv_reasons: list[str] = field(default_factory=list)

    # 전략
    strategy_type: str = "UNKNOWN"
    expected_holding_minutes: int = 0

    # 거래 후보 (AI 수정 불가)
    action: str = "HOLD"
    entry_price: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    leverage: int = 1
    notional_size: float = 0.0
    margin_ratio: float = 0.0
    actual_rr: float = 0.0
    min_required_rr: float = 2.0
    expected_net_profit: float | None = None
    expected_net_loss: float | None = None
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    liquidation_price: float | None = None
