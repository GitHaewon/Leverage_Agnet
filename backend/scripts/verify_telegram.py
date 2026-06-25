#!/usr/bin/env python3
"""
Telegram 봇 연결 및 알림 전체 검증 스크립트.

검증 항목:
  1. BOT_TOKEN / CHAT_ID 환경변수 설정 확인
  2. getMe — 봇 정보 조회 (토큰 유효성)
  3. getChat — 채팅방 접근 권한 확인
  4. 실제 메시지 발송 5종
       [주문 체결] OrderFilledEvent
       [주문 실패] OrderFailedEvent
       [일일 손실 한도] MaxDailyLossEvent
       [Kill Switch] KillSwitchEvent
       [긴급 청산] EmergencyClosedEvent
  5. 응답속도 측정
  6. 최종 요약

실행:
  cd /path/to/Leverage_Agent
  python backend/scripts/verify_telegram.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

SEP  = "─" * 58
PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"
INFO = "   "


def _sec(n: int, title: str) -> None:
    print(f"\n{SEP}")
    print(f"[{n}/6] {title}")
    print(SEP)


def _row(status: str, msg: str = "") -> None:
    print(f"  {status}  {msg}" if msg else f"  {status}")


@dataclass
class CheckResult:
    label: str
    success: bool
    detail: str = ""
    error: str = ""
    elapsed_s: float = 0.0


# ── Telegram API 직접 호출 헬퍼 ───────────────────────────────────────────────

async def _get(client, token: str, method: str) -> dict:
    import httpx
    url = f"https://api.telegram.org/bot{token}/{method}"
    resp = await client.get(url, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


async def _post(client, token: str, method: str, payload: dict) -> dict:
    import httpx
    url = f"https://api.telegram.org/bot{token}/{method}"
    resp = await client.post(url, json=payload, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


# ── 알림 이벤트 팩토리 ─────────────────────────────────────────────────────────

def _make_events():
    from agents.alert.models import (
        OrderFilledEvent, OrderFailedEvent, MaxDailyLossEvent,
        KillSwitchEvent, EmergencyClosedEvent,
    )
    now = datetime.now(timezone.utc)
    return [
        OrderFilledEvent(
            symbol="BTCUSDT",
            direction="LONG",
            fill_price=Decimal("67500.00"),
            quantity=Decimal("0.001"),
            leverage=5,
            take_profit=Decimal("69750.00"),
            stop_loss=Decimal("66375.00"),
        ),
        OrderFailedEvent(
            symbol="ETHUSDT",
            direction="SHORT",
            rejection_code="RISK_RR_TOO_LOW",
            reason="R:R 1.5 < 최소 2.0",
        ),
        MaxDailyLossEvent(
            daily_loss_usdt=Decimal("150.00"),
            limit_usdt=Decimal("150.00"),
            triggered_at=now,
        ),
        KillSwitchEvent(
            reason="일일 손실 한도 도달 — 자동매매 중단",
            triggered_at=now,
        ),
        EmergencyClosedEvent(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=Decimal("67500.00"),
            exit_price=Decimal("67320.00"),
            reason="TP/SL 설정 실패 — 긴급 청산",
            triggered_at=now,
        ),
    ]


# ── 메인 검증 ─────────────────────────────────────────────────────────────────

async def main() -> None:
    import httpx

    print("\n" + "=" * 58)
    print("  AI Trading Copilot — Telegram 봇 검증")
    print("=" * 58)

    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    results: list[CheckResult] = []

    # ── [1] 환경변수 확인 ────────────────────────────────────────────────────
    _sec(1, "환경변수 설정 확인")
    token_ok   = bool(token)
    chat_id_ok = bool(chat_id)

    if token_ok:
        masked = token[:10] + "..." + token[-6:]
        _row(PASS, f"TELEGRAM_BOT_TOKEN  : {masked}")
    else:
        _row(FAIL, "TELEGRAM_BOT_TOKEN 미설정 — .env 확인 필요")

    if chat_id_ok:
        _row(PASS, f"TELEGRAM_CHAT_ID    : {chat_id}")
    else:
        _row(FAIL, "TELEGRAM_CHAT_ID 미설정 — .env 확인 필요")
        _row(INFO, "chat_id 얻는 방법: 봇에게 /start 후")
        _row(INFO, "https://api.telegram.org/bot<TOKEN>/getUpdates 조회")

    env_ok = token_ok and chat_id_ok
    results.append(CheckResult("환경변수", env_ok,
                                detail="BOT_TOKEN + CHAT_ID 모두 설정됨" if env_ok else "",
                                error="" if env_ok else "환경변수 누락"))

    if not env_ok:
        _print_summary(results)
        return

    async with httpx.AsyncClient() as client:

        # ── [2] getMe (봇 토큰 유효성) ───────────────────────────────────────
        _sec(2, "getMe — 봇 토큰 유효성 확인")
        t0 = time.perf_counter()
        try:
            data = await _get(client, token, "getMe")
            elapsed = time.perf_counter() - t0
            bot = data.get("result", {})
            bot_name     = bot.get("first_name", "?")
            bot_username = bot.get("username", "?")
            bot_id       = bot.get("id", "?")
            _row(PASS, f"봇 이름 : {bot_name} (@{bot_username})")
            _row(INFO, f"봇 ID   : {bot_id}  |  응답 {elapsed:.2f}s")
            results.append(CheckResult("getMe", True, detail=f"@{bot_username}", elapsed_s=elapsed))
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            _row(FAIL, f"getMe 실패: {exc}")
            if "401" in str(exc):
                _row(INFO, "→ 토큰이 유효하지 않습니다. @BotFather에서 재발급하세요.")
            results.append(CheckResult("getMe", False, error=str(exc), elapsed_s=elapsed))
            _print_summary(results)
            return

        # ── [3] getChat (채팅방 접근 권한) ───────────────────────────────────
        _sec(3, "getChat — 채팅방 접근 권한 확인")
        t0 = time.perf_counter()
        try:
            data = await _post(client, token, "getChat", {"chat_id": chat_id})
            elapsed = time.perf_counter() - t0
            chat = data.get("result", {})
            chat_type  = chat.get("type", "?")
            chat_title = chat.get("title") or chat.get("first_name") or chat.get("username") or "?"
            _row(PASS, f"채팅방 : {chat_title} (type={chat_type})")
            _row(INFO, f"응답 {elapsed:.2f}s")
            results.append(CheckResult("getChat", True, detail=f"{chat_title}({chat_type})", elapsed_s=elapsed))
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            _row(FAIL, f"getChat 실패: {exc}")
            if "400" in str(exc) or "chat not found" in str(exc).lower():
                _row(INFO, "→ TELEGRAM_CHAT_ID가 잘못됐거나 봇이 채팅방에 없습니다.")
                _row(INFO, "   그룹 채팅이면 봇을 초대 후 메시지를 보내야 chat_id가 생깁니다.")
            results.append(CheckResult("getChat", False, error=str(exc), elapsed_s=elapsed))
            _print_summary(results)
            return

        # ── [4] 알림 5종 발송 ────────────────────────────────────────────────
        _sec(4, "실제 알림 메시지 5종 발송")
        from agents.alert.formatter import format_alert
        from agents.alert.sender import TelegramSender

        sender = TelegramSender(bot_token=token)
        events = _make_events()
        event_labels = [
            "OrderFilledEvent   (주문 체결)",
            "OrderFailedEvent   (주문 실패)",
            "MaxDailyLossEvent  (일일 손실 한도)",
            "KillSwitchEvent    (Kill Switch)",
            "EmergencyClosedEvent (긴급 청산)",
        ]
        send_times: list[float] = []
        all_sent = True

        for event, label in zip(events, event_labels):
            t0 = time.perf_counter()
            try:
                text = format_alert(event)
                await sender.send(chat_id, text)
                elapsed = time.perf_counter() - t0
                send_times.append(elapsed)
                _row(PASS, f"{label}  ({elapsed:.2f}s)")
                results.append(CheckResult(label, True, elapsed_s=elapsed))
            except Exception as exc:
                elapsed = time.perf_counter() - t0
                _row(FAIL, f"{label}  → {exc}")
                results.append(CheckResult(label, False, error=str(exc), elapsed_s=elapsed))
                all_sent = False

        # ── [5] 응답속도 ─────────────────────────────────────────────────────
        _sec(5, "응답속도 측정")
        if send_times:
            avg = sum(send_times) / len(send_times)
            _row(INFO, f"평균 {avg:.2f}s  |  최소 {min(send_times):.2f}s  |  최대 {max(send_times):.2f}s")
            if avg < 1.5:
                _row(PASS, "응답속도 양호 — 실시간 알림에 적합")
            elif avg < 3.0:
                _row(WARN, "응답속도 보통 — 문제 없으나 네트워크 상태 확인 권장")
            else:
                _row(WARN, "응답속도 느림 — Telegram API 레이트 리밋 또는 네트워크 점검")
        else:
            _row(WARN, "발송 기록 없음 — 이전 단계 실패")

    # ── [6] 최종 요약 ─────────────────────────────────────────────────────────
    _sec(6, "최종 요약")
    _print_summary(results)


def _print_summary(results: list[CheckResult]) -> None:
    passed = sum(1 for r in results if r.success)
    total  = len(results)

    for r in results:
        icon = "✅" if r.success else "❌"
        detail = r.detail or r.error or ""
        print(f"  {icon}  {r.label:<36} {detail}")

    print(f"\n  {passed}/{total} 통과", end="")
    if all(r.success for r in results):
        print(" — Telegram 봇 완전 검증 ✅")
        print()
        print("  활성화된 알림 이벤트 5종:")
        print("    📊 주문 체결 (OrderFilledEvent)")
        print("    ❌ 주문 실패 (OrderFailedEvent)")
        print("    🚨 일일 손실 한도 도달 (MaxDailyLossEvent)")
        print("    ⛔ Kill Switch 발동 (KillSwitchEvent)")
        print("    🚨 긴급 청산 완료 (EmergencyClosedEvent)")
        print()
        print("  파이프라인 연결 상태:")
        print("    analysis_worker.py 에서 TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID")
        print("    두 값이 모두 설정되면 AlertDispatcher가 자동으로 활성화됩니다.")
    else:
        failed = [r for r in results if not r.success]
        print(" — 일부 항목 실패")
        for r in failed:
            print(f"\n  ❌ {r.label}")
            if r.error:
                print(f"     오류: {r.error}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
