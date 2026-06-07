"""
AI Analyst Agent 파서 테스트.

검증:
  [정상 파싱]
  - decision / confidence / reason / risk_level 필드 추출
  - confidence 정수 변환 (0-100)
  - entry / tp / sl / leverage / rr_ratio 추출
  - raw_reasons 추출
  - model_used / tokens 메타 전달
  - is_actionable True for LONG/SHORT

  [마크다운 코드블록 처리]
  - ```json ... ``` 감싸인 응답 파싱

  [Safety Rules — HOLD 강제]
  - confidence < 60 → forced_hold=True, decision=HOLD
  - stop_loss=None (LONG) → forced_hold=True
  - stop_loss=0 (LONG) → forced_hold=True  (0은 None으로 간주 X, 하지만 None만 체크)
  - rr_ratio < 2.0 (LONG) → forced_hold=True
  - HOLD 원본 → forced_hold=False (강제 아님)

  [risk_level 도출]
  - Claude 미출력 시 confidence 기준 파생
  - HOLD → HIGH
  - confidence >= 80 → LOW
  - 60 <= confidence < 80 → MEDIUM

  [파싱 실패 — 안전 HOLD]
  - 빈 문자열 → HOLD, forced_hold=True
  - JSON 아님 → HOLD
  - direction 없음 → HOLD
  - 알 수 없는 direction → HOLD
  - confidence 클램핑 (>100 → 100, <0 → 0)
  - leverage 클램핑 (>20 → 20, <1 → 1)
"""
from __future__ import annotations

import json

from agents.analyst.parser import _derive_risk_level, parse_response

from tests.unit.agents._analyst_fixtures import (
    make_claude_response,
    make_hold_response,
    make_markdown_response,
)


# ── 정상 파싱 ─────────────────────────────────────────────────────────────────────

def test_parse_long_decision():
    result = parse_response(make_claude_response(decision="LONG"))
    assert result.decision.decision == "LONG"


def test_parse_short_decision():
    result = parse_response(make_claude_response(decision="SHORT", stop_loss=68300.0, take_profit=65700.0))
    assert result.decision.decision == "SHORT"


def test_parse_confidence_as_integer():
    result = parse_response(make_claude_response(confidence=82))
    assert result.decision.confidence == 82
    assert isinstance(result.decision.confidence, int)


def test_parse_reason_string():
    result = parse_response(make_claude_response(reason="RSI=42 과매도"))
    assert result.decision.reason == "RSI=42 과매도"


def test_parse_risk_level_medium():
    result = parse_response(make_claude_response(risk_level="MEDIUM"))
    assert result.decision.risk_level == "MEDIUM"


def test_parse_risk_level_low():
    result = parse_response(make_claude_response(risk_level="LOW"))
    assert result.decision.risk_level == "LOW"


def test_parse_entry_price():
    result = parse_response(make_claude_response(entry_price=67450.0))
    assert result.entry_price == 67450.0


def test_parse_take_profit():
    result = parse_response(make_claude_response(take_profit=69200.0))
    assert result.take_profit == 69200.0


def test_parse_stop_loss():
    result = parse_response(make_claude_response(stop_loss=66800.0))
    assert result.stop_loss == 66800.0


def test_parse_leverage():
    result = parse_response(make_claude_response(leverage=5))
    assert result.leverage == 5


def test_parse_rr_ratio():
    result = parse_response(make_claude_response(rr_ratio=2.71))
    assert abs(result.rr_ratio - 2.71) < 1e-9


def test_parse_raw_reasons():
    reasons = ["근거1", "근거2", "근거3"]
    result = parse_response(make_claude_response(raw_reasons=reasons))
    assert result.raw_reasons == reasons


def test_parse_model_meta():
    result = parse_response(make_claude_response(), model_used="claude-sonnet-4-6", tokens_input=847, tokens_output=203)
    assert result.model_used == "claude-sonnet-4-6"
    assert result.tokens_input == 847
    assert result.tokens_output == 203


def test_parse_long_is_actionable():
    result = parse_response(make_claude_response(decision="LONG"))
    assert result.is_actionable is True


def test_parse_hold_not_actionable():
    result = parse_response(make_hold_response())
    assert result.is_actionable is False


def test_parse_forced_hold_false_for_valid():
    result = parse_response(make_claude_response())
    assert result.forced_hold is False


# ── 마크다운 코드블록 처리 ────────────────────────────────────────────────────────

def test_parse_markdown_wrapped_json():
    raw = make_markdown_response(make_claude_response())
    result = parse_response(raw)
    assert result.decision.decision == "LONG"


def test_parse_markdown_with_json_tag():
    raw = f"```json\n{make_claude_response()}\n```"
    result = parse_response(raw)
    assert result.decision.confidence == 82


# ── Safety Rules ──────────────────────────────────────────────────────────────────

def test_confidence_below_60_forces_hold():
    raw = make_claude_response(decision="LONG", confidence=55, stop_loss=66800.0, rr_ratio=2.5)
    result = parse_response(raw)
    assert result.decision.decision == "HOLD"
    assert result.forced_hold is True


