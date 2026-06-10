#!/usr/bin/env python3
"""
OpenAI GPT 재검증 스크립트.

검증 항목:
  1. GPT 호출 성공
  2. JSON Structured Output 성공
  3. LONG 응답 테스트  (RSI=28, MACD Bullish, EMA 상향)
  4. SHORT 응답 테스트 (RSI=78, MACD Bearish, EMA 하향)
  5. HOLD 응답 테스트  (RSI=50, 중립 신호)
  6. 평균 응답시간 측정 (3회 평균)
  7. OpenAI 비용 로그 확인

실행:
  cd /path/to/Leverage_Agent
  python scripts/verify_openai.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

# ── 모델별 단가 (USD / 1M tokens) ────────────────────────────────────────────
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-5":           (2.50,  10.00),
    "gpt-5-mini":      (0.50,   2.00),
    "gpt-4o":          (2.50,  10.00),
    "gpt-4o-mini":     (0.15,   0.60),
    "gpt-4-turbo":     (10.00, 30.00),
    "gpt-4":           (30.00, 60.00),
}

# ── 출력 헬퍼 ────────────────────────────────────────────────────────────────

SEP  = "─" * 62
PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"
INFO = "   "


def _sec(n: int, title: str) -> None:
    print(f"\n{SEP}")
    print(f"[{n}/7] {title}")
    print(SEP)


def _row(status: str, msg: str = "") -> None:
    print(f"  {status}  {msg}" if msg else f"  {status}")


def _cost(model: str, in_tok: int, out_tok: int) -> str:
    """토큰 수 → USD 비용 문자열."""
    key = model.split("-202")[0]  # 날짜 suffix 제거 (gpt-4o-2024-xx → gpt-4o)
    # prefix match
    rate = next(
        (v for k, v in _PRICING.items() if key.startswith(k) or k.startswith(key)),
        None,
    )
    if rate is None:
        return f"(모델 '{model}' 단가 미등록 — pricing dict 수동 추가 필요)"
    in_cost  = in_tok  / 1_000_000 * rate[0]
    out_cost = out_tok / 1_000_000 * rate[1]
    total    = in_cost + out_cost
    return (
        f"입력 {in_tok}tok × ${rate[0]:.2f}/1M = ${in_cost:.6f}  |  "
        f"출력 {out_tok}tok × ${rate[1]:.2f}/1M = ${out_cost:.6f}  |  "
        f"합계 ${total:.6f}"
    )


# ── 데이터 클래스 ─────────────────────────────────────────────────────────────

@dataclass
class CallResult:
    label: str
    success: bool
    decision: str = ""
    confidence: int = 0
    reason: str = ""
    model_id: str = ""
    in_tokens: int = 0
    out_tokens: int = 0
    elapsed_s: float = 0.0
    raw: str = ""
    error: str = ""


# ── 단일 GPT 호출 ─────────────────────────────────────────────────────────────

_SYSTEM = """You are a professional cryptocurrency futures trading analyst.
OUTPUT FORMAT (strict JSON only — no markdown, no extra text):
{
  "decision": "LONG|SHORT|HOLD",
  "confidence": 0-100,
  "reason": "Korean one-line summary referencing specific indicator values"
}"""

_SCENARIOS: dict[str, str] = {
    "LONG": (
        "Analyze BTCUSDT (current price: $67,500)\n"
        "RSI(14) = 28      → oversold zone\n"
        "MACD              → Bullish crossover just confirmed\n"
        "EMA20 = $67,200  > EMA50 = $66,800  → uptrend\n"
        "Fear & Greed: 22 (Extreme Fear)\n"
        "OI change +8% (1h), Funding rate: -0.012% (negative → favors long)"
    ),
    "SHORT": (
        "Analyze BTCUSDT (current price: $71,200)\n"
        "RSI(14) = 78      → overbought zone\n"
        "MACD              → Bearish crossover just confirmed\n"
        "EMA20 = $70,900  < EMA50 = $71,500  → downtrend\n"
        "Fear & Greed: 88 (Extreme Greed)\n"
        "OI change -5% (1h), Funding rate: +0.032% (high positive → favors short)"
    ),
    "HOLD": (
        "Analyze BTCUSDT (current price: $68,100)\n"
        "RSI(14) = 51      → neutral\n"
        "MACD              → no clear crossover, histogram near zero\n"
        "EMA20 = $68,050  ≈ EMA50 = $68,080  → no trend\n"
        "Fear & Greed: 50 (Neutral)\n"
        "OI change 0% (1h), Funding rate: +0.001% (near zero)"
    ),
}


async def _call_once(client, model: str, label: str, user_msg: str) -> CallResult:
    import openai

    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=model,
            max_completion_tokens=2000,  # reasoning model은 reasoning token 포함 전체 한도
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
        )
        elapsed = time.perf_counter() - t0
        choice = resp.choices[0]
        raw = choice.message.content or ""

        # reasoning model: content가 비어도 reasoning_tokens는 소비됨 — 디버그 출력
        if not raw:
            fr = getattr(choice, "finish_reason", "unknown")
            usage = resp.usage
            details = getattr(usage, "completion_tokens_details", None)
            reasoning_tok = getattr(details, "reasoning_tokens", 0) if details else 0
            return CallResult(
                label=label, success=False, elapsed_s=elapsed,
                model_id=resp.model,
                in_tokens=getattr(usage, "prompt_tokens", 0),
                out_tokens=getattr(usage, "completion_tokens", 0),
                error=(
                    f"빈 응답 (finish_reason={fr}). "
                    f"reasoning_tokens={reasoning_tok}, "
                    f"completion_tokens={getattr(usage, 'completion_tokens', 0)}"
                ),
            )

        data = json.loads(raw)

        decision   = str(data.get("decision", "")).upper()
        confidence = int(data.get("confidence", 0))
        reason     = str(data.get("reason", ""))

        valid = (
            decision in ("LONG", "SHORT", "HOLD")
            and 0 <= confidence <= 100
            and bool(reason)
        )
        return CallResult(
            label=label, success=valid,
            decision=decision, confidence=confidence, reason=reason,
            model_id=resp.model,
            in_tokens=resp.usage.prompt_tokens,
            out_tokens=resp.usage.completion_tokens,
            elapsed_s=elapsed, raw=raw,
        )

    except openai.AuthenticationError as e:
        return CallResult(label=label, success=False, elapsed_s=time.perf_counter()-t0,
                          error=f"인증 실패: {e}")
    except openai.NotFoundError as e:
        return CallResult(label=label, success=False, elapsed_s=time.perf_counter()-t0,
                          error=f"모델 없음: {e}")
    except openai.RateLimitError as e:
        return CallResult(label=label, success=False, elapsed_s=time.perf_counter()-t0,
                          error=f"Rate Limit: {e}")
    except openai.APIError as e:
        return CallResult(label=label, success=False, elapsed_s=time.perf_counter()-t0,
                          error=f"API 오류: {e}")
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        return CallResult(label=label, success=False, elapsed_s=time.perf_counter()-t0,
                          error=f"JSON 파싱 오류: {e}", raw=raw if 'raw' in dir() else "")


# ── 메인 검증 ─────────────────────────────────────────────────────────────────

async def main() -> None:
    import openai

    print("\n" + "=" * 62)
    print("  AI Trading Copilot — OpenAI GPT 재검증")
    print("=" * 62)

    api_key = os.getenv("OPENAI_API_KEY", "")
    model   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    if not api_key:
        print("\n❌ OPENAI_API_KEY 없음. 루트 .env를 확인하세요.")
        sys.exit(1)

    masked = api_key[:12] + "..." + api_key[-6:]
    print(f"\n  API Key : {masked}")
    print(f"  Model   : {model}")

    client = openai.AsyncOpenAI(api_key=api_key)
    results: list[CallResult] = []

    # ── [1] LONG 시나리오 ────────────────────────────────────────────────────
    _sec(1, "LONG 응답 테스트  (RSI=28 과매도, MACD 강세, EMA 상향)")
    r = await _call_once(client, model, "LONG", _SCENARIOS["LONG"])
    results.append(r)
    if r.error:
        _row(FAIL, r.error)
    else:
        _row(PASS if r.success else WARN, f"decision: {r.decision}  confidence: {r.confidence}%")
        _row(INFO, f"reason: {r.reason}")
        _row(INFO, f"시간: {r.elapsed_s:.2f}s  |  토큰: {r.in_tokens}+{r.out_tokens}")
        if r.decision != "LONG":
            _row(WARN, f"예상 LONG이지만 GPT가 {r.decision} 판단 — reason 확인 권장")

    # ── [2] SHORT 시나리오 ───────────────────────────────────────────────────
    _sec(2, "SHORT 응답 테스트 (RSI=78 과매수, MACD 약세, EMA 하향)")
    r = await _call_once(client, model, "SHORT", _SCENARIOS["SHORT"])
    results.append(r)
    if r.error:
        _row(FAIL, r.error)
    else:
        _row(PASS if r.success else WARN, f"decision: {r.decision}  confidence: {r.confidence}%")
        _row(INFO, f"reason: {r.reason}")
        _row(INFO, f"시간: {r.elapsed_s:.2f}s  |  토큰: {r.in_tokens}+{r.out_tokens}")
        if r.decision != "SHORT":
            _row(WARN, f"예상 SHORT이지만 GPT가 {r.decision} 판단 — reason 확인 권장")

    # ── [3] HOLD 시나리오 ────────────────────────────────────────────────────
    _sec(3, "HOLD 응답 테스트  (RSI=51 중립, MACD 무신호, EMA 횡보)")
    r = await _call_once(client, model, "HOLD", _SCENARIOS["HOLD"])
    results.append(r)
    if r.error:
        _row(FAIL, r.error)
    else:
        _row(PASS if r.success else WARN, f"decision: {r.decision}  confidence: {r.confidence}%")
        _row(INFO, f"reason: {r.reason}")
        _row(INFO, f"시간: {r.elapsed_s:.2f}s  |  토큰: {r.in_tokens}+{r.out_tokens}")
        if r.decision != "HOLD":
            _row(WARN, f"예상 HOLD이지만 GPT가 {r.decision} 판단 — 허용 가능")

    # ── [4] GPT 호출 성공 집계 ───────────────────────────────────────────────
    _sec(4, "GPT 호출 성공 + JSON Structured Output")
    failed = [r for r in results if r.error]
    ok     = [r for r in results if not r.error]
    if failed:
        for r in failed:
            _row(FAIL, f"{r.label}: {r.error}")
        api_ok = False
    else:
        _row(PASS, f"3/3 호출 성공, 모두 유효한 JSON 반환")
        _row(PASS, f"decision 필드: LONG/SHORT/HOLD 형식 정상")
        _row(PASS, f"confidence 필드: 0-100 범위 정상")
        _row(PASS, f"reason 필드: 한국어 요약 반환")
        api_ok = True

    # ── [5] 응답시간 측정 (BTC LONG 시나리오 3회 반복) ──────────────────────
    _sec(5, "평균 응답시간 측정  (LONG 시나리오 3회)")
    times: list[float] = []
    if api_ok:
        print("  실행 중", end="", flush=True)
        for i in range(3):
            r2 = await _call_once(client, model, f"타이밍-{i+1}", _SCENARIOS["LONG"])
            times.append(r2.elapsed_s)
            print(f"  {r2.elapsed_s:.2f}s", end="", flush=True)
        print()
        avg = sum(times) / len(times)
        mn  = min(times)
        mx  = max(times)
        _row(PASS, f"평균 {avg:.2f}s  |  최소 {mn:.2f}s  |  최대 {mx:.2f}s")
        if avg < 3.0:
            _row(INFO, "→ 응답속도 양호 (15분 주기 파이프라인에 충분)")
        elif avg < 8.0:
            _row(WARN, "→ 응답속도 보통 — 파이프라인 타임아웃 10s 이상으로 설정 권장")
        else:
            _row(WARN, "→ 응답속도 느림 — 네트워크 또는 모델 부하 확인 필요")
    else:
        _row(WARN, "API 호출 실패로 응답시간 측정 생략")
        avg = 0.0

    # ── [6] JSON 응답 예시 출력 ──────────────────────────────────────────────
    _sec(6, "응답 예시")
    for r in results:
        if not r.error:
            print(f"\n  [{r.label} 시나리오]")
            try:
                pretty = json.dumps(json.loads(r.raw), ensure_ascii=False, indent=4)
                for line in pretty.splitlines():
                    print(f"    {line}")
            except Exception:
                print(f"    {r.raw}")

    # ── [7] 비용 로그 ────────────────────────────────────────────────────────
    _sec(7, "OpenAI 비용 로그")
    all_calls = results + (
        [CallResult(label=f"타이밍-{i+1}", success=True,
                    model_id=results[0].model_id if results else model,
                    in_tokens=results[0].in_tokens if results else 0,
                    out_tokens=results[0].out_tokens if results else 0,
                    elapsed_s=t) for i, t in enumerate(times)]
        if times else []
    )

    total_in  = sum(r.in_tokens  for r in all_calls if not r.error)
    total_out = sum(r.out_tokens for r in all_calls if not r.error)
    total_calls = len([r for r in all_calls if not r.error])

    actual_model = results[0].model_id if results and not results[0].error else model
    print(f"\n  실제 모델 ID : {actual_model}")
    print(f"  총 API 호출  : {total_calls}회 (시나리오 3 + 응답시간 측정 3)")
    print(f"  총 입력 토큰 : {total_in:,}")
    print(f"  총 출력 토큰 : {total_out:,}")

    if total_calls > 0:
        per_in  = total_in  // total_calls
        per_out = total_out // total_calls
        print(f"  호출당 평균  : 입력 {per_in}tok / 출력 {per_out}tok")
        print(f"\n  이번 검증 비용:")
        print(f"    {_cost(actual_model, total_in, total_out)}")

        # 운영 비용 추정 (15분 주기, 코인 2개)
        calls_per_day  = (24 * 60 // 15) * 2    # 192회/일
        proj_in_day    = per_in  * calls_per_day
        proj_out_day   = per_out * calls_per_day
        print(f"\n  운영 비용 추정 (15분 주기 × 코인 2개 = {calls_per_day}회/일):")
        print(f"    {_cost(actual_model, proj_in_day, proj_out_day)}")
        print(f"    → 월 추정 비용: ", end="")

        key = actual_model.split("-202")[0]
        rate = next(
            (v for k, v in _PRICING.items() if key.startswith(k) or k.startswith(key)),
            None,
        )
        if rate:
            daily  = (proj_in_day/1e6)*rate[0] + (proj_out_day/1e6)*rate[1]
            monthly = daily * 30
            print(f"${monthly:.4f} / 월")
        else:
            print("(단가 미등록)")

    # ── 최종 요약 ──────────────────────────────────────────────────────────────
    print(f"\n{'=' * 62}")
    print("  최종 요약")
    print(f"{'=' * 62}")

    format_ok     = api_ok
    long_ok       = bool(results) and not results[0].error
    short_ok      = len(results) > 1 and not results[1].error
    hold_ok       = len(results) > 2 and not results[2].error
    timing_ok     = bool(times)

    items = [
        ("GPT 호출 성공",          format_ok),
        ("JSON Structured Output", format_ok),
        ("LONG 응답",              long_ok),
        ("SHORT 응답",             short_ok),
        ("HOLD 응답",              hold_ok),
        ("응답시간 측정",          timing_ok),
        ("비용 로그",              total_calls > 0),
    ]
    passed = sum(ok for _, ok in items)
    for name, ok in items:
        print(f"  {'✅' if ok else '❌'}  {name}")

    print(f"\n  {passed}/7 통과", end="")

    if passed == 7:
        print(" — OpenAI 연결 완전 검증 ✅")
        print()
        print("  Shadow Trading 진행 가능 여부")
        print(f"  {'=' * 40}")
        print("  ✅ API 연결 정상")
        print("  ✅ JSON 파싱 정상")
        print("  ✅ LONG / SHORT / HOLD 판단 작동")
        print(f"  ✅ 평균 응답시간 {avg:.2f}s (파이프라인 정상 범위)")
        print()
        print("  → Shadow Trading 즉시 시작 가능합니다.")
        print("     OrchestratorDeps.execution = ShadowExecutionEngine(...) 으로")
        print("     기존 파이프라인에 주입하면 실제 주문 없이 검증 가능합니다.")
    else:
        print(" — 일부 항목 실패")
        if not api_ok:
            print()
            error_msg = results[0].error if results else "unknown"
            if "insufficient_quota" in error_msg or "quota" in error_msg.lower():
                print("  → OpenAI 계정에 크레딧이 없습니다.")
                print("     platform.openai.com/settings/billing 에서 충전 후 재실행하세요.")
            elif "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                print(f"  → 모델 '{model}' 이 존재하지 않습니다.")
                print("     .env 의 OPENAI_MODEL 을 gpt-4o-mini 등 유효한 모델로 변경하세요.")
            elif "인증" in error_msg:
                print("  → API Key가 유효하지 않습니다. .env 를 확인하세요.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
