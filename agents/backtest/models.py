"""
Backtest Engine 데이터 모델.

설계 원칙:
  - 금융 데이터는 모두 Decimal (float 절대 사용 금지)
  - 타임스탬프는 UTC TIMESTAMPTZ
  - 순수 dataclass — 외부 의존성 없음
"""
from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal


# ── 설정 ────────────────────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    """백테스트 실행 설정."""

    # ── 초기 자본 ──────────────────────────────────────────────────────────────
    initial_capital: Decimal = Decimal("10000")   # USDT

    # ── 수수료 (Binance Futures 기준) ──────────────────────────────────────────
    taker_fee_rate: float = 0.0004    # 0.04% — 시장가 주문
    maker_fee_rate: float = 0.0002    # 0.02% — 지정가 주문
    use_taker_fee: bool = True        # True = 시장가 기준

    # ── 슬리피지 ──────────────────────────────────────────────────────────────
    slippage_model: Literal["fixed", "volume"] = "fixed"
    slippage_rate: float = 0.0005     # 0.05% 고정 슬리피지
    slippage_volume_factor: float = 0.1  # volume 모델: 주문량 / 봉 거래량 × factor

    # ── 펀딩피 ────────────────────────────────────────────────────────────────
    funding_interval_hours: int = 8   # 8시간마다 (Binance 표준)
    default_funding_rate: float = 0.0001   # 0.01% per interval (기본값)
    apply_funding_fee: bool = True

    # ── 성과 지표 계산 ────────────────────────────────────────────────────────
    risk_free_rate: float = 0.04      # 4% 연율 (Sharpe Ratio 기준)
    periods_per_year: int = 365       # 일 기준 (암호화폐 24/7)

    # ── 실행 규칙 ─────────────────────────────────────────────────────────────
    entry_on_next_open: bool = True   # True = 신호 다음 봉 시가 진입 (더 현실적)
    max_open_positions: int = 1       # 동시 오픈 포지션 한도


# ── 입력 데이터 ─────────────────────────────────────────────────────────────────

@dataclass
class OHLCVBar:
    """단일 OHLCV 캔들 (백테스트 가격 데이터)."""
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    funding_rate: float = 0.0001    # 해당 봉 펀딩비율 (8h 집계)
    is_funding_bar: bool = False    # 00:00 / 08:00 / 16:00 UTC 봉


@dataclass
class BacktestSignal:
    """백테스트용 트레이딩 시그널."""
    timestamp: datetime              # 시그널 생성 시각
    symbol: str                      # "BTCUSDT"
    direction: Literal["LONG", "SHORT"]
    confidence: float                # 0.0 ~ 1.0
    entry_price: Decimal             # 시그널 진입가 (실제 체결가 ≠)
    take_profit: Decimal | None
    stop_loss: Decimal               # 필수
    leverage: int
    rr_ratio: float
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ── 거래 기록 ────────────────────────────────────────────────────────────────────

