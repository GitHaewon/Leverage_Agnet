"""
Trade Executor — 단일 거래의 진입/청산 시뮬레이션.

OHLCV 봉 기반 현실적 실행:
  - 진입: 다음 봉 시가 기준 (entry_on_next_open=True)
  - TP/SL 체결: 봉 내 고가/저가로 판단
  - 동일 봉에서 TP와 SL 모두 닿으면: 시가와의 거리로 우선순위 결정
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from agents.backtest.costs import (
    FeeCalculator,
    FundingFeeAccumulator,
    SlippageModel,
    net_pnl_from_prices,
)
from agents.backtest.models import (
    BacktestConfig,
    BacktestSignal,
    OHLCVBar,
    Trade,
    TradeExitReason,
)


class TradeExecutor:
    """
    단일 거래 진입/청산 시뮬레이터.

    사용 방법:
        executor = TradeExecutor(config)
        trade = executor.enter(signal, entry_bar)
        closed = executor.check_exit(trade, current_bar)
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._config    = config
        self._fee_calc  = FeeCalculator(config)
        self._slippage  = SlippageModel(config)
        self._funding   = FundingFeeAccumulator(config)

    # ════════════════════════════════════════════════════════════════
    # 진입
    # ════════════════════════════════════════════════════════════════

    def enter(
        self,
        signal: BacktestSignal,
        entry_bar: OHLCVBar,
        portfolio_value: Decimal,
        risk_amount: Decimal,
    ) -> Trade:
        """
        시그널 기반 포지션 진입 시뮬레이션.

        진입가:
          entry_on_next_open=True  → entry_bar.open 사용
          entry_on_next_open=False → signal.entry_price 사용

        Args:
            signal:          트레이딩 시그널
            entry_bar:       진입 봉 (신호 다음 봉)
            portfolio_value: 현재 포트폴리오 가치
            risk_amount:     이번 거래에 허용된 리스크 USDT

        Returns:
            진입 완료된 Trade 객체
        """
        base_price = (
            entry_bar.open
            if self._config.entry_on_next_open
            else signal.entry_price
        )

        # 슬리피지 적용
        actual_price, slip_cost = self._slippage.apply_entry(
            direction=signal.direction,
            signal_price=base_price,
            quantity=Decimal("1"),  # 임시 수량으로 비율 계산
            bar_volume=entry_bar.volume,
        )

        # 수량 계산 (TRADING_RULES §7.1 공식)
        sl_distance = abs(actual_price - signal.stop_loss)
        if sl_distance == 0:
            sl_distance = actual_price * Decimal("0.001")  # 0.1% 최소 SL

        quantity = _round_quantity(
            (risk_amount / sl_distance),
            signal.symbol,
        )

        if quantity <= 0:
            quantity = _min_quantity(signal.symbol)

        # 실제 슬리피지 비용 (올바른 수량 기준)
        _, slip_cost = self._slippage.apply_entry(
            direction=signal.direction,
            signal_price=base_price,
            quantity=quantity,
            bar_volume=entry_bar.volume,
        )

        margin = (quantity * actual_price) / signal.leverage

        # 진입 수수료
        entry_fee = self._fee_calc.calculate(quantity, actual_price)

        return Trade(
            trade_id=f"trade_{uuid.uuid4().hex[:8]}",
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_time=entry_bar.timestamp,
            signal_entry_price=signal.entry_price,
            actual_entry_price=actual_price,
            quantity=quantity,
            leverage=signal.leverage,
            margin_used=margin.quantize(Decimal("0.01")),
            take_profit=signal.take_profit,
            stop_loss=signal.stop_loss,
            entry_fee=entry_fee,
            slippage_cost=slip_cost.quantize(Decimal("0.00000001")),
        )

    # ════════════════════════════════════════════════════════════════
    # TP/SL 체결 확인
    # ════════════════════════════════════════════════════════════════

    def check_exit(
        self,
        trade: Trade,
        bar: OHLCVBar,
        force_exit: bool = False,
    ) -> Trade | None:
        """
        현재 봉에서 TP 또는 SL이 체결되었는지 확인.

        Args:
            trade:       오픈 포지션
            bar:         현재 OHLCV 봉
            force_exit:  True = 강제 청산 (시가 기준)

        Returns:
            청산된 Trade | None (청산 안 됨)
        """
        if force_exit:
            return self._close_trade(trade, bar, bar.close, TradeExitReason.TIMEOUT)

        exit_price, exit_reason = self._find_exit(trade, bar)
        if exit_price is None:
            return None

        return self._close_trade(trade, bar, exit_price, exit_reason)

    def _find_exit(
        self,
        trade: Trade,
        bar: OHLCVBar,
    ) -> tuple[Decimal | None, TradeExitReason | None]:
        """봉 내 TP/SL 체결 가격 결정."""
        tp = trade.take_profit
        sl = trade.stop_loss

        if trade.direction == "LONG":
            sl_hit = bar.low <= sl
            tp_hit = (tp is not None) and (bar.high >= tp)
        else:  # SHORT
            sl_hit = bar.high >= sl
            tp_hit = (tp is not None) and (bar.low <= tp)

        if not sl_hit and not tp_hit:
            return None, None

        # 둘 다 닿은 경우: 시가와의 거리로 우선순위 결정
        if sl_hit and tp_hit and tp is not None:
            sl_dist = abs(bar.open - sl)
            tp_dist = abs(bar.open - tp)
            if sl_dist < tp_dist:
                return sl, TradeExitReason.STOP_LOSS
            else:
                return tp, TradeExitReason.TAKE_PROFIT

        if tp_hit and tp is not None:
            return tp, TradeExitReason.TAKE_PROFIT
        if sl_hit:
            return sl, TradeExitReason.STOP_LOSS

        return None, None

    # ════════════════════════════════════════════════════════════════
    # 청산 처리
    # ════════════════════════════════════════════════════════════════

    def _close_trade(
        self,
        trade: Trade,
        bar: OHLCVBar,
        signal_exit_price: Decimal,
        exit_reason: TradeExitReason,
    ) -> Trade:
        """청산 슬리피지 적용 후 PnL 계산."""
        actual_exit, slip_extra = self._slippage.apply_exit(
            direction=trade.direction,
            signal_price=signal_exit_price,
            quantity=trade.quantity,
            bar_volume=bar.volume,
        )

        exit_fee = self._fee_calc.calculate(trade.quantity, actual_exit)

        # 펀딩비 — 이 봉이 펀딩 시점이면 마지막 한 번 추가
        funding = self._funding.calculate_single(
            direction=trade.direction,
            quantity=trade.quantity,
            mark_price=actual_exit,
            funding_rate=bar.funding_rate if bar.is_funding_bar else 0.0,
        ) if bar.is_funding_bar else Decimal("0")

        total_funding = trade.funding_fees + funding

        # 그로스 PnL (수수료/슬리피지 제외)
        gross = net_pnl_from_prices(
            direction=trade.direction,
            quantity=trade.quantity,
            entry_price=trade.actual_entry_price,
            exit_price=actual_exit,
            leverage=1,   # Quantity가 이미 레버리지를 반영
        )

        total_costs = (
            trade.entry_fee
            + exit_fee
            + abs(total_funding)
            + trade.slippage_cost
            + slip_extra
        )
        net = gross - total_costs

        trade.exit_time          = bar.timestamp
        trade.actual_exit_price  = actual_exit
        trade.exit_reason        = exit_reason
        trade.exit_fee           = exit_fee
        trade.funding_fees       = total_funding
        trade.slippage_cost     += slip_extra
        trade.gross_pnl          = gross.quantize(Decimal("0.01"))
        trade.net_pnl            = net.quantize(Decimal("0.01"))
        trade.pnl_pct            = (
            float(net / trade.margin_used * 100)
            if trade.margin_used > 0 else 0.0
        )
        return trade

    # ════════════════════════════════════════════════════════════════
    # 펀딩비 적립 (포지션 보유 중 8h마다 호출)
    # ════════════════════════════════════════════════════════════════

    def accrue_funding(self, trade: Trade, bar: OHLCVBar) -> Decimal:
        """
        펀딩비 부과 봉에서 호출.
        Returns: 이번 부과 금액 (양수 = 비용)
        """
        if not bar.is_funding_bar:
            return Decimal("0")

        fee = self._funding.calculate_single(
            direction=trade.direction,
            quantity=trade.quantity,
            mark_price=bar.close,
            funding_rate=bar.funding_rate,
        )
        trade.funding_fees += fee
        return fee


# ── 수량 헬퍼 ────────────────────────────────────────────────────────────────────

_LOT_SIZES = {"BTCUSDT": Decimal("0.001"), "ETHUSDT": Decimal("0.01")}
_MIN_QTY   = {"BTCUSDT": Decimal("0.001"), "ETHUSDT": Decimal("0.01")}


def _round_quantity(qty: Decimal, symbol: str) -> Decimal:
    from decimal import ROUND_DOWN
    lot = _LOT_SIZES.get(symbol, Decimal("0.001"))
    return (qty / lot).to_integral_value(rounding=ROUND_DOWN) * lot


def _min_quantity(symbol: str) -> Decimal:
    return _MIN_QTY.get(symbol, Decimal("0.001"))
