"""
Walk Forward Testing Engine — 타입 정의.

TRADING_RULES.md 상수 포함:
  §1.1  SYSTEM_MAX_LEVERAGE = 20
  §3.1  RISK_PER_TRADE_MIN / MAX
  §7.4  MIN_RR_RATIO = 2.0
  §11.3 MIN_CONFIDENCE = 0.60
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import pandas as pd

# ── TRADING_RULES.md 상수 ────────────────────────────────────────────────────

SYSTEM_MAX_LEVERAGE: int = 20
MIN_RR_RATIO: float = 2.0
MIN_CONFIDENCE: float = 0.60
RISK_PER_TRADE_MIN: float = 0.005
RISK_PER_TRADE_MAX: float = 0.050


@dataclass
class SignalData:
    """전략이 생성한 거래 시그널."""

    timestamp: datetime
    direction: Literal["LONG", "SHORT"]
    entry_price: float
    take_profit: float
    stop_loss: float
    confidence: float = 1.0      # 0.0 ~ 1.0
    leverage: int = 1
    symbol: str = "BTCUSDT"


@dataclass
class Trade:
    """시뮬레이션된 단일 거래 결과."""

    entry_time: datetime
    exit_time: datetime
    direction: str
    entry_price: float
    exit_price: float
    quantity: float
    leverage: int
    margin_used: float
    pnl_usdt: float              # 수수료 반영 순손익
    pnl_pct: float               # 증거금 기준 수익률
    rr_ratio: float
    close_reason: str            # "tp_hit" | "sl_hit" | "window_end"
    gross_pnl: float             # 수수료 전 손익
    commission: float


@dataclass
class PerformanceMetrics:
    """4대 성과 지표 + 보조 지표."""

    # 4대 성과 지표
    cagr: float                  # Compound Annual Growth Rate
    sharpe_ratio: float          # Sharpe Ratio (연환산)
    max_drawdown: float          # Maximum Drawdown (음수, -0.15 = -15%)
    profit_factor: float         # 총 수익 / 총 손실

    # 보조 지표
    win_rate: float
    total_trades: int
    total_pnl_usdt: float
    avg_pnl_usdt: float
    calmar_ratio: float          # CAGR / |MDD|
    best_trade_usdt: float
    worst_trade_usdt: float
    final_equity: float

    @classmethod
    def empty(cls) -> "PerformanceMetrics":
        return cls(
            cagr=0.0, sharpe_ratio=0.0, max_drawdown=0.0,
            profit_factor=0.0, win_rate=0.0, total_trades=0,
            total_pnl_usdt=0.0, avg_pnl_usdt=0.0, calmar_ratio=0.0,
            best_trade_usdt=0.0, worst_trade_usdt=0.0, final_equity=0.0,
        )


@dataclass
class WalkForwardConfig:
    """
    WFT 엔진 설정.

    기본값은 TRADING_RULES.md 권장 사항 기반:
      - risk_per_trade: 2% (§3.1 중간값)
      - commission_rate: 0.04% (Binance Futures taker fee)
      - max_leverage: 5 (Free 플랜 상한)
    """

    # 자본 설정
    initial_capital: float = 10_000.0
    risk_per_trade: float = 0.02         # §3.1: 2% per trade
    commission_rate: float = 0.0004      # Binance taker 0.04%
    slippage_rate: float = 0.0001        # 0.01% 슬리피지 가정
    max_leverage: int = 5

    # Rolling Window 설정
    is_window_days: int = 90             # In-Sample: 3개월
    oos_window_days: int = 30            # Out-of-Sample: 1개월
    step_days: int = 30                  # 슬라이드 간격

    # 파라미터 검증
    min_trades_per_window: int = 5       # 유효 윈도우 최소 거래 수
    efficiency_threshold: float = 0.5   # OOS/IS Sharpe 최소 비율

    # 최적화 기준
    optimization_metric: str = "sharpe_ratio"   # IS 그리드 서치 기준 지표

    # 리스크-프리 이율
    risk_free_rate: float = 0.05         # 연간 5%


@dataclass
class WindowResult:
    """단일 IS/OOS 윈도우 결과."""

    window_id: int
    is_start: datetime
    is_end: datetime
    oos_start: datetime
    oos_end: datetime

    # IS 결과
    is_trades: list[Trade]
    is_metrics: PerformanceMetrics
    is_best_params: dict[str, Any]
    is_equity_curve: list[float]

    # OOS 결과
    oos_trades: list[Trade]
    oos_metrics: PerformanceMetrics
    oos_equity_curve: list[float]

    # 파라미터 유효성 검증
    is_valid: bool
    efficiency_ratio: float              # OOS Sharpe / IS Sharpe
    validation_notes: list[str]


@dataclass
class WalkForwardResult:
    """WFT 전체 실행 결과."""

    config: WalkForwardConfig
    total_windows: int
    valid_windows: int

    # 전체 OOS 합산 성과 (진짜 성과)
    combined_oos_metrics: PerformanceMetrics
    combined_oos_equity: list[float]

    # 개별 윈도우 결과
    window_results: list[WindowResult]

    # 요약 통계
    avg_efficiency_ratio: float
    consistency_score: float             # 유효 윈도우 비율 (0.0 ~ 1.0)
    param_stability: dict[str, Any]      # 파라미터별 안정성 분석
    overfitting_risk: str                # "low" | "medium" | "high"


# ── 전략 베이스 클래스 ────────────────────────────────────────────────────────

class BaseStrategy(abc.ABC):
    """
    WFT 엔진에서 요구하는 전략 인터페이스.

    구현 요구사항:
      - generate_signals(): OHLCV + 파라미터 → 시그널 목록
      - parameter_space(): IS 그리드 서치에 사용할 파라미터 공간
    """

    @abc.abstractmethod
    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any],
    ) -> list[SignalData]:
        """
        ohlcv 컬럼: open, high, low, close, volume (DatetimeIndex, UTC)
        반환 시그널의 timestamp는 ohlcv 인덱스 범위 내여야 한다.
        """

    @abc.abstractmethod
    def parameter_space(self) -> dict[str, list[Any]]:
        """
        파라미터 이름 → 탐색할 값 리스트.
        예: {"rsi_period": [14, 21], "rsi_oversold": [30, 35]}
        그리드 서치 조합 수 = 각 리스트 크기의 곱.
        """
