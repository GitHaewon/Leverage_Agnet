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

from agents.decision.models import AIReviewResult
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
