#!/usr/bin/env python3
"""Regression checks for core A-share trading rules."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from paper_trading.engine import (  # noqa: E402
    OrderRequest,
    PaperTradingEngine,
    calc_commission,
    is_trading_time,
    market_phase,
)
from paper_trading.market_data import Quote  # noqa: E402


class FakeMarketData:
    def __init__(self, quote: Quote) -> None:
        self.quote = quote

    def normalize_symbol(self, symbol: str) -> str:
        return symbol

    def get_quote(self, symbol: str) -> Quote:
        return self.quote

    def get_quotes(self, symbols):
        return {symbol: self.quote for symbol in symbols}

    def get_intraday_bars(self, symbol: str, freq: str = "1m", count: int = 240):
        import pandas as pd

        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    def get_history(self, symbol: str, start: str | None = None, end: str | None = None, count: int = 240):
        raise NotImplementedError


def assert_raises(fn, expected_text: str) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        if expected_text not in str(exc):
            raise AssertionError(f"expected error containing {expected_text!r}, got {exc!r}") from exc
        return
    raise AssertionError(f"expected error containing {expected_text!r}")


def test_price_tick_validation() -> None:
    quote = Quote("600519", "贵州茅台", 1450.0, 1450.0, 1455.0, 1448.0, 1440.0, 1000, 0.5, "2026-04-11 10:00:00", "fake", 1584.0, 1296.0)
    with tempfile.TemporaryDirectory() as tmp:
        engine = PaperTradingEngine(str(Path(tmp) / "paper.db"), market_data=FakeMarketData(quote))
        engine.create_account("alpha", 500000)
        assert_raises(
            lambda: engine.place_order(OrderRequest(account_id="alpha", symbol="600519", side="buy", qty=100, order_type="limit", limit_price=1450.005)),
            "0.01",
        )


def test_market_phase_windows() -> None:
    monday = datetime(2026, 4, 13, 9, 20)
    assert market_phase(monday) == "opening_call_auction"
    assert is_trading_time(monday) is False
    assert market_phase(datetime(2026, 4, 13, 9, 31)) == "morning_continuous"
    assert is_trading_time(datetime(2026, 4, 13, 9, 31)) is True
    assert market_phase(datetime(2026, 4, 13, 12, 0)) == "lunch_break"
    assert market_phase(datetime(2026, 4, 13, 14, 58)) == "closing_call_auction"
    assert is_trading_time(datetime(2026, 4, 13, 14, 58)) is False


def test_stale_quote_market_order_rejected() -> None:
    stale_quote = Quote("600519", "贵州茅台", 1450.0, 1450.0, 1455.0, 1448.0, 1440.0, 1000, 0.5, "2026-04-10 15:00:00", "fake", 1584.0, 1296.0)
    with tempfile.TemporaryDirectory() as tmp:
        engine = PaperTradingEngine(str(Path(tmp) / "paper.db"), market_data=FakeMarketData(stale_quote))
        engine.create_account("alpha", 500000)
        import paper_trading.engine as engine_module

        original = engine_module.is_trading_time
        engine_module.is_trading_time = lambda dt=None: True
        try:
            assert_raises(
                lambda: engine.place_order(OrderRequest(account_id="alpha", symbol="600519", side="buy", qty=100, order_type="market")),
                "stale",
            )
        finally:
            engine_module.is_trading_time = original


def test_shanghai_transfer_fee_included() -> None:
    sh_fee = calc_commission(100000.0, "600519")
    sz_fee = calc_commission(100000.0, "000001")
    assert round(sh_fee - sz_fee, 2) == 1.0, (sh_fee, sz_fee)


if __name__ == "__main__":
    test_price_tick_validation()
    test_market_phase_windows()
    test_stale_quote_market_order_rejected()
    test_shanghai_transfer_fee_included()
    print("PASS rule_regression_check")
