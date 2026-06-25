"""
analysis_worker._build_deps() 실행 엔진 주입 검증.

SHADOW_TRADING_ENABLED 플래그에 따라 올바른 ExecutionEngine 구현체가 주입된다.

검증 항목:
  1. SHADOW=true, LIVE=false  → ShadowExecutionEngine 주입
  2. ShadowTradeRepository는 전달된 session으로 초기화된다
  3. SHADOW=false, LIVE=false → ExecutionEngine(paper) 주입
  4. LIVE=true + user_id      → ExecutionEngine(live), SHADOW 플래그 무관
  5. LIVE=true, user_id=None  → shadow 분기로 fallthrough

임포트 순서 주의:
  - analysis_worker는 모듈 레벨에서 `from celery import Task` 및
    `from app.core.config import settings`를 실행한다.
  - 테스트 환경에 celery가 없고, backend/.env 파싱이 실패할 수 있으므로
    두 모듈을 sys.modules에 먼저 등록한 뒤 analysis_worker를 임포트한다.
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

# ── 사전 mock 등록 (analysis_worker 임포트 전에 완료되어야 함) ──────────────

# celery: 테스트 환경에 설치되지 않음
_celery_stub = MagicMock()
_celery_stub.Task = object  # type: ignore[assignment]
sys.modules.setdefault("celery", _celery_stub)
sys.modules.setdefault("celery.app", MagicMock())
sys.modules.setdefault("celery.utils", MagicMock())
sys.modules.setdefault("app.workers.celery_app", MagicMock())

# app.core.config: Settings() 생성 시 backend/.env 파싱 실패 방지
_config_stub = MagicMock()
if "app.core.config" not in sys.modules:
    sys.modules["app.core.config"] = _config_stub

# ── analysis_worker 임포트 (celery + config mock 이후) ───────────────────────

import app.workers.analysis_worker as worker_module  # noqa: E402
from app.workers.analysis_worker import _build_deps  # noqa: E402


# ── 픽스처 헬퍼 ─────────────────────────────────────────────────────────────

def _module_mocks() -> dict:
    """_build_deps() 내부 import 경로를 MagicMock으로 대체한다."""
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
        "agents.shadow.execution": MagicMock(),
        "app.repositories.shadow_trade_repository": MagicMock(),
        "app.gateways.binance_gateway": MagicMock(),
        "app.safety": MagicMock(),
        "app.safety.adapter": MagicMock(),
    }


def _mock_settings(*, shadow: bool, live: bool, **extra) -> MagicMock:
    s = MagicMock()
    s.SHADOW_TRADING_ENABLED = shadow
    s.LIVE_TRADING_ENABLED = live
    s.SHADOW_MIN_LONG_SCORE = None
    s.SHADOW_MIN_SHORT_SCORE = None
    s.SHADOW_MAX_RISK_SCORE = None
    s.SHADOW_AI_REVIEW_REQUIRED = True
    s.OPENAI_API_KEY = "test-key"
    s.OPENAI_MODEL = "gpt-5"
    s.BINANCE_TESTNET = True
    for k, v in extra.items():
        setattr(s, k, v)
    return s


# ── 테스트 ───────────────────────────────────────────────────────────────────

class TestBuildDepsExecutionMode:
    """_build_deps() 실행 엔진 분기 검증."""

    @pytest.mark.asyncio
    async def test_shadow_mode_injects_shadow_engine(self, monkeypatch):
        """SHADOW=true, LIVE=false → ShadowExecutionEngine 주입, ExecutionEngine 미사용."""
        mocks = _module_mocks()
        mock_shadow_cls = MagicMock(name="ShadowExecutionEngine")
        mock_exec_cls = MagicMock(name="ExecutionEngine")
        mocks["agents.shadow.execution"].ShadowExecutionEngine = mock_shadow_cls
        mocks["agents.execution.engine"].ExecutionEngine = mock_exec_cls

        monkeypatch.setattr(worker_module, "settings", _mock_settings(shadow=True, live=False))

        with patch.dict("sys.modules", mocks):
            await _build_deps(MagicMock(), session=MagicMock())

        mock_shadow_cls.assert_called_once()
        mock_exec_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_shadow_repository_receives_session(self, monkeypatch):
        """ShadowTradeRepository는 _build_deps()에 전달된 session으로 초기화된다."""
        mocks = _module_mocks()
        mock_repo_cls = MagicMock(name="ShadowTradeRepository")
        mocks["app.repositories.shadow_trade_repository"].ShadowTradeRepository = mock_repo_cls

        monkeypatch.setattr(worker_module, "settings", _mock_settings(shadow=True, live=False))

        mock_session = MagicMock(name="async_session")
        with patch.dict("sys.modules", mocks):
            await _build_deps(MagicMock(), session=mock_session)

        mock_repo_cls.assert_called_once_with(mock_session)

    @pytest.mark.asyncio
    async def test_paper_mode_injects_execution_engine(self, monkeypatch):
        """SHADOW=false, LIVE=false → ExecutionEngine(paper) 주입, ShadowEngine 미사용."""
        mocks = _module_mocks()
        mock_shadow_cls = MagicMock(name="ShadowExecutionEngine")
        mock_exec_cls = MagicMock(name="ExecutionEngine")
        mocks["agents.shadow.execution"].ShadowExecutionEngine = mock_shadow_cls
        mocks["agents.execution.engine"].ExecutionEngine = mock_exec_cls

        monkeypatch.setattr(worker_module, "settings", _mock_settings(shadow=False, live=False))

        with patch.dict("sys.modules", mocks):
            await _build_deps(MagicMock())

        mock_exec_cls.assert_called_once()
        mock_shadow_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_live_mode_overrides_shadow(self, monkeypatch):
        """LIVE=true + user_id → ExecutionEngine(live), SHADOW 플래그와 무관하게 우선."""
        mocks = _module_mocks()
        mock_shadow_cls = MagicMock(name="ShadowExecutionEngine")
        mock_exec_cls = MagicMock(name="ExecutionEngine")
        mocks["agents.shadow.execution"].ShadowExecutionEngine = mock_shadow_cls
        mocks["agents.execution.engine"].ExecutionEngine = mock_exec_cls

        monkeypatch.setattr(worker_module, "settings", _mock_settings(shadow=True, live=True))

        with patch.dict("sys.modules", mocks):
            await _build_deps(MagicMock(), user_id=uuid.uuid4())

        mock_exec_cls.assert_called_once()
        mock_shadow_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_live_mode_without_user_id_falls_through_to_shadow(self, monkeypatch):
        """LIVE=true이지만 user_id=None → shadow 분기 진입, BinanceGateway 미사용."""
        mocks = _module_mocks()
        mock_shadow_cls = MagicMock(name="ShadowExecutionEngine")
        mock_exec_cls = MagicMock(name="ExecutionEngine")
        mock_binance_cls = MagicMock(name="BinanceGateway")
        mocks["agents.shadow.execution"].ShadowExecutionEngine = mock_shadow_cls
        mocks["agents.execution.engine"].ExecutionEngine = mock_exec_cls
        mocks["app.gateways.binance_gateway"].BinanceGateway = mock_binance_cls

        monkeypatch.setattr(worker_module, "settings", _mock_settings(shadow=True, live=True))

        with patch.dict("sys.modules", mocks):
            # user_id=None → LIVE 조건(user_id is not None) 불충족 → shadow 분기
            await _build_deps(MagicMock(), session=MagicMock())

        mock_binance_cls.assert_not_called()
        mock_shadow_cls.assert_called_once()


class TestShadowDecisionConfig:
    def test_shadow_mode_builds_relaxed_decision_config(self, monkeypatch):
        monkeypatch.setattr(
            worker_module,
            "settings",
            _mock_settings(
                shadow=True,
                live=False,
                SHADOW_MIN_LONG_SCORE=60,
                SHADOW_MIN_SHORT_SCORE=60,
                SHADOW_MAX_RISK_SCORE=45,
                SHADOW_AI_REVIEW_REQUIRED=False,
            ),
        )

        cfg = worker_module._shadow_decision_config()
        assert cfg == {
            "profile": "shadow",
            "ai_review_required": False,
            "min_long_score": 60.0,
            "min_short_score": 60.0,
            "max_risk_score": 45.0,
            "max_risk_trend": 45.0,
            "max_risk_breakout": 45.0,
            "max_risk_intraday": 45.0,
            "max_risk_scalping": 45.0,
        }

    def test_live_mode_never_gets_shadow_decision_config(self, monkeypatch):
        monkeypatch.setattr(
            worker_module,
            "settings",
            _mock_settings(
                shadow=True,
                live=True,
                SHADOW_MIN_LONG_SCORE=60,
                SHADOW_MAX_RISK_SCORE=45,
            ),
        )

        assert worker_module._shadow_decision_config() is None

    def test_paper_mode_without_shadow_gets_no_shadow_decision_config(self, monkeypatch):
        monkeypatch.setattr(
            worker_module,
            "settings",
            _mock_settings(shadow=False, live=False, SHADOW_MIN_LONG_SCORE=60),
        )

        assert worker_module._shadow_decision_config() is None
