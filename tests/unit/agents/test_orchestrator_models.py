"""
Orchestrator 모델 단위 테스트.

검증 항목:
  - AgentResult 상태 전이 (mark_success / mark_failed / mark_skipped)
  - AgentResult 속성 (succeeded, failed)
  - PipelineResult 헬퍼 (step(), failed_steps, skipped_steps)
  - PipelineStatus 열거형 값
"""
from __future__ import annotations

import time

import pytest

from agents.orchestrator.models import (
    AgentResult,
    AgentStatus,
    PipelineResult,
    PipelineStatus,
)


# ── AgentResult ───────────────────────────────────────────────────────────────

class TestAgentResult:
    def test_initial_status_is_pending(self) -> None:
        r = AgentResult(agent_name="test")
        assert r.status == AgentStatus.PENDING

    def test_mark_success_sets_output(self) -> None:
        r = AgentResult(agent_name="test", status=AgentStatus.RUNNING)
        r.mark_success({"value": 42})
        assert r.status == AgentStatus.SUCCESS
        assert r.output == {"value": 42}
        assert r.error is None
        assert r.latency_ms > 0
        assert r.finished_at is not None

    def test_mark_failed_sets_error(self) -> None:
        r = AgentResult(agent_name="test", status=AgentStatus.RUNNING)
        r.mark_failed("TimeoutError: exceeded 30s")
        assert r.status == AgentStatus.FAILED
        assert r.error == "TimeoutError: exceeded 30s"
        assert r.output is None
        assert r.latency_ms >= 0
        assert r.finished_at is not None

    def test_mark_skipped(self) -> None:
        r = AgentResult(agent_name="test")
        r.mark_skipped("upstream failed")
        assert r.status == AgentStatus.SKIPPED
        assert r.error == "upstream failed"
        assert r.latency_ms == 0.0

    def test_mark_skipped_default_reason(self) -> None:
        r = AgentResult(agent_name="test")
        r.mark_skipped()
        assert r.status == AgentStatus.SKIPPED
        assert r.error == ""

    def test_succeeded_property(self) -> None:
        r = AgentResult(agent_name="test")
        r.mark_success("ok")
        assert r.succeeded is True
        assert r.failed is False

    def test_failed_property(self) -> None:
        r = AgentResult(agent_name="test")
        r.mark_failed("err")
        assert r.failed is True
        assert r.succeeded is False

    def test_latency_is_non_negative(self) -> None:
        r = AgentResult(agent_name="test", status=AgentStatus.RUNNING)
        time.sleep(0.01)
        r.mark_success(None)
        assert r.latency_ms >= 10.0

    def test_attempt_default_is_one(self) -> None:
        r = AgentResult(agent_name="test")
        assert r.attempt == 1


# ── PipelineResult ────────────────────────────────────────────────────────────

class TestPipelineResult:
    def _make_result(self, statuses: list[AgentStatus]) -> PipelineResult:
        steps = []
        names = ["a", "b", "c", "d"]
        for i, status in enumerate(statuses):
            r = AgentResult(agent_name=names[i])
            if status == AgentStatus.SUCCESS:
                r.mark_success("ok")
            elif status == AgentStatus.FAILED:
                r.mark_failed("err")
            elif status == AgentStatus.SKIPPED:
                r.mark_skipped("upstream")
            steps.append(r)
        return PipelineResult(
            run_id="run_001",
            coin="BTC",
            status=PipelineStatus.COMPLETED,
            steps=steps,
        )

    def test_step_lookup_by_name(self) -> None:
        result = self._make_result([AgentStatus.SUCCESS, AgentStatus.FAILED])
        assert result.step("a") is not None
        assert result.step("b") is not None
        assert result.step("z") is None

    def test_failed_steps_property(self) -> None:
        result = self._make_result([
            AgentStatus.SUCCESS, AgentStatus.FAILED, AgentStatus.SKIPPED
        ])
        assert len(result.failed_steps) == 1
        assert result.failed_steps[0].agent_name == "b"

    def test_skipped_steps_property(self) -> None:
        result = self._make_result([
            AgentStatus.SUCCESS, AgentStatus.FAILED, AgentStatus.SKIPPED
        ])
        assert len(result.skipped_steps) == 1
        assert result.skipped_steps[0].agent_name == "c"

    def test_succeeded_property_on_completed(self) -> None:
        result = self._make_result([AgentStatus.SUCCESS])
        assert result.succeeded is True
        assert result.failed is False

    def test_failed_property_on_failed_status(self) -> None:
        result = self._make_result([AgentStatus.SUCCESS])
        result.status = PipelineStatus.FAILED
        assert result.failed is True
        assert result.succeeded is False

    def test_total_latency_default(self) -> None:
        result = self._make_result([])
        assert result.total_latency_ms == 0.0

    def test_rejection_reason_default_none(self) -> None:
        result = self._make_result([])
        assert result.rejection_reason is None


# ── PipelineStatus ────────────────────────────────────────────────────────────

class TestPipelineStatus:
    def test_all_statuses_are_string_enum(self) -> None:
        for s in PipelineStatus:
            assert isinstance(s.value, str)

    @pytest.mark.parametrize("s", [
        PipelineStatus.RUNNING,
        PipelineStatus.COMPLETED,
        PipelineStatus.HOLD,
        PipelineStatus.REJECTED,
        PipelineStatus.FAILED,
    ])
    def test_status_equality_with_string(self, s: PipelineStatus) -> None:
        assert s == s.value
