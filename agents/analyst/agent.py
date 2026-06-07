"""
AI Analyst Agent — Claude Sonnet 기반 시장 분석.

설계 원칙:
  - AnthropicClientProtocol DI: 테스트에서 StubAnthropicClient로 교체
  - 모델명 환경변수로 교체 가능 (settings.CLAUDE_MODEL)
  - AI는 분석만 수행 — 주문 실행 코드 없음
  - 하위 에이전트 점수 전부 0 → Claude 호출 없이 즉시 HOLD
"""
from __future__ import annotations

from typing import Protocol

from agents.analyst.models import (
    AnalystResult,
    MarketContext,
    StrategyContext,
    TechnicalContext,
)
from agents.analyst.parser import _safe_hold, parse_response
from agents.analyst.prompt import SYSTEM_PROMPT, build_user_prompt

_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_MAX_TOKENS = 500
_DEFAULT_TEMPERATURE = 0.1

# 하위 에이전트 점수가 이 임계값 이하이면 LLM 호출 스킵 (AGENTS.md §5.6)
_SKIP_THRESHOLD = 0.05


# ── 프로토콜 ─────────────────────────────────────────────────────────────────────

class AnthropicClientProtocol(Protocol):
    """
    Anthropic 메시지 생성 인터페이스.

    반환값: (text_content, input_tokens, output_tokens)
    프로덕션: AnthropicClient (anthropic.AsyncAnthropic 래핑)
    테스트:   StubAnthropicClient
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

class AnthropicClient:
    """anthropic.AsyncAnthropic을 AnthropicClientProtocol로 래핑한다."""

    def __init__(self, api_key: str) -> None:
        import anthropic as _anthropic
        self._client = _anthropic.AsyncAnthropic(api_key=api_key)

    async def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> tuple[str, int, int]:
        resp = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            temperature=temperature,
        )
        text = resp.content[0].text
        return text, resp.usage.input_tokens, resp.usage.output_tokens


# ── 메인 에이전트 ────────────────────────────────────────────────────────────────

class AnalystAgent:
    """
    Claude Sonnet 기반 AI 분석 에이전트.

    analyze() 호출 → 프롬프트 생성 → Claude API 호출 → 응답 파싱 → AnalystResult 반환.
    """

    def __init__(
        self,
        client: AnthropicClientProtocol,
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
        모든 점수가 0에 가까우면 Claude 호출 없이 HOLD를 반환한다.
        """
        _strategy = strategy or StrategyContext()

        if self._should_skip_llm(technical, _strategy):
            return _safe_hold(
                "하위 에이전트 점수 전부 0 — 시장 데이터 부족으로 HOLD",
                model_used=self._model,
            )

        user_prompt = build_user_prompt(market, technical, _strategy)
        try:
            text, tokens_in, tokens_out = await self._client.create_message(
                model=self._model,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=self._temperature,
            )
        except Exception as exc:
            return _safe_hold(
                f"Claude API 오류: {exc}",
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
