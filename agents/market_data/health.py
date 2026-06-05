"""
HealthMonitor — Market Data Agent 헬스체크 Watchdog.

동작:
  - 마지막 수신 시간을 기록
  - 30초 이상 데이터 수신 없으면 unhealthy 판정
  - 백그라운드 태스크로 주기적으로 상태 확인 + 로그 출력

AGENTS.md §1.4:
  헬스체크: 30초마다 마지막 수신 시간 확인
  5분 이상 데이터 없음 → 알림 (PagerDuty / Slack)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)

_UNHEALTHY_THRESHOLD_SECONDS = 30    # 30초 → unhealthy
_CRITICAL_THRESHOLD_SECONDS  = 300   # 5분 → 심각 경보
_CHECK_INTERVAL_SECONDS      = 30    # 체크 주기


class HealthMonitor:
    """Market Data Agent 헬스체크 모니터."""

    def __init__(
        self,
        unhealthy_threshold: int = _UNHEALTHY_THRESHOLD_SECONDS,
        critical_threshold: int = _CRITICAL_THRESHOLD_SECONDS,
        on_critical: Callable[[int], None] | None = None,
    ) -> None:
        self._unhealthy_threshold = unhealthy_threshold
        self._critical_threshold = critical_threshold
        self._on_critical = on_critical  # 5분 경보 콜백
        self._last_received_at: datetime | None = None
        self._is_running = False
        self._task: asyncio.Task | None = None

    def record_received(self) -> None:
        """WebSocket 메시지 수신 시 호출."""
        self._last_received_at = datetime.now(timezone.utc)

    @property
    def last_received_at(self) -> datetime | None:
        return self._last_received_at

    @property
    def elapsed_seconds(self) -> float:
        if self._last_received_at is None:
            return float("inf")
        return (datetime.now(timezone.utc) - self._last_received_at).total_seconds()

    @property
    def is_healthy(self) -> bool:
        return self.elapsed_seconds < self._unhealthy_threshold

    @property
    def is_critical(self) -> bool:
        return self.elapsed_seconds >= self._critical_threshold

    def get_status(self) -> dict:
        elapsed = self.elapsed_seconds
        return {
            "is_healthy": self.is_healthy,
            "is_critical": self.is_critical,
            "last_received_at": self._last_received_at.isoformat() if self._last_received_at else None,
            "elapsed_seconds": round(elapsed, 1) if elapsed != float("inf") else None,
        }

    # ── 백그라운드 Watchdog ────────────────────────────────────────────────────

    async def start_watchdog(self) -> None:
        """백그라운드 헬스체크 태스크 시작."""
        self._is_running = True
        self._task = asyncio.create_task(self._watchdog_loop())

    async def stop_watchdog(self) -> None:
        """헬스체크 태스크 중단."""
        self._is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _watchdog_loop(self) -> None:
        while self._is_running:
            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
            await self._check()

    async def _check(self) -> None:
        elapsed = self.elapsed_seconds

        if elapsed == float("inf"):
            logger.warning("HealthMonitor: no data received yet")
            return

        if self.is_critical:
            logger.critical(
                "MARKET_DATA_CRITICAL: No data for %.0fs (threshold %ds)",
                elapsed, self._critical_threshold,
            )
            if self._on_critical:
                try:
                    self._on_critical(int(elapsed))
                except Exception as exc:
                    logger.error("on_critical callback failed: %s", exc)

        elif not self.is_healthy:
            logger.warning(
                "HealthMonitor: No data for %.0fs (threshold %ds) — reconnect expected",
                elapsed, self._unhealthy_threshold,
            )
        else:
            logger.debug("HealthMonitor: OK, last received %.1fs ago", elapsed)
