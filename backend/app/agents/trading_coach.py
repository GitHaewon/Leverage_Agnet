"""
AI Trading Coach — 주간 성과 분석 에이전트.

LangGraph 4-노드 파이프라인:
  aggregate_stats → detect_patterns → synthesize → finalize

외부 의존 없는 순수 집계/감지 후 Claude Sonnet 합성.
DB 접근은 없다 — CoachingService가 데이터를 주입한다.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, TypedDict
from zoneinfo import ZoneInfo

import anthropic
from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from app.core.config import settings
from app.schemas.coaching import (
    CoinStat,
    EmotionalPattern,
    HourStat,
    JournalData,
    RepeatedMistake,
    StrategyStat,
    WeekdayStat,
)

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

# ── 상수 ──────────────────────────────────────────────────────────────────────

MIN_TRADES_REQUIRED = 5
NIGHT_HOURS_KST = frozenset(range(0, 6))      # 00:00 ~ 05:59 KST
WEEKDAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]

# 리스크 점수 감점
_SCORE_HIGH_PATTERN      = 15
_SCORE_MEDIUM_PATTERN    = 8
_SCORE_REPEATED_MISTAKE  = 5   # count >= 3 인 반복 실수 1건당
_SCORE_LOW_WIN_RATE      = 10  # 전체 승률 < 40%
_SCORE_NIGHT_POOR        = 5   # 야간 승률 패턴 추가 감점

# 복수매매: 연속 2손실 후 레버리지가 이전 대비 이 배수 이상 증가
_REVENGE_LEVERAGE_RATIO  = 1.5

# Claude 합성
_MAX_TOKENS  = 600
_TEMPERATURE = 0.3


# ── LangGraph State ───────────────────────────────────────────────────────────

class CoachState(TypedDict):
    # 입력
    user_id: str
    period_start: datetime
    period_end: datetime
    journals: list[JournalData]
    reflection_mistakes: list[str]

    # 통계 (plain dict — LangGraph 직렬화 호환)
    overall_stats: dict[str, Any]
    hourly_stats: list[dict]
    weekday_stats: list[dict]
    coin_stats: list[dict]
    strategy_stats: list[dict]
    repeated_mistakes: list[dict]

    # 패턴 감지
    emotional_patterns: list[dict]
    risk_behavior_score: int

    # Claude 출력
    coach_summary: str
    strengths: list[str]
    blind_spots: list[str]
    weekly_goal: str

    # 제어
    skip_reason: str | None
    model_used: str
    tokens_input: int
    tokens_output: int
    errors: list[str]


# ── 입출력 스키마 ─────────────────────────────────────────────────────────────

class CoachInput(BaseModel):
    user_id: str
    period_start: datetime
    period_end: datetime
    journals: list[JournalData]
    reflection_mistakes: list[str] = []


class CoachResult(BaseModel):
    overall_stats: dict[str, Any]
    hourly_stats: list[HourStat]
    weekday_stats: list[WeekdayStat]
    coin_stats: list[CoinStat]
    strategy_stats: list[StrategyStat]
    repeated_mistakes: list[RepeatedMistake]
    emotional_patterns: list[EmotionalPattern]
    risk_behavior_score: int
    coach_summary: str
    strengths: list[str]
    blind_spots: list[str]
    weekly_goal: str
    skip_reason: str | None
    model_used: str
    tokens_input: int
    tokens_output: int


# ── Claude 프롬프트 ───────────────────────────────────────────────────────────

_COACH_SYSTEM = """\
당신은 암호화폐 선물 거래 전문 코치입니다.
사용자의 거래 데이터를 분석하여 실질적이고 개인화된 주간 코칭 리포트를 작성하세요.

규칙:
1. 구체적인 수치를 반드시 인용하세요 (예: "화요일 승률 78%", "야간 18%p 저하")
2. 격려적이지만 직설적으로 작성하세요
3. 한국어로 작성하세요
4. weekly_goal은 하나만 제시하세요 (집중력이 중요합니다)

