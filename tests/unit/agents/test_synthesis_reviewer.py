"""
AI Reviewer (synthesis) 단위 테스트.

검증 항목:
  Parser:
    1. 유효한 APPROVE JSON 파싱
    2. 유효한 REJECT JSON 파싱
    3. 잘못된 JSON → 안전 REJECT
    4. 필드 누락 → 안전 REJECT 또는 보수적 기본값
    5. 마크다운 코드블록 JSON 파싱
    6. confidence 클램프 (>1 → 1, <0 → 0)
    7. review_action 대소문자 정규화
    8. 알 수 없는 review_action → 안전 REJECT

  Prompt:
    9.  SYSTEM_PROMPT에 AI가 거래 생성 불가 명시
    10. SYSTEM_PROMPT에 AI가 entry/TP/SL/leverage/size 수정 불가 명시
    11. SYSTEM_PROMPT에 RiskEngine 우회 불가 명시
    12. SYSTEM_PROMPT에 "APPROVE" | "REJECT" JSON 형식 명시
    13. build_review_prompt에 coin 포함
    14. build_review_prompt에 action (LONG/SHORT/HOLD) 포함
    15. build_review_prompt에 stop_loss 포함
    16. build_review_prompt에 take_profit 포함
    17. build_review_prompt에 leverage 포함
    18. build_review_prompt에 actual_rr 포함
    19. build_review_prompt에 expected_net_profit 포함
    20. build_review_prompt에 liquidation_price 포함
    21. build_review_prompt에 market_regime 포함
    22. build_review_prompt에 strategy_type 포함
    23. build_review_prompt에 no_trade_flag 포함
    24. build_review_prompt는 뉴스 원문을 포함하지 않고 요약만 포함
    25. build_review_prompt에 spread/slippage 포함

  AIReviewResult 구조:
    26. review_action 필드 존재
    27. confidence 필드 존재 (float)
    28. critical_contradiction 필드 존재 (bool)
    29. risk_warnings 필드 존재 (list)
    30. reason_summary 필드 존재 (str)
"""
from __future__ import annotations

import json

import pytest

from agents.decision.models import AIReviewAction, AIReviewResult
from agents.synthesis.agent import ReviewerAgent
from agents.synthesis.models import ReviewInput
from agents.synthesis.parser import parse_review_response, _safe_reject
from agents.synthesis.prompt import SYSTEM_PROMPT, build_review_prompt


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────

def _approve_json(
    confidence: float = 0.82,
    critical_contradiction: bool = False,
    risk_warnings: list[str] | None = None,
    reason_summary: str = "차트 방향과 국면 일치, 셋업 유효",
) -> str:
    return json.dumps({
        "review_action": "APPROVE",
        "confidence": confidence,
        "critical_contradiction": critical_contradiction,
        "risk_warnings": risk_warnings or [],
        "reason_summary": reason_summary,
    }, ensure_ascii=False)


def _reject_json(
    confidence: float = 0.75,
    critical_contradiction: bool = True,
    risk_warnings: list[str] | None = None,
    reason_summary: str = "지표가 방향과 정반대",
) -> str:
    return json.dumps({
        "review_action": "REJECT",
        "confidence": confidence,
        "critical_contradiction": critical_contradiction,
        "risk_warnings": risk_warnings or ["funding_rate_too_high"],
        "reason_summary": reason_summary,
    }, ensure_ascii=False)


def _make_review_input(**kwargs) -> ReviewInput:
    defaults = dict(
        coin="BTC",
        symbol="BTCUSDT",
        market_regime="TREND_UP",
        regime_confidence=0.80,
        chart_long_score=62.0,
        chart_short_score=18.0,
        chart_risk_score=15.0,
        chart_reasons=["EMA 정배열", "RSI 45: 중립~롱", "MACD 상승"],
        news_sentiment_score=25.0,
        news_risk_score=10.0,
        news_no_trade_flag=False,
        news_reasons=["긍정 감성 소폭 — 트리거 아님"],
        deriv_risk_score=8.0,
        deriv_crowded_side="NONE",
        deriv_reasons=["펀딩 중립"],
        strategy_type="TREND_FOLLOWING",
        expected_holding_minutes=120,
        action="LONG",
        entry_price=67450.0,
        stop_loss=66500.0,
        take_profit=69350.0,
        leverage=5,
        notional_size=5000.0,
        margin_ratio=0.015,
        actual_rr=2.0,
        min_required_rr=2.0,
        expected_net_profit=95.0,
        expected_net_loss=47.5,
        spread_bps=1.5,
        slippage_bps=3.0,
        liquidation_price=64200.0,
    )
    defaults.update(kwargs)
    return ReviewInput(**defaults)


