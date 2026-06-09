"""
Walk Forward Testing Engine — 메인 오케스트레이터.

실행 흐름:
  1. OHLCV → Rolling Window 분할 (splitter.py)
  2. 각 윈도우:
     a. IS: parameter_space 그리드 서치 → 최적 파라미터 탐색
     b. OOS: 최적 파라미터로 시뮬레이션 → 성과 검증
  3. 전체 OOS 합산 성과 계산
  4. 과적합 위험도 평가 → WalkForwardResult 반환
"""
from __future__ import annotations

import itertools
import logging
from typing import Any

import numpy as np
import pandas as pd

from .metrics import calculate_metrics
from .simulator import TradeSimulator
from .splitter import split_windows
from .types import (
    BaseStrategy,
    PerformanceMetrics,
    Trade,
    WalkForwardConfig,
    WalkForwardResult,
    WindowResult,
)
from .validator import validate_window

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = frozenset({"open", "high", "low", "close", "volume"})


def _validate_ohlcv(ohlcv: pd.DataFrame) -> None:
    missing = _REQUIRED_COLUMNS - set(ohlcv.columns)
    if missing:
        raise ValueError(f"OHLCV 필수 컬럼 누락: {missing}")
    if not isinstance(ohlcv.index, pd.DatetimeIndex):
        raise ValueError("OHLCV index는 DatetimeIndex여야 합니다")


