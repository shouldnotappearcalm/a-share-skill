#!/usr/bin/env python3
"""Regression tests for realtime intraday aggregation."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import sys

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import fetch_realtime  # noqa: E402


def _frame(rows: list[tuple[str, float, float, float, float, int]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"])
    return df.set_index("time")


def test_aggregate_intraday_data_drops_forming_bar() -> None:
    minute_df = _frame(
        [
            ("2026-06-16 14:55:00", 9.9, 10.5, 9.8, 10.2, 800),
            ("2026-06-17 09:30:00", 10.1, 10.2, 10.0, 10.15, 100),
            ("2026-06-17 10:30:00", 10.2, 10.5, 10.1, 10.4, 200),
            ("2026-06-17 10:35:00", 10.4, 10.8, 10.3, 10.7, 300),
        ]
    )

    result = fetch_realtime._aggregate_intraday_data(
        minute_df,
        date(2026, 6, 17),
        now=datetime(2026, 6, 17, 10, 37, 0),
        freq_minutes=5,
    )

    assert result["open"] == 10.1
    assert result["high"] == 10.5
    assert result["low"] == 10.0
    assert result["close"] == 10.4
    assert result["volume"] == 300
    assert result["bar_time"] == pd.Timestamp("2026-06-17 10:30:00")


if __name__ == "__main__":
    test_aggregate_intraday_data_drops_forming_bar()
    print("PASS test_fetch_realtime_intraday")
