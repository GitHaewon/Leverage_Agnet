"""
Prometheus 메트릭 익스포터.

prometheus_client 패키지가 필요하다.
설치되어 있지 않으면 PrometheusExporter 생성 시 ImportError 발생.
"""
from __future__ import annotations

from agents.monitoring.models import MetricsSnapshot

# prometheus_client는 인스턴스 생성 시점에 임포트 — 선택적 의존성
try:
    from prometheus_client import Gauge as _Gauge

    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PROMETHEUS_AVAILABLE = False


METRIC_NAMES = {
    "order_success_rate": "trading_order_success_rate",
    "win_rate": "trading_win_rate",
    "max_drawdown": "trading_drawdown_ratio",
    "daily_pnl": "trading_daily_pnl_usdt",
    "open_positions_count": "trading_open_positions_count",
}

METRIC_DESCRIPTIONS = {
    "order_success_rate": "Ratio of filled orders to total submitted orders (0–1)",
    "win_rate": "Ratio of profitable closed trades to total closed trades (0–1)",
    "max_drawdown": "Maximum peak-to-trough drawdown ratio (0–1)",
    "daily_pnl": "Today realized PnL + all open positions unrealized PnL (USDT)",
    "open_positions_count": "Number of currently open positions",
}


class PrometheusExporter:
    """
    MetricsSnapshot → Prometheus Gauge 업데이트.

    Gauge 레지스트리는 생성자에서 한 번만 초기화한다.
    update()를 주기적으로 호출해 최신 값으로 갱신한다.
    """

    def __init__(self, registry=None) -> None:
        if not _PROMETHEUS_AVAILABLE:
            raise ImportError(
                "prometheus_client 패키지가 설치되어 있지 않습니다. "
                "pip install prometheus_client"
            )
        kwargs = {"registry": registry} if registry is not None else {}

        self._gauges: dict[str, _Gauge] = {
            key: _Gauge(METRIC_NAMES[key], METRIC_DESCRIPTIONS[key], **kwargs)
            for key in METRIC_NAMES
        }

    def update(self, snapshot: MetricsSnapshot) -> None:
        """MetricsSnapshot의 값으로 모든 Gauge를 갱신한다."""
        self._gauges["order_success_rate"].set(float(snapshot.order_success_rate))
        self._gauges["win_rate"].set(float(snapshot.win_rate))
        self._gauges["max_drawdown"].set(float(snapshot.max_drawdown))
        self._gauges["daily_pnl"].set(float(snapshot.daily_pnl))
        self._gauges["open_positions_count"].set(float(snapshot.open_positions_count))

    def gauge_value(self, key: str) -> float:
        """테스트 및 헬스체크용 — 현재 Gauge 값 반환."""
        return self._gauges[key]._value.get()
