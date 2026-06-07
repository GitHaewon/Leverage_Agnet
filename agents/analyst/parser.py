"""
AI Analyst Agent 응답 파서.

순수 함수 — I/O 없음.
JSON 추출 → 필드 검증 → Safety Rule 적용 → AnalystResult 반환.

Safety Rules (AGENTS.md §5.6, CLAUDE.md 절대 규칙):
  1. confidence < 60 → HOLD 강제
  2. LONG/SHORT에 stop_loss 없음 → HOLD 강제
  3. LONG/SHORT에 rr_ratio < 2.0 → HOLD 강제
  4. JSON 파싱 실패 → HOLD 반환
"""
from __future__ import annotations

import json
import re
from typing import Any

from agents.analyst.models import AnalysisDecision, AnalystResult

_MIN_CONFIDENCE = 60
_MIN_RR_RATIO = 2.0


# ── 공개 API ─────────────────────────────────────────────────────────────────────

def parse_response(
    raw: str,
    *,
    entry_price_fallback: float = 0.0,
    model_used: str = "",
    tokens_input: int = 0,
    tokens_output: int = 0,
) -> AnalystResult:
    """Claude 응답 문자열 → AnalystResult.

    파싱 실패 또는 Safety Rule 위반 시 HOLD를 반환한다.
    """
    try:
        data = _extract_json(raw)
        result = _build_result(data, entry_price_fallback, model_used, tokens_input, tokens_output)
        return _validate_and_enforce(result)
    except Exception as exc:
        return _safe_hold(f"파싱 실패: {exc}", model_used, tokens_input, tokens_output)


# ── 내부 파싱 ────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict[str, Any]:
    """응답 텍스트에서 JSON 객체를 추출한다. 마크다운 코드블록도 처리."""
    cleaned = re.sub(r"```(?:json)?\n?(.*?)```", r"\1", text, flags=re.DOTALL)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("JSON 객체를 찾을 수 없습니다")
    return json.loads(match.group())


def _build_result(
    data: dict[str, Any],
    entry_price_fallback: float,
    model_used: str,
    tokens_input: int,
    tokens_output: int,
) -> AnalystResult:
    direction = str(data.get("decision", "HOLD")).upper()
    if direction not in ("LONG", "SHORT", "HOLD"):
        direction = "HOLD"

    confidence = max(0, min(100, int(data.get("confidence", 0))))
    reason = str(data.get("reason", "분석 결과 없음"))
    risk_level_raw = str(data.get("risk_level", "")).upper()
    risk_level = risk_level_raw if risk_level_raw in ("LOW", "MEDIUM", "HIGH") else \
        _derive_risk_level(direction, confidence)

    entry_price = _safe_float(data.get("entry_price"), entry_price_fallback)
    take_profit = _optional_float(data.get("take_profit"))
    stop_loss = _optional_float(data.get("stop_loss"))
    leverage = max(1, min(20, int(data.get("leverage", 1))))
    rr_ratio = _safe_float(data.get("rr_ratio"), 0.0)
    raw_reasons = list(data.get("raw_reasons", [reason]))

    return AnalystResult(
        decision=AnalysisDecision(
            decision=direction,  # type: ignore[arg-type]
            confidence=confidence,
            reason=reason,
            risk_level=risk_level,  # type: ignore[arg-type]
        ),
        entry_price=entry_price,
        take_profit=take_profit,
        stop_loss=stop_loss,
        leverage=leverage,
        rr_ratio=rr_ratio,
        raw_reasons=raw_reasons,
        model_used=model_used,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
    )


def _validate_and_enforce(result: AnalystResult) -> AnalystResult:
    """Safety Rule 위반을 HOLD로 강제 변환한다."""
    if result.decision.decision == "HOLD":
        return result

    if result.decision.confidence < _MIN_CONFIDENCE:
        return _force_hold(
            result,
            f"confidence {result.decision.confidence} < {_MIN_CONFIDENCE} — HOLD 강제",
        )

    if result.stop_loss is None:
        return _force_hold(result, "stop_loss 없음 — HOLD 강제 (CLAUDE.md 절대 규칙)")

    if result.rr_ratio < _MIN_RR_RATIO:
        return _force_hold(
            result,
            f"R:R {result.rr_ratio:.2f} < {_MIN_RR_RATIO} — HOLD 강제",
        )

    return result


def _force_hold(original: AnalystResult, reason: str) -> AnalystResult:
    """원본 결과를 HOLD로 변환한다. 가격 데이터는 보존한다."""
    return AnalystResult(
        decision=AnalysisDecision(
            decision="HOLD",
            confidence=original.decision.confidence,
            reason=reason,
            risk_level="HIGH",
        ),
        entry_price=original.entry_price,
        take_profit=original.take_profit,
        stop_loss=original.stop_loss,
        leverage=original.leverage,
        rr_ratio=original.rr_ratio,
        raw_reasons=original.raw_reasons,
        model_used=original.model_used,
        tokens_input=original.tokens_input,
        tokens_output=original.tokens_output,
        forced_hold=True,
        hold_reason=reason,
    )


def _safe_hold(
    reason: str,
    model_used: str = "",
    tokens_input: int = 0,
    tokens_output: int = 0,
) -> AnalystResult:
    return AnalystResult(
        decision=AnalysisDecision(
            decision="HOLD",
            confidence=0,
            reason=reason,
            risk_level="HIGH",
        ),
        entry_price=0.0,
        take_profit=None,
        stop_loss=None,
        leverage=1,
        rr_ratio=0.0,
        raw_reasons=[reason],
        model_used=model_used,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        forced_hold=True,
        hold_reason=reason,
    )


# ── 유틸 ─────────────────────────────────────────────────────────────────────────

def _derive_risk_level(decision: str, confidence: int) -> str:
    """decision + confidence → risk_level 도출 (Claude 미출력 시 폴백)."""
    if decision == "HOLD":
        return "HIGH"
    if confidence >= 80:
        return "LOW"
    if confidence >= 60:
        return "MEDIUM"
    return "HIGH"


def _safe_float(val: Any, default: float) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _optional_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None
