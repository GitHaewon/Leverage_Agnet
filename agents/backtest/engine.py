"""
BacktestEngine — 메인 실행 엔진.

실행 루프:
  for each bar:
    1. 오픈 포지션 펀딩비 적립 (8h 봉이면)
    2. 오픈 포지션 TP/SL 체결 확인
    3. 이 봉에 해당하는 신호 진입 시뮬레이션
    4. equity 기록

설계 원칙:
  - 데이터 로딩은 호출자 책임 (순수 계산 엔진)
  - 신호는 미리 생성된 BacktestSignal 리스트 주입
  - 동시 포지션 한도 적용
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Sequence

from agents.backtest.costs import mark_funding_bars
from agents.backtest.executor import TradeExecutor
from agents.backtest.metrics import MetricsCalculator, build_equity_curve_with_drawdown
from agents.backtest.models import (
    BacktestConfig,
    BacktestResult,
    BacktestSignal,
    EquityPoint,
    OHLCVBar,
    Trade,
    TradeExitReason,
)

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    OHLCV + 시그널 기반 백테스트 실행 엔진.

    사용 예:
        engine = BacktestEngine(config)
        result = engine.run(signals, bars)
        print(result.metrics.to_dict())
    """

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self._config    = config or BacktestConfig()
        self._executor  = TradeExecutor(self._config)
        self._metrics   = MetricsCalculator(self._config)

    # ════════════════════════════════════════════════════════════════
    # 메인 실행
    # ════════════════════════════════════════════════════════════════

    def run(
        self,
        signals: Sequence[BacktestSignal],
        bars: Sequence[OHLCVBar],
        risk_amount_per_trade: Decimal | None = None,
    ) -> BacktestResult:
        """
        백테스트 실행.

        Args:
            signals:               시그널 리스트 (시간순 정렬)
            bars:                  OHLCV 봉 리스트 (시간순 정렬)
            risk_amount_per_trade: 거래당 리스크 금액 (None → 초기 자본의 2%)

        Returns:
            BacktestResult (trades, equity_curve, metrics 포함)
        """
        if not bars:
            raise ValueError("bars가 비어 있습니다.")

        # 펀딩비 봉 표시
        bars = list(mark_funding_bars(list(bars)))

        # 초기화
        cash     = self._config.initial_capital
        equity   = self._config.initial_capital
        open_trades: list[Trade] = []
        closed_trades: list[Trade] = []
        equity_curve: list[EquityPoint] = []

        # 기본 리스크 금액
        default_risk = (
            risk_amount_per_trade
            or self._config.initial_capital * Decimal("0.02")
        )

        # 시그널을 타임스탬프 → 리스트 맵으로 인덱싱
        signal_map = _build_signal_index(signals)

        # 다음 봉 진입 대기열
        pending_signal: BacktestSignal | None = None

        # 시작/종료 날짜
        start_date = bars[0].timestamp
        end_date   = bars[-1].timestamp

        logger.info(
            "Backtest 시작: %d 봉 / %d 시그널 / 초기자본 $%.2f",
            len(bars), len(signals), float(self._config.initial_capital),
        )

        for i, bar in enumerate(bars):

            # ── Step 1: 대기 중인 시그널 진입 ───────────────────────────────
            if pending_signal is not None:
                if len(open_trades) < self._config.max_open_positions:
                    trade = self._executor.enter(
                        signal=pending_signal,
                        entry_bar=bar,
                        portfolio_value=equity,
                        risk_amount=default_risk,
                    )
                    cash -= trade.margin_used + trade.entry_fee
                    open_trades.append(trade)
                    logger.debug(
                        "진입: %s %s @ $%.2f qty=%.4f",
                        trade.direction, trade.symbol,
                        float(trade.actual_entry_price), float(trade.quantity),
                    )
                pending_signal = None

            # ── Step 2: 펀딩비 적립 ─────────────────────────────────────────
            if bar.is_funding_bar:
                for trade in open_trades:
                    fee = self._executor.accrue_funding(trade, bar)
                    cash -= fee   # 비용 또는 수익 반영

            # ── Step 3: TP/SL 체결 확인 ─────────────────────────────────────
            still_open: list[Trade] = []
            for trade in open_trades:
                closed = self._executor.check_exit(trade, bar)
                if closed is not None:
                    # 증거금 반환 + 실현 PnL 반영
                    cash += closed.margin_used + (closed.net_pnl or Decimal("0"))
                    closed_trades.append(closed)
                    logger.debug(
                        "청산 [%s]: %s @ $%.2f PnL=$%.2f",
                        closed.exit_reason.value if closed.exit_reason else "?",
                        closed.symbol,
                        float(closed.actual_exit_price or 0),
                        float(closed.net_pnl or 0),
                    )
                else:
                    still_open.append(trade)
            open_trades = still_open

            # ── Step 4: 새 시그널 확인 (다음 봉에 진입) ────────────────────
            if bar.timestamp in signal_map:
                sigs = signal_map[bar.timestamp]
                if sigs and len(open_trades) < self._config.max_open_positions:
                    pending_signal = sigs[0]   # 첫 번째 신호만 사용

            # ── Step 5: equity 계산 ─────────────────────────────────────────
            unrealized = _calc_unrealized_pnl(open_trades, bar.close)
            equity = cash + sum(t.margin_used for t in open_trades) + unrealized

            equity_curve.append(EquityPoint(
                timestamp=bar.timestamp,
                equity=equity.quantize(Decimal("0.01")),
                cash=cash.quantize(Decimal("0.01")),
                unrealized_pnl=unrealized.quantize(Decimal("0.01")),
                open_positions=len(open_trades),
                peak_equity=Decimal("0"),   # 아래에서 채움
                drawdown_pct=0.0,
            ))

        # ── 백테스트 종료: 남은 포지션 강제 청산 ────────────────────────────
        if open_trades:
            last_bar = bars[-1]
            for trade in open_trades:
                closed = self._executor.check_exit(trade, last_bar, force_exit=True)
                if closed:
                    cash += closed.margin_used + (closed.net_pnl or Decimal("0"))
                    closed_trades.append(closed)

            # 마지막 equity 갱신
            if equity_curve:
                equity_curve[-1].equity = cash.quantize(Decimal("0.01"))
                equity_curve[-1].cash   = cash.quantize(Decimal("0.01"))

        # ── equity curve 낙폭 계산 ────────────────────────────────────────
        equity_curve = build_equity_curve_with_drawdown(equity_curve)

        # ── 성과 지표 계산 ────────────────────────────────────────────────
        all_trades = closed_trades   # 강제 청산 포함
        metrics = self._metrics.calculate(
            trades=all_trades,
            equity_curve=equity_curve,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self._config.initial_capital,
            total_bars=len(bars),
        )

        logger.info(
            "Backtest 완료: 거래 %d건 / 수익률 %.2f%% / MDD %.2f%% / Sharpe %.3f",
            metrics.total_trades,
            metrics.total_return,
            metrics.max_drawdown,
            metrics.sharpe_ratio,
        )

        return BacktestResult(
            config=self._config,
            trades=all_trades,
            equity_curve=equity_curve,
            metrics=metrics,
        )

    # ════════════════════════════════════════════════════════════════
    # 편의 메서드
    # ════════════════════════════════════════════════════════════════

    def run_with_risk_pct(
        self,
        signals: Sequence[BacktestSignal],
        bars: Sequence[OHLCVBar],
        risk_pct: float = 0.02,
    ) -> BacktestResult:
        """초기 자본의 risk_pct%를 거래당 리스크로 사용."""
        risk_amount = self._config.initial_capital * Decimal(str(risk_pct))
        return self.run(signals, bars, risk_amount)

    def summary(self, result: BacktestResult) -> str:
        """백테스트 결과 요약 텍스트."""
        m = result.metrics
        return (
            f"━━━━ Backtest 결과 ━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"기간:    {m.start_date.date()} ~ {m.end_date.date()} ({m.duration_days}일)\n"
            f"초기자본: ${float(m.initial_capital):,.2f}  최종자산: ${float(m.final_equity):,.2f}\n"
            f"\n[수익률]\n"
            f"  Total Return : {m.total_return:+.2f}%\n"
            f"  CAGR         : {m.cagr:+.2f}%\n"
            f"\n[위험]\n"
            f"  Max Drawdown : {m.max_drawdown:.2f}%\n"
            f"  Sharpe Ratio : {m.sharpe_ratio:.3f}\n"
            f"  Sortino      : {m.sortino_ratio:.3f}\n"
            f"  Calmar       : {m.calmar_ratio:.3f}\n"
            f"\n[거래]\n"
            f"  Profit Factor: {m.profit_factor:.3f}\n"
            f"  Win Rate     : {m.win_rate:.1%}\n"
            f"  Total Trades : {m.total_trades}\n"
            f"  Avg Win      : ${float(m.avg_win_usdt):,.2f}\n"
            f"  Avg Loss     : -${float(m.avg_loss_usdt):,.2f}\n"
            f"  Best Trade   : ${float(m.best_trade):,.2f}\n"
            f"  Worst Trade  : ${float(m.worst_trade):,.2f}\n"
            f"\n[비용]\n"
            f"  수수료       : ${float(m.total_fees):,.2f}\n"
            f"  슬리피지     : ${float(m.total_slippage):,.2f}\n"
            f"  펀딩비       : ${float(m.total_funding_fees):,.2f}\n"
            f"  총 비용      : ${float(m.total_costs):,.2f} ({m.cost_drag_pct:.2f}% drag)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────────

def _build_signal_index(
    signals: Sequence[BacktestSignal],
) -> dict[datetime, list[BacktestSignal]]:
    """타임스탬프 → 시그널 리스트 인덱스 생성."""
    index: dict[datetime, list[BacktestSignal]] = defaultdict(list)
    for sig in signals:
        index[sig.timestamp].append(sig)
    return dict(index)


def _calc_unrealized_pnl(
    open_trades: list[Trade],
    current_price: Decimal,
) -> Decimal:
    """오픈 포지션 미실현 PnL 합산."""
    total = Decimal("0")
    for trade in open_trades:
        if trade.direction == "LONG":
            pnl = (current_price - trade.actual_entry_price) * trade.quantity
        else:
            pnl = (trade.actual_entry_price - current_price) * trade.quantity
        total += pnl
    return total
