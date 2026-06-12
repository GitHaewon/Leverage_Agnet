"""
AI Reviewer 응답 파서.

JSON 추출 → AIReviewResult 반환.
파싱 실패 시 안전 REJECT를 반환한다 — 예외를 밖으로 전파하지 않는다.

안전 REJECT 기준 (CLAUDE.md 절대 규칙):
  - JSON 파싱 실패
  - review_action 필드 누락 / 유효하지 않은 값
  - 예외 발생 시
"""
from __future__ import annotations

import json
import re
from typing import Any

from agents.decision.models import AIReviewAction, AIReviewResult


def parse_review_response(raw: str) -> AIReviewResult:
    """GPT 응답 문자열 → AIReviewResult.

    파싱 실패 시 critical_contradiction=True인 안전 REJECT를 반환한다.
    """
    try:
        data = _extract_json(raw)
        return _build_result(data)
    except Exception:
        return _safe_reject()


# ── 내부 파싱 ─────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict[str, Any]:
    """응답 텍스트에서 JSON 객체를 추출한다. 마크다운 코드블록도 처리."""
    cleaned = re.sub(r"```(?:json)?\n?(.*?)```", r"\1", text, flags=re.DOTALL)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("JSON 객체를 찾을 수 없습니다")
    return json.loads(match.group())


def _build_result(data: dict[str, Any]) -> AIReviewResult:
    action_raw = str(data.get("review_action", "")).upper()
    if action_raw == "APPROVE":
        action = AIReviewAction.APPROVE
    elif action_raw == "REJECT":
        action = AIReviewAction.REJECT
    else:
        # 유효하지 않은 action → 안전 REJECT
        return _safe_reject(reason_summary=f"invalid review_action: {action_raw!r}")

    raw_confidence = data.get("confidence", 0.0)
    confidence = max(0.0, min(1.0, float(raw_confidence)))

    critical = bool(data.get("critical_contradiction", False))

    warnings_raw = data.get("risk_warnings", [])
    warnings = list(warnings_raw) if isinstance(warnings_raw, list) else []

    reason = str(data.get("reason_summary", ""))

    return AIReviewResult(
        review_action=action,
        confidence=round(confidence, 4),
        critical_contradiction=critical,
        risk_warnings=warnings,
        reason_summary=reason,
    )


# ── 안전 REJECT 팩토리 ────────────────────────────────────────────────────────

def _safe_reject(
    *,
    reason_summary: str = "AI review parse failed",
    risk_warnings: list[str] | None = None,
) -> AIReviewResult:
    """파싱 실패 또는 유효하지 않은 응답에 대한 보수적 REJECT."""
    return AIReviewResult(
        review_action=AIReviewAction.REJECT,
        confidence=0.0,
        critical_contradiction=True,
        risk_warnings=risk_warnings if risk_warnings is not None else ["invalid_json"],
        reason_summary=reason_summary,
    )
