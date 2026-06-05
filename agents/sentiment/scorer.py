"""
Sentiment 순수 점수 계산 함수.

외부 의존성 없음 — FinBERT 결과를 받아 수치로 변환한다.
"""
from __future__ import annotations

import math
from typing import Callable, Sequence

from agents.sentiment.models import NewsItem, NEWS_WEIGHTS


def normalize_fear_greed(index: int) -> float:
    """Fear & Greed Index (0-100) → -1.0 ~ +1.0 (역발상 지표).

    0 = Extreme Fear → +1.0 (역발상 매수)
    50 = Neutral     →  0.0
    100 = Extreme Greed → -1.0 (역발상 매도)
    """
    return (50 - index) / 50.0


def score_headline(
    headline: str,
    classifier: Callable[[list[str]], list[dict]],
) -> NewsItem:
    """FinBERT(또는 호환 분류기)로 단일 헤드라인을 분석하여 NewsItem을 반환한다."""
    results = classifier([headline])
    r = results[0]
    label: str = r["label"].lower()
    confidence: float = float(r["score"])

    if label == "positive":
        score = +confidence
    elif label == "negative":
        score = -confidence
    else:
        score = 0.0
        label = "neutral"

    return NewsItem(
        headline=headline,
        source="",
        published_at="",
        sentiment=label,  # type: ignore[arg-type]
        confidence=confidence,
        score=score,
    )


def calculate_news_score(
    headlines: Sequence[str],
    classifier: Callable[[list[str]], list[dict]],
) -> tuple[float, list[NewsItem]]:
    """최근 헤드라인(인덱스 0이 가장 최신)에 역수 가중치를 적용하여 감성 점수를 계산한다.

    Returns:
        (news_score: float, classified_items: list[NewsItem])
    """
    if not headlines:
        return 0.0, []

    results = classifier(list(headlines))
    items: list[NewsItem] = []

    for i, (headline, r) in enumerate(zip(headlines, results)):
        label: str = r["label"].lower()
        confidence: float = float(r["score"])
        if label == "positive":
            score = +confidence
        elif label == "negative":
            score = -confidence
        else:
            score = 0.0
            label = "neutral"

        items.append(NewsItem(
            headline=headline,
            source="",
            published_at="",
            sentiment=label,  # type: ignore[arg-type]
            confidence=confidence,
            score=score,
        ))

    # 역수 가중치 (인덱스 0 = 가장 최신, 가중치 1.0)
    scores = [item.score for item in items]
    weights = [1.0 / (i + 1) for i in range(len(scores))]
    total_weight = sum(weights)
    weighted_score = sum(s * w for s, w in zip(scores, weights)) / total_weight

    return float(weighted_score), items


def combine_sentiment_scores(
    news_score: float,
    fear_greed_score: float,
    weights: dict[str, float] = NEWS_WEIGHTS,
) -> float:
    """뉴스 점수와 F&G 점수를 가중 평균하여 종합 감성 점수를 반환한다."""
    combined = news_score * weights["news"] + fear_greed_score * weights["fear_greed"]
    return max(-1.0, min(1.0, combined))


def determine_dominant_sentiment(score: float) -> str:
    """종합 점수로 지배적 감성을 결정한다."""
    if score > 0.1:
        return "positive"
    if score < -0.1:
        return "negative"
    return "neutral"
