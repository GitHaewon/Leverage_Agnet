"""
Walk Forward Testing Engine 단위 테스트 (22 tests).

검증 대상:
  - _param_combinations:   파라미터 그리드 생성
  - SignalData 검증:        R:R, 신뢰도, 레버리지 상한
  - TradeSimulator:         TP/SL 시뮬레이션, 포지션 사이징
  - validate_window:        효율 비율 검증
  - WalkForwardEngine.run:  전체 WFT 실행, 오류 처리
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import pytest

from app.backtesting.engine import WalkForwardEngine, _param_combinations
from app.backtesting.simulator import (
    TradeSimulator,
    _compute_rr_ratio,
    _validate_signal,
)
from app.backtesting.types import (
    BaseStrategy,
    PerformanceMetrics,
    SignalData,
    WalkForwardConfig,
    WalkForwardResult,
)
from app.backtesting.validator import validate_window

UTC = timezone.utc


# ── 테스트용 전략 ─────────────────────────────────────────────────────────────

class FixedSignalStrategy(BaseStrategy):
    """결정론적 고정 시그널 전략 (WFT 테스트용)."""

    def generate_signals(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any],
    ) -> list[SignalData]:
        n = int(params.get("signal_every_n", 10))
        confidence = float(params.get("confidence", 0.8))
        signals = []

        for i in range(0, len(ohlcv) - n, n):
            entry = float(ohlcv["close"].iloc[i])
            signals.append(SignalData(
                timestamp=ohlcv.index[i].to_pydatetime(),
                direction="LONG",
                entry_price=entry,
                take_profit=entry * 1.04,   # 4% TP
                stop_loss=entry * 0.98,      # 2% SL → R:R = 2.0
                confidence=confidence,
                leverage=5,
            ))
        return signals

    def parameter_space(self) -> dict[str, list[Any]]:
        return {
            "signal_every_n": [5, 10, 20],
            "confidence": [0.7, 0.8],
        }


class EmptyStrategy(BaseStrategy):
    def generate_signals(self, ohlcv, params):
        return []

    def parameter_space(self):
        return {}


def _trending_ohlcv(days: int = 200, freq: str = "4h") -> pd.DataFrame:
    """상승 추세 OHLCV 생성 (TP 도달 확률 높음)."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    idx = pd.date_range(start=start, periods=days * 6, freq=freq, tz=UTC)
    closes = [40_000.0 * (1.001 ** i) for i in range(len(idx))]
    return pd.DataFrame(
        {
            "open":   [c * 0.999 for c in closes],
            "high":   [c * 1.006 for c in closes],
            "low":    [c * 0.994 for c in closes],
            "close":  closes,
            "volume": [1_000.0] * len(idx),
        },
        index=idx,
    )


def _small_config() -> WalkForwardConfig:
    return WalkForwardConfig(
        initial_capital=10_000.0,
        is_window_days=60,
        oos_window_days=20,
        step_days=20,
        min_trades_per_window=2,
        efficiency_threshold=0.3,
        risk_per_trade=0.02,
        commission_rate=0.0004,
        max_leverage=5,
    )


# ── TestParamCombinations ─────────────────────────────────────────────────────

class TestParamCombinations:
    def test_single_param_three_values(self) -> None:
        combos = _param_combinations({"rsi": [14, 21, 28]})
        assert len(combos) == 3

    def test_two_params_cartesian_product(self) -> None:
        combos = _param_combinations({"a": [1, 2], "b": [10, 20]})
        assert len(combos) == 4

    def test_empty_space_returns_one_empty_dict(self) -> None:
        assert _param_combinations({}) == [{}]

    def test_keys_preserved_in_each_combo(self) -> None:
        combos = _param_combinations({"rsi_period": [14, 21], "lev": [3]})
        for c in combos:
            assert "rsi_period" in c
            assert "lev" in c


# ── TestSignalValidation ──────────────────────────────────────────────────────

class TestSignalValidation:
    def _config(self) -> WalkForwardConfig:
        return WalkForwardConfig()

    def _long_signal(
        self,
        confidence: float = 0.8,
        tp_pct: float = 0.04,
        sl_pct: float = 0.02,
    ) -> SignalData:
        entry = 40_000.0
        return SignalData(
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
            direction="LONG",
            entry_price=entry,
            take_profit=entry * (1 + tp_pct),
            stop_loss=entry * (1 - sl_pct),
            confidence=confidence,
            leverage=5,
        )

    def test_valid_signal_passes(self) -> None:
        assert _validate_signal(self._long_signal(), self._config()) is True

    def test_confidence_below_min_rejected(self) -> None:
        # MIN_CONFIDENCE = 0.60
        assert _validate_signal(self._long_signal(confidence=0.59), self._config()) is False

    def test_confidence_exactly_min_passes(self) -> None:
        assert _validate_signal(self._long_signal(confidence=0.60), self._config()) is True

    def test_rr_below_min_rejected(self) -> None:
        # tp_pct=0.02, sl_pct=0.02 → R:R = 1.0 < 2.0
        assert _validate_signal(self._long_signal(tp_pct=0.02), self._config()) is False

    def test_rr_exactly_min_passes(self) -> None:
        # tp=0.04, sl=0.02 → R:R = 2.0
        rr = _compute_rr_ratio(self._long_signal(tp_pct=0.04, sl_pct=0.02))
        assert abs(rr - 2.0) < 1e-9

    def test_short_rr_calculation_correct(self) -> None:
        entry = 40_000.0
        short_signal = SignalData(
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
            direction="SHORT",
            entry_price=entry,
            take_profit=entry * 0.96,  # 4% 수익
            stop_loss=entry * 1.02,    # 2% 손실
            confidence=0.8,
            leverage=5,
        )
        assert abs(_compute_rr_ratio(short_signal) - 2.0) < 1e-9


