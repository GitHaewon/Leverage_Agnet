"""
MemorySearcher 통합 테스트.

Qdrant 클라이언트와 Claude API를 Mock으로 대체하여
외부 서비스 없이 검색 로직의 전체 흐름을 검증한다.

검증 대상:
  - search_similar_trades(): 유사 거래 검색 흐름
  - search_winning_patterns(): 수익 패턴 검색 (is_win=True 필터)
  - search_losing_patterns(): 손실 패턴 검색 (is_win=False 필터)
  - _synthesize(): Claude 호출 및 빈 hit 처리
  - _multi_search(): 다중 컬렉션 집계 + 점수 정렬
  - _build_filter_conditions(): user_id 필수, coin/direction/is_win 선택
  - TradeMemoryResult: win_rate, avg_pnl 계산
  - build_query_from_signal(): 쿼리 텍스트 자동 생성
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from app.memory.searcher import (
    MemorySearcher,
    PatternQuery,
    SearchCollection,
    SearchHit,
    SimilarTradeQuery,
    TradeMemoryResult,
    _build_filter_conditions,
    _resolve_collections,
    build_query_from_signal,
)
from app.memory.collections import (
    COLLECTION_JOURNALS,
    COLLECTION_REFLECTIONS,
    COLLECTION_STRATEGY,
)
from app.memory.store import MemoryStore


# ── 픽스처 ────────────────────────────────────────────────────────────────────

USER_ID = str(uuid.uuid4())


def _make_scored_point(
    *,
    score: float = 0.85,
    coin: str = "BTC",
    direction: str = "LONG",
    is_win: bool = True,
    net_pnl: float = 131.50,
    close_reason: str = "tp_hit",
    source: str = "journal",
) -> MagicMock:
    point = MagicMock()
    point.score = score
    point.payload = {
        "source": source,
        "user_id": USER_ID,
        "coin": coin,
        "direction": direction,
        "is_win": is_win,
        "net_pnl": net_pnl,
        "close_reason": close_reason,
    }
    return point


def _make_searcher(
    *,
    search_results: list | None = None,
    synthesis_text: str = "RSI 과매도 반등 패턴이 가장 효과적입니다.",
) -> tuple[MemorySearcher, AsyncMock, AsyncMock]:
    """Mock Qdrant + Claude를 주입한 MemorySearcher를 반환."""
    mock_qdrant = AsyncMock()
    mock_qdrant.search = AsyncMock(return_value=search_results or [])

    mock_store = MagicMock(spec=MemoryStore)
    mock_store._client = mock_qdrant
    mock_store._initialized = True

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=synthesis_text)]

    mock_anthropic = MagicMock(spec=anthropic.AsyncAnthropic)
    mock_anthropic.messages = MagicMock()
    mock_anthropic.messages.create = AsyncMock(return_value=mock_msg)

    searcher = MemorySearcher(store=mock_store, anthropic_client=mock_anthropic)
    return searcher, mock_qdrant, mock_anthropic


# ── TradeMemoryResult 계산 테스트 ─────────────────────────────────────────────

class TestTradeMemoryResult:

    def _make_hit(self, *, is_win: bool, net_pnl: float) -> SearchHit:
        return SearchHit(
            score=0.8,
            source="journal",
            coin="BTC",
            direction="LONG",
            is_win=is_win,
            net_pnl=net_pnl,
            close_reason="tp_hit",
            payload={},
        )

    def test_win_rate_all_wins(self) -> None:
        hits = [self._make_hit(is_win=True, net_pnl=100) for _ in range(4)]
        result = TradeMemoryResult(hits=hits, synthesis="", query="test")
        assert result.win_rate == pytest.approx(1.0)

    def test_win_rate_all_losses(self) -> None:
        hits = [self._make_hit(is_win=False, net_pnl=-50) for _ in range(3)]
        result = TradeMemoryResult(hits=hits, synthesis="", query="test")
        assert result.win_rate == pytest.approx(0.0)

    def test_win_rate_mixed(self) -> None:
        hits = [
            self._make_hit(is_win=True, net_pnl=100),
            self._make_hit(is_win=False, net_pnl=-50),
            self._make_hit(is_win=True, net_pnl=80),
            self._make_hit(is_win=False, net_pnl=-30),
        ]
        result = TradeMemoryResult(hits=hits, synthesis="", query="test")
        assert result.win_rate == pytest.approx(0.5)

    def test_avg_pnl_positive(self) -> None:
        hits = [
            self._make_hit(is_win=True, net_pnl=100),
            self._make_hit(is_win=True, net_pnl=200),
        ]
        result = TradeMemoryResult(hits=hits, synthesis="", query="test")
        assert result.avg_pnl == pytest.approx(150.0)

    def test_avg_pnl_empty_hits(self) -> None:
        result = TradeMemoryResult(hits=[], synthesis="", query="test")
        assert result.win_rate == pytest.approx(0.0)
        assert result.avg_pnl == pytest.approx(0.0)

    def test_total_found_matches_hits_length(self) -> None:
        hits = [self._make_hit(is_win=True, net_pnl=50) for _ in range(7)]
        result = TradeMemoryResult(hits=hits, synthesis="", query="test")
        assert result.total_found == 7


# ── SearchHit 변환 테스트 ─────────────────────────────────────────────────────

class TestSearchHit:

    def test_from_scored_point_maps_fields(self) -> None:
        point = _make_scored_point(score=0.92, coin="ETH", direction="SHORT")
        hit = SearchHit.from_scored_point(point)

        assert hit.score == pytest.approx(0.92)
        assert hit.coin == "ETH"
        assert hit.direction == "SHORT"
        assert hit.is_win is True

    def test_from_scored_point_empty_payload(self) -> None:
        point = MagicMock()
        point.score = 0.7
        point.payload = None

        hit = SearchHit.from_scored_point(point)
        assert hit.coin == ""
        assert hit.direction == ""
        assert hit.is_win is False
        assert hit.net_pnl == pytest.approx(0.0)

    def test_score_rounded_to_4_decimals(self) -> None:
        point = _make_scored_point(score=0.912345678)
        hit = SearchHit.from_scored_point(point)
        # round(0.912345678, 4) == 0.9123
        assert hit.score == pytest.approx(0.9123)


# ── _build_filter_conditions 테스트 ──────────────────────────────────────────

class TestBuildFilterConditions:

    def test_always_includes_user_id(self) -> None:
        conditions = _build_filter_conditions(user_id=USER_ID)
        keys = [c.key for c in conditions]
        assert "user_id" in keys

    def test_coin_added_when_provided(self) -> None:
        conditions = _build_filter_conditions(user_id=USER_ID, coin="BTC")
        keys = [c.key for c in conditions]
        assert "coin" in keys

    def test_direction_added_when_provided(self) -> None:
        conditions = _build_filter_conditions(user_id=USER_ID, direction="LONG")
        keys = [c.key for c in conditions]
        assert "direction" in keys

    def test_is_win_added_as_bool(self) -> None:
        conditions = _build_filter_conditions(user_id=USER_ID, is_win=True)
        keys = [c.key for c in conditions]
        assert "is_win" in keys

    def test_only_user_id_when_no_optional(self) -> None:
        conditions = _build_filter_conditions(user_id=USER_ID)
        assert len(conditions) == 1

    def test_all_conditions_when_fully_specified(self) -> None:
        conditions = _build_filter_conditions(
            user_id=USER_ID, coin="ETH", direction="SHORT", is_win=False
        )
        assert len(conditions) == 4


# ── _resolve_collections 테스트 ───────────────────────────────────────────────

class TestResolveCollections:

    def test_journals_only(self) -> None:
        result = _resolve_collections(SearchCollection.JOURNALS)
        assert result == [COLLECTION_JOURNALS]

    def test_reflections_only(self) -> None:
        result = _resolve_collections(SearchCollection.REFLECTIONS)
        assert result == [COLLECTION_REFLECTIONS]

    def test_strategy_only(self) -> None:
        result = _resolve_collections(SearchCollection.STRATEGY)
        assert result == [COLLECTION_STRATEGY]

    def test_all_returns_three_collections(self) -> None:
        result = _resolve_collections(SearchCollection.ALL)
        assert len(result) == 3
        assert COLLECTION_JOURNALS in result
        assert COLLECTION_REFLECTIONS in result
        assert COLLECTION_STRATEGY in result


# ── search_similar_trades 테스트 ──────────────────────────────────────────────

class TestSearchSimilarTrades:

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_returns_trade_memory_result(self, mock_embed: MagicMock) -> None:
        results = [_make_scored_point(score=0.88)]
        searcher, _, _ = _make_searcher(search_results=results)

        query = SimilarTradeQuery(
            query_text="BTC LONG RSI 과매도 진입",
            user_id=USER_ID,
        )
        result = await searcher.search_similar_trades(query)

        assert isinstance(result, TradeMemoryResult)
        assert len(result.hits) == 1
        assert result.hits[0].score == pytest.approx(0.88)

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_synthesis_text_included(self, mock_embed: MagicMock) -> None:
        results = [_make_scored_point()]
        searcher, _, _ = _make_searcher(
            search_results=results,
            synthesis_text="과매도 반등 패턴 검증됨",
        )

        query = SimilarTradeQuery(query_text="BTC LONG", user_id=USER_ID)
        result = await searcher.search_similar_trades(query)

        assert "과매도 반등 패턴" in result.synthesis

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_empty_hits_returns_empty_synthesis(self, mock_embed: MagicMock) -> None:
        searcher, _, _ = _make_searcher(search_results=[])

        query = SimilarTradeQuery(query_text="알 수 없는 상황", user_id=USER_ID)
        result = await searcher.search_similar_trades(query)

        assert result.total_found == 0
        assert result.synthesis == ""

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_coin_filter_passed_to_qdrant(self, mock_embed: MagicMock) -> None:
        searcher, mock_qdrant, _ = _make_searcher(search_results=[])

        query = SimilarTradeQuery(
            query_text="BTC LONG", user_id=USER_ID, coin="BTC"
        )
        await searcher.search_similar_trades(query)

        call_kwargs = mock_qdrant.search.call_args.kwargs
        must_conditions = call_kwargs["query_filter"].must
        keys = [c.key for c in must_conditions]
        assert "coin" in keys

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_query_stored_in_result(self, mock_embed: MagicMock) -> None:
        searcher, _, _ = _make_searcher(search_results=[])

        query = SimilarTradeQuery(query_text="RSI 과매도 BTC", user_id=USER_ID)
        result = await searcher.search_similar_trades(query)

        assert result.query == "RSI 과매도 BTC"


# ── search_winning_patterns 테스트 ────────────────────────────────────────────

class TestSearchWinningPatterns:

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_is_win_true_filter_sent(self, mock_embed: MagicMock) -> None:
        searcher, mock_qdrant, _ = _make_searcher(search_results=[])

        query = PatternQuery(query_text="BTC LONG RSI 과매도", user_id=USER_ID)
        await searcher.search_winning_patterns(query)

        # ALL 컬렉션 = 세 번 호출
        assert mock_qdrant.search.call_count == 3
        for call in mock_qdrant.search.call_args_list:
            must = call.kwargs["query_filter"].must
            keys = {c.key for c in must}
            assert "is_win" in keys

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_winning_synthesis_prompt_type(self, mock_embed: MagicMock) -> None:
        results = [_make_scored_point(is_win=True)]
        searcher, _, mock_anthropic = _make_searcher(search_results=results)

        query = PatternQuery(query_text="BTC", user_id=USER_ID)
        await searcher.search_winning_patterns(query)

        prompt = mock_anthropic.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "수익" in prompt

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_all_returned_hits_have_correct_is_win(self, mock_embed: MagicMock) -> None:
        results = [
            _make_scored_point(score=0.9, is_win=True),
            _make_scored_point(score=0.8, is_win=True),
        ]
        searcher, _, _ = _make_searcher(search_results=results)

        query = PatternQuery(
            query_text="BTC LONG",
            user_id=USER_ID,
            collection=SearchCollection.JOURNALS,
        )
        result = await searcher.search_winning_patterns(query)

        assert all(h.is_win for h in result.hits)
        assert result.win_rate == pytest.approx(1.0)


# ── search_losing_patterns 테스트 ─────────────────────────────────────────────

class TestSearchLosingPatterns:

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_is_win_false_filter_sent(self, mock_embed: MagicMock) -> None:
        searcher, mock_qdrant, _ = _make_searcher(search_results=[])

        query = PatternQuery(query_text="BTC SHORT", user_id=USER_ID)
        await searcher.search_losing_patterns(query)

        for call in mock_qdrant.search.call_args_list:
            must = call.kwargs["query_filter"].must
            is_win_conditions = [
                c for c in must if c.key == "is_win"
            ]
            assert len(is_win_conditions) == 1
            assert is_win_conditions[0].match.value is False

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_losing_synthesis_prompt_type(self, mock_embed: MagicMock) -> None:
        results = [_make_scored_point(is_win=False, net_pnl=-80)]
        searcher, _, mock_anthropic = _make_searcher(search_results=results)

        query = PatternQuery(query_text="ETH SHORT", user_id=USER_ID)
        await searcher.search_losing_patterns(query)

        prompt = mock_anthropic.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "손실" in prompt

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_negative_avg_pnl_for_all_losses(self, mock_embed: MagicMock) -> None:
        results = [
            _make_scored_point(is_win=False, net_pnl=-100),
            _make_scored_point(is_win=False, net_pnl=-60),
        ]
        searcher, _, _ = _make_searcher(search_results=results)

        query = PatternQuery(
            query_text="ETH SHORT",
            user_id=USER_ID,
            collection=SearchCollection.JOURNALS,
        )
        result = await searcher.search_losing_patterns(query)

        assert result.avg_pnl < 0


# ── _multi_search 집계 + 정렬 테스트 ─────────────────────────────────────────

class TestMultiSearch:

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_hits_sorted_by_score_descending(self, mock_embed: MagicMock) -> None:
        scored_points = [
            _make_scored_point(score=0.6),
            _make_scored_point(score=0.9),
            _make_scored_point(score=0.75),
        ]
        searcher, _, _ = _make_searcher(search_results=scored_points)

        query = SimilarTradeQuery(
            query_text="BTC LONG",
            user_id=USER_ID,
            collection=SearchCollection.JOURNALS,
        )
        result = await searcher.search_similar_trades(query)

        scores = [h.score for h in result.hits]
        assert scores == sorted(scores, reverse=True)

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_limit_applied_to_total_hits(self, mock_embed: MagicMock) -> None:
        # ALL 컬렉션: 각 컬렉션마다 limit=3개 반환 → 총 9개 → limit으로 3개만
        three_points = [_make_scored_point(score=0.8 - i * 0.05) for i in range(3)]
        searcher, mock_qdrant, _ = _make_searcher(search_results=three_points)

        query = PatternQuery(
            query_text="BTC LONG",
            user_id=USER_ID,
            collection=SearchCollection.ALL,
            limit=3,
        )
        result = await searcher.search_winning_patterns(query)

        assert len(result.hits) <= 3

    @patch("app.memory.searcher.embed_text", return_value=[0.1] * 384)
    async def test_qdrant_failure_in_one_collection_does_not_raise(
        self, mock_embed: MagicMock
    ) -> None:
        mock_qdrant = AsyncMock()
        mock_qdrant.search = AsyncMock(side_effect=Exception("Qdrant timeout"))

        mock_store = MagicMock(spec=MemoryStore)
        mock_store._client = mock_qdrant

        mock_anthropic = MagicMock(spec=anthropic.AsyncAnthropic)
        mock_anthropic.messages = MagicMock()
        mock_anthropic.messages.create = AsyncMock(
            return_value=MagicMock(content=[MagicMock(text="")])
        )

        searcher = MemorySearcher(store=mock_store, anthropic_client=mock_anthropic)

        query = SimilarTradeQuery(
            query_text="BTC LONG",
            user_id=USER_ID,
            collection=SearchCollection.JOURNALS,
        )
        # 예외 전파 없이 빈 결과 반환해야 한다
        result = await searcher.search_similar_trades(query)
        assert isinstance(result, TradeMemoryResult)
        assert result.total_found == 0


# ── _synthesize 테스트 ────────────────────────────────────────────────────────

class TestSynthesize:

    def _make_hit(self) -> SearchHit:
        return SearchHit(
            score=0.85,
            source="journal",
            coin="BTC",
            direction="LONG",
            is_win=True,
            net_pnl=131.5,
            close_reason="tp_hit",
            payload={},
        )

    async def test_returns_empty_string_for_no_hits(self) -> None:
        searcher, _, _ = _make_searcher()
        result = await searcher._synthesize("similar", [])
        assert result == ""

    async def test_calls_claude_with_correct_model(self) -> None:
        from app.core.config import settings
        _, _, mock_anthropic = _make_searcher()
        searcher, _, mock_anthropic = _make_searcher(
            search_results=[], synthesis_text="패턴 분석 완료"
        )

        # 직접 _synthesize 호출
        hits = [self._make_hit()]
        await searcher._synthesize("winning", hits)

        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert call_kwargs["model"] == settings.CLAUDE_MODEL

    async def test_returns_stripped_synthesis_text(self) -> None:
        searcher, _, _ = _make_searcher(synthesis_text="  RSI 과매도 성공 패턴  ")
        hits = [self._make_hit()]
        result = await searcher._synthesize("similar", hits)
        assert result == "RSI 과매도 성공 패턴"

    async def test_api_error_returns_empty_string(self) -> None:
        mock_store = MagicMock(spec=MemoryStore)
        mock_anthropic = MagicMock(spec=anthropic.AsyncAnthropic)
        mock_anthropic.messages = MagicMock()
        mock_anthropic.messages.create = AsyncMock(
            side_effect=anthropic.APIStatusError(
                "overloaded", response=MagicMock(status_code=529), body={}
            )
        )

        searcher = MemorySearcher(store=mock_store, anthropic_client=mock_anthropic)
        hits = [self._make_hit()]
        result = await searcher._synthesize("similar", hits)
        assert result == ""

    async def test_generic_exception_returns_empty_string(self) -> None:
        mock_store = MagicMock(spec=MemoryStore)
        mock_anthropic = MagicMock(spec=anthropic.AsyncAnthropic)
        mock_anthropic.messages = MagicMock()
        mock_anthropic.messages.create = AsyncMock(side_effect=RuntimeError("network error"))

        searcher = MemorySearcher(store=mock_store, anthropic_client=mock_anthropic)
        hits = [self._make_hit()]
        result = await searcher._synthesize("similar", hits)
        assert result == ""

    async def test_synthesis_includes_hit_info_in_prompt(self) -> None:
        searcher, _, mock_anthropic = _make_searcher(synthesis_text="OK")
        hits = [
            SearchHit(
                score=0.90,
                source="journal",
                coin="ETH",
                direction="SHORT",
                is_win=False,
                net_pnl=-48.50,
                close_reason="sl_hit",
                payload={},
            )
        ]
        await searcher._synthesize("losing", hits)

        prompt = mock_anthropic.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "ETH" in prompt
        assert "SHORT" in prompt
        assert "sl_hit" in prompt


# ── build_query_from_signal 테스트 ────────────────────────────────────────────

class TestBuildQueryFromSignal:

    def test_includes_coin_and_direction(self) -> None:
        text = build_query_from_signal("BTC", "LONG", [])
        assert "BTC" in text
        assert "LONG" in text

    def test_includes_first_three_reasons(self) -> None:
        reasons = ["RSI 과매도", "EMA200 지지", "Funding Rate 음수", "Volume 급증"]
        text = build_query_from_signal("BTC", "LONG", reasons)
        assert "RSI 과매도" in text
        assert "EMA200 지지" in text
        assert "Funding Rate 음수" in text
        # 4번째는 포함되지 않아야 함
        assert "Volume 급증" not in text

    def test_includes_tech_score(self) -> None:
        text = build_query_from_signal("ETH", "SHORT", [], tech_score=0.72)
        assert "기술점수" in text
        assert "+0.72" in text

    def test_includes_market_score(self) -> None:
        text = build_query_from_signal("ETH", "SHORT", [], market_score=-0.31)
        assert "시장점수" in text
        assert "-0.31" in text

    def test_empty_reasons_still_builds_query(self) -> None:
        text = build_query_from_signal("BTC", "LONG", [])
        assert len(text) > 0

    def test_pipe_separator_used(self) -> None:
        text = build_query_from_signal("BTC", "LONG", ["RSI 과매도"], tech_score=0.5)
        assert "|" in text
