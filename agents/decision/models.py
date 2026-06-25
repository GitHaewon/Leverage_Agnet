"""
Decision layer 공유 데이터 모델.

설계 원칙:
  - 순수 Python dataclass / enum — 외부 의존성 없음
  - agents.* 임포트 금지 (순환 임포트 방지)
  - Decimal: 모든 가격·손익 필드 (부동소수점 정밀도 오류 방지)
  - float:   비율·점수·bps 단위 필드

레이어 역할:
  DecisionEngine    → TradeCandidate 생성 (결정적, agents/decision/)
  ReviewerAgent     → AIReviewResult 반환 (검토만, 숫자 권한 없음, agents/synthesis/)
  RiskEngine        → ValidationResult 반환 (validate_candidate, 최종 안전 게이트)
  OrchestratorPipeline → FinalDecision 조립
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional


# ── Enums ─────────────────────────────────────────────────────────────────────

class FinalAction(str, Enum):
    """파이프라인 최종 액션."""
    LONG  = "LONG"
    SHORT = "SHORT"
    HOLD  = "HOLD"


class StrategyType(str, Enum):
    """후보를 생성한 전략 분류."""
    SCALPING        = "SCALPING"
    INTRADAY        = "INTRADAY"
    TREND_FOLLOWING = "TREND_FOLLOWING"
    BREAKOUT        = "BREAKOUT"
    UNKNOWN         = "UNKNOWN"


class AIReviewAction(str, Enum):
    """AI 리뷰어의 최종 판정."""
    APPROVE = "APPROVE"
    REJECT  = "REJECT"


class MarketRegime(str, Enum):
    """현재 시장 상태 분류."""
    TREND_UP       = "TREND_UP"
    TREND_DOWN     = "TREND_DOWN"
    RANGE          = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    NEWS_EVENT     = "NEWS_EVENT"
    UNKNOWN        = "UNKNOWN"


# ── 중간 분석 결과 ─────────────────────────────────────────────────────────────

@dataclass
class MarketRegimeResult:
    """
    시장 국면 분류 결과.

    TechnicalAnalysis / MarketStructure 에이전트 출력으로부터 결정적으로 생성된다.
    """
    regime:     MarketRegime
    confidence: float          # 0.0 ~ 1.0
    reasons:    list[str]      = field(default_factory=list)


@dataclass
class SignalScore:
    """
    방향별 점수 집계.

    StrategyEngine이 개별 전략 시그널을 집계한 가중 점수.
    no_trade_score가 LONG/SHORT 모두를 초과하면 HOLD로 귀결된다.

    risk_score: 고위험 요소(고변동성·뉴스 이벤트 등) 페널티 (0.0~1.0, 높을수록 위험).
    """
    long_score:      float
    short_score:     float
    no_trade_score:  float
    risk_score:      float
    reasons:         list[str] = field(default_factory=list)


@dataclass
class StrategySelectionResult:
    """
    후보 생성에 사용할 전략 및 파라미터 선택 결과.

    expected_holding_minutes: 전략 유형 기반 예상 보유 시간.
    min_required_rr: 이 전략에서 수용 가능한 최소 R:R (기본 2.0, 전략별 상이).
    """
    strategy_type:             StrategyType
    expected_holding_minutes:  int
    min_required_rr:           float          # 최소 1:2 (CLAUDE.md 절대 규칙)
    reasons:                   list[str] = field(default_factory=list)


# ── 핵심 모델 ─────────────────────────────────────────────────────────────────

@dataclass
class TradeCandidate:
    """
    결정적 코드가 생성한 거래 후보.

    AI는 이 객체를 수정하지 않는다. 검토(승인/거부)만 수행한다.
    RiskEngine이 quantity·leverage를 최종 확정하므로 여기서는 추천값이다.

    가격 필드 (Decimal):
      entry_price, stop_loss, take_profit, notional_size,
      expected_gross_profit, expected_gross_loss,
      expected_fees, expected_slippage_cost,
      expected_net_profit, expected_net_loss,
      liquidation_price

    비율 필드 (float):
      margin_ratio, actual_rr, min_required_rr,
      spread_bps, slippage_bps
    """
    # ── 기본 식별 ────────────────────────────────────────────────────────────
    action:  FinalAction
    coin:    str           # "BTC" | "ETH"
    symbol:  str           # "BTCUSDT" | "ETHUSDT"

    # ── 전략 메타 ─────────────────────────────────────────────────────────────
    strategy_type:            StrategyType
    expected_holding_minutes: int

    # ── 가격 파라미터 (Decimal) ───────────────────────────────────────────────
    entry_price:   Decimal
    stop_loss:     Optional[Decimal]   # HOLD 시 None; LONG/SHORT 시 필수
    take_profit:   Optional[Decimal]   # HOLD 시 None

    # ── 포지션 사이징 ─────────────────────────────────────────────────────────
    leverage:      int                 # 추천 레버리지 (RiskEngine이 상한 적용)
    margin_ratio:  float               # 계좌 대비 증거금 비율 (예: 0.02 = 2%)
    notional_size: Decimal             # 명목 포지션 크기 (entry_price × qty_estimate)

    # ── R:R ──────────────────────────────────────────────────────────────────
    actual_rr:       float             # 이 후보의 실제 R:R
    min_required_rr: float             # 전략 요구 최소 R:R (≥ 2.0)

    # ── 손익 추정 (Decimal, HOLD 시 None) ────────────────────────────────────
    expected_gross_profit:    Optional[Decimal]
    expected_gross_loss:      Optional[Decimal]
    expected_fees:            Decimal           # 예상 수수료 (USDT)
    expected_slippage_cost:   Decimal           # 예상 슬리피지 비용 (USDT)
    expected_net_profit:      Optional[Decimal]
    expected_net_loss:        Optional[Decimal]

    # ── 청산·실행 비용 ────────────────────────────────────────────────────────
    liquidation_price: Optional[Decimal]        # 청산가 추정 (계좌 잔고·레버리지 의존)
    spread_bps:        float                    # 현재 스프레드 (bp)
    slippage_bps:      float                    # 예상 슬리피지 (bp)

    # ── 근거 ─────────────────────────────────────────────────────────────────
    reasons: list[str] = field(default_factory=list)
    strategy_name: Optional[str] = None


@dataclass
class AIReviewResult:
    """
    AI 리뷰어의 TradeCandidate 검토 결과.

    AI는 TradeCandidate의 어떤 숫자도 수정하지 않는다.
    APPROVE / REJECT + 신뢰도 + 경고만 반환한다.

    critical_contradiction: AI가 핵심 지표와 방향이 정반대임을 감지한 경우 True.
    risk_warnings: 거부 없이 경고하는 리스트 (RiskEngine에 전달 가능).
    """
    review_action:          AIReviewAction
    confidence:             float          # 0.0 ~ 1.0 (AI 리뷰 신뢰도)
    critical_contradiction: bool
    risk_warnings:          list[str]      = field(default_factory=list)
    reason_summary:         str            = ""


@dataclass
class RiskCheckResult:
    """
    RiskEngine 검증 결과 요약.

    agents.risk.models.ValidationResult의 의사결정 요약이다.
    (ValidationResult 전체를 파이프라인 밖으로 노출하지 않기 위한 경계 모델)

    passed: 모든 검증 통과 여부.
    failed_checks: 실패한 검증 코드 목록 (예: ["ORDER_003", "LOW_CONFIDENCE"]).
    risk_per_trade_pct: 이번 거래에 적용된 계좌 대비 리스크 비율.
    expected_net_profit/loss: RiskEngine이 사이징 기준으로 재계산한 최종 손익.
    """
    passed:              bool
    failed_checks:       list[str]      = field(default_factory=list)
    warnings:            list[str]      = field(default_factory=list)
    risk_per_trade_pct:  float          = 0.0
    expected_net_profit: Optional[Decimal] = None
    expected_net_loss:   Optional[Decimal] = None


@dataclass
class NewsSentimentScore:
    """
    뉴스·감성 분석 점수 결과.

    역할: 직접 거래 트리거가 아닌 리스크 필터.
      - Positive news → long_score_adjustment 소폭 증가 (LONG 강제 아님)
      - Negative news → short_score_adjustment 소폭 증가 (SHORT 강제 아님)
      - 주요 이벤트 / 극단적 탐욕·공포 → risk_score 증가 + no_trade_flag 가능

    sentiment_score  : -100 ~ +100 (뉴스 + F&G 역발상 종합)
    long_score_adjustment  : 상위 레이어 long_score 에 가산할 조정치
    short_score_adjustment : 상위 레이어 short_score 에 가산할 조정치
    risk_score       : 0 ~ 100 (높을수록 진입 위험)
    no_trade_flag    : True 이면 진입 금지 (주요 이벤트 또는 NEWS_EVENT 국면)
    reasons          : 결정 근거 문자열 목록
    """
    sentiment_score:         float
    long_score_adjustment:   float
    short_score_adjustment:  float
    risk_score:              float
    no_trade_flag:           bool
    reasons:                 list[str] = field(default_factory=list)

    @classmethod
    def neutral(cls) -> "NewsSentimentScore":
        """데이터 없음 또는 오류 시 안전한 중립 결과."""
        return cls(
            sentiment_score=0.0,
            long_score_adjustment=0.0,
            short_score_adjustment=0.0,
            risk_score=0.0,
            no_trade_flag=False,
            reasons=["뉴스·감성 데이터 없음 — 중립 처리"],
        )


@dataclass
class DerivativesMarketScore:
    """
    선물 파생 데이터 기반 시장 혼잡도·리스크 점수 결과.

    역할: 직접 거래 트리거가 아닌 방향 점수 조정 및 리스크 필터.
      - Price up + OI up + neutral funding → 롱 소폭 우대
      - 고펀딩 + 롱 쏠림 → 롱 추격 감점, 리스크 증가
      - 음수 펀딩 + 숏 쏠림 → 숏 추격 감점, 리스크 증가
      - 가격 급변 + OI 감소 → 청산 이벤트 가능성으로 리스크 증가

    long/short_score_adjustment: 상위 레이어 long_score / short_score 에 가산할 조정치
    risk_score: 0 ~ 100 (높을수록 진입 위험)
    crowded_side: LONG / SHORT / NONE
    reasons: 결정 근거 문자열 목록
    """
    long_score_adjustment:  float
    short_score_adjustment: float
    risk_score:             float
    crowded_side:           Literal["LONG", "SHORT", "NONE"]
    reasons:                list[str] = field(default_factory=list)

    @classmethod
    def neutral(cls) -> "DerivativesMarketScore":
        """데이터 없음 또는 오류 시 안전한 중립 결과."""
        return cls(
            long_score_adjustment=0.0,
            short_score_adjustment=0.0,
            risk_score=0.0,
            crowded_side="NONE",
            reasons=["파생 시장 데이터 없음 — 중립 처리"],
        )


@dataclass
class FinalDecision:
    """
    파이프라인 최종 의사결정 컨테이너.

    OrchestratorPipeline이 각 단계 결과를 조립해 반환한다.
    외부(API 응답, 로그, 거래일지)에 노출되는 최상위 객체.

    candidate / ai_review / risk_result 는 HOLD 경로에서 None일 수 있다.
    """
    action:      FinalAction
    reason:      str

    candidate:   Optional[TradeCandidate]  = None
    ai_review:   Optional[AIReviewResult]  = None
    risk_result: Optional[RiskCheckResult] = None
