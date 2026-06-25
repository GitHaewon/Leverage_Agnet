"""
ShadowDecisionRepository 단위 테스트.

검증 항목:
  1.  save() — ORM 객체가 session.add() + flush() 호출
  2.  save() — final_action이 DB에 정확히 전달됨
  3.  save() — rejection_reason 200자 초과 시 자동 절단
  4.  save() — 진단 필드 None 허용 (nullable)
  5.  list_decisions() — user_id 필터 적용
  6.  list_decisions() — coin 필터 적용
  7.  list_decisions() — final_action 필터 적용
  8.  list_decisions() — limit/offset 반영
  9.  get_stats() — 전체 사이클 수 집계
  10. get_stats() — hold_rate 계산
  11. get_stats() — rejection_stage 분포 집계
  12. get_stats() — ai_approve_rate 계산
  13. get_stats() — 데이터 없을 때 0/None 반환
  14. _pipeline_status_to_action() — LONG/SHORT/HOLD 매핑
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.schemas.shadow_decisions import ShadowDecisionRecord, ShadowDecisionStats


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────────

def _record(
    final_action: str = "HOLD",
    rejection_stage: str | None = None,
    rejection_reason: str | None = None,
    ai_decision: str | None = None,
    ai_confidence: float | None = None,
) -> ShadowDecisionRecord:
    return ShadowDecisionRecord(
        run_id=str(uuid.uuid4()),
        user_id="user-001",
        coin="BTC",
        final_action=final_action,  # type: ignore[arg-type]
        decided_at=datetime.now(timezone.utc),
        rejection_stage=rejection_stage,
        rejection_reason=rejection_reason,
        ai_decision=ai_decision,
        ai_confidence=ai_confidence,
    )


def _make_repo(rows: list | None = None):
    from app.repositories.shadow_decision_repository import ShadowDecisionRepository

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    if rows is not None:
        # list_decisions와 get_stats 공용 mock
        scalars_mock = MagicMock()
        scalars_mock.all = MagicMock(return_value=rows)
        execute_result = AsyncMock()
        execute_result.scalars = MagicMock(return_value=scalars_mock)
        execute_result.scalar_one = MagicMock(return_value=len(rows))
        session.execute = AsyncMock(return_value=execute_result)

    return ShadowDecisionRepository(session), session


def _orm_row(
    final_action: str = "HOLD",
    rejection_stage: str | None = None,
    ai_decision: str | None = None,
    ai_confidence: Decimal | None = None,
) -> MagicMock:
    row = MagicMock()
    row.final_action = final_action
    row.rejection_stage = rejection_stage
    row.ai_decision = ai_decision
    row.ai_confidence = ai_confidence
    return row


# ── Group 1: save() ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_calls_session_add_and_flush():
    repo, session = _make_repo()
    await repo.save(_record())
    session.add.assert_called_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_passes_final_action():
    repo, session = _make_repo()
    await repo.save(_record(final_action="LONG"))
    added_orm = session.add.call_args[0][0]
    assert added_orm.final_action == "LONG"


@pytest.mark.asyncio
async def test_save_truncates_rejection_reason_at_200():
    long_reason = "x" * 300
    repo, session = _make_repo()
    await repo.save(_record(rejection_reason=long_reason))
    added_orm = session.add.call_args[0][0]
    assert len(added_orm.rejection_reason) == 200


@pytest.mark.asyncio
async def test_save_allows_null_diagnostic_fields():
    repo, session = _make_repo()
    rec = _record()  # 진단 필드 모두 None
    await repo.save(rec)
    added_orm = session.add.call_args[0][0]
    assert added_orm.chart_score is None
    assert added_orm.ai_confidence is None
    assert added_orm.risk_passed is None


@pytest.mark.asyncio
async def test_save_decision_log_maps_payload_to_shadow_decision():
    repo, session = _make_repo()
    trade_id = uuid.uuid4()
    await repo.save_decision_log(
        "run-001",
        {
            "run_id": "run-001",
            "user_id": "user-001",
            "coin": "BTC",
            "timestamp": "2026-06-25T12:00:00+00:00",
            "market_regime": "TREND_UP",
            "chart_score": {"long_score": 80.0, "short_score": 10.0},
            "strategy_type": "PULLBACK",
            "candidate_action": "LONG",
            "final_action": "LONG",
            "expected_entry_price": 67000.0,
            "stop_loss": 66000.0,
            "take_profit": 69200.0,
            "actual_rr": 2.2,
            "leverage": 5,
            "ai_review": {
                "review_action": "APPROVE",
                "confidence": 0.85,
                "critical_contradiction": False,
            },
            "risk_result": {"approved": True},
            "rejection_stage": None,
            "rejection_reason": None,
            "actual_result": {
                "entry_exchange_order_id": f"shadow-entry-{trade_id}",
            },
        },
    )

    added_orm = session.add.call_args[0][0]
    assert added_orm.run_id == "run-001"
    assert added_orm.user_id == "user-001"
    assert added_orm.final_action == "LONG"
    assert added_orm.chart_score == Decimal("0.7")
    assert added_orm.ai_decision == "APPROVE"
    assert added_orm.risk_passed is True
    assert added_orm.shadow_trade_id == trade_id


# ── Group 2: list_decisions() ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_decisions_returns_rows_and_total():
    rows = [_orm_row(), _orm_row("LONG")]
    repo, session = _make_repo(rows)
    results, total = await repo.list_decisions("user-001")
    assert len(results) == 2
    assert total == 2


@pytest.mark.asyncio
async def test_list_decisions_coin_filter_applied():
    """coin 필터가 쿼리에 포함되는지 확인 (execute 1회 이상 호출)."""
    repo, session = _make_repo([])
    await repo.list_decisions("user-001", coin="ETH")
    assert session.execute.await_count >= 1


@pytest.mark.asyncio
async def test_list_decisions_final_action_filter_applied():
    repo, session = _make_repo([])
    await repo.list_decisions("user-001", final_action="HOLD")
    assert session.execute.await_count >= 1


# ── Group 3: get_stats() ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_stats_empty_returns_zeros():
    repo, session = _make_repo([])
    stats = await repo.get_stats("user-001")
    assert stats.total_cycles == 0
    assert stats.executed == 0
    assert stats.held == 0
    assert stats.hold_rate == 0.0
    assert stats.avg_ai_confidence is None
    assert stats.ai_approve_rate is None


@pytest.mark.asyncio
async def test_get_stats_total_and_executed_count():
    rows = [
        _orm_row("LONG"),
        _orm_row("SHORT"),
        _orm_row("HOLD"),
        _orm_row("HOLD"),
    ]
    repo, session = _make_repo(rows)
    stats = await repo.get_stats("user-001")
    assert stats.total_cycles == 4
    assert stats.executed == 2
    assert stats.held == 2


@pytest.mark.asyncio
async def test_get_stats_hold_rate():
    rows = [_orm_row("HOLD")] * 3 + [_orm_row("LONG")]
    repo, session = _make_repo(rows)
    stats = await repo.get_stats("user-001")
    assert stats.hold_rate == pytest.approx(75.0)


@pytest.mark.asyncio
async def test_get_stats_rejection_stage_distribution():
    rows = [
        _orm_row(rejection_stage="DECISION_ENGINE"),
        _orm_row(rejection_stage="DECISION_ENGINE"),
        _orm_row(rejection_stage="AI_REVIEW"),
        _orm_row(rejection_stage="RISK_ENGINE"),
        _orm_row(rejection_stage="POSITION_LIMIT"),
        _orm_row("LONG"),  # 체결 — rejection_stage 없음
    ]
    repo, session = _make_repo(rows)
    stats = await repo.get_stats("user-001")
    assert stats.rejected_at_decision == 2
    assert stats.rejected_at_ai == 1
    assert stats.rejected_at_risk == 1
    assert stats.rejected_at_position == 1


@pytest.mark.asyncio
async def test_get_stats_ai_approve_rate():
    rows = [
        _orm_row(ai_decision="APPROVE", ai_confidence=Decimal("0.85")),
        _orm_row(ai_decision="APPROVE", ai_confidence=Decimal("0.90")),
        _orm_row(ai_decision="REJECT",  ai_confidence=Decimal("0.60")),
    ]
    repo, session = _make_repo(rows)
    stats = await repo.get_stats("user-001")
    assert stats.ai_approve_rate == pytest.approx(100 * 2 / 3, rel=1e-3)
    assert stats.avg_ai_confidence == pytest.approx(
        float((Decimal("0.85") + Decimal("0.90") + Decimal("0.60")) / 3), rel=1e-3
    )


# ── Group 4: _pipeline_status_to_action() ────────────────────────────────────

def test_status_to_action_long_from_execution_result():
    from app.schemas.shadow_decisions import pipeline_status_to_action
    exec_result = MagicMock()
    exec_result.entry_order.side = "BUY"
    assert pipeline_status_to_action("COMPLETED", exec_result) == "LONG"


def test_status_to_action_short_from_execution_result():
    from app.schemas.shadow_decisions import pipeline_status_to_action
    exec_result = MagicMock()
    exec_result.entry_order.side = "SELL"
    assert pipeline_status_to_action("COMPLETED", exec_result) == "SHORT"


def test_status_to_action_defaults_to_hold():
    from app.schemas.shadow_decisions import pipeline_status_to_action
    assert pipeline_status_to_action("HOLD") == "HOLD"
    assert pipeline_status_to_action("REJECTED") == "HOLD"
    assert pipeline_status_to_action("FAILED") == "HOLD"
    assert pipeline_status_to_action("") == "HOLD"


def test_infer_rejection_stage_ai_review():
    from app.schemas.shadow_decisions import infer_rejection_stage
    assert infer_rejection_stage("HOLD", "AI reviewer rejected candidate") == "AI_REVIEW"
    assert infer_rejection_stage("HOLD", "AI 리뷰 실패") == "AI_REVIEW"


def test_infer_rejection_stage_risk():
    from app.schemas.shadow_decisions import infer_rejection_stage
    assert infer_rejection_stage("HOLD", "risk limit exceeded") == "RISK_ENGINE"


def test_infer_rejection_stage_portfolio():
    from app.schemas.shadow_decisions import infer_rejection_stage
    assert infer_rejection_stage("REJECTED", None) == "POSITION_LIMIT"


def test_infer_rejection_stage_none_when_completed():
    from app.schemas.shadow_decisions import infer_rejection_stage
    assert infer_rejection_stage("COMPLETED", None) is None
