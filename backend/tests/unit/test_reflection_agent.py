"""
ReflectionAgent 단위 테스트.

외부 의존성(Claude API, DB)은 Mock 처리한다.
검증 대상:
  - 리스크 규칙 위반 감지 로직
  - 컨텍스트 텍스트 생성
  - LLM 응답 파싱 (정상 / 비정상)
  - 전체 run_reflection() 흐름
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.agents.reflection_agent import (
    MIN_RR_RATIO,
    SYSTEM_MAX_LEVERAGE,
    _build_context_text,
    _detect_risk_violations,
    _parse_llm_response,
    run_reflection,
)
from app.schemas.reflection import ReflectionInput


# ── 공통 픽스처 ───────────────────────────────────────────────────────────────

@pytest.fixture
def base_state() -> dict:
    """리스크 위반 없는 기본 거래 상태."""
    return {
        "position_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "coin": "BTC",
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "leverage": 5,
        "user_max_leverage": 10,
        "entry_price": "67450.00",
        "close_price": "69200.00",
        "stop_loss": "66800.00",
        "take_profit": "69200.00",
        "net_pnl": "131.50",
        "pnl_percentage": "13.15",
        "duration_seconds": 10800,
        "close_reason": "tp_hit",
        "signal_confidence": 0.87,
        "signal_reasons": [
            "RSI(14) = 42.3 과매도",
            "Funding Rate -0.02% 숏 과다",
        ],
        "signal_rr_ratio": 2.71,
        "signal_entry_price": "67450.00",
        "signal_tp": "69200.00",
        "signal_sl": "66800.00",
        "price_action_summary": None,
        "risk_rule_violations": [],
        "context_text": "",
        "reflection_output": None,
        "error": None,
        "tokens_input": 0,
        "tokens_output": 0,
    }


@pytest.fixture
def base_input() -> ReflectionInput:
    """ReflectionInput 기본 픽스처."""
    return ReflectionInput(
        position_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        coin="BTC",
        symbol="BTCUSDT",
        direction="LONG",
        leverage=5,
        user_max_leverage=10,
        entry_price=Decimal("67450.00"),
        close_price=Decimal("69200.00"),
        stop_loss=Decimal("66800.00"),
        take_profit=Decimal("69200.00"),
        net_pnl=Decimal("131.50"),
        pnl_percentage=Decimal("13.15"),
        duration_seconds=10800,
        close_reason="tp_hit",
        signal_confidence=0.87,
        signal_reasons=["RSI(14) = 42.3 과매도", "Funding Rate -0.02% 숏 과다"],
        signal_rr_ratio=2.71,
        signal_entry_price=Decimal("67450.00"),
        signal_tp=Decimal("69200.00"),
        signal_sl=Decimal("66800.00"),
    )


# ── 리스크 위반 감지 테스트 ────────────────────────────────────────────────────

class TestDetectRiskViolations:

    def test_no_violations_on_clean_trade(self, base_state: dict) -> None:
        violations = _detect_risk_violations(base_state)
        assert violations == []

    def test_detects_low_rr_ratio(self, base_state: dict) -> None:
        base_state["signal_rr_ratio"] = 1.5  # 2.0 미만
        violations = _detect_risk_violations(base_state)
        assert any("R:R" in v for v in violations)
        assert any("1.50" in v for v in violations)

    def test_detects_rr_exactly_at_minimum(self, base_state: dict) -> None:
        base_state["signal_rr_ratio"] = MIN_RR_RATIO  # 정확히 2.0 — 위반 아님
        violations = _detect_risk_violations(base_state)
        assert not any("R:R" in v for v in violations)

    def test_detects_leverage_over_system_max(self, base_state: dict) -> None:
        base_state["leverage"] = SYSTEM_MAX_LEVERAGE + 1  # 21x
        violations = _detect_risk_violations(base_state)
        assert any("시스템 상한" in v for v in violations)

    def test_detects_leverage_over_user_max(self, base_state: dict) -> None:
        base_state["leverage"] = 15
        base_state["user_max_leverage"] = 10
        violations = _detect_risk_violations(base_state)
        assert any("사용자 최대 설정" in v for v in violations)

    def test_no_violation_when_leverage_equals_user_max(self, base_state: dict) -> None:
        base_state["leverage"] = 10
        base_state["user_max_leverage"] = 10
        violations = _detect_risk_violations(base_state)
        assert not any("레버리지" in v for v in violations)

    def test_detects_missing_stop_loss(self, base_state: dict) -> None:
        base_state["stop_loss"] = ""
        violations = _detect_risk_violations(base_state)
        assert any("Stop Loss" in v for v in violations)

    def test_detects_low_confidence_execution(self, base_state: dict) -> None:
        base_state["signal_confidence"] = 0.55  # 0.60 미만
        violations = _detect_risk_violations(base_state)
        assert any("신뢰도" in v for v in violations)

    def test_multiple_violations_detected(self, base_state: dict) -> None:
        base_state["signal_rr_ratio"] = 1.2
        base_state["leverage"] = 25
        violations = _detect_risk_violations(base_state)
        assert len(violations) >= 2


# ── 컨텍스트 텍스트 생성 테스트 ───────────────────────────────────────────────

class TestBuildContextText:

    def test_includes_core_trade_info(self, base_state: dict) -> None:
        text = _build_context_text(base_state, [])
        assert "BTCUSDT" in text
        assert "67,450.00" in text
        assert "69,200.00" in text
        assert "10800" not in text  # 분 단위로 변환됨
        assert "180분" in text

    def test_includes_signal_reasons(self, base_state: dict) -> None:
        text = _build_context_text(base_state, [])
        assert "RSI(14) = 42.3" in text
        assert "Funding Rate" in text

    def test_includes_violations_when_present(self, base_state: dict) -> None:
        violations = ["R:R 비율 1.50 < 최소 기준 2.0"]
        text = _build_context_text(base_state, violations)
        assert "R:R 비율 1.50" in text
        assert "⚠️" in text

    def test_shows_no_violation_when_clean(self, base_state: dict) -> None:
        text = _build_context_text(base_state, [])
        assert "위반 없음" in text

    def test_tp_hit_shows_korean_label(self, base_state: dict) -> None:
        text = _build_context_text(base_state, [])
        assert "목표가 도달" in text

    def test_sl_hit_shows_korean_label(self, base_state: dict) -> None:
        base_state["close_reason"] = "sl_hit"
        text = _build_context_text(base_state, [])
        assert "손절가 도달" in text

    def test_includes_price_action_summary_when_provided(self, base_state: dict) -> None:
        base_state["price_action_summary"] = "진입 후 2% 상승 후 저항 반전"
        text = _build_context_text(base_state, [])
        assert "진입 후 2% 상승 후 저항 반전" in text

    def test_short_direction_shows_korean(self, base_state: dict) -> None:
        base_state["direction"] = "SHORT"
        text = _build_context_text(base_state, [])
        assert "숏(SHORT)" in text


# ── LLM 응답 파싱 테스트 ──────────────────────────────────────────────────────

class TestParseLlmResponse:

    def test_parses_valid_json(self) -> None:
        raw = json.dumps({
            "summary": "BTC LONG 익절 성공",
            "strengths": ["RSI 과매도 진입 정확"],
            "mistakes": ["TP 설정 소폭 보수적"],
            "improvements": ["부분 익절 전략 검토"],
            "entry_analysis": "진입 타이밍 우수",
            "pnl_cause": "기술적 과매도 반등",
            "ai_grade": "B",
        })
        result = _parse_llm_response(raw)
        assert result is not None
        assert result["summary"] == "BTC LONG 익절 성공"
        assert result["ai_grade"] == "B"

    def test_parses_json_with_markdown_code_block(self) -> None:
        raw = "```json\n" + json.dumps({
            "summary": "test",
            "strengths": [],
            "mistakes": [],
            "improvements": [],
            "entry_analysis": "ok",
            "pnl_cause": "ok",
            "ai_grade": "C",
        }) + "\n```"
        result = _parse_llm_response(raw)
        assert result is not None
        assert result["summary"] == "test"

    def test_parses_json_embedded_in_text(self) -> None:
        payload = json.dumps({
            "summary": "embedded",
            "strengths": [],
            "mistakes": [],
            "improvements": [],
            "entry_analysis": "",
            "pnl_cause": "",
            "ai_grade": "A",
        })
        raw = f"Here is my analysis:\n{payload}\nEnd."
        result = _parse_llm_response(raw)
        assert result is not None
        assert result["summary"] == "embedded"

    def test_returns_none_for_invalid_json(self) -> None:
        result = _parse_llm_response("완전히 잘못된 텍스트")
        assert result is None

    def test_fills_missing_required_fields(self) -> None:
        # summary는 있지만 나머지 누락
        raw = json.dumps({"summary": "only summary"})
        result = _parse_llm_response(raw)
        assert result is not None
        assert result["strengths"] == []
        assert result["mistakes"] == []
        assert result["improvements"] == []

    def test_corrects_invalid_ai_grade(self) -> None:
        raw = json.dumps({
            "summary": "s",
            "strengths": [],
            "mistakes": [],
            "improvements": [],
            "entry_analysis": "",
            "pnl_cause": "",
            "ai_grade": "X",  # 유효하지 않은 등급
        })
        result = _parse_llm_response(raw)
        assert result is not None
        assert result["ai_grade"] == "C"  # 기본값으로 교정


# ── 전체 run_reflection() 흐름 테스트 ────────────────────────────────────────

class TestRunReflection:

    def _make_mock_message(self, content: dict) -> MagicMock:
        msg = MagicMock()
        msg.content = [MagicMock(text=json.dumps(content))]
        msg.usage = MagicMock(input_tokens=500, output_tokens=150)
        return msg

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    def test_successful_reflection(
        self, mock_anthropic_cls: MagicMock, base_input: ReflectionInput
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = self._make_mock_message({
            "summary": "BTC LONG 목표가 달성",
            "strengths": ["RSI 과매도 진입 정확", "Funding Rate 역발상"],
            "mistakes": [],
            "improvements": ["부분 익절 전략 도입"],
            "entry_analysis": "진입 타이밍 우수",
            "pnl_cause": "기술적 지지선 반등",
            "ai_grade": "A",
        })

        result = run_reflection(base_input)

        assert result.output.summary == "BTC LONG 목표가 달성"
        assert result.output.ai_grade == "A"
        assert result.output.strengths == ["RSI 과매도 진입 정확", "Funding Rate 역발상"]
        assert result.tokens_input == 500
        assert result.tokens_output == 150
        assert result.risk_rule_violations == []
        assert result.error is None

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    def test_risk_violations_detected_and_passed_to_result(
        self, mock_anthropic_cls: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = self._make_mock_message({
            "summary": "손실 거래",
            "strengths": [],
            "mistakes": ["R:R 기준 위반"],
            "improvements": ["시그널 필터링 강화"],
            "entry_analysis": "진입 시점 부적절",
            "pnl_cause": "R:R 부족",
            "ai_grade": "D",
        })

        inp = ReflectionInput(
            position_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            coin="ETH",
            symbol="ETHUSDT",
            direction="SHORT",
            leverage=15,
            user_max_leverage=10,  # 위반: 15 > 10
            entry_price=Decimal("3500.00"),
            close_price=Decimal("3450.00"),
            stop_loss=Decimal("3600.00"),
            net_pnl=Decimal("-25.00"),
            pnl_percentage=Decimal("-2.50"),
            duration_seconds=300,
            close_reason="manual",
            signal_rr_ratio=1.5,  # 위반: 1.5 < 2.0
        )

        result = run_reflection(inp)

        assert len(result.risk_rule_violations) >= 2
        assert any("R:R" in v for v in result.risk_rule_violations)
        assert any("레버리지" in v for v in result.risk_rule_violations)

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    def test_fallback_on_api_error(
        self, mock_anthropic_cls: MagicMock, base_input: ReflectionInput
    ) -> None:
        import anthropic as anthropic_module
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = anthropic_module.APIStatusError(
            "rate limit", response=MagicMock(status_code=429), body={}
        )

        result = run_reflection(base_input)

        # 에러 시 폴백 응답 — summary는 있어야 함
        assert result.output.summary != ""
        assert result.error is not None

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    def test_fallback_on_invalid_json(
        self, mock_anthropic_cls: MagicMock, base_input: ReflectionInput
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        bad_msg = MagicMock()
        bad_msg.content = [MagicMock(text="이것은 JSON이 아닙니다")]
        bad_msg.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_client.messages.create.return_value = bad_msg

        result = run_reflection(base_input)

        # finalize 노드가 폴백 처리
        assert result.output.summary != ""

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    def test_output_contains_4_required_fields(
        self, mock_anthropic_cls: MagicMock, base_input: ReflectionInput
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = self._make_mock_message({
            "summary": "요약",
            "strengths": ["강점1"],
            "mistakes": ["실수1"],
            "improvements": ["개선1"],
            "entry_analysis": "진입 분석",
            "pnl_cause": "원인",
            "ai_grade": "B",
        })

        result = run_reflection(base_input)

        # 사용자 지정 4-field 검증
        assert isinstance(result.output.summary, str)
        assert isinstance(result.output.strengths, list)
        assert isinstance(result.output.mistakes, list)
        assert isinstance(result.output.improvements, list)

    @patch("app.agents.reflection_agent.anthropic.Anthropic")
    def test_uses_configured_model(
        self, mock_anthropic_cls: MagicMock, base_input: ReflectionInput
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = self._make_mock_message({
            "summary": "s", "strengths": [], "mistakes": [], "improvements": [],
            "entry_analysis": "", "pnl_cause": "", "ai_grade": "C",
        })

        run_reflection(base_input)

        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-sonnet-4-6"
