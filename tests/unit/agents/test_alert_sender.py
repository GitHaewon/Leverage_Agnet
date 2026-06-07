"""
TelegramSender 테스트.

검증:
  - 올바른 Telegram API URL로 POST (토큰 포함)
  - payload에 chat_id 포함
  - payload에 text 포함
  - HTTP 4xx 오류 시 HTTPStatusError 발생
  - HTTP 5xx 오류 시 HTTPStatusError 발생
  - bot_token 빈 문자열 → ValueError
  - timeout 설정이 AsyncClient에 전달됨
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.alert.sender import TelegramSender


def _run(coro):
    return asyncio.run(coro)


def _mock_client(status_code: int = 200):
    """httpx.AsyncClient를 흉내 내는 Mock 반환."""
    mock_response = MagicMock()
    if status_code >= 400:
        import httpx
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=MagicMock(status_code=status_code),
        )
    else:
        mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ── URL 검증 ─────────────────────────────────────────────────────────────────────

def test_sender_posts_to_telegram_api_url():
    """URL에 api.telegram.org 포함."""
    sender = TelegramSender(bot_token="mytoken123")
    mock_client = _mock_client()

    with patch("agents.alert.sender.httpx.AsyncClient", return_value=mock_client):
        _run(sender.send("chat-1", "hello"))

    url = mock_client.post.call_args[0][0]
    assert "api.telegram.org" in url


def test_sender_url_contains_bot_token():
    """URL에 bot 토큰이 포함된다."""
    sender = TelegramSender(bot_token="SECRET-TOKEN-XYZ")
    mock_client = _mock_client()

    with patch("agents.alert.sender.httpx.AsyncClient", return_value=mock_client):
        _run(sender.send("chat-1", "hello"))

    url = mock_client.post.call_args[0][0]
    assert "SECRET-TOKEN-XYZ" in url


def test_sender_url_uses_sendmessage_endpoint():
    sender = TelegramSender(bot_token="tok")
    mock_client = _mock_client()

    with patch("agents.alert.sender.httpx.AsyncClient", return_value=mock_client):
        _run(sender.send("chat-1", "hello"))

    url = mock_client.post.call_args[0][0]
    assert "sendMessage" in url


# ── payload 검증 ──────────────────────────────────────────────────────────────────

def test_sender_payload_contains_chat_id():
    sender = TelegramSender(bot_token="tok")
    mock_client = _mock_client()

    with patch("agents.alert.sender.httpx.AsyncClient", return_value=mock_client):
        _run(sender.send("chat-999", "hello"))

    payload = mock_client.post.call_args[1]["json"]
    assert payload["chat_id"] == "chat-999"


def test_sender_payload_contains_text():
    sender = TelegramSender(bot_token="tok")
    mock_client = _mock_client()

    with patch("agents.alert.sender.httpx.AsyncClient", return_value=mock_client):
        _run(sender.send("chat-1", "주문 체결 알림"))

    payload = mock_client.post.call_args[1]["json"]
    assert payload["text"] == "주문 체결 알림"


# ── 오류 처리 ─────────────────────────────────────────────────────────────────────

def test_sender_raises_on_4xx():
    import httpx
    sender = TelegramSender(bot_token="tok")
    mock_client = _mock_client(status_code=400)

    with patch("agents.alert.sender.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.HTTPStatusError):
            _run(sender.send("chat-1", "hello"))


def test_sender_raises_on_5xx():
    import httpx
    sender = TelegramSender(bot_token="tok")
    mock_client = _mock_client(status_code=500)

    with patch("agents.alert.sender.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.HTTPStatusError):
            _run(sender.send("chat-1", "hello"))


# ── 생성자 검증 ───────────────────────────────────────────────────────────────────

def test_empty_bot_token_raises_value_error():
    with pytest.raises(ValueError):
        TelegramSender(bot_token="")


def test_sender_passes_timeout_to_client():
    """timeout 값이 AsyncClient 생성자에 전달된다."""
    sender = TelegramSender(bot_token="tok", timeout=30.0)
    mock_client = _mock_client()

    with patch("agents.alert.sender.httpx.AsyncClient", return_value=mock_client) as mock_cls:
        _run(sender.send("chat-1", "hello"))

    _, kwargs = mock_cls.call_args
    assert kwargs.get("timeout") == 30.0