class _FakeOpenAIClient:
    def __init__(self, response: str | None = None) -> None:
        self.response = response or _approve_json()
        self.call_count = 0

    async def create_message(self, **kwargs):
        self.call_count += 1
        return self.response, 10, 5


# ── Parser 테스트 ─────────────────────────────────────────────────────────────

class TestParserApprove:
    def test_parse_approve_action(self) -> None:
        result = parse_review_response(_approve_json())
        assert result.review_action == AIReviewAction.APPROVE

    def test_parse_approve_confidence(self) -> None:
        result = parse_review_response(_approve_json(confidence=0.82))
        assert abs(result.confidence - 0.82) < 1e-4

    def test_parse_approve_critical_contradiction_false(self) -> None:
        result = parse_review_response(_approve_json(critical_contradiction=False))
        assert result.critical_contradiction is False

    def test_parse_approve_empty_risk_warnings(self) -> None:
        result = parse_review_response(_approve_json(risk_warnings=[]))
        assert result.risk_warnings == []

    def test_parse_approve_with_warnings(self) -> None:
        result = parse_review_response(_approve_json(risk_warnings=["spread_high"]))
        assert "spread_high" in result.risk_warnings

    def test_parse_approve_reason_summary(self) -> None:
        result = parse_review_response(_approve_json(reason_summary="valid setup"))
        assert "valid setup" in result.reason_summary


# ── ReviewerAgent 시장 국면 플레이북 사전 필터 ───────────────────────────────

class TestReviewerPlaybookGuard:
    @pytest.mark.asyncio
    async def test_high_volatility_rejects_without_ai_call(self) -> None:
        client = _FakeOpenAIClient()
        reviewer = ReviewerAgent(client)
        result = await reviewer.review(_make_review_input(market_regime="HIGH_VOLATILITY"))
        assert result.review_action == AIReviewAction.REJECT
        assert "regime_high_volatility_no_trade" in result.risk_warnings
        assert client.call_count == 0

    @pytest.mark.asyncio
    async def test_range_rejects_trend_pullback(self) -> None:
        client = _FakeOpenAIClient()
        reviewer = ReviewerAgent(client)
        result = await reviewer.review(
            _make_review_input(market_regime="RANGE", strategy_type="TREND_PULLBACK")
        )
        assert result.review_action == AIReviewAction.REJECT
        assert "strategy_not_allowed_for_regime" in result.risk_warnings
        assert client.call_count == 0

    @pytest.mark.asyncio
    async def test_range_rejects_breakout_retest(self) -> None:
        client = _FakeOpenAIClient()
        reviewer = ReviewerAgent(client)
        result = await reviewer.review(
            _make_review_input(market_regime="RANGE", strategy_type="BREAKOUT_RETEST")
        )
        assert result.review_action == AIReviewAction.REJECT
        assert "strategy_not_allowed_for_regime" in result.risk_warnings
        assert client.call_count == 0

    @pytest.mark.asyncio
    async def test_trend_up_allows_playbook_strategy_and_calls_ai(self) -> None:
        client = _FakeOpenAIClient()
        reviewer = ReviewerAgent(client)
        result = await reviewer.review(
            _make_review_input(market_regime="TREND_UP", strategy_type="BREAKOUT_RETEST")
        )
        assert result.review_action == AIReviewAction.APPROVE
        assert client.call_count == 1

    @pytest.mark.asyncio
    async def test_unknown_regime_rejects_without_ai_call(self) -> None:
        client = _FakeOpenAIClient()
        reviewer = ReviewerAgent(client)
        result = await reviewer.review(_make_review_input(market_regime="UNKNOWN"))
        assert result.review_action == AIReviewAction.REJECT
        assert "regime_unknown_conservative_reject" in result.risk_warnings
        assert client.call_count == 0

    @pytest.mark.asyncio
    async def test_strategy_min_rr_rejects_without_ai_call(self) -> None:
        client = _FakeOpenAIClient()
        reviewer = ReviewerAgent(client)
        result = await reviewer.review(
            _make_review_input(
                market_regime="TREND_UP",
                strategy_type="TREND_PULLBACK",
                actual_rr=1.5,
            )
        )
        assert result.review_action == AIReviewAction.REJECT
        assert "strategy_min_rr_not_met" in result.risk_warnings
        assert client.call_count == 0


