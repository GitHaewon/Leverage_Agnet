"""
Walk Forward Testing Engine — 파라미터 유효성 검증.

IS에서 최적화된 파라미터가 OOS에서도 유효한지 효율 비율로 판정한다.

  efficiency_ratio = OOS Sharpe / IS Sharpe

효율 비율이 config.efficiency_threshold (기본 0.5) 이상이면 유효 윈도우.
"""
from __future__ import annotations

from .types import PerformanceMetrics, WalkForwardConfig


def validate_window(
    is_metrics: PerformanceMetrics,
    oos_metrics: PerformanceMetrics,
    config: WalkForwardConfig,
) -> tuple[bool, float, list[str]]:
    """
    IS 대비 OOS 성과를 검증한다.

    반환: (is_valid, efficiency_ratio, validation_notes)
    """
    notes: list[str] = []

    # 거래 수 최소 요건
    if oos_metrics.total_trades < config.min_trades_per_window:
        notes.append(
            f"OOS 거래 부족: {oos_metrics.total_trades}건 "
            f"(최소 {config.min_trades_per_window}건)"
        )
        return False, 0.0, notes

    if is_metrics.total_trades < config.min_trades_per_window:
        notes.append(
            f"IS 거래 부족: {is_metrics.total_trades}건 "
            f"(최소 {config.min_trades_per_window}건)"
        )
        return False, 0.0, notes

    # IS Sharpe가 0 이하이면 파라미터 자체가 유효하지 않음
    if is_metrics.sharpe_ratio <= 0:
        notes.append(f"IS Sharpe 비정상: {is_metrics.sharpe_ratio:.3f}")
        return False, 0.0, notes

    efficiency_ratio = oos_metrics.sharpe_ratio / is_metrics.sharpe_ratio

    if efficiency_ratio < config.efficiency_threshold:
        notes.append(
            f"효율 비율 부족: {efficiency_ratio:.2f} "
            f"(최소 {config.efficiency_threshold})"
        )
        return False, efficiency_ratio, notes

    # 경고: OOS MDD가 -30% 초과
    if oos_metrics.max_drawdown < -0.30:
        notes.append(f"OOS MDD 경고: {oos_metrics.max_drawdown:.1%}")

    if not notes:
        notes.append("검증 통과")

    return True, efficiency_ratio, notes
