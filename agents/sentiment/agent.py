"""
Sentiment Agent — 뉴스 감성 + Fear & Greed 종합 점수 산출.

실행 방식: Celery Task (Technical Analysis와 병렬 실행)
실행 주기: 5분
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from agents.sentiment.fear_greed import fetch_fear_greed
from agents.sentiment.models import (
    FearGreedData,
    SentimentInput,
    SentimentResult,
    label_fear_greed,
)
from agents.sentiment.news_fetcher import fetch_crypto_headlines
from agents.sentiment.scorer import (
    calculate_news_score,
    combine_sentiment_scores,
    determine_dominant_sentiment,
    normalize_fear_greed,
)

logger = logging.getLogger(__name__)

# FinBERT 모델 지연 로딩 (첫 호출 시 다운로드)
_finbert_pipeline: Optional[Callable] = None


def _get_finbert() -> Callable:
    global _finbert_pipeline
    if _finbert_pipeline is None:
        from transformers import pipeline as hf_pipeline  # type: ignore[import]
        _finbert_pipeline = hf_pipeline(
            "text-classification",
            model="ProsusAI/finbert",
            device=-1,  # CPU
        )
    return _finbert_pipeline


class SentimentAgent:
    """Sentiment Agent.

    classifier: FinBERT 파이프라인 또는 테스트용 Mock.
    None이면 첫 analyze() 호출 시 지연 로딩.
    """

    def __init__(self, classifier: Optional[Callable] = None) -> None:
        self._classifier = classifier

    async def analyze(
        self,
        inp: SentimentInput,
        *,
        cached_fear_greed: Optional[FearGreedData] = None,
        cached_headlines: Optional[list[str]] = None,
    ) -> SentimentResult:
        """감성 분석을 수행하고 SentimentResult를 반환한다.

        캐싱된 Fear & Greed 또는 헤드라인이 있으면 재활용한다.
        """
        classifier = self._classifier or _get_finbert()

        # Fear & Greed 조회 (캐시 우선)
        if cached_fear_greed is not None:
            fg_data = cached_fear_greed
        else:
            fg_data = await fetch_fear_greed()

        # 뉴스 헤드라인 조회 (캐시 우선)
        if cached_headlines is not None:
            headlines = cached_headlines
        else:
            headlines = await fetch_crypto_headlines(
                inp.coin, count=inp.news_count
            )

        # 점수 계산
        news_score, news_items = calculate_news_score(headlines, classifier)
        fear_greed_score = fg_data.score
        sentiment_score = combine_sentiment_scores(news_score, fear_greed_score)
        dominant = determine_dominant_sentiment(sentiment_score)

        return SentimentResult(
            coin=inp.coin,
            sentiment_score=round(sentiment_score, 4),
            news_score=round(news_score, 4),
            fear_greed_score=round(fear_greed_score, 4),
            fear_greed_index=fg_data.index,
            fear_greed_label=fg_data.label,
            dominant_sentiment=dominant,
            news_items=news_items,
            news_analyzed=len(news_items),
            cache_used=(cached_fear_greed is not None or cached_headlines is not None),
        )

    @staticmethod
    def fallback(coin: str) -> SentimentResult:
        """API 실패 시 중립 점수를 반환한다."""
        return SentimentResult.neutral(coin, cache_used=True)