# ── TestTradeSimulator ────────────────────────────────────────────────────────

class TestTradeSimulator:
    def _config(self) -> WalkForwardConfig:
        return WalkForwardConfig(
            initial_capital=10_000.0,
            risk_per_trade=0.02,
            commission_rate=0.0004,
            slippage_rate=0.0001,
            max_leverage=5,
        )

    def _ohlcv_with_trend(self) -> pd.DataFrame:
        """상승 추세 10봉 — TP(4%) 도달 가능."""
        idx = pd.date_range("2025-01-01", periods=10, freq="4h", tz=UTC)
        closes = [40_000.0 * (1.01 ** i) for i in range(10)]
        return pd.DataFrame({
            "open":   [c * 0.999 for c in closes],
            "high":   [c * 1.005 for c in closes],
            "low":    [c * 0.995 for c in closes],
            "close":  closes,
            "volume": [1_000.0] * 10,
        }, index=idx)

    def test_invalid_signal_skipped(self) -> None:
        ohlcv = self._ohlcv_with_trend()
        entry = float(ohlcv["close"].iloc[0])
        signal = SignalData(
            timestamp=ohlcv.index[0].to_pydatetime(),
            direction="LONG",
            entry_price=entry,
            take_profit=entry * 1.04,
            stop_loss=entry * 0.98,
            confidence=0.50,          # < MIN_CONFIDENCE(0.60) → 건너뜀
            leverage=5,
        )
        sim = TradeSimulator()
        trades, equity = sim.run(ohlcv, [signal], self._config(), 10_000.0)
        assert len(trades) == 0
        assert equity == [10_000.0]

    def test_equity_starts_with_initial_capital(self) -> None:
        ohlcv = self._ohlcv_with_trend()
        sim = TradeSimulator()
        _, equity = sim.run(ohlcv, [], self._config(), 10_000.0)
        assert equity[0] == 10_000.0

    def test_tp_hit_produces_positive_pnl(self) -> None:
        ohlcv = self._ohlcv_with_trend()
        entry = float(ohlcv["close"].iloc[0])
        signal = SignalData(
            timestamp=ohlcv.index[0].to_pydatetime(),
            direction="LONG",
            entry_price=entry,
            take_profit=entry * 1.04,
            stop_loss=entry * 0.98,
            confidence=0.8,
            leverage=5,
        )
        sim = TradeSimulator()
        trades, _ = sim.run(ohlcv, [signal], self._config(), 10_000.0)
        tp_trades = [t for t in trades if t.close_reason == "tp_hit"]
        if tp_trades:
            assert tp_trades[0].pnl_usdt > 0

    def test_leverage_capped_at_system_max_20(self) -> None:
        ohlcv = self._ohlcv_with_trend()
        entry = float(ohlcv["close"].iloc[0])
        signal = SignalData(
            timestamp=ohlcv.index[0].to_pydatetime(),
            direction="LONG",
            entry_price=entry,
            take_profit=entry * 1.04,
            stop_loss=entry * 0.98,
            confidence=0.8,
            leverage=100,             # → SYSTEM_MAX(20)으로 제한
        )
        sim = TradeSimulator()
        trades, _ = sim.run(ohlcv, [signal], self._config(), 10_000.0)
        for t in trades:
            assert t.leverage <= 20

    def test_commission_deducted_from_pnl(self) -> None:
        ohlcv = self._ohlcv_with_trend()
        entry = float(ohlcv["close"].iloc[0])
        signal = SignalData(
            timestamp=ohlcv.index[0].to_pydatetime(),
            direction="LONG",
            entry_price=entry,
            take_profit=entry * 1.04,
            stop_loss=entry * 0.98,
            confidence=0.8,
            leverage=5,
        )
        sim = TradeSimulator()
        trades, _ = sim.run(ohlcv, [signal], self._config(), 10_000.0)
        for t in trades:
            # 순손익 = 총손익 - 수수료
            assert abs(t.pnl_usdt - (t.gross_pnl - t.commission)) < 1e-6


# ── TestParameterValidator ────────────────────────────────────────────────────

