"""
Synthesis Agent — Claude Sonnet 프롬프트.

AGENTS.md §5.4 기준.
"""
from __future__ import annotations

from agents.synthesis.models import SynthesisInput

SYSTEM_PROMPT = """
You are a professional cryptocurrency futures trading analyst with 10+ years of experience.
Your task is to synthesize multi-dimensional market data into a precise trading signal.

RULES (non-negotiable):
1. Direction must be LONG, SHORT, or HOLD only
2. If confidence < 0.60, output HOLD regardless of your analysis
3. Stop Loss is MANDATORY — never output a signal without stop_loss
4. Minimum R:R ratio is 2.0 — if you cannot find a valid R:R, output HOLD
5. Reasons must reference SPECIFIC indicator values (e.g., "RSI(14) = 42.3")
6. Entry price should be current market price or next clear support/resistance
7. Leverage must be conservative (5x for 60-70% confidence, 10x max for 90%+)

OUTPUT FORMAT (strict JSON, no markdown, no explanation outside JSON):
{
  "direction": "LONG|SHORT|HOLD",
  "confidence": 0.00,
  "entry_price": 0.0,
  "take_profit": 0.0,
  "stop_loss": 0.0,
  "leverage": 0,
  "rr_ratio": 0.0,
  "reasons": ["reason1", "reason2", "reason3"]
}
""".strip()


def calculate_weighted_score(inp: SynthesisInput) -> float:
    """Technical 40% + Market Structure 35% + Sentiment 25%."""
    return (
        inp.tech_score * 0.40
        + inp.market_score * 0.35
        + inp.sentiment_score * 0.25
    )


def format_indicators(indicators: dict) -> str:
    """지표 딕셔너리를 사람이 읽기 쉬운 문자열로 변환한다."""
    lines = []
    for tf, data in indicators.items():
        if isinstance(data, dict):
            parts = [f"  [{tf}]"]
            for k, v in data.items():
                if isinstance(v, float):
                    parts.append(f"    {k}: {v:.4f}")
                else:
                    parts.append(f"    {k}: {v}")
            lines.append("\n".join(parts))
    return "\n".join(lines) if lines else "  (indicators unavailable)"


def format_news(news_items: list[dict]) -> str:
    if not news_items:
        return "  (no recent news)"
    lines = []
    for item in news_items[:5]:
        sentiment = item.get("sentiment", "neutral").upper()
        headline = item.get("headline", "")
        source = item.get("source", "")
        lines.append(f"  [{sentiment}] {headline} ({source})")
    return "\n".join(lines)


def build_user_prompt(inp: SynthesisInput) -> str:
    composite = calculate_weighted_score(inp)
    return f"""Analyze {inp.coin} (current price: ${inp.current_price:,.2f})

=== TECHNICAL ANALYSIS (score: {inp.tech_score:+.2f}) ===
{format_indicators(inp.tech_indicators)}
Support:    {[f'${s:,.0f}' for s in inp.support_levels[:3]]}
Resistance: {[f'${r:,.0f}' for r in inp.resistance_levels[:3]]}

=== SENTIMENT ANALYSIS (score: {inp.sentiment_score:+.2f}) ===
Fear & Greed Index: {inp.fear_greed_index} ({inp.fear_greed_label})
Recent news sentiment: {inp.dominant_sentiment}
Key headlines:
{format_news(inp.news_items)}

=== MARKET STRUCTURE (score: {inp.market_score:+.2f}) ===
Funding Rate:      {inp.funding_rate:.4%}
OI Change (1h):    {inp.oi_1h_change_pct:+.2f}%
Long/Short Ratio:  {inp.long_short_ratio:.2f} (Longs: {inp.long_account_pct:.1f}%)
Whale Activity:    {inp.whale_activity}

=== COMPOSITE SIGNAL ===
Weighted score: {composite:+.2f}
(Technical 40% + Market Structure 35% + Sentiment 25%)

Generate your trading signal now."""
