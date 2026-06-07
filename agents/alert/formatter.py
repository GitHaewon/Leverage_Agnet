"""
Alert 메시지 포맷터.

순수 함수 — I/O 없음. 이벤트 → Telegram 텍스트 메시지.
"""
from __future__ import annotations

from agents.alert.models import (
    AlertEvent,
    KillSwitchEvent,
    LiquidationRiskEvent,
    MaxDailyLossEvent,
    OrderFailedEvent,
    OrderFilledEvent,
)

_SEP = "─" * 16

_DIRECTION_SYMBOL = {"LONG": "▲", "SHORT": "▼"}


def _fmt_price(price) -> str:
    return f"${float(price):,.2f}"


def _fmt_qty(qty) -> str:
    return f"{float(qty):.5f}".rstrip("0").rstrip(".")


def _fmt_pct(ratio) -> str:
    return f"{float(ratio) * 100:.1f}%"


def _fmt_dt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def format_order_filled(event: OrderFilledEvent) -> str:
    direction_sym = _DIRECTION_SYMBOL[event.direction]
    lines = [
        "📊 [주문 체결]",
        _SEP,
        f"심볼: {event.symbol} {direction_sym} {event.direction}",
        f"체결가: {_fmt_price(event.fill_price)}",
        f"수량: {_fmt_qty(event.quantity)}",
        f"레버리지: {event.leverage}x",
    ]
    if event.take_profit is not None:
        lines.append(f"TP: {_fmt_price(event.take_profit)}")
    if event.stop_loss is not None:
        lines.append(f"SL: {_fmt_price(event.stop_loss)}")
    return "\n".join(lines)


def format_order_failed(event: OrderFailedEvent) -> str:
    direction_sym = _DIRECTION_SYMBOL[event.direction]
    return "\n".join([
        "❌ [주문 실패]",
        _SEP,
        f"심볼: {event.symbol} {direction_sym} {event.direction}",
        f"거부 코드: {event.rejection_code}",
        f"사유: {event.reason}",
    ])


def format_max_daily_loss(event: MaxDailyLossEvent) -> str:
    return "\n".join([
        "🚨 [일일 손실 한도 도달]",
        _SEP,
        f"손실: {_fmt_price(event.daily_loss_usdt)}",
        f"한도: {_fmt_price(event.limit_usdt)}",
        "자동매매가 즉시 중단되었습니다.",
        f"발동 시각: {_fmt_dt(event.triggered_at)}",
    ])


def format_kill_switch(event: KillSwitchEvent) -> str:
    return "\n".join([
        "⛔ [Kill Switch 발동]",
        _SEP,
        f"사유: {event.reason}",
        f"발동 시각: {_fmt_dt(event.triggered_at)}",
        "모든 자동매매가 즉시 중단되었습니다.",
    ])


def format_liquidation_risk(event: LiquidationRiskEvent) -> str:
    direction_sym = _DIRECTION_SYMBOL[event.direction]
    return "\n".join([
        "⚠️ [청산 위험]",
        _SEP,
        f"심볼: {event.symbol} {direction_sym} {event.direction}",
        f"진입가: {_fmt_price(event.entry_price)}",
        f"현재가: {_fmt_price(event.current_price)}",
        f"청산가: {_fmt_price(event.liq_price)}",
        f"마진 비율: {_fmt_pct(event.margin_ratio)}",
    ])


def format_alert(event: AlertEvent) -> str:
    """이벤트 타입에 따라 올바른 포맷터로 라우팅."""
    if isinstance(event, OrderFilledEvent):
        return format_order_filled(event)
    if isinstance(event, OrderFailedEvent):
        return format_order_failed(event)
    if isinstance(event, MaxDailyLossEvent):
        return format_max_daily_loss(event)
    if isinstance(event, KillSwitchEvent):
        return format_kill_switch(event)
    if isinstance(event, LiquidationRiskEvent):
        return format_liquidation_risk(event)
    raise ValueError(f"알 수 없는 이벤트 타입: {type(event)}")
