"""
Agent Runner.

단일 에이전트 실행을 담당한다.
  - 비동기 실행 (asyncio.wait_for)
  - 지수 백오프 retry (1s → 2s → 4s …)
  - 예외를 AgentResult에 담아 반환 — 절대 raise 하지 않음
  - timeout / max_retries 를 호출 시점에 override 가능
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from agents.orchestrator.models import AgentResult, AgentStatus

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT: float = 30.0
_DEFAULT_MAX_RETRIES: int = 2
_DEFAULT_BASE_DELAY: float = 1.0


class AgentRunner:
    """
    retry + timeout + error-isolation 래퍼.

    Parameters
    ----------
    max_retries:
        최초 시도 포함 총 시도 횟수 = max_retries + 1.
        0 이면 단 1회만 실행.
    base_delay:
        retry 첫 간격(초). 2배씩 증가. (1s → 2s → 4s)
    default_timeout:
        asyncio.wait_for 타임아웃 기본값(초).
    """

    def __init__(
        self,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        base_delay: float = _DEFAULT_BASE_DELAY,
        default_timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.default_timeout = default_timeout

    async def run(
        self,
        agent_name: str,
        coro_fn: Callable[[], Awaitable[Any]],
        *,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> AgentResult:
        """
        에이전트 실행.

        실패(timeout / exception)해도 예외를 올리지 않고
        AgentResult(status=FAILED)로 감싸서 반환한다.

        Parameters
        ----------
        agent_name:
            로그 및 AgentResult.agent_name에 사용.
        coro_fn:
            인자 없는 coroutine factory. 매번 새 coroutine을 만든다.
        timeout:
            None 이면 default_timeout 사용.
        max_retries:
            None 이면 self.max_retries 사용.
        """
        result = AgentResult(agent_name=agent_name, status=AgentStatus.RUNNING)
        _timeout = timeout if timeout is not None else self.default_timeout
        _retries = max_retries if max_retries is not None else self.max_retries
        last_error: str = ""

        total_attempts = _retries + 1
        for attempt in range(1, total_attempts + 1):
            result.attempt = attempt
            try:
                output = await asyncio.wait_for(coro_fn(), timeout=_timeout)
                result.mark_success(output)
                logger.info(
                    "[runner] %-24s attempt=%d/%d  latency=%5.0fms  OK",
                    agent_name, attempt, total_attempts, result.latency_ms,
                )
                return result

            except asyncio.TimeoutError:
                last_error = f"TimeoutError: exceeded {_timeout:.1f}s"
                logger.warning(
                    "[runner] %-24s attempt=%d/%d  TIMEOUT after %.1fs",
                    agent_name, attempt, total_attempts, _timeout,
                )

            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "[runner] %-24s attempt=%d/%d  ERROR: %s",
                    agent_name, attempt, total_attempts, last_error,
                )

            if attempt < total_attempts:
                delay = self.base_delay * (2 ** (attempt - 1))
                logger.debug(
                    "[runner] %-24s  retry in %.1fs …", agent_name, delay
                )
                await asyncio.sleep(delay)

        result.mark_failed(last_error)
        logger.error(
            "[runner] %-24s FAILED after %d attempt(s): %s",
            agent_name, total_attempts, last_error,
        )
        return result
