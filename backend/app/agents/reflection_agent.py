"""
ReflectionAgent — 거래 종료 후 AI 회고 분석.

LangGraph StateGraph:
  prepare_context → run_llm → finalize → END

역할:
  1. 진입 이유 / 수익·손실 원인 분석
  2. Risk Rule 위반 여부 프로그래매틱 검증
  3. Claude Sonnet → 구조화된 JSON 출력
  4. 출력: { summary, strengths, mistakes, improvements }
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Optional

import anthropic
from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from app.core.config import settings
from app.schemas.reflection import ReflectionInput, ReflectionOutput

logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────────────────

SYSTEM_MAX_LEVERAGE = 20
MIN_RR_RATIO = 2.0

SYSTEM_PROMPT = """\
You are an expert cryptocurrency futures trading coach conducting a post-trade review.
Analyze the completed trade objectively and provide structured feedback.

RULES:
1. Be specific — reference actual price levels, indicator values, and timing from the context
2. Grade the trade: A (excellent execution), B (good), C (acceptable), D (poor risk management)
3. Identify strengths even in losing trades (good process ≠ bad outcome)
4. Identify mistakes even in winning trades (luck ≠ skill)
5. Write ALL text in Korean
6. Output ONLY valid JSON — no markdown, no code blocks, no explanation outside JSON

OUTPUT FORMAT (strict JSON, no deviation):
{
  "summary": "1-2문장 거래 요약",
  "strengths": ["구체적 강점 1", "구체적 강점 2"],
  "mistakes": ["구체적 실수 1", "구체적 실수 2"],
  "improvements": ["다음 번 실천 사항 1", "다음 번 실천 사항 2"],
  "entry_analysis": "진입 시점 상세 평가 (한국어)",
  "pnl_cause": "수익/손실 근본 원인 (한국어)",
  "ai_grade": "A|B|C|D"
}