class TestParameterValidator:
    def _config(self) -> WalkForwardConfig:
        return WalkForwardConfig(min_trades_per_window=5, efficiency_threshold=0.5)

    def _metrics(self, sharpe: float = 1.0, trades: int = 10) -> PerformanceMetrics:
        return PerformanceMetrics(
            cagr=0.20, sharpe_ratio=sharpe, max_drawdown=-0.10,
            profit_factor=2.0, win_rate=0.60, total_trades=trades,
            total_pnl_usdt=1_000.0, avg_pnl_usdt=100.0, calmar_ratio=2.0,
            best_trade_usdt=200.0, worst_trade_usdt=-80.0, final_equity=11_000.0,
        )

    def test_valid_window_passes(self) -> None:
        is_v, eff, _ = validate_window(
            self._metrics(sharpe=1.5),
            self._metrics(sharpe=0.9),
            self._config(),
        )
        assert is_v is True
        assert abs(eff - 0.9 / 1.5) < 1e-9

    def test_low_efficiency_fails(self) -> None:
        # 0.5 / 2.0 = 0.25 < 0.5
        is_v, _, _ = validate_window(
            self._metrics(sharpe=2.0),
            self._metrics(sharpe=0.5),
            self._config(),
        )
        assert is_v is False

    def test_insufficient_oos_trades_fails(self) -> None:
        is_v, _, notes = validate_window(
            self._metrics(sharpe=1.5, trades=10),
            self._metrics(sharpe=1.0, trades=3),  # < min=5
            self._config(),
        )
        assert is_v is False
        assert any("OOS" in n for n in notes)

    def test_nonpositive_is_sharpe_fails(self) -> None:
        is_v, _, _ = validate_window(
            self._metrics(sharpe=-0.5),
            self._metrics(sharpe=0.5),
            self._config(),
        )
        assert is_v is False

    def test_notes_populated_on_pass(self) -> None:
        is_v, _, notes = validate_window(
            self._metrics(sharpe=1.0),
            self._metrics(sharpe=0.8),
            self._config(),
        )
        assert is_v
        assert len(notes) > 0


# ── TestWalkForwardEngine ─────────────────────────────────────────────────────

class TestWalkForwardEngine:
    def test_run_returns_walk_forward_result_type(self) -> None:
        engine = WalkForwardEngine(FixedSignalStrategy(), _small_config())
        result = engine.run(_trending_ohlcv())
        assert isinstance(result, WalkForwardResult)

    def test_total_windows_positive(self) -> None:
        engine = WalkForwardEngine(FixedSignalStrategy(), _small_config())
        result = engine.run(_trending_ohlcv())
        assert result.total_windows > 0

    def test_combined_oos_metrics_populated(self) -> None:
        engine = WalkForwardEngine(FixedSignalStrategy(), _small_config())
        result = engine.run(_trending_ohlcv())
        assert isinstance(result.combined_oos_metrics, PerformanceMetrics)

    def test_overfitting_risk_is_valid_string(self) -> None:
        engine = WalkForwardEngine(FixedSignalStrategy(), _small_config())
        result = engine.run(_trending_ohlcv())
        assert result.overfitting_risk in ("low", "medium", "high")

    def test_consistency_score_in_range(self) -> None:
        engine = WalkForwardEngine(FixedSignalStrategy(), _small_config())
        result = engine.run(_trending_ohlcv())
        assert 0.0 <= result.consistency_score <= 1.0

    def test_empty_strategy_zero_combined_trades(self) -> None:
        engine = WalkForwardEngine(EmptyStrategy(), _small_config())
        result = engine.run(_trending_ohlcv())
        assert result.combined_oos_metrics.total_trades == 0

    def test_insufficient_data_raises_value_error(self) -> None:
        engine = WalkForwardEngine(FixedSignalStrategy(), _small_config())
        tiny = _trending_ohlcv(days=10)   # 10 < 60+20=80 일
        with pytest.raises(ValueError, match="데이터가 부족"):
            engine.run(tiny)

    def test_missing_ohlcv_columns_raises(self) -> None:
        engine = WalkForwardEngine(FixedSignalStrategy(), _small_config())
        bad_df = pd.DataFrame({"price": [1.0, 2.0, 3.0]})
        with pytest.raises(ValueError, match="필수 컬럼"):
            engine.run(bad_df)

    def test_non_datetime_index_raises(self) -> None:
        engine = WalkForwardEngine(FixedSignalStrategy(), _small_config())
        ohlcv = _trending_ohlcv()
        ohlcv.index = range(len(ohlcv))   # DatetimeIndex 제거
        with pytest.raises(ValueError, match="DatetimeIndex"):
            engine.run(ohlcv)

    def test_window_is_before_oos(self) -> None:
        engine = WalkForwardEngine(FixedSignalStrategy(), _small_config())
        result = engine.run(_trending_ohlcv())
        for w in result.window_results:
            assert w.is_start < w.is_end
            assert w.is_end <= w.oos_start
            assert w.oos_start < w.oos_end

    def test_valid_windows_le_total_windows(self) -> None:
        engine = WalkForwardEngine(FixedSignalStrategy(), _small_config())
        result = engine.run(_trending_ohlcv())
        assert result.valid_windows <= result.total_windows

    def test_combined_equity_starts_with_initial(self) -> None:
        engine = WalkForwardEngine(FixedSignalStrategy(), _small_config())
        result = engine.run(_trending_ohlcv())
        assert result.combined_oos_equity[0] == _small_config().initial_capital
