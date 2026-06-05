from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "trading_copilot",
    broker=str(settings.REDIS_URL),
    backend=str(settings.REDIS_URL),
    include=[
        "app.workers.analysis_worker",
        "app.workers.notification_worker",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,           # 태스크 실패 시 재큐
    worker_prefetch_multiplier=1,  # 주문 실행 공정성
    beat_schedule={
        "analyze-btc-eth-every-5min": {
            "task": "app.workers.analysis_worker.run_analysis_cycle",
            "schedule": 300.0,     # 5분 (초 단위)
            "args": (["BTCUSDT", "ETHUSDT"],),
        },
        "daily-summary-22-kst": {
            "task": "app.workers.notification_worker.send_daily_summary",
            "schedule": {"hour": 13, "minute": 0},   # UTC 13:00 = KST 22:00
        },
        "signal-expiry-check-every-min": {
            "task": "app.workers.analysis_worker.expire_signals",
            "schedule": 60.0,
        },
    },
)
