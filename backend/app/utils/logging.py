from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from app.core.config import settings


class _JsonFormatter(logging.Formatter):
    """프로덕션용 JSON 로그 포맷."""

    def format(self, record: logging.LogRecord) -> str:
        log: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log["exception"] = self.formatException(record.exc_info)
        # structlog 스타일의 extra 필드 포함
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            }:
                log[key] = value
        return json.dumps(log, ensure_ascii=False, default=str)


class _DevFormatter(logging.Formatter):
    """개발용 컬러 텍스트 포맷."""

    _LEVEL_COLORS = {
        "DEBUG": "\033[36m",    # cyan
        "INFO": "\033[32m",     # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",    # red
        "CRITICAL": "\033[35m", # magenta
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._LEVEL_COLORS.get(record.levelname, "")
        level = f"{color}{record.levelname:<8}{self._RESET}"
        return (
            f"{datetime.now().strftime('%H:%M:%S')} | {level} | "
            f"{record.name} | {record.getMessage()}"
        )


def setup_logging() -> None:
    """앱 시작 시 한 번 호출. lifespan에서 호출."""
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    formatter: logging.Formatter = (
        _JsonFormatter() if settings.is_production else _DevFormatter()
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()
    root.addHandler(handler)

    # 노이즈 줄이기
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
