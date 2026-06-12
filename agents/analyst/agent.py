"""
AI Analyst Agent — OpenAI GPT 기반 시장 분석.

설계 원칙:
  - OpenAIClientProtocol DI: 테스트에서 StubOpenAIClient로 교체
  - 모델명 환경변수로 교체 가능 (OPENAI_MODEL)
  - AI는 분석만 수행 — 주문 실행 코드 없음
  - 하위 에이전트 점수 전부 0 → GPT 호출 없이 즉시 HOLD
"""
from __future__ import annotations

import logging
import os
import time
from typing import Protocol

from agents.analyst.models import (
    AnalystResult,
    MarketContext,
    StrategyContext,
    TechnicalContext,
)
from agents.analyst.parser import _safe_hold, parse_response
from agents.analyst.prompt import SYSTEM_PROMPT, build_user_prompt

_DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")
_DEFAULT_MAX_TOKENS = 4000  # reasoning model은 reasoning token을 내부 소모 → 실제 출력에 충분한 여유 필요
_DEFAULT_TEMPERATURE = 1.0

# 하위 에이전트 점수가 이 임계값 이하이면 LLM 호출 스킵 (AGENTS.md §5.6)
_SKIP_THRESHOLD = 0.05

logger = logging.getLogger(__name__)

# ── 비용 모니터링 ─────────────────────────────────────────────────────────────────
# 구체적인 모델명 먼저 (prefix match 오류 방지: gpt-5-mini가 gpt-5보다 먼저 매칭되어야 함)
_COST_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-5-mini":  (0.50,  2.00),
    "gpt-5":       (2.50, 10.00),
    "gpt-4o-mini": (0.15,  0.60),
    "gpt-4o":      (2.50, 10.00),
}


def _estimate_cost_usd(model: str, in_tok: int, out_tok: int) -> float:
    """모델 ID와 토큰 수로 예상 비용(USD)을 계산한다."""
    base = model.split("-202")[0]   # 날짜 suffix 제거: gpt-5-mini-2025-08-07 → gpt-5-mini
    rate = _COST_PER_1M.get(base)
    if rate is None:
        rate = next((v for k, v in _COST_PER_1M.items() if base.startswith(k)), None)
    if rate is None:
        return 0.0
    return (in_tok / 1_000_000) * rate[0] + (out_tok / 1_000_000) * rate[1]


def _log_openai_call(model: str, in_tok: int, out_tok: int, elapsed_ms: float) -> None:
    """GPT 호출 비용·토큰·응답시간을 INFO 레벨로 기록한다."""
    total = in_tok + out_tok
    cost  = _estimate_cost_usd(model, in_tok, out_tok)
    logger.info(
        "openai_usage model=%s in_tokens=%d out_tokens=%d total_tokens=%d "
        "cost_usd=$%.6f latency_ms=%.0f",
        model, in_tok, out_tok, total, cost, elapsed_ms,
    )


# ── 프로토콜 ─────────────────────────────────────────────────────────────────────

class OpenAIClientProtocol(Protocol):
    """
    OpenAI 메시지 생성 인터페이스.

    반환값: (text_content, input_tokens, output_tokens)
    프로덕션: OpenAIClient (openai.AsyncOpenAI 래핑)
    테스트:   StubOpenAIClient
    """
    async def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> tuple[str, int, int]: ...


# ── 프로덕션 클라이언트 ───────────────────────────────────────────────────────────

class OpenAIClient:
    """openai.AsyncOpenAI를 OpenAIClientProtocol로 래핑한다."""

    def __init__(self, api_key: str) -> None:
        import openai as _openai
        self._client = _openai.AsyncOpenAI(api_key=api_key)

    async def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> tuple[str, int, int]:
        full_messages = [{"role": "system", "content": system}] + messages
        kwargs: dict = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "messages": full_messages,  # type: ignore[arg-type]
        }
        # temperature=1 이 기본값인 모델(gpt-5 계열)은 1 이외 값을 거부한다.
        # temperature가 기본값(1.0)이 아닐 때만 명시적으로 전달한다.
        if temperature != 1.0:
            kwargs["temperature"] = temperature
        resp = await self._client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        return text, resp.usage.prompt_tokens, resp.usage.completion_tokens


# ── 메인 에이전트 ────────────────────────────────────────────────────────────────

class AnalystAgent:
    """
    OpenAI GPT 기반 AI 분석 에이전트.

    analyze() 호출 → 프롬프트 생성 → OpenAI API 호출 → 응답 파싱 → AnalystResult 반환.

    DEPRECATED: AI가 시그널을 생성하던 경로. 결정적 DecisionEngine + ReviewerAgent로
    대체됨 (agents/decision/, agents/synthesis/). 프로덕션 파이프라인은 더 이상 이
    클래스를 사용하지 않는다. 신규 코드에서 사용 금지 — AI는 검토(APPROVE/REJECT)만 한다.
    (레거시 테스트 호환 목적으로만 유지)
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

    async def analyze(
        self,
        market: MarketContext,
        technical: TechnicalContext,
        strategy: StrategyContext | None = None,
    ) -> AnalystResult:
        """
        세 컨텍스트를 종합하여 AI 분석 결과를 반환한다.

        strategy=None이면 중립 StrategyContext를 사용한다.
        모든 점수가 0에 가까우면 GPT 호출 없이 HOLD를 반환한다.
        """
        _strategy = strategy or StrategyContext()

        if self._should_skip_llm(technical, _strategy):
            return _safe_hold(
                "하위 에이전트 점수 전부 0 — 시장 데이터 부족으로 HOLD",
                model_used=self._model,
            )

        user_prompt = build_user_prompt(market, technical, _strategy)
        try:
            t0 = time.perf_counter()
            text, tokens_in, tokens_out = await self._client.create_message(
                model=self._model,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=self._temperature,
            )
            _log_openai_call(self._model, tokens_in, tokens_out, (time.perf_counter() - t0) * 1000)
        except Exception as exc:
            return _safe_hold(
                f"OpenAI API 오류: {exc}",
                model_used=self._model,
            )

        return parse_response(
            text,
            entry_price_fallback=market.current_price,
            model_used=self._model,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
        )

    def _should_skip_llm(
        self,
        technical: TechnicalContext,
        strategy: StrategyContext,
    ) -> bool:
        """세 점수가 모두 _SKIP_THRESHOLD 이하이면 True."""
        return (
            abs(technical.tech_score) <= _SKIP_THRESHOLD
            and abs(strategy.sentiment_score) <= _SKIP_THRESHOLD
            and abs(strategy.market_score) <= _SKIP_THRESHOLD
        )
