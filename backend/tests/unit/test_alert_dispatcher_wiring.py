"""
analysis_worker._build_deps() AlertDispatcher 주입 검증.

검증 항목:
  1. TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID 모두 있으면 AlertDispatcher 주입
  2. TELEGRAM_BOT_TOKEN 없으면 alert_dispatcher=None
  3. TELEGRAM_CHAT_ID 없으면 alert_dispatcher=None
  4. AlertDispatcher는 TelegramSender로 초기화된다 (올바른 인자)
  5. 기존 shadow / paper / live 경로의 alert_dispatcher는 항상 생성된다 (설정 있을 때)
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

# celery + config 사전 모킹
_celery_stub = MagicMock()
_celery_stub.Task = object  # type: ignore[assignment]
sys.modules.setdefault("celery", _celery_stub)
sys.modules.setdefault("celery.app", MagicMock())
sys.modules.setdefault("app.workers.celery_app", MagicMock())
if "app.core.config" not in sys.modules:
    sys.modules["app.core.config"] = MagicMock()

import app.workers.analysis_worker as worker_module  # noqa: E402
from app.workers.analysis_worker import _build_deps  # noqa: E402


def _module_mocks() -> dict:
    return {
        "agents.orchestrator.pipeline": MagicMock(),
        "agents.market_data.agent": MagicMock(),
        "agents.technical_analysis.agent": MagicMock(),
        "agents.strategy.engine": MagicMock(),
        "agents.analyst.agent": MagicMock(),
        "agents.risk.engine": MagicMock(),
        "agents.portfolio.engine": MagicMock(),
        "agents.position_manager.engine": MagicMock(),
        "agents.execution.engine": MagicMock(),
        "agents.execution.gateway": MagicMock(),
        "agents.alert.dispatcher": MagicMock(),
        "agents.alert.sender": MagicMock(),
    }


def _mock_settings(*, bot_token: str, chat_id: str) -> MagicMock:
    s = MagicMock()
    s.SHADOW_TRADING_ENABLED = False
    s.LIVE_TRADING_ENABLED = False
    s.OPENAI_API_KEY = "test-key"
    s.OPENAI_MODEL = "gpt-5"
    s.TELEGRAM_BOT_TOKEN = bot_token
    s.TELEGRAM_CHAT_ID = chat_id
    return s


class TestAlertDispatcherWiring:

    @pytest.mark.asyncio
    async def test_dispatcher_injected_when_both_configured(self, monkeypatch):
        """bot_token + chat_id 모두 있으면 AlertDispatcher가 주입된다."""
        mocks = _module_mocks()
        mock_dispatcher_cls = MagicMock(name="AlertDispatcher")
        mock_sender_cls = MagicMock(name="TelegramSender")
        mocks["agents.alert.dispatcher"].AlertDispatcher = mock_dispatcher_cls
        mocks["agents.alert.sender"].TelegramSender = mock_sender_cls

        mock_deps_cls = MagicMock(name="OrchestratorDeps")
        mocks["agents.orchestrator.pipeline"].OrchestratorDeps = mock_deps_cls

        monkeypatch.setattr(
            worker_module, "settings",
            _mock_settings(bot_token="tok123", chat_id="chat456"),
        )

        with patch.dict("sys.modules", mocks):
            await _build_deps(MagicMock())

        mock_dispatcher_cls.assert_called_once()
        # OrchestratorDeps의 alert_dispatcher 인자 확인
        _, kwargs = mock_deps_cls.call_args
        assert kwargs.get("alert_dispatcher") is mock_dispatcher_cls.return_value

    @pytest.mark.asyncio
    async def test_dispatcher_none_when_no_bot_token(self, monkeypatch):
        """bot_token이 빈 문자열이면 alert_dispatcher=None."""
        mocks = _module_mocks()
        mock_dispatcher_cls = MagicMock(name="AlertDispatcher")
        mocks["agents.alert.dispatcher"].AlertDispatcher = mock_dispatcher_cls

        mock_deps_cls = MagicMock(name="OrchestratorDeps")
        mocks["agents.orchestrator.pipeline"].OrchestratorDeps = mock_deps_cls

        monkeypatch.setattr(
            worker_module, "settings",
            _mock_settings(bot_token="", chat_id="chat456"),
        )

        with patch.dict("sys.modules", mocks):
            await _build_deps(MagicMock())

        mock_dispatcher_cls.assert_not_called()
        _, kwargs = mock_deps_cls.call_args
        assert kwargs.get("alert_dispatcher") is None

    @pytest.mark.asyncio
    async def test_dispatcher_none_when_no_chat_id(self, monkeypatch):
        """chat_id가 빈 문자열이면 alert_dispatcher=None."""
        mocks = _module_mocks()
        mock_dispatcher_cls = MagicMock(name="AlertDispatcher")
        mocks["agents.alert.dispatcher"].AlertDispatcher = mock_dispatcher_cls

        mock_deps_cls = MagicMock(name="OrchestratorDeps")
        mocks["agents.orchestrator.pipeline"].OrchestratorDeps = mock_deps_cls

        monkeypatch.setattr(
            worker_module, "settings",
            _mock_settings(bot_token="tok123", chat_id=""),
        )

        with patch.dict("sys.modules", mocks):
            await _build_deps(MagicMock())

        mock_dispatcher_cls.assert_not_called()
        _, kwargs = mock_deps_cls.call_args
        assert kwargs.get("alert_dispatcher") is None

    @pytest.mark.asyncio
    async def test_telegram_sender_receives_bot_token(self, monkeypatch):
        """TelegramSender는 TELEGRAM_BOT_TOKEN으로 초기화된다."""
        mocks = _module_mocks()
        mock_sender_cls = MagicMock(name="TelegramSender")
        mocks["agents.alert.sender"].TelegramSender = mock_sender_cls

        monkeypatch.setattr(
            worker_module, "settings",
            _mock_settings(bot_token="real-bot-token", chat_id="12345"),
        )

        with patch.dict("sys.modules", mocks):
            await _build_deps(MagicMock())

        mock_sender_cls.assert_called_once_with(bot_token="real-bot-token")

    @pytest.mark.asyncio
    async def test_alert_dispatcher_receives_chat_id(self, monkeypatch):
        """AlertDispatcher는 TELEGRAM_CHAT_ID로 초기화된다."""
        mocks = _module_mocks()
        mock_dispatcher_cls = MagicMock(name="AlertDispatcher")
        mocks["agents.alert.dispatcher"].AlertDispatcher = mock_dispatcher_cls

        monkeypatch.setattr(
            worker_module, "settings",
            _mock_settings(bot_token="tok", chat_id="my-chat-99"),
        )

        with patch.dict("sys.modules", mocks):
            await _build_deps(MagicMock())

        _, kwargs = mock_dispatcher_cls.call_args
        assert kwargs.get("chat_id") == "my-chat-99"

    @pytest.mark.asyncio
    async def test_shadow_mode_also_injects_dispatcher(self, monkeypatch):
        """Shadow 모드에서도 AlertDispatcher가 주입된다."""
        mocks = _module_mocks()
        mocks["agents.shadow.execution"] = MagicMock()
        mocks["app.repositories.shadow_trade_repository"] = MagicMock()

        mock_dispatcher_cls = MagicMock(name="AlertDispatcher")
        mocks["agents.alert.dispatcher"].AlertDispatcher = mock_dispatcher_cls

        mock_deps_cls = MagicMock(name="OrchestratorDeps")
        mocks["agents.orchestrator.pipeline"].OrchestratorDeps = mock_deps_cls

        s = _mock_settings(bot_token="tok", chat_id="chat")
        s.SHADOW_TRADING_ENABLED = True
        monkeypatch.setattr(worker_module, "settings", s)

        with patch.dict("sys.modules", mocks):
            await _build_deps(MagicMock(), session=MagicMock())

        mock_dispatcher_cls.assert_called_once()
        _, kwargs = mock_deps_cls.call_args
        assert kwargs.get("alert_dispatcher") is not None
