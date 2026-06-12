"""
AI Analyst Agent — OpenAI GPT 기반 시장 분석.
AI는 분석만 수행한다. 주문 권한 없음.

DEPRECATED (Step 9+): AI가 시그널/방향/진입가를 "생성"하던 이 경로는
결정적 의사결정 플로우로 대체되었다.
  - 시그널 생성: agents/decision/ (DecisionEngine → TradeCandidate, 결정적)
  - AI 역할:     agents/synthesis/ (ReviewerAgent → APPROVE/REJECT 검토 전용)

이 패키지에서 유일하게 현역으로 쓰이는 것은 `OpenAIClient`(OpenAI 전송 래퍼)이며
ReviewerAgent가 이를 재사용한다. AnalystAgent / build_user_prompt / parse_response /
MarketContext·TechnicalContext·StrategyContext / AnalysisDecision·AnalystResult 는
프로덕션 플로우에서 더 이상 사용되지 않는다(레거시 테스트 호환을 위해 유지).
신규 코드는 절대 AnalystAgent로 시그널을 생성하지 말 것.

TODO: OpenAIClient를 중립 위치(예: agents/common/openai_client.py)로 이전한 뒤
      이 패키지와 관련 레거시 테스트를 제거하는 정리 작업을 별도 단계로 진행.
"""
from agents.analyst.agent import AnalystAgent, OpenAIClient, OpenAIClientProtocol
from agents.analyst.models import (
    AnalysisDecision,
    AnalystResult,
    MarketContext,
    StrategyContext,
    TechnicalContext,
)
from agents.analyst.parser import parse_response
from agents.analyst.prompt import SYSTEM_PROMPT, build_user_prompt, compute_composite_score

__all__ = [
    "AnalysisDecision",
    "AnalystAgent",
    "AnalystResult",
    "OpenAIClient",
    "OpenAIClientProtocol",
    "MarketContext",
    "SYSTEM_PROMPT",
    "StrategyContext",
    "TechnicalContext",
    "build_user_prompt",
    "compute_composite_score",
    "parse_response",
]
