"""
Portfolio Manager 데이터 모델.

TRADING_RULES.md 근거:
  §2.4  — 단일 코인 집중도 50% 한도
  §3.2  — 포트폴리오 총 리스크 10% / 15%(공격형) 한도
  §3.3  — 단일 포지션 증거금 20% 한도
  §10.4 — 잔고 10% 미만 시 긴급 청산
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from agents.risk.constants import (
    ACCOUNT_EMERGENCY_THRESHOLD,
    MAX_PORTFOLIO_RISK,
    MAX_PORTFOLIO_RISK_AGGRESSIVE,
    MAX_SINGLE_COIN_PORTFOLIO_RATIO,
    MAX_SINGLE_POSITION_MARGIN_RATIO,
    SYSTEM_MAX_LEVERAGE,
)

# ── 포트폴리오 전용 상수 ──────────────────────────────────────────────────────

# §3.2 경고 임계값 (한도의 80%)
PORTFOLIO_RISK_WARNING_PCT: float = 0.80

# §2.4 집중도 경고 임계값 (한도의 80%)
CONCENTRATION_WARNING_PCT: float = 0.80

# BTC-ETH 근사 상관계수 (역사적 값)
BTC_ETH_CORRELATION: float = 0.85

# 리스크 점수 컴포넌트 가중치 (합산 = 1.0)
SCORE_WEIGHT_PORTFOLIO_RISK: float = 0.40
SCORE_WEIGHT_CONCENTRATION: float = 0.25
SCORE_WEIGHT_CORRELATION: float = 0.20
SCORE_WEIGHT_LEVERAGE: float = 0.15

# 리스크 레벨 경계
_SCORE_LEVELS: list[tuple[float, str]] = [
    (0.30, "safe"),
    (0.50, "moderate"),
    (0.75, "elevated"),
    (1.01, "critical"),
]

__all__ = [
    # 상수 재노출
    "MAX_PORTFOLIO_RISK",
    "MAX_PORTFOLIO_RISK_AGGRESSIVE",
    "MAX_SINGLE_COIN_PORTFOLIO_RATIO",
    "MAX_SINGLE_POSITION_MARGIN_RATIO",
    "ACCOUNT_EMERGENCY_THRESHOLD",
    "SYSTEM_MAX_LEVERAGE",
    "PORTFOLIO_RISK_WARNING_PCT",
    "CONCENTRATION_WARNING_PCT",
    "BTC_ETH_CORRELATION",
    "SCORE_WEIGHT_PORTFOLIO_RISK",
    "SCORE_WEIGHT_CONCENTRATION",
    "SCORE_WEIGHT_CORRELATION",
    "SCORE_WEIGHT_LEVERAGE",
    "_SCORE_LEVELS",
    # 모델
    "PortfolioPosition",
    "AccountContext",
    "SymbolExposure",
    "PortfolioSnapshot",
    "CorrelationRisk",
    "RiskScoreComponents",
    "PortfolioRiskScore",
]


# ── 입력 모델 ─────────────────────────────────��───────────────────────────────

@dataclass
class PortfolioPosition:
    """포트폴리오 계산에 필요한 오픈 포지션 정보."""
    id: str
    coin: str                          # "BTC" | "ETH"
    symbol: str                        # "BTCUSDT" | "ETHUSDT"
    direction: Literal["LONG", "SHORT"]
    entry_price: Decimal
    current_price: Decimal
    stop_loss: Decimal
    quantity: Decimal
    leverage: int
    margin_used: Decimal
    unrealized_pnl: Decimal

    @property
    def notional_value(self) -> Decimal:
        """현재가 기준 명목 가치 (USDT). quantity × current_price."""
        return self.quantity * self.current_price

    @property
    def risk_usdt(self) -> Decimal:
        """SL 기준 최대 예상 손실 (USDT). 항상 0 이상."""
        if self.direction == "LONG":
            return max(Decimal("0"), (self.entry_price - self.stop_loss) * self.quantity)
        return max(Decimal("0"), (self.stop_loss - self.entry_price) * self.quantity)


@dataclass
class AccountContext:
    """포트폴리오 계산에 필요한 계좌 컨텍스트."""
    available_balance: Decimal         # 신규 거래 가능 잔고 (USDT)
    initial_balance: Decimal           # 최초 잔고 (§10.4 비상 임계값 기준)
    risk_profile: Literal["conservative", "moderate", "aggressive"]

    @property
    def portfolio_risk_limit(self) -> Decimal:
        """§3.2 리스크 프로파일별 포트폴리오 총 리스크 한도 비율."""
        if self.risk_profile == "aggressive":
            return Decimal(str(MAX_PORTFOLIO_RISK_AGGRESSIVE))
        return Decimal(str(MAX_PORTFOLIO_RISK))

    @property
    def max_risk_usdt(self) -> Decimal:
        """포트폴리오 총 리스크 한도 (USDT)."""
        return self.available_balance * self.portfolio_risk_limit


# ── 출력 모델 ─────────────────────────────────────────────────────────────────

@dataclass
class SymbolExposure:
    """심볼별 노출도 (§3.2 총 노출도 분해)."""
    coin: str
    symbol: str
    direction: str
    notional_value: Decimal           # quantity × current_price
    margin_used: Decimal
    unrealized_pnl: Decimal
    risk_usdt: Decimal                # 최대 예상 손실
    portfolio_weight: float           # 전체 명목 가치 대비 비중 (0.0~1.0)


@dataclass
class PortfolioSnapshot:
    """포트폴리오 전체 상태 스냅샷 (전체 계좌 관리 + 총 노출도 + 심볼별 노출도)."""
    # 잔고
    available_balance: Decimal
    total_balance: Decimal            # available + unrealized_pnl 합산

    # 총 노출도
    total_notional: Decimal           # Σ quantity × current_price
    total_margin_used: Decimal        # Σ margin_used
    margin_utilization: float         # total_margin / available_balance

    # 총 리스크 (§3.2 naive sum — 보수적 접근)
    total_risk_usdt: Decimal          # Σ max_loss (SL 기준)
    total_risk_pct: float             # total_risk / available_balance

    # 집중도 (§2.4)
    coin_concentrations: dict[str, float]   # coin → 전체 명목 가치 비중
    max_concentration_coin: str             # 가장 집중된 코인
    max_concentration_pct: float            # 최대 집중도

    # 포지션
    position_count: int
    symbol_exposures: list[SymbolExposure]

    # §10.4 비상 상태
    is_emergency: bool                # balance < initial × 10%


@dataclass
class CorrelationRisk:
    """상관관계 기반 포트폴리오 리스크 계산 결과."""
    raw_risk_usdt: Decimal            # naive sum
    adjusted_risk_usdt: Decimal       # 상관관계 반영 후 (2자산 포트폴리오 공식)
    adjustment_factor: float          # adjusted / raw (1.0 = 무상관, <1.0 = 분산 효과)
    correlation_coefficient: float    # 사용된 BTC-ETH 상관계수
    # (coinA, dirA, coinB, dirB, effective_rho)
    pairs: list[tuple[str, str, str, str, float]]


@dataclass
class RiskScoreComponents:
    """리스크 점수 4개 컴포넌트 (디버깅 및 UI 분해 표시용)."""
    portfolio_risk_ratio: float       # total_risk / limit (0~1)
    concentration_ratio: float        # max_coin_pct / 0.50 (0~1)
    correlation_penalty: float        # 동일 방향 상관 페널티 (0~1)
    leverage_ratio: float             # avg_leverage / 20 (0~1)


@dataclass
class PortfolioRiskScore:
    """포트폴리오 종합 리���크 점수 (0.0=안전, 1.0=위험)."""
    score: float                      # 4-컴포넌트 가중합
    level: Literal["safe", "moderate", "elevated", "critical"]
    components: RiskScoreComponents
    breaches: list[str]               # 하드 리미트 위반 (거래 차단)
    warnings: list[str]               # 소프트 리미트 경고
    can_add_position: bool            # 신규 포지션 추가 가능 여부
    max_additional_risk_usdt: Decimal  # 추가 가능한 최대 리스크
