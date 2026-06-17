#!/usr/bin/env python3
"""Regression tests for intraday snapshot aggregation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import sys

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from paper_trading.market_data import MarketDataProvider  # noqa: E402


def _frame(rows: list[tuple[str, float, float, float, float, int]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"])
    return df.set_index("time")


def test_latest_history_snapshot_uses_only_closed_today_bars() -> None:
    provider = MarketDataProvider()
    day_df = _frame(
        [
            ("2026-06-16 15:00:00", 9.8, 10.1, 9.7, 10.0, 1000),
            ("2026-06-17 15:00:00", 10.1, 10.6, 10.0, 10.4, 1200),
        ]
    )
    minute_df = _frame(
        [
            ("2026-06-16 14:55:00", 9.9, 10.5, 9.8, 10.2, 800),
            ("2026-06-17 09:30:00", 10.1, 10.2, 10.0, 10.15, 100),
            ("2026-06-17 10:30:00", 10.2, 10.5, 10.1, 10.4, 200),
            ("2026-06-17 10:35:00", 10.4, 10.8, 10.3, 10.7, 300),
        ]
    )

    with patch("paper_trading.market_data.get_price", side_effect=[day_df, minute_df]), patch(
        "paper_trading.market_data.datetime"
    ) as dt_mock:
        dt_mock.now.return_value = datetime(2026, 6, 17, 10, 37, 0)
        snapshot = provider._latest_history_snapshot("600000")

    assert snapshot.open == 10.1
    assert snapshot.high == 10.5
    assert snapshot.low == 10.0
    assert snapshot.price == 10.4
    assert snapshot.volume == 300
    assert snapshot.timestamp == "2026-06-17 10:30:00"
    assert snapshot.source == "tencent/sina-minute-closed"


def test_get_quote_recomputes_timestamp_and_change_pct_from_qt() -> None:
    provider = MarketDataProvider()
    with patch.object(
        provider,
        "_latest_history_snapshot",
    ) as latest_mock, patch("paper_trading.market_data._parse_tencent_quote") as parse_mock:
        latest_mock.return_value = type("Snapshot", (), {})()
        snapshot = latest_mock.return_value
        snapshot.symbol = "600000"
        snapshot.name = "600000"
        snapshot.price = 10.4
        snapshot.open = 10.1
        snapshot.high = 10.5
        snapshot.low = 10.0
        snapshot.prev_close = 10.0
        snapshot.volume = 300
        snapshot.change_pct = 4.0
        snapshot.timestamp = "2026-06-17 10:30:00"
        snapshot.source = "tencent/sina-minute-closed"
        snapshot.limit_up = None
        snapshot.limit_down = None
        provider._realtime_session.get = lambda *args, **kwargs: type("Resp", (), {"text": "mock"})()
        parse_mock.return_value = {
            "name": "浦发银行",
            "price": 10.8,
            "open": 10.2,
            "high": 10.9,
            "low": 10.1,
            "limit_up": 11.0,
            "limit_down": 9.0,
        }

        with patch("paper_trading.market_data.datetime") as dt_mock:
            dt_mock.now.return_value = datetime(2026, 6, 17, 10, 37, 0)
            quote = provider.get_quote("600000")

    assert quote.price == 10.8
    assert quote.open == 10.2
    assert quote.high == 10.9
    assert quote.low == 10.1
    assert quote.change_pct == 8.0
    assert quote.timestamp == "2026-06-17 10:37:00"
    assert quote.source == "tencent-qt+tencent/sina-minute-closed"


if __name__ == "__main__":
    test_latest_history_snapshot_uses_only_closed_today_bars()
    test_get_quote_recomputes_timestamp_and_change_pct_from_qt()
    print("PASS test_market_data_intraday_snapshot")
