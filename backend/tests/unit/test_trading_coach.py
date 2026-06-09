"""
TradingCoach 에이전트 단위 테스트.

Claude API와 DB를 Mock 처리한다.
검증 대상:
  - aggregate_stats: 시간대별·요일별·코인별·전략별·반복실수 집계
  - detect_patterns: 복수매매·야간거래·조기손절·코인집중손실 감지
  - detect_patterns: 리스크 점수 계산
  - _parse_llm_response: JSON 파싱 및 마크다운 코드블록 처리
  - _build_prompt: 프롬프트 구성 검증
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.agents.trading_coach import (
    CoachInput,
    CoachState,
    _build_prompt,
    _parse_llm_response,
    aggregate_stats,
    detect_patterns,
)

KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc


# ── 픽스처 헬퍼 ───────────────────────────────────────────────────────────────

def _dt(hour_kst: int, weekday_offset: int = 0) -> datetime:
    """KST 기준 날짜/시간 → UTC datetime (tzinfo 포함)."""
    # 2026-06-09 (월요일) KST 기준
    base = datetime(2026, 6, 9, hour_kst, 0, tzinfo=KST)
    from datetime import timedelta
    return (base + timedelta(days=weekday_offset)).astimezone(UTC)


def _journal(
    *,
    coin: str = "BTC",
    direction: str = "LONG",
    net_pnl: float = 100.0,
    hour_kst: int = 10,
    weekday_offset: int = 0,
    duration_seconds: int = 7200,
    close_reason: str = "tp_hit",
    strategy: str | None = "RSI_EMA",
    leverage: int = 5,
    pnl_percentage: float = 5.0,
) -> dict:
    return {
        "coin": coin,
        "direction": direction,
        "net_pnl": net_pnl,
        "entry_time": _dt(hour_kst, weekday_offset),
        "duration_seconds": duration_seconds,
        "close_reason": close_reason,
        "strategy": strategy,
        "leverage": leverage,
        "pnl_percentage": pnl_percentage,
    }


def _base_state(**overrides) -> CoachState:
    defaults: CoachState = {
        "user_id": "test-user",
        "period_start": _dt(0, -28),
        "period_end": _dt(0),
        "journals": [],
        "reflection_mistakes": [],
        "overall_stats": {},
        "hourly_stats": [],
        "weekday_stats": [],
        "coin_stats": [],
        "strategy_stats": [],
        "repeated_mistakes": [],
        "emotional_patterns": [],
        "risk_behavior_score": 100,
        "coach_summary": "",
        "strengths": [],
        "blind_spots": [],
        "weekly_goal": "",
        "skip_reason": None,
        "model_used": "claude-sonnet-4-6",
        "tokens_input": 0,
        "tokens_output": 0,
        "errors": [],
    }
    return {**defaults, **overrides}  # type: ignore[return-value]


# ── TestAggregateStats ────────────────────────────────────────────────────────

class TestAggregateStats:

    def test_insufficient_trades_sets_skip_reason(self) -> None:
        state = _base_state(journals=[_journal()] * 4)  # 4건 < 5건 최소
        result = aggregate_stats(state)
        assert result["skip_reason"] is not None
        assert "4건" in result["skip_reason"]
        assert result["overall_stats"] == {}

    def test_sufficient_trades_computes_overall_stats(self) -> None:
        journals = [_journal(net_pnl=100)] * 3 + [_journal(net_pnl=-50)] * 2
        state = _base_state(journals=journals)
        result = aggregate_stats(state)

        assert result["skip_reason"] is None
        stats = result["overall_stats"]
        assert stats["total_trades"] == 5
        assert stats["win_count"] == 3
        assert stats["loss_count"] == 2
        assert stats["win_rate"] == pytest.approx(0.6, abs=1e-4)
        assert stats["total_pnl_usdt"] == pytest.approx(200.0)

    def test_hourly_stats_grouped_by_kst_hour(self) -> None:
        journals = [
            _journal(hour_kst=2, net_pnl=100),   # 새벽
            _journal(hour_kst=3, net_pnl=-50),   # 새벽
            _journal(hour_kst=14, net_pnl=80),   # 오후
            _journal(hour_kst=15, net_pnl=90),   # 오후
            _journal(hour_kst=15, net_pnl=-30),  # 오후
        ]
        state = _base_state(journals=journals)
        result = aggregate_stats(state)

        hours = {h["hour"]: h for h in result["hourly_stats"]}
        assert 2 in hours
        assert 3 in hours
        assert 14 in hours
        assert 15 in hours

    def test_hourly_stats_label_correct(self) -> None:
        journals = [_journal(hour_kst=3)] * 5
        state = _base_state(journals=journals)
        result = aggregate_stats(state)

        h3 = next(h for h in result["hourly_stats"] if h["hour"] == 3)
        assert h3["label"] == "새벽(00-05시)"

    def test_weekday_stats_grouped_by_kst_weekday(self) -> None:
        # 2026-06-09 = 월요일 (weekday=0)
        journals = [
            _journal(weekday_offset=0, net_pnl=100),   # 월
            _journal(weekday_offset=0, net_pnl=80),    # 월
            _journal(weekday_offset=1, net_pnl=-50),   # 화
            _journal(weekday_offset=2, net_pnl=60),    # 수
            _journal(weekday_offset=2, net_pnl=40),    # 수
        ]
        state = _base_state(journals=journals)
        result = aggregate_stats(state)

        weekdays = {w["weekday"]: w for w in result["weekday_stats"]}
        assert 0 in weekdays  # 월
        assert weekdays[0]["name"] == "월"
        assert weekdays[0]["count"] == 2
        assert weekdays[0]["win_rate"] == pytest.approx(1.0)

    def test_coin_stats_sorted_by_total_pnl_desc(self) -> None:
        journals = [
            _journal(coin="BTC", net_pnl=200),
            _journal(coin="BTC", net_pnl=100),
            _journal(coin="ETH", net_pnl=-80),
            _journal(coin="ETH", net_pnl=-60),
            _journal(coin="SOL", net_pnl=10),
        ]
        state = _base_state(journals=journals)
        result = aggregate_stats(state)

        coins = [c["coin"] for c in result["coin_stats"]]
        assert coins[0] == "BTC"
        assert coins[-1] == "ETH"

    def test_coin_stats_deviation_vs_overall(self) -> None:
        journals = [
            _journal(coin="BTC", net_pnl=100),
            _journal(coin="BTC", net_pnl=100),
            _journal(coin="ETH", net_pnl=-50),
            _journal(coin="ETH", net_pnl=-50),
            _journal(coin="SOL", net_pnl=100),
        ]
        state = _base_state(journals=journals)
        result = aggregate_stats(state)

        btc = next(c for c in result["coin_stats"] if c["coin"] == "BTC")
        eth = next(c for c in result["coin_stats"] if c["coin"] == "ETH")
        assert btc["deviation"] > 0
        assert eth["deviation"] < 0

    def test_strategy_stats_sorted_by_win_rate_desc(self) -> None:
        journals = [
            _journal(strategy="RSI_EMA", net_pnl=100),
            _journal(strategy="RSI_EMA", net_pnl=100),
            _journal(strategy="MACD",    net_pnl=-50),
            _journal(strategy="MACD",    net_pnl=-50),
            _journal(strategy="MACD",    net_pnl=-30),
        ]
        state = _base_state(journals=journals)
        result = aggregate_stats(state)

        strats = [s["strategy"] for s in result["strategy_stats"]]
        assert strats[0] == "RSI_EMA"   # 승률 100%
        assert strats[-1] == "MACD"     # 승률 0%

    def test_none_strategy_becomes_미지정(self) -> None:
        journals = [_journal(strategy=None)] * 5
        state = _base_state(journals=journals)
        result = aggregate_stats(state)

        strats = [s["strategy"] for s in result["strategy_stats"]]
        assert "전략 미지정" in strats

    def test_repeated_mistakes_counted_and_filtered_by_min2(self) -> None:
        mistakes = ["손절 너무 빠름"] * 3 + ["레버리지 과다"] * 2 + ["시간외 거래"] * 1
        state = _base_state(
            journals=[_journal()] * 5,
            reflection_mistakes=mistakes,
        )
        result = aggregate_stats(state)

        texts = [m["text"] for m in result["repeated_mistakes"]]
        counts = {m["text"]: m["count"] for m in result["repeated_mistakes"]}

        assert "손절 너무 빠름" in texts
        assert "레버리지 과다" in texts
        assert "시간외 거래" not in texts   # count=1 → 제외
        assert counts["손절 너무 빠름"] == 3

    def test_win_rate_deviation_in_hourly_stats(self) -> None:
        # 전체 승률 0.6 (3승2패), 특정 시간대 0승
        journals = [
            _journal(hour_kst=2, net_pnl=-100),
            _journal(hour_kst=2, net_pnl=-100),
            _journal(hour_kst=10, net_pnl=100),
            _journal(hour_kst=10, net_pnl=100),
            _journal(hour_kst=10, net_pnl=100),
        ]
        state = _base_state(journals=journals)
        result = aggregate_stats(state)

        h2 = next(h for h in result["hourly_stats"] if h["hour"] == 2)
        assert h2["deviation"] < 0   # 전체 대비 낮음


# ── TestDetectPatterns ────────────────────────────────────────────────────────

class TestDetectPatterns:

    def _run(self, state: CoachState) -> CoachState:
        return detect_patterns(aggregate_stats(state))

    def test_skip_reason_bypasses_detection(self) -> None:
        state = _base_state(journals=[_journal()] * 2, skip_reason="데이터 부족")
        result = detect_patterns(state)
        assert result["emotional_patterns"] == []
        assert result["risk_behavior_score"] == 0

    def test_revenge_trading_detected(self) -> None:
        # 2연속 손실 후 레버리지 2배 → 복수매매
        journals = [
            _journal(net_pnl=-100, leverage=5),
            _journal(net_pnl=-80,  leverage=5),
            _journal(net_pnl=100,  leverage=10),  # 5x → 10x (2배 이상)
            _journal(net_pnl=-100, leverage=5),
            _journal(net_pnl=-80,  leverage=5),
            _journal(net_pnl=50,   leverage=10),  # 두 번째 복수매매
        ]
        state = _base_state(journals=journals)
        result = self._run(state)

        types = [p["pattern_type"] for p in result["emotional_patterns"]]
        assert "revenge_trading" in types

        p = next(p for p in result["emotional_patterns"] if p["pattern_type"] == "revenge_trading")
        assert p["severity"] == "high"

    def test_revenge_trading_not_detected_with_normal_leverage(self) -> None:
        # 2연속 손실 후 레버리지 소폭 증가 (1.5배 미만)
        journals = [
            _journal(net_pnl=-100, leverage=5),
            _journal(net_pnl=-80,  leverage=5),
            _journal(net_pnl=100,  leverage=6),   # 1.2배 → 미감지
            _journal(net_pnl=-100, leverage=5),
            _journal(net_pnl=-80,  leverage=5),
            _journal(net_pnl=50,   leverage=6),
        ]
        state = _base_state(journals=journals)
        result = self._run(state)

        types = [p["pattern_type"] for p in result["emotional_patterns"]]
        assert "revenge_trading" not in types

    def test_night_trading_poor_performance_detected(self) -> None:
        # 야간(02시 KST) 3건 모두 손실 vs 낮 2건 승리 → 야간 승률 0% < 평균 40%*0.7
        journals = [
            _journal(hour_kst=2, net_pnl=-100),
            _journal(hour_kst=3, net_pnl=-80),
            _journal(hour_kst=4, net_pnl=-60),
            _journal(hour_kst=10, net_pnl=200),
            _journal(hour_kst=14, net_pnl=150),
        ]
        state = _base_state(journals=journals)
        result = self._run(state)

        types = [p["pattern_type"] for p in result["emotional_patterns"]]
        assert "night_trading_poor_performance" in types

    def test_night_trading_not_detected_if_fewer_than_3_night_trades(self) -> None:
        journals = [
            _journal(hour_kst=2, net_pnl=-100),
            _journal(hour_kst=3, net_pnl=-80),
            _journal(hour_kst=10, net_pnl=200),
            _journal(hour_kst=14, net_pnl=150),
            _journal(hour_kst=15, net_pnl=120),
        ]
        state = _base_state(journals=journals)
        result = self._run(state)

        types = [p["pattern_type"] for p in result["emotional_patterns"]]
        assert "night_trading_poor_performance" not in types

    def test_premature_stop_loss_detected(self) -> None:
        journals = [
            _journal(close_reason="sl_hit", duration_seconds=100),
            _journal(close_reason="sl_hit", duration_seconds=200),
            _journal(close_reason="sl_hit", duration_seconds=250),
            _journal(close_reason="tp_hit", duration_seconds=7200),
            _journal(close_reason="tp_hit", duration_seconds=5400),
        ]
        state = _base_state(journals=journals)
        result = self._run(state)

        types = [p["pattern_type"] for p in result["emotional_patterns"]]
        assert "premature_stop_loss" in types

    def test_premature_stop_loss_not_detected_below_threshold(self) -> None:
        journals = [
            _journal(close_reason="sl_hit", duration_seconds=100),
            _journal(close_reason="sl_hit", duration_seconds=200),
            _journal(close_reason="tp_hit", duration_seconds=7200),
            _journal(close_reason="tp_hit", duration_seconds=5400),
            _journal(close_reason="tp_hit", duration_seconds=3600),
        ]
        state = _base_state(journals=journals)
        result = self._run(state)

        types = [p["pattern_type"] for p in result["emotional_patterns"]]
        assert "premature_stop_loss" not in types

    def test_coin_fixation_loss_detected(self) -> None:
        journals = [
            _journal(coin="SOL", net_pnl=-100),
            _journal(coin="SOL", net_pnl=-80),
            _journal(coin="SOL", net_pnl=-90),
            _journal(coin="BTC", net_pnl=200),
            _journal(coin="BTC", net_pnl=150),
        ]
        state = _base_state(journals=journals)
        result = self._run(state)

        types = [p["pattern_type"] for p in result["emotional_patterns"]]
        assert "coin_fixation_loss" in types

    def test_risk_score_deducted_for_high_pattern(self) -> None:
        # 복수매매(high) → -15점
        journals = [
            _journal(net_pnl=-100, leverage=5),
            _journal(net_pnl=-80,  leverage=5),
            _journal(net_pnl=100,  leverage=10),
            _journal(net_pnl=-100, leverage=5),
            _journal(net_pnl=-80,  leverage=5),
            _journal(net_pnl=50,   leverage=10),
        ]
        state = _base_state(journals=journals)
        result = self._run(state)

        assert result["risk_behavior_score"] <= 85  # 100 - 15

    def test_risk_score_minimum_is_zero(self) -> None:
        # 다수의 패턴 → 점수가 0 아래로 내려가지 않아야 한다
        many_losses = [_journal(net_pnl=-100, leverage=5 + i, close_reason="sl_hit", duration_seconds=60 + i) for i in range(20)]
        state = _base_state(journals=many_losses)
        result = self._run(state)

        assert result["risk_behavior_score"] >= 0

    def test_no_patterns_keeps_perfect_risk_score(self) -> None:
        journals = [_journal(net_pnl=100, leverage=5, close_reason="tp_hit", duration_seconds=7200)] * 10
        state = _base_state(journals=journals)
        result = self._run(state)

        assert result["risk_behavior_score"] == 100
        assert result["emotional_patterns"] == []


# ── TestParseLlmResponse ──────────────────────────────────────────────────────

class TestParseLlmResponse:

    def test_valid_json(self) -> None:
        raw = json.dumps({
            "coach_summary": "BTC 거래 우수",
            "strengths": ["강점1"],
            "blind_spots": ["개선1"],
            "weekly_goal": "목표",
        })
        result = _parse_llm_response(raw)
        assert result["coach_summary"] == "BTC 거래 우수"

    def test_json_with_markdown_codeblock(self) -> None:
        raw = '```json\n{"coach_summary": "야간 거래 주의", "strengths": []}\n```'
        result = _parse_llm_response(raw)
        assert result["coach_summary"] == "야간 거래 주의"

    def test_json_embedded_in_text(self) -> None:
        raw = '분석 결과입니다.\n{"coach_summary": "테스트", "strengths": [], "blind_spots": [], "weekly_goal": "목표"}\n이상입니다.'
        result = _parse_llm_response(raw)
        assert result["coach_summary"] == "테스트"

    def test_malformed_json_returns_empty_dict(self) -> None:
        result = _parse_llm_response("이것은 JSON이 아닙니다")
        assert result == {}

    def test_empty_string_returns_empty_dict(self) -> None:
        result = _parse_llm_response("")
        assert result == {}


# ── TestBuildPrompt ───────────────────────────────────────────────────────────

class TestBuildPrompt:

    def _make_state_with_data(self) -> CoachState:
        journals = [
            _journal(coin="BTC", net_pnl=200, hour_kst=10, weekday_offset=0),
            _journal(coin="BTC", net_pnl=150, hour_kst=11, weekday_offset=1),
            _journal(coin="ETH", net_pnl=-80, hour_kst=2,  weekday_offset=2),
            _journal(coin="ETH", net_pnl=-60, hour_kst=3,  weekday_offset=3),
            _journal(coin="SOL", net_pnl=50,  hour_kst=14, weekday_offset=4),
        ]
        state = _base_state(journals=journals)
        state = aggregate_stats(state)
        state = detect_patterns(state)
        return state

    def test_prompt_contains_period_dates(self) -> None:
        state = self._make_state_with_data()
        prompt = _build_prompt(state)
        assert "2026" in prompt

    def test_prompt_contains_coin_stats(self) -> None:
        state = self._make_state_with_data()
        prompt = _build_prompt(state)
        assert "BTC" in prompt
        assert "ETH" in prompt

    def test_prompt_contains_weekday_section(self) -> None:
        state = self._make_state_with_data()
        prompt = _build_prompt(state)
        assert "요일별 승률" in prompt

    def test_prompt_contains_hourly_section(self) -> None:
        state = self._make_state_with_data()
        prompt = _build_prompt(state)
        assert "시간대별 승률" in prompt

    def test_prompt_contains_risk_score(self) -> None:
        state = self._make_state_with_data()
        prompt = _build_prompt(state)
        assert "리스크 행동 점수" in prompt

    def test_prompt_contains_emotional_patterns_when_present(self) -> None:
        journals = [
            _journal(net_pnl=-100, leverage=5),
            _journal(net_pnl=-80,  leverage=5),
            _journal(net_pnl=100,  leverage=10),
            _journal(net_pnl=-100, leverage=5),
            _journal(net_pnl=-80,  leverage=5),
            _journal(net_pnl=50,   leverage=10),
        ]
        state = _base_state(journals=journals)
        state = aggregate_stats(state)
        state = detect_patterns(state)
        prompt = _build_prompt(state)
        assert "감지된 행동 패턴" in prompt