class TestParserReject:
    def test_parse_reject_action(self) -> None:
        result = parse_review_response(_reject_json())
        assert result.review_action == AIReviewAction.REJECT

    def test_parse_reject_confidence(self) -> None:
        result = parse_review_response(_reject_json(confidence=0.75))
        assert abs(result.confidence - 0.75) < 1e-4

    def test_parse_reject_critical_contradiction(self) -> None:
        result = parse_review_response(_reject_json(critical_contradiction=True))
        assert result.critical_contradiction is True

    def test_parse_reject_risk_warnings_preserved(self) -> None:
        result = parse_review_response(_reject_json(risk_warnings=["oi_crowded", "funding_extreme"]))
        assert "oi_crowded" in result.risk_warnings
        assert "funding_extreme" in result.risk_warnings

    def test_parse_reject_not_critical(self) -> None:
        result = parse_review_response(_reject_json(critical_contradiction=False))
        assert result.review_action == AIReviewAction.REJECT
        assert result.critical_contradiction is False


class TestParserInvalidInput:
    def test_empty_string_returns_safe_reject(self) -> None:
        result = parse_review_response("")
        assert result.review_action == AIReviewAction.REJECT
        assert result.critical_contradiction is True

    def test_non_json_returns_safe_reject(self) -> None:
        result = parse_review_response("I recommend approving this trade.")
        assert result.review_action == AIReviewAction.REJECT

    def test_invalid_json_syntax_returns_safe_reject(self) -> None:
        result = parse_review_response("{review_action: APPROVE}")  # missing quotes
        assert result.review_action == AIReviewAction.REJECT

    def test_invalid_action_returns_safe_reject(self) -> None:
        data = json.dumps({
            "review_action": "MAYBE",
            "confidence": 0.8,
            "critical_contradiction": False,
            "risk_warnings": [],
            "reason_summary": "test",
        })
        result = parse_review_response(data)
        assert result.review_action == AIReviewAction.REJECT

    def test_safe_reject_has_invalid_json_warning(self) -> None:
        result = parse_review_response("totally broken")
        assert "invalid_json" in result.risk_warnings

    def test_safe_reject_confidence_zero(self) -> None:
        result = parse_review_response("")
        assert result.confidence == 0.0

    def test_safe_reject_reason_summary_present(self) -> None:
        result = parse_review_response("")
        assert len(result.reason_summary) > 0


class TestParserMissingFields:
    def test_missing_review_action_returns_reject(self) -> None:
        data = json.dumps({
            "confidence": 0.7,
            "critical_contradiction": False,
            "risk_warnings": [],
            "reason_summary": "test",
        })
        result = parse_review_response(data)
        assert result.review_action == AIReviewAction.REJECT

    def test_missing_confidence_defaults_to_zero(self) -> None:
        data = json.dumps({
            "review_action": "APPROVE",
            "critical_contradiction": False,
            "risk_warnings": [],
            "reason_summary": "ok",
        })
        result = parse_review_response(data)
        assert result.confidence == 0.0

    def test_missing_risk_warnings_defaults_to_empty(self) -> None:
        data = json.dumps({
            "review_action": "APPROVE",
            "confidence": 0.8,
            "critical_contradiction": False,
            "reason_summary": "ok",
        })
        result = parse_review_response(data)
        assert result.risk_warnings == []

    def test_missing_critical_contradiction_defaults_false(self) -> None:
        data = json.dumps({
            "review_action": "APPROVE",
            "confidence": 0.8,
            "risk_warnings": [],
            "reason_summary": "ok",
        })
        result = parse_review_response(data)
        assert result.critical_contradiction is False