반드시 아래 JSON 형식으로만 응답하세요:
{
  "coach_summary": "2-3문장 핵심 인사이트 (예: 'BTC 거래는 수익성이 높지만 SOL 거래는 지속 손실 중입니다.')",
  "strengths": ["강점1", "강점2", "강점3"],
  "blind_spots": ["개선점1", "개선점2", "개선점3"],
  "weekly_goal": "이번 주 실천할 구체적 목표 1가지"
}
"""


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────

def _win_rate(journals: list[JournalData]) -> float:
    if not journals:
        return 0.0
    return sum(1 for j in journals if j["net_pnl"] > 0) / len(journals)


def _avg_pnl(journals: list[JournalData]) -> float:
    if not journals:
        return 0.0
    return sum(j["net_pnl"] for j in journals) / len(journals)


def _kst_hour(dt: datetime) -> int:
    return dt.astimezone(KST).hour


def _kst_weekday(dt: datetime) -> int:  # 0=월 … 6=일 (Python weekday)
    return dt.astimezone(KST).weekday()


def _time_block_label(hour: int) -> str:
    if hour < 6:
        return "새벽(00-05시)"
    if hour < 12:
        return "오전(06-11시)"
    if hour < 18:
        return "오후(12-17시)"
    return "저녁(18-23시)"


# ── 노드 1: 통계 집계 ─────────────────────────────────────────────────────────

def aggregate_stats(state: CoachState) -> CoachState:
    journals = state["journals"]

    if len(journals) < MIN_TRADES_REQUIRED:
        return {
            **state,
            "skip_reason": (
                f"거래 데이터 부족: {len(journals)}건 "
                f"(최소 {MIN_TRADES_REQUIRED}건 필요)"
            ),
            "overall_stats": {},
            "hourly_stats": [],
            "weekday_stats": [],
            "coin_stats": [],
            "strategy_stats": [],
            "repeated_mistakes": [],
        }

    total = len(journals)
    overall_wr = _win_rate(journals)
    total_pnl = sum(j["net_pnl"] for j in journals)

    overall_stats: dict[str, Any] = {
        "total_trades": total,
        "win_rate": round(overall_wr, 4),
        "win_count": sum(1 for j in journals if j["net_pnl"] > 0),
        "loss_count": sum(1 for j in journals if j["net_pnl"] <= 0),
        "total_pnl_usdt": round(total_pnl, 2),
        "avg_pnl_usdt": round(total_pnl / total, 2),
    }

    # 시간대별 (KST)
    hourly_groups: dict[int, list] = defaultdict(list)
    for j in journals:
        hourly_groups[_kst_hour(j["entry_time"])].append(j)

    hourly_stats = [
        {
            "hour": h,
            "label": _time_block_label(h),
            "count": len(g),
            "win_rate": round(_win_rate(g), 4),
            "avg_pnl": round(_avg_pnl(g), 2),
            "deviation": round(_win_rate(g) - overall_wr, 4),
        }
        for h, g in sorted(hourly_groups.items())
    ]

    # 요일별 (KST)
    weekday_groups: dict[int, list] = defaultdict(list)
    for j in journals:
        weekday_groups[_kst_weekday(j["entry_time"])].append(j)

    weekday_stats = [
        {
            "weekday": w,
            "name": WEEKDAY_NAMES[w],
            "count": len(g),
            "win_rate": round(_win_rate(g), 4),
            "avg_pnl": round(_avg_pnl(g), 2),
            "deviation": round(_win_rate(g) - overall_wr, 4),
        }
        for w, g in sorted(weekday_groups.items())
    ]

    # 코인별 (총 손익 내림차순)
    coin_groups: dict[str, list] = defaultdict(list)
    for j in journals:
        coin_groups[j["coin"]].append(j)

    coin_stats = sorted(
        [
            {
                "coin": coin,
                "count": len(g),
                "win_rate": round(_win_rate(g), 4),
                "avg_pnl": round(_avg_pnl(g), 2),
                "total_pnl": round(sum(j["net_pnl"] for j in g), 2),
                "deviation": round(_win_rate(g) - overall_wr, 4),
            }
            for coin, g in coin_groups.items()
        ],
        key=lambda c: c["total_pnl"],
        reverse=True,
    )

    # 전략별 (승률 내림차순)
    strat_groups: dict[str, list] = defaultdict(list)
    for j in journals:
        strat_groups[j.get("strategy") or "전략 미지정"].append(j)

    strategy_stats = sorted(
        [
            {
                "strategy": strat,
                "count": len(g),
                "win_rate": round(_win_rate(g), 4),
                "avg_pnl": round(_avg_pnl(g), 2),
                "deviation": round(_win_rate(g) - overall_wr, 4),
            }
            for strat, g in strat_groups.items()
        ],
        key=lambda s: s["win_rate"],
        reverse=True,
    )

    # 반복 실수 (reflection_reports.mistakes 빈도 집계)
    mistake_counts = Counter(state["reflection_mistakes"])
    repeated_mistakes = [
        {"text": text, "count": cnt}
        for text, cnt in mistake_counts.most_common(5)
        if cnt >= 2
    ]

    return {
        **state,
        "skip_reason": None,
        "overall_stats": overall_stats,
        "hourly_stats": hourly_stats,
        "weekday_stats": weekday_stats,
        "coin_stats": coin_stats,
        "strategy_stats": strategy_stats,
        "repeated_mistakes": repeated_mistakes,
    }


# ── 노드 2: 행동 패턴 감지 + 리스크 점수 ─────────────────────────────────────

def detect_patterns(state: CoachState) -> CoachState:
    if state.get("skip_reason"):
        return {**state, "emotional_patterns": [], "risk_behavior_score": 0}

    journals = state["journals"]
    sorted_j = sorted(journals, key=lambda j: j["entry_time"])
    overall_wr: float = state["overall_stats"]["win_rate"]

    patterns: list[dict] = []

    # 패턴 1: 복수매매 (2연속 손실 후 레버리지 1.5배 이상 증가)
    revenge_count = 0
    for i in range(2, len(sorted_j)):
        if sorted_j[i - 2]["net_pnl"] < 0 and sorted_j[i - 1]["net_pnl"] < 0:
            if sorted_j[i]["leverage"] >= sorted_j[i - 2]["leverage"] * _REVENGE_LEVERAGE_RATIO:
                revenge_count += 1

    if revenge_count >= 2:
        patterns.append({
            "pattern_type": "revenge_trading",
            "severity": "high",
            "evidence": (
                f"2연속 손실 후 레버리지 {_REVENGE_LEVERAGE_RATIO:.0%} 이상 증가 "
                f"— {revenge_count}회 관찰"
            ),
            "occurrences": revenge_count,
        })

    # 패턴 2: 야간 거래 승률 저하 (KST 00:00~05:59)
    night_j = [j for j in journals if _kst_hour(j["entry_time"]) in NIGHT_HOURS_KST]
    if len(night_j) >= 3:
        night_wr = _win_rate(night_j)
        if night_wr < overall_wr * 0.70:
            deviation_pp = round((overall_wr - night_wr) * 100, 1)
            patterns.append({
                "pattern_type": "night_trading_poor_performance",
                "severity": "medium",
                "evidence": (
                    f"야간 거래 승률 {night_wr:.0%} "
                    f"— 평균 대비 {deviation_pp}%p 낮음 ({len(night_j)}건)"
                ),
                "occurrences": len(night_j),
            })

    # 패턴 3: 조기 손절 반복 (5분 이내 sl_hit)
    quick_stops = [
        j for j in journals
        if j["close_reason"] == "sl_hit" and j["duration_seconds"] < 300
    ]
    if len(quick_stops) >= 3:
        patterns.append({
            "pattern_type": "premature_stop_loss",
            "severity": "medium",
            "evidence": (
                f"진입 후 5분 이내 손절 {len(quick_stops)}건 "
                "— SL이 너무 좁게 설정되는 경향"
            ),
            "occurrences": len(quick_stops),
        })

    # 패턴 4: 특정 코인 집중 손실 (3건 이상, 승률 35% 미만, 누적 손실)
    for cs in state.get("coin_stats", []):
        if cs["count"] >= 3 and cs["win_rate"] < 0.35 and cs["total_pnl"] < 0:
            severity = "high" if cs["total_pnl"] < -200 else "medium"
            patterns.append({
                "pattern_type": "coin_fixation_loss",
                "severity": severity,
                "evidence": (
                    f"{cs['coin']} 거래 승률 {cs['win_rate']:.0%} | "
                    f"누적 손실 {cs['total_pnl']:.1f} USDT ({cs['count']}건)"
                ),
                "occurrences": cs["count"],
            })

    # 리스크 점수 (100점 기준 감점)
    score = 100
    for p in patterns:
        if p["severity"] == "high":
            score -= _SCORE_HIGH_PATTERN
        elif p["severity"] == "medium":
            score -= _SCORE_MEDIUM_PATTERN

    for m in state.get("repeated_mistakes", []):
        if m["count"] >= 3:
            score -= _SCORE_REPEATED_MISTAKE

    if overall_wr < 0.40:
        score -= _SCORE_LOW_WIN_RATE

    if any(p["pattern_type"] == "night_trading_poor_performance" for p in patterns):
        score -= _SCORE_NIGHT_POOR

    return {
        **state,
        "emotional_patterns": patterns,
        "risk_behavior_score": max(0, min(100, score)),
    }


# ── 노드 3: Claude Sonnet 합성 ────────────────────────────────────────────────

async def synthesize(state: CoachState) -> CoachState:
    if state.get("skip_reason"):
        return {
            **state,
            "coach_summary": "",
            "strengths": [],
            "blind_spots": [],
            "weekly_goal": "",
            "model_used": settings.CLAUDE_MODEL,
            "tokens_input": 0,
            "tokens_output": 0,
        }

    prompt = _build_prompt(state)

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=_COACH_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        parsed = _parse_llm_response(response.content[0].text.strip())

        return {
            **state,
            "coach_summary": parsed.get("coach_summary", ""),
            "strengths": parsed.get("strengths", []),
            "blind_spots": parsed.get("blind_spots", []),
            "weekly_goal": parsed.get("weekly_goal", ""),
            "model_used": settings.CLAUDE_MODEL,
            "tokens_input": response.usage.input_tokens,
            "tokens_output": response.usage.output_tokens,
        }
    except Exception as exc:
        logger.warning("TradingCoach synthesis failed: %s", exc)
        return {
            **state,
            "coach_summary": "",
            "strengths": [],
            "blind_spots": [],
            "weekly_goal": "",
            "model_used": settings.CLAUDE_MODEL,
            "tokens_input": 0,
            "tokens_output": 0,
            "errors": state.get("errors", []) + [str(exc)],
        }


# ── 노드 4: 최종 정리 ─────────────────────────────────────────────────────────

def finalize(state: CoachState) -> CoachState:
    return state


# ── 프롬프트 빌더 ─────────────────────────────────────────────────────────────

def _build_prompt(state: CoachState) -> str:
    stats = state["overall_stats"]
    ps = state["period_start"].strftime("%Y-%m-%d")
    pe = state["period_end"].strftime("%Y-%m-%d")

    lines = [
        f"=== 거래 성과 분석 ({ps} ~ {pe}) ===",
        (
            f"총 거래: {stats['total_trades']}건 | 승률: {stats['win_rate']:.1%} | "
            f"총 손익: {stats['total_pnl_usdt']:+.1f} USDT"
        ),
        "",
        "=== 코인별 성과 ===",
    ]

    for cs in state["coin_stats"]:
        dev = f"{'+'if cs['deviation']>=0 else ''}{cs['deviation']*100:.1f}%p"
        lines.append(
            f"{cs['coin']}: 승률 {cs['win_rate']:.0%} | "
            f"총 손익 {cs['total_pnl']:+.1f} USDT | {cs['count']}건, 평균 대비 {dev}"
        )

    lines += ["", "=== 요일별 승률 ==="]
    for ws in state["weekday_stats"]:
        if ws["count"] >= 2:
            dev = f"{'+'if ws['deviation']>=0 else ''}{ws['deviation']*100:.1f}%p"
            lines.append(f"{ws['name']}요일: {ws['win_rate']:.0%} ({ws['count']}건, {dev})")

    lines += ["", "=== 시간대별 승률 ==="]
    for hs in state["hourly_stats"]:
        if hs["count"] >= 2:
            dev = f"{'+'if hs['deviation']>=0 else ''}{hs['deviation']*100:.1f}%p"
            lines.append(
                f"{hs['hour']:02d}시: {hs['win_rate']:.0%} ({hs['count']}건, {dev})"
            )

    if state["strategy_stats"]:
        lines += ["", "=== 전략별 성과 ==="]
        for ss in state["strategy_stats"][:5]:
            dev = f"{'+'if ss['deviation']>=0 else ''}{ss['deviation']*100:.1f}%p"
            lines.append(f"{ss['strategy']}: 승률 {ss['win_rate']:.0%} ({ss['count']}건, {dev})")

    if state["emotional_patterns"]:
        lines += ["", "=== 감지된 행동 패턴 ==="]
        for p in state["emotional_patterns"]:
            lines.append(f"[{p['severity'].upper()}] {p['evidence']}")

    if state["repeated_mistakes"]:
        lines += ["", "=== 반복 실수 (AI 회고 기록) ==="]
        for m in state["repeated_mistakes"]:
            lines.append(f"'{m['text']}' — {m['count']}회 반복")

    lines += ["", f"리스크 행동 점수: {state['risk_behavior_score']}/100"]
    return "\n".join(lines)


def _parse_llm_response(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    logger.warning("TradingCoach: LLM 응답 파싱 실패")
    return {}


# ── 라우팅 ────────────────────────────────────────────────────────────────────

def _route_after_aggregate(state: CoachState) -> str:
    return "finalize" if state.get("skip_reason") else "detect_patterns"


# ── 그래프 ────────────────────────────────────────────────────────────────────

def _build_graph() -> Any:
    graph = StateGraph(CoachState)
    graph.add_node("aggregate_stats", aggregate_stats)
    graph.add_node("detect_patterns", detect_patterns)
    graph.add_node("synthesize",      synthesize)
    graph.add_node("finalize",        finalize)

    graph.set_entry_point("aggregate_stats")
    graph.add_conditional_edges(
        "aggregate_stats",
        _route_after_aggregate,
        {"detect_patterns": "detect_patterns", "finalize": "finalize"},
    )
    graph.add_edge("detect_patterns", "synthesize")
    graph.add_edge("synthesize",      "finalize")
    graph.add_edge("finalize",        END)

    return graph.compile()


_graph = _build_graph()


# ── 공개 API ──────────────────────────────────────────────────────────────────

async def run_coaching(inp: CoachInput) -> CoachResult:
    """TradingCoach 에이전트 실행. CoachingService에서 호출한다."""
    initial_state: CoachState = {
        "user_id": inp.user_id,
        "period_start": inp.period_start,
        "period_end": inp.period_end,
        "journals": inp.journals,
        "reflection_mistakes": inp.reflection_mistakes,
        "overall_stats": {},
        "hourly_stats": [],
        "weekday_stats": [],
        "coin_stats": [],
        "strategy_stats": [],
        "repeated_mistakes": [],
        "emotional_patterns": [],
        "risk_behavior_score": 0,
        "coach_summary": "",
        "strengths": [],
        "blind_spots": [],
        "weekly_goal": "",
        "skip_reason": None,
        "model_used": settings.CLAUDE_MODEL,
        "tokens_input": 0,
        "tokens_output": 0,
        "errors": [],
    }

    final = await _graph.ainvoke(initial_state)

    return CoachResult(
        overall_stats=final["overall_stats"],
        hourly_stats=[HourStat(**h) for h in final["hourly_stats"]],
        weekday_stats=[WeekdayStat(**w) for w in final["weekday_stats"]],
        coin_stats=[CoinStat(**c) for c in final["coin_stats"]],
        strategy_stats=[StrategyStat(**s) for s in final["strategy_stats"]],
        repeated_mistakes=[RepeatedMistake(**m) for m in final["repeated_mistakes"]],
        emotional_patterns=[EmotionalPattern(**p) for p in final["emotional_patterns"]],
        risk_behavior_score=final["risk_behavior_score"],
        coach_summary=final["coach_summary"],
        strengths=final["strengths"],
        blind_spots=final["blind_spots"],
        weekly_goal=final["weekly_goal"],
        skip_reason=final["skip_reason"],
        model_used=final["model_used"],
        tokens_input=final["tokens_input"],
        tokens_output=final["tokens_output"],
    )