strengths/mistakes/improvements: 2~4항목. 없으면 빈 배열 [].
"""

_CLOSE_REASON_KO: dict[str, str] = {
    "tp_hit":       "목표가 도달 (익절)",
    "sl_hit":       "손절가 도달 (손절)",
    "manual":       "수동 종료",
    "liquidated":   "강제 청산",
    "emergency":    "긴급 청산",
    "dca_reversal": "DCA 반전 청산",
}


# ── LangGraph State ───────────────────────────────────────────────────────────

class ReflectionState(TypedDict):
    # 입력 (ReflectionInput에서 평탄화)
    position_id: str
    user_id: str
    coin: str
    symbol: str
    direction: str
    leverage: int
    user_max_leverage: int
    entry_price: str
    close_price: str
    stop_loss: str
    take_profit: Optional[str]
    net_pnl: str
    pnl_percentage: str
    duration_seconds: int
    close_reason: str
    signal_confidence: Optional[float]
    signal_reasons: list[str]
    signal_rr_ratio: Optional[float]
    signal_entry_price: Optional[str]
    signal_tp: Optional[str]
    signal_sl: Optional[str]
    price_action_summary: Optional[str]

    # 중간 계산 결과
    risk_rule_violations: list[str]
    context_text: str

    # 최종 출력
    reflection_output: Optional[dict[str, Any]]
    error: Optional[str]
    tokens_input: int
    tokens_output: int


# ── 노드: 컨텍스트 준비 + 리스크 위반 검증 ───────────────────────────────────

def prepare_context(state: ReflectionState) -> ReflectionState:
    """거래 컨텍스트 텍스트 생성 + 리스크 규칙 위반 프로그래매틱 검증."""
    violations = _detect_risk_violations(state)
    context_text = _build_context_text(state, violations)
    return {
        **state,
        "risk_rule_violations": violations,
        "context_text": context_text,
    }


def _detect_risk_violations(state: ReflectionState) -> list[str]:
    """
    CLAUDE.md 트레이딩 안전 규칙 위반 여부를 프로그래매틱으로 검증한다.
    LLM 판단이 아닌 사실 기반 체크다.
    """
    violations: list[str] = []

    # 규칙 1: R:R 최소 1:2
    rr = state.get("signal_rr_ratio")
    if rr is not None and rr < MIN_RR_RATIO:
        violations.append(f"R:R 비율 {rr:.2f} < 최소 기준 {MIN_RR_RATIO} — 시그널이 기준 미달 상태로 실행됨")

    # 규칙 2: 레버리지 상한
    lev = state["leverage"]
    if lev > SYSTEM_MAX_LEVERAGE:
        violations.append(f"레버리지 {lev}x > 시스템 상한 {SYSTEM_MAX_LEVERAGE}x")
    elif lev > state["user_max_leverage"]:
        violations.append(
            f"레버리지 {lev}x > 사용자 최대 설정 {state['user_max_leverage']}x"
        )

    # 규칙 4: 포지션 사이징 — SL 없는 주문은 DB 제약으로 방지되지만 이중 확인
    if not state.get("stop_loss"):
        violations.append("손절(Stop Loss) 미설정 — 절대 규칙 위반")

    # 규칙 3: 신뢰도 0.60 미만 시그널 실행 감지
    conf = state.get("signal_confidence")
    if conf is not None and conf < 0.60:
        violations.append(
            f"시그널 신뢰도 {conf:.0%} < 0.60 — HOLD 강제 조건 미적용 의심"
        )

    return violations


def _build_context_text(state: ReflectionState, violations: list[str]) -> str:
    """Claude에 전달할 거래 컨텍스트 텍스트를 구성한다."""
    direction_ko = "롱(LONG)" if state["direction"] == "LONG" else "숏(SHORT)"
    close_reason_ko = _CLOSE_REASON_KO.get(state["close_reason"], state["close_reason"])
    pnl_sign = "+" if Decimal(state["net_pnl"]) >= 0 else ""
    duration_min = state["duration_seconds"] // 60
    duration_sec = state["duration_seconds"] % 60

    lines = [
        "=== 완료된 거래 ===",
        f"심볼: {state['symbol']} {direction_ko}",
        f"레버리지: {state['leverage']}x",
        f"진입가: ${Decimal(state['entry_price']):,.2f}",
        f"청산가: ${Decimal(state['close_price']):,.2f}",
        f"P&L: {pnl_sign}{Decimal(state['net_pnl']):.2f} USDT "
        f"({pnl_sign}{Decimal(state['pnl_percentage']):.2f}%)",
        f"보유 시간: {duration_min}분 {duration_sec}초",
        f"종료 이유: {close_reason_ko}",
        "",
        "=== 목표가 / 손절가 ===",
        f"목표가(TP): "
        + (f"${Decimal(state['take_profit']):,.2f}" if state.get("take_profit") else "미설정"),
        f"손절가(SL): ${Decimal(state['stop_loss']):,.2f}",
        "",
    ]

    if state.get("signal_reasons"):
        lines += [
            "=== AI 시그널 근거 ===",
            f"신뢰도: {state['signal_confidence']:.0%}" if state.get("signal_confidence") else "신뢰도: N/A",
            f"R:R 비율: {state['signal_rr_ratio']:.2f}" if state.get("signal_rr_ratio") else "",
        ]
        for reason in state["signal_reasons"]:
            lines.append(f"• {reason}")
        lines.append("")

    if violations:
        lines += ["=== Risk Rule 위반 감지 ==="]
        for v in violations:
            lines.append(f"⚠️ {v}")
        lines.append("")
    else:
        lines += ["=== Risk Rule 위반 감지 ===", "위반 없음", ""]

    if state.get("price_action_summary"):
        lines += [
            "=== 포지션 보유 중 가격 흐름 ===",
            state["price_action_summary"],
            "",
        ]

    return "\n".join(lines)


# ── 노드: Claude Sonnet 호출 ──────────────────────────────────────────────────

def run_llm(state: ReflectionState) -> ReflectionState:
    """Claude Sonnet API를 호출하여 구조화된 회고 분석을 생성한다."""
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    try:
        response = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=800,
            temperature=0.2,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": state["context_text"]}],
        )
    except anthropic.APIStatusError as e:
        logger.error("Claude API error: %s", e)
        return {**state, "error": f"Claude API error: {e.status_code}", "tokens_input": 0, "tokens_output": 0}

    raw_text = response.content[0].text.strip()
    parsed = _parse_llm_response(raw_text)

    return {
        **state,
        "reflection_output": parsed,
        "tokens_input": response.usage.input_tokens,
        "tokens_output": response.usage.output_tokens,
        "error": None if parsed else "JSON parsing failed",
    }


def _parse_llm_response(raw: str) -> dict[str, Any] | None:
    """
    Claude 응답에서 JSON을 추출·검증한다.
    마크다운 코드블록이 포함된 경우를 방어적으로 처리한다.
    """
    text = raw.strip()
    # 마크다운 코드블록 제거
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.startswith("```")
        )

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # JSON 블록을 찾아서 재시도
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            logger.error("No JSON found in LLM response: %s", raw[:200])
            return None
        try:
            data = json.loads(raw[start:end])
        except json.JSONDecodeError:
            logger.error("JSON parse failed: %s", raw[:200])
            return None

    # 필수 4-field 검증
    required = {"summary", "strengths", "mistakes", "improvements"}
    if not required.issubset(data.keys()):
        missing = required - data.keys()
        logger.warning("LLM output missing fields: %s", missing)
        # 누락 필드는 기본값으로 채움
        for field in missing:
            data[field] = [] if field != "summary" else "분석 데이터 부족"

    # ai_grade 검증
    grade = data.get("ai_grade", "C")
    if grade not in {"A", "B", "C", "D"}:
        data["ai_grade"] = "C"

    return data


# ── 노드: 최종 검증 ───────────────────────────────────────────────────────────

def finalize(state: ReflectionState) -> ReflectionState:
    """
    LLM 출력이 없거나 에러인 경우 폴백 응답을 생성한다.
    최소한의 구조적 출력은 항상 보장된다.
    """
    if state.get("reflection_output"):
        return state

    close_reason_ko = _CLOSE_REASON_KO.get(state["close_reason"], state["close_reason"])
    pnl_str = f"{Decimal(state['net_pnl']):.2f} USDT"
    fallback: dict[str, Any] = {
        "summary": (
            f"{state['coin']} {state['direction']} 포지션 — "
            f"{close_reason_ko}, P&L {pnl_str}"
        ),
        "strengths": [],
        "mistakes": [],
        "improvements": ["AI 분석을 재시도하거나 수동으로 리뷰하세요."],
        "entry_analysis": None,
        "pnl_cause": None,
        "ai_grade": "C",
    }
    return {**state, "reflection_output": fallback, "error": state.get("error")}


# ── LangGraph 그래프 ──────────────────────────────────────────────────────────

def _build_graph() -> Any:
    graph: StateGraph = StateGraph(ReflectionState)

    graph.add_node("prepare_context", prepare_context)
    graph.add_node("run_llm", run_llm)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("prepare_context")
    graph.add_edge("prepare_context", "run_llm")
    graph.add_edge("run_llm", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


_graph = _build_graph()


# ── 공개 인터페이스 ───────────────────────────────────────────────────────────

class ReflectionResult:
    """run_reflection()의 반환 값."""

    def __init__(self, state: ReflectionState) -> None:
        raw = state.get("reflection_output") or {}
        self.output = ReflectionOutput(
            summary=raw.get("summary", ""),
            strengths=raw.get("strengths") or [],
            mistakes=raw.get("mistakes") or [],
            improvements=raw.get("improvements") or [],
            entry_analysis=raw.get("entry_analysis") or "",
            pnl_cause=raw.get("pnl_cause") or "",
            ai_grade=raw.get("ai_grade", "C"),
        )
        self.risk_rule_violations: list[str] = state.get("risk_rule_violations") or []
        self.tokens_input: int = state.get("tokens_input") or 0
        self.tokens_output: int = state.get("tokens_output") or 0
        self.error: str | None = state.get("error")


def run_reflection(inp: ReflectionInput) -> ReflectionResult:
    """
    ReflectionAgent 실행 진입점.

    동기 함수 — Celery task에서 asyncio.run() 없이 직접 호출한다.
    LangGraph 내부는 순수 Python (비동기 없음).
    """
    initial_state: ReflectionState = {
        "position_id": str(inp.position_id),
        "user_id": str(inp.user_id),
        "coin": inp.coin,
        "symbol": inp.symbol,
        "direction": inp.direction,
        "leverage": inp.leverage,
        "user_max_leverage": inp.user_max_leverage,
        "entry_price": str(inp.entry_price),
        "close_price": str(inp.close_price),
        "stop_loss": str(inp.stop_loss),
        "take_profit": str(inp.take_profit) if inp.take_profit else None,
        "net_pnl": str(inp.net_pnl),
        "pnl_percentage": str(inp.pnl_percentage),
        "duration_seconds": inp.duration_seconds,
        "close_reason": inp.close_reason,
        "signal_confidence": inp.signal_confidence,
        "signal_reasons": inp.signal_reasons,
        "signal_rr_ratio": inp.signal_rr_ratio,
        "signal_entry_price": str(inp.signal_entry_price) if inp.signal_entry_price else None,
        "signal_tp": str(inp.signal_tp) if inp.signal_tp else None,
        "signal_sl": str(inp.signal_sl) if inp.signal_sl else None,
        "price_action_summary": inp.price_action_summary,
        # 중간 결과 초기화
        "risk_rule_violations": [],
        "context_text": "",
        "reflection_output": None,
        "error": None,
        "tokens_input": 0,
        "tokens_output": 0,
    }

    final_state: ReflectionState = _graph.invoke(initial_state)
    return ReflectionResult(final_state)