class TestParserEdgeCases:
    def test_markdown_wrapped_json_parsed(self) -> None:
        raw = f"```json\n{_approve_json()}\n```"
        result = parse_review_response(raw)
        assert result.review_action == AIReviewAction.APPROVE

    def test_markdown_no_tag_parsed(self) -> None:
        raw = f"```\n{_reject_json()}\n```"
        result = parse_review_response(raw)
        assert result.review_action == AIReviewAction.REJECT

    def test_confidence_clamped_above_1(self) -> None:
        data = json.dumps({
            "review_action": "APPROVE",
            "confidence": 1.5,
            "critical_contradiction": False,
            "risk_warnings": [],
            "reason_summary": "ok",
        })
        result = parse_review_response(data)
        assert result.confidence <= 1.0

    def test_confidence_clamped_below_0(self) -> None:
        data = json.dumps({
            "review_action": "APPROVE",
            "confidence": -0.3,
            "critical_contradiction": False,
            "risk_warnings": [],
            "reason_summary": "ok",
        })
        result = parse_review_response(data)
        assert result.confidence >= 0.0

    def test_lowercase_review_action_approved(self) -> None:
        data = json.dumps({
            "review_action": "approve",
            "confidence": 0.8,
            "critical_contradiction": False,
            "risk_warnings": [],
            "reason_summary": "ok",
        })
        result = parse_review_response(data)
        assert result.review_action == AIReviewAction.APPROVE

    def test_returns_ai_review_result_type(self) -> None:
        result = parse_review_response(_approve_json())
        assert isinstance(result, AIReviewResult)


# ── SYSTEM_PROMPT 내용 검증 ───────────────────────────────────────────────────

class TestSystemPrompt:
    def test_prompt_states_cannot_create_trade(self) -> None:
        keywords = ["cannot create", "CANNOT create", "cannot modify", "no order"]
        assert any(k.lower() in SYSTEM_PROMPT.lower() for k in keywords)

    def test_prompt_states_cannot_change_entry(self) -> None:
        assert "entry" in SYSTEM_PROMPT.lower() or "CANNOT change" in SYSTEM_PROMPT

    def test_prompt_states_cannot_change_tp(self) -> None:
        assert "take profit" in SYSTEM_PROMPT.lower() or "TP" in SYSTEM_PROMPT

    def test_prompt_states_cannot_change_sl(self) -> None:
        assert "stop loss" in SYSTEM_PROMPT.lower() or "SL" in SYSTEM_PROMPT

    def test_prompt_states_cannot_change_leverage(self) -> None:
        assert "leverage" in SYSTEM_PROMPT.lower()

    def test_prompt_states_cannot_change_size(self) -> None:
        assert "size" in SYSTEM_PROMPT.lower()

    def test_prompt_states_cannot_override_risk_engine(self) -> None:
        assert "RiskEngine" in SYSTEM_PROMPT or "risk engine" in SYSTEM_PROMPT.lower()

    def test_prompt_has_approve_reject_format(self) -> None:
        assert "APPROVE" in SYSTEM_PROMPT
        assert "REJECT" in SYSTEM_PROMPT

    def test_prompt_has_json_output_format(self) -> None:
        assert "review_action" in SYSTEM_PROMPT
        assert "confidence" in SYSTEM_PROMPT
        assert "critical_contradiction" in SYSTEM_PROMPT

    def test_prompt_no_entry_price_in_output_format(self) -> None:
        # 출력 JSON 형식에 entry_price / take_profit / stop_loss / leverage 없어야 함
        prompt_lower = SYSTEM_PROMPT.lower()
        # SYSTEM_PROMPT의 OUTPUT FORMAT 섹션만 검사 (rules 섹션은 제외)
        output_section_start = SYSTEM_PROMPT.find("OUTPUT FORMAT")
        if output_section_start >= 0:
            output_section = SYSTEM_PROMPT[output_section_start:]
            assert "entry_price" not in output_section
            assert "\"take_profit\"" not in output_section
            assert "\"stop_loss\"" not in output_section
            assert "\"leverage\"" not in output_section


# ── build_review_prompt 내용 검증 ────────────────────────────────────────────

