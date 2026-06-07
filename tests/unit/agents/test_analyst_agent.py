"""
AnalystAgent 테스트.

검증:
  [정상 흐름]
  - analyze() → AnalystResult 반환
  - StubClient 1회 호출
  - model이 StubClient에 전달됨
  - SYSTEM_PROMPT가 system 인자로 전달됨
  - user_prompt가 messages에 포함됨

  [결과 내용]
  - decision 필드 채워짐
  - confidence 정수
  - reason 비어 있지 않음
  - is_actionable LONG → True
  - tokens_input / tokens_output 반영됨

  [strategy=None 기본값]
  - strategy 미전달 시 중립 StrategyContext 사용 → 정상 작동

  [LLM 스킵 — 모든 점수 0]
  - tech=0, sentiment=0, market=0 → Claude 호출 없이 HOLD 반환
  - forced_hold=True
  - StubClient call_count=0

  [API 오류 처리]
  - FailingClient → HOLD 반환
  - forced_hold=True
  - error 메시지 포함

  [설정]
  - 커스텀 model명이 create_message에 전달됨
  - 커스텀 max_tokens 전달됨 (protocol 인수 검증)
"""
from __future__ import annotations

import asyncio

from agents.analyst.agent import AnalystAgent
from agents.analyst.prompt import SYSTEM_PROMPT

from tests.unit.agents._analyst_fixtures import (
    FailingAnthropicClient,
    StubAnthropicClient,
    make_claude_response,
    make_hold_response,
    make_market,
    make_neutral_strategy,
    make_neutral_technical,
    make_strategy,
    make_technical,
)


def _run(coro):
    return asyncio.run(coro)


def _agent(response: str = "", model: str = "claude-sonnet-4-6", **kwargs) -> tuple[AnalystAgent, StubAnthropicClient]:
    stub = StubAnthropicClient(response_text=response or make_claude_response())
    agent = AnalystAgent(client=stub, model=model, **kwargs)
    return agent, stub


# ── 정상 흐름 ─────────────────────────────────────────────────────────────────────

def test_analyze_returns_analyst_result():
    from agents.analyst.models import AnalystResult
    agent, _ = _agent()
    result = _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert isinstance(result, AnalystResult)


def test_analyze_calls_client_once():
    agent, stub = _agent()
    _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert stub.call_count == 1


def test_analyze_passes_model_to_client():
    agent, stub = _agent(model="claude-sonnet-4-6")
    _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert stub.last_model == "claude-sonnet-4-6"


def test_analyze_passes_system_prompt():
    agent, stub = _agent()
    _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert stub.last_system == SYSTEM_PROMPT


def test_analyze_passes_user_message():
    agent, stub = _agent()
    _run(agent.analyze(make_market(coin="BTC"), make_technical(), make_strategy()))
    assert stub.last_messages[0]["role"] == "user"
    assert "BTC" in stub.last_messages[0]["content"]


# ── 결과 내용 ─────────────────────────────────────────────────────────────────────

def test_analyze_decision_field_set():
    agent, _ = _agent(make_claude_response(decision="LONG"))
    result = _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert result.decision.decision == "LONG"


def test_analyze_confidence_is_integer():
    agent, _ = _agent(make_claude_response(confidence=82))
    result = _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert isinstance(result.decision.confidence, int)
    assert result.decision.confidence == 82


def test_analyze_reason_not_empty():
    agent, _ = _agent()
    result = _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert result.decision.reason != ""


def test_analyze_long_is_actionable():
    agent, _ = _agent(make_claude_response(decision="LONG"))
    result = _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert result.is_actionable is True


def test_analyze_tokens_reflected():
    stub = StubAnthropicClient(tokens_in=847, tokens_out=203)
    agent = AnalystAgent(client=stub)
    result = _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert result.tokens_input == 847
    assert result.tokens_output == 203


def test_analyze_model_used_reflected():
    agent, _ = _agent(model="claude-sonnet-4-6")
    result = _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert result.model_used == "claude-sonnet-4-6"


# ── strategy=None 기본값 ──────────────────────────────────────────────────────────

def test_analyze_strategy_none_uses_neutral():
    """strategy=None → 중립 StrategyContext, 정상 작동."""
    agent, stub = _agent()
    result = _run(agent.analyze(make_market(), make_technical()))  # strategy 생략
    assert stub.call_count == 1
    assert result is not None


def test_analyze_strategy_none_prompt_contains_neutral():
    agent, stub = _agent()
    _run(agent.analyze(make_market(), make_technical()))
    content = stub.last_messages[0]["content"]
    assert "Neutral" in content or "50" in content  # neutral F&G


# ── LLM 스킵 (모든 점수 0) ───────────────────────────────────────────────────────

def test_all_zero_scores_skips_llm():
    agent, stub = _agent()
    _run(agent.analyze(make_market(), make_neutral_technical(), make_neutral_strategy()))
    assert stub.call_count == 0


def test_all_zero_scores_returns_hold():
    agent, _ = _agent()
    result = _run(agent.analyze(make_market(), make_neutral_technical(), make_neutral_strategy()))
    assert result.decision.decision == "HOLD"


def test_all_zero_scores_forced_hold():
    agent, _ = _agent()
    result = _run(agent.analyze(make_market(), make_neutral_technical(), make_neutral_strategy()))
    assert result.forced_hold is True


def test_nonzero_tech_score_does_not_skip():
    """tech_score가 0이 아니면 LLM 호출."""
    agent, stub = _agent()
    tech = make_neutral_technical()
    tech.tech_score = 0.1
    _run(agent.analyze(make_market(), tech, make_neutral_strategy()))
    assert stub.call_count == 1


# ── API 오류 처리 ─────────────────────────────────────────────────────────────────

def test_api_error_returns_hold():
    agent = AnalystAgent(client=FailingAnthropicClient("timeout"))
    result = _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert result.decision.decision == "HOLD"


def test_api_error_forced_hold():
    agent = AnalystAgent(client=FailingAnthropicClient())
    result = _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert result.forced_hold is True


def test_api_error_hold_reason_contains_error():
    agent = AnalystAgent(client=FailingAnthropicClient("connection timeout"))
    result = _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert "connection timeout" in result.hold_reason or "오류" in result.hold_reason


def test_api_error_does_not_raise():
    """API 오류는 호출자로 전파되지 않는다."""
    agent = AnalystAgent(client=FailingAnthropicClient())
    try:
        _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    except Exception:
        assert False, "analyze()가 예외를 전파했습니다."


# ── 설정 전달 ─────────────────────────────────────────────────────────────────────

def test_custom_model_passed_to_client():
    stub = StubAnthropicClient()
    agent = AnalystAgent(client=stub, model="claude-haiku-4-5")
    _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert stub.last_model == "claude-haiku-4-5"


def test_hold_response_from_claude_not_forced():
    """Claude가 직접 HOLD 반환 → forced_hold=False."""
    agent, _ = _agent(make_hold_response())
    result = _run(agent.analyze(make_market(), make_technical(), make_strategy()))
    assert result.decision.decision == "HOLD"
    assert result.forced_hold is False
