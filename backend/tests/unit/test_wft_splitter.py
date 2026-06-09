"""
Rolling Window 분할기 단위 테스트 (12 tests).

검증 대상:
  - split_windows: IS/OOS 쌍 생성, 경계 처리, 데이터 부족 시 빈 목록
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.backtesting.splitter import split_windows
from app.backtesting.types import WalkForwardConfig

UTC = timezone.utc


def _make_ohlcv(start: datetime, end: datetime, freq: str = "1h") -> pd.DataFrame:
    idx = pd.date_range(start=start, end=end, freq=freq, tz=UTC)
    n = len(idx)
    return pd.DataFrame(
        {
            "open":   [100.0] * n,
            "high":   [105.0] * n,
            "low":    [95.0] * n,
            "close":  [102.0] * n,
            "volume": [1_000.0] * n,
        },
        index=idx,
    )


def _config(is_days: int = 90, oos_days: int = 30, step_days: int = 30) -> WalkForwardConfig:
    return WalkForwardConfig(
        is_window_days=is_days,
        oos_window_days=oos_days,
        step_days=step_days,
    )


class TestWindowSplitter:
    def test_produces_windows_for_sufficient_data(self) -> None:
        ohlcv = _make_ohlcv(
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
        )
        windows = split_windows(ohlcv, _config())
        assert len(windows) > 0

    def test_empty_df_returns_empty(self) -> None:
        empty = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([]),
        )
        assert split_windows(empty, _config()) == []

    def test_insufficient_data_returns_empty(self) -> None:
        # 31일 < 90 + 30 = 120일
        ohlcv = _make_ohlcv(
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 2, 1, tzinfo=UTC),
        )
        assert split_windows(ohlcv, _config()) == []

    def test_each_window_is_tuple_of_two_dfs(self) -> None:
        ohlcv = _make_ohlcv(
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 6, 1, tzinfo=UTC),
        )
        for is_df, oos_df in split_windows(ohlcv, _config()):
            assert isinstance(is_df, pd.DataFrame)
            assert isinstance(oos_df, pd.DataFrame)
            assert not is_df.empty
            assert not oos_df.empty

    def test_is_before_oos(self) -> None:
        ohlcv = _make_ohlcv(
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 6, 1, tzinfo=UTC),
        )
        for is_df, oos_df in split_windows(ohlcv, _config()):
            assert is_df.index[-1] < oos_df.index[0]

    def test_no_overlap_between_is_and_oos(self) -> None:
        ohlcv = _make_ohlcv(
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 6, 1, tzinfo=UTC),
        )
        for is_df, oos_df in split_windows(ohlcv, _config()):
            is_timestamps = set(is_df.index)
            oos_timestamps = set(oos_df.index)
            assert is_timestamps.isdisjoint(oos_timestamps)

    def test_windows_advance_by_step(self) -> None:
        ohlcv = _make_ohlcv(
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 6, 1, tzinfo=UTC),
        )
        windows = split_windows(ohlcv, _config(step_days=30))
        if len(windows) >= 2:
            start1 = windows[0][0].index[0]
            start2 = windows[1][0].index[0]
            diff_days = (start2 - start1).days
            assert 29 <= diff_days <= 31

    def test_is_length_approximately_is_days(self) -> None:
        ohlcv = _make_ohlcv(
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 6, 1, tzinfo=UTC),
        )
        for is_df, _ in split_windows(ohlcv, _config(is_days=90)):
            days = (is_df.index[-1] - is_df.index[0]).days
            assert 85 <= days <= 95

    def test_oos_length_approximately_oos_days(self) -> None:
        ohlcv = _make_ohlcv(
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 6, 1, tzinfo=UTC),
        )
        for _, oos_df in split_windows(ohlcv, _config(oos_days=30)):
            days = (oos_df.index[-1] - oos_df.index[0]).days
            assert 25 <= days <= 35

    def test_large_step_produces_fewer_windows(self) -> None:
        ohlcv = _make_ohlcv(
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 6, 1, tzinfo=UTC),
        )
        w30 = split_windows(ohlcv, _config(step_days=30))
        w60 = split_windows(ohlcv, _config(step_days=60))
        assert len(w30) > len(w60)

    def test_exact_minimum_data_produces_one_window(self) -> None:
        # 정확히 IS + OOS = 120일 데이터
        ohlcv = _make_ohlcv(
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 5, 1, tzinfo=UTC),  # 121일
        )
        windows = split_windows(ohlcv, _config())
        assert len(windows) >= 1

    def test_windows_are_in_chronological_order(self) -> None:
        ohlcv = _make_ohlcv(
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 6, 1, tzinfo=UTC),
        )
        windows = split_windows(ohlcv, _config())
        for i in range(1, len(windows)):
            prev_is_start = windows[i - 1][0].index[0]
            curr_is_start = windows[i][0].index[0]
            assert curr_is_start > prev_is_start
