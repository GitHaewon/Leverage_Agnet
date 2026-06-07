"""
Alert 발송 레이어.

SenderProtocol: 덕 타이핑 인터페이스 — 테스트에서는 CaptureSender로 교체.
TelegramSender: httpx로 Telegram Bot API를 직접 호출.
"""
from __future__ import annotations

from typing import Protocol

import httpx


class SenderProtocol(Protocol):
    async def send(self, chat_id: str, text: str) -> None: ...


class TelegramSender:
    """
    Telegram Bot API를 통해 메시지를 발송한다.

    bot_token: @BotFather로 발급받은 토큰 (환경변수 TELEGRAM_BOT_TOKEN)
    """

    _API_BASE = "https://api.telegram.org"

    def __init__(self, bot_token: str, timeout: float = 10.0) -> None:
        if not bot_token:
            raise ValueError("bot_token은 비어 있을 수 없습니다.")
        self._token = bot_token
        self._timeout = timeout

    async def send(self, chat_id: str, text: str) -> None:
        """메시지를 Telegram으로 발송. HTTP 오류 시 httpx.HTTPStatusError 발생."""
        url = f"{self._API_BASE}/bot{self._token}/sendMessage"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                url,
                json={"chat_id": chat_id, "text": text},
            )
            resp.raise_for_status()