def _param_combinations(space: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not space:
        return [{}]
    keys = list(space.keys())
    values = list(space.values())
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def _get_metric_value(metrics: PerformanceMetrics, metric_name: str) -> float:
    return float(getattr(metrics, metric_name, 0.0) or 0.0)


class WalkForwardEngine:
    """
    Walk Forward Testing Engine.

    IS 윈도우에서 최적 파라미터를 탐색하고,
    OOS 윈도우에서 해당 파라미터의 실제 성과를 검증한다.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        config: WalkForwardConfig | None = None,
    ) -> None:
        self.strategy = strategy
        self.config = config or WalkForwardConfig()
        self._simulator = TradeSimulator()

    def run(self, ohlcv: pd.DataFrame) -> WalkForwardResult:
        """
        Walk Forward Testing 전체 사이클 실행.

        raises ValueError: OHLCV 포맷 오류 또는 데이터 부족
        """
        _validate_ohlcv(ohlcv)
        windows = split_windows(ohlcv, self.config)

        if not windows:
            min_days = self.config.is_window_days + self.config.oos_window_days
            raise ValueError(
                f"데이터가 부족하여 윈도우를 생성할 수 없습니다. "
                f"최소 {min_days}일 데이터가 필요합니다."
            )

        window_results: list[WindowResult] = []
        all_oos_trades: list[Trade] = []
        running_equity = self.config.initial_capital
        combined_equity: list[float] = [running_equity]

        for idx, (is_df, oos_df) in enumerate(windows):
            logger.debug("윈도우 %d/%d 처리 중…", idx + 1, len(windows))

            # IS: 최적 파라미터 탐색
            best_params, is_trades, is_metrics, is_equity = self._optimize_is(is_df)

            # OOS: 최적 파라미터로 검증
            oos_trades, oos_equity = self._run_window(
                oos_df, best_params, self.config.initial_capital
            )
            oos_metrics = calculate_metrics(
                oos_trades,
                oos_equity,
                self.config,
                oos_df.index[0].to_pydatetime(),
                oos_df.index[-1].to_pydatetime(),
            )

            is_valid, eff_ratio, notes = validate_window(
                is_metrics, oos_metrics, self.config
            )

            window_results.append(WindowResult(
                window_id=idx,
                is_start=is_df.index[0].to_pydatetime(),
                is_end=is_df.index[-1].to_pydatetime(),
                oos_start=oos_df.index[0].to_pydatetime(),
                oos_end=oos_df.index[-1].to_pydatetime(),
                is_trades=is_trades,
                is_metrics=is_metrics,
                is_best_params=best_params,
                is_equity_curve=is_equity,
                oos_trades=oos_trades,
                oos_metrics=oos_metrics,
                oos_equity_curve=oos_equity,
                is_valid=is_valid,
                efficiency_ratio=eff_ratio,
                validation_notes=notes,
            ))

            # OOS 손익을 누적 equity에 반영
            all_oos_trades.extend(oos_trades)
            if oos_trades and len(oos_equity) > 1:
                deltas = [e - self.config.initial_capital for e in oos_equity[1:]]
                for delta in deltas:
                    running_equity += delta
                    combined_equity.append(running_equity)

        valid_windows = sum(1 for w in window_results if w.is_valid)

        oos_start_dt = window_results[0].oos_start if window_results else pd.Timestamp.utcnow().to_pydatetime()
        oos_end_dt = window_results[-1].oos_end if window_results else pd.Timestamp.utcnow().to_pydatetime()
        combined_metrics = calculate_metrics(
            all_oos_trades,
            combined_equity,
            self.config,
            oos_start_dt,
            oos_end_dt,
        )

        eff_ratios = [w.efficiency_ratio for w in window_results if w.efficiency_ratio > 0]
        avg_eff = float(np.mean(eff_ratios)) if eff_ratios else 0.0
        consistency = valid_windows / len(window_results) if window_results else 0.0

        return WalkForwardResult(
            config=self.config,
            total_windows=len(window_results),
            valid_windows=valid_windows,
            combined_oos_metrics=combined_metrics,
            combined_oos_equity=combined_equity,
            window_results=window_results,
            avg_efficiency_ratio=avg_eff,
            consistency_score=consistency,
            param_stability=self._analyze_param_stability(window_results),
            overfitting_risk=self._assess_overfitting_risk(avg_eff, consistency),
        )

    # ── IS 최적화 ─────────────────────────────────────────────────────────────

    def _optimize_is(
        self,
        is_df: pd.DataFrame,
    ) -> tuple[dict[str, Any], list[Trade], PerformanceMetrics, list[float]]:
        """
        IS 기간에서 parameter_space 그리드 서치.
        optimization_metric 기준으로 최고 파라미터를 반환한다.
        """
        param_combos = _param_combinations(self.strategy.parameter_space())

        best_score = float("-inf")
        best_params: dict[str, Any] = param_combos[0] if param_combos else {}
        best_trades: list[Trade] = []
        best_metrics = PerformanceMetrics.empty()
        best_equity: list[float] = [self.config.initial_capital]

        for params in param_combos:
            trades, equity = self._run_window(is_df, params, self.config.initial_capital)
            if len(trades) < self.config.min_trades_per_window:
                continue

            metrics = calculate_metrics(
                trades,
                equity,
                self.config,
                is_df.index[0].to_pydatetime(),
                is_df.index[-1].to_pydatetime(),
            )
            score = _get_metric_value(metrics, self.config.optimization_metric)
            if score > best_score:
                best_score = score
                best_params = params
                best_trades = trades
                best_metrics = metrics
                best_equity = equity

        return best_params, best_trades, best_metrics, best_equity

    def _run_window(
        self,
        ohlcv: pd.DataFrame,
        params: dict[str, Any],
        initial_capital: float,
    ) -> tuple[list[Trade], list[float]]:
        signals = self.strategy.generate_signals(ohlcv, params)
        return self._simulator.run(ohlcv, signals, self.config, initial_capital)

    # ── 분석 ──────────────────────────────────────────────────────────────────

    def _analyze_param_stability(
        self, windows: list[WindowResult]
    ) -> dict[str, Any]:
        """
        윈도우별 최적 파라미터 분포 분석.
        CV(변동계수) <= 0.5이면 안정적.
        """
        if not windows:
            return {}

        param_values: dict[str, list] = {}
        for w in windows:
            for k, v in w.is_best_params.items():
                param_values.setdefault(k, []).append(v)

        stability: dict[str, Any] = {}
        for param, values in param_values.items():
            try:
                arr = np.array(values, dtype=float)
                mean = float(np.mean(arr))
                std = float(np.std(arr))
                cv = std / mean if mean != 0 else 0.0
                stability[param] = {
                    "mean": round(mean, 4),
                    "std": round(std, 4),
                    "cv": round(cv, 4),
                    "stable": cv <= 0.5,
                }
            except (TypeError, ValueError):
                unique = list({str(v) for v in values})
                stability[param] = {
                    "unique_values": sorted(unique),
                    "stable": len(unique) == 1,
                }

        return stability

    @staticmethod
    def _assess_overfitting_risk(
        avg_efficiency: float, consistency: float
    ) -> str:
        """
        효율 비율과 일관성으로 과적합 위험도를 평가한다.

        low:    avg_eff >= 0.7 AND consistency >= 0.7
        medium: avg_eff >= 0.5 AND consistency >= 0.5
        high:   그 외
        """
        if avg_efficiency >= 0.7 and consistency >= 0.7:
            return "low"
        if avg_efficiency >= 0.5 and consistency >= 0.5:
            return "medium"
        return "high"
