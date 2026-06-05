"""
Position Sizing Engine 전용 데이터 모델.

4가지 사이징 방법을 지원:
  1. FixedRisk   — 계좌의 N% 리스크
  2. FixedDollar — 고정 USDT 금액 리스크
  3. PercentRisk — 가용 잔고의 N%를 리스크 (FixedRisk와 동일, 명시적)
  4. Kelly       — Kelly Criterion 최적 비율 (분수 Kelly 적용)
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import Decimal


# ── 사이징 방법 ────────────────────────────────────────────────────────────────

class SizingMethod(str, enum.Enum):
    FIXED_RISK   = "fixed_risk"    # balance × risk_pct → TRADING_RULES.md §7.1
    FIXED_DOLLAR = "fixed_dollar"  # 고정 USDT 금액
    PERCENT_RISK = "percent_risk"  # available_balance × risk_pct (명시적)
    KELLY        = "kelly"         # Kelly Criterion (분수 Kelly 적용)


# ── 사이징 설정 ────────────────────────────────────────────────────────────────

@dataclass
class SizingConfig:
    """포지션 사이징 설정 — 사용자 또는 시스템이 주입."""

    method: SizingMethod = SizingMethod.FIXED_RISK

    # ── Fixed Risk / Percent Risk 설정 ──────────────────────────────────────
    risk_pct: float | None = None           # 0.005 ~ 0.05 (0.5% ~ 5%)
    use_available_balance: bool = True      # True=가용잔고, False=총잔고 기준

    # ── Fixed Dollar 설정 ───────────────────────────────────────────────────
    risk_usdt: Decimal | None = None        # 고정 손실 허용 금액 (USDT)

    # ── Kelly Criterion 설정 ────────────────────────────────────────────────
    kelly_fraction: float = 0.25            # 분수 Kelly 비율 (0.25 = Quarter-Kelly)
    kelly_min_trades: int = 20              # Kelly 계산에 필요한 최소 거래 수
    kelly_lookback_days: int = 90           # 분석 기간 (일)
    kelly_fallback_risk_pct: float = 0.01  # 거래 이력 부족 시 기본값 (1%)

    # ── 공통 안전 상한 ──────────────────────────────────────────────────────
    max_risk_pct: float = 0.05             # TRADING_RULES.md §3.1 상한
    min_risk_pct: float = 0.005            # TRADING_RULES.md §3.1 하한


# ── 거래 통계 (Kelly & 분석용) ──────────────────────────────────────────────────

@dataclass
class TradeStatistics:
    """
    역사적 거래 성과 통계.
    Kelly Criterion 계산과 성과 분석에 사용.
    """
    total_trades: int
    winning_trades: int
    losing_trades: int

    total_pnl: Decimal
    avg_win_usdt: Decimal          # 평균 수익 (수익 거래만)
    avg_loss_usdt: Decimal         # 평균 손실 절댓값 (손실 거래만)
    gross_win_usdt: Decimal        # 총 수익
    gross_loss_usdt: Decimal       # 총 손실 절댓값

    # 기간 정보
    period_days: int = 90

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def loss_rate(self) -> float:
        return 1.0 - self.win_rate

    @property
    def avg_odds(self) -> float:
        """avg_win / avg_loss — Kelly의 'b' 파라미터."""
        if self.avg_loss_usdt == 0:
            return 0.0
        return float(self.avg_win_usdt / self.avg_loss_usdt)

    @property
    def profit_factor(self) -> float:
        if self.gross_loss_usdt == 0:
            return 0.0
        return float(self.gross_win_usdt / self.gross_loss_usdt)

    @property
    def is_sufficient(self) -> bool:
        return self.total_trades > 0

    def as_dict(self) -> dict:
        return {
            "total_trades":   self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades":  self.losing_trades,
            "win_rate":       f"{self.win_rate:.1%}",
            "avg_win_usdt":   str(self.avg_win_usdt),
            "avg_loss_usdt":  str(self.avg_loss_usdt),
            "avg_odds":       round(self.avg_odds, 3),
            "profit_factor":  round(self.profit_factor, 3),
            "total_pnl":      str(self.total_pnl),
            "period_days":    self.period_days,
        }


# ── Kelly 계산 결과 ───────────────────────────────────────────────────────────────

@dataclass
class KellyResult:
    """Kelly Criterion 계산 결과."""
    full_kelly_fraction: float       # Raw Kelly (종종 과도함)
    applied_fraction: float          # 분수 Kelly 적용 후 (안전한 값)
    kelly_multiplier: float          # 분수 비율 (예: 0.25 = Quarter-Kelly)
    win_rate: float
    avg_odds: float                  # avg_win / avg_loss
    sample_size: int
    is_valid: bool                   # 충분한 데이터 여부
    reason: str | None = None        # 무효 사유

    @property
    def capped_risk_pct(self) -> float:
        """
        안전 상한 5% 적용 후 최종 리스크 비율.
        Kelly가 매우 보수적인 경우 최솟값 0.5% 보장.
        """
        from agents.risk.constants import RISK_PER_TRADE_MAX, RISK_PER_TRADE_MIN
        return max(
            RISK_PER_TRADE_MIN,
            min(RISK_PER_TRADE_MAX, self.applied_fraction),
        )


# ── 사이징 결과 ───────────────────────────────────────────────────────────────────

@dataclass
class SizingResult:
    """
    Position Sizing 계산 결과.
    PositionSizingResult의 상위 호환 (method 정보 추가).
    """
    method: SizingMethod

    # ── 적용된 리스크 ──────────────────────────────────────────────────────
    risk_amount_usdt: Decimal        # 실제 리스크 금액 (USDT)
    risk_pct: float                  # 잔고 대비 실제 리스크 비율

    # ── 포지션 파라미터 ────────────────────────────────────────────────────
    quantity: Decimal                # 주문 수량 (코인 단위, lot_size 반올림)
    margin_used: Decimal             # 필요 증거금 (USDT)
    position_value: Decimal          # 명목 포지션 가치 (margin × leverage)
    max_loss: Decimal                # 최대 손실 = risk_amount_usdt
    max_profit: Decimal              # 최대 수익 (take_profit 있을 때)
    final_leverage: int              # 4중 상한 적용 최종 레버리지
    rr_ratio: Decimal                # R:R 비율

    # ── Kelly 전용 필드 (method=KELLY일 때만 값 있음) ───────────────────────
    kelly: KellyResult | None = None

    # ── 경고 ───────────────────────────────────────────────────────────────
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "method":           self.method.value,
            "risk_amount_usdt": str(self.risk_amount_usdt),
            "risk_pct":         f"{self.risk_pct:.2%}",
            "quantity":         str(self.quantity),
            "margin_used":      str(self.margin_used),
            "position_value":   str(self.position_value),
            "max_loss":         str(self.max_loss),
            "max_profit":       str(self.max_profit),
            "final_leverage":   self.final_leverage,
            "rr_ratio":         str(self.rr_ratio),
            "warnings":         self.warnings,
        }
        if self.kelly:
            d["kelly"] = {
                "full_kelly":      round(self.kelly.full_kelly_fraction, 4),
                "applied_fraction": round(self.kelly.applied_fraction, 4),
                "multiplier":      self.kelly.kelly_multiplier,
                "win_rate":        f"{self.kelly.win_rate:.1%}",
                "avg_odds":        round(self.kelly.avg_odds, 3),
                "sample_size":     self.kelly.sample_size,
            }
        return d


@dataclass
class SizingComparison:
    """4가지 방법 비교 결과."""
    signal_symbol: str
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal | None
    leverage: int
    account_balance: Decimal
    results: dict[str, dict]       # method → SizingResult.to_dict()

    def summary(self) -> dict:
        return {
            "signal": {
                "symbol":     self.signal_symbol,
                "entry":      str(self.entry_price),
                "stop_loss":  str(self.stop_loss),
                "take_profit":str(self.take_profit) if self.take_profit else None,
                "leverage":   self.leverage,
            },
            "account_balance": str(self.account_balance),
            "methods":         self.results,
        }
