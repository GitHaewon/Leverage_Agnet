"""
AI Analyst Agent 프롬프트 빌더 테스트.

검증:
  [SYSTEM_PROMPT]
  - ANALYSIS ONLY 명시
  - 주문 권한 없음 명시
  - HOLD 강제 조건 (confidence < 60)
  - JSON 출력 형식 명시

  [compute_composite_score]
  - Tech 40% + Market 35% + Sentiment 25%
  - 모두 0 → 0
  - 모두 1.0 → 1.0
  - 음수 포함

  [build_user_prompt]
  - coin + 현재가 포함
  - tech_score 포함
  - indicators 내용 포함
  - signals_fired 포함
  - support/resistance levels 포함
  - sentiment_score 포함
  - fear_greed_index 포함
  - dominant_sentiment 포함
  - news headline 포함
  - market_score 포함
  - funding_rate 포함
  - whale_activity 포함
  - composite_score 포함
  - strategy=None이면 중립값 사용
  - 뉴스 최대 5개
"""
from __future__ import annotations

from agents.analyst.prompt import SYSTEM_PROMPT, build_user_prompt, compute_composite_score

from tests.unit.agents._analyst_fixtures import (
    make_market,
    make_neutral_strategy,
    make_neutral_technical,
    make_strategy,
    make_technical,
)


# ── SYSTEM_PROMPT 내용 검증 ───────────────────────────────────────────────────────

def test_system_prompt_analysis_only():
    assert "ANALYSIS ONLY" in SYSTEM_PROMPT


def test_system_prompt_no_order_authority():
    assert "order" in SYSTEM_PROMPT.lower() or "authority" in SYSTEM_PROMPT.lower()


def test_system_prompt_hold_rule():
    assert "60" in SYSTEM_PROMPT


def test_system_prompt_json_format():
    assert "decision" in SYSTEM_PROMPT
    assert "confidence" in SYSTEM_PROMPT
    assert "risk_level" in SYSTEM_PROMPT


def test_system_prompt_stop_loss_mandatory():
    assert "stop_loss" in SYSTEM_PROMPT


def test_system_prompt_rr_ratio_rule():
    assert "rr_ratio" in SYSTEM_PROMPT or "R:R" in SYSTEM_PROMPT or "2.0" in SYSTEM_PROMPT


# ── compute_composite_score ───────────────────────────────────────────────────────

def test_composite_score_all_zero():
    tech = make_neutral_technical()
    strategy = make_neutral_strategy()
    assert compute_composite_score(tech, strategy) == 0.0


def test_composite_score_all_one():
    tech = make_technical(tech_score=1.0)
    strategy = make_strategy(market_score=1.0, sentiment_score=1.0)
    assert abs(compute_composite_score(tech, strategy) - 1.0) < 1e-9


def test_composite_score_weights():
    """Tech 40% + Market 35% + Sentiment 25% 검증."""
    tech = make_technical(tech_score=1.0)
    strategy = make_strategy(market_score=0.0, sentiment_score=0.0)
    assert abs(compute_composite_score(tech, strategy) - 0.40) < 1e-9


def test_composite_score_market_weight():
    tech = make_technical(tech_score=0.0)
    strategy = make_strategy(market_score=1.0, sentiment_score=0.0)
    assert abs(compute_composite_score(tech, strategy) - 0.35) < 1e-9


def test_composite_score_sentiment_weight():
    tech = make_technical(tech_score=0.0)
    strategy = make_strategy(market_score=0.0, sentiment_score=1.0)
    assert abs(compute_composite_score(tech, strategy) - 0.25) < 1e-9


def test_composite_score_negative_values():
    tech = make_technical(tech_score=-1.0)
    strategy = make_strategy(market_score=-1.0, sentiment_score=-1.0)
    assert compute_composite_score(tech, strategy) == -1.0


def test_composite_score_mixed():
    """mixed 값 수치 계산 검증."""
    tech = make_technical(tech_score=0.72)
    strategy = make_strategy(market_score=0.58, sentiment_score=-0.31)
    score = compute_composite_score(tech, strategy)
    expected = 0.72 * 0.40 + 0.58 * 0.35 + (-0.31) * 0.25
    assert abs(score - expected) < 1e-9


