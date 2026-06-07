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
    RUNNING   = "running"
    COMPLETED = "completed"   # Step 8(Execution)까지 완주
    HOLD      = "hold"        # AI Analyst → HOLD 판정
    REJECTED  = "rejected"    # Risk / Portfolio 거부
    FAILED    = "failed"      # Critical Agent 실패


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
    analyst_result: Any = None     # step 4  AnalystResult
    risk_result: Any = None        # step 5  ValidationResult
    portfolio_check: Any = None    # step 6  (bool, str)
    position_state: Any = None     # step 7  OpenResult
    execution_result: Any = None   # step 8  ExecutionResult

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