def test_confidence_below_60_hold_reason_contains_threshold():
    raw = make_claude_response(decision="LONG", confidence=50, stop_loss=66800.0, rr_ratio=2.5)
    result = parse_response(raw)
    assert "60" in result.hold_reason


def test_missing_stop_loss_forces_hold():
    data = json.loads(make_claude_response(decision="LONG", confidence=80, rr_ratio=2.5))
    data["stop_loss"] = None
    result = parse_response(json.dumps(data))
    assert result.decision.decision == "HOLD"
    assert result.forced_hold is True


def test_rr_ratio_below_2_forces_hold():
    raw = make_claude_response(decision="LONG", confidence=80, stop_loss=66800.0, rr_ratio=1.5)
    result = parse_response(raw)
    assert result.decision.decision == "HOLD"
    assert result.forced_hold is True


def test_rr_below_2_hold_reason_contains_rr():
    raw = make_claude_response(decision="LONG", confidence=80, stop_loss=66800.0, rr_ratio=1.8)
    result = parse_response(raw)
    assert "R:R" in result.hold_reason or "1.8" in result.hold_reason


def test_hold_original_not_force_hold():
    """Claude가 직접 HOLD 출력 → forced_hold=False."""
    result = parse_response(make_hold_response())
    assert result.decision.decision == "HOLD"
    assert result.forced_hold is False


def test_safety_preserves_original_confidence_on_force_hold():
    """forced_hold 시에도 원본 confidence 값은 보존된다."""
    raw = make_claude_response(decision="LONG", confidence=55, stop_loss=66800.0, rr_ratio=2.5)
    result = parse_response(raw)
    assert result.decision.confidence == 55


def test_safety_risk_level_high_on_force_hold():
    """forced_hold → risk_level은 항상 HIGH."""
    raw = make_claude_response(decision="LONG", confidence=55, stop_loss=66800.0, rr_ratio=2.5)
    result = parse_response(raw)
    assert result.decision.risk_level == "HIGH"


# ── risk_level 도출 ───────────────────────────────────────────────────────────────

def test_derive_risk_level_hold_is_high():
    assert _derive_risk_level("HOLD", 0) == "HIGH"


def test_derive_risk_level_confidence_80_is_low():
    assert _derive_risk_level("LONG", 80) == "LOW"


def test_derive_risk_level_confidence_90_is_low():
    assert _derive_risk_level("SHORT", 90) == "LOW"


def test_derive_risk_level_confidence_65_is_medium():
    assert _derive_risk_level("LONG", 65) == "MEDIUM"


def test_derive_risk_level_confidence_60_is_medium():
    assert _derive_risk_level("LONG", 60) == "MEDIUM"


def test_derive_risk_level_confidence_50_is_high():
    assert _derive_risk_level("LONG", 50) == "HIGH"


def test_risk_level_derived_when_claude_omits_it():
    """Claude가 risk_level 미출력 시 confidence 기준으로 파생된다."""
    data = json.loads(make_claude_response(confidence=85, risk_level="INVALID"))
    result = parse_response(json.dumps(data))
    # confidence=85 >= 80 → LOW (safety rule 통과 시)
    assert result.decision.risk_level == "LOW"


# ── 파싱 실패 안전 HOLD ───────────────────────────────────────────────────────────

def test_empty_string_returns_hold():
    result = parse_response("")
    assert result.decision.decision == "HOLD"
    assert result.forced_hold is True


def test_non_json_returns_hold():
    result = parse_response("I cannot provide a trading signal.")
    assert result.decision.decision == "HOLD"


def test_unknown_direction_becomes_hold():
    data = json.loads(make_claude_response())
    data["decision"] = "BUY"  # 잘못된 값
    result = parse_response(json.dumps(data))
    # "BUY" → "HOLD" (방향 정규화), confidence < 60으로 인해 HOLD 유지
    assert result.decision.decision == "HOLD"


def test_confidence_clamped_at_100():
    data = json.loads(make_claude_response(confidence=82))
    data["confidence"] = 150  # 범위 초과
    result = parse_response(json.dumps(data))
    assert result.decision.confidence <= 100


def test_confidence_clamped_at_0():
    data = json.loads(make_claude_response(confidence=82))
    data["confidence"] = -10  # 음수
    result = parse_response(json.dumps(data))
    assert result.decision.confidence >= 0


def test_leverage_clamped_at_20():
    raw = make_claude_response(leverage=50)  # 상한 초과
    result = parse_response(raw)
    assert result.leverage <= 20


def test_leverage_clamped_at_1():
    raw = make_claude_response(leverage=0)  # 하한 미만
    result = parse_response(raw)
    assert result.leverage >= 1


def test_entry_price_fallback_used():
    data = json.loads(make_claude_response())
    data.pop("entry_price", None)
    result = parse_response(json.dumps(data), entry_price_fallback=67450.0)
    assert result.entry_price == 67450.0
