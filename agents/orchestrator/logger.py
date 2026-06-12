"""
Orchestrator 실행 로그.

LogStorage 프로토콜을 구현한 어떤 저장소든 주입 가능.
기본값: InMemoryLogStorage (테스트 / 개발용).

프로덕션에서는 RedisLogStorage / DBLogStorage 등으로 교체한다.
"""
from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

from agents.orchestrator.models import AgentResult, AgentStatus, PipelineResult

logger = logging.getLogger(__name__)


# ── LogStorage 프로토콜 ────────────────────────────────────────────────────────

@runtime_checkable
class LogStorage(Protocol):
    async def save_step(self, run_id: str, step: AgentResult) -> None: ...
    async def save_pipeline(self, result: PipelineResult) -> None: ...
    async def save_decision_log(self, run_id: str, payload: dict) -> None: ...


# ── InMemoryLogStorage ────────────────────────────────────────────────────────

class InMemoryLogStorage:
    """개발 / 테스트용 인메모리 저장소."""

    def __init__(self) -> None:
        self._steps: list[dict] = []
        self._pipelines: list[dict] = []
        self._decision_logs: list[dict] = []

    async def save_step(self, run_id: str, step: AgentResult) -> None:
        self._steps.append({
            "run_id":      run_id,
            "agent_name":  step.agent_name,
            "status":      step.status,
            "attempt":     step.attempt,
            "latency_ms":  step.latency_ms,
            "error":       step.error,
            "started_at":  step.started_at.isoformat(),
            "finished_at": step.finished_at.isoformat() if step.finished_at else None,
        })

    async def save_pipeline(self, result: PipelineResult) -> None:
        self._pipelines.append({
            "run_id":           result.run_id,
            "coin":             result.coin,
            "status":           result.status,
            "steps_total":      len(result.steps),
            "steps_failed":     len(result.failed_steps),
            "steps_skipped":    len(result.skipped_steps),
            "total_latency_ms": result.total_latency_ms,
            "rejection_reason": result.rejection_reason,
            "triggered_at":     result.triggered_at.isoformat(),
            "finished_at":      result.finished_at.isoformat(),
        })

    async def save_decision_log(self, run_id: str, payload: dict) -> None:
        row = dict(payload)
        row["run_id"] = run_id
        self._decision_logs.append(row)

    # ── 조회 (테스트용) ──────────────────────────────────────────────────────

    def get_steps(self, run_id: str) -> list[dict]:
        return [s for s in self._steps if s["run_id"] == run_id]

    def get_pipeline(self, run_id: str) -> dict | None:
        return next((p for p in self._pipelines if p["run_id"] == run_id), None)

    def get_decision_logs(self, run_id: str | None = None) -> list[dict]:
        if run_id is None:
            return list(self._decision_logs)
        return [d for d in self._decision_logs if d["run_id"] == run_id]

    def clear(self) -> None:
        self._steps.clear()
        self._pipelines.clear()
        self._decision_logs.clear()


# ── OrchestratorLogger ────────────────────────────────────────────────────────

class OrchestratorLogger:
    def __init__(self, storage: LogStorage | None = None) -> None:
        self._storage: LogStorage = storage or InMemoryLogStorage()

    async def log_step(self, run_id: str, step: AgentResult) -> None:
        _status_icon = {
            AgentStatus.SUCCESS: "✓",
            AgentStatus.FAILED:  "✗",
            AgentStatus.SKIPPED: "–",
        }.get(step.status, "?")

        log_fn = (
            logger.info    if step.status == AgentStatus.SUCCESS  else
            logger.warning if step.status == AgentStatus.SKIPPED  else
            logger.error
        )
        log_fn(
            "[%s] %s %-24s  status=%-8s  latency=%5.0fms  attempt=%d%s",
            run_id[:8],
            _status_icon,
            step.agent_name,
            step.status,
            step.latency_ms,
            step.attempt,
            f"  err={step.error}" if step.error else "",
        )
        try:
            await self._storage.save_step(run_id, step)
        except Exception as exc:
            logger.warning("[logger] step 저장 실패: %s", exc)

    async def log_pipeline(self, result: PipelineResult) -> None:
        logger.info(
            "[%s] pipeline  coin=%-4s  status=%-10s  steps=%d  latency=%.0fms%s",
            result.run_id[:8],
            result.coin,
            result.status,
            len(result.steps),
            result.total_latency_ms,
            f"  reason={result.rejection_reason}" if result.rejection_reason else "",
        )
        try:
            await self._storage.save_pipeline(result)
        except Exception as exc:
            logger.warning("[logger] pipeline 저장 실패: %s", exc)

    async def log_decision(self, run_id: str, payload: dict) -> None:
        row = dict(payload)
        row["run_id"] = run_id
        logger.info(
            "decision_log %s",
            json.dumps(row, ensure_ascii=False, sort_keys=True),
        )
        save = getattr(self._storage, "save_decision_log", None)
        if save is None:
            return
        try:
            await save(run_id, payload)
        except Exception as exc:
            logger.warning("[logger] decision log 저장 실패: %s", exc)