class TradeExitReason(str, enum.Enum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS   = "stop_loss"
    SIGNAL      = "signal"       # 반대 시그널 진입
    TIMEOUT     = "timeout"      # 백테스트 종료
    MANUAL      = "manual"       # 수동 청산


@dataclass
class Trade:
    """단일 포지션 진입~청산 기록."""

    # ── 식별 ──────────────────────────────────────────────────────────────────
    trade_id: str
    signal_id: str
    symbol: str
    direction: Literal["LONG", "SHORT"]

    # ── 진입 ──────────────────────────────────────────────────────────────────
    entry_time: datetime
    signal_entry_price: Decimal      # 원래 시그널 가격
    actual_entry_price: Decimal      # 슬리피지 적용 후 실제 체결가
    quantity: Decimal                # 코인 단위
    leverage: int
    margin_used: Decimal             # 증거금 (USDT)

    take_profit: Decimal | None
    stop_loss: Decimal

    # ── 청산 (진입 후 채워짐) ──────────────────────────────────────────────────
    exit_time: datetime | None          = None
    actual_exit_price: Decimal | None   = None
    exit_reason: TradeExitReason | None = None

    # ── 비용 ──────────────────────────────────────────────────────────────────
    entry_fee: Decimal     = Decimal("0")    # 진입 수수료
    exit_fee: Decimal      = Decimal("0")    # 청산 수수료
    funding_fees: Decimal  = Decimal("0")    # 누적 펀딩비
    slippage_cost: Decimal = Decimal("0")    # 슬리피지 비용 (절댓값)

    # ── 손익 (청산 후 채워짐) ────────────────────────────────────────────────
    gross_pnl: Decimal | None = None         # 수수료/슬리피지 전 PnL
    net_pnl: Decimal | None   = None         # 모든 비용 차감 후 순 PnL
    pnl_pct: float | None     = None         # 증거금 대비 수익률 (%)

    @property
    def duration_hours(self) -> float | None:
        if self.exit_time is None:
            return None
        delta = self.exit_time - self.entry_time
        return delta.total_seconds() / 3600

    @property
    def total_costs(self) -> Decimal:
        return self.entry_fee + self.exit_fee + self.funding_fees + self.slippage_cost

    @property
    def is_winner(self) -> bool | None:
        if self.net_pnl is None:
            return None
        return self.net_pnl > 0


# ── 포트폴리오 추적 ──────────────────────────────────────────────────────────────

@dataclass
class EquityPoint:
    """시점별 포트폴리오 상태 스냅샷 (equity curve)."""
    timestamp: datetime
    equity: Decimal              # 총 자산 (현금 + 미실현 PnL)
    cash: Decimal                # 사용 가능 현금
    unrealized_pnl: Decimal      # 미실현 PnL
    open_positions: int
    peak_equity: Decimal         # 이 시점까지의 최고 자산
    drawdown_pct: float          # 현재 낙폭 (음수, %)


# ── 성과 지표 ────────────────────────────────────────────────────────────────────

@dataclass
class BacktestMetrics:
    """백테스트 전체 성과 지표 (6종 + 보조 지표)."""

    # ── 핵심 6종 ─────────────────────────────────────────────────────────────
    total_return: float          # 총 수익률 (%)
    cagr: float                  # 연환산 수익률 (%)
    max_drawdown: float          # 최대 낙폭 (%, 음수)
    sharpe_ratio: float          # Sharpe Ratio
    profit_factor: float         # 총 수익 / 총 손실
    win_rate: float              # 승률 (0.0 ~ 1.0)

    # ── 보조 지표 ────────────────────────────────────────────────────────────
    sortino_ratio: float         # Sharpe (하방 변동성 기준)
    calmar_ratio: float          # CAGR / |MDD|

    # ── 거래 통계 ────────────────────────────────────────────────────────────
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win_usdt: Decimal
    avg_loss_usdt: Decimal
    avg_trade_duration_hours: float
    best_trade: Decimal
    worst_trade: Decimal

    # ── 비용 분석 ────────────────────────────────────────────────────────────
    total_fees: Decimal
    total_slippage: Decimal
    total_funding_fees: Decimal
    total_costs: Decimal         # 전체 비용 합계
    cost_drag_pct: float         # 비용이 수익률에 미친 영향 (%)

    # ── 기간 정보 ────────────────────────────────────────────────────────────
    start_date: datetime
    end_date: datetime
    duration_days: int
    total_bars: int

    # ── 자본 ─────────────────────────────────────────────────────────────────
    initial_capital: Decimal
    final_equity: Decimal

    def to_dict(self) -> dict:
        return {
            "returns": {
                "total_return":  f"{self.total_return:.2f}%",
                "cagr":          f"{self.cagr:.2f}%",
                "final_equity":  str(self.final_equity),
                "initial_capital": str(self.initial_capital),
            },
            "risk": {
                "max_drawdown":  f"{self.max_drawdown:.2f}%",
                "sharpe_ratio":  round(self.sharpe_ratio, 3),
                "sortino_ratio": round(self.sortino_ratio, 3),
                "calmar_ratio":  round(self.calmar_ratio, 3),
            },
            "trades": {
                "profit_factor": round(self.profit_factor, 3),
                "win_rate":      f"{self.win_rate:.1%}",
                "total_trades":  self.total_trades,
                "winning":       self.winning_trades,
                "losing":        self.losing_trades,
                "avg_win":       str(self.avg_win_usdt),
                "avg_loss":      str(self.avg_loss_usdt),
                "best_trade":    str(self.best_trade),
                "worst_trade":   str(self.worst_trade),
                "avg_duration_hours": round(self.avg_trade_duration_hours, 1),
            },
            "costs": {
                "total_fees":         str(self.total_fees),
                "total_slippage":     str(self.total_slippage),
                "total_funding_fees": str(self.total_funding_fees),
                "total_costs":        str(self.total_costs),
                "cost_drag_pct":      f"{self.cost_drag_pct:.2f}%",
            },
            "period": {
                "start_date":   self.start_date.isoformat(),
                "end_date":     self.end_date.isoformat(),
                "duration_days": self.duration_days,
                "total_bars":   self.total_bars,
            },
        }


@dataclass
class BacktestResult:
    """백테스트 전체 결과."""
    config: BacktestConfig
    trades: list[Trade]
    equity_curve: list[EquityPoint]
    metrics: BacktestMetrics

    @property
    def closed_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.exit_time is not None]

    @property
    def open_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.exit_time is None]
