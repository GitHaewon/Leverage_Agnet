from __future__ import annotations

import time

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_failure, task_postrun, task_prerun, task_retry

from app.core.config import settings

celery_app = Celery(
    "trading_copilot",
    broker=str(settings.REDIS_URL),
    backend=str(settings.REDIS_URL),
    include=[
        "app.workers.analysis_worker",
        "app.workers.shadow_monitor_worker",
        "app.workers.market_data_worker",
        "app.workers.notification_worker",
        "app.workers.reflection_worker",
        "app.workers.coaching_worker",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    task_acks_late=True,           # 태스크 실패 시 재큐
    worker_prefetch_multiplier=1,  # 주문 실행 공정성
    beat_schedule={
        "fetch-market-data-every-1min": {
            "task": "app.workers.market_data_worker.fetch_market_data",
            "schedule": 60.0,
        },
        "analyze-btc-eth-every-15min": {
            "task": "app.workers.analysis_worker.run_analysis_cycle",
            "schedule": 900.0,     # 15분 (shadow trading 테스트용)
            "args": (["BTCUSDT", "ETHUSDT"],),
        },
        "daily-summary-22-kst": {
            "task": "app.workers.notification_worker.send_daily_summary",
            "schedule": crontab(hour=13, minute=0),   # UTC 13:00 = KST 22:00
        },
        "signal-expiry-check-every-min": {
            "task": "app.workers.analysis_worker.expire_signals",
            "schedule": 60.0,
        },
        "shadow-monitor-every-30s": {
            "task": "app.workers.shadow_monitor_worker.run_shadow_monitor",
            "schedule": 30.0,
        },
        "weekly-coaching-report-mon-09-kst": {
            "task": "app.workers.coaching_worker.run_weekly_coaching_all_users",
            "schedule": crontab(day_of_week="mon", hour=0, minute=0),  # UTC Mon 00:00 = KST 09:00
        },
    },
)


# ── Prometheus 태스크 계측 ─────────────────────────────────────────────────────
# task_id → 시작 시간 매핑 (프로세스 로컬)
_task_start_times: dict[str, float] = {}


@task_prerun.connect
def on_task_prerun(task_id: str, task: object, **kwargs: object) -> None:
    _task_start_times[task_id] = time.monotonic()


@task_postrun.connect
def on_task_postrun(
    task_id: str,
    task: object,
    retval: object,
    state: str,
    **kwargs: object,
) -> None:
    start = _task_start_times.pop(task_id, None)
    duration = (time.monotonic() - start) if start is not None else 0.0

    try:
        from app.observability.metrics import record_celery_task
        task_name = getattr(task, "name", str(task))
        status = "success" if state == "SUCCESS" else "failure"
        record_celery_task(task_name, status, duration)
    except Exception:
        pass


@task_failure.connect
def on_task_failure(
    task_id: str,
    exception: Exception,
    **kwargs: object,
) -> None:
    try:
        from app.observability.metrics import record_error
        error_type = type(exception).__name__
        record_error(component="celery", error_type=error_type)
    except Exception:
        pass


@task_retry.connect
def on_task_retry(
    request: object,
    reason: object,
    **kwargs: object,
) -> None:
    try:
        from app.observability.metrics import record_celery_task
        task_name = getattr(request, "task", "unknown")
        record_celery_task(task_name, "retry", 0.0)
    except Exception:
        pass
