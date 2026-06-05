"""
이메일 발송 서비스.

개발 환경: 이메일 내용을 로그에 출력
프로덕션: SMTP로 실제 발송

설계 원칙: 이메일 발송 실패가 API 응답을 차단하지 않도록
실제 발송은 Celery 태스크로 위임한다.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "http://localhost:3000"   # 환경변수로 관리 예정


def _send_smtp(to_email: str, subject: str, html_body: str) -> None:
    """동기 SMTP 발송 — Celery 워커 내에서 호출."""
    if not settings.SMTP_USER:
        logger.warning("SMTP_USER not set. Email not sent to %s.", to_email)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
    except Exception as exc:
        logger.error("SMTP error sending to %s: %s", to_email, exc)
        raise


def _log_email(to_email: str, subject: str, content: str) -> None:
    """개발 환경용: 이메일 내용 로그 출력."""
    logger.info(
        "📧 [DEV EMAIL] To: %s | Subject: %s\n%s",
        to_email, subject, content,
    )


async def send_verification_email(email: str, code: str) -> None:
    """이메일 인증 코드 발송."""
    subject = "[AI Trading Copilot] 이메일 인증 코드"
    content = f"인증 코드: {code}\n유효 시간: 5분"
    html = f"""
    <h2>이메일 인증</h2>
    <p>아래 6자리 코드를 입력하여 이메일을 인증하세요.</p>
    <h1 style="letter-spacing:8px;font-size:40px;">{code}</h1>
    <p>이 코드는 <strong>5분</strong> 후 만료됩니다.</p>
    <p>본인이 요청하지 않았다면 이 이메일을 무시하세요.</p>
    """
    if settings.is_production and settings.SMTP_USER:
        _send_smtp(email, subject, html)
    else:
        _log_email(email, subject, content)


async def send_password_reset_email(email: str, reset_token: str) -> None:
    """비밀번호 재설정 링크 발송."""
    reset_url = f"{_BASE_URL}/auth/reset-password?token={reset_token}"
    subject = "[AI Trading Copilot] 비밀번호 재설정"
    content = f"재설정 링크: {reset_url}\n유효 시간: 30분"
    html = f"""
    <h2>비밀번호 재설정</h2>
    <p>아래 버튼을 클릭하여 비밀번호를 재설정하세요.</p>
    <a href="{reset_url}"
       style="display:inline-block;padding:12px 24px;background:#3B82F6;
              color:white;text-decoration:none;border-radius:6px;">
      비밀번호 재설정
    </a>
    <p>이 링크는 <strong>30분</strong> 후 만료됩니다.</p>
    <p>본인이 요청하지 않았다면 이 이메일을 무시하세요.</p>
    """
    if settings.is_production and settings.SMTP_USER:
        _send_smtp(email, subject, html)
    else:
        _log_email(email, subject, content)
