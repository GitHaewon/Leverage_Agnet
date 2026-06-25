#!/usr/bin/env python
"""
Shadow trading funnel analysis — shadow_decisions 테이블에서 직접 집계.

실행:
    cd backend
    python scripts/analyze_shadow_funnel.py
    python scripts/analyze_shadow_funnel.py --user <user_id>
    python scripts/analyze_shadow_funnel.py --coin BTC
    python scripts/analyze_shadow_funnel.py --days 7

출력 해석:
    rejection_stage 분포가 어디에 집중되는지를 보고 bottleneck을 파악한다.
    DECISION_ENGINE > 80%  → MAX_RISK_SCORE / MIN_LONG_SCORE 튜닝 필요
    RISK_ENGINE     > 50%  → GLOBAL_MIN_RISK_REWARD_RATIO / R:R 계산 점검
    AI_REVIEW       > 50%  → 후보 품질 자체가 낮거나 AI가 너무 보수적
    executed/total  < 5%   → 전체 게이트가 너무 빡빡 → shadow 완화 프로파일 검토
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def run(user_id: str | None, coin: str | None, days: int) -> None:
    from sqlalchemy import select, and_, cast, String
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL 환경변수 미설정")
        sys.exit(1)

    for prefix in ("postgresql://", "postgres://"):
        if db_url.startswith(prefix):
            db_url = "postgresql+asyncpg://" + db_url[len(prefix):]
            break

    engine = create_async_engine(db_url, echo=False)
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with sf() as session:
            from app.models.shadow_decision import ShadowDecision

            since = datetime.now(timezone.utc) - timedelta(days=days)
            filters = [ShadowDecision.decided_at >= since]
            if user_id:
                filters.append(cast(ShadowDecision.user_id, String) == user_id)
            if coin:
                filters.append(ShadowDecision.coin == coin.upper())

            stmt = select(ShadowDecision).where(and_(*filters)).order_by(
                ShadowDecision.decided_at.desc()
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        if not rows:
            print(f"데이터 없음 (기간: 최근 {days}일)")
            return

        _print_report(rows, days)
    finally:
        await engine.dispose()


def _print_report(rows: list, days: int) -> None:
    total = len(rows)
    executed = [r for r in rows if r.final_action in ("LONG", "SHORT")]
    held = [r for r in rows if r.final_action == "HOLD"]

    stages = Counter(r.rejection_stage for r in rows if r.rejection_stage)
    regimes = Counter(r.market_regime for r in rows if r.market_regime)
    strategies = Counter(r.strategy_type for r in rows if r.strategy_type)
    final_actions = Counter(r.final_action for r in rows)

    ai_rows = [r for r in rows if r.ai_decision is not None]
    ai_approve = [r for r in ai_rows if r.ai_decision == "APPROVE"]
    confidences = [
        float(r.ai_confidence) for r in rows if r.ai_confidence is not None
    ]

    since_date = min(r.decided_at for r in rows).strftime("%Y-%m-%d %H:%M")
    until_date = max(r.decided_at for r in rows).strftime("%Y-%m-%d %H:%M")

    _hr()
    print(f"  SHADOW FUNNEL REPORT  (최근 {days}일: {since_date} ~ {until_date})")
    _hr()

    print(f"\n[총 사이클]  {total:,}건")
    print(f"  EXECUTED : {len(executed):,}건  ({_pct(len(executed), total):.1f}%)")
    print(f"  HELD     : {len(held):,}건  ({_pct(len(held), total):.1f}%)")

    print(f"\n[최종 action 분포]")
    for action, cnt in sorted(final_actions.items()):
        print(f"  {action:<6} : {cnt:,}건  ({_pct(cnt, total):.1f}%)")

    print(f"\n[rejection_stage 분포] (미실행 사이클의 탈락 위치)")
    stage_order = ["DECISION_ENGINE", "AI_REVIEW", "RISK_ENGINE", "POSITION_LIMIT", None]
    stage_total = sum(stages.values())
    if stage_total:
        for stage in stage_order:
            cnt = stages.get(stage, 0)
            label = stage or "(stage 없음 — 실행됨)"
            bar = "█" * int(20 * cnt / max(stage_total, 1))
            print(f"  {label:<20} : {cnt:>5,}건  {bar}")
        print(f"  기타")
        for s, cnt in stages.items():
            if s not in stage_order:
                print(f"    {s}: {cnt:,}건")
    else:
        print("  (rejection_stage 기록 없음)")

    print(f"\n[전략 유형 분포]")
    for strategy, cnt in strategies.most_common():
        print(f"  {strategy:<20} : {cnt:,}건  ({_pct(cnt, total):.1f}%)")

    print(f"\n[시장 국면 분포]")
    for regime, cnt in regimes.most_common():
        print(f"  {regime:<20} : {cnt:,}건  ({_pct(cnt, total):.1f}%)")

    print(f"\n[AI 리뷰 통계]")
    if ai_rows:
        approve_rate = _pct(len(ai_approve), len(ai_rows))
        print(f"  리뷰 실행 : {len(ai_rows):,}건  ({_pct(len(ai_rows), total):.1f}%)")
        print(f"  APPROVE   : {len(ai_approve):,}건  ({approve_rate:.1f}%)")
        print(f"  REJECT    : {len(ai_rows) - len(ai_approve):,}건  ({100 - approve_rate:.1f}%)")
        if confidences:
            print(f"  avg confidence : {mean(confidences):.3f}")
    else:
        print("  (AI 리뷰 기록 없음)")

    print(f"\n[진단 힌트]")
    if total == 0:
        print("  ⚠ 데이터 없음 — SHADOW_TRADING_ENABLED=true 여부 확인")
    elif len(executed) / total < 0.03:
        print("  ⚠ 체결률 < 3% — 게이트가 너무 빡빡하거나 regime이 UNKNOWN/HIGH_VOL 위주")
    if stages.get("DECISION_ENGINE", 0) > stage_total * 0.7:
        print("  ⚠ DECISION_ENGINE 탈락 > 70% — MAX_RISK_SCORE / MIN_LONG_SCORE 완화 검토")
    if stages.get("RISK_ENGINE", 0) > stage_total * 0.4:
        print("  ⚠ RISK_ENGINE 탈락 > 40% — R:R 계산 또는 risk 게이트 점검")
    if stages.get("AI_REVIEW", 0) > stage_total * 0.4:
        print("  ⚠ AI_REVIEW 탈락 > 40% — 후보 품질 또는 confidence 임계값 점검")
    if regimes.get("UNKNOWN", 0) + regimes.get("HIGH_VOLATILITY", 0) > total * 0.5:
        print("  ⚠ UNKNOWN/HIGH_VOL 국면 > 50% — regime 분류 파라미터 점검")
    if len(executed) >= 30:
        print(f"  ✓ 체결 {len(executed)}건 확보 — win rate 분석 가능")
    else:
        print(f"  ⚠ 체결 {len(executed)}건 (통계적 유의 기준 30건 미충족)")

    _hr()


def _hr() -> None:
    print("─" * 60)


def _pct(part: int, total: int) -> float:
    return 100.0 * part / total if total else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Shadow funnel analysis from DB")
    parser.add_argument("--user", default=None, help="user_id 필터")
    parser.add_argument("--coin", default=None, help="코인 필터 (BTC, ETH)")
    parser.add_argument("--days", type=int, default=14, help="분석 기간(일), 기본 14")
    args = parser.parse_args()

    asyncio.run(run(args.user, args.coin, args.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
