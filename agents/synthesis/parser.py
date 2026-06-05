"""
Claude 응답 파서 — JSON 추출 + 시그널 검증.

검증 실패 시 HOLD로 강제 변환 (AGENTS.md §5.6).
"""
from __future__ import annotations

import json
import re
from typing import Any

from agents.synthesis.models import SynthesisResult

MIN_CONFIDENCE = 0.60
MIN_RR_RATIO = 2.0


def parse_claude_response(raw: str) -> SynthesisResult:
    """Claude 응답 문자열에서 JSON을 추출하고 SynthesisResult로 변환한다.

    JSON 파싱 실패 또는 검증 실패 시 HOLD를 반환한다.
    """
    try:
        data = _extract_json(raw)
        result = _dict_to_result(data, raw)
        return _validate_and_enforce(result)
    except Exception as exc:
        return SynthesisResult.hold(reason=f"파싱 실패: {exc}", skipped=False)


def _extract_json(text: str) -> dict[str, Any]:
    """응답에서 JSON 객체를 추출한다. 마크다운 코드블록도 처리한다."""
    # 마크다운 코드블록 제거
    cleaned = re.sub(r"```(?:json)?\n?(.*?)```", r"\1", text, flags=re.DOTALL)

    # 중괄호로 묶인 JSON 추출
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("JSON 객체를 찾을 수 없습니다")
    return json.loads(match.group())


def _dict_to_result(data: dict, raw: str) -> SynthesisResult:
    direction = str(data.get("direction", "HOLD")).upper()
    if direction not in ("LONG", "SHORT", "HOLD"):
        direction = "HOLD"

    return SynthesisResult(
        direction=direction,  # type: ignore[arg-type]
        confidence=float(data.get("confidence", 0.0)),
        entry_price=float(data.get("entry_price", 0.0)),
        take_profit=_optional_float(data.get("take_profit")),
        stop_loss=_optional_float(data.get("stop_loss")),
        leverage=max(1, min(20, int(data.get("leverage", 1)))),
        rr_ratio=float(data.get("rr_ratio", 0.0)),
        reasons=list(data.get("reasons", [])),
        raw_response=raw,
    )


def _validate_and_enforce(result: SynthesisResult) -> SynthesisResult:
    """검증 실패 조건을 HOLD로 강제 변환한다 (AGENTS.md §5.6)."""
    if result.direction == "HOLD":
        return result

    if result.confidence < MIN_CONFIDENCE:
        return SynthesisResult.hold(
            reason=f"confidence {result.confidence:.2f} < {MIN_CONFIDENCE} — HOLD 강제"
        )

    if result.stop_loss is None:
        return SynthesisResult.hold(reason="stop_loss 없음 — HOLD 강제")

    if result.rr_ratio < MIN_RR_RATIO:
        return SynthesisResult.hold(
            reason=f"R:R {result.rr_ratio:.2f} < {MIN_RR_RATIO} — HOLD 강제"
        )

    if len(result.reasons) < 3:
        result.reasons = result.reasons + ["(추가 근거 없음)"] * (3 - len(result.reasons))

    return result


def _optional_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None
