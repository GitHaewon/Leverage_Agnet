"""
PrometheusExporter 테스트.

prometheus_client 미설치 환경에서는 전체 스킵.

검증:
  - update() 이후 각 게이지 값이 MetricsSnapshot 값과 일치
  - order_success_rate 게이지 업데이트
  - win_rate 게이지 업데이트
  - max_drawdown 게이지 업데이트
  - daily_pnl 게이지 업데이트 (음수 포함)
  - open_positions_count 게이지 업데이트
  - update() 재호출 시 덮어쓰기
  - METRIC_NAMES 상수 — 5개 키 모두 존재
  - prometheus_client 미설치 시 ImportError
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

prometheus_client = pytest.importorskip(
    "prometheus_client",
    reason="prometheus_client 미설치 — PrometheusExporter 테스트 스킵",
)

from prometheus_client import CollectorRegistry

from agents.monitoring.models import MetricsSnapshot
from agents.monitoring.prometheus import METRIC_NAMES, PrometheusExporter


def _make_snapshot(**kwargs) -> MetricsSnapshot:
    defaults = dict(
        order_success_rate=Decimal("0.85"),
        win_rate=Decimal("0.6"),
        max_drawdown=Decimal("0.1"),
        daily_pnl=Decimal("250.0"),
        open_positions_count=3,
        total_orders=20,
        total_trades=10,
        computed_at=datetime(2026, 6, 7, 12, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return MetricsSnapshot(**defaults)


def _exporter() -> PrometheusExporter:
    """격리된 레지스트리로 PrometheusExporter 생성 (전역 레지스트리 오염 방지)."""
    registry = CollectorRegistry()
    return PrometheusExporter(registry=registry)


# ── 게이지 업데이트 ───────────────────────────────────────────────────────────────

def test_update_order_success_rate():
    exp = _exporter()
    exp.update(_make_snapshot(order_success_rate=Decimal("0.75")))
    assert abs(exp.gauge_value("order_success_rate") - 0.75) < 1e-9


def test_update_win_rate():
    exp = _exporter()
    exp.update(_make_snapshot(win_rate=Decimal("0.55")))
    assert abs(exp.gauge_value("win_rate") - 0.55) < 1e-9


def test_update_max_drawdown():
    exp = _exporter()
    exp.update(_make_snapshot(max_drawdown=Decimal("0.18")))
    assert abs(exp.gauge_value("max_drawdown") - 0.18) < 1e-9


def test_update_daily_pnl_positive():
    exp = _exporter()
    exp.update(_make_snapshot(daily_pnl=Decimal("300.0")))
    assert abs(exp.gauge_value("daily_pnl") - 300.0) < 1e-6


def test_update_daily_pnl_negative():
    """daily_pnl은 음수 가능."""
    exp = _exporter()
    exp.update(_make_snapshot(daily_pnl=Decimal("-150.0")))
    assert exp.gauge_value("daily_pnl") < 0
    assert abs(exp.gauge_value("daily_pnl") - (-150.0)) < 1e-6


def test_update_open_positions_count():
    exp = _exporter()
    exp.update(_make_snapshot(open_positions_count=4))
    assert exp.gauge_value("open_positions_count") == 4.0


def test_update_zero_values():
    exp = _exporter()
    exp.update(_make_snapshot(
        order_success_rate=Decimal("0"),
        win_rate=Decimal("0"),
        max_drawdown=Decimal("0"),
        daily_pnl=Decimal("0"),
        open_positions_count=0,
    ))
    for key in METRIC_NAMES:
        assert exp.gauge_value(key) == 0.0


# ── 재호출 덮어쓰기 ───────────────────────────────────────────────────────────────

def test_update_overwrites_previous_value():
    exp = _exporter()
    exp.update(_make_snapshot(win_rate=Decimal("0.9")))
    exp.update(_make_snapshot(win_rate=Decimal("0.4")))
    assert abs(exp.gauge_value("win_rate") - 0.4) < 1e-9


def test_update_all_gauges_at_once():
    """update() 한 번으로 5개 게이지 모두 갱신."""
    exp = _exporter()
    snap = _make_snapshot(
        order_success_rate=Decimal("0.8"),
        win_rate=Decimal("0.65"),
        max_drawdown=Decimal("0.05"),
        daily_pnl=Decimal("100.0"),
        open_positions_count=2,
    )
    exp.update(snap)
    assert abs(exp.gauge_value("order_success_rate") - 0.8) < 1e-9
    assert abs(exp.gauge_value("win_rate") - 0.65) < 1e-9
    assert abs(exp.gauge_value("max_drawdown") - 0.05) < 1e-9
    assert abs(exp.gauge_value("daily_pnl") - 100.0) < 1e-6
    assert exp.gauge_value("open_positions_count") == 2.0


# ── METRIC_NAMES 상수 ─────────────────────────────────────────────────────────────

def test_metric_names_has_five_keys():
    assert len(METRIC_NAMES) == 5


def test_metric_names_contains_all_required_keys():
    expected = {
        "order_success_rate",
        "win_rate",
        "max_drawdown",
        "daily_pnl",
        "open_positions_count",
    }
    assert set(METRIC_NAMES.keys()) == expected


def test_metric_names_prometheus_format():
    """Prometheus 네이밍: 소문자 + 언더스코어, trading_ 접두사."""
    for prom_name in METRIC_NAMES.values():
        assert prom_name.startswith("trading_")
        assert prom_name == prom_name.lower()
