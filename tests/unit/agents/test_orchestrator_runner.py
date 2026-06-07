"""
AgentRunner 단위 테스트.

검증 항목:
  - 성공 시 AgentResult(SUCCESS) 반환
  - 예외 발생 시 AgentResult(FAILED) 반환 (raise 하지 않음)
  - TimeoutError 시 AgentResult(FAILED) 반환
  - retry 횟수 정확히 지킴 (max_retries=2 → 총 3회 시도)
  - retry=0 → 단 1회만 시도
  - 두 번째 시도에서 성공하면 SUCCESS
  - 지수 백오프 (asyncio.sleep 호출 횟수 검증)
  - timeout / max_retries override 가능
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agents.orchestrator.models import AgentStatus
from agents.orchestrator.runner import AgentRunner


class TestAgentRunnerSuccess:
    @pytest.mark.asyncio
    async def test_returns_success_on_ok(self) -> None:
        runner = AgentRunner(max_retries=0, default_timeout=5.0)
        result = await runner.run("test_agent", lambda: _coro("ok"))
        assert result.status == AgentStatus.SUCCESS
        assert result.output == "ok"
        assert result.error is None
        assert result.agent_name == "test_agent"

    @pytest.mark.asyncio
    async def test_attempt_is_one_on_first_success(self) -> None:
        runner = AgentRunner(max_retries=2)
        result = await runner.run("agent", lambda: _coro(42))
        assert result.attempt == 1

    @pytest.mark.asyncio
    async def test_latency_recorded(self) -> None:
        runner = AgentRunner(max_retries=0, default_timeout=5.0)
        result = await runner.run("agent", lambda: _coro("x"))
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_none_output_is_ok(self) -> None:
        runner = AgentRunner(max_retries=0)
        result = await runner.run("agent", lambda: _coro(None))
        assert result.succeeded
        assert result.output is None


class TestAgentRunnerFailure:
    @pytest.mark.asyncio
    async def test_exception_returns_failed_not_raises(self) -> None:
        async def boom():
            raise ValueError("DB 연결 실패")

        runner = AgentRunner(max_retries=0)
        result = await runner.run("agent", boom)
        assert result.status == AgentStatus.FAILED
        assert "ValueError" in result.error
        assert "DB 연결 실패" in result.error

    @pytest.mark.asyncio
    async def test_timeout_returns_failed(self) -> None:
        async def slow():
            await asyncio.sleep(10)

        runner = AgentRunner(max_retries=0, default_timeout=0.05)
        result = await runner.run("agent", slow)
        assert result.status == AgentStatus.FAILED
        assert "TimeoutError" in result.error

    @pytest.mark.asyncio
    async def test_failed_result_has_no_output(self) -> None:
        async def boom():
            raise RuntimeError("error")

        runner = AgentRunner(max_retries=0)
        result = await runner.run("agent", boom)
        assert result.output is None


class TestAgentRunnerRetry:
    @pytest.mark.asyncio
    async def test_retries_max_times(self) -> None:
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        runner = AgentRunner(max_retries=2, base_delay=0.001)
        result = await runner.run("agent", always_fail)

        assert result.status == AgentStatus.FAILED
        assert call_count == 3   # 최초 1 + retry 2

    @pytest.mark.asyncio
    async def test_zero_retries_tries_once(self) -> None:
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        runner = AgentRunner(max_retries=0)
        await runner.run("agent", always_fail)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_success_on_second_attempt(self) -> None:
        call_count = 0

        async def fail_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")
            return "recovered"

        runner = AgentRunner(max_retries=2, base_delay=0.001)
        result = await runner.run("agent", fail_once)
        assert result.status == AgentStatus.SUCCESS
        assert result.output == "recovered"
        assert result.attempt == 2
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_attempt_number_increments(self) -> None:
        attempts_seen = []

        async def fail_twice():
            raise RuntimeError("fail")

        runner = AgentRunner(max_retries=2, base_delay=0.001)

        original_run = runner.run

        async def patched_run(name, coro_fn, **kwargs):
            r = await original_run(name, coro_fn, **kwargs)
            attempts_seen.append(r.attempt)
            return r

        runner.run = patched_run
        await runner.run("agent", fail_twice)
        # attempt는 최종 실패한 attempt (=3)
        assert attempts_seen[-1] == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self) -> None:
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        async def always_fail():
            raise RuntimeError("x")

        runner = AgentRunner(max_retries=3, base_delay=1.0)

        with patch("agents.orchestrator.runner.asyncio.sleep", side_effect=fake_sleep):
            await runner.run("agent", always_fail)

        # 지수 백오프: 1.0, 2.0, 4.0
        assert sleep_calls == pytest.approx([1.0, 2.0, 4.0])

    @pytest.mark.asyncio
    async def test_override_max_retries_at_call_site(self) -> None:
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("x")

        runner = AgentRunner(max_retries=5, base_delay=0.001)
        await runner.run("agent", always_fail, max_retries=1)
        assert call_count == 2   # override → 총 2회

    @pytest.mark.asyncio
    async def test_override_timeout_at_call_site(self) -> None:
        async def slow():
            await asyncio.sleep(10)

        runner = AgentRunner(default_timeout=60.0, max_retries=0)
        result = await runner.run("agent", slow, timeout=0.05)
        assert result.failed
        assert "TimeoutError" in result.error


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

async def _coro(value):
    return value
