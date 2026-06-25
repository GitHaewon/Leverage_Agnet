"""
AI Reviewer Agent — OpenAI GPT 기반 TradeCandidate 검토.

설계 원칙:
  - OpenAIClientProtocol DI: 테스트에서 Stub으로 교체
  - 모델명 환경변수로 교체 가능 (OPENAI_MODEL)
  - AI는 검토만 수행 — 거래 생성·수정 권한 없음
  - API 오류 / 파싱 실패 → 안전 REJECT (절대 APPROVE로 새지 않음)
"""
from __future__ import annotations

import logging
import os
from typing import Protocol

from agents.decision.constants import STRATEGY_MIN_RR
from agents.decision.models import AIReviewAction, AIReviewResult
from agents.decision.strategy_selector import (
    get_allowed_strategies_for_regime,
    is_strategy_allowed_for_regime,
)
from agents.synthesis.models import ReviewInput
from agents.synthesis.parser import parse_review_response
from agents.synthesis.prompt import SYSTEM_PROMPT, build_review_prompt

_DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")
_DEFAULT_MAX_TOKENS = 2000
_DEFAULT_TEMPERATURE = 1.0

logger = logging.getLogger(__name__)


class OpenAIClientProtocol(Protocol):
    """OpenAI 메시지 생성 인터페이스. 반환값: (text, input_tokens, output_tokens)."""
    async def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> tuple[str, int, int]: ...


class ReviewerAgent:
    """
    OpenAI GPT 기반 AI 리뷰어.

    review(review_input) → AIReviewResult (APPROVE / REJECT).
    AI는 TradeCandidate의 어떤 숫자도 수정하지 않는다.
    """

    def __init__(
        self,
        client: OpenAIClientProtocol,
        model: str = _DEFAULT_MODEL,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float = _DEFAULT_TEMPERATURE,
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def review(self, review_input: ReviewInput) -> AIReviewResult:
        """TradeCandidate를 검토한다. 실패 시 안전 REJECT."""
        playbook_reject = _review_playbook_guard(review_input)
        if playbook_reject is not None:
            return playbook_reject

        prompt = build_review_prompt(review_input)
        try:
            text, _tokens_in, _tokens_out = await self._client.create_message(
                model=self._model,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=self._temperature,
            )
        except Exception as exc:
            logger.warning("AI reviewer OpenAI 오류 — 안전 REJECT: %s", exc)
            # 빈 문자열 → parser가 critical_contradiction=True REJECT 반환
            return parse_review_response("")

        return parse_review_response(text)


def _strategy_key(value: str | None) -> str:
    if value is None:
        return "UNKNOWN"
    key = str(value).strip().upper()
    aliases = {
        "PULLBACK": "TREND_PULLBACK",
        "RETEST": "BREAKOUT_RETEST",
    }
    return aliases.get(key, key)


def _reject(reason: str, warning: str) -> AIReviewResult:
    return AIReviewResult(
        review_action=AIReviewAction.REJECT,
        confidence=1.0,
        critical_contradiction=True,
        risk_warnings=[warning],
        reason_summary=reason,
    )


def _review_playbook_guard(review_input: ReviewInput) -> AIReviewResult | None:
    """시장 국면별 전략 플레이북을 AI 호출 전에 결정적으로 적용한다."""
    regime = str(review_input.market_regime or "UNKNOWN").upper()
    strategy = _strategy_key(review_input.strategy_type)

    if regime == "HIGH_VOLATILITY":
        return _reject(
            "HIGH_VOLATILITY regime blocks new shadow/live candidates by playbook.",
            "regime_high_volatility_no_trade",
        )
    if regime == "NEWS_EVENT":
        return _reject(
            "NEWS_EVENT regime blocks new candidates by playbook.",
            "regime_news_event_no_trade",
        )
    if regime == "UNKNOWN":
        return _reject(
            "UNKNOWN market regime is handled conservatively by playbook.",
            "regime_unknown_conservative_reject",
        )

    if not is_strategy_allowed_for_regime(strategy, regime):
        allowed = ", ".join(get_allowed_strategies_for_regime(regime)) or "none"
        return _reject(
            f"Strategy {strategy} is not allowed for market regime {regime}. "
            f"Allowed strategies: {allowed}.",
            "strategy_not_allowed_for_regime",
        )

    min_rr = STRATEGY_MIN_RR.get(strategy)
    if min_rr is None:
        min_rr = STRATEGY_MIN_RR.get(str(review_input.strategy_type).upper(), 2.0)
    if float(review_input.actual_rr or 0.0) < float(min_rr):
        return _reject(
            f"Candidate R:R {review_input.actual_rr:.2f} is below strategy minimum "
            f"{min_rr:.2f} for {strategy}.",
            "strategy_min_rr_not_met",
        )

    return None
