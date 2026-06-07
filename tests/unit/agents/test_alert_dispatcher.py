"""
AlertDispatcher 테스트.

검증:
  [성공 케이스 — CaptureSender]
  - dispatch() → AlertResult(success=True)
  - event_type이 결과에 보존됨
  - chat_id가 결과에 보존됨
  - error는 None
  - Sender에 chat_id 전달됨
  - Sender에 텍스트 전달됨 (포맷된 메시지)
  - 각 이벤트 타입마다 Sender 1회 호출

  [실패 케이스 — FailingSender]
  - Sender 예외 → AlertResult(success=False)
  - error 메시지 포함
  - 예외가 호출자로 전파되지 않음

  [독립성]
  - 여러 이벤트 연속 dispatch → 각각 독립 결과
  - Sender 호출 횟수 정확
"""
from __future__ import annotations

import asyncio

from agents.alert.dispatcher import AlertDispatcher

from tests.unit.agents._alert_fixtures import (
    CaptureSender,
    FailingSender,
    make_kill_switch,
    make_liquidation_risk,
    make_max_daily_loss,
    make_order_failed,
    make_order_filled,
)


def _run(coro):
    return asyncio.run(coro)


def _dispatcher(sender=None, chat_id="chat-123"):
    return AlertDispatcher(sender=sender or CaptureSender(), chat_id=chat_id)


# ── 성공 케이스 ───────────────────────────────────────────────────────────────────

def test_dispatch_order_filled_success():
    result = _run(_dispatcher().dispatch(make_order_filled()))
    assert result.success is True


def test_dispatch_order_failed_success():
    result = _run(_dispatcher().dispatch(make_order_failed()))
    assert result.success is True


def test_dispatch_max_daily_loss_success():
    result = _run(_dispatcher().dispatch(make_max_daily_loss()))
    assert result.success is True


def test_dispatch_kill_switch_success():
    result = _run(_dispatcher().dispatch(make_kill_switch()))
    assert result.success is True


def test_dispatch_liquidation_risk_success():
    result = _run(_dispatcher().dispatch(make_liquidation_risk()))
    assert result.success is True


def test_dispatch_result_event_type_preserved():
    result = _run(_dispatcher().dispatch(make_order_filled()))
    assert result.event_type == "order_filled"


def test_dispatch_result_chat_id_preserved():
    result = _run(_dispatcher(chat_id="777").dispatch(make_order_filled()))
    assert result.chat_id == "777"


def test_dispatch_success_error_is_none():
    result = _run(_dispatcher().dispatch(make_order_filled()))
    assert result.error is None


def test_dispatch_sends_to_correct_chat_id():
    sender = CaptureSender()
    _run(_dispatcher(sender=sender, chat_id="chat-999").dispatch(make_order_filled()))
    assert sender.last_call["chat_id"] == "chat-999"


def test_dispatch_sends_formatted_text():
    sender = CaptureSender()
    _run(_dispatcher(sender=sender).dispatch(make_order_filled()))
    assert "주문 체결" in sender.last_call["text"]


def test_dispatch_kill_switch_sends_correct_text():
    sender = CaptureSender()
    _run(_dispatcher(sender=sender).dispatch(make_kill_switch(reason="테스트 발동")))
    assert "테스트 발동" in sender.last_call["text"]


def test_dispatch_sender_called_once_per_event():
    sender = CaptureSender()
    dispatcher = _dispatcher(sender=sender)
    _run(dispatcher.dispatch(make_order_filled()))
    assert sender.call_count == 1


# ── 실패 케이스 ───────────────────────────────────────────────────────────────────

def test_dispatch_sender_failure_returns_failure_result():
    dispatcher = _dispatcher(sender=FailingSender("timeout"))
    result = _run(dispatcher.dispatch(make_order_filled()))
    assert result.success is False


def test_dispatch_sender_failure_contains_error():
    dispatcher = _dispatcher(sender=FailingSender("timeout"))
    result = _run(dispatcher.dispatch(make_order_filled()))
    assert "timeout" in result.error


def test_dispatch_sender_failure_does_not_raise():
    """Sender 예외는 호출자로 전파되지 않는다."""
    dispatcher = _dispatcher(sender=FailingSender())
    try:
        _run(dispatcher.dispatch(make_order_filled()))
    except Exception:
        assert False, "dispatch()가 예외를 전파했습니다."


def test_dispatch_failure_event_type_preserved():
    dispatcher = _dispatcher(sender=FailingSender())
    result = _run(dispatcher.dispatch(make_kill_switch()))
    assert result.event_type == "kill_switch"


def test_dispatch_failure_chat_id_preserved():
    dispatcher = _dispatcher(sender=FailingSender(), chat_id="chat-fail")
    result = _run(dispatcher.dispatch(make_order_failed()))
    assert result.chat_id == "chat-fail"


# ── 독립성 ────────────────────────────────────────────────────────────────────────

def test_multiple_dispatches_independent_results():
    sender = CaptureSender()
    dispatcher = _dispatcher(sender=sender)
    r1 = _run(dispatcher.dispatch(make_order_filled()))
    r2 = _run(dispatcher.dispatch(make_order_failed()))
    assert r1.event_type == "order_filled"
    assert r2.event_type == "order_failed"


def test_multiple_dispatches_sender_call_count():
    sender = CaptureSender()
    dispatcher = _dispatcher(sender=sender)
    for event in [
        make_order_filled(),
        make_order_failed(),
        make_max_daily_loss(),
        make_kill_switch(),
        make_liquidation_risk(),
    ]:
        _run(dispatcher.dispatch(event))
    assert sender.call_count == 5
