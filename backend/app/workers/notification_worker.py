from __future__ import annotations

import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.notification_worker.send_daily_summary", bind=True, max_retries=3)
def send_daily_summary(self: object) -> dict[str, str]:
    logger.info("Daily summary task triggered (not yet implemented)")
    return {"status": "skipped", "reason": "not implemented"}
