"""
Agent Orchestrator 데이터 모델.

설계 원칙:
  - 외부 의존성 없음 (순수 dataclass / enum)
  - AgentResult: 에이전트 1회 실행 결과 (성공/실패/스킵)
  - PipelineContext: 에이전트 간 데이터 전달 컨테이너
  - PipelineInput: 파이프라인 최초 입력 (coin + 사용자 컨텍스트)
  - PipelineResult: 파이프라인 최종 결과 (외부 노출)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional


# ── Enums ─────────────────────────────────────────────────────────────────────

class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED  = "failed"
    SKIPPED = "skipped"


class PipelineStatus(str, Enum):
    RUNNING          = "running"
    COMPLETED        = "completed"          # Step 8(Execution)까지 완주
    HOLD             = "hold"               # AI Analyst → HOLD 판정
    REJECTED         = "rejected"           # Risk / Portfolio 거부
    FAILED           = "failed"             # Critical Agent 실패
    EMERGENCY_CLOSED = "emergency_closed"   # 진입 후 TP/SL 실패 → 긴급 청산 완료


# ── AgentResult ───────────────────────────────────────────────────────────────

@dataclass
class AgentResult:
    """에이전트 1회 실행 결과."""
    agent_name: str
    status: AgentStatus = AgentStatus.PENDING
    output: Any = None
    error: Optional[str] = None
    attempt: int = 1
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    latency_ms: float = 0.0

    def mark_success(self, output: Any) -> None:
        self.finished_at = datetime.now(timezone.utc)
        self.latency_ms = (self.finished_at - self.started_at).total_seconds() * 1000
        self.status = AgentStatus.SUCCESS
        self.output = output

    def mark_failed(self, error: str) -> None:
        self.finished_at = datetime.now(timezone.utc)
        self.latency_ms = (self.finished_at - self.started_at).total_seconds() * 1000
        self.status = AgentStatus.FAILED
        self.error = error

    def mark_skipped(self, reason: str = "") -> None:
        self.finished_at = datetime.now(timezone.utc)
        self.latency_ms = 0.0
        self.status = AgentStatus.SKIPPED
        self.error = reason

    @property
    def succeeded(self) -> bool:
        return self.status == AgentStatus.SUCCESS

    @property
    def failed(self) -> bool:
        return self.status == AgentStatus.FAILED


# ── PipelineInput ─────────────────────────────────────────────────────────────

@dataclass
class PipelineInput:
    """
    파이프라인 최초 입력.

    Orchestrator 바깥(Celery worker 등)이 조립해서 전달한다.
    user_ctx / account_state는 RiskEngine·ExecutionEngine에 그대로 전달된다.
    """
    coin: str                         # "BTC" | "ETH"
    user_id: Optional[str] = None

    # RiskEngine / ExecutionEngine에 전달할 사용자 컨텍스트
    user_ctx: Any = None              # agents.risk.models.UserContext
    account_state: Any = None         # agents.risk.models.AccountState

    # ExecutionEngine 추가 인자
    daily_loss_usdt: Any = None       # Decimal
    weekly_loss_usdt: Any = None      # Decimal
    weekly_limit_usdt: Any = None     # Decimal
    consecutive_losses: int = 0

    # PortfolioEngine 인자
    open_positions: list[Any] = field(default_factory=list)   # PortfolioPosition[]
    portfolio_account: Any = None                              # AccountContext

    # DecisionEngine 런타임 오버라이드. 기본 None이면 live 보수 상수 사용.
    decision_config: Any = None


# ── PipelineContext ───────────────────────────────────────────────────────────

@dataclass
class PipelineContext:
    """에이전트 간 데이터 전달 컨테이너 (파이프라인 내부 전용)."""
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    coin: str = "BTC"
    user_id: Optional[str] = None
    triggered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # 각 단계 출력
    market_snapshot: Any = None    # step 1
    tech_result: Any = None        # step 2  TechnicalAnalysisResult
    strategy_signal: Any = None    # step 3  AggregatedSignal
    decision_result: Any = None    # step 4  DecisionResult (regime/scores/candidate)
    candidate: Any = None          # step 4  TradeCandidate
    ai_review: Any = None          # step 5  AIReviewResult
    risk_result: Any = None        # step 6  ValidationResult
    final_decision: Any = None     # step 7  FinalDecision
    portfolio_check: Any = None    # step 8  (bool, str)
    position_state: Any = None     # step 9  OpenResult
    execution_result: Any = None   # step 10 ExecutionResult

    # decision 이후 공유 시그널 (execution 이후 PostTradeHook에서도 필요)
    raw_signal: Any = None

    errors: list[dict] = field(default_factory=list)


# ── PipelineResult ────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """파이프라인 최종 결과 (외부 노출)."""
    run_id: str
    coin: str
    status: PipelineStatus
    steps: list[AgentResult]
    execution_result: Any = None
    rejection_reason: Optional[str] = None
    total_latency_ms: float = 0.0
    triggered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def step(self, name: str) -> Optional[AgentResult]:
        """이름으로 AgentResult 조회."""
        return next((s for s in self.steps if s.agent_name == name), None)

    @property
    def succeeded(self) -> bool:
        return self.status == PipelineStatus.COMPLETED

    @property
    def failed(self) -> bool:
        return self.status == PipelineStatus.FAILED

    @property
    def failed_steps(self) -> list[AgentResult]:
        return [s for s in self.steps if s.status == AgentStatus.FAILED]

    @property
    def skipped_steps(self) -> list[AgentResult]:
        return [s for s in self.steps if s.status == AgentStatus.SKIPPED]


# ── PostTradeEvent ────────────────────────────────────────────────────────────

@dataclass
class PostTradeEvent:
    """
    포지션 청산 완료 후 PostTradeHookProvider에 전달되는 이벤트.

    realized_pnl_usdt: 실제 체결 fill price로 계산한 확정 P&L (USDT).
      - 값이 있으면 (EMERGENCY_CLOSED 등 즉시 청산): SafetyGate가 이 값을 사용한다.
      - None이면: max_loss_usdt (SL 기준 보수적 추정)를 fallback으로 사용한다.

    max_loss_usdt: RiskEngine이 계산한 SL 기준 최대 손실 노출량.
      realized_pnl_usdt가 없는 경우의 보수적 fallback이다.
      포지션 모니터링 워커가 구현되면 이 값은 쓰이지 않는다.
    """
    user_id: str
    coin: str
    direction: str              # "LONG" | "SHORT"
    entry_price: Decimal
    quantity: Decimal
    stop_loss: Optional[Decimal]
    max_loss_usdt: float        # SL 기준 최대 손실 추정 (fallback)
    period_start_balance: float  # 당일 00:00 UTC 기준 잔고 추정 = balance + daily_loss
    week_start_balance: float    # 주간 시작 기준 잔고 추정  = balance + weekly_loss
    current_balance: float       # 체결 시점 계좌 잔고
    realized_pnl_usdt: Optional[float] = None  # fill price 기반 확정 P&L; None이면 max_loss_usdt 사용