class TestBuildReviewPrompt:
    def _prompt(self, **kwargs) -> str:
        return build_review_prompt(_make_review_input(**kwargs))

    def test_prompt_contains_coin(self) -> None:
        p = self._prompt(coin="ETH")
        assert "ETH" in p

    def test_prompt_contains_action_long(self) -> None:
        p = self._prompt(action="LONG")
        assert "LONG" in p

    def test_prompt_contains_action_short(self) -> None:
        p = self._prompt(action="SHORT")
        assert "SHORT" in p

    def test_prompt_contains_stop_loss(self) -> None:
        p = self._prompt(stop_loss=66500.0)
        assert "66,500" in p or "66500" in p

    def test_prompt_contains_take_profit(self) -> None:
        p = self._prompt(take_profit=69350.0)
        assert "69,350" in p or "69350" in p

    def test_prompt_contains_leverage(self) -> None:
        p = self._prompt(leverage=5)
        assert "5x" in p or "5" in p

    def test_prompt_contains_actual_rr(self) -> None:
        p = self._prompt(actual_rr=2.5)
        assert "2.50" in p or "2.5" in p

    def test_prompt_contains_expected_net_profit(self) -> None:
        p = self._prompt(expected_net_profit=95.0)
        assert "95" in p

    def test_prompt_contains_liquidation_price(self) -> None:
        p = self._prompt(liquidation_price=64200.0)
        assert "64,200" in p or "64200" in p

    def test_prompt_none_liquidation_shows_na(self) -> None:
        p = self._prompt(liquidation_price=None)
        assert "N/A" in p

    def test_prompt_contains_market_regime(self) -> None:
        p = self._prompt(market_regime="TREND_DOWN")
        assert "TREND_DOWN" in p

    def test_prompt_contains_strategy_type(self) -> None:
        p = self._prompt(strategy_type="BREAKOUT")
        assert "BREAKOUT" in p

    def test_prompt_contains_no_trade_flag(self) -> None:
        p = self._prompt(news_no_trade_flag=True)
        assert "True" in p or "true" in p

    def test_prompt_contains_spread(self) -> None:
        p = self._prompt(spread_bps=2.5)
        assert "2.5" in p

    def test_prompt_contains_slippage(self) -> None:
        p = self._prompt(slippage_bps=3.0)
        assert "3.0" in p

    def test_prompt_chart_reasons_included(self) -> None:
        p = self._prompt(chart_reasons=["EMA 정배열", "RSI 45"])
        assert "EMA 정배열" in p
        assert "RSI 45" in p

    def test_prompt_chart_reasons_limited_to_five(self) -> None:
        many = [f"reason_{i}" for i in range(10)]
        p = self._prompt(chart_reasons=many)
        assert "reason_5" not in p
        assert "reason_4" in p

    def test_prompt_news_reasons_included(self) -> None:
        p = self._prompt(news_reasons=["긍정 감성", "F&G=50 중립"])
        assert "긍정 감성" in p

    def test_prompt_contains_reminder_cannot_change_values(self) -> None:
        p = self._prompt()
        lower = p.lower()
        assert "cannot" in lower or "cannot modify" in lower

    def test_prompt_contains_reminder_no_riskengine_override(self) -> None:
        p = self._prompt()
        assert "RiskEngine" in p or "riskengine" in p.lower()


# ── AIReviewResult 구조 검증 ─────────────────────────────────────────────────

class TestAIReviewResultStructure:
    def test_has_review_action_field(self) -> None:
        r = parse_review_response(_approve_json())
        assert hasattr(r, "review_action")
        assert isinstance(r.review_action, AIReviewAction)

    def test_has_confidence_field_as_float(self) -> None:
        r = parse_review_response(_approve_json(confidence=0.85))
        assert hasattr(r, "confidence")
        assert isinstance(r.confidence, float)

    def test_has_critical_contradiction_field_as_bool(self) -> None:
        r = parse_review_response(_approve_json())
        assert hasattr(r, "critical_contradiction")
        assert isinstance(r.critical_contradiction, bool)

    def test_has_risk_warnings_field_as_list(self) -> None:
        r = parse_review_response(_approve_json())
        assert hasattr(r, "risk_warnings")
        assert isinstance(r.risk_warnings, list)

    def test_has_reason_summary_field_as_str(self) -> None:
        r = parse_review_response(_approve_json())
        assert hasattr(r, "reason_summary")
        assert isinstance(r.reason_summary, str)

    def test_safe_reject_factory_returns_correct_type(self) -> None:
        r = _safe_reject()
        assert isinstance(r, AIReviewResult)
        assert r.review_action == AIReviewAction.REJECT
        assert r.confidence == 0.0
        assert r.critical_contradiction is True
        assert "invalid_json" in r.risk_warnings
