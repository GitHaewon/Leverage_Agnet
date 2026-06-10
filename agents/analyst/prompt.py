"""
AI Analyst Agent 프롬프트 빌더.

순수 함수 — I/O 없음.
AGENTS.md §5.4 기준, 공개 출력 형식(decision/confidence/reason/risk_level) 반영.
"""
from __future__ import annotations

from agents.analyst.models import MarketContext, StrategyContext, TechnicalContext

SYSTEM_PROMPT = """
You are a professional cryptocurrency futures trading analyst with 10+ years of experience.
Your role is ANALYSIS ONLY — you have NO order placement authority whatsoever.

RULES (non-negotiable):
1. decision must be LONG, SHORT, or HOLD only
2. If confidence < 60, output HOLD regardless of your analysis
3. stop_loss is MANDATORY for LONG/SHORT — if you cannot set one, output HOLD
4. Minimum rr_ratio is 2.0 for LONG/SHORT — if unachievable, output HOLD
5. reason must reference SPECIFIC indicator values (e.g., "RSI(14)=42.3")
6. risk_level: LOW = clear high-confidence signal, MEDIUM = moderate, HIGH = uncertain/volatile
7. leverage: 5x max for confidence 60–70%, 10x max for 70–85%, 15x max for 85%+
8. reason must be written in Korean as ONE concise sentence

OUTPUT FORMAT (strict JSON, no markdown, no text outside JSON):
{
  "decision": "LONG|SHORT|HOLD",
  "confidence": 0-100,
  "reason": "한국어 요약 (구체적 지표값 포함)",
  "risk_level": "LOW|MEDIUM|HIGH",
  "entry_price": 0.0,
  "take_profit": 0.0,
  "stop_loss": 0.0,
  "leverage": 1,
  "rr_ratio": 0.0,
  "raw_reasons": ["reason1", "reason2", "reason3"]
}
""".strip()


# ── 가중 복합 점수 ────────────────────────────────────────────────────────────────

def compute_composite_score(technical: TechnicalContext, strategy: StrategyContext) -> float:
    """Technical 40% + Market Structure 35% + Sentiment 25%."""
    return (
        technical.tech_score * 0.40
        + strategy.market_score * 0.35
        + strategy.sentiment_score * 0.25
    )


# ── 포맷 헬퍼 ────────────────────────────────────────────────────────────────────

def _format_indicators(indicators: dict) -> str:
    if not indicators:
        return "  (indicators unavailable)"
    lines = []
    for key, val in indicators.items():
        if isinstance(val, dict):
            # 중괄호·쉼표 제거 → space-separated k=v 형식으로 토큰 절감
            sub = " ".join(
                f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}"
                for k, v in val.items()
            )
            lines.append(f"  {key}: {sub}")
        elif isinstance(val, float):
            lines.append(f"  {key}: {val:.3f}")
        else:
            lines.append(f"  {key}: {val}")
    return "\n".join(lines)


def _format_signals(signals: list[str]) -> str:
    if not signals:
        return "  (no signals fired)"
    return "\n".join(f"  - {s}" for s in signals)


def _format_news(news_items: list[dict]) -> str:
    if not news_items:
        return "  (no recent news)"
    lines = []
    for item in news_items[:3]:
        sentiment = str(item.get("sentiment", "neutral")).upper()
        headline = item.get("headline", "")
        source = item.get("source", "")
        lines.append(f"  [{sentiment}] {headline} ({source})")
    return "\n".join(lines)


# ── 메인 프롬프트 빌더 ────────────────────────────────────────────────────────────

def build_user_prompt(
    market: MarketContext,
    technical: TechnicalContext,
    strategy: StrategyContext,
) -> str:
    composite = compute_composite_score(technical, strategy)
    tf_scores = "  " + "\n  ".join(
        f"{tf}: {score:+.2f}"
        for tf, score in technical.timeframe_scores.items()
    ) if technical.timeframe_scores else "  (unavailable)"

    return f"""Analyze {market.coin} (current price: ${market.current_price:,.2f})

=== TECHNICAL ANALYSIS (score: {technical.tech_score:+.2f}) ===
Timeframe Scores:
{tf_scores}
Indicators:
{_format_indicators(technical.indicators)}
Signals Fired:
{_format_signals(technical.signals_fired)}
Support:    {[f'${s:,.0f}' for s in technical.support_levels[:3]]}
Resistance: {[f'${r:,.0f}' for r in technical.resistance_levels[:3]]}

=== SENTIMENT ANALYSIS (score: {strategy.sentiment_score:+.2f}) ===
Fear & Greed Index: {strategy.fear_greed_index} ({strategy.fear_greed_label})
Dominant sentiment: {strategy.dominant_sentiment}
Key headlines:
{_format_news(strategy.news_items)}

=== MARKET STRUCTURE (score: {strategy.market_score:+.2f}) ===
Funding Rate:     {strategy.funding_rate:.4%}
OI Change (1h):   {strategy.oi_1h_change_pct:+.2f}%
Long/Short Ratio: {strategy.long_short_ratio:.2f} (Longs: {strategy.long_account_pct:.1f}%)
Whale Activity:   {strategy.whale_activity}

=== COMPOSITE SIGNAL ===
Weighted score: {composite:+.2f}
(Technical 40% + Market Structure 35% + Sentiment 25%)

Generate your analysis now. Remember: ANALYSIS ONLY — no order authority."""
