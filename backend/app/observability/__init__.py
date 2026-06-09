"""
Production Observability — Prometheus 메트릭 수집.

사용법:
  from app.observability import metrics
  metrics.record_order("BTCUSDT", "BUY", "filled", latency)
"""
from app.observability import metrics  # noqa: F401

__all__ = ["metrics"]