# ── build_user_prompt ─────────────────────────────────────────────────────────────

def test_prompt_contains_coin():
    prompt = build_user_prompt(make_market(coin="ETH"), make_technical(), make_strategy())
    assert "ETH" in prompt


def test_prompt_contains_current_price():
    prompt = build_user_prompt(make_market(current_price=67450.0), make_technical(), make_strategy())
    assert "67,450" in prompt


def test_prompt_contains_tech_score():
    tech = make_technical(tech_score=0.72)
    prompt = build_user_prompt(make_market(), tech, make_strategy())
    assert "+0.72" in prompt or "0.72" in prompt


def test_prompt_contains_indicator_key():
    tech = make_technical(indicators={"rsi_1h": 42.3})
    prompt = build_user_prompt(make_market(), tech, make_strategy())
    assert "rsi_1h" in prompt


def test_prompt_contains_signal():
    tech = make_technical(signals_fired=["rsi_oversold_4h"])
    prompt = build_user_prompt(make_market(), tech, make_strategy())
    assert "rsi_oversold_4h" in prompt


def test_prompt_contains_support_level():
    tech = make_technical(support_levels=[66800.0])
    prompt = build_user_prompt(make_market(), tech, make_strategy())
    assert "66,800" in prompt


def test_prompt_contains_resistance_level():
    tech = make_technical(resistance_levels=[69000.0])
    prompt = build_user_prompt(make_market(), tech, make_strategy())
    assert "69,000" in prompt


def test_prompt_contains_sentiment_score():
    strategy = make_strategy(sentiment_score=-0.31)
    prompt = build_user_prompt(make_market(), make_technical(), strategy)
    assert "-0.31" in prompt


def test_prompt_contains_fear_greed_index():
    strategy = make_strategy(fear_greed_index=42, fear_greed_label="Fear")
    prompt = build_user_prompt(make_market(), make_technical(), strategy)
    assert "42" in prompt
    assert "Fear" in prompt


def test_prompt_contains_dominant_sentiment():
    strategy = make_strategy(dominant_sentiment="negative")
    prompt = build_user_prompt(make_market(), make_technical(), strategy)
    assert "negative" in prompt


def test_prompt_contains_news_headline():
    strategy = make_strategy(news_items=[{"headline": "BTC 상승 예상", "source": "CoinDesk", "sentiment": "positive"}])
    prompt = build_user_prompt(make_market(), make_technical(), strategy)
    assert "BTC 상승 예상" in prompt


def test_prompt_contains_market_score():
    strategy = make_strategy(market_score=0.58)
    prompt = build_user_prompt(make_market(), make_technical(), strategy)
    assert "+0.58" in prompt or "0.58" in prompt


def test_prompt_contains_funding_rate():
    strategy = make_strategy(funding_rate=-0.0002)
    prompt = build_user_prompt(make_market(), make_technical(), strategy)
    assert "-0.0200%" in prompt or "0.0200" in prompt


def test_prompt_contains_whale_activity():
    strategy = make_strategy(whale_activity="accumulating")
    prompt = build_user_prompt(make_market(), make_technical(), strategy)
    assert "accumulating" in prompt


def test_prompt_contains_composite_score():
    prompt = build_user_prompt(make_market(), make_technical(), make_strategy())
    assert "Weighted score" in prompt


def test_prompt_news_limited_to_five():
    many_news = [
        {"headline": f"뉴스 {i}", "source": "src", "sentiment": "neutral"}
        for i in range(10)
    ]
    strategy = make_strategy(news_items=many_news)
    prompt = build_user_prompt(make_market(), make_technical(), strategy)
    assert prompt.count("뉴스 5") == 0  # 뉴스 5~9는 미포함


def test_prompt_analysis_only_reminder():
    prompt = build_user_prompt(make_market(), make_technical(), make_strategy())
    assert "ANALYSIS ONLY" in prompt


def test_prompt_no_news_shows_placeholder():
    strategy = make_strategy(news_items=[])
    prompt = build_user_prompt(make_market(), make_technical(), strategy)
    assert "no recent news" in prompt
