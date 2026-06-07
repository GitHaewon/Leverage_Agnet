"""
AlertDispatcher — 이벤트를 받아 포맷 후 Sender로 발송.

실패해도 예외를 전파하지 않는다.
AlertResult(success=False, error=...) 를 반환해 호출자가 판단하게 한다.
"""
from __future__ import annotations

from agents.alert.formatter import format_alert
from agents.alert.models import AlertEvent, AlertResult
from agents.alert.sender import SenderProtocol


class AlertDispatcher:
    """
    AlertEvent → format_alert() → SenderProtocol.send()

    chat_id: 알림을 받을 Telegram 채팅 ID (사용자별로 주입)
    """

    def __init__(self, sender: SenderProtocol, chat_id: str) -> None:
        self._sender = sender
        self._chat_id = chat_id

    async def dispatch(self, event: AlertEvent) -> AlertResult:
        try:
            text = format_alert(event)
            await self._sender.send(self._chat_id, text)
            return AlertResult(
                success=True,
                event_type=event.event_type,
                chat_id=self._chat_id,
            )
        except Exception as exc:
            return AlertResult(
                success=False,
                event_type=event.event_type,
                chat_id=self._chat_id,
                error=str(exc),
            )
