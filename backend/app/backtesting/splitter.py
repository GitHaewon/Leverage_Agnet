"""
Walk Forward Testing Engine — Rolling Window 분할기.

전략:
  cursor를 step_days씩 이동하며 IS/OOS 윈도우 쌍을 생성한다.
  OOS 끝이 데이터 범위를 벗어나면 중단한다.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .types import WalkForwardConfig


def split_windows(
    ohlcv: pd.DataFrame,
    config: WalkForwardConfig,
) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Rolling Window로 (IS DataFrame, OOS DataFrame) 쌍 목록을 반환한다.

    각 윈도우:
      IS  = [cursor, cursor + is_window_days)
      OOS = [cursor + is_window_days, cursor + is_window_days + oos_window_days)
    cursor를 step_days씩 전진하며 OOS가 데이터 범위 내에 있는 동안 반복.
    """
    if ohlcv.empty:
        return []

    start = ohlcv.index[0]
    end = ohlcv.index[-1]

    is_delta = timedelta(days=config.is_window_days)
    oos_delta = timedelta(days=config.oos_window_days)
    step_delta = timedelta(days=config.step_days)

    windows: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    cursor = start

    while True:
        is_start = cursor
        is_end = cursor + is_delta
        oos_start = is_end
        oos_end = oos_start + oos_delta

        if oos_end > end:
            break

        is_df = ohlcv.loc[(ohlcv.index >= is_start) & (ohlcv.index < is_end)]
        oos_df = ohlcv.loc[(ohlcv.index >= oos_start) & (ohlcv.index < oos_end)]

        if not is_df.empty and not oos_df.empty:
            windows.append((is_df, oos_df))

        cursor = cursor + step_delta

    return windows
