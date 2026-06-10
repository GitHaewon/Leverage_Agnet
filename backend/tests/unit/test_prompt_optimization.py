"""
prompt.py / agent.py 최적화 검증 테스트.

검증 항목:
  1. 뉴스 3건 상한 적용
  2. Indicator 포맷: 중괄호 없음, space-separated, 소수 3자리
  3. _estimate_cost_usd: 모델별 단가, prefix match 우선순위
  4. _log_openai_call: logger.info 호출 형식
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from agents.analyst.prompt import _format_indicators, _format_news, build_user_prompt
from agents.analyst.agent import _estimate_cost_usd, _log_openai_call
from agents.analyst.models import MarketContext, StrategyContext, TechnicalContext


# ── 1. 뉴스 3건 상한 ─────────────────────────────────────────────────────────────

class TestFormatNews:
    def _make_items(self, n: int) -> list[dict]:
        return [{"sentiment": "positive", "headline": f"headline {i}", "source": "src"} for i in range(n)]

    def test_5_items_returns_3(self):
        result = _format_news(self._make_items(5))
        assert result.count("[POSITIVE]") == 3

    def test_3_items_returns_3(self):
        result = _format_news(self._make_items(3))
        assert result.count("[POSITIVE]") == 3

    def test_2_items_returns_2(self):
        result = _format_news(self._make_items(2))
        assert result.count("[POSITIVE]") == 2

    def test_empty_returns_placeholder(self):
        assert _format_news([]) == "  (no recent news)"


# ── 2. Indicator 포맷 ─────────────────────────────────────────────────────────────

class TestFormatIndicators:
    def test_nested_dict_no_braces(self):
        result = _format_indicators({"macd": {"signal": 0.005, "histogram": 0.003}})
        assert "{" not in result
        assert "}" not in result

    def test_nested_dict_space_separated(self):
        result = _format_indicators({"macd": {"signal": 0.005, "histogram": 0.003}})
        # 쉼표 없이 공백으로 구분
        assert ", " not in result
        assert "signal=0.005 histogram=0.003" in result

    def test_float_value_3_decimal_places(self):
        result = _format_indicators({"rsi": 42.3})
        assert "42.300" in result

    def test_nested_float_3_decimal_places(self):
        result = _format_indicators({"bb": {"upper": 70000.0, "lower": 64000.0}})
        assert "upper=70000.000" in result
        assert "lower=64000.000" in result

    def test_non_float_value_unchanged(self):
        result = _format_indicators({"volume": {"trend": "bullish"}})
        assert "trend=bullish" in result

    def test_empty_returns_placeholder(self):
        assert _format_indicators({}) == "  (indicators unavailable)"


# ── 3. 비용 계산 ─────────────────────────────────────────────────────────────────

class TestEstimateCost:
    def test_gpt5_mini_exact(self):
        cost = _estimate_cost_usd("gpt-5-mini", 1_000_000, 1_000_000)
        # in: $0.50, out: $2.00 → total $2.50
        assert abs(cost - 2.50) < 0.001

    def test_gpt5_mini_with_date_suffix(self):
        # gpt-5-mini-2025-08-07 → base = gpt-5-mini
        cost = _estimate_cost_usd("gpt-5-mini-2025-08-07", 1_000_000, 0)
        assert abs(cost - 0.50) < 0.001

    def test_gpt5_not_matched_as_gpt5_mini(self):
        # gpt-5 (not mini) → $2.50/1M input
        cost = _estimate_cost_usd("gpt-5", 1_000_000, 0)
        assert abs(cost - 2.50) < 0.001

    def test_unknown_model_returns_zero(self):
        assert _estimate_cost_usd("unknown-model-xyz", 1000, 1000) == 0.0

    def test_zero_tokens_returns_zero(self):
        assert _estimate_cost_usd("gpt-5-mini", 0, 0) == 0.0

    def test_gpt4o_mini(self):
        cost = _estimate_cost_usd("gpt-4o-mini", 1_000_000, 0)
        assert abs(cost - 0.15) < 0.001


# ── 4. 로그 형식 ─────────────────────────────────────────────────────────────────

class TestLogOpenAICall:
    def test_log_contains_required_fields(self, caplog):
        with caplog.at_level(logging.INFO, logger="agents.analyst.agent"):
            _log_openai_call("gpt-5-mini-2025-08-07", 500, 700, 8500.0)

        assert len(caplog.records) == 1
        msg = caplog.records[0].message
        assert "model=gpt-5-mini-2025-08-07" in msg
        assert "in_tokens=500" in msg
        assert "out_tokens=700" in msg
        assert "total_tokens=1200" in msg
        assert "cost_usd=" in msg
        assert "latency_ms=8500" in msg

    def test_log_cost_value_correct(self, caplog):
        # 500 in + 700 out with gpt-5-mini: cost = 500/1M*0.5 + 700/1M*2.0 = $0.00165
        with caplog.at_level(logging.INFO, logger="agents.analyst.agent"):
            _log_openai_call("gpt-5-mini", 500, 700, 1000.0)
        msg = caplog.records[0].message
        assert "$0.001650" in msg or "cost_usd=$0.00165" in msg


# ── 5. build_user_prompt 통합 — 뉴스 상한 반영 확인 ─────────────────────────────

class TestBuildUserPromptNewsLimit:
    def test_5_news_in_context_produces_3_in_prompt(self):
        market = MarketContext(coin="BTC", symbol="BTCUSDT", current_price=67500.0)
        technical = TechnicalContext(
            tech_score=0.5,
            timeframe_scores={"1d": 0.5},
            indicators={},
            signals_fired=[],
            support_levels=[],
            resistance_levels=[],
        )
        strategy = StrategyContext(
            news_items=[
                {"sentiment": "positive", "headline": f"news {i}", "source": "src"}
                for i in range(5)
            ]
        )
        prompt = build_user_prompt(market, technical, strategy)
        assert prompt.count("[POSITIVE]") == 3
